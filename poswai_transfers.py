"""ใบโอนของข้ามสาขา — what left one branch, and what reached the other.

Moving stock between branches already worked, in one step: the source was
debited and the destination credited in the same instant. That is a van that
never breaks down. When a box goes missing on the way, both branches' books
say it arrived, and the shortfall turns up weeks later as a stock count
nobody can explain.

So a transfer is a document now. One branch sends it, the other confirms what
actually turned up, and the stock moves on that confirmation — the same shape
as a purchase order, for the same reason.

Nothing is written off automatically. If ten were sent and eight arrived, the
two stay on the sending branch's books and the document says they are missing,
because a system that quietly destroys stock to make two numbers agree is how
a shop stops believing its own figures.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from typing import Any

SENT, RECEIVED, CANCELLED = "sent", "received", "cancelled"
BANGKOK = dt.timezone(dt.timedelta(hours=7))


class TransferError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def init_transfers(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS stock_transfers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        number TEXT NOT NULL UNIQUE,
        from_branch_id INTEGER NOT NULL,
        to_branch_id INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'sent',
        sent_by INTEGER NOT NULL,
        sent_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f','now')),
        received_by INTEGER,
        received_at TEXT,
        note TEXT NOT NULL DEFAULT '',
        cancel_reason TEXT NOT NULL DEFAULT '')""")
    conn.execute("""CREATE TABLE IF NOT EXISTS stock_transfer_lines (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        transfer_id INTEGER NOT NULL REFERENCES stock_transfers(id),
        ingredient_id TEXT NOT NULL,
        quantity REAL NOT NULL CHECK(quantity > 0),
        -- NULL until the far branch confirms. Not the same as zero.
        received_quantity REAL)""")
    conn.execute("CREATE INDEX IF NOT EXISTS stock_transfer_lines_transfer"
                 " ON stock_transfer_lines(transfer_id)")


def _quantity(value: Any, field: str, *, allow_zero: bool = False) -> float:
    if isinstance(value, bool):
        raise TransferError(f"{field} ไม่ถูกต้อง")
    try:
        amount = float(value)
    except (TypeError, ValueError):
        raise TransferError(f"{field} ต้องเป็นตัวเลข") from None
    if amount < 0 or (not allow_zero and amount == 0):
        raise TransferError(f"{field} ต้องมากกว่าศูนย์" if not allow_zero
                            else f"{field} ติดลบไม่ได้")
    if amount > 1_000_000:
        raise TransferError(f"{field} สูงเกินไป")
    return round(amount, 4)


def _text(value: Any, field: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) > limit:
        raise TransferError(f"{field} ยาวเกิน {limit} ตัวอักษร")
    return text


def next_number(conn: sqlite3.Connection, today: dt.date | None = None) -> str:
    """TR-2611-0001, per month, like the other documents the shop files."""
    today = today or dt.datetime.now(BANGKOK).date()
    prefix = f"TR-{today.year % 100:02d}{today.month:02d}"
    highest = conn.execute(
        "SELECT number FROM stock_transfers WHERE number LIKE ? ORDER BY number DESC LIMIT 1",
        (f"{prefix}-%",)).fetchone()
    count = int(highest[0].rsplit("-", 1)[1]) if highest else 0
    return f"{prefix}-{count + 1:04d}"


