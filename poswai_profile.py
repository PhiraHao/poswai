"""The shop's own identity and the money rules printed on its bills.

Until now a shop could set its name and its PromptPay number and nothing else,
so every receipt carried the same hard-coded address and tax ID — one real
shop's bill showed another company's tax number, which is worse than showing
none. Everything a receipt needs now comes from here instead.

The settings live in the shop's OWN database, not in the registry, because the
first shop ("main") has no registry row at all and would otherwise be the one
shop that can never be configured. One row, one column per setting, so a shop
opened before this existed reads the defaults and keeps working.

Money is counted in satang as whole numbers from end to end. A bill that adds
7% VAT to 333.33 baht in floating point lands a satang away from what the
customer is charged, and that satang turns up months later as a till that will
not balance.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any, Iterable

# Thai VAT has been 7% for the whole life of every shop that will use this,
# but a rate belongs in the shop's settings, not in the code that prints bills.
DEFAULT_VAT_BP = 700
# Rates are kept in basis points (700 = 7.00%) so a half-percent service charge
# is expressible without a float ever touching the money.
MAX_RATE_BP = 10000

TAX_EXEMPT = "none"  # a menu item's own tax_mode, meaning VAT never applies to it

# What the shop actually sells. It decides the words on the screens and which
# of them a shop ever opens — a clothes shop has no kitchen to watch and no
# tables to seat anyone at, and being shown both is how an owner concludes the
# software was not meant for them.
#
# It changes wording and visibility only. Nothing is deleted when a shop
# switches, because a shop that tries "ค้าปลีก" for an afternoon and goes back
# must find its tables and its recipes still there.
BUSINESS_TYPES = {
    "restaurant": {
        "label": "ร้านอาหาร / คาเฟ่",
        "tabs_hidden": [],
        "words": {"sell": "สั่งอาหาร", "sell_hint": "เมนูและตะกร้า", "item": "เมนู",
                  "items": "เมนูอาหาร", "seat": "โต๊ะ", "stock": "วัตถุดิบและสูตร",
                  "workspace": "ร้านอาหาร",
                  "tagline": "ระบบจัดการร้านอาหารผ่าน LINE OA ใช้ได้แม้เน็ตหลุด",
                  "seats_hint": "โต๊ะและการชำระเงิน", "stock_title": "สต็อกและสูตรอาหาร"},
    },
    "retail": {
        "label": "ร้านค้า / ขายสินค้า",
        # No kitchen to watch: the thing is on the shelf, it is handed over.
        "tabs_hidden": ["kitchen"],
        "words": {"sell": "ขายสินค้า", "sell_hint": "สินค้าและตะกร้า", "item": "สินค้า",
                  "items": "รายการสินค้า", "seat": "ช่องขาย", "stock": "สต็อกสินค้า",
                  "workspace": "ร้านค้า",
                  "tagline": "ระบบขายหน้าร้าน ใช้ได้แม้เน็ตหลุด",
                  "seats_hint": "ช่องขายและการชำระเงิน", "stock_title": "สต็อกสินค้า"},
    },
    "service": {
        "label": "ร้านบริการ / รับงาน",
        "tabs_hidden": ["kitchen"],
        "words": {"sell": "เปิดบิล", "sell_hint": "บริการและตะกร้า", "item": "บริการ",
                  "items": "รายการบริการ", "seat": "คิว", "stock": "ของใช้ในร้าน",
                  "workspace": "ร้านบริการ",
                  "tagline": "ระบบเปิดบิลรับงาน ใช้ได้แม้เน็ตหลุด",
                  "seats_hint": "คิวและการชำระเงิน", "stock_title": "ของใช้ในร้าน"},
    },
}
DEFAULT_BUSINESS_TYPE = "restaurant"


class ProfileError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


# name -> (SQL type and default, python caster). Adding a setting here is the
# whole job: the table widens itself on open and the API passes it through.
FIELDS: dict[str, tuple[str, str]] = {
    "business_type": (f"TEXT NOT NULL DEFAULT '{DEFAULT_BUSINESS_TYPE}'", "business_type"),
    "legal_name": ("TEXT NOT NULL DEFAULT ''", "text"),
    "address": ("TEXT NOT NULL DEFAULT ''", "text"),
    "phone": ("TEXT NOT NULL DEFAULT ''", "text"),
    "tax_id": ("TEXT NOT NULL DEFAULT ''", "tax_id"),
    # What the Revenue Department calls this address: the head office, or a
    # numbered branch. A full tax invoice has to say which, and a shop that
    # leaves it blank is the head office, which is almost always true.
    "tax_branch": ("TEXT NOT NULL DEFAULT ''", "text"),
    "vat_rate_bp": ("INTEGER NOT NULL DEFAULT 0", "rate"),
    "vat_inclusive": ("INTEGER NOT NULL DEFAULT 1", "flag"),
    "service_charge_bp": ("INTEGER NOT NULL DEFAULT 0", "rate"),
    "receipt_header": ("TEXT NOT NULL DEFAULT ''", "text"),
    "receipt_footer": ("TEXT NOT NULL DEFAULT ''", "text"),
}
TEXT_LIMITS = {"legal_name": 120, "address": 200, "phone": 30,
               "receipt_header": 120, "receipt_footer": 200, "tax_branch": 60}
# The two fields a shop writes as a block, where the line breaks are the point:
# an address and a closing message are printed the way they were typed. Every
# other field is one line, so stray spacing in it is collapsed.
MULTILINE = frozenset({"address", "receipt_footer"})


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create the one-row settings table, widening it for older shops."""
    conn.execute("CREATE TABLE IF NOT EXISTS shop_profile (id INTEGER PRIMARY KEY CHECK (id = 1))")
    have = {row[1] for row in conn.execute("PRAGMA table_info(shop_profile)")}
    for name, (sql_type, _) in FIELDS.items():
        if name not in have:
            conn.execute(f"ALTER TABLE shop_profile ADD COLUMN {name} {sql_type}")
    conn.execute("INSERT OR IGNORE INTO shop_profile (id) VALUES (1)")


