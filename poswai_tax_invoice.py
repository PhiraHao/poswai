"""ใบกำกับภาษีเต็มรูป — the document a company can actually claim VAT with.

Until now the till printed a sheet of text with "ใบกำกับภาษีเต็มรูป" written
on it. That is not one. The Revenue Department wants a running number that
never repeats and never skips, the seller's registered name, address, tax
number and branch, the buyer's name, address and tax number, and the VAT shown
as its own line. A customer who files the printed sheet finds out it was worth
nothing at the end of the year, by which time the sale is long past arguing
about.

So an invoice is a record, not a printout: issued once per bill, numbered by
the database, and reprintable because what was issued is what gets reprinted.
Nothing here recalculates anything — the amounts are copied from the bill as
it was paid. A tax document that moves when the menu changes is a worse
problem than no tax document.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sqlite3
from typing import Any

# What the Revenue Department calls the place that issued it. A shop with one
# address is the head office; a branch prints its own registered number.
HEAD_OFFICE = "สำนักงานใหญ่"
BANGKOK = dt.timezone(dt.timedelta(hours=7))


class InvoiceError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def init_tax_invoices(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS tax_invoices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        number TEXT NOT NULL UNIQUE,
        -- One bill, one invoice. Two invoices for one sale is the thing the
        -- Revenue Department looks for, so the database refuses it outright.
        order_no TEXT NOT NULL UNIQUE,
        branch_id INTEGER NOT NULL,
        issued_by INTEGER NOT NULL,
        issued_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f','now')),
        buyer_name TEXT NOT NULL,
        buyer_tax_id TEXT NOT NULL DEFAULT '',
        buyer_address TEXT NOT NULL DEFAULT '',
        buyer_branch TEXT NOT NULL DEFAULT '',
        -- The seller as it was on the day. A shop that corrects its address
        -- next month must not change what it already handed a customer.
        seller_json TEXT NOT NULL,
        -- The money as it was paid, in satang.
        subtotal_cents INTEGER NOT NULL,
        discount_cents INTEGER NOT NULL DEFAULT 0,
        service_charge_cents INTEGER NOT NULL DEFAULT 0,
        vat_cents INTEGER NOT NULL DEFAULT 0,
        total_cents INTEGER NOT NULL,
        vat_rate_bp INTEGER NOT NULL DEFAULT 0,
        vat_inclusive INTEGER NOT NULL DEFAULT 1,
        lines_json TEXT NOT NULL,
        cancelled_at TEXT,
        cancel_reason TEXT NOT NULL DEFAULT '')""")
    conn.execute("CREATE INDEX IF NOT EXISTS tax_invoices_issued ON tax_invoices(issued_at)")


def valid_tax_id(digits: str) -> bool:
    """The same 13-digit check as the shop's own number."""
    if not re.fullmatch(r"\d{13}", digits):
        return False
    total = sum(int(digit) * (13 - position) for position, digit in enumerate(digits[:12]))
    return (11 - total % 11) % 10 == int(digits[12])


def next_number(conn: sqlite3.Connection, today: dt.date | None = None) -> str:
    """A running number per month: 2611-0001, 2611-0002, …

    Per month because that is how a Thai shop files them, and padded so they
    sort the way they were issued. Counted from the highest number already
    issued this month rather than from how many rows exist, so a cancelled
    invoice still burns its number — a gap in the sequence is a question the
    shop can answer, a reused number is one it cannot.
    """
    today = today or dt.datetime.now(BANGKOK).date()
    prefix = f"{today.year % 100:02d}{today.month:02d}"
    highest = conn.execute(
        "SELECT number FROM tax_invoices WHERE number LIKE ? ORDER BY number DESC LIMIT 1",
        (f"{prefix}-%",)).fetchone()
    count = int(highest[0].split("-")[1]) if highest else 0
    return f"{prefix}-{count + 1:04d}"


def _text(value: Any, field: str, limit: int, *, multiline: bool = False) -> str:
    text = str(value or "")
    text = text.strip() if multiline else " ".join(text.split())
    if len(text) > limit:
        raise InvoiceError(f"{field} ยาวเกิน {limit} ตัวอักษร")
    return text


