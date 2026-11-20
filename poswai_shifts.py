"""กะการขายและลิ้นชักเงินสด — the till's own account of its money.

A shop knows what it sold, because every bill is recorded. What it has never
known is what is actually in the drawer, and the difference between the two is
the only place a shop finds out that money went missing.

So a shift is opened with a counted float, every note that goes in or out
without being a sale is written down, and at the end the drawer is counted
again. Expected and counted are stored side by side, never reconciled into one
number: a shift that is 200 baht short is a fact the owner needs to see, not a
number to be quietly adjusted away.

Money is in satang as whole numbers, like the rest of the system.
"""

from __future__ import annotations

import sqlite3
from typing import Any

OPEN, CLOSED = "open", "closed"

# Why money moved without a sale. Kept short on purpose: a long list makes the
# person at the till pick the first one every time.
CASH_IN = "in"        # ตั้งต้นเพิ่ม / เจ้าของเติมเงินทอน
CASH_OUT = "out"      # ถอนเงินไปฝาก / เอาไปใช้
CASH_EXPENSE = "expense"   # จ่ายค่าของหน้าร้านจากลิ้นชัก
MOVEMENT_KINDS = (CASH_IN, CASH_OUT, CASH_EXPENSE)
# What each kind does to the drawer.
MOVEMENT_SIGN = {CASH_IN: 1, CASH_OUT: -1, CASH_EXPENSE: -1}

# The payment methods that put paper money in the drawer. A transfer the staff
# confirmed seeing arrive is money in the bank, not in the till, so counting it
# here would make every drawer look short by the day's transfers.
CASH_METHODS = ("เงินสด (Cash)",)


class ShiftError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def init_shifts(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS cash_shifts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        branch_id INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'open',
        opened_by INTEGER NOT NULL,
        -- To the millisecond, not the second. CURRENT_TIMESTAMP rounds to the
        -- second, and a bill closed in the same second a shift opened then
        -- falls inside both shifts — the old one's drawer comes up short by
        -- exactly that bill and the new one's long by it.
        opened_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
        opening_cents INTEGER NOT NULL DEFAULT 0,
        closed_by INTEGER,
        closed_at TEXT,
        -- What the drawer should hold, and what was actually in it. Both are
        -- kept: the gap between them is the whole point of counting.
        expected_cents INTEGER,
        counted_cents INTEGER,
        note TEXT NOT NULL DEFAULT '')""")
    # One open shift per branch, enforced by the database rather than by a
    # check that two tills pressing "open" at once could both pass.
    conn.execute("""CREATE UNIQUE INDEX IF NOT EXISTS cash_shifts_one_open
        ON cash_shifts(branch_id) WHERE status='open'""")
    conn.execute("""CREATE TABLE IF NOT EXISTS cash_movements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        shift_id INTEGER NOT NULL REFERENCES cash_shifts(id),
        kind TEXT NOT NULL,
        amount_cents INTEGER NOT NULL,
        reason TEXT NOT NULL DEFAULT '',
        staff_id INTEGER NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
    conn.execute("CREATE INDEX IF NOT EXISTS cash_movements_shift ON cash_movements(shift_id)")