def read(conn: sqlite3.Connection) -> dict[str, Any]:
    ensure_schema(conn)
    columns = ",".join(FIELDS)
    row = conn.execute(f"SELECT {columns} FROM shop_profile WHERE id=1").fetchone()
    profile = dict(zip(FIELDS, row))
    profile["vat_inclusive"] = bool(profile["vat_inclusive"])
    # A database edited by hand, or written by a build that knew another type,
    # must not leave the screens with no words at all.
    if profile["business_type"] not in BUSINESS_TYPES:
        profile["business_type"] = DEFAULT_BUSINESS_TYPE
    profile["business"] = BUSINESS_TYPES[profile["business_type"]]
    return profile


def save(conn: sqlite3.Connection, changes: dict[str, Any]) -> dict[str, Any]:
    """Store only the settings the owner actually sent, validated."""
    ensure_schema(conn)
    clean: dict[str, Any] = {}
    for name, value in changes.items():
        if value is None:
            continue
        if name not in FIELDS:
            raise ProfileError(f"ไม่รู้จักการตั้งค่า {name}")
        clean[name] = _cast(name, value)
    if clean:
        assignments = ",".join(f"{name}=?" for name in clean)
        conn.execute(f"UPDATE shop_profile SET {assignments} WHERE id=1", tuple(clean.values()))
    return read(conn)


def _cast(name: str, value: Any) -> Any:
    kind = FIELDS[name][1]
    if kind == "business_type":
        if value not in BUSINESS_TYPES:
            raise ProfileError("ประเภทธุรกิจไม่ถูกต้อง")
        return value
    if kind == "text":
        text = str(value).strip() if name in MULTILINE else " ".join(str(value).split())
        limit = TEXT_LIMITS[name]
        if len(text) > limit:
            raise ProfileError(f"ข้อความยาวเกิน {limit} ตัวอักษร")
        return text
    if kind == "tax_id":
        digits = re.sub(r"[\s-]", "", str(value))
        if digits and not valid_tax_id(digits):
            raise ProfileError("เลขประจำตัวผู้เสียภาษีต้องเป็นตัวเลข 13 หลักที่ถูกต้อง")
        return digits
    if kind == "flag":
        return 1 if value not in (0, "0", False, "false", "") else 0
    # rate
    try:
        rate = int(round(float(value)))
    except (TypeError, ValueError) as exc:
        raise ProfileError("อัตราต้องเป็นตัวเลข") from exc
    if not 0 <= rate <= MAX_RATE_BP:
        raise ProfileError("อัตราต้องอยู่ระหว่าง 0 ถึง 100%")
    return rate


