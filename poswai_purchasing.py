"""ซัพพลายเออร์และใบสั่งซื้อ — what the shop ordered, and what actually turned up.

The stock screen could already say what was on the shelf and let someone type
in a new number. What it could not say is what is on its way, who it was
ordered from, or what it cost. So a shop ordering twice because it forgot the
first order, or paying an invoice it cannot check, had nothing to look at.

An order is written, then sent, then received. Receiving is the only step that
touches stock, and it goes through the same audited movement ledger as every
other change — a purchase order that moved stock by its own private route
would be a second set of books.

Received quantities are recorded as they actually arrived, not as they were
ordered. A supplier who sends nine of ten is the normal case, and a system
that records ten makes the shelf disagree with the shop from that day on.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from typing import Any

DRAFT, SENT, RECEIVED, CANCELLED = "draft", "sent", "received", "cancelled"
OPEN_STATES = (DRAFT, SENT)
BANGKOK = dt.timezone(dt.timedelta(hours=7))


class PurchaseError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def init_purchasing(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS suppliers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        phone TEXT NOT NULL DEFAULT '',
        note TEXT NOT NULL DEFAULT '',
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
    # Two suppliers with the same name is a shop that cannot tell its own
    # orders apart a month later.
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS suppliers_name ON suppliers(name)")
    conn.execute("""CREATE TABLE IF NOT EXISTS purchase_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        number TEXT NOT NULL UNIQUE,
        branch_id INTEGER NOT NULL,
        supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
        status TEXT NOT NULL DEFAULT 'draft',
        created_by INTEGER NOT NULL,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f','now')),
        sent_at TEXT,
        received_by INTEGER,
        received_at TEXT,
        note TEXT NOT NULL DEFAULT '',
        cancel_reason TEXT NOT NULL DEFAULT '')""")
    conn.execute("""CREATE TABLE IF NOT EXISTS purchase_order_lines (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL REFERENCES purchase_orders(id),
        ingredient_id TEXT NOT NULL,
        quantity REAL NOT NULL CHECK(quantity > 0),
        unit_cost_cents INTEGER NOT NULL DEFAULT 0,
        -- Filled in on receiving. NULL means not received yet, which is not
        -- the same as received as zero.
        received_quantity REAL)""")
    conn.execute("CREATE INDEX IF NOT EXISTS purchase_order_lines_order"
                 " ON purchase_order_lines(order_id)")


def _text(value: Any, field: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) > limit:
        raise PurchaseError(f"{field} ยาวเกิน {limit} ตัวอักษร")
    return text


def _quantity(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise PurchaseError(f"{field} ไม่ถูกต้อง")
    try:
        amount = float(value)
    except (TypeError, ValueError):
        raise PurchaseError(f"{field} ต้องเป็นตัวเลข") from None
    if not amount > 0:
        raise PurchaseError(f"{field} ต้องมากกว่าศูนย์")
    if amount > 1_000_000:
        raise PurchaseError(f"{field} สูงเกินไป")
    return round(amount, 4)


def _cents(value: Any, field: str) -> int:
    try:
        cents = round(float(value or 0) * 100)
    except (TypeError, ValueError):
        raise PurchaseError(f"{field} ต้องเป็นตัวเลข") from None
    if cents < 0:
        raise PurchaseError(f"{field} ติดลบไม่ได้")
    if cents > 100_000_000:
        raise PurchaseError(f"{field} สูงเกินไป")
    return cents


# ---- suppliers -----------------------------------------------------------

def save_supplier(conn: sqlite3.Connection, *, supplier_id: int | None = None,
                  name: str, phone: str = "", note: str = "", active: bool = True) -> dict:
    name = _text(name, "ชื่อผู้ขาย", 120)
    if not name:
        raise PurchaseError("ต้องใส่ชื่อผู้ขาย")
    phone = _text(phone, "เบอร์โทร", 40)
    note = _text(note, "หมายเหตุ", 200)
    clash = conn.execute("SELECT id FROM suppliers WHERE name=? AND id IS NOT ?",
                         (name, supplier_id)).fetchone()
    if clash:
        raise PurchaseError(f"มีผู้ขายชื่อ {name} อยู่แล้ว", 409)
    if supplier_id:
        changed = conn.execute(
            "UPDATE suppliers SET name=?,phone=?,note=?,active=? WHERE id=?",
            (name, phone, note, int(bool(active)), supplier_id)).rowcount
        if not changed:
            raise PurchaseError("ไม่พบผู้ขายรายนี้", 404)
    else:
        supplier_id = conn.execute(
            "INSERT INTO suppliers (name,phone,note,active) VALUES (?,?,?,?)",
            (name, phone, note, int(bool(active)))).lastrowid
    return supplier(conn, supplier_id)


def supplier(conn: sqlite3.Connection, supplier_id: int) -> dict:
    row = conn.execute("SELECT id,name,phone,note,active FROM suppliers WHERE id=?",
                       (supplier_id,)).fetchone()
    if row is None:
        raise PurchaseError("ไม่พบผู้ขายรายนี้", 404)
    return {"id": row[0], "name": row[1], "phone": row[2], "note": row[3],
            "active": bool(row[4])}


def list_suppliers(conn: sqlite3.Connection, include_inactive: bool = False) -> list[dict]:
    sql = "SELECT id,name,phone,note,active FROM suppliers"
    if not include_inactive:
        sql += " WHERE active=1"
    sql += " ORDER BY name"
    return [{"id": row[0], "name": row[1], "phone": row[2], "note": row[3],
             "active": bool(row[4])} for row in conn.execute(sql)]


# ---- purchase orders -----------------------------------------------------

def next_number(conn: sqlite3.Connection, today: dt.date | None = None) -> str:
    """PO-2611-0001. Per month, like the tax invoices, for the same reason:
    that is the drawer a shop files them in."""
    today = today or dt.datetime.now(BANGKOK).date()
    prefix = f"PO-{today.year % 100:02d}{today.month:02d}"
    highest = conn.execute(
        "SELECT number FROM purchase_orders WHERE number LIKE ? ORDER BY number DESC LIMIT 1",
        (f"{prefix}-%",)).fetchone()
    count = int(highest[0].rsplit("-", 1)[1]) if highest else 0
    return f"{prefix}-{count + 1:04d}"


def create_order(conn: sqlite3.Connection, *, branch_id: int, supplier_id: int,
                 staff_id: int, lines: list[dict], note: str = "",
                 today: dt.date | None = None) -> dict:
    supplier(conn, supplier_id)   # refuses a supplier that does not exist
    if not isinstance(lines, list) or not 1 <= len(lines) <= 100:
        raise PurchaseError("ใบสั่งซื้อต้องมี 1 ถึง 100 รายการ")
    clean, seen = [], set()
    for raw in lines:
        if not isinstance(raw, dict):
            raise PurchaseError("รายการไม่ถูกต้อง")
        ingredient = _text(raw.get("ingredient_id"), "รหัสวัตถุดิบ", 80)
        if not ingredient:
            raise PurchaseError("ต้องเลือกวัตถุดิบทุกบรรทัด")
        if ingredient in seen:
            raise PurchaseError(f"{ingredient} ซ้ำกันในใบเดียว")
        seen.add(ingredient)
        clean.append({"ingredient_id": ingredient,
                      "quantity": _quantity(raw.get("quantity"), "จำนวน"),
                      "unit_cost_cents": _cents(raw.get("unit_cost"), "ราคาต่อหน่วย")})
    number = next_number(conn, today)
    order_id = conn.execute(
        "INSERT INTO purchase_orders (number, branch_id, supplier_id, created_by, note)"
        " VALUES (?,?,?,?,?)",
        (number, branch_id, supplier_id, staff_id, _text(note, "หมายเหตุ", 300))).lastrowid
    conn.executemany(
        "INSERT INTO purchase_order_lines (order_id, ingredient_id, quantity, unit_cost_cents)"
        " VALUES (?,?,?,?)",
        [(order_id, line["ingredient_id"], line["quantity"], line["unit_cost_cents"])
         for line in clean])
    return order(conn, order_id)


def send_order(conn: sqlite3.Connection, order_id: int) -> dict:
    """Mark it as placed with the supplier. Nothing moves yet."""
    current = order(conn, order_id)
    if current["status"] != DRAFT:
        raise PurchaseError("ใบนี้ส่งไปแล้วหรือปิดไปแล้ว", 409)
    conn.execute("UPDATE purchase_orders SET status=?,"
                 " sent_at=strftime('%Y-%m-%d %H:%M:%f','now') WHERE id=?", (SENT, order_id))
    return order(conn, order_id)


def cancel_order(conn: sqlite3.Connection, order_id: int, reason: str) -> dict:
    reason = _text(reason, "เหตุผล", 200)
    if not reason:
        raise PurchaseError("ต้องบอกเหตุผลที่ยกเลิก")
    current = order(conn, order_id)
    if current["status"] == RECEIVED:
        raise PurchaseError("ใบที่รับของแล้วยกเลิกไม่ได้ ถ้าของผิดให้บันทึกเป็นของเสียแทน", 409)
    if current["status"] == CANCELLED:
        raise PurchaseError("ใบนี้ถูกยกเลิกไปแล้ว", 409)
    conn.execute("UPDATE purchase_orders SET status=?, cancel_reason=? WHERE id=?",
                 (CANCELLED, reason, order_id))
    return order(conn, order_id)


def receive_order(conn: sqlite3.Connection, order_id: int, staff_id: int,
                  received: dict[str, Any] | None = None, *, apply_movement) -> dict:
    """Book in what turned up, and move the stock through the audit ledger.

    ``received`` maps ingredient id to the quantity that actually arrived.
    Anything left out arrived in full, which is the common case and saves the
    person at the back door typing the same numbers twice. A line that arrived
    as nothing is recorded as zero and moves no stock — the order still says
    it was expected, which is the record a shop argues an invoice with.
    """
    current = order(conn, order_id)
    if current["status"] == RECEIVED:
        raise PurchaseError("ใบนี้รับของแล้ว", 409)
    if current["status"] == CANCELLED:
        raise PurchaseError("ใบนี้ถูกยกเลิกไปแล้ว", 409)
    received = received or {}
    unknown = set(received) - {line["ingredient_id"] for line in current["lines"]}
    if unknown:
        raise PurchaseError(f"{', '.join(sorted(unknown))} ไม่ได้อยู่ในใบสั่งซื้อนี้")

    for line in current["lines"]:
        arrived = line["quantity"] if line["ingredient_id"] not in received else \
            _received_quantity(received[line["ingredient_id"]])
        conn.execute("UPDATE purchase_order_lines SET received_quantity=? WHERE id=?",
                     (arrived, line["id"]))
        if arrived <= 0:
            continue
        # Through the same ledger as every other stock change: a purchase
        # order with its own private route into the shelf would be a second
        # set of books.
        apply_movement(conn, event_id=f"po-{current['number']}-{line['ingredient_id']}",
                       branch_id=current["branch_id"], ingredient_id=line["ingredient_id"],
                       action="restock", quantity=arrived, actor_staff_id=staff_id,
                       note=f"รับของตาม {current['number']} จาก {current['supplier']['name']}")
    conn.execute("UPDATE purchase_orders SET status=?, received_by=?,"
                 " received_at=strftime('%Y-%m-%d %H:%M:%f','now') WHERE id=?",
                 (RECEIVED, staff_id, order_id))
    return order(conn, order_id)


def _received_quantity(value: Any) -> float:
    """Like a quantity, but zero is allowed: nothing turned up."""
    if isinstance(value, bool):
        raise PurchaseError("จำนวนที่รับไม่ถูกต้อง")
    try:
        amount = float(value)
    except (TypeError, ValueError):
        raise PurchaseError("จำนวนที่รับต้องเป็นตัวเลข") from None
    if amount < 0:
        raise PurchaseError("จำนวนที่รับติดลบไม่ได้")
    if amount > 1_000_000:
        raise PurchaseError("จำนวนที่รับสูงเกินไป")
    return round(amount, 4)


def order(conn: sqlite3.Connection, order_id: int) -> dict:
    row = conn.execute(
        "SELECT id,number,branch_id,supplier_id,status,created_by,created_at,sent_at,"
        "received_by,received_at,note,cancel_reason FROM purchase_orders WHERE id=?",
        (order_id,)).fetchone()
    if row is None:
        raise PurchaseError("ไม่พบใบสั่งซื้อนี้", 404)
    lines = [{"id": line[0], "ingredient_id": line[1], "quantity": line[2],
              "unit_cost": line[3] / 100, "received_quantity": line[4],
              "amount": round(line[2] * line[3] / 100, 2)}
             for line in conn.execute(
                 "SELECT id,ingredient_id,quantity,unit_cost_cents,received_quantity"
                 " FROM purchase_order_lines WHERE order_id=? ORDER BY id", (order_id,))]
    return {"id": row[0], "number": row[1], "branch_id": row[2],
            "supplier": supplier(conn, row[3]), "status": row[4],
            "created_by": row[5], "created_at": row[6], "sent_at": row[7],
            "received_by": row[8], "received_at": row[9], "note": row[10],
            "cancel_reason": row[11], "lines": lines,
            "total": round(sum(line["amount"] for line in lines), 2)}


def list_orders(conn: sqlite3.Connection, branch_id: int, *,
                status: str | None = None, limit: int = 50) -> list[dict]:
    sql = "SELECT id FROM purchase_orders WHERE branch_id=?"
    params: list = [branch_id]
    if status:
        if status not in (DRAFT, SENT, RECEIVED, CANCELLED):
            raise PurchaseError("สถานะไม่ถูกต้อง")
        sql += " AND status=?"
        params.append(status)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(max(1, min(int(limit), 200)))
    return [order(conn, row[0]) for row in conn.execute(sql, params)]


def on_the_way(conn: sqlite3.Connection, branch_id: int) -> dict[str, float]:
    """How much of each ingredient is already ordered and not yet here.

    The stock screen shows this beside the shelf count so a shop stops
    ordering a second time because it forgot the first.
    """
    rows = conn.execute(
        f"SELECT l.ingredient_id, SUM(l.quantity) FROM purchase_order_lines l"
        f" JOIN purchase_orders o ON o.id=l.order_id"
        f" WHERE o.branch_id=? AND o.status IN ({','.join('?' * len(OPEN_STATES))})"
        f" GROUP BY l.ingredient_id", (branch_id, *OPEN_STATES))
    return {row[0]: round(row[1] or 0, 4) for row in rows}
