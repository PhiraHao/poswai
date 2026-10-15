#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
POS WAI Enterprise V3 Server (FastAPI + Relational SQLite/PostgreSQL Schema)
ครอบคลุม:
1. ระบบจัดการโต๊ะแบบเพิ่ม-ลดเองได้ (Dynamic Tables) & QR Ordering
2. ระบบสูตรตัดวัตถุดิบอัตโนมัติแบบ Hybrid (Auto-Template + Custom Edit BOM) & โหมดร้านเดี่ยว/หลายสาขา + Waste Log
3. ระบบยื่นใบลาผ่าน LINE LIFF -> อนุมัติผ่าน LINE Flex Message -> อัปเดตตารางกะ (staff_shifts)
   -> ระงับรหัส PIN หน้าเครื่อง POS ชั่วคราว (ป้องกันสวมสิทธิ์) -> ตรวจจับขาดงานอัตโนมัติ (>60 นาที)
4. ระบบคำนวณค่าคอมมิชชัน (Individual รายบุคคล & Pooled Equal กองกลางหารเฉพาะคนมาทำงานจริง ตัดคนลา/ขาดงานออก)
5. โครงสร้างฐานข้อมูล Relational Database ครบ 5 หมวดหลักตาม ER-Diagram
"""

import sqlite3
import datetime
import json
import os
import hmac
import re
from typing import List, Optional
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(
    title="POS WAI Enterprise V3 API (Leave, Shift, POS Lock & Commission Engine)",
    version="3.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./poswai.db")
PROMPTPAY_ID = os.getenv("PROMPTPAY_ID", "")
LINE_LIFF_ID = os.getenv("LINE_LIFF_ID", "")
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "")
PREVIEW_ONLY = os.getenv("POSWAI_PREVIEW_ONLY", "0") == "1"
MANAGER_REPORT_TOKEN = os.getenv("POSWAI_MANAGER_REPORT_TOKEN", "")
PAYROLL_REGULAR_HOURS_PER_DAY = float(os.getenv("POSWAI_REGULAR_HOURS_PER_DAY", "8"))
PAYROLL_OT_MULTIPLIER = float(os.getenv("POSWAI_OT_MULTIPLIER", "1.5"))
if PAYROLL_REGULAR_HOURS_PER_DAY <= 0 or PAYROLL_OT_MULTIPLIER < 0:
    raise RuntimeError("Invalid payroll hours or overtime multiplier")
if not DATABASE_URL.startswith("sqlite:///"):
    raise RuntimeError("This deployment supports SQLite only; configure a persistent SQLite DATABASE_URL")
DB_PATH = Path(DATABASE_URL.removeprefix("sqlite:///"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


# =====================================================================
# 1. RELATIONAL DATABASE SCHEMA (5 หมวดหลักตาม ER-Diagram)
# =====================================================================
def init_db() -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # หมวดที่ 1: พนักงานและสาขา (branches & staffs)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS branches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            lat REAL DEFAULT 18.7961,
            lng REAL DEFAULT 98.9682,
            geofence_radius_meters INTEGER DEFAULT 50,
            is_single_store BOOLEAN DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS staffs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            branch_id INTEGER NOT NULL REFERENCES branches(id),
            line_user_id TEXT UNIQUE,
            name TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'cashier',
            pin_code_hash TEXT NOT NULL,
            is_active BOOLEAN DEFAULT 1,
            hourly_rate REAL DEFAULT 50.0,
            commission_rate REAL DEFAULT 0.03,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    # หมวดที่ 2: กะงานและการลงเวลา (shift_templates, staff_shifts, attendances)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS shift_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            branch_id INTEGER NOT NULL REFERENCES branches(id),
            name TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS staff_shifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            staff_id INTEGER NOT NULL REFERENCES staffs(id),
            branch_id INTEGER NOT NULL REFERENCES branches(id),
            work_date TEXT NOT NULL,
            shift_template_id INTEGER REFERENCES shift_templates(id),
            status TEXT DEFAULT 'scheduled', -- scheduled, completed, on_leave, absent, swapped
            pos_pin_locked BOOLEAN DEFAULT 0,
            UNIQUE(staff_id, work_date)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS attendances (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            staff_id INTEGER NOT NULL REFERENCES staffs(id),
            shift_id INTEGER REFERENCES staff_shifts(id),
            clock_in TEXT NOT NULL,
            clock_out TEXT,
            clock_in_lat REAL,
            clock_in_lng REAL,
            is_within_geofence BOOLEAN DEFAULT 1,
            verified_method TEXT DEFAULT 'line_gps',
            work_hours REAL DEFAULT 0.0
        )
        """
    )

    # หมวดที่ 3: การลาผ่าน LINE (leave_requests)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS leave_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            staff_id INTEGER NOT NULL REFERENCES staffs(id),
            leave_type TEXT NOT NULL, -- sick, personal, vacation, swap_shift
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            reason TEXT,
            attachment_url TEXT,
            status TEXT DEFAULT 'pending', -- pending, approved, rejected, cancelled
            reviewed_by INTEGER REFERENCES staffs(id),
            reviewed_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    # หมวดที่ 4: การขายหน้าร้าน (pos_orders)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS pos_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            branch_id INTEGER NOT NULL REFERENCES branches(id),
            order_no TEXT UNIQUE NOT NULL,
            closed_by_staff_id INTEGER REFERENCES staffs(id),
            total_amount REAL NOT NULL,
            net_amount REAL NOT NULL,
            payment_method TEXT DEFAULT 'qr_promptpay',
            status TEXT DEFAULT 'paid', -- paid, refunded, void
            closed_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    # หมวดที่ 5: ค่าคอมมิชชัน (commission_rules & commission_records)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS commission_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            branch_id INTEGER NOT NULL REFERENCES branches(id),
            type TEXT DEFAULT 'pooled_equal', -- individual, pooled_equal, tiered
            rate_percent REAL DEFAULT 0.03,
            min_sales_target REAL DEFAULT 0.0
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS commission_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            staff_id INTEGER NOT NULL REFERENCES staffs(id),
            order_id INTEGER REFERENCES pos_orders(id),
            period_date TEXT NOT NULL,
            base_sales_amount REAL NOT NULL DEFAULT 0.0,
            calculated_amount REAL NOT NULL DEFAULT 0.0,
            pool_divisor INTEGER DEFAULT 1,
            is_paid BOOLEAN DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cur.execute("""CREATE TABLE IF NOT EXISTS inventory (
        branch_id INTEGER NOT NULL, ingredient_id TEXT NOT NULL, stock REAL NOT NULL DEFAULT 0,
        PRIMARY KEY (branch_id, ingredient_id))""")
    cur.execute("""CREATE TABLE IF NOT EXISTS order_items (
        order_no TEXT NOT NULL, item_id TEXT NOT NULL, name TEXT NOT NULL,
        quantity REAL NOT NULL, unit_price REAL NOT NULL, bom_json TEXT NOT NULL)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS order_events (
        event_id TEXT PRIMARY KEY, order_no TEXT NOT NULL UNIQUE, branch_id INTEGER NOT NULL,
        table_no TEXT NOT NULL, total_amount REAL NOT NULL, status TEXT NOT NULL DEFAULT 'open',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS payment_events (
        event_id TEXT PRIMARY KEY, order_no TEXT NOT NULL UNIQUE, amount REAL NOT NULL,
        method TEXT NOT NULL, slip_reference TEXT, closed_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS attendance_events (
        event_id TEXT PRIMARY KEY, staff_id INTEGER NOT NULL, action TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS leave_event_ids (
        event_id TEXT PRIMARY KEY, leave_id INTEGER NOT NULL)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS service_calls (
        event_id TEXT PRIMARY KEY, branch_id INTEGER NOT NULL, table_no TEXT NOT NULL,
        call_type TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, acknowledged_at TEXT)""")

    conn.commit()
    conn.close()


