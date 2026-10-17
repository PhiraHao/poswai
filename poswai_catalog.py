"""Server-owned restaurant menu, order quotation, and atomic BOM consumption.

The caller owns the SQLite transaction. Never accept a submitted item's name,
price, or BOM as authority; those values are loaded from this catalog instead.
No example products are seeded into a live branch automatically.
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any


class CatalogError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


STATIONS = ("ครัวร้อน", "ครัวเย็น/ยำ", "บาร์น้ำ")
# How the shop's printed price relates to tax, so the bill can be explained.
TAX_MODES = ("included", "excluded", "none")
# Columns added after the first release. Each is widened in place on open so an
# existing shop's database keeps working without a migration step.
ADDED_COLUMNS = (
    ("station", "TEXT NOT NULL DEFAULT 'ครัวร้อน'"),
    ("category", "TEXT NOT NULL DEFAULT ''"),
    ("description", "TEXT NOT NULL DEFAULT ''"),
    ("cost_cents", "INTEGER NOT NULL DEFAULT 0"),
    ("photo", "TEXT NOT NULL DEFAULT ''"),
    ("tax_mode", "TEXT NOT NULL DEFAULT 'included'"),
    ("service_charge", "INTEGER NOT NULL DEFAULT 0"),
    ("sold_out", "INTEGER NOT NULL DEFAULT 0"),
    ("option_title", "TEXT NOT NULL DEFAULT ''"),
    ("levels_json", "TEXT NOT NULL DEFAULT '[]'"),
    ("addons_json", "TEXT NOT NULL DEFAULT '[]'"),
)
MENU_COLUMNS = ("item_id,name,price_cents,bom_json,active,station,category,description,"
                "cost_cents,photo,tax_mode,service_charge,sold_out,option_title,"
                "levels_json,addons_json")


def _positive_decimal(value: Any, field: str, *, allow_zero: bool = False) -> Decimal:
    if isinstance(value, bool):
        raise CatalogError(f"Invalid {field}")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise CatalogError(f"Invalid {field}") from None
    if not result.is_finite() or result < 0 or (not allow_zero and result == 0):
        raise CatalogError(f"Invalid {field}")
    return result


def _money_cents(value: Any) -> int:
    amount = _positive_decimal(value, "price", allow_zero=True)
    cents = amount * 100
    if cents != cents.to_integral_value() or cents > 100_000_000:
        raise CatalogError("Price must have at most two decimals and be at most 1,000,000")
    return int(cents)


def _branch(branch_id: Any) -> int:
    if isinstance(branch_id, bool):
        raise CatalogError("Invalid branch")
    try:
        result = int(branch_id)
    except (TypeError, ValueError):
        raise CatalogError("Invalid branch") from None
    if result < 1 or str(result) != str(branch_id):
        raise CatalogError("Invalid branch")
    return result


def _item_id(value: Any) -> str:
    if isinstance(value, bool):
        raise CatalogError("Invalid item id")
    result = str(value).strip()
    if not result or len(result) > 80:
        raise CatalogError("Invalid item id")
    return result


def _validated_bom(bom: Any) -> list[dict]:
    if not isinstance(bom, list) or len(bom) > 100:
        raise CatalogError("Invalid BOM")
    amounts: dict[str, Decimal] = defaultdict(Decimal)
    for part in bom:
        if not isinstance(part, dict):
            raise CatalogError("Invalid BOM part")
        ingredient = str(part.get("ingId", "")).strip()
        if not ingredient or len(ingredient) > 80 or ingredient == "NONE":
            raise CatalogError("Invalid ingredient id")
        amount = _positive_decimal(part.get("qty"), "BOM quantity")
        if amount > 1_000_000 or amount.as_tuple().exponent < -6:
            raise CatalogError("Invalid BOM quantity")
        amounts[ingredient] += amount
    return [{"ingId": key, "qty": float(value)} for key, value in sorted(amounts.items())]


def _text(value: Any, field: str, limit: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise CatalogError(f"Invalid {field}")
    result = value.strip()
    if len(result) > limit:
        raise CatalogError(f"{field} is too long")
    return result


def _flag(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise CatalogError(f"Invalid {field}")
    return value


def _signed_cents(value: Any, field: str) -> int:
    """A topping may lower the price (bring your own cup), so allow negatives."""
    if isinstance(value, bool):
        raise CatalogError(f"Invalid {field}")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise CatalogError(f"Invalid {field}") from None
    cents = amount * 100
    if not amount.is_finite() or cents != cents.to_integral_value() or abs(cents) > 1_000_000:
        raise CatalogError(f"{field} must have at most two decimals and be within 10,000")
    return int(cents)


def _validated_levels(levels: Any) -> list[str]:
    """Sweetness or spice choices. They never change the price."""
    if not isinstance(levels, list) or len(levels) > 12:
        raise CatalogError("Invalid option list")
    result = []
    for level in levels:
        name = _text(level, "option", 80)
        if not name:
            raise CatalogError("An option cannot be blank")
        if name in result:
            raise CatalogError(f"Option {name} is listed twice")
        result.append(name)
    return result


def _validated_addons(addons: Any) -> list[dict]:
    """Toppings, each with its own price and its own share of the stock."""
    if not isinstance(addons, list) or len(addons) > 30:
        raise CatalogError("Invalid topping list")
    result, seen = [], set()
    for addon in addons:
        if not isinstance(addon, dict):
            raise CatalogError("Invalid topping")
        name = _text(addon.get("name"), "topping name", 80)
        if not name:
            raise CatalogError("A topping cannot be blank")
        if name in seen:
            raise CatalogError(f"Topping {name} is listed twice")
        seen.add(name)
        ingredient = str(addon.get("ingId", "NONE")).strip() or "NONE"
        if len(ingredient) > 80:
            raise CatalogError("Invalid ingredient id")
        amount = Decimal("0")
        if ingredient != "NONE":
            amount = _positive_decimal(addon.get("qty"), "topping quantity", allow_zero=True)
            if amount > 1_000_000 or amount.as_tuple().exponent < -6:
                raise CatalogError("Invalid topping quantity")
            if amount == 0:
                ingredient = "NONE"   # nothing to deduct, so do not pin an ingredient
        # A stored row already carries exact cents; a submitted form carries
        # baht. Re-validating a stored row must read its own field, or the
        # price silently becomes zero the next time the dish is ordered.
        raw_cents = addon.get("price_cents")
        if isinstance(raw_cents, int) and not isinstance(raw_cents, bool):
            if abs(raw_cents) > 1_000_000:
                raise CatalogError("topping price must be within 10,000")
            price_cents = raw_cents
        else:
            price_cents = _signed_cents(addon.get("price", 0), "topping price")
        result.append({"name": name, "price_cents": price_cents,
                       "ingId": ingredient, "qty": float(amount)})
    return result


def _addon_out(addon: dict) -> dict:
    return {"name": addon["name"], "price": addon["price_cents"] / 100,
            "ingId": addon["ingId"], "qty": addon["qty"]}


def init_catalog(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS menu_catalog (
        branch_id INTEGER NOT NULL,
        item_id TEXT NOT NULL,
        name TEXT NOT NULL,
        price_cents INTEGER NOT NULL CHECK(price_cents >= 0),
        bom_json TEXT NOT NULL DEFAULT '[]',
        active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (branch_id,item_id)
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS menu_catalog_active ON menu_catalog(branch_id,active)")
    columns = {row[1] for row in conn.execute("PRAGMA table_info(menu_catalog)")}
    for column, definition in ADDED_COLUMNS:
        if column not in columns:
            conn.execute(f"ALTER TABLE menu_catalog ADD COLUMN {column} {definition}")


def upsert_menu_item(
    conn: sqlite3.Connection, branch_id: int, item_id: str | int,
    name: str, price: Any, bom: list[dict], active: bool = True, station: str = "ครัวร้อน",
    *, category: Any = "", description: Any = "", cost: Any = 0, photo: Any = None,
    tax_mode: str = "included", service_charge: bool = False, sold_out: bool = False,
    option_title: Any = "", levels: Any = None, addons: Any = None,
) -> dict:
    """Write one menu item. ``photo`` of None keeps whatever photo is on file,
    because the picture is uploaded by its own endpoint, not by this form."""
    branch_id, item_id = _branch(branch_id), _item_id(item_id)
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 200:
        raise CatalogError("Invalid item name")
    if station not in STATIONS:
        raise CatalogError("Invalid kitchen station")
    if tax_mode not in TAX_MODES:
        raise CatalogError("Invalid tax mode")
    active, service_charge = _flag(active, "active flag"), _flag(service_charge, "service charge flag")
    sold_out = _flag(sold_out, "sold out flag")
    cents, canonical_bom = _money_cents(price), _validated_bom(bom)
    cost_cents = _money_cents(cost)
    category, description = _text(category, "category", 60), _text(description, "description", 500)
    option_title = _text(option_title, "option title", 120)
    canonical_levels = _validated_levels([] if levels is None else levels)
    canonical_addons = _validated_addons([] if addons is None else addons)
    kept_photo = conn.execute(
        "SELECT photo FROM menu_catalog WHERE branch_id=? AND item_id=?",
        (branch_id, item_id)).fetchone()
    photo = (kept_photo[0] if kept_photo else "") if photo is None else _text(photo, "photo", 300)
    conn.execute("""INSERT INTO menu_catalog
        (branch_id,item_id,name,price_cents,bom_json,active,station,category,description,
         cost_cents,photo,tax_mode,service_charge,sold_out,option_title,levels_json,addons_json)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(branch_id,item_id) DO UPDATE SET
        name=excluded.name,price_cents=excluded.price_cents,bom_json=excluded.bom_json,
        active=excluded.active,station=excluded.station,category=excluded.category,
        description=excluded.description,cost_cents=excluded.cost_cents,photo=excluded.photo,
        tax_mode=excluded.tax_mode,service_charge=excluded.service_charge,sold_out=excluded.sold_out,
        option_title=excluded.option_title,levels_json=excluded.levels_json,
        addons_json=excluded.addons_json,updated_at=CURRENT_TIMESTAMP""",
        (branch_id, item_id, name.strip(), cents, json.dumps(canonical_bom), int(active), station,
         category, description, cost_cents, photo, tax_mode, int(service_charge), int(sold_out),
         option_title, json.dumps(canonical_levels, ensure_ascii=False),
         json.dumps(canonical_addons, ensure_ascii=False)))
    return {"branch_id": branch_id, "id": item_id, "name": name.strip(),
            "price": cents / 100, "bom": canonical_bom, "active": active, "station": station,
            "category": category, "description": description, "cost": cost_cents / 100,
            "photo": photo, "tax_mode": tax_mode, "service_charge": service_charge,
            "sold_out": sold_out, "option_title": option_title, "levels": canonical_levels,
            "addons": [_addon_out(addon) for addon in canonical_addons]}


def set_menu_status(conn: sqlite3.Connection, branch_id: int, item_id: str,
                    active: Any = None, sold_out: Any = None) -> dict:
    """Flip whether a dish is on the menu, or has run out, and nothing else.

    A dish runs out in the middle of service. Saving the whole form back would
    carry whatever is on screen with it, so availability moves on its own.
    """
    branch_id, item_id = _branch(branch_id), _item_id(item_id)
    fields, values = [], []
    if active is not None:
        fields.append("active=?")
        values.append(int(_flag(active, "active flag")))
    if sold_out is not None:
        fields.append("sold_out=?")
        values.append(int(_flag(sold_out, "sold out flag")))
    if not fields:
        raise CatalogError("ไม่ได้ระบุสถานะที่จะเปลี่ยน")
    cursor = conn.execute(
        f"UPDATE menu_catalog SET {','.join(fields)},updated_at=CURRENT_TIMESTAMP"
        " WHERE branch_id=? AND item_id=?", (*values, branch_id, item_id))
    if cursor.rowcount != 1:
        raise CatalogError(f"Item {item_id} is unavailable", 404)
    row = conn.execute("SELECT active,sold_out FROM menu_catalog WHERE branch_id=? AND item_id=?",
                       (branch_id, item_id)).fetchone()
    return {"branch_id": branch_id, "id": item_id,
            "active": bool(row[0]), "sold_out": bool(row[1])}


def set_menu_photo(conn: sqlite3.Connection, branch_id: int, item_id: str, photo: str) -> None:
    branch_id, item_id = _branch(branch_id), _item_id(item_id)
    cursor = conn.execute("UPDATE menu_catalog SET photo=?,updated_at=CURRENT_TIMESTAMP"
                          " WHERE branch_id=? AND item_id=?",
                          (_text(photo, "photo", 300), branch_id, item_id))
    if cursor.rowcount != 1:
        raise CatalogError(f"Item {item_id} is unavailable", 404)


def delete_menu_item(conn: sqlite3.Connection, branch_id: int, item_id: str) -> str:
    """Remove a menu item. Past orders keep their own copy of name and price,
    so deleting a dish never rewrites a bill the shop has already printed."""
    branch_id, item_id = _branch(branch_id), _item_id(item_id)
    row = conn.execute("SELECT photo FROM menu_catalog WHERE branch_id=? AND item_id=?",
                       (branch_id, item_id)).fetchone()
    if row is None:
        raise CatalogError(f"Item {item_id} is unavailable", 404)
    conn.execute("DELETE FROM menu_catalog WHERE branch_id=? AND item_id=?", (branch_id, item_id))
    return row[0] or ""


def list_menu_items(conn: sqlite3.Connection, branch_id: int, *, active_only: bool = True) -> list[dict]:
    branch_id = _branch(branch_id)
    sql = f"SELECT {MENU_COLUMNS} FROM menu_catalog WHERE branch_id=?"
    if active_only:
        sql += " AND active=1"
    sql += " ORDER BY category,item_id"
    return [{"id": row[0], "name": row[1], "price": row[2] / 100,
             "bom": json.loads(row[3]), "active": bool(row[4]), "station": row[5],
             "category": row[6], "description": row[7], "cost": row[8] / 100,
             "photo": row[9], "tax_mode": row[10], "service_charge": bool(row[11]),
             "sold_out": bool(row[12]), "option_title": row[13],
             "levels": json.loads(row[14]),
             "addons": [_addon_out(addon) for addon in json.loads(row[15])]}
            for row in conn.execute(sql, (branch_id,))]


def list_menu_categories(conn: sqlite3.Connection, branch_id: int) -> list[str]:
    branch_id = _branch(branch_id)
    return [row[0] for row in conn.execute(
        "SELECT DISTINCT category FROM menu_catalog WHERE branch_id=? AND category!=''"
        " ORDER BY category", (branch_id,))]


def quote_order(conn: sqlite3.Connection, branch_id: int, items: list[Any]) -> dict:
    """Return trusted order lines, exact total and aggregated BOM quantities.

    Each submitted line needs only ``id`` and positive integer ``qty``. Extra
    fields such as client price/name/BOM are ignored. A missing/inactive menu
    item is rejected. Call inside the transaction that inserts the order.
    """
    branch_id = _branch(branch_id)
    if not isinstance(items, list) or not 1 <= len(items) <= 100:
        raise CatalogError("Order must contain 1 to 100 lines")
    lines, deductions, total_cents = [], defaultdict(Decimal), 0
    for raw in items:
        getter = raw.get if isinstance(raw, dict) else lambda key, default=None: getattr(raw, key, default)
        item_id = _item_id(getter("id"))
        course_mode = getter("course_mode", "FIRE")
        if course_mode not in ("FIRE", "HOLD"):
            raise CatalogError("Invalid course mode")
        qty_decimal = _positive_decimal(getter("qty"), "quantity")
        if qty_decimal != qty_decimal.to_integral_value() or qty_decimal > 1000:
            raise CatalogError("Quantity must be a whole number from 1 to 1000")
        qty = int(qty_decimal)
        row = conn.execute("""SELECT name,price_cents,bom_json,station,sold_out,addons_json
            FROM menu_catalog WHERE branch_id=? AND item_id=? AND active=1""",
            (branch_id, item_id)).fetchone()
        if row is None:
            raise CatalogError(f"Item {item_id} is unavailable", 409)
        name, price_cents, bom_json, station, sold_out, addons_json = row
        if sold_out:
            raise CatalogError(f"{name} ขายหมดชั่วคราว", 409)
        bom = json.loads(bom_json)
        # Stored BOM is admin controlled but validate it again against legacy
        # or manually modified databases before allowing stock mutations.
        bom = _validated_bom(bom)
        # Toppings are priced from the shop's own list, never from the request.
        offered = {addon["name"]: addon for addon in _validated_addons(json.loads(addons_json))}
        chosen, line_cents = [], price_cents
        raw_addons = getter("addons", []) or []
        if not isinstance(raw_addons, list) or len(raw_addons) > 30:
            raise CatalogError("Invalid topping selection")
        for raw_addon in raw_addons:
            addon = offered.get(_text(raw_addon, "topping name", 80))
            if addon is None:
                raise CatalogError(f"{name} ไม่มีตัวเลือกเพิ่มนี้", 409)
            if addon["name"] in {picked["name"] for picked in chosen}:
                continue   # the same topping twice still means once
            chosen.append(addon)
            line_cents += addon["price_cents"]
            if addon["ingId"] != "NONE" and addon["qty"] > 0:
                bom = bom + [{"ingId": addon["ingId"], "qty": addon["qty"]}]
        if line_cents < 0:
            raise CatalogError(f"{name} ลดราคาจนติดลบไม่ได้")
        bom = _validated_bom(bom)
        level = _text(getter("level", ""), "option", 80)
        total_cents += line_cents * qty
        if total_cents > 100_000_000:
            raise CatalogError("Order total exceeds limit")
        for part in bom:
            deductions[part["ingId"]] += Decimal(str(part["qty"])) * qty
        lines.append({"id": item_id, "name": name, "qty": qty,
                      "price": line_cents / 100, "bom": bom, "station": station,
                      "course_mode": course_mode, "level": level,
                      "addons": [addon["name"] for addon in chosen]})
    return {"items": lines, "total_amount": total_cents / 100,
            "total_cents": total_cents,
            "deductions": {key: float(value) for key, value in sorted(deductions.items())}}


def deduct_inventory(
    conn: sqlite3.Connection, branch_id: int, deductions: dict[str, float],
    *, allow_negative: bool = False,
) -> None:
    """Deduct each ingredient exactly once in the caller's write transaction.

    Default policy rejects missing or insufficient stock. Explicit
    ``allow_negative`` supports sites that intentionally backorder ingredients.
    """
    branch_id = _branch(branch_id)
    for ingredient_id, raw_amount in sorted(deductions.items()):
        ingredient_id = _item_id(ingredient_id)
        amount = _positive_decimal(raw_amount, "stock deduction")
        if amount > 1_000_000_000:
            raise CatalogError("Invalid stock deduction")
        if allow_negative:
            conn.execute("""INSERT INTO inventory(branch_id,ingredient_id,stock) VALUES (?,?,?)
                ON CONFLICT(branch_id,ingredient_id) DO UPDATE SET stock=stock-excluded.stock""",
                (branch_id, ingredient_id, -float(amount)))
        else:
            cursor = conn.execute("""UPDATE inventory SET stock=stock-?
                WHERE branch_id=? AND ingredient_id=? AND stock>=?""",
                (float(amount), branch_id, ingredient_id, float(amount)))
            if cursor.rowcount != 1:
                raise CatalogError(f"Insufficient stock: {ingredient_id}", 409)
