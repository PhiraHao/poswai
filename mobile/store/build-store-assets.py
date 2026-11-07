"""Google Play images for POS WAI, from the shop's own assets.

  python mobile/store/build-store-assets.py

  out/icon-512.png        the app icon (the owner's POS WAI tile, full bleed)
  out/feature-1024x500.png the banner at the top of the listing
  out/phone-*.png         screenshots: the raw phone shots in screens/ with the
                          phone's status and navigation bars trimmed, so each is
                          within Play's 2:1 limit

The screenshots in screens/ are the real app on a phone with sample dishes held
in memory only (see README "Play Store"); nothing in them is drawn by hand.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent
ASSETS = HERE.parent.parent / "assets"
OUT = HERE / "out"
CREAM = (250, 246, 238)
INK = (23, 35, 34)
FONT_BOLD = "C:/Windows/Fonts/LeelaUIb.ttf"
FONT = "C:/Windows/Fonts/LeelawUI.ttf"


def icon() -> None:
    """The lettering on the icon's cream, edge to edge: Play rounds the corners itself."""
    art = Image.open(ASSETS / "brand-icon-art.webp").convert("RGBA")
    canvas = Image.new("RGBA", (512, 512), CREAM + (255,))
    art.thumbnail((400, 400), Image.LANCZOS)
    canvas.alpha_composite(art, ((512 - art.width) // 2, (512 - art.height) // 2))
    canvas.convert("RGB").save(OUT / "icon-512.png")


def feature() -> None:
    width, height = 1024, 500
    canvas = Image.new("RGB", (width, height), CREAM)
    draw = ImageDraw.Draw(canvas)
    # A warm band behind the mascot.
    for x in range(width):
        t = max(0.0, (x - 520) / (width - 520))
        colour = tuple(int(CREAM[i] + (c - CREAM[i]) * t) for i, c in enumerate((255, 214, 92)))
        draw.line([(x, 0), (x, height)], fill=colour)
    art = Image.open(ASSETS / "brand-icon-art.webp").convert("RGBA")
    art.thumbnail((300, 180), Image.LANCZOS)
    canvas.paste(art, (60, 70), art)
    big = ImageFont.truetype(FONT_BOLD, 46)
    small = ImageFont.truetype(FONT, 28)
    draw.text((62, 280), "ระบบขายหน้าร้าน", font=big, fill=INK)
    draw.text((62, 336), "สำหรับร้านอาหาร", font=big, fill=INK)
    draw.text((64, 408), "ขาย · ครัว · รับเงิน · ใบเสร็จ · ใช้ได้แม้เน็ตหลุด", font=small, fill=(90, 98, 104))
    mascot = Image.open(ASSETS / "mascot-pos.webp").convert("RGBA")
    mascot.thumbnail((440, 440), Image.LANCZOS)
    canvas.paste(mascot, (width - mascot.width - 30, height - mascot.height - 20), mascot)
    canvas.save(OUT / "feature-1024x500.png")


def screenshots() -> None:
    """Trim the phone's own bars: 1080x2340 → about 1080x2060 (Play allows up to 2:1)."""
    for source in sorted((HERE / "screens").glob("*.png")):
        shot = Image.open(source).convert("RGB")
        top = round(shot.height * 0.026)        # status bar
        bottom = round(shot.height * 0.094)     # Android's back/home/recent bar
        trimmed = shot.crop((0, top, shot.width, shot.height - bottom))
        assert trimmed.height <= 2 * trimmed.width, source.name
        trimmed.save(OUT / f"phone-{source.stem}.png")


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    icon()
    feature()
    screenshots()
    print("\n".join(sorted(p.name for p in OUT.iterdir())))
