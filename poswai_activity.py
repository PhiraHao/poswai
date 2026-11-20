"""บันทึกว่าใครทำอะไรกับเงินและของในร้าน

เหตุผลอันดับหนึ่งที่เจ้าของร้านไทยซื้อ POS คือกันพนักงานโกง ไม่ใช่ดูรายงานยอดขาย
ของเดิมตอบได้ครึ่งเดียว — กะกับลิ้นชักบอกว่า "เงินหาย" แต่ไม่บอกว่าหายตรงไหน
เพราะไม่มีที่ไหนจดว่าใครกดส่วนลด ใครแก้ราคาเมนู ใครนับสต็อกใหม่ ใครเปิดลิ้นชัก

หนึ่งตารางสำหรับทุกการกระทำที่แตะเงินหรือของ เพราะสิบตารางที่ต้องไปไล่ดูทีละที่
คือสิ่งที่ไม่มีใครเปิดดู แถวในนี้เขียนอย่างเดียว ไม่มีทางลบหรือแก้จาก API ไหน
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
from typing import Any

BANGKOK_SHIFT = "+7 hours"

# คำอธิบายภาษาไทยอยู่ที่นี่ที่เดียว หน้าจอจึงไม่ต้องเดาชื่อเอง และรายงานกับ
# หน้าจอเรียกสิ่งเดียวกันด้วยคำเดียวกันเสมอ
ACTIONS: dict[str, str] = {
    "discount": "ให้ส่วนลด",
    "void": "ยกเลิกบิลก่อนรับเงิน",
    "refund": "คืนเงินบิลที่ชำระแล้ว",
    "menu_price": "แก้ราคาเมนู",
    "shop_settings": "แก้ตั้งค่าร้าน",
    "stock_set": "ตั้งยอดสต็อกเอง",
    "cash_in": "นำเงินเข้าลิ้นชัก",
    "cash_out": "นำเงินออกลิ้นชัก",
    "shift_open": "เปิดกะ",
    "shift_close": "ปิดกะ",
    "tax_invoice_cancel": "ยกเลิกใบกำกับภาษี",
    "po_cancel": "ยกเลิกใบสั่งซื้อ",
    "transfer_cancel": "ยกเลิกใบโอน",
    "pin_reset": "ตั้งรหัสพนักงานใหม่",
    "role_change": "เปลี่ยนตำแหน่งพนักงาน",
    "points_change": "แก้แต้มสมาชิก",
    "manager_override": "ผู้จัดการอนุมัติด้วยรหัส",
    "split_bill": "แยกบิล",
    "move_table": "ย้ายโต๊ะ",
    "merge_bill": "รวมบิล",
    "refund_partial": "คืนเงินบางส่วน",
    "credit_note": "ออกใบลดหนี้",
}


class ActivityError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def init(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS staff_activity (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        branch_id INTEGER NOT NULL,
        staff_id INTEGER,
        staff_name TEXT NOT NULL DEFAULT '',
        staff_role TEXT NOT NULL DEFAULT '',
        action TEXT NOT NULL,
        subject TEXT NOT NULL DEFAULT '',
        detail TEXT NOT NULL DEFAULT '',
        amount_cents INTEGER NOT NULL DEFAULT 0,
        extra_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL
            DEFAULT (strftime('%Y-%m-%d %H:%M:%f','now')))""")
    # เรียงตามเวลาเสมอ และกรองตามคนหรือตามชนิดการกระทำได้โดยไม่ต้องสแกนทั้งตาราง
    conn.execute("CREATE INDEX IF NOT EXISTS staff_activity_by_time"
                 " ON staff_activity(branch_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS staff_activity_by_staff"
                 " ON staff_activity(staff_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS staff_activity_by_action"
                 " ON staff_activity(action, created_at)")


