"""รายงานยอดขายตามช่วงวันที่ พร้อมกำไรเท่าที่รู้ต้นทุนจริง

The dashboard a shop already had answers one question: how is today going.
An owner closing the month needs the other one — what did these thirty days
do, which dishes earned their place, which did not, and who sold them.

Profit is reported only from the cost recorded on the bill at the time of the
sale. A dish whose cost was never filled in is counted separately and said
out loud, because a profit figure that silently treats an unknown cost as zero
reads as a very profitable shop right up until the owner believes it.

SQLite timestamps are UTC. A Thai shop's day runs on UTC+7, so every date
comparison shifts first — otherwise a bill at 1am Thai time lands on the
previous day's report.
"""

from __future__ import annotations

import datetime as dt
import sqlite3

BANGKOK_SHIFT = "+7 hours"
BUSINESS_DATE = f"date(closed_at, '{BANGKOK_SHIFT}')"
MAX_DAYS = 400


class ReportError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _day(value, field: str) -> str:
    try:
        return dt.date.fromisoformat(str(value)).isoformat()
    except (TypeError, ValueError):
        raise ReportError(f"{field} ต้องเป็นวันที่แบบ 2026-11-09") from None


def date_range(start=None, end=None, today: dt.date | None = None) -> tuple[str, str]:
    """A sane window, defaulting to the last thirty days ending today."""
    today = today or dt.datetime.now(dt.timezone(dt.timedelta(hours=7))).date()
    end_day = _day(end, "วันที่สิ้นสุด") if end else today.isoformat()
    start_day = _day(start, "วันที่เริ่ม") if start else (
        dt.date.fromisoformat(end_day) - dt.timedelta(days=29)).isoformat()
    if start_day > end_day:
        raise ReportError("วันที่เริ่มต้องไม่เกินวันที่สิ้นสุด")
    span = (dt.date.fromisoformat(end_day) - dt.date.fromisoformat(start_day)).days + 1
    if span > MAX_DAYS:
        raise ReportError(f"ขอรายงานได้ครั้งละไม่เกิน {MAX_DAYS} วัน")
    return start_day, end_day


def _rows(conn: sqlite3.Connection, sql: str, params: tuple) -> list[tuple]:
    return conn.execute(sql, params).fetchall()


