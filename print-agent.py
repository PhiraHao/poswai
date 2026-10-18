"""POS WAI print agent — run this on the machine the receipt printer is plugged into.

The till in a small shop is a phone, and a phone cannot drive a 58mm USB or
Bluetooth printer: iOS has no Web Bluetooth and these printers have no
AirPrint. So the phone does not print. It leaves the receipt with POS WAI, and
this program — running on the computer or tablet the printer IS plugged into —
collects it and prints it. Every device in the shop then prints to one printer.

Thai is drawn as a picture rather than sent as text. The cheap 58mm printers
carry a Chinese character set and a Thai code page that may or may not be the
one the shop needs; a bitmap of real Thai letters always comes out right.

    python print-agent.py            first run asks what it needs and saves it
    python print-agent.py --once     collect and print anything waiting, then stop
    python print-agent.py --test     print a test slip and stop

Needs: Pillow (pip install pillow), and on Windows pywin32 (pip install pywin32).
"""

from __future__ import annotations

import argparse
import configparser
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CONFIG_PATH = Path(__file__).with_name("print-agent.ini")
PAPER_DOTS = 384          # 58mm paper, 203 dpi
# How many dot rows go in one image command. Small enough that the printer
# keeps up with the data, large enough that a receipt is not thousands of
# commands. 24 rows is the size these printers are happiest with.
BAND_ROWS = 24
POLL_SECONDS = 3
ERROR_BACKOFF_SECONDS = 15
THAI_FONTS = (
    r"C:\Windows\Fonts\tahoma.ttf",
    r"C:\Windows\Fonts\leelawui.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansThai-Regular.ttf",
    "/Library/Fonts/Thonburi.ttc",
    "/System/Library/Fonts/Supplemental/Ayuthaya.ttf",
)


# --------------------------------------------------------------- what to print
# A Thai vowel or tone mark sits on the letter before it and has no width of
# its own. Starting a line with one leaves it stacked on nothing, which is how
# "โต๊ะ 1 | วันที่ ..." came out of the printer as scattered marks.
THAI_MARKS = frozenset("ัิีึืฺุู"
                       "็่้๊๋์ํ๎")


def wrap(line: str, fits) -> list[str]:
    """Break a too-long line at spaces, and inside a word only between letters.

    Thai writes without spaces, so a long run of it has to be broken somewhere;
    what must never happen is breaking a letter away from the marks that belong
    on top of it.
    """
    pieces: list[str] = []
    current = ""
    for word in re.split(r"(\s+)", line):
        if not word:
            continue
        if fits(current + word):
            current += word
            continue
        if current.strip():
            pieces.append(current.rstrip())
            current = ""
        if word.isspace():
            continue
        for char in word:
            if current and char not in THAI_MARKS and not fits(current + char):
                pieces.append(current)
                current = ""
            current += char
    if current.strip():
        pieces.append(current.rstrip())
    return pieces or [""]


def render(text: str, font_path: str, size: int = 22) -> bytes:
    """The receipt as ESC/POS raster, so Thai looks like Thai."""
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.truetype(font_path, size)
    pad, line_height = 6, size + 7
    room = PAPER_DOTS - 2 * pad
    measure = ImageDraw.Draw(Image.new("L", (1, 1)))
    fits = lambda piece: measure.textlength(piece, font=font) <= room

    lines: list[str] = []
    for raw in text.replace("\r", "").split("\n"):
        if fits(raw) or not raw.strip():
            lines.append(raw)
            continue
        # Too wide for the paper: break it rather than let the printer clip it.
        for piece in wrap(raw, fits):
            lines.append(piece)

    height = max(line_height, line_height * len(lines) + 2 * pad)
    image = Image.new("L", (PAPER_DOTS, height), 255)
    draw = ImageDraw.Draw(image)
    for index, line in enumerate(lines):
        draw.text((pad, pad + index * line_height), line, font=font, fill=0)
    mono = image.point(lambda value: 0 if value < 160 else 255, mode="1")

    width_bytes = PAPER_DOTS // 8
    pixels = mono.load()

    def band(top: int, rows: int) -> bytes:
        out = bytearray([0x1D, 0x76, 0x30, 0x00,
                         width_bytes & 0xFF, width_bytes >> 8,
                         rows & 0xFF, rows >> 8])
        for y in range(top, top + rows):
            for byte_index in range(width_bytes):
                byte = 0
                for bit in range(8):
                    # In ESC/POS a set bit burns a dot, which is the opposite
                    # of the image, where 0 is black.
                    if not pixels[byte_index * 8 + bit, y]:
                        byte |= 0x80 >> bit
                out.append(byte)
        return bytes(out)

    # One tall image in a single command overruns these printers: somewhere in
    # the middle a band of rows comes out as noise, and which band moves with
    # the length of the receipt. Printing it as a stack of short images gives
    # the head time to keep up, and each one stands on its own.
    picture = b"".join(band(top, min(BAND_ROWS, height - top))
                       for top in range(0, height, BAND_ROWS))
    return b"\x1b@" + picture + b"\n\n\n\n\x1dV\x00"