def _text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def record(conn: sqlite3.Connection, *, branch_id: int, staff: dict | None,
           action: str, subject: str = "", detail: str = "",
           amount_cents: int = 0, **extra: Any) -> None:
    """จดหนึ่งการกระทำ

    ชื่อกับตำแหน่งของคนทำถูกคัดลอกมาเก็บไว้ตรงนี้ด้วย ไม่ใช่อ้างถึงตาราง staffs
    อย่างเดียว เพราะพนักงานลาออกแล้วถูกลบหรือเปลี่ยนตำแหน่งได้ แต่บันทึกต้อง
    บอกได้เสมอว่าตอนนั้นเป็นใครและตำแหน่งอะไร
    """
    if action not in ACTIONS:
        raise ActivityError(f"ไม่รู้จักการกระทำ {action}")
    conn.execute(
        "INSERT INTO staff_activity (branch_id, staff_id, staff_name, staff_role,"
        " action, subject, detail, amount_cents, extra_json)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (int(branch_id), (staff or {}).get("id"), _text((staff or {}).get("name"), 80),
         _text((staff or {}).get("role"), 20), action, _text(subject, 120),
         _text(detail, 300), int(amount_cents or 0),
         json.dumps(extra, ensure_ascii=False) if extra else "{}"))


def _day(value, fallback: dt.date) -> str:
    try:
        return dt.date.fromisoformat(str(value)).isoformat()
    except (TypeError, ValueError):
        return fallback.isoformat()


def listing(conn: sqlite3.Connection, *, branch_id: int | None = None,
            start=None, end=None, action: str = "", staff_id: int | None = None,
            limit: int = 200, today: dt.date | None = None) -> dict:
    """สิ่งที่เกิดขึ้นในช่วงวันที่ถาม ใหม่สุดก่อน

    วันทำการนับตามเวลาไทย เหมือนรายงานยอดขาย ไม่ใช่วัน UTC ของเครื่อง
    """
    today = today or dt.datetime.now(dt.timezone(dt.timedelta(hours=7))).date()
    start_day = _day(start, today - dt.timedelta(days=7))
    end_day = _day(end, today)
    if start_day > end_day:
        start_day, end_day = end_day, start_day
    limit = max(1, min(int(limit or 200), 500))

    where = [f"date(created_at, '{BANGKOK_SHIFT}') BETWEEN ? AND ?"]
    params: list = [start_day, end_day]
    if branch_id is not None:
        where.append("branch_id=?")
        params.append(int(branch_id))
    if action:
        if action not in ACTIONS:
            raise ActivityError(f"ไม่รู้จักการกระทำ {action}")
        where.append("action=?")
        params.append(action)
    if staff_id:
        where.append("staff_id=?")
        params.append(int(staff_id))
    clause = " AND ".join(where)

    rows = conn.execute(
        "SELECT id, branch_id, staff_id, staff_name, staff_role, action, subject,"
        " detail, amount_cents, created_at FROM staff_activity"
        f" WHERE {clause} ORDER BY created_at DESC, id DESC LIMIT ?",
        (*params, limit)).fetchall()
    entries = [{"id": row[0], "branch_id": row[1], "staff_id": row[2],
                "staff": row[3] or "ไม่ระบุ", "role": row[4], "action": row[5],
                "action_label": ACTIONS.get(row[5], row[5]), "subject": row[6],
                "detail": row[7], "amount": (row[8] or 0) / 100,
                "at": row[9]} for row in rows]

    # สรุปว่าใครทำอะไรไปกี่ครั้ง เพื่อให้เห็นรูปแบบโดยไม่ต้องอ่านทีละบรรทัด
    by_staff = [{"staff_id": row[0], "staff": row[1] or "ไม่ระบุ", "count": row[2],
                 "amount": (row[3] or 0) / 100}
                for row in conn.execute(
                    "SELECT staff_id, staff_name, COUNT(*), COALESCE(SUM(amount_cents),0)"
                    f" FROM staff_activity WHERE {clause}"
                    " GROUP BY staff_id, staff_name ORDER BY 3 DESC", params)]
    by_action = [{"action": row[0], "label": ACTIONS.get(row[0], row[0]),
                  "count": row[1], "amount": (row[2] or 0) / 100}
                 for row in conn.execute(
                     "SELECT action, COUNT(*), COALESCE(SUM(amount_cents),0)"
                     f" FROM staff_activity WHERE {clause}"
                     " GROUP BY action ORDER BY 2 DESC", params)]

    return {"start": start_day, "end": end_day, "branch_id": branch_id,
            "entries": entries, "by_staff": by_staff, "by_action": by_action,
            "actions": [{"action": key, "label": label} for key, label in ACTIONS.items()]}