def valid_tax_id(digits: str) -> bool:
    """Thai 13-digit tax/ID number, check digit included.

    A typo in a tax number is invisible on a receipt but makes the document
    useless to the customer's accountant, and the shop only finds out at the
    end of the year. The checksum catches almost every single-digit slip.
    """
    if not re.fullmatch(r"\d{13}", digits):
        return False
    total = sum(int(digit) * (13 - position) for position, digit in enumerate(digits[:12]))
    return (11 - total % 11) % 10 == int(digits[12])


def split_discount(line_cents: list[int], discount_cents: int) -> list[int]:
    """Spread a bill-wide discount over the lines, to the exact satang.

    Needed because the service charge and VAT are worked out per line: a 100
    baht discount on a bill where only the food carries service charge has to
    take its share off the food. Largest remainder keeps the parts summing to
    the whole, so the discount shown never disagrees with the lines.
    """
    subtotal = sum(line_cents)
    if discount_cents <= 0 or subtotal <= 0:
        return [0] * len(line_cents)
    discount_cents = min(discount_cents, subtotal)
    exact = [cents * discount_cents / subtotal for cents in line_cents]
    shares = [int(value) for value in exact]
    for index in sorted(range(len(exact)), key=lambda i: exact[i] - shares[i], reverse=True)[
            :discount_cents - sum(shares)]:
        shares[index] += 1
    return shares


def bill(lines: Iterable[dict], *, profile: dict, discount_cents: int = 0) -> dict:
    """Work out what the customer actually pays, line by line.

    ``lines`` each give ``cents`` (quantity already multiplied in), whether the
    line carries ``service_charge``, and the menu item's own ``tax_mode``.

    The shop's settings decide the VAT: one rate, and whether menu prices
    already contain it. A menu item's tax_mode only matters when it is
    ``none`` — that is how a shop marks the few things VAT never applies to —
    because two places to set "is this price with or without VAT" is two places
    for an owner to contradict themselves.

    Service charge is taxed the same way the shop's prices are, which is what
    the Revenue Department expects and what every other POS prints.
    """
    lines = list(lines)
    line_cents = [int(line["cents"]) for line in lines]
    if any(cents < 0 for cents in line_cents):
        raise ProfileError("ยอดต่อรายการติดลบไม่ได้")
    subtotal = sum(line_cents)
    discount_cents = max(0, min(int(discount_cents), subtotal))
    shares = split_discount(line_cents, discount_cents)
    net = [cents - share for cents, share in zip(line_cents, shares)]

    sc_bp = int(profile.get("service_charge_bp") or 0)
    service_cents = 0
    charged_lines = []
    for line, amount in zip(lines, net):
        line_service = round(amount * sc_bp / 10000) if line.get("service_charge") else 0
        service_cents += line_service
        charged_lines.append((line, amount + line_service))

    vat_bp = int(profile.get("vat_rate_bp") or 0)
    inclusive = bool(profile.get("vat_inclusive", True))
    vat_cents = 0
    added_cents = 0
    for line, amount in charged_lines:
        if not vat_bp or line.get("tax_mode") == TAX_EXEMPT:
            continue
        if inclusive:
            # The price already contains the tax; pull out the portion that is
            # tax so the receipt can name it. The total does not move.
            vat_cents += amount - round(amount * 10000 / (10000 + vat_bp))
        else:
            share = round(amount * vat_bp / 10000)
            vat_cents += share
            added_cents += share

    total = subtotal - discount_cents + service_cents + added_cents
    return {"subtotal_cents": subtotal, "discount_cents": discount_cents,
            "service_charge_cents": service_cents, "vat_cents": vat_cents,
            "vat_inclusive": inclusive, "vat_rate_bp": vat_bp,
            "service_charge_bp": sc_bp, "total_cents": total}


def change_for(total_cents: int, paid_cents: int) -> int:
    """How much goes back to the customer, or a refusal if they are short.

    The till used to leave this to whoever was standing at it. Counting it here
    means the amount tendered is recorded with the sale, which is the only way
    a shift's cash can ever be checked against its sales.
    """
    if paid_cents < total_cents:
        raise ProfileError("เงินที่รับมาน้อยกว่ายอดที่ต้องจ่าย")
    return paid_cents - total_cents