def _money_cents(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ShiftError(f"{field} ไม่ถูกต้อง")
    try:
        cents = round(float(value) * 100)
    except (TypeError, ValueError):
        raise ShiftError(f"{field} ต้องเป็นตัวเลข") from None
    if cents < 0:
        raise ShiftError(f"{field} ติดลบไม่ได้")
    if cents > 100_000_000:
        raise ShiftError(f"{field} สูงเกินไป")
    return cents


def open_shift(conn: sqlite3.Connection, branch_id: int, staff_id: int,
               opening: Any = 0, note: str = "") -> dict:
    """Start counting, from the float that is in the drawer right now."""
    if current_shift(conn, branch_id):
        raise ShiftError("สาขานี้เปิดกะค้างอยู่แล้ว ปิดกะเดิมก่อน", 409)
    cents = _money_cents(opening, "เงินทอนตั้งต้น")
    cursor = conn.execute(
        "INSERT INTO cash_shifts (branch_id, opened_by, opening_cents, note) VALUES (?,?,?,?)",
        (branch_id, staff_id, cents, " ".join(str(note or "").split())[:200]))
    return shift_detail(conn, cursor.lastrowid)


def add_movement(conn: sqlite3.Connection, branch_id: int, staff_id: int,
                 kind: str, amount: Any, reason: str = "") -> dict:
    """Money in or out of the drawer that is not a sale.

    A reason is required for anything leaving the drawer. "Where did the 500
    go" is the question this table exists to answer, and a blank row answers
    nothing.
    """
    if kind not in MOVEMENT_KINDS:
        raise ShiftError("ประเภทรายการเงินสดไม่ถูกต้อง")
    shift = current_shift(conn, branch_id)
    if not shift:
        raise ShiftError("ยังไม่ได้เปิดกะ", 409)
    cents = _money_cents(amount, "จำนวนเงิน")
    if cents == 0:
        raise ShiftError("จำนวนเงินต้องมากกว่าศูนย์")
    reason = " ".join(str(reason or "").split())[:200]
    if kind in (CASH_OUT, CASH_EXPENSE) and not reason:
        raise ShiftError("ต้องบอกเหตุผลที่นำเงินออกจากลิ้นชัก")
    conn.execute("INSERT INTO cash_movements (shift_id, kind, amount_cents, reason, staff_id)"
                 " VALUES (?,?,?,?,?)", (shift["id"], kind, cents, reason, staff_id))
    return shift_detail(conn, shift["id"])


def close_shift(conn: sqlite3.Connection, branch_id: int, staff_id: int,
                counted: Any, note: str = "") -> dict:
    """Count the drawer and close. The difference is recorded, not corrected."""
    shift = current_shift(conn, branch_id)
    if not shift:
        raise ShiftError("ยังไม่ได้เปิดกะ", 409)
    cents = _money_cents(counted, "เงินที่นับได้")
    detail = shift_detail(conn, shift["id"])
    conn.execute("UPDATE cash_shifts SET status=?, closed_by=?,"
                 " closed_at=strftime('%Y-%m-%d %H:%M:%f', 'now'),"
                 " expected_cents=?, counted_cents=?, note=? WHERE id=?",
                 (CLOSED, staff_id, detail["expected_cents"], cents,
                  " ".join(str(note or "").split())[:200] or detail["note"], shift["id"]))
    return shift_detail(conn, shift["id"])


def current_shift(conn: sqlite3.Connection, branch_id: int) -> dict | None:
    row = conn.execute("SELECT id FROM cash_shifts WHERE branch_id=? AND status=?",
                       (branch_id, OPEN)).fetchone()
    return shift_detail(conn, row[0]) if row else None


def shift_detail(conn: sqlite3.Connection, shift_id: int) -> dict:
    """One shift with its money worked out from the records, every time.

    Nothing is kept as a running total. A total that is written down drifts
    the first time a bill is voided behind its back; counted from the records
    it is always what the records say.
    """
    row = conn.execute(
        "SELECT id,branch_id,status,opened_by,opened_at,opening_cents,closed_by,closed_at,"
        "expected_cents,counted_cents,note FROM cash_shifts WHERE id=?", (shift_id,)).fetchone()
    if row is None:
        raise ShiftError("ไม่พบกะนี้", 404)
    (sid, branch_id, status, opened_by, opened_at, opening, closed_by, closed_at,
     expected_stored, counted, note) = row

    window_end = closed_at or "9999-12-31"
    placeholders = ",".join("?" for _ in CASH_METHODS)
    sales = conn.execute(
        f"SELECT COALESCE(SUM(net_amount),0), COUNT(*) FROM pos_orders"
        f" WHERE branch_id=? AND status='paid' AND payment_method IN ({placeholders})"
        f" AND closed_at >= ? AND closed_at <= ?",
        (branch_id, *CASH_METHODS, opened_at, window_end)).fetchone()
    cash_sales_cents = round((sales[0] or 0) * 100)

    # Every bill of the shift, not just the cash ones, so the owner can see
    # what the shift did as well as what the drawer should hold.
    takings = conn.execute(
        "SELECT COALESCE(SUM(net_amount),0), COUNT(*) FROM pos_orders"
        " WHERE branch_id=? AND status='paid' AND closed_at >= ? AND closed_at <= ?",
        (branch_id, opened_at, window_end)).fetchone()

    movements = [
        {"id": m[0], "kind": m[1], "amount": m[2] / 100, "reason": m[3],
         "staff_id": m[4], "at": m[5]}
        for m in conn.execute(
            "SELECT id,kind,amount_cents,reason,staff_id,created_at FROM cash_movements"
            " WHERE shift_id=? ORDER BY id", (shift_id,))]
    moved_cents = sum(MOVEMENT_SIGN[m["kind"]] * round(m["amount"] * 100) for m in movements)

    expected = opening + cash_sales_cents + moved_cents
    detail = {
        "id": sid, "branch_id": branch_id, "status": status,
        "opened_by": opened_by, "opened_at": opened_at,
        "closed_by": closed_by, "closed_at": closed_at,
        "opening": opening / 100, "opening_cents": opening,
        "cash_sales": cash_sales_cents / 100,
        "cash_bills": sales[1],
        "takings": round(takings[0] or 0, 2), "bills": takings[1],
        "cash_in": sum(m["amount"] for m in movements if m["kind"] == CASH_IN),
        "cash_out": sum(m["amount"] for m in movements
                        if m["kind"] in (CASH_OUT, CASH_EXPENSE)),
        "movements": movements, "note": note,
        "expected": expected / 100, "expected_cents": expected,
    }
    if status == CLOSED:
        # A closed shift keeps the figure it was closed on. Recomputing it
        # later would quietly move a shift that was short back into balance.
        detail["expected"] = (expected_stored or 0) / 100
        detail["expected_cents"] = expected_stored or 0
        detail["counted"] = (counted or 0) / 100
        detail["difference"] = round(((counted or 0) - (expected_stored or 0)) / 100, 2)
    return detail


def list_shifts(conn: sqlite3.Connection, branch_id: int, limit: int = 30) -> list[dict]:
    rows = conn.execute(
        "SELECT id FROM cash_shifts WHERE branch_id=? ORDER BY id DESC LIMIT ?",
        (branch_id, max(1, min(int(limit), 200)))).fetchall()
    return [shift_detail(conn, row[0]) for row in rows]
