"""รายงานภาษีขาย และไฟล์ส่งบัญชี

ร้านที่จดทะเบียน VAT ต้องทำรายงานภาษีขายทุกเดือน และยื่น ภ.พ.30 ภายในวันที่ 15
ของเดือนถัดไป ของเดิมร้านต้องนั่งไล่บิลทีละใบจากหน้ารายงานยอดขาย แล้วพิมพ์ลง
Excel เอง ซึ่งนอกจากกินเวลาทั้งวันแล้ว ยังเป็นที่ที่ตัวเลขเพี้ยนได้เงียบ ๆ

รูปแบบการลงรายการมาจากประกาศอธิบดีกรมสรรพากร (ฉบับที่ 89) ซึ่งแยกสามกรณี:
- ใบกำกับภาษีเต็มรูป ลงเป็นรายใบ (ข้อ 7(1)) พร้อมเลขผู้เสียภาษีและสถานประกอบการ
  ของผู้ซื้อ เมื่อผู้ซื้อเป็นผู้ประกอบการจดทะเบียน (ข้อ 2/2)
- ใบกำกับภาษีอย่างย่อ ลงยอดรวมของแต่ละวันเป็นแถวเดียว โดยบอกช่วงเลขที่ (ข้อ 7(2))
  ซึ่งเป็นกรณีของร้านอาหารแทบทุกบิล
- ใบลดหนี้ ลงเป็นรายใบ (ข้อ 7(10)) และลงเป็นยอดติดลบ เพราะเป็นการลดยอดขาย

ตัวเลขทุกตัวมาจากสิ่งที่เกิดขึ้นจริง ไม่คิดใหม่: ใบกำกับภาษีใช้ยอดตามที่ออกไป
บิลอย่างย่อใช้ยอดที่รับเงินจริงหักเงินที่คืนไปแล้ว ถ้าคิดใหม่จากเมนูวันนี้
รายงานจะไม่ตรงกับเงินที่อยู่ในบัญชีธนาคารของร้าน
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import sqlite3

BANGKOK = dt.timezone(dt.timedelta(hours=7))
BANGKOK_SHIFT = "+7 hours"
HEAD_OFFICE = "สำนักงานใหญ่"

# ชื่อคอลัมน์ตามรายงานภาษีขาย เรียงตามที่บัญชีกับสรรพากรคุ้นเคย
COLUMNS = ("ลำดับที่", "วัน เดือน ปี", "เล่มที่/เลขที่", "ชื่อผู้ซื้อสินค้า/ผู้รับบริการ",
           "เลขประจำตัวผู้เสียภาษีของผู้ซื้อ", "สถานประกอบการ",
           "มูลค่าสินค้าหรือบริการ", "จำนวนเงินภาษีมูลค่าเพิ่ม")

# คอลัมน์ของไฟล์รายบิลที่ส่งให้บัญชี — ไม่ใช่แม่แบบของโปรแกรมบัญชีเจ้าใดเจ้าหนึ่ง
# แต่เป็นทุกช่องที่บัญชีต้องใช้ จับคู่เข้าโปรแกรมไหนก็ได้
BILL_COLUMNS = ("เลขที่บิล", "วันที่", "เวลา", "โต๊ะ", "ช่องทางชำระ", "ผู้ปิดบิล",
                "มูลค่าก่อนภาษี", "ส่วนลด", "ค่าบริการ", "ภาษีมูลค่าเพิ่ม", "ยอดรวม",
                "คืนเงิน", "ยอดสุทธิ", "เลขที่ใบกำกับภาษี", "ชื่อผู้ซื้อ",
                "เลขประจำตัวผู้เสียภาษีของผู้ซื้อ", "เลขที่ใบลดหนี้")


class VatReportError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def month_range(month: str = "", today: dt.date | None = None) -> tuple[str, str, str]:
    """เดือนภาษีหนึ่งเดือน รับเป็น 2026-11 คืนวันแรก วันสุดท้าย และชื่อเดือน

    เป็นเดือนเสมอ ไม่ใช่ช่วงวันที่ตามใจ เพราะรายงานภาษีขายยื่นเป็นเดือนภาษี
    ช่วงคร่อมเดือนไม่มีความหมายในแบบ ภ.พ.30 และเป็นที่มาของการยื่นผิด
    """
    today = today or dt.datetime.now(BANGKOK).date()
    text = str(month or "").strip() or f"{today.year:04d}-{today.month:02d}"
    try:
        year, number = (int(part) for part in text.split("-", 1))
        first = dt.date(year, number, 1)
    except (TypeError, ValueError):
        raise VatReportError("เดือนภาษีต้องเป็นแบบ 2026-11") from None
    if not 2000 <= year <= 2999:
        raise VatReportError("เดือนภาษีไม่ถูกต้อง")
    last = dt.date(year + (number == 12), number % 12 + 1, 1) - dt.timedelta(days=1)
    return first.isoformat(), last.isoformat(), text


def _seller(conn: sqlite3.Connection, branch_id: int, seller: dict) -> dict:
    """ผู้ประกอบการตามที่หัวรายงานต้องบอก และด่านที่กันร้านที่ไม่ได้จด VAT ออกไป

    ``seller`` คือก้อนเดียวกับที่ใบกำกับภาษีใช้ ไม่อ่านการตั้งค่าซ้ำเอง — สองที่
    ที่อ่านชื่อร้านคนละทางคือสองชื่อร้านบนเอกสารที่ยื่นสรรพากร
    """
    if not seller.get("tax_id") or not int(seller.get("vat_rate_bp") or 0):
        # ร้านที่ไม่ได้จดทะเบียน VAT ไม่ต้องทำรายงานนี้ และไม่ควรได้ไฟล์ที่ดูเหมือน
        # ว่าทำแล้ว เพราะเป็นเอกสารที่ยื่นต่อสรรพากร
        raise VatReportError("ร้านนี้ยังไม่ได้ใส่เลขประจำตัวผู้เสียภาษีหรืออัตรา VAT "
                             "ในหน้าตั้งค่า รายงานภาษีขายใช้ได้เฉพาะร้านที่จดทะเบียน VAT", 409)
    branch = conn.execute("SELECT name FROM branches WHERE id=?", (branch_id,)).fetchone()
    return {"name": seller.get("name", ""), "tax_id": seller["tax_id"],
            "place": seller.get("branch") or HEAD_OFFICE,
            "branch_name": branch[0] if branch else "",
            "vat_rate_bp": int(seller["vat_rate_bp"]),
            "address": seller.get("address", "")}


def _full_invoices(conn: sqlite3.Connection, branch_id: int, start: str, end: str) -> list[dict]:
    """ใบกำกับภาษีเต็มรูป ลงเป็นรายใบตามข้อ 7(1)

    ใช้ยอดตามที่ออกใบไป ไม่หักเงินที่คืนทีหลัง เพราะการคืนเงินมีใบลดหนี้ของตัวเอง
    ที่ลงเป็นแถวติดลบ การหักสองที่คือการหักซ้ำ
    """
    rows = conn.execute(
        "SELECT number,issued_at,buyer_name,buyer_tax_id,buyer_branch,total_cents,vat_cents"
        " FROM tax_invoices WHERE branch_id=? AND cancelled_at IS NULL"
        f" AND date(issued_at, '{BANGKOK_SHIFT}') BETWEEN ? AND ?"
        " ORDER BY issued_at, number", (branch_id, start, end)).fetchall()
    return [{"kind": "full", "at": row[1], "day": _day_of(row[1]), "number": row[0],
             "buyer": row[2], "buyer_tax_id": row[3],
             "place": row[4] or HEAD_OFFICE,
             "value_cents": row[5] - row[6], "vat_cents": row[6]}
            for row in rows]


def _credit_notes(conn: sqlite3.Connection, branch_id: int, start: str, end: str) -> list[dict]:
    """ใบลดหนี้ ลงเป็นรายใบตามข้อ 7(10) และเป็นยอดติดลบ เพราะเป็นการลดยอดขาย"""
    rows = conn.execute(
        "SELECT c.number,c.issued_at,c.diff_total_cents,c.diff_vat_cents,"
        "i.buyer_name,i.buyer_tax_id,i.buyer_branch,i.number"
        " FROM credit_notes c JOIN tax_invoices i ON i.id=c.tax_invoice_id"
        " WHERE c.branch_id=? AND c.cancelled_at IS NULL"
        f" AND date(c.issued_at, '{BANGKOK_SHIFT}') BETWEEN ? AND ?"
        " ORDER BY c.issued_at, c.number", (branch_id, start, end)).fetchall()
    return [{"kind": "credit", "at": row[1], "day": _day_of(row[1]),
             "number": f"{row[0]} (ลดใบ {row[7]})",
             "buyer": row[4], "buyer_tax_id": row[5], "place": row[6] or HEAD_OFFICE,
             "value_cents": -(row[2] - row[3]), "vat_cents": -row[3]}
            for row in rows]


def _abbreviated(conn: sqlite3.Connection, branch_id: int, start: str, end: str) -> list[dict]:
    """บิลที่ไม่ได้ออกใบกำกับภาษีเต็มรูป ลงยอดรวมวันละแถวตามข้อ 7(2)

    ใช้ยอดที่รับเงินจริงหักเงินที่คืนไปแล้ว เพราะบิลพวกนี้ไม่มีใบลดหนี้มาลบให้
    บิลที่คืนเงินครบทั้งใบไม่อยู่ในนี้อยู่แล้ว เพราะสถานะไม่ใช่ paid
    """
    where = ("p.branch_id=? AND p.status='paid'"
             f" AND date(p.closed_at, '{BANGKOK_SHIFT}') BETWEEN ? AND ?"
             " AND NOT EXISTS (SELECT 1 FROM tax_invoices t WHERE t.order_no=p.order_no"
             " AND t.cancelled_at IS NULL)")
    scope = (branch_id, start, end)
    sold = conn.execute(
        f"SELECT date(p.closed_at, '{BANGKOK_SHIFT}') AS day,"
        " COUNT(*), SUM(CAST(ROUND(e.total_amount*100) AS INTEGER)), SUM(e.vat_cents),"
        " MIN(p.order_no), MAX(p.order_no)"
        " FROM pos_orders p JOIN order_events e ON e.order_no=p.order_no"
        f" WHERE {where} GROUP BY day ORDER BY day", scope).fetchall()
    # เงินที่คืนไปของบิลพวกนี้ นับตามวันของบิล ไม่ใช่วันที่คืน เพื่อให้แถวของวันนั้น
    # เท่ากับเงินที่ร้านได้จริงจากการขายของวันนั้น
    given = dict(conn.execute(
        f"SELECT date(p.closed_at, '{BANGKOK_SHIFT}') AS day,"
        " SUM(r.amount_cents) || ':' || SUM(r.vat_cents)"
        " FROM order_refunds r JOIN pos_orders p ON p.order_no=r.order_no"
        f" WHERE {where} GROUP BY day", scope).fetchall())
    rows = []
    for day, bills, total_cents, vat_cents, first_no, last_no in sold:
        back_total, back_vat = (int(part) for part in given.get(day, "0:0").split(":"))
        total_cents = (total_cents or 0) - back_total
        vat_cents = (vat_cents or 0) - back_vat
        if total_cents <= 0 and vat_cents <= 0:
            continue
        span = f"เลขที่ {_short(first_no)} ถึงเลขที่ {_short(last_no)}" if bills > 1 \
            else f"เลขที่ {_short(first_no)}"
        rows.append({"kind": "abbreviated", "at": day, "day": day, "number": span,
                     "buyer": f"ขายปลีกตามใบกำกับภาษีอย่างย่อ ({bills} ใบ)",
                     "buyer_tax_id": "", "place": "",
                     "value_cents": total_cents - vat_cents, "vat_cents": vat_cents})
    return rows


def _short(order_no: str) -> str:
    """เลขบิลที่คนอ่านออก ตัวเดียวกับที่พิมพ์บนใบเสร็จ"""
    text = str(order_no or "")
    return text[-5:].upper() if len(text) > 5 else text.upper()


def _day_of(stamp: str) -> str:
    text = str(stamp or "").replace("T", " ")
    try:
        moment = dt.datetime.fromisoformat(text[:19]).replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return text[:10]
    return moment.astimezone(BANGKOK).date().isoformat()


def sales_vat_report(conn: sqlite3.Connection, branch_id: int, *, seller: dict,
                     month: str = "", today: dt.date | None = None) -> dict:
    """รายงานภาษีขายของเดือนภาษีหนึ่งเดือน พร้อมตัวเลขที่ต้องกรอกใน ภ.พ.30"""
    start, end, label = month_range(month, today)
    seller = _seller(conn, branch_id, seller)
    rows = (_full_invoices(conn, branch_id, start, end)
            + _abbreviated(conn, branch_id, start, end)
            + _credit_notes(conn, branch_id, start, end))
    rows.sort(key=lambda row: (row["day"], row["kind"] != "abbreviated", row["number"]))
    for index, row in enumerate(rows, start=1):
        row["no"] = index
        row["value"] = row["value_cents"] / 100
        row["vat"] = row["vat_cents"] / 100
    value_cents = sum(row["value_cents"] for row in rows)
    vat_cents = sum(row["vat_cents"] for row in rows)
    return {
        "branch_id": branch_id, "month": label, "start": start, "end": end,
        "seller": seller, "columns": list(COLUMNS), "rows": rows,
        "totals": {"value": value_cents / 100, "vat": vat_cents / 100,
                   "entries": len(rows)},
        # ตัวเลขที่กรอกลงแบบ ภ.พ.30 ตรง ๆ — ร้านอาหารขายของที่เสียภาษีทั้งหมด
        # ยอดขายที่ได้รับยกเว้นจึงเป็นศูนย์ ถ้าร้านขายของยกเว้นด้วยต้องแยกเอง
        "pp30": {"total_sales": value_cents / 100,
                 "taxable_sales": value_cents / 100,
                 "output_tax": vat_cents / 100,
                 "vat_rate": seller["vat_rate_bp"] / 100},
    }


def report_csv(report: dict) -> str:
    """รายงานภาษีขายเป็น CSV ที่เปิดใน Excel แล้วภาษาไทยไม่เพี้ยน"""
    out = io.StringIO()
    writer = csv.writer(out)
    seller = report["seller"]
    writer.writerow(["รายงานภาษีขาย"])
    writer.writerow(["ชื่อผู้ประกอบการ", seller["name"]])
    writer.writerow(["เลขประจำตัวผู้เสียภาษี", seller["tax_id"]])
    writer.writerow(["ชื่อสถานประกอบการ", seller["branch_name"]])
    writer.writerow(["สถานประกอบการ", seller["place"]])
    writer.writerow(["เดือนภาษี", report["month"]])
    writer.writerow([])
    writer.writerow(list(COLUMNS))
    for row in report["rows"]:
        writer.writerow([row["no"], row["day"], row["number"], row["buyer"],
                         row["buyer_tax_id"], row["place"],
                         f"{row['value']:.2f}", f"{row['vat']:.2f}"])
    writer.writerow([])
    writer.writerow(["", "", "", "", "", "รวม",
                     f"{report['totals']['value']:.2f}", f"{report['totals']['vat']:.2f}"])
    return out.getvalue()


def bills_csv(conn: sqlite3.Connection, branch_id: int, start: str, end: str) -> str:
    """ทุกบิลที่รับเงินในช่วงนี้ หนึ่งบรรทัดต่อบิล สำหรับส่งให้บัญชี

    ไม่ใช่แม่แบบนำเข้าของโปรแกรมบัญชีเจ้าใดเจ้าหนึ่ง เพราะแม่แบบพวกนั้นเปลี่ยนได้
    ตลอดและผิดนิดเดียวก็นำเข้าไม่ผ่าน ไฟล์นี้มีทุกช่องที่บัญชีต้องใช้ ให้จับคู่
    คอลัมน์เข้าโปรแกรมไหนก็ได้ ซึ่งทำครั้งเดียวแล้วใช้ได้ตลอด
    """
    rows = conn.execute(
        "SELECT p.order_no, p.closed_at, e.table_no, p.payment_method, s.name,"
        " e.subtotal_cents, e.discount_cents, e.service_charge_cents, e.vat_cents,"
        " CAST(ROUND(e.total_amount*100) AS INTEGER), p.status,"
        " (SELECT COALESCE(SUM(r.amount_cents),0) FROM order_refunds r"
        "   WHERE r.order_no=p.order_no),"
        " (SELECT t.number FROM tax_invoices t WHERE t.order_no=p.order_no"
        "   AND t.cancelled_at IS NULL),"
        " (SELECT t.buyer_name FROM tax_invoices t WHERE t.order_no=p.order_no"
        "   AND t.cancelled_at IS NULL),"
        " (SELECT t.buyer_tax_id FROM tax_invoices t WHERE t.order_no=p.order_no"
        "   AND t.cancelled_at IS NULL),"
        " (SELECT GROUP_CONCAT(c.number) FROM credit_notes c"
        "   WHERE c.order_no=p.order_no AND c.cancelled_at IS NULL)"
        " FROM pos_orders p JOIN order_events e ON e.order_no=p.order_no"
        " LEFT JOIN staffs s ON s.id=p.closed_by_staff_id"
        " WHERE p.branch_id=?"
        f" AND date(p.closed_at, '{BANGKOK_SHIFT}') BETWEEN ? AND ?"
        " ORDER BY p.closed_at", (branch_id, start, end)).fetchall()
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(list(BILL_COLUMNS))
    for row in rows:
        stamp = _stamp(row[1])
        refunded = row[11] or 0
        total = row[9] or 0
        # บิลที่คืนเงินครบทั้งใบ ยอดสุทธิเป็นศูนย์ ไม่ใช่ยอดเดิม
        net = 0 if row[10] == "refunded" else total - refunded
        writer.writerow([
            _short(row[0]), stamp[:10], stamp[11:16], row[2] or "", row[3] or "",
            row[4] or "", f"{(row[5] or 0) / 100:.2f}", f"{(row[6] or 0) / 100:.2f}",
            f"{(row[7] or 0) / 100:.2f}", f"{(row[8] or 0) / 100:.2f}",
            f"{total / 100:.2f}",
            f"{(total if row[10] == 'refunded' else refunded) / 100:.2f}",
            f"{net / 100:.2f}", row[12] or "", row[13] or "", row[14] or "", row[15] or ""])
    return out.getvalue()


def _stamp(value: str) -> str:
    """เวลาที่เก็บเป็น UTC อ่านเป็นเวลาไทย เพราะบัญชีอ่านวันที่ตามปฏิทินร้าน"""
    text = str(value or "").replace("T", " ")
    try:
        moment = dt.datetime.fromisoformat(text[:19]).replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return text[:16]
    return moment.astimezone(BANGKOK).strftime("%Y-%m-%d %H:%M")


# Excel บนวินโดวส์ภาษาไทยอ่าน CSV เป็น UTF-8 ก็ต่อเมื่อมี BOM นำหน้า
# ไม่มีแล้วชื่อเมนูกับชื่อลูกค้ากลายเป็นตัวประหลาดทั้งไฟล์
def as_download(text: str) -> bytes:
    return ("﻿" + text).encode("utf-8")