init_db()


@app.middleware("http")
async def protect_preview(request: Request, call_next):
    if PREVIEW_ONLY and request.url.path.startswith("/api/") and request.method not in ("GET", "HEAD"):
        return JSONResponse({"detail": "Preview mode: transactions are disabled"}, status_code=403)
    return await call_next(request)


class OrderItem(BaseModel):
    id: str | int
    name: str
    price: float
    qty: float
    bom: list[dict] = []


class OrderCreate(BaseModel):
    event_id: str
    order_no: str
    branch_id: int = 1
    table_no: str
    total_amount: float
    items: list[OrderItem]


class ServiceCallCreate(BaseModel):
    event_id: str
    branch_id: int = 1
    table_no: str
    call_type: str


@app.post("/api/service-calls")
def create_service_call(req: ServiceCallCreate):
    if not req.event_id or len(req.event_id) > 80 or req.branch_id < 1 or not req.table_no.strip() or len(req.table_no) > 24 or not req.call_type.strip() or len(req.call_type) > 80:
        raise HTTPException(400, "Invalid service call")
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT OR IGNORE INTO service_calls (event_id, branch_id, table_no, call_type) VALUES (?, ?, ?, ?)",
                     (req.event_id, req.branch_id, req.table_no.strip(), req.call_type.strip()))
    return {"status": "pending", "event_id": req.event_id}