def send(conn: sqlite3.Connection, *, from_branch_id: int, to_branch_id: int,
         staff_id: int, lines: list[dict], note: str = "",
         today: dt.date | None = None) -> dict:
    """Write the note that goes in the box. Stock does not move yet.

    It moves when the far branch says what arrived, because that is the only
    moment anyone actually knows.
    """
    if from_branch_id == to_branch_id:
        raise TransferError("สาขาต้นทางกับปลายทางต้องคนละสาขา")
    for branch_id in (from_branch_id, to_branch_id):
        if not conn.execute("SELECT 1 FROM branches WHERE id=?", (branch_id,)).fetchone():
            raise TransferError(f"ไม่พบสาขา {branch_id}", 404)
    if not isinstance(lines, list) or not 1 <= len(lines) <= 100:
        raise TransferError("ใบโอนต้องมี 1 ถึง 100 รายการ")

    clean, seen = [], set()
    for raw in lines:
        if not isinstance(raw, dict):
            raise TransferError("รายการไม่ถูกต้อง")
        ingredient = _text(raw.get("ingredient_id"), "รหัสวัตถุดิบ", 80)
        if not ingredient:
            raise TransferError("ต้องเลือกวัตถุดิบทุกบรรทัด")
        if ingredient in seen:
            raise TransferError(f"{ingredient} ซ้ำกันในใบเดียว")
        seen.add(ingredient)
        quantity = _quantity(raw.get("quantity"), "จำนวน")
        # Refusing here rather than at receiving time: the person loading the
        # van can still put the box back, which they cannot do tomorrow.
        have = conn.execute("SELECT stock FROM inventory WHERE branch_id=? AND ingredient_id=?",
                            (from_branch_id, ingredient)).fetchone()
        if not have or have[0] < quantity:
            raise TransferError(f"{ingredient} ในสาขาต้นทางมีไม่พอ "
                                f"(มี {have[0] if have else 0})", 409)
        clean.append({"ingredient_id": ingredient, "quantity": quantity})

    number = next_number(conn, today)
    transfer_id = conn.execute(
        "INSERT INTO stock_transfers (number, from_branch_id, to_branch_id, sent_by, note)"
        " VALUES (?,?,?,?,?)",
        (number, from_branch_id, to_branch_id, staff_id,
         _text(note, "หมายเหตุ", 300))).lastrowid
    conn.executemany(
        "INSERT INTO stock_transfer_lines (transfer_id, ingredient_id, quantity)"
        " VALUES (?,?,?)",
        [(transfer_id, line["ingredient_id"], line["quantity"]) for line in clean])
    return transfer(conn, transfer_id)


def receive(conn: sqlite3.Connection, transfer_id: int, staff_id: int,
            received: dict[str, Any] | None = None, *, apply_movement) -> dict:
    """Confirm what turned up, and move exactly that much.

    Anything left out of ``received`` arrived in full. A line that arrived
    short moves only what arrived; the rest stays on the sending branch's
    books, flagged on this document for someone to go and look for.
    """
    current = transfer(conn, transfer_id)
    if current["status"] == RECEIVED:
        raise TransferError("ใบนี้รับของแล้ว", 409)
    if current["status"] == CANCELLED:
        raise TransferError("ใบนี้ถูกยกเลิกไปแล้ว", 409)
    received = received or {}
    unknown = set(received) - {line["ingredient_id"] for line in current["lines"]}
    if unknown:
        raise TransferError(f"{', '.join(sorted(unknown))} ไม่ได้อยู่ในใบโอนนี้")

    for line in current["lines"]:
        arrived = line["quantity"] if line["ingredient_id"] not in received else \
            _quantity(received[line["ingredient_id"]], "จำนวนที่รับ", allow_zero=True)
        if arrived > line["quantity"]:
            raise TransferError(f"{line['ingredient_id']} รับมากกว่าที่ส่งไม่ได้")
        conn.execute("UPDATE stock_transfer_lines SET received_quantity=? WHERE id=?",
                     (arrived, line["id"]))
        if arrived <= 0:
            continue
        # One atomic movement through the shared ledger: it debits the sending
        # branch and credits the receiving one, so the two can never disagree
        # about where the stock is.
        apply_movement(conn, event_id=f"tr-{current['number']}-{line['ingredient_id']}",
                       branch_id=current["from_branch_id"],
                       ingredient_id=line["ingredient_id"], action="transfer",
                       quantity=arrived, actor_staff_id=staff_id,
                       target_branch_id=current["to_branch_id"],
                       note=f"โอนตาม {current['number']}")
    conn.execute("UPDATE stock_transfers SET status=?, received_by=?,"
                 " received_at=strftime('%Y-%m-%d %H:%M:%f','now') WHERE id=?",
                 (RECEIVED, staff_id, transfer_id))
    return transfer(conn, transfer_id)


