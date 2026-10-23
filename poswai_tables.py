"""The shop's tables and the permanent link printed on each one.

A sticker on a table outlives any token, so the printed QR carries only an
unguessable code. The server looks that code up and mints a fresh, short-lived
table token on every scan. A shop that loses a sticker revokes the code or
issues a new one; the paper on every other table keeps working.

The caller owns the SQLite transaction and has already checked the staff role.
"""

from __future__ import annotations

import re
import secrets
import sqlite3

# A table's own name, as the shop writes it on the furniture.
TABLE_NO_PATTERN = re.compile(r"[\w\- ]{1,24}", re.UNICODE)
# What goes in the printed link. Long enough that guessing is hopeless, short
# enough that the QR stays coarse and still scans from a phone's distance.
CODE_PATTERN = re.compile(r"[A-Za-z0-9_-]{16,64}")
MAX_TABLES_PER_BRANCH = 300


class TableError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def init_tables(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS shop_tables (
        branch_id INTEGER NOT NULL,
        table_no TEXT NOT NULL,
        code TEXT NOT NULL UNIQUE,
        active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
        seats INTEGER NOT NULL DEFAULT 0 CHECK(seats >= 0),
        note TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        revoked_at TEXT,
        PRIMARY KEY (branch_id, table_no)
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS shop_tables_active ON shop_tables(branch_id,active)")


def _branch(value: object) -> int:
    if isinstance(value, bool):
        raise TableError("สาขาไม่ถูกต้อง")
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise TableError("สาขาไม่ถูกต้อง") from None
    if result < 1:
        raise TableError("สาขาไม่ถูกต้อง")
    return result


def _table_no(value: object) -> str:
    result = str(value or "").strip()
    if not TABLE_NO_PATTERN.fullmatch(result):
        raise TableError("ชื่อโต๊ะใช้ตัวอักษร ตัวเลข ขีด หรือเว้นวรรค ยาวไม่เกิน 24 ตัว")
    return result


def new_code() -> str:
    """22 url-safe characters. Not derived from the table name, so the code
    tells a stranger nothing and two tables never collide by being renamed."""
    return secrets.token_urlsafe(16)


def add_table(conn: sqlite3.Connection, branch_id: int, table_no: str,
              seats: object = 0, note: object = "") -> dict:
    branch_id, table_no = _branch(branch_id), _table_no(table_no)
    try:
        seats = int(seats or 0)
    except (TypeError, ValueError):
        raise TableError("จำนวนที่นั่งไม่ถูกต้อง") from None
    if seats < 0 or seats > 999:
        raise TableError("จำนวนที่นั่งไม่ถูกต้อง")
    note = str(note or "").strip()
    if len(note) > 120:
        raise TableError("หมายเหตุยาวเกินไป")
    count = conn.execute("SELECT COUNT(*) FROM shop_tables WHERE branch_id=?", (branch_id,)).fetchone()[0]
    if count >= MAX_TABLES_PER_BRANCH:
        raise TableError(f"สาขาหนึ่งมีโต๊ะได้ไม่เกิน {MAX_TABLES_PER_BRANCH} โต๊ะ", 409)
    code = new_code()
    try:
        conn.execute("INSERT INTO shop_tables(branch_id,table_no,code,seats,note) VALUES(?,?,?,?,?)",
                     (branch_id, table_no, code, seats, note))
    except sqlite3.IntegrityError as exc:
        raise TableError(f"มีโต๊ะ {table_no} อยู่แล้ว", 409) from exc
    return {"branch_id": branch_id, "table_no": table_no, "code": code,
            "active": True, "seats": seats, "note": note}


def list_tables(conn: sqlite3.Connection, branch_id: int) -> list[dict]:
    branch_id = _branch(branch_id)
    rows = conn.execute(
        "SELECT table_no,code,active,seats,note,created_at,revoked_at FROM shop_tables"
        " WHERE branch_id=? ORDER BY (table_no GLOB '[0-9]*')=0,"
        " CAST(table_no AS INTEGER),table_no", (branch_id,))
    return [{"branch_id": branch_id, "table_no": row[0], "code": row[1], "active": bool(row[2]),
             "seats": row[3], "note": row[4], "created_at": row[5], "revoked_at": row[6]}
            for row in rows]


def resolve_code(conn: sqlite3.Connection, code: str) -> dict:
    """Find the table a printed sticker belongs to. A revoked sticker is told
    apart from one that never existed, so a shop can explain it to a guest."""
    if not isinstance(code, str) or not CODE_PATTERN.fullmatch(code):
        raise TableError("ลิงก์โต๊ะไม่ถูกต้อง", 404)
    row = conn.execute("SELECT branch_id,table_no,active FROM shop_tables WHERE code=?",
                       (code,)).fetchone()
    if row is None:
        raise TableError("ลิงก์โต๊ะไม่ถูกต้อง", 404)
    if not row[2]:
        raise TableError("QR ของโต๊ะนี้ถูกยกเลิกแล้ว กรุณาเรียกพนักงาน", 410)
    return {"branch_id": row[0], "table_no": row[1]}


def set_active(conn: sqlite3.Connection, branch_id: int, table_no: str, active: bool) -> dict:
    """Revoke the sticker on one table, or bring it back. The code is kept, so
    an accidental revoke does not force the shop to reprint."""
    branch_id, table_no = _branch(branch_id), _table_no(table_no)
    if not isinstance(active, bool):
        raise TableError("สถานะไม่ถูกต้อง")
    cursor = conn.execute(
        "UPDATE shop_tables SET active=?,revoked_at=CASE WHEN ? THEN NULL ELSE CURRENT_TIMESTAMP END"
        " WHERE branch_id=? AND table_no=?", (int(active), int(active), branch_id, table_no))
    if cursor.rowcount != 1:
        raise TableError(f"ไม่พบโต๊ะ {table_no}", 404)
    return {"branch_id": branch_id, "table_no": table_no, "active": active}


def reissue_code(conn: sqlite3.Connection, branch_id: int, table_no: str) -> dict:
    """Give one table a brand new code. Every sticker already printed for that
    table stops working at once, which is the point: this is what a shop does
    when a photograph of its QR is circulating."""
    branch_id, table_no = _branch(branch_id), _table_no(table_no)
    code = new_code()
    cursor = conn.execute(
        "UPDATE shop_tables SET code=?,active=1,revoked_at=NULL WHERE branch_id=? AND table_no=?",
        (code, branch_id, table_no))
    if cursor.rowcount != 1:
        raise TableError(f"ไม่พบโต๊ะ {table_no}", 404)
    return {"branch_id": branch_id, "table_no": table_no, "code": code, "active": True}


def delete_table(conn: sqlite3.Connection, branch_id: int, table_no: str) -> None:
    branch_id, table_no = _branch(branch_id), _table_no(table_no)
    cursor = conn.execute("DELETE FROM shop_tables WHERE branch_id=? AND table_no=?",
                          (branch_id, table_no))
    if cursor.rowcount != 1:
        raise TableError(f"ไม่พบโต๊ะ {table_no}", 404)