# ------------------------------------------------------------- where it goes
def send(data: bytes, target: str) -> None:
    """`windows:<printer name>` for an installed driver, `file:<path>` otherwise."""
    kind, _, where = target.partition(":")
    if kind == "file":
        with open(where, "wb") as device:
            device.write(data)
        return
    if kind != "windows":
        raise SystemExit(f"ไม่รู้จักปลายทาง {target!r} (ใช้ windows:ชื่อเครื่องพิมพ์ หรือ file:พาธ)")
    import win32print

    handle = win32print.OpenPrinter(where)
    try:
        job = win32print.StartDocPrinter(handle, 1, ("POS WAI receipt", None, "RAW"))
        try:
            win32print.StartPagePrinter(handle)
            win32print.WritePrinter(handle, data)
            win32print.EndPagePrinter(handle)
        finally:
            win32print.EndDocPrinter(handle)
    finally:
        win32print.ClosePrinter(handle)


def windows_printers() -> list[str]:
    try:
        import win32print
    except ImportError:
        return []
    return [row[2] for row in win32print.EnumPrinters(
        win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS)]


# ------------------------------------------------------------------ the shop
class Shop:
    def __init__(self, base_url: str, shop: str, key: str):
        self.base = base_url.rstrip("/")
        self.shop = shop
        self.key = key

    def _call(self, path: str, body: dict | None = None) -> dict:
        url = f"{self.base}{path}"
        url += ("&" if "?" in url else "?") + "shop=" + urllib.parse.quote(self.shop)
        request = urllib.request.Request(url, headers={"X-Print-Key": self.key})
        if body is not None:
            request.data = json.dumps(body).encode()
            request.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode() or "{}")

    def next_job(self) -> dict | None:
        return self._call("/api/print/next").get("job")

    def done(self, job_id: int) -> None:
        self._call("/api/print/done", {"job_id": job_id})


# --------------------------------------------------------------- setting up
def ask_settings() -> configparser.ConfigParser:
    print("ตั้งค่าตัวกลางพิมพ์ POS WAI (กด Enter เพื่อใช้ค่าในวงเล็บ)\n")
    base = input("ที่อยู่เว็บ [https://poswai.zzaxstudio.com]: ").strip() or "https://poswai.zzaxstudio.com"
    shop = input("ชื่อร้านในลิงก์ เช่น guohao: ").strip()
    key = input("กุญแจเครื่องพิมพ์ (จากหน้าแคชเชียร์ > เครื่องที่เสียบปริ้นเตอร์ไว้): ").strip()

    printers = windows_printers()
    if printers:
        print("\nเครื่องพิมพ์ที่เจอในเครื่องนี้:")
        for index, name in enumerate(printers, 1):
            print(f"  {index}. {name}")
        chosen = input("เลือกหมายเลข (หรือพิมพ์ชื่อเอง): ").strip()
        name = printers[int(chosen) - 1] if chosen.isdigit() and 1 <= int(chosen) <= len(printers) else chosen
        target = f"windows:{name}"
    else:
        target = input("ปลายทาง เช่น file:/dev/usb/lp0: ").strip()

    font = next((path for path in THAI_FONTS if Path(path).exists()), "")
    if not font:
        font = input("ยังไม่เจอฟอนต์ไทย ใส่พาธไฟล์ .ttf: ").strip()

    settings = configparser.ConfigParser()
    settings["agent"] = {"base_url": base, "shop": shop, "key": key,
                         "target": target, "font": font, "font_size": "22"}
    with CONFIG_PATH.open("w", encoding="utf-8") as handle:
        settings.write(handle)
    print(f"\nบันทึกไว้ที่ {CONFIG_PATH} แล้ว · แก้ไฟล์นี้ได้ถ้าต้องเปลี่ยนทีหลัง\n")
    return settings