def sales_report(conn: sqlite3.Connection, branch_id: int, *,
                 start=None, end=None, today: dt.date | None = None) -> dict:
    """Everything the owner asked of a date range, in one read."""
    start_day, end_day = date_range(start, end, today)
    # Only bills that were actually paid and not reversed. A voided bill that
    # still counted would make every refund look like a sale.
    where = (f"branch_id=? AND status='paid'"
             f" AND {BUSINESS_DATE} BETWEEN ? AND ?")
    scope = (branch_id, start_day, end_day)

    totals = _rows(conn, f"SELECT COUNT(*), COALESCE(SUM(net_amount),0) FROM pos_orders WHERE {where}",
                   scope)[0]
    bills, revenue = totals[0], round(totals[1] or 0, 2)

    by_day = [{"date": row[0], "bills": row[1], "revenue": round(row[2] or 0, 2)}
              for row in _rows(conn,
                               f"SELECT {BUSINESS_DATE} AS day, COUNT(*), COALESCE(SUM(net_amount),0)"
                               f" FROM pos_orders WHERE {where} GROUP BY day ORDER BY day", scope)]

    by_method = [{"method": row[0] or "ไม่ระบุ", "bills": row[1], "revenue": round(row[2] or 0, 2)}
                 for row in _rows(conn,
                                  f"SELECT payment_method, COUNT(*), COALESCE(SUM(net_amount),0)"
                                  f" FROM pos_orders WHERE {where}"
                                  f" GROUP BY payment_method ORDER BY 3 DESC", scope)]

    # Qualified with the table name because these queries join, and an
    # unqualified column that resolves today breaks the day a joined table
    # gains a column of the same name.
    bill_where = (f"p.branch_id=? AND p.status='paid'"
                  f" AND date(p.closed_at, '{BANGKOK_SHIFT}') BETWEEN ? AND ?")

    by_staff = [{"staff_id": row[0], "name": row[1] or "ไม่ระบุ", "bills": row[2],
                 "revenue": round(row[3] or 0, 2)}
                for row in _rows(conn,
                                 f"SELECT p.closed_by_staff_id, s.name, COUNT(*),"
                                 f" COALESCE(SUM(p.net_amount),0) FROM pos_orders p"
                                 f" LEFT JOIN staffs s ON s.id=p.closed_by_staff_id"
                                 f" WHERE {bill_where}"
                                 f" GROUP BY p.closed_by_staff_id, s.name ORDER BY 4 DESC", scope)]

    # Item lines of those same bills, which is where categories and cost live.
    line_where = bill_where
    by_item = [{"id": row[0], "name": row[1], "qty": round(row[2] or 0, 2),
                "revenue": round(row[3] or 0, 2), "cost": round(row[4] or 0, 2),
                "profit": round((row[3] or 0) - (row[4] or 0), 2)}
               for row in _rows(conn,
                                f"SELECT i.item_id, i.name, SUM(i.quantity),"
                                f" SUM(i.quantity*i.unit_price), SUM(i.quantity*i.unit_cost)"
                                f" FROM order_items i JOIN pos_orders p ON p.order_no=i.order_no"
                                f" WHERE {line_where} GROUP BY i.item_id, i.name"
                                f" ORDER BY 4 DESC LIMIT 100", scope)]

    by_category = [{"category": row[0] or "ไม่ระบุหมวด", "qty": round(row[1] or 0, 2),
                    "revenue": round(row[2] or 0, 2)}
                   for row in _rows(conn,
                                    f"SELECT COALESCE(NULLIF(m.category,''),'ไม่ระบุหมวด'),"
                                    f" SUM(i.quantity), SUM(i.quantity*i.unit_price)"
                                    f" FROM order_items i JOIN pos_orders p ON p.order_no=i.order_no"
                                    f" LEFT JOIN menu_catalog m"
                                    f" ON m.item_id=i.item_id AND m.branch_id=p.branch_id"
                                    f" WHERE {line_where} GROUP BY 1 ORDER BY 3 DESC", scope)]

    # How much of the range we can speak about at all. Lines sold before costs
    # were recorded, or whose cost was left at zero, are named rather than
    # folded into the profit as if they cost nothing.
    cost_known = _rows(conn,
                       f"SELECT COALESCE(SUM(CASE WHEN i.unit_cost > 0"
                       f" THEN i.quantity*i.unit_price ELSE 0 END),0),"
                       f" COALESCE(SUM(CASE WHEN i.unit_cost > 0 THEN i.quantity*i.unit_cost ELSE 0 END),0),"
                       f" COALESCE(SUM(CASE WHEN i.unit_cost > 0 THEN 0 ELSE i.quantity*i.unit_price END),0)"
                       f" FROM order_items i JOIN pos_orders p ON p.order_no=i.order_no"
                       f" WHERE {line_where}", scope)[0]
    priced_revenue, priced_cost, unpriced_revenue = (round(value or 0, 2) for value in cost_known)

    return {
        "branch_id": branch_id, "start": start_day, "end": end_day,
        "bills": bills, "revenue": revenue,
        "average_bill": round(revenue / bills, 2) if bills else 0,
        "by_day": by_day, "by_method": by_method, "by_staff": by_staff,
        "by_item": by_item, "by_category": by_category,
        "profit": {
            # Only the part of the range whose cost the shop actually knows.
            "revenue_with_cost": priced_revenue,
            "cost": priced_cost,
            "gross_profit": round(priced_revenue - priced_cost, 2),
            "margin_percent": round((priced_revenue - priced_cost) / priced_revenue * 100, 2)
                              if priced_revenue > 0 else None,
            "revenue_without_cost": unpriced_revenue,
            "complete": unpriced_revenue == 0,
        },
    }


def sales_csv(report: dict) -> str:
    """The same report as a file the owner's accountant can open.

    Written by hand rather than with csv.writer so the column order is the one
    a person reads top to bottom, and so the file starts with the range it
    covers — a spreadsheet with no dates on it gets filed and then disbelieved.
    """
    def row(*cells) -> str:
        out = []
        for cell in cells:
            text = "" if cell is None else str(cell)
            if any(ch in text for ch in ',"\n'):
                text = '"' + text.replace('"', '""') + '"'
            out.append(text)
        return ",".join(out)

    lines = [row("รายงานยอดขาย", f"{report['start']} ถึง {report['end']}"),
             row("จำนวนบิล", report["bills"]),
             row("ยอดขายรวม", report["revenue"]),
             row("เฉลี่ยต่อบิล", report["average_bill"]),
             row("กำไรขั้นต้น (เฉพาะที่รู้ต้นทุน)", report["profit"]["gross_profit"]),
             row("ยอดขายที่ยังไม่รู้ต้นทุน", report["profit"]["revenue_without_cost"]),
             ""]
    lines += [row("วันที่", "บิล", "ยอดขาย")]
    lines += [row(day["date"], day["bills"], day["revenue"]) for day in report["by_day"]]
    lines += ["", row("ช่องทางชำระ", "บิล", "ยอดขาย")]
    lines += [row(m["method"], m["bills"], m["revenue"]) for m in report["by_method"]]
    lines += ["", row("พนักงาน", "บิล", "ยอดขาย")]
    lines += [row(s["name"], s["bills"], s["revenue"]) for s in report["by_staff"]]
    lines += ["", row("หมวด", "จำนวน", "ยอดขาย")]
    lines += [row(c["category"], c["qty"], c["revenue"]) for c in report["by_category"]]
    lines += ["", row("สินค้า", "จำนวน", "ยอดขาย", "ต้นทุน", "กำไร")]
    lines += [row(i["name"], i["qty"], i["revenue"], i["cost"], i["profit"]) for i in report["by_item"]]
    return "\n".join(lines) + "\n"