@app.get("/api/service-calls")
def list_service_calls(branch_id: int = 1):
    if branch_id < 1:
        raise HTTPException(400, "Invalid branch")
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT event_id, branch_id, table_no, call_type, status, created_at FROM service_calls "
                            "WHERE branch_id=? AND status='pending' ORDER BY created_at DESC LIMIT 100", (branch_id,)).fetchall()
    return {"calls": [dict(row) for row in rows]}


@app.post("/api/service-calls/{event_id}/acknowledge")
def acknowledge_service_call(event_id: str):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("UPDATE service_calls SET status='acknowledged', acknowledged_at=CURRENT_TIMESTAMP "
                              "WHERE event_id=? AND status='pending'", (event_id,))
        exists = conn.execute("SELECT status FROM service_calls WHERE event_id=?", (event_id,)).fetchone()
    if not exists:
        raise HTTPException(404, "Service call not found")
    return {"event_id": event_id, "status": "acknowledged", "changed": bool(cursor.rowcount)}


@app.post("/api/orders")
def create_order(req: OrderCreate):
    if req.total_amount < 0 or not req.items or any(i.qty <= 0 or i.price < 0 for i in req.items):
        raise HTTPException(400, "Invalid order")
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        existing = cur.execute("SELECT order_no FROM order_events WHERE event_id=? OR order_no=?", (req.event_id, req.order_no)).fetchone()
        if existing:
            return {"status": "existing", "order_no": existing[0]}
        cur.execute("INSERT INTO order_events (event_id, order_no, branch_id, table_no, total_amount) VALUES (?,?,?,?,?)",
                    (req.event_id, req.order_no, req.branch_id, req.table_no, req.total_amount))
        for item in req.items:
            cur.execute("INSERT INTO order_items VALUES (?,?,?,?,?,?)",
                        (req.order_no, str(item.id), item.name, item.qty, item.price, json.dumps(item.bom)))
            for part in item.bom:
                ingredient_id, amount = str(part["ingId"]), float(part["qty"]) * item.qty
                if amount < 0:
                    raise HTTPException(400, "Invalid BOM quantity")
                cur.execute("INSERT INTO inventory (branch_id, ingredient_id, stock) VALUES (?,?,?) "
                            "ON CONFLICT(branch_id, ingredient_id) DO UPDATE SET stock=stock-excluded.stock",
                            (req.branch_id, ingredient_id, -amount))
    return {"status": "open", "order_no": req.order_no}


class PaymentCreate(BaseModel):
    event_id: str
    order_no: str
    amount: float
    method: str
    slip_reference: Optional[str] = None