def issue(conn: sqlite3.Connection, *, order_no: str, branch_id: int, staff_id: int,
          seller: dict, buyer: dict, today: dt.date | None = None) -> dict:
    """Turn a paid bill into a numbered invoice, once.

    The seller has to be a registered one: an invoice without the seller's tax
    number is not a tax invoice, and printing it anyway is how a shop finds out
    at the end of the year.
    """
    if not seller.get("tax_id"):
        raise InvoiceError("ร้านยังไม่ได้ใส่เลขประจำตัวผู้เสียภาษีในหน้าตั้งค่า "
                           "ใบกำกับภาษีเต็มรูปต้องมีเลขนี้", 409)
    if not seller.get("address"):
        raise InvoiceError("ร้านยังไม่ได้ใส่ที่อยู่ในหน้าตั้งค่า "
                           "ใบกำกับภาษีเต็มรูปต้องมีที่อยู่ผู้ขาย", 409)

    existing = conn.execute("SELECT id FROM tax_invoices WHERE order_no=?", (order_no,)).fetchone()
    if existing:
        # Handing the same one back is right: the customer asking twice wants
        # the document, not a second one that would not survive an audit.
        return detail(conn, existing[0])

    bill = conn.execute(
        "SELECT total_amount, subtotal_cents, discount_cents, service_charge_cents, vat_cents"
        " FROM order_events WHERE order_no=? AND branch_id=?", (order_no, branch_id)).fetchone()
    if bill is None:
        raise InvoiceError("ไม่พบบิลนี้", 404)
    paid = conn.execute("SELECT 1 FROM pos_orders WHERE order_no=? AND status='paid'",
                        (order_no,)).fetchone()
    if not paid:
        raise InvoiceError("ออกใบกำกับภาษีได้เฉพาะบิลที่ชำระเงินแล้ว", 409)

    buyer_name = _text(buyer.get("name"), "ชื่อผู้ซื้อ", 200)
    if not buyer_name:
        raise InvoiceError("ต้องใส่ชื่อผู้ซื้อ")
    buyer_tax = re.sub(r"[\s-]", "", str(buyer.get("tax_id") or ""))
    if buyer_tax and not valid_tax_id(buyer_tax):
        raise InvoiceError("เลขประจำตัวผู้เสียภาษีของผู้ซื้อไม่ถูกต้อง")

    lines = [{"name": row[0], "qty": row[1], "price": row[2],
              "amount": round(row[1] * row[2], 2)}
             for row in conn.execute(
                 "SELECT name,quantity,unit_price FROM order_items WHERE order_no=?", (order_no,))]

    number = next_number(conn, today)
    cursor = conn.execute(
        "INSERT INTO tax_invoices (number, order_no, branch_id, issued_by, buyer_name,"
        " buyer_tax_id, buyer_address, buyer_branch, seller_json, subtotal_cents,"
        " discount_cents, service_charge_cents, vat_cents, total_cents, vat_rate_bp,"
        " vat_inclusive, lines_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (number, order_no, branch_id, staff_id, buyer_name, buyer_tax,
         _text(buyer.get("address"), "ที่อยู่ผู้ซื้อ", 300, multiline=True),
         _text(buyer.get("branch"), "สาขาของผู้ซื้อ", 60) or HEAD_OFFICE,
         json.dumps(seller, ensure_ascii=False),
         bill[1], bill[2], bill[3], bill[4], round(bill[0] * 100),
         int(seller.get("vat_rate_bp") or 0), int(bool(seller.get("vat_inclusive", True))),
         json.dumps(lines, ensure_ascii=False)))
    return detail(conn, cursor.lastrowid)


def detail(conn: sqlite3.Connection, invoice_id: int) -> dict:
    row = conn.execute(
        "SELECT id,number,order_no,branch_id,issued_by,issued_at,buyer_name,buyer_tax_id,"
        "buyer_address,buyer_branch,seller_json,subtotal_cents,discount_cents,"
        "service_charge_cents,vat_cents,total_cents,vat_rate_bp,vat_inclusive,lines_json,"
        "cancelled_at,cancel_reason FROM tax_invoices WHERE id=?", (invoice_id,)).fetchone()
    if row is None:
        raise InvoiceError("ไม่พบใบกำกับภาษีนี้", 404)
    return {
        "id": row[0], "number": row[1], "order_no": row[2], "branch_id": row[3],
        "issued_by": row[4], "issued_at": row[5],
        "buyer": {"name": row[6], "tax_id": row[7], "address": row[8], "branch": row[9]},
        "seller": json.loads(row[10]),
        "subtotal": row[11] / 100, "discount": row[12] / 100,
        "service_charge": row[13] / 100, "vat": row[14] / 100, "total": row[15] / 100,
        "vat_rate_bp": row[16], "vat_inclusive": bool(row[17]),
        "lines": json.loads(row[18]),
        "cancelled_at": row[19], "cancel_reason": row[20],
    }


def by_number(conn: sqlite3.Connection, number: str) -> dict:
    row = conn.execute("SELECT id FROM tax_invoices WHERE number=?", (number,)).fetchone()
    if row is None:
        raise InvoiceError("ไม่พบใบกำกับภาษีเลขนี้", 404)
    return detail(conn, row[0])


def cancel(conn: sqlite3.Connection, number: str, reason: str) -> dict:
    """Mark it void. The row stays and the number stays used.

    Deleting it would free the number to be issued again, and two documents
    with one number is exactly what an audit looks for.
    """
    reason = _text(reason, "เหตุผล", 200)
    if not reason:
        raise InvoiceError("ต้องบอกเหตุผลที่ยกเลิก")
    invoice = by_number(conn, number)
    if invoice["cancelled_at"]:
        raise InvoiceError("ใบนี้ถูกยกเลิกไปแล้ว", 409)
    conn.execute("UPDATE tax_invoices SET cancelled_at=strftime('%Y-%m-%d %H:%M:%f','now'),"
                 " cancel_reason=? WHERE id=?", (reason, invoice["id"]))
    return detail(conn, invoice["id"])


def listing(conn: sqlite3.Connection, branch_id: int | None = None, limit: int = 50) -> list[dict]:
    sql = "SELECT id FROM tax_invoices"
    params: list = []
    if branch_id is not None:
        sql += " WHERE branch_id=?"
        params.append(branch_id)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(max(1, min(int(limit), 200)))
    return [detail(conn, row[0]) for row in conn.execute(sql, params)]