def cancel(conn: sqlite3.Connection, transfer_id: int, reason: str) -> dict:
    """Call off a transfer nobody has confirmed. Nothing moved, so nothing
    needs undoing."""
    reason = _text(reason, "เหตุผล", 200)
    if not reason:
        raise TransferError("ต้องบอกเหตุผลที่ยกเลิก")
    current = transfer(conn, transfer_id)
    if current["status"] == RECEIVED:
        raise TransferError("ใบที่รับของแล้วยกเลิกไม่ได้ ให้โอนกลับแทน", 409)
    if current["status"] == CANCELLED:
        raise TransferError("ใบนี้ถูกยกเลิกไปแล้ว", 409)
    conn.execute("UPDATE stock_transfers SET status=?, cancel_reason=? WHERE id=?",
                 (CANCELLED, reason, transfer_id))
    return transfer(conn, transfer_id)


def transfer(conn: sqlite3.Connection, transfer_id: int) -> dict:
    row = conn.execute(
        "SELECT id,number,from_branch_id,to_branch_id,status,sent_by,sent_at,"
        "received_by,received_at,note,cancel_reason FROM stock_transfers WHERE id=?",
        (transfer_id,)).fetchone()
    if row is None:
        raise TransferError("ไม่พบใบโอนนี้", 404)
    lines = [{"id": line[0], "ingredient_id": line[1], "quantity": line[2],
              "received_quantity": line[3],
              # What was sent and never turned up. Shown, never written off.
              "missing": None if line[3] is None else round(line[2] - line[3], 4)}
             for line in conn.execute(
                 "SELECT id,ingredient_id,quantity,received_quantity"
                 " FROM stock_transfer_lines WHERE transfer_id=? ORDER BY id", (transfer_id,))]
    names = {b[0]: b[1] for b in conn.execute("SELECT id,name FROM branches")}
    return {"id": row[0], "number": row[1],
            "from_branch_id": row[2], "from_branch": names.get(row[2], str(row[2])),
            "to_branch_id": row[3], "to_branch": names.get(row[3], str(row[3])),
            "status": row[4], "sent_by": row[5], "sent_at": row[6],
            "received_by": row[7], "received_at": row[8], "note": row[9],
            "cancel_reason": row[10], "lines": lines,
            "shortfall": any(line["missing"] for line in lines)}


def listing(conn: sqlite3.Connection, branch_id: int, limit: int = 50) -> list[dict]:
    """Both directions: what this branch sent and what is coming to it."""
    rows = conn.execute(
        "SELECT id FROM stock_transfers WHERE from_branch_id=? OR to_branch_id=?"
        " ORDER BY id DESC LIMIT ?",
        (branch_id, branch_id, max(1, min(int(limit), 200)))).fetchall()
    return [transfer(conn, row[0]) for row in rows]


def in_transit(conn: sqlite3.Connection, branch_id: int) -> dict:
    """What has left for this branch and not been confirmed, and what this
    branch has sent out and not had confirmed."""
    incoming = {row[0]: round(row[1] or 0, 4) for row in conn.execute(
        "SELECT l.ingredient_id, SUM(l.quantity) FROM stock_transfer_lines l"
        " JOIN stock_transfers t ON t.id=l.transfer_id"
        " WHERE t.to_branch_id=? AND t.status=? GROUP BY l.ingredient_id",
        (branch_id, SENT))}
    outgoing = {row[0]: round(row[1] or 0, 4) for row in conn.execute(
        "SELECT l.ingredient_id, SUM(l.quantity) FROM stock_transfer_lines l"
        " JOIN stock_transfers t ON t.id=l.transfer_id"
        " WHERE t.from_branch_id=? AND t.status=? GROUP BY l.ingredient_id",
        (branch_id, SENT))}
    return {"incoming": incoming, "outgoing": outgoing}