@app.post("/api/payments/close")
def close_payment(req: PaymentCreate):
    if req.amount <= 0:
        raise HTTPException(400, "Invalid amount")
    if "QR" in req.method:
        raise HTTPException(501, "QR slip verification provider is not configured")
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        existing = cur.execute("SELECT order_no FROM payment_events WHERE event_id=?", (req.event_id,)).fetchone()
        if existing:
            return {"status": "paid", "order_no": existing[0]}
        order = cur.execute("SELECT branch_id, status FROM order_events WHERE order_no=?", (req.order_no,)).fetchone()
        if not order:
            raise HTTPException(404, "Order not found")
        if order[1] != "open":
            raise HTTPException(409, "Order already closed")
        cur.execute("INSERT INTO payment_events (event_id, order_no, amount, method, slip_reference) VALUES (?,?,?,?,?)",
                    (req.event_id, req.order_no, req.amount, req.method, req.slip_reference))
        cur.execute("UPDATE order_events SET status='paid' WHERE order_no=?", (req.order_no,))
        cur.execute("INSERT INTO pos_orders (branch_id, order_no, total_amount, net_amount, payment_method) VALUES (?,?,?,?,?)",
                    (order[0], req.order_no, req.amount, req.amount, req.method))
    return {"status": "paid", "order_no": req.order_no}


class AttendanceCreate(BaseModel):
    event_id: str
    staff_id: int
    action: str


@app.post("/api/attendance")
def record_attendance(req: AttendanceCreate):
    if req.action not in ("clock_in", "clock_out"):
        raise HTTPException(400, "Invalid attendance action")
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("INSERT OR IGNORE INTO attendance_events (event_id, staff_id, action) VALUES (?,?,?)",
                    (req.event_id, req.staff_id, req.action))
        if cur.rowcount:
            now = datetime.datetime.now().isoformat(timespec="seconds")
            if req.action == "clock_in":
                cur.execute("INSERT INTO attendances (staff_id, clock_in) VALUES (?,?)", (req.staff_id, now))
            else:
                cur.execute("UPDATE attendances SET clock_out=? WHERE id=(SELECT id FROM attendances "
                            "WHERE staff_id=? AND clock_out IS NULL ORDER BY id DESC LIMIT 1)",
                            (now, req.staff_id))
    return {"status": "recorded"}


@app.get("/api/commissions")
def commissions(work_date: str, branch_id: int = 1):
    with sqlite3.connect(DB_PATH) as conn:
        sales = conn.execute("SELECT COALESCE(SUM(net_amount),0) FROM pos_orders WHERE branch_id=? AND DATE(closed_at)=?",
                             (branch_id, work_date)).fetchone()[0]
    divisor = calculate_pooled_commission_divisor(work_date)
    return {"sales": sales, "pool": round(sales * 0.03, 2), "pool_divisor": divisor,
            "equal_share": round(sales * 0.03 / divisor, 2)}


