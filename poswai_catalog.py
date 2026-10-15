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
    if "station" not in columns:
        conn.execute("ALTER TABLE menu_catalog ADD COLUMN station TEXT NOT NULL DEFAULT 'ครัวร้อน'")


def upsert_menu_item(
    conn: sqlite3.Connection, branch_id: int, item_id: str | int,
    name: str, price: Any, bom: list[dict], active: bool = True, station: str = "ครัวร้อน",
) -> dict:
    branch_id, item_id = _branch(branch_id), _item_id(item_id)
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 200:
        raise CatalogError("Invalid item name")
    if not isinstance(active, bool):
        raise CatalogError("Invalid active flag")
    if station not in STATIONS:
        raise CatalogError("Invalid kitchen station")
    cents, canonical_bom = _money_cents(price), _validated_bom(bom)
    conn.execute("""INSERT INTO menu_catalog
        (branch_id,item_id,name,price_cents,bom_json,active,station) VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(branch_id,item_id) DO UPDATE SET
        name=excluded.name,price_cents=excluded.price_cents,
        bom_json=excluded.bom_json,active=excluded.active,station=excluded.station,updated_at=CURRENT_TIMESTAMP""",
        (branch_id, item_id, name.strip(), cents, json.dumps(canonical_bom), int(active), station))
    return {"branch_id": branch_id, "id": item_id, "name": name.strip(),
            "price": cents / 100, "bom": canonical_bom, "active": active, "station": station}


def list_menu_items(conn: sqlite3.Connection, branch_id: int, *, active_only: bool = True) -> list[dict]:
    branch_id = _branch(branch_id)
    sql = "SELECT item_id,name,price_cents,bom_json,active,station FROM menu_catalog WHERE branch_id=?"
    if active_only:
        sql += " AND active=1"
    sql += " ORDER BY item_id"
    return [{"id": row[0], "name": row[1], "price": row[2] / 100,
             "bom": json.loads(row[3]), "active": bool(row[4]), "station": row[5]}
            for row in conn.execute(sql, (branch_id,))]


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
        row = conn.execute("""SELECT name,price_cents,bom_json,station FROM menu_catalog
            WHERE branch_id=? AND item_id=? AND active=1""", (branch_id, item_id)).fetchone()
        if row is None:
            raise CatalogError(f"Item {item_id} is unavailable", 409)
        name, price_cents, bom_json, station = row
        bom = json.loads(bom_json)
        # Stored BOM is admin controlled but validate it again against legacy
        # or manually modified databases before allowing stock mutations.
        bom = _validated_bom(bom)
        total_cents += price_cents * qty
        if total_cents > 100_000_000:
            raise CatalogError("Order total exceeds limit")
        for part in bom:
            deductions[part["ingId"]] += Decimal(str(part["qty"])) * qty
        lines.append({"id": item_id, "name": name, "qty": qty,
                      "price": price_cents / 100, "bom": bom, "station": station,
                      "course_mode": course_mode})
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