def load_settings() -> configparser.SectionProxy:
    settings = configparser.ConfigParser()
    if CONFIG_PATH.exists():
        settings.read(CONFIG_PATH, encoding="utf-8")
    else:
        settings = ask_settings()
    section = settings["agent"]
    missing = [name for name in ("base_url", "shop", "key", "target", "font") if not section.get(name)]
    if missing:
        raise SystemExit(f"ไฟล์ {CONFIG_PATH} ยังขาด: {', '.join(missing)}")
    return section


# ------------------------------------------------------------------- running
def print_text(text: str, section: configparser.SectionProxy) -> None:
    send(render(text, section["font"], int(section.get("font_size", "22"))), section["target"])


def main() -> None:
    parser = argparse.ArgumentParser(description="ตัวกลางพิมพ์ใบเสร็จของ POS WAI")
    parser.add_argument("--once", action="store_true", help="พิมพ์ที่ค้างอยู่แล้วจบ")
    parser.add_argument("--test", action="store_true", help="พิมพ์ใบทดสอบแล้วจบ")
    arguments = parser.parse_args()
    # Python holds back prints when this runs from a script or a service
    # rather than a console, and a silent window looks like a dead program.
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
    section = load_settings()

    if arguments.test:
        print_text("   ทดสอบเครื่องพิมพ์\n   POS WAI\n"
                   "--------------------------------\n"
                   "กะเพราหมูสับ      x1   ฿50.00\n"
                   "ชาเย็น            x2   ฿50.00\n"
                   "--------------------------------\n"
                   "รวม                    ฿100.00\n"
                   "   ขอบคุณที่ใช้บริการครับ", section)
        print("ส่งใบทดสอบไปที่เครื่องพิมพ์แล้ว")
        return

    shop = Shop(section["base_url"], section["shop"], section["key"])
    refused = 0
    print(f"กำลังรอใบเสร็จจาก {section['base_url']} ร้าน {section['shop']}")
    print("ปิดโปรแกรมด้วย Ctrl+C\n")
    while True:
        try:
            job = shop.next_job()
            if not job:
                if arguments.once:
                    print("ไม่มีใบรอพิมพ์")
                    return
                time.sleep(POLL_SECONDS)
                continue
            for _ in range(max(1, int(job.get("copies", 1)))):
                print_text(job["body"], section)
            shop.done(job["job_id"])
            refused = 0
            print(f"พิมพ์แล้ว: {job.get('title') or job['job_id']}")
        except KeyboardInterrupt:
            print("\nหยุดแล้ว")
            return
        except urllib.error.HTTPError as error:
            if error.code == 401:
                # A shop that reissues its key mid-service, or a server
                # restarting, must not leave the counter with no printer for
                # the rest of the day. Say so loudly and keep asking: the fix
                # is to paste the new key in, and this picks it up by itself.
                refused += 1
                print(f"กุญแจเครื่องพิมพ์ใช้ไม่ได้ (ครั้งที่ {refused}) · "
                      f"แก้ key ในไฟล์ {CONFIG_PATH.name} แล้วรอสักครู่ เดี๋ยวลองใหม่ให้เอง",
                      file=sys.stderr)
                section = load_settings()
                shop = Shop(section["base_url"], section["shop"], section["key"])
                time.sleep(ERROR_BACKOFF_SECONDS)
                continue
            print(f"เซิร์ฟเวอร์ตอบ {error.code} · รอแล้วลองใหม่", file=sys.stderr)
            time.sleep(ERROR_BACKOFF_SECONDS)
        except Exception as error:                       # noqa: BLE001 - keep printing
            # A jam, a pulled cable or a dropped Wi-Fi must not end the shift.
            print(f"ผิดพลาด: {error} · รอแล้วลองใหม่", file=sys.stderr)
            time.sleep(ERROR_BACKOFF_SECONDS)


if __name__ == "__main__":
    main()