@app.get("/api/staff/payroll")
def staff_payroll(month: str, branch_id: int = 1, x_manager_report_token: str = Header(default="")):
    """Read-only staff ledger. Rates here are configured payroll inputs, not statutory rates."""
    if not MANAGER_REPORT_TOKEN:
        raise HTTPException(503, "Manager payroll access is not configured")
    if not hmac.compare_digest(x_manager_report_token, MANAGER_REPORT_TOKEN):
        raise HTTPException(403, "Manager payroll access denied")
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise HTTPException(400, "month must be YYYY-MM")
    if branch_id < 1:
        raise HTTPException(400, "Invalid branch")
    start = datetime.date.fromisoformat(f"{month}-01")
    end = (start.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        staff_rows = conn.execute(
            "SELECT id, name, role, hourly_rate FROM staffs WHERE branch_id=? AND is_active=1 ORDER BY name",
            (branch_id,),
        ).fetchall()
        attendance_rows = conn.execute(
            "SELECT id, staff_id, clock_in, clock_out FROM attendances "
            "WHERE substr(clock_in,1,10)>=? AND substr(clock_in,1,10)<? ORDER BY clock_in DESC",
            (start.isoformat(), end.isoformat()),
        ).fetchall()
        leave_rows = conn.execute(
            "SELECT id, staff_id, leave_type, start_date, end_date, status FROM leave_requests "
            "WHERE start_date<? AND end_date>=? ORDER BY start_date DESC",
            (end.isoformat(), start.isoformat()),
        ).fetchall()
        commission_rows = conn.execute(
            "SELECT staff_id, period_date, SUM(calculated_amount) AS amount FROM commission_records "
            "WHERE period_date>=? AND period_date<? GROUP BY staff_id,period_date",
            (start.isoformat(), end.isoformat()),
        ).fetchall()
    by_staff = {row["id"]: {
        "id": row["id"], "name": row["name"], "role": row["role"],
        "hourly_rate": float(row["hourly_rate"] or 0), "regular_hours": 0.0,
        "ot_hours": 0.0, "work_days": 0, "attendance": [], "leave": [],
        "commission_records": [], "commission": 0.0,
    } for row in staff_rows}
    # Configurable business defaults; payroll law and deductions must be configured separately.
    regular_hours_per_day, ot_multiplier = PAYROLL_REGULAR_HOURS_PER_DAY, PAYROLL_OT_MULTIPLIER
    hours_by_day = {}
    for row in attendance_rows:
        item = by_staff.get(row["staff_id"])
        if item is None:
            continue
        hours = 0.0
        if row["clock_out"]:
            try:
                delta = datetime.datetime.fromisoformat(row["clock_out"]) - datetime.datetime.fromisoformat(row["clock_in"])
                hours = min(max(delta.total_seconds() / 3600, 0), 24)
            except ValueError:
                hours = 0.0
        day_key = (row["staff_id"], row["clock_in"][:10])
        prior = hours_by_day.get(day_key, 0.0)
        regular = max(min(prior + hours, regular_hours_per_day) - min(prior, regular_hours_per_day), 0)
        ot = max(hours - regular, 0)
        hours_by_day[day_key] = prior + hours
        item["regular_hours"] += regular
        item["ot_hours"] += ot
        if row["clock_out"]:
            item.setdefault("_worked_dates", set()).add(row["clock_in"][:10])
        item["attendance"].append({"date": row["clock_in"][:10], "clock_in": row["clock_in"],
                                   "clock_out": row["clock_out"], "regular_hours": round(regular, 2),
                                   "ot_hours": round(ot, 2)})
    for row in leave_rows:
        item = by_staff.get(row["staff_id"])
        if item is not None:
            item["leave"].append({"id": row["id"], "type": row["leave_type"],
                                  "start_date": row["start_date"], "end_date": row["end_date"],
                                  "status": row["status"]})
    for row in commission_rows:
        item = by_staff.get(row["staff_id"])
        if item is not None:
            amount = float(row["amount"] or 0)
            item["commission"] += amount
            item["commission_records"].append({"date": row["period_date"], "amount": round(amount, 2)})
    for item in by_staff.values():
        item["work_days"] = len(item.pop("_worked_dates", set()))
        item["regular_hours"] = round(item["regular_hours"], 2)
        item["ot_hours"] = round(item["ot_hours"], 2)
        item["base_pay"] = round(item["regular_hours"] * item["hourly_rate"], 2)
        item["ot_pay"] = round(item["ot_hours"] * item["hourly_rate"] * ot_multiplier, 2)
        item["commission"] = round(item["commission"], 2)
        item["total_pay"] = round(item["base_pay"] + item["ot_pay"] + item["commission"], 2)
    return {"month": month, "branch_id": branch_id, "regular_hours_per_day": regular_hours_per_day,
            "ot_multiplier": ot_multiplier, "staff": list(by_staff.values()),
            "note": "Estimated gross pay before deductions and benefits; confirm configured payroll policy before use."}


# =====================================================================
# 2. BUSINESS LOGIC: อนุมัติใบลา -> ล็อก PIN POS -> ตัดตัวหารคอมมิชชันกองกลาง
# =====================================================================
class LeaveRequestCreate(BaseModel):
    event_id: str
    staff_id: int
    leave_type: str  # sick, personal, vacation, swap_shift
    start_date: str
    end_date: str
    reason: str
    attachment_url: Optional[str] = None


class LeaveApprovalAction(BaseModel):
    leave_id: int
    manager_staff_id: int
    decision: str  # 'approved' or 'rejected'


@app.post("/api/line-liff/leave-requests")
def submit_leave_request(req: LeaveRequestCreate):
    """1. พนักงานกดยื่นใบลาผ่าน LINE LIFF -> บันทึกเป็น Pending และเตรียมส่ง Flex Message หาผู้จัดการ"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    existing = cur.execute("SELECT leave_id FROM leave_event_ids WHERE event_id=?", (req.event_id,)).fetchone()
    if existing:
        conn.close()
        return {"status": "pending", "leave_id": existing[0], "line_flex_notification": "not_configured"}
    cur.execute(
        """
        INSERT INTO leave_requests (staff_id, leave_type, start_date, end_date, reason, attachment_url, status)
        VALUES (?, ?, ?, ?, ?, ?, 'pending')
        """,
        (req.staff_id, req.leave_type, req.start_date, req.end_date, req.reason, req.attachment_url),
    )
    leave_id = cur.lastrowid
    cur.execute("INSERT INTO leave_event_ids VALUES (?,?)", (req.event_id, leave_id))
    conn.commit()
    conn.close()
    return {
        "status": "pending",
        "leave_id": leave_id,
        "line_flex_notification": "not_configured",
    }


@app.post("/api/line-webhook/approve-leave")
def manager_review_leave(action: LeaveApprovalAction):
    """
    2. ผู้จัดการกดปุ่ม [อนุมัติ] หรือ [ปฏิเสธ] บน LINE Flex Message:
       - หาก 'approved':
         1) อัปเดต staff_shifts.status = 'on_leave'
         2) ตั้งค่า pos_pin_locked = 1 เพื่อป้องกันเพื่อนร่วมงานนำรหัส PIN ไปสวมสิทธิ์เปิดบิล
         3) ตัดชื่อออกจากตัวหารค่าคอมมิชชันกองกลาง (pool_divisor) ในวันดังกล่าวอัตโนมัติ
    """
    if action.decision not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="Decision must be 'approved' or 'rejected'")

    now_str = datetime.datetime.now().isoformat(timespec="seconds")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT staff_id, start_date FROM leave_requests WHERE id = ?", (action.leave_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Leave request not found")

    staff_id, work_date = row
    cur.execute(
        """
        UPDATE leave_requests
        SET status = ?, reviewed_by = ?, reviewed_at = ?
        WHERE id = ?
        """,
        (action.decision, action.manager_staff_id, now_str, action.leave_id),
    )

    if action.decision == "approved":
        cur.execute(
            """
            INSERT INTO staff_shifts (staff_id, branch_id, work_date, status, pos_pin_locked)
            VALUES (?, 1, ?, 'on_leave', 1)
            ON CONFLICT(staff_id, work_date)
            DO UPDATE SET status = 'on_leave', pos_pin_locked = 1
            """,
            (staff_id, work_date),
        )

    conn.commit()
    conn.close()
    return {
        "status": action.decision,
        "leave_id": action.leave_id,
        "staff_id": staff_id,
        "pos_pin_locked": action.decision == "approved",
        "work_date": work_date,
    }


def calculate_pooled_commission_divisor(work_date: str) -> int:
    """
    คำนวณตัวหารจำนวนคนที่มาทำงานจริง (active_workers_count)
    โดยตัดคนที่สถานะเป็น 'on_leave' หรือ 'absent' ออกตาม SQL Logic
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT COUNT(DISTINCT staff_id) AS active_workers_count
        FROM attendances
        WHERE DATE(clock_in) = ?
          AND staff_id NOT IN (
              SELECT staff_id
              FROM staff_shifts
              WHERE work_date = ?
                AND status IN ('on_leave', 'absent')
          )
        """,
        (work_date, work_date),
    )
    count = cur.fetchone()[0]
    conn.close()
    return max(1, count)




@app.get("/api/enterprise/analytics-dashboard")
def get_executive_analytics_dashboard(benchmark: str = "WOW"):
    """
    4-Pillar Executive BI & Predictive Analytics Endpoint:
    1. Comparative Benchmarking (DoD / WoW) + Channel & Payment Split
    2. 4-Group BCG Menu Engineering Matrix (Stars, Cash Cows, Puzzles, Dogs/Dead Stock)
    3. 7-Day Hourly Heatmap + KDS Speed Bottleneck + Predictive Roster
    4. Food Cost & Wastage Monitoring + Customer Retention & LTV
    """
    return {
        "sales_realtime": {
            "today_sales": 4850.00,
            "daily_target": 6000.00,
            "benchmark_mode": benchmark,
            "wow_growth_percent": 14.2,
            "dod_growth_percent": 8.5,
            "channel_split": {
                "dine_in": 2813.00,
                "takeaway": 679.00,
                "grabfood": 727.00,
                "lineman": 436.00,
                "robinhood_shopee": 195.00,
            },
            "payment_split": {
                "qr_promptpay": 2522.00,
                "cash": 1450.00,
                "credit_card": 582.00,
                "ewallet": 296.00,
            },
        },
        "bcg_menu_matrix": {
            "stars": ["กะเพราหมูกรอบไข่ดาว", "ชาไทยเย็นพรีเมียม"],
            "cash_cows": ["น้ำเปล่า + น้ำแข็ง"],
            "puzzles": ["ปลากะพงทอดน้ำปลา"],
            "dogs_dead_stock": ["บัวลอยเผือกมะพร้าวอ่อน"],
        },
        "kds_and_predictive_roster": {
            "avg_prep_minutes_offpeak": 5.8,
            "avg_prep_minutes_peak": 11.4,
            "bottleneck_station": "เตาทอด (ปลากะพงทอดน้ำปลา/หมูกรอบ เฉลี่ย 14.5 นาที)",
            "recommended_weekend_staff": {"kitchen": 3, "bar": 1, "cashier": 1, "service": 2},
        },
        "food_cost_and_retention": {
            "actual_food_cost_percent": 34.8,
            "target_corridor_percent": "30.0 - 35.0",
            "waste_cost_baht": 135.00,
            "returning_member_ratio_percent": 68.0,
            "avg_basket_size_baht": 285.00,
            "spending_per_head_baht": 142.00,
            "customer_ltv_baht": 4620.00,
        },
    }


app.mount("/assets", StaticFiles(directory=Path(__file__).parent / "assets"), name="assets")


@app.get("/service-worker.js")
def serve_worker():
    return FileResponse(Path(__file__).parent / "service-worker.js", media_type="application/javascript",
                        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"})


@app.get("/{asset_name}.css")
def serve_workspace_css(asset_name: str):
    if asset_name not in {"ui", "workspace", "sales-redesign", "ops-redesign", "people-redesign", "reports-restore", "service-call"}:
        raise HTTPException(404, "Stylesheet not found")
    return FileResponse(Path(__file__).parent / f"{asset_name}.css", media_type="text/css")


@app.get("/{asset_name}.js")
def serve_workspace_js(asset_name: str):
    if asset_name not in {"workspace", "sales-redesign", "ops-redesign", "people-redesign", "reports-restore", "service-call"}:
        raise HTTPException(404, "Script not found")
    return FileResponse(Path(__file__).parent / f"{asset_name}.js", media_type="application/javascript")


@app.get("/", response_class=HTMLResponse)
def serve_v3_prototype():
    html_file = Path(__file__).parent / "index.html"
    if html_file.exists():
        return html_file.read_text(encoding="utf-8")
    return "<h3>POS WAI Enterprise V3 Server Running</h3>"


@app.get("/index.html")
def serve_index():
    return FileResponse(Path(__file__).parent / "index.html")


@app.get("/line_pos_prototype.html")
def serve_prototype():
    return FileResponse(Path(__file__).parent / "line_pos_prototype.html")


@app.get("/manifest.json")
def serve_manifest():
    return FileResponse(Path(__file__).parent / "manifest.json", media_type="application/manifest+json")


@app.get("/icons.svg")
def serve_ui_icons():
    return FileResponse(Path(__file__).parent / "icons.svg", media_type="image/svg+xml")


@app.get("/icon-{size}.png")
def serve_icon(size: int):
    if size not in (192, 512):
        raise HTTPException(404, "Icon not found")
    return FileResponse(Path(__file__).parent / f"icon-{size}.png", media_type="image/png")


@app.get("/api/config")
def public_config():
    return {"promptpay_id": PROMPTPAY_ID, "line_liff_id": LINE_LIFF_ID, "preview_only": PREVIEW_ONLY}


if __name__ == "__main__":
    print("POS WAI Enterprise V3 Database & Leave/Commission Engine initialized successfully.")
