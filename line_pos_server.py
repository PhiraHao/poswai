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
from contextlib import closing
import datetime
import json
import os
import hmac
import math
import hashlib
import base64
import secrets
import time
import re
import httpx
from contextlib import closing
from typing import List, Optional
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pydantic import ValidationError
from poswai_analytics import build_analytics_dashboard
from poswai_commissions import allocate_commissions
from poswai_inventory import (InventoryError, apply_inventory_movement,
                              init_inventory_movements, list_inventory_movements)
from easyslip import SlipVerificationError, verify_bank_slip
from poswai_catalog import (CatalogError, deduct_inventory, init_catalog,
                            list_menu_items, quote_order, upsert_menu_item, STATIONS)
from poswai_commerce import (create_order as create_commerce_order, init_commerce,
                             list_customers as commerce_customers, mark_handed_off, segment_for,
                             upsert_customer)
from line_integration import (build_leave_flex, parse_leave_postback,
                              push_leave_request, verify_liff_id_token,
                              verify_webhook_signature)

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
LINE_LOGIN_CHANNEL_ID = os.getenv("LINE_LOGIN_CHANNEL_ID", "")
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "")
PREVIEW_ONLY = os.getenv("POSWAI_PREVIEW_ONLY", "0") == "1"
BOOTSTRAP_MANAGER_PIN = os.getenv("POSWAI_BOOTSTRAP_MANAGER_PIN", "")
TABLE_QR_SECRET = os.getenv("POSWAI_TABLE_QR_SECRET", "")
SONGWAI_WEBHOOK_SECRET = os.getenv("SONGWAI_WEBHOOK_SECRET", "")
SONGWAI_RESTAURANT_ID = int(os.getenv("SONGWAI_RESTAURANT_ID", "0"))
SESSION_LIFETIME = 12 * 60 * 60
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
    item_columns = {row[1] for row in cur.execute("PRAGMA table_info(order_items)")}
    if "station" not in item_columns:
        cur.execute("ALTER TABLE order_items ADD COLUMN station TEXT NOT NULL DEFAULT 'ครัวร้อน'")
    if "course_mode" not in item_columns:
        cur.execute("ALTER TABLE order_items ADD COLUMN course_mode TEXT NOT NULL DEFAULT 'FIRE'")
    cur.execute("""CREATE TABLE IF NOT EXISTS order_events (
        event_id TEXT PRIMARY KEY, order_no TEXT NOT NULL UNIQUE, branch_id INTEGER NOT NULL,
        table_no TEXT NOT NULL, total_amount REAL NOT NULL, status TEXT NOT NULL DEFAULT 'open',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS kds_station_tickets (
        order_no TEXT NOT NULL REFERENCES order_events(order_no),
        station TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('held','queued','ready')),
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        fired_at TEXT, ready_at TEXT,
        PRIMARY KEY(order_no,station))""")
    cur.execute("""INSERT OR IGNORE INTO kds_station_tickets(order_no,station,status)
        SELECT oi.order_no,oi.station,
          CASE WHEN SUM(CASE WHEN oi.course_mode='HOLD' THEN 1 ELSE 0 END)>0 THEN 'held' ELSE 'queued' END
        FROM order_items oi JOIN order_events oe ON oe.order_no=oi.order_no
        WHERE oe.status='open' GROUP BY oi.order_no,oi.station""")
    cur.execute("""CREATE TABLE IF NOT EXISTS payment_events (
        event_id TEXT PRIMARY KEY, order_no TEXT NOT NULL UNIQUE, amount REAL NOT NULL,
        method TEXT NOT NULL, slip_reference TEXT, closed_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS table_payment_events (
        event_id TEXT PRIMARY KEY, branch_id INTEGER NOT NULL, table_no TEXT NOT NULL,
        order_nos_json TEXT NOT NULL, amount REAL NOT NULL, slip_reference TEXT NOT NULL UNIQUE,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS attendance_events (
        event_id TEXT PRIMARY KEY, staff_id INTEGER NOT NULL, action TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS leave_event_ids (
        event_id TEXT PRIMARY KEY, leave_id INTEGER NOT NULL)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS service_calls (
        event_id TEXT PRIMARY KEY, branch_id INTEGER NOT NULL, table_no TEXT NOT NULL,
        call_type TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, acknowledged_at TEXT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS auth_sessions (
        token_hash TEXT PRIMARY KEY, staff_id INTEGER NOT NULL REFERENCES staffs(id),
        expires_at INTEGER NOT NULL)""")
    cur.execute("CREATE INDEX IF NOT EXISTS auth_sessions_expiry ON auth_sessions(expires_at)")
    init_catalog(conn)
    init_inventory_movements(conn)
    init_commerce(conn)
    cur.execute("""CREATE TABLE IF NOT EXISTS auth_login_attempts (
        staff_id INTEGER PRIMARY KEY, failures INTEGER NOT NULL, first_failed_at INTEGER NOT NULL)""")
    if BOOTSTRAP_MANAGER_PIN and not cur.execute("SELECT 1 FROM staffs LIMIT 1").fetchone():
        if len(BOOTSTRAP_MANAGER_PIN) < 8:
            raise RuntimeError("POSWAI_BOOTSTRAP_MANAGER_PIN must contain at least 8 characters")
        cur.execute("INSERT OR IGNORE INTO branches (id, name) VALUES (1, 'Main branch')")
        cur.execute("INSERT INTO staffs (branch_id, name, role, pin_code_hash) VALUES (1, ?, 'manager', ?)",
                    (os.getenv("POSWAI_BOOTSTRAP_MANAGER_NAME", "Manager"), hash_pin(BOOTSTRAP_MANAGER_PIN)))

    conn.commit()
    conn.close()


def hash_pin(pin: str) -> str:
    if len(pin) < 8 or len(pin) > 128:
        raise HTTPException(400, "PIN must contain 8 to 128 characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, 310_000)
    return f"pbkdf2_sha256$310000${salt.hex()}${digest.hex()}"


def verify_pin(pin: str, encoded: str) -> bool:
    try:
        scheme, rounds, salt_hex, digest_hex = encoded.split("$")
        if scheme != "pbkdf2_sha256" or int(rounds) < 100_000 or int(rounds) > 1_000_000:
            return False
        digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt_hex), int(rounds))
        return hmac.compare_digest(digest, bytes.fromhex(digest_hex))
    except (ValueError, TypeError, AttributeError):
        return False


init_db()


@app.middleware("http")
async def protect_preview(request: Request, call_next):
    if PREVIEW_ONLY and request.url.path.startswith("/api/") and request.method not in ("GET", "HEAD"):
        return JSONResponse({"detail": "Preview mode: transactions are disabled"}, status_code=403)
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.cookies.get("poswai_session"):
        origin = request.headers.get("origin")
        if origin:
            from urllib.parse import urlsplit
            source = urlsplit(origin)
            forwarded_host = request.headers.get("x-forwarded-host", request.headers.get("host", ""))
            if source.netloc != forwarded_host or source.scheme not in ("https", "http"):
                return JSONResponse({"detail": "Invalid request origin"}, status_code=403)
    response = await call_next(request)
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


def require_staff(request: Request, roles: tuple[str, ...] = (), branch_id: int | None = None) -> dict:
    token = request.cookies.get("poswai_session", "")
    if len(token) != 64 or not re.fullmatch(r"[0-9a-f]{64}", token):
        raise HTTPException(401, "Staff login required")
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT s.id,s.branch_id,s.name,s.role,s.is_active,a.expires_at FROM auth_sessions a "
            "JOIN staffs s ON s.id=a.staff_id WHERE a.token_hash=?",
            (hashlib.sha256(token.encode()).hexdigest(),),
        ).fetchone()
        if row and row["expires_at"] <= int(time.time()):
            conn.execute("DELETE FROM auth_sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))
            row = None
        if row and conn.execute("SELECT 1 FROM staff_shifts WHERE staff_id=? AND work_date=? AND pos_pin_locked=1",
                                (row["id"], datetime.date.today().isoformat())).fetchone():
            conn.execute("DELETE FROM auth_sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))
            row = None
    if not row or not row["is_active"]:
        raise HTTPException(401, "Staff login required")
    staff = dict(row)
    if roles and staff["role"] not in roles:
        raise HTTPException(403, "Staff role not permitted")
    if branch_id is not None and staff["branch_id"] != branch_id:
        raise HTTPException(403, "Staff branch not permitted")
    return staff


class LoginRequest(BaseModel):
    staff_id: int
    pin: str


@app.post("/api/auth/login")
def staff_login(req: LoginRequest, request: Request, response: Response):
    if req.staff_id < 1 or len(req.pin) > 128:
        raise HTTPException(401, "Invalid staff credentials")
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        conn.row_factory = sqlite3.Row
        now = int(time.time())
        attempt = conn.execute("SELECT failures,first_failed_at FROM auth_login_attempts WHERE staff_id=?",
                               (req.staff_id,)).fetchone()
        if attempt and attempt["failures"] >= 5 and now - attempt["first_failed_at"] < 900:
            raise HTTPException(429, "Too many login attempts; try again in 15 minutes")
        row = conn.execute("SELECT id,branch_id,name,role,is_active,pin_code_hash FROM staffs WHERE id=?", (req.staff_id,)).fetchone()
        # Always run a slow comparison so missing staff IDs do not provide a fast enumeration path.
        valid = verify_pin(req.pin, row["pin_code_hash"] if row else hash_pin("invalid-credentials"))
        if not row or not row["is_active"] or not valid:
            if not attempt or now - attempt["first_failed_at"] >= 900:
                conn.execute("INSERT INTO auth_login_attempts (staff_id,failures,first_failed_at) VALUES (?,?,?) "
                             "ON CONFLICT(staff_id) DO UPDATE SET failures=1,first_failed_at=excluded.first_failed_at",
                             (req.staff_id, 1, now))
            else:
                conn.execute("UPDATE auth_login_attempts SET failures=failures+1 WHERE staff_id=?", (req.staff_id,))
            conn.commit()
            raise HTTPException(401, "Invalid staff credentials")
        today = datetime.date.today().isoformat()
        locked = conn.execute("SELECT 1 FROM staff_shifts WHERE staff_id=? AND work_date=? AND pos_pin_locked=1",
                              (row["id"], today)).fetchone()
        if locked:
            raise HTTPException(403, "Staff access is locked for this shift")
        token = secrets.token_hex(32)
        expires = int(time.time()) + SESSION_LIFETIME
        conn.execute("DELETE FROM auth_login_attempts WHERE staff_id=?", (row["id"],))
        conn.execute("DELETE FROM auth_sessions WHERE staff_id=? OR expires_at<=?", (row["id"], int(time.time())))
        conn.execute("INSERT INTO auth_sessions (token_hash,staff_id,expires_at) VALUES (?,?,?)",
                     (hashlib.sha256(token.encode()).hexdigest(), row["id"], expires))
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").split(",")[0] == "https"
    response.set_cookie("poswai_session", token, max_age=SESSION_LIFETIME, httponly=True,
                        secure=secure, samesite="strict", path="/")
    return {"staff_id": row["id"], "branch_id": row["branch_id"], "name": row["name"],
            "role": row["role"], "expires_at": expires}


@app.get("/api/auth/session")
def staff_session(request: Request):
    staff = require_staff(request)
    return {"staff_id": staff["id"], "branch_id": staff["branch_id"], "name": staff["name"],
            "role": staff["role"], "expires_at": staff["expires_at"]}


@app.post("/api/auth/logout")
def staff_logout(request: Request, response: Response):
    token = request.cookies.get("poswai_session", "")
    if token:
        with closing(sqlite3.connect(DB_PATH)) as conn, conn:
            conn.execute("DELETE FROM auth_sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))
    response.delete_cookie("poswai_session", path="/")
    return {"status": "logged_out"}


class StaffCreate(BaseModel):
    name: str
    role: str
    pin: str
    line_user_id: Optional[str] = None


@app.post("/api/staff")
def create_staff(req: StaffCreate, request: Request):
    manager = require_staff(request, roles=("manager", "owner"))
    if not req.name.strip() or len(req.name) > 100 or req.role not in ("manager", "cashier", "kitchen", "service", "staff"):
        raise HTTPException(400, "Invalid staff profile")
    if req.line_user_id is not None and (not req.line_user_id or len(req.line_user_id) > 100):
        raise HTTPException(400, "Invalid LINE user ID")
    pin_hash = hash_pin(req.pin)
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        try:
            cur = conn.execute("INSERT INTO staffs (branch_id,line_user_id,name,role,pin_code_hash) VALUES (?,?,?,?,?)",
                               (manager["branch_id"], req.line_user_id, req.name.strip(), req.role, pin_hash))
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, "Staff LINE identity already exists") from exc
    return {"staff_id": cur.lastrowid, "branch_id": manager["branch_id"], "name": req.name.strip(), "role": req.role}


class TableTokenRequest(BaseModel):
    branch_id: int
    table_no: str


def _table_signature(payload: bytes) -> str:
    return hmac.new(TABLE_QR_SECRET.encode(), payload, hashlib.sha256).hexdigest()


@app.post("/api/tables/token")
def issue_table_token(req: TableTokenRequest, request: Request):
    require_staff(request, roles=("manager", "owner"), branch_id=req.branch_id)
    if len(TABLE_QR_SECRET) < 32:
        raise HTTPException(503, "Table QR signing is not configured")
    if req.branch_id < 1 or not re.fullmatch(r"[\w\- ]{1,24}", req.table_no, re.UNICODE):
        raise HTTPException(400, "Invalid table")
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        if not conn.execute("SELECT 1 FROM branches WHERE id=?", (req.branch_id,)).fetchone():
            raise HTTPException(404, "Branch not found")
    expires = int(time.time()) + 30 * 24 * 3600
    payload = json.dumps({"b": req.branch_id, "t": req.table_no, "e": expires},
                         sort_keys=True, separators=(",", ":")).encode()
    encoded = base64.urlsafe_b64encode(payload).rstrip(b"=").decode()
    return {"token": encoded + "." + _table_signature(payload), "expires_at": expires}


def require_table_or_staff(request: Request, branch_id: int, table_no: str) -> None:
    if request.cookies.get("poswai_session"):
        try:
            require_staff(request, branch_id=branch_id)
            return
        except HTTPException as exc:
            if exc.status_code != 401:
                raise
    token = request.headers.get("x-table-token", "")
    if len(TABLE_QR_SECRET) < 32 or len(token) > 512 or "." not in token:
        raise HTTPException(401, "Staff login or table QR token required")
    try:
        encoded, signature = token.split(".", 1)
        payload = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        data = json.loads(payload)
        valid = hmac.compare_digest(signature, _table_signature(payload))
        if not valid or data["b"] != branch_id or data["t"] != table_no or data["e"] < int(time.time()):
            raise ValueError("Invalid table token")
    except (ValueError, KeyError, TypeError):
        raise HTTPException(403, "Invalid or expired table QR token")


class OrderItem(BaseModel):
    id: str | int
    name: str
    price: float
    qty: float
    bom: list[dict] = []
    course_mode: str = "FIRE"


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


class MenuUpsert(BaseModel):
    branch_id: int = 1
    name: str
    price: float
    bom: list[dict] = []
    active: bool = True
    station: str = "ครัวร้อน"


@app.get("/api/menu")
def get_menu(request: Request, branch_id: int = 1, include_inactive: bool = False):
    try:
        if include_inactive:
            require_staff(request, roles=("manager", "owner"), branch_id=branch_id)
        with closing(sqlite3.connect(DB_PATH)) as conn:
            return {"branch_id": branch_id, "items": list_menu_items(conn, branch_id, active_only=not include_inactive)}
    except CatalogError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


@app.put("/api/menu/{item_id}")
def put_menu_item(item_id: str, item: MenuUpsert, request: Request):
    require_staff(request, roles=("manager", "owner"), branch_id=item.branch_id)
    try:
        with closing(sqlite3.connect(DB_PATH)) as conn, conn:
            if item_id.startswith("songwai-") and item.active:
                if not item.bom:
                    raise CatalogError("Add a BOM recipe before activating Songwai menu", 409)
                for part in item.bom:
                    if not conn.execute("SELECT 1 FROM inventory WHERE branch_id=? AND ingredient_id=?",
                                        (item.branch_id, part.get("ingId"))).fetchone():
                        raise CatalogError("Add ingredient stock before activating Songwai menu", 409)
            return upsert_menu_item(conn, item.branch_id, item_id, item.name, item.price, item.bom, item.active, item.station)
    except CatalogError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


class InventorySet(BaseModel):
    branch_id: int = 1
    stock: float


@app.get("/api/inventory")
def get_inventory(request: Request, branch_id: int = 1):
    require_staff(request, branch_id=branch_id)
    with closing(sqlite3.connect(DB_PATH)) as conn:
        rows = conn.execute("SELECT ingredient_id,stock FROM inventory WHERE branch_id=? ORDER BY ingredient_id", (branch_id,)).fetchall()
    return {"branch_id": branch_id, "items": [{"id": row[0], "stock": row[1]} for row in rows]}


@app.put("/api/inventory/{ingredient_id}")
def put_inventory(ingredient_id: str, item: InventorySet, request: Request):
    require_staff(request, roles=("manager", "owner"), branch_id=item.branch_id)
    if not ingredient_id or len(ingredient_id) > 80 or not math.isfinite(item.stock) or item.stock < 0:
        raise HTTPException(400, "Invalid stock")
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        try:
            conn.execute("INSERT INTO inventory(branch_id,ingredient_id,stock) VALUES(?,?,?)",
                         (item.branch_id, ingredient_id, item.stock))
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, "Stock already exists; record a movement instead") from exc
    return {"branch_id": item.branch_id, "id": ingredient_id, "stock": item.stock}


class InventoryMovementCreate(BaseModel):
    event_id: str
    branch_id: int = 1
    ingredient_id: str
    action: str
    quantity: float
    target_branch_id: Optional[int] = None
    note: str = ""


@app.post("/api/inventory/movements")
def post_inventory_movement(item: InventoryMovementCreate, request: Request):
    roles = ("manager", "owner", "staff", "kitchen") if item.action == "waste" else ("manager", "owner")
    actor = require_staff(request, roles=roles, branch_id=item.branch_id)
    try:
        with closing(sqlite3.connect(DB_PATH)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            return apply_inventory_movement(
                conn, event_id=item.event_id, branch_id=item.branch_id,
                ingredient_id=item.ingredient_id, action=item.action,
                quantity=item.quantity, target_branch_id=item.target_branch_id,
                note=item.note, actor_staff_id=actor["id"],
            )
    except InventoryError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


@app.get("/api/inventory/movements")
def get_inventory_movements(request: Request, branch_id: int = 1):
    require_staff(request, branch_id=branch_id)
    try:
        with closing(sqlite3.connect(DB_PATH)) as conn:
            return {"branch_id": branch_id, "items": list_inventory_movements(conn, branch_id)}
    except InventoryError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


@app.post("/api/service-calls")
def create_service_call(req: ServiceCallCreate, request: Request):
    if not req.event_id or len(req.event_id) > 80 or req.branch_id < 1 or not req.table_no.strip() or len(req.table_no) > 24 or not req.call_type.strip() or len(req.call_type) > 80:
        raise HTTPException(400, "Invalid service call")
    require_table_or_staff(request, req.branch_id, req.table_no.strip())
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        conn.execute("INSERT OR IGNORE INTO service_calls (event_id, branch_id, table_no, call_type) VALUES (?, ?, ?, ?)",
                     (req.event_id, req.branch_id, req.table_no.strip(), req.call_type.strip()))
    return {"status": "pending", "event_id": req.event_id}


@app.get("/api/service-calls")
def list_service_calls(request: Request, branch_id: int = 1):
    if branch_id < 1:
        raise HTTPException(400, "Invalid branch")
    require_staff(request, branch_id=branch_id)
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT event_id, branch_id, table_no, call_type, status, created_at FROM service_calls "
                            "WHERE branch_id=? AND status='pending' ORDER BY created_at DESC LIMIT 100", (branch_id,)).fetchall()
    return {"calls": [dict(row) for row in rows]}


@app.post("/api/service-calls/{event_id}/acknowledge")
def acknowledge_service_call(event_id: str, request: Request):
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        found = conn.execute("SELECT branch_id FROM service_calls WHERE event_id=?", (event_id,)).fetchone()
        if not found:
            raise HTTPException(404, "Service call not found")
        require_staff(request, roles=("manager", "owner", "cashier"), branch_id=found[0])
        cursor = conn.execute("UPDATE service_calls SET status='acknowledged', acknowledged_at=CURRENT_TIMESTAMP "
                              "WHERE event_id=? AND status='pending'", (event_id,))
        exists = conn.execute("SELECT status FROM service_calls WHERE event_id=?", (event_id,)).fetchone()
    if not exists:
        raise HTTPException(404, "Service call not found")
    return {"event_id": event_id, "status": "acknowledged", "changed": bool(cursor.rowcount)}


class OnlineOrderLine(BaseModel):
    id: str | int
    qty: int


class OnlineOrderCreate(BaseModel):
    event_id: str
    branch_id: int = 1
    fulfillment: str = "self_pickup"
    items: list[OnlineOrderLine]
    customer_name: str = ""
    contact_phone: str = ""
    line_id_token: str
    marketing_opt_in: bool | None = None


def _online_order_record(conn: sqlite3.Connection, order_no: str) -> dict:
    conn.row_factory = sqlite3.Row
    row = conn.execute("""SELECT o.order_no,o.branch_id,o.source,o.external_id,o.fulfillment,
        o.customer_name,o.contact_phone,o.pickup_code,o.payment_status,o.status,o.created_at,o.channel,
        e.total_amount FROM online_orders o JOIN order_events e ON e.order_no=o.order_no
        WHERE o.order_no=?""", (order_no,)).fetchone()
    if not row:
        raise HTTPException(404, "Online order not found")
    result = dict(row)
    result["items"] = [{"id": item[0], "name": item[1], "qty": item[2], "price": item[3]}
                       for item in conn.execute("SELECT item_id,name,quantity,unit_price FROM order_items WHERE order_no=?", (order_no,))]
    return result


@app.post("/api/online/orders")
def place_online_order(req: OnlineOrderCreate):
    if req.branch_id < 1 or req.fulfillment != "self_pickup" or not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", req.event_id):
        raise HTTPException(400, "Invalid online order")
    if len(req.customer_name.strip()) > 100 or len(req.contact_phone.strip()) > 30:
        raise HTTPException(400, "Invalid customer details")
    line_id = verify_liff_id_token(req.line_id_token, LINE_LOGIN_CHANNEL_ID)
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute("""SELECT o.order_no,c.line_user_id FROM online_orders o
            LEFT JOIN crm_customers c ON c.id=o.customer_id
            WHERE o.branch_id=? AND o.source='poswai' AND o.external_id=?""",
            (req.branch_id, req.event_id)).fetchone()
        if existing:
            if existing[1] != line_id:
                raise HTTPException(409, "Order ID already used")
            return _online_order_record(conn, existing[0])
        customer_id = upsert_customer(conn, branch_id=req.branch_id, source="line",
            external_id=line_id, display_name=req.customer_name.strip(),
            phone=req.contact_phone.strip(), marketing_opt_in=req.marketing_opt_in)
        try:
            result = create_commerce_order(conn, branch_id=req.branch_id, source="poswai",
                external_id=req.event_id, fulfillment="self_pickup",
                items=[line.model_dump() for line in req.items], customer_id=customer_id,
                customer_name=req.customer_name.strip(), contact_phone=req.contact_phone.strip(),
                channel="POS WAI")
        except CatalogError as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc
        return _online_order_record(conn, result["order_no"])


class SongwaiOrderLine(BaseModel):
    menu_id: int
    qty: int


class SongwaiOrderCreate(BaseModel):
    order_id: int
    restaurant_id: int
    user_id: int | None = None
    delivery_mode: str
    customer_name: str = ""
    contact_phone: str = ""
    payment_status: str = "pending"
    items: list[SongwaiOrderLine]


@app.post("/api/integrations/songwai/orders")
async def intake_songwai_order(request: Request):
    if len(SONGWAI_WEBHOOK_SECRET) < 32 or SONGWAI_RESTAURANT_ID < 1:
        raise HTTPException(503, "Songwai integration is not configured")
    body = await request.body()
    if len(body) > 64_000:
        raise HTTPException(413, "Order payload too large")
    stamp = request.headers.get("x-songwai-timestamp", "")
    signature = request.headers.get("x-songwai-signature", "")
    if not stamp.isdecimal() or abs(int(stamp) - int(time.time())) > 300:
        raise HTTPException(401, "Invalid Songwai timestamp")
    expected = hmac.new(SONGWAI_WEBHOOK_SECRET.encode(), stamp.encode() + b"." + body,
                        hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, "sha256=" + expected):
        raise HTTPException(401, "Invalid Songwai signature")
    try:
        req = SongwaiOrderCreate.model_validate_json(body)
    except ValidationError as exc:
        raise HTTPException(422, "Invalid Songwai order") from exc
    if req.restaurant_id != SONGWAI_RESTAURANT_ID or req.order_id < 1:
        raise HTTPException(403, "Unmapped Songwai restaurant")
    if req.delivery_mode not in ("pickup", "rider") or req.payment_status not in ("pending", "paid"):
        raise HTTPException(400, "Invalid Songwai fulfillment or payment state")
    if len(req.customer_name.strip()) > 100 or len(req.contact_phone.strip()) > 30:
        raise HTTPException(400, "Invalid customer details")
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        external_id = str(req.order_id)
        existing = conn.execute("SELECT order_no FROM online_orders WHERE branch_id=1 AND source='songwai' AND external_id=?",
                                (external_id,)).fetchone()
        if existing:
            return _online_order_record(conn, existing[0])
        mapped = []
        for line in req.items:
            row = conn.execute("""SELECT pos_item_id FROM songwai_menu_map
                WHERE branch_id=1 AND restaurant_id=? AND songwai_menu_id=?""",
                (req.restaurant_id, line.menu_id)).fetchone()
            if not row:
                raise HTTPException(409, f"Songwai menu {line.menu_id} is not mapped")
            mapped.append({"id": row[0], "qty": line.qty})
        customer_id = None
        if req.user_id and req.user_id > 0:
            customer_id = upsert_customer(conn, branch_id=1, source="songwai",
                external_id=str(req.user_id), display_name=req.customer_name.strip(),
                phone=req.contact_phone.strip())
        try:
            result = create_commerce_order(conn, branch_id=1, source="songwai",
                external_id=external_id,
                fulfillment="self_pickup" if req.delivery_mode == "pickup" else "rider_pickup",
                items=mapped, customer_id=customer_id, customer_name=req.customer_name.strip(),
                contact_phone=req.contact_phone.strip(), payment_status=req.payment_status,
                channel="Songwai")
        except CatalogError as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc
        return _online_order_record(conn, result["order_no"])


class ManualChannelOrder(BaseModel):
    branch_id: int = 1
    channel: str
    external_order_id: str
    fulfillment: str
    items: list[OnlineOrderLine]
    customer_name: str = ""
    contact_phone: str = ""


@app.post("/api/online/manual-orders")
def create_manual_channel_order(req: ManualChannelOrder, request: Request):
    """Staff-entered partner orders; never represented as an API connection."""
    require_staff(request, roles=("manager", "owner", "cashier"), branch_id=req.branch_id)
    if req.channel not in ("GrabFood", "LINE MAN", "ShopeeFood", "TikTok Shop", "โทรศัพท์"):
        raise HTTPException(400, "Unsupported manual channel")
    if req.fulfillment not in ("self_pickup", "rider_pickup"):
        raise HTTPException(400, "Invalid fulfillment")
    if not re.fullmatch(r"[A-Za-z0-9_-]{2,80}", req.external_order_id):
        raise HTTPException(400, "Invalid partner order ID")
    if len(req.customer_name.strip()) > 100 or len(req.contact_phone.strip()) > 30:
        raise HTTPException(400, "Invalid customer details")
    external_id = "manual:" + req.channel + ":" + req.external_order_id
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute("SELECT order_no FROM online_orders WHERE branch_id=? AND source='poswai' AND external_id=?",
                                (req.branch_id, external_id)).fetchone()
        if existing:
            return _online_order_record(conn, existing[0])
        try:
            result = create_commerce_order(conn, branch_id=req.branch_id, source="poswai",
                external_id=external_id, fulfillment=req.fulfillment,
                items=[line.model_dump() for line in req.items], customer_id=None,
                customer_name=req.customer_name.strip(), contact_phone=req.contact_phone.strip(),
                channel=req.channel)
        except CatalogError as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc
        return _online_order_record(conn, result["order_no"])


class SongwaiMenuMap(BaseModel):
    branch_id: int = 1
    restaurant_id: int
    songwai_menu_id: int
    pos_item_id: str


@app.put("/api/integrations/songwai/menu-map")
def map_songwai_menu(req: SongwaiMenuMap, request: Request):
    require_staff(request, roles=("manager", "owner"), branch_id=req.branch_id)
    if req.restaurant_id != SONGWAI_RESTAURANT_ID or req.songwai_menu_id < 1 or not req.pos_item_id.strip():
        raise HTTPException(400, "Invalid Songwai menu mapping")
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        item = conn.execute("SELECT 1 FROM menu_catalog WHERE branch_id=? AND item_id=? AND active=1",
                            (req.branch_id, req.pos_item_id.strip())).fetchone()
        if not item:
            raise HTTPException(409, "POS menu item must be active first")
        conn.execute("""INSERT INTO songwai_menu_map(branch_id,restaurant_id,songwai_menu_id,pos_item_id)
            VALUES(?,?,?,?) ON CONFLICT(branch_id,restaurant_id,songwai_menu_id)
            DO UPDATE SET pos_item_id=excluded.pos_item_id""",
            (req.branch_id, req.restaurant_id, req.songwai_menu_id, req.pos_item_id.strip()))
    return {"status": "mapped", **req.model_dump()}


@app.get("/api/integrations/songwai/menu-map")
def list_songwai_menu_map(request: Request, branch_id: int = 1):
    require_staff(request, roles=("manager", "owner"), branch_id=branch_id)
    with closing(sqlite3.connect(DB_PATH)) as conn:
        rows = conn.execute("""SELECT songwai_menu_id,pos_item_id FROM songwai_menu_map
            WHERE branch_id=? AND restaurant_id=? ORDER BY songwai_menu_id""",
            (branch_id, SONGWAI_RESTAURANT_ID)).fetchall()
    return {"restaurant_id": SONGWAI_RESTAURANT_ID,
            "mappings": [{"songwai_menu_id": row[0], "pos_item_id": row[1]} for row in rows]}


@app.get("/api/integrations/songwai/catalog")
def get_songwai_catalog(request: Request, branch_id: int = 1):
    require_staff(request, roles=("manager", "owner"), branch_id=branch_id)
    if SONGWAI_RESTAURANT_ID < 1:
        raise HTTPException(503, "Songwai restaurant is not configured")
    try:
        response = httpx.get(f"https://songwai.online/api/restaurants/{SONGWAI_RESTAURANT_ID}/menus", timeout=8)
        response.raise_for_status()
        items = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, "Cannot load Songwai menu") from exc
    if not isinstance(items, list):
        raise HTTPException(502, "Invalid Songwai menu response")
    return {"restaurant_id": SONGWAI_RESTAURANT_ID, "items": [
        {"id": item.get("id"), "name": item.get("name") or item.get("name_th") or "",
         "price": item.get("price")}
        for item in items if isinstance(item, dict) and item.get("restaurant_id") == SONGWAI_RESTAURANT_ID
    ]}


@app.post("/api/integrations/songwai/import-drafts")
def import_songwai_drafts(request: Request, branch_id: int = 1):
    """Create inactive POS menu placeholders; never overwrite an existing recipe."""
    require_staff(request, roles=("manager", "owner"), branch_id=branch_id)
    catalog = get_songwai_catalog(request, branch_id)
    if catalog["restaurant_id"] != 37 or not catalog["items"]:
        raise HTTPException(409, "Expected restaurant 37 catalog")
    imported = 0
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        for item in catalog["items"]:
            menu_id = item.get("id")
            if isinstance(menu_id, bool) or not isinstance(menu_id, int) or menu_id < 1:
                raise HTTPException(502, "Invalid Songwai menu ID")
            pos_id = f"songwai-{menu_id}"
            existing = conn.execute("SELECT 1 FROM menu_catalog WHERE branch_id=? AND item_id=?",
                                    (branch_id, pos_id)).fetchone()
            if not existing:
                try:
                    upsert_menu_item(conn, branch_id, pos_id, item["name"], item["price"], [], False)
                except (CatalogError, KeyError) as exc:
                    raise HTTPException(502, "Invalid Songwai catalog item") from exc
                imported += 1
            conn.execute("""INSERT INTO songwai_menu_map(branch_id,restaurant_id,songwai_menu_id,pos_item_id)
                VALUES(?,?,?,?) ON CONFLICT(branch_id,restaurant_id,songwai_menu_id) DO NOTHING""",
                (branch_id, SONGWAI_RESTAURANT_ID, menu_id, pos_id))
    return {"restaurant_id": SONGWAI_RESTAURANT_ID, "imported": imported,
            "total": len(catalog["items"]), "status": "drafts_inactive"}


@app.get("/api/online/orders")
def list_online_orders(request: Request, branch_id: int = 1, status: str = "active"):
    require_staff(request, branch_id=branch_id)
    if status not in ("active", "all"):
        raise HTTPException(400, "Invalid order filter")
    with closing(sqlite3.connect(DB_PATH)) as conn:
        query = "SELECT order_no FROM online_orders WHERE branch_id=?"
        if status == "active":
            query += " AND status NOT IN ('handed_off','cancelled')"
        query += " ORDER BY created_at DESC LIMIT 200"
        return {"orders": [_online_order_record(conn, row[0]) for row in conn.execute(query, (branch_id,)).fetchall()]}


class OnlineStatusUpdate(BaseModel):
    status: str


@app.patch("/api/online/orders/{order_no}")
def update_online_order(order_no: str, req: OnlineStatusUpdate, request: Request):
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT branch_id,status FROM online_orders WHERE order_no=?", (order_no,)).fetchone()
        if not row:
            raise HTTPException(404, "Online order not found")
        require_staff(request, roles=("manager", "owner", "cashier", "kitchen", "service"), branch_id=row[0])
        allowed = {"new": {"accepted", "cancelled"}, "accepted": {"preparing", "cancelled"},
                   "preparing": {"ready", "cancelled"}, "ready": {"handed_off"}}
        if req.status == row[1]:
            return _online_order_record(conn, order_no)
        if req.status not in allowed.get(row[1], set()):
            raise HTTPException(409, "Invalid order status transition")
        if req.status == "handed_off":
            if not conn.execute("SELECT 1 FROM online_orders WHERE order_no=? AND payment_status='paid'", (order_no,)).fetchone():
                raise HTTPException(409, "Payment must be confirmed before handoff")
            mark_handed_off(conn, order_no)
        else:
            if req.status == "cancelled":
                from poswai_commerce import restore_cancelled_inventory
                restore_cancelled_inventory(conn, row[0], order_no)
            conn.execute("UPDATE online_orders SET status=?,ready_at=CASE WHEN ?='ready' THEN CURRENT_TIMESTAMP ELSE ready_at END WHERE order_no=?",
                         (req.status, req.status, order_no))
        return _online_order_record(conn, order_no)


@app.patch("/api/online/orders/{order_no}/payment")
def confirm_online_payment(order_no: str, request: Request):
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT branch_id,payment_status FROM online_orders WHERE order_no=?", (order_no,)).fetchone()
        if not row:
            raise HTTPException(404, "Online order not found")
        require_staff(request, roles=("manager", "owner", "cashier"), branch_id=row[0])
        if row[1] != "paid":
            conn.execute("UPDATE online_orders SET payment_status='paid' WHERE order_no=?", (order_no,))
        return _online_order_record(conn, order_no)


@app.get("/api/crm/customers")
def get_crm_customers(request: Request, branch_id: int = 1, segment: str = "all"):
    require_staff(request, roles=("manager", "owner"), branch_id=branch_id)
    if segment not in ("all", "new", "returning", "dormant30"):
        raise HTTPException(400, "Invalid customer segment")
    with closing(sqlite3.connect(DB_PATH)) as conn:
        customers = commerce_customers(conn, branch_id, segment)
    return {"branch_id": branch_id, "segment": segment, "customers": customers}


class CustomerConsent(BaseModel):
    branch_id: int = 1
    line_id_token: str
    marketing_opt_in: bool


@app.post("/api/crm/me/consent")
def set_customer_consent(req: CustomerConsent):
    if req.branch_id < 1:
        raise HTTPException(400, "Invalid branch")
    line_id = verify_liff_id_token(req.line_id_token, LINE_LOGIN_CHANNEL_ID)
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        customer_id = upsert_customer(conn, branch_id=req.branch_id, source="line",
            external_id=line_id, marketing_opt_in=req.marketing_opt_in)
    return {"customer_id": customer_id, "marketing_opt_in": req.marketing_opt_in}


class CampaignDraft(BaseModel):
    branch_id: int = 1
    segment: str
    message: str


@app.post("/api/crm/campaigns")
def create_campaign(req: CampaignDraft, request: Request):
    manager = require_staff(request, roles=("manager", "owner"), branch_id=req.branch_id)
    if req.segment not in ("new", "returning", "dormant30") or not 1 <= len(req.message.strip()) <= 500:
        raise HTTPException(400, "Invalid campaign")
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        audience = [c for c in commerce_customers(conn, req.branch_id, req.segment)
                    if c["marketing_opt_in"] and c["line_linked"]]
        cursor = conn.execute("INSERT INTO crm_campaigns(branch_id,segment,message,created_by) VALUES(?,?,?,?)",
                              (req.branch_id, req.segment, req.message.strip(), manager["id"]))
    return {"campaign_id": cursor.lastrowid, "status": "draft", "eligible_recipients": len(audience)}


@app.get("/api/crm/campaigns/{campaign_id}")
def get_campaign(campaign_id: int, request: Request):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT id,branch_id,segment,message,status,created_at,sent_at FROM crm_campaigns WHERE id=?",
                           (campaign_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Campaign not found")
        require_staff(request, roles=("manager", "owner"), branch_id=row["branch_id"])
        audience = [c for c in commerce_customers(conn, row["branch_id"], row["segment"])
                    if c["marketing_opt_in"] and c["line_linked"]]
        counts = dict(conn.execute("SELECT status,COUNT(*) FROM crm_campaign_deliveries WHERE campaign_id=? GROUP BY status",
                                   (campaign_id,)).fetchall())
    return {**dict(row), "eligible_recipients": len(audience), "delivery_attempts": counts}


@app.post("/api/crm/campaigns/{campaign_id}/send")
def send_campaign(campaign_id: int, request: Request):
    if not LINE_CHANNEL_ACCESS_TOKEN:
        raise HTTPException(503, "LINE OA is not configured")
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.row_factory = sqlite3.Row
        campaign = conn.execute("SELECT id,branch_id,segment,message,status FROM crm_campaigns WHERE id=?",
                                (campaign_id,)).fetchone()
        if not campaign:
            raise HTTPException(404, "Campaign not found")
        require_staff(request, roles=("manager", "owner"), branch_id=campaign["branch_id"])
        if campaign["status"] != "draft":
            raise HTTPException(409, "Campaign was already submitted")
        recipients = [row for row in conn.execute("SELECT * FROM crm_customers WHERE branch_id=? AND marketing_opt_in=1 AND line_user_id IS NOT NULL",
                                                (campaign["branch_id"],)).fetchall()
                      if segment_for(row) == campaign["segment"]]
        if not recipients:
            raise HTTPException(409, "No opted-in LINE recipients in this segment")
        if len(recipients) > 50:
            raise HTTPException(409, "Campaign exceeds the 50-recipient safety limit")
        conn.execute("UPDATE crm_campaigns SET status='submitting',sent_at=CURRENT_TIMESTAMP WHERE id=?", (campaign_id,))
        for recipient in recipients:
            conn.execute("INSERT INTO crm_campaign_deliveries(campaign_id,customer_id,status) VALUES(?,?,'unknown')",
                         (campaign_id, recipient["id"]))
    # Mark each attempt before contacting LINE. A timeout stays unknown and is
    # never retried automatically, so an ambiguous response cannot double-send.
    accepted = 0
    with httpx.Client(timeout=8.0) as client:
        for recipient in recipients:
            try:
                response = client.post("https://api.line.me/v2/bot/message/push",
                    headers={"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"},
                    json={"to": recipient["line_user_id"], "messages": [
                        {"type": "text", "text": campaign["message"]}]})
                status = "accepted" if response.status_code == 200 else "rejected"
            except httpx.HTTPError:
                status = "unknown"
            accepted += status == "accepted"
            with closing(sqlite3.connect(DB_PATH)) as conn, conn:
                conn.execute("UPDATE crm_campaign_deliveries SET status=? WHERE campaign_id=? AND customer_id=?",
                             (status, campaign_id, recipient["id"]))
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        conn.execute("UPDATE crm_campaigns SET status='submitted' WHERE id=?", (campaign_id,))
    return {"campaign_id": campaign_id, "status": "submitted", "line_accepted": accepted,
            "attempted": len(recipients), "note": "LINE HTTP acceptance does not prove message delivery"}


@app.post("/api/orders")
def create_order(req: OrderCreate, request: Request):
    if not math.isfinite(req.total_amount) or req.total_amount < 0 or not req.items or any(not math.isfinite(item.price) for item in req.items):
        raise HTTPException(400, "Invalid order")
    require_table_or_staff(request, req.branch_id, req.table_no)
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        cur = conn.cursor()
        existing = cur.execute("SELECT event_id,order_no FROM order_events WHERE event_id=? OR order_no=?", (req.event_id, req.order_no)).fetchone()
        if existing:
            if existing != (req.event_id, req.order_no):
                raise HTTPException(409, "Order event ID or number already belongs to another order")
            return {"status": "existing", "order_no": existing[1]}
        try:
            quote = quote_order(conn, req.branch_id, req.items)
            if round(req.total_amount * 100) != quote["total_cents"]:
                raise CatalogError("Order total differs from current menu prices", 409)
            if any(round(item.price * 100) != round(canonical["price"] * 100) for item, canonical in zip(req.items, quote["items"])):
                raise CatalogError("Order item price differs from current menu", 409)
            deduct_inventory(conn, req.branch_id, quote["deductions"])
        except CatalogError as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc
        cur.execute("INSERT INTO order_events (event_id, order_no, branch_id, table_no, total_amount) VALUES (?,?,?,?,?)",
                    (req.event_id, req.order_no, req.branch_id, req.table_no, quote["total_amount"]))
        for item in quote["items"]:
            cur.execute("INSERT INTO order_items (order_no,item_id,name,quantity,unit_price,bom_json,station,course_mode) VALUES (?,?,?,?,?,?,?,?)",
                        (req.order_no, item["id"], item["name"], item["qty"], item["price"],
                         json.dumps(item["bom"]), item["station"], item["course_mode"]))
        for station in {item["station"] for item in quote["items"]}:
            status = "held" if any(item["station"] == station and item["course_mode"] == "HOLD" for item in quote["items"]) else "queued"
            cur.execute("INSERT INTO kds_station_tickets (order_no,station,status) VALUES (?,?,?)",
                        (req.order_no, station, status))
    return {"status": "open", "order_no": req.order_no}


@app.get("/api/orders")
def list_open_orders(request: Request, branch_id: int = 1, table_no: str = ""):
    if branch_id < 1:
        raise HTTPException(400, "Invalid branch")
    if table_no:
        require_table_or_staff(request, branch_id, table_no)
    else:
        require_staff(request, branch_id=branch_id)
    query = "SELECT order_no,table_no,total_amount,status,created_at FROM order_events WHERE branch_id=? AND status='open'"
    params: list = [branch_id]
    if table_no:
        query += " AND table_no=?"
        params.append(table_no)
    query += " ORDER BY created_at DESC LIMIT 200"
    with closing(sqlite3.connect(DB_PATH)) as conn:
        orders = []
        for row in conn.execute(query, params).fetchall():
            items = conn.execute("SELECT item_id,name,quantity,unit_price,bom_json,station,course_mode FROM order_items WHERE order_no=?", (row[0],)).fetchall()
            orders.append({"order_no": row[0], "table_no": row[1], "total_amount": row[2],
                           "status": row[3], "created_at": row[4],
                           "items": [{"id": item[0], "name": item[1], "qty": item[2], "price": item[3],
                                      "bom": json.loads(item[4]), "station": item[5],
                                      "courseMode": item[6]} for item in items]})
    return {"branch_id": branch_id, "orders": orders}


@app.get("/api/kds")
def list_kds_tickets(request: Request, branch_id: int = 1):
    require_staff(request, branch_id=branch_id)
    with closing(sqlite3.connect(DB_PATH)) as conn:
        rows = conn.execute(
            "SELECT k.order_no,k.station,k.status,k.created_at,k.fired_at,k.ready_at,oe.table_no "
            "FROM kds_station_tickets k JOIN order_events oe ON oe.order_no=k.order_no "
            "WHERE oe.branch_id=? AND (k.status!='ready' OR k.created_at>=datetime('now','-1 day')) "
            "ORDER BY k.created_at DESC LIMIT 300", (branch_id,),
        ).fetchall()
        tickets = []
        for row in rows:
            items = conn.execute(
                "SELECT name,quantity,course_mode FROM order_items WHERE order_no=? AND station=?",
                (row[0], row[1]),
            ).fetchall()
            tickets.append({"order_no": row[0], "station": row[1], "status": row[2],
                            "created_at": row[3], "fired_at": row[4], "ready_at": row[5],
                            "table_no": row[6], "items": [{"name": item[0], "qty": item[1],
                                                             "course_mode": item[2]} for item in items]})
    return {"branch_id": branch_id, "tickets": tickets}


def _advance_kds_ticket(request: Request, order_no: str, station: str, action: str) -> dict:
    if station not in STATIONS:
        raise HTTPException(400, "Invalid kitchen station")
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        row = conn.execute("SELECT k.status,oe.branch_id FROM kds_station_tickets k "
                           "JOIN order_events oe ON oe.order_no=k.order_no "
                           "WHERE k.order_no=? AND k.station=?", (order_no, station)).fetchone()
        if not row:
            raise HTTPException(404, "Kitchen ticket not found")
        roles = ("manager", "owner", "kitchen", "cashier", "service") if action == "fire" else ("manager", "owner", "kitchen")
        require_staff(request, roles=roles, branch_id=row[1])
        status = row[0]
        if action == "fire":
            if status == "held":
                conn.execute("UPDATE kds_station_tickets SET status='queued',fired_at=CURRENT_TIMESTAMP "
                             "WHERE order_no=? AND station=?", (order_no, station))
                conn.execute("UPDATE order_items SET course_mode='FIRE' WHERE order_no=? AND station=?",
                             (order_no, station))
                status = "queued"
        elif status == "held":
            raise HTTPException(409, "Fire the held course before marking ready")
        elif status == "queued":
            conn.execute("UPDATE kds_station_tickets SET status='ready',ready_at=CURRENT_TIMESTAMP "
                         "WHERE order_no=? AND station=?", (order_no, station))
            status = "ready"
    return {"order_no": order_no, "station": station, "status": status}


@app.post("/api/kds/{order_no}/{station}/fire")
def fire_kds_ticket(order_no: str, station: str, request: Request):
    return _advance_kds_ticket(request, order_no, station, "fire")


@app.post("/api/kds/{order_no}/{station}/ready")
def ready_kds_ticket(order_no: str, station: str, request: Request):
    return _advance_kds_ticket(request, order_no, station, "ready")


class PaymentCreate(BaseModel):
    event_id: str
    order_no: str
    amount: float
    method: str
    slip_reference: Optional[str] = None


class VerifiedTablePaymentCreate(BaseModel):
    event_id: str
    branch_id: int = 1
    table_no: str
    order_nos: list[str]
    amount: float
    slip_image: str


@app.post("/api/payments/close-table")
def close_table_with_verified_slip(req: VerifiedTablePaymentCreate, request: Request):
    """Close one table's listed orders only after EasySlip verifies the same total."""
    if (not req.event_id or len(req.event_id) > 80 or req.branch_id < 1 or
            not req.table_no.strip() or len(req.table_no.strip()) > 24 or
            not math.isfinite(req.amount) or req.amount <= 0):
        raise HTTPException(400, "Invalid payment event")
    if not req.order_nos or len(req.order_nos) > 100 or len(set(req.order_nos)) != len(req.order_nos):
        raise HTTPException(400, "Invalid order list")
    cashier = require_staff(request, roles=("manager", "owner", "cashier"), branch_id=req.branch_id)
    if not os.getenv("EASYSLIP_API_KEY", ""):
        raise HTTPException(503, "EasySlip is not configured")
    order_nos = sorted(req.order_nos)
    placeholders = ",".join("?" for _ in order_nos)
    with closing(sqlite3.connect(DB_PATH)) as conn:
        prior = conn.execute("SELECT order_nos_json,amount,branch_id,table_no FROM table_payment_events WHERE event_id=?", (req.event_id,)).fetchone()
        if prior:
            if (json.loads(prior[0]) != order_nos or abs(float(prior[1]) - req.amount) > 0.01 or
                    prior[2] != req.branch_id or prior[3] != req.table_no.strip()):
                raise HTTPException(409, "Payment event has different orders or amount")
            return {"status": "paid", "order_nos": order_nos, "existing": True}
        rows = conn.execute(f"SELECT order_no,branch_id,table_no,total_amount,status FROM order_events WHERE order_no IN ({placeholders})", order_nos).fetchall()
    if len(rows) != len(order_nos) or any(row[1] != req.branch_id or row[2] != req.table_no or row[4] != "open" for row in rows):
        raise HTTPException(409, "Orders are not open on the selected table and branch")
    expected_cents = sum(round(float(row[3]) * 100) for row in rows)
    if expected_cents <= 0 or round(req.amount * 100) != expected_cents:
        raise HTTPException(409, "Slip amount does not match the unpaid order total")
    try:
        slip_reference = verify_bank_slip(req.slip_image, expected_cents / 100, os.environ["EASYSLIP_API_KEY"])
    except SlipVerificationError as exc:
        raise HTTPException(422, str(exc)) from exc
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        prior = conn.execute("SELECT order_nos_json,amount,branch_id,table_no FROM table_payment_events WHERE event_id=?", (req.event_id,)).fetchone()
        if prior:
            if (json.loads(prior[0]) != order_nos or abs(float(prior[1]) - req.amount) > 0.01 or
                    prior[2] != req.branch_id or prior[3] != req.table_no.strip()):
                raise HTTPException(409, "Payment event has different orders or amount")
            return {"status": "paid", "order_nos": order_nos, "existing": True}
        if conn.execute("SELECT 1 FROM table_payment_events WHERE slip_reference=?", (slip_reference,)).fetchone():
            raise HTTPException(409, "Slip transaction reference was already used")
        current = conn.execute(f"SELECT order_no,status,total_amount,branch_id,table_no FROM order_events WHERE order_no IN ({placeholders})", order_nos).fetchall()
        if len(current) != len(order_nos) or any(row[1] != "open" or row[3] != req.branch_id or row[4] != req.table_no for row in current):
            raise HTTPException(409, "One or more orders were already closed")
        conn.execute("INSERT INTO table_payment_events(event_id,branch_id,table_no,order_nos_json,amount,slip_reference) VALUES (?,?,?,?,?,?)",
                     (req.event_id, req.branch_id, req.table_no, json.dumps(order_nos), expected_cents / 100, slip_reference))
        for row in current:
            order_no, amount = row[0], float(row[2])
            conn.execute("INSERT INTO payment_events(event_id,order_no,amount,method,slip_reference) VALUES (?,?,?,?,?)",
                         (f"{req.event_id}:{order_no}", order_no, amount, "QR PromptPay", slip_reference))
            conn.execute("UPDATE order_events SET status='paid' WHERE order_no=?", (order_no,))
            cursor = conn.execute("INSERT INTO pos_orders(branch_id,order_no,closed_by_staff_id,total_amount,net_amount,payment_method) VALUES (?,?,?,?,?,?)",
                                  (req.branch_id, order_no, cashier["id"], amount, amount, "QR PromptPay"))
            allocate_commissions(conn, cursor.lastrowid)
    return {"status": "paid", "order_nos": order_nos, "slip_reference": slip_reference}


@app.post("/api/payments/close")
def close_payment(req: PaymentCreate, request: Request):
    if not math.isfinite(req.amount) or req.amount <= 0:
        raise HTTPException(400, "Invalid amount")
    if req.method != "เงินสด (Cash)" or req.slip_reference:
        raise HTTPException(501, "Use verified EasySlip flow for QR; other payment providers are not configured")
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        cur = conn.cursor()
        order = cur.execute("SELECT branch_id, status, total_amount FROM order_events WHERE order_no=?", (req.order_no,)).fetchone()
        if not order:
            raise HTTPException(404, "Order not found")
        cashier = require_staff(request, roles=("manager", "owner", "cashier"), branch_id=order[0])
        existing = cur.execute("SELECT order_no FROM payment_events WHERE event_id=?", (req.event_id,)).fetchone()
        if existing:
            if existing[0] != req.order_no:
                raise HTTPException(409, "Payment event already belongs to another order")
            return {"status": "paid", "order_no": existing[0], "commission": {"status": "already_processed"}}
        if order[1] != "open":
            raise HTTPException(409, "Order already closed")
        if abs(req.amount - order[2]) > 0.01:
            raise HTTPException(409, "Payment does not match order total")
        cur.execute("INSERT INTO payment_events (event_id, order_no, amount, method, slip_reference) VALUES (?,?,?,?,?)",
                    (req.event_id, req.order_no, req.amount, req.method, req.slip_reference))
        cur.execute("UPDATE order_events SET status='paid' WHERE order_no=?", (req.order_no,))
        cur.execute("INSERT INTO pos_orders (branch_id, order_no, closed_by_staff_id, total_amount, net_amount, payment_method) VALUES (?,?,?,?,?,?)",
                    (order[0], req.order_no, cashier["id"], req.amount, req.amount, req.method))
        commission = allocate_commissions(conn, cur.lastrowid)
    return {"status": "paid", "order_no": req.order_no, "commission": commission}


class AttendanceCreate(BaseModel):
    event_id: str
    staff_id: int
    action: str


@app.post("/api/attendance")
def record_attendance(req: AttendanceCreate, request: Request):
    if req.action not in ("clock_in", "clock_out"):
        raise HTTPException(400, "Invalid attendance action")
    staff = require_staff(request)
    if staff["id"] != req.staff_id and staff["role"] not in ("manager", "owner"):
        raise HTTPException(403, "Cannot record attendance for another staff member")
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        target = conn.execute("SELECT branch_id,is_active FROM staffs WHERE id=?", (req.staff_id,)).fetchone()
        if not target or not target[1]:
            raise HTTPException(404, "Active staff not found")
        if target[0] != staff["branch_id"]:
            raise HTTPException(403, "Staff branch not permitted")
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
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
def commissions(request: Request, work_date: str, branch_id: int = 1):
    require_staff(request, roles=("manager", "owner"), branch_id=branch_id)
    try:
        datetime.date.fromisoformat(work_date)
    except ValueError:
        raise HTTPException(400, "work_date must be YYYY-MM-DD")
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        sales = conn.execute("SELECT COALESCE(SUM(net_amount),0) FROM pos_orders "
                             "WHERE branch_id=? AND status='paid' AND date(closed_at,'+7 hours')=?",
                             (branch_id, work_date)).fetchone()[0]
        allocation = conn.execute(
            "SELECT COALESCE(SUM(cr.calculated_amount),0), COALESCE(MAX(cr.pool_divisor),0) "
            "FROM commission_records cr JOIN pos_orders po ON po.id=cr.order_id "
            "WHERE po.branch_id=? AND po.status='paid' AND cr.period_date=?",
            (branch_id, work_date),
        ).fetchone()
    pool = round(allocation[0], 2)
    divisor = allocation[1]
    return {"sales": round(sales, 2), "pool": pool, "pool_divisor": divisor,
            "equal_share": round(pool / divisor, 2) if divisor else 0.0}


@app.get("/api/staff/payroll")
def staff_payroll(request: Request, month: str, branch_id: int = 1):
    """Read-only staff ledger. Rates here are configured payroll inputs, not statutory rates."""
    require_staff(request, roles=("manager", "owner"), branch_id=branch_id)
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise HTTPException(400, "month must be YYYY-MM")
    if branch_id < 1:
        raise HTTPException(400, "Invalid branch")
    start = datetime.date.fromisoformat(f"{month}-01")
    end = (start.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
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


@app.get("/api/staff/overview")
def staff_overview(request: Request, branch_id: int = 1):
    """Manager's live roster and leave inbox for one branch."""
    require_staff(request, roles=("manager", "owner"), branch_id=branch_id)
    today = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=7))).date().isoformat()
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        staff_rows = conn.execute(
            "SELECT s.id,s.name,s.role,s.branch_id,ss.status,ss.pos_pin_locked,"
            "st.name AS shift_name,st.start_time,st.end_time,"
            "(SELECT MAX(a.clock_in) FROM attendances a WHERE a.staff_id=s.id AND substr(a.clock_in,1,10)=?) AS clock_in "
            "FROM staffs s LEFT JOIN staff_shifts ss ON ss.staff_id=s.id AND ss.work_date=? "
            "LEFT JOIN shift_templates st ON st.id=ss.shift_template_id "
            "WHERE s.branch_id=? AND s.is_active=1 ORDER BY s.id",
            (today, today, branch_id),
        ).fetchall()
        leaves = conn.execute(
            "SELECT l.id,l.staff_id,s.name AS staff_name,l.leave_type,l.start_date,l.end_date,"
            "l.reason,l.status,l.created_at FROM leave_requests l "
            "JOIN staffs s ON s.id=l.staff_id WHERE s.branch_id=? "
            "ORDER BY l.created_at DESC,l.id DESC LIMIT 100", (branch_id,),
        ).fetchall()
        commissions = conn.execute(
            "SELECT cr.staff_id,COALESCE(SUM(cr.calculated_amount),0) AS amount "
            "FROM commission_records cr JOIN staffs s ON s.id=cr.staff_id "
            "WHERE s.branch_id=? AND cr.period_date=? GROUP BY cr.staff_id", (branch_id, today),
        ).fetchall()
    by_staff_commission = {row["staff_id"]: round(float(row["amount"]), 2) for row in commissions}
    staff = [{"id": row["id"], "name": row["name"], "role": row["role"],
              "shift": row["shift_name"] or (f"{row['start_time']}–{row['end_time']}" if row["start_time"] else "—"),
              "status": row["status"] or ("completed" if row["clock_in"] else "scheduled"),
              "pos_pin_locked": bool(row["pos_pin_locked"]), "clock_in": row["clock_in"],
              "commission_today": by_staff_commission.get(row["id"], 0.0)} for row in staff_rows]
    return {"branch_id": branch_id, "work_date": today, "staff": staff,
            "leave_requests": [dict(row) for row in leaves],
            "note": "Only recorded shifts, attendance, approved leave and commission entries are shown."}


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
    line_id_token: Optional[str] = None


class LeaveApprovalAction(BaseModel):
    leave_id: int
    decision: str  # 'approved' or 'rejected'


class LineLinkRequest(BaseModel):
    line_id_token: str


@app.post("/api/line-liff/link")
def link_line_staff(req: LineLinkRequest, request: Request):
    staff = require_staff(request)
    line_user_id = verify_liff_id_token(req.line_id_token, LINE_LOGIN_CHANNEL_ID)
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        owner = conn.execute("SELECT id FROM staffs WHERE line_user_id=?", (line_user_id,)).fetchone()
        if owner and owner[0] != staff["id"]:
            raise HTTPException(status_code=409, detail="LINE account is already linked to another staff member")
        current = conn.execute("SELECT line_user_id FROM staffs WHERE id=?", (staff["id"],)).fetchone()
        if current and current[0] and current[0] != line_user_id:
            raise HTTPException(status_code=409, detail="Staff account is already linked to another LINE account")
        conn.execute("UPDATE staffs SET line_user_id=? WHERE id=?", (line_user_id, staff["id"]))
    return {"status": "linked", "staff_id": staff["id"]}


def _review_leave(leave_id: int, manager_staff_id: int, decision: str) -> dict:
    if decision not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="Invalid leave decision")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT l.staff_id, l.start_date, l.end_date, l.status, s.branch_id "
            "FROM leave_requests l JOIN staffs s ON s.id=l.staff_id WHERE l.id=?", (leave_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Leave request not found")
        manager = conn.execute("SELECT branch_id FROM staffs WHERE id=? AND is_active=1", (manager_staff_id,)).fetchone()
        if not manager or manager["branch_id"] != row["branch_id"]:
            raise HTTPException(status_code=403, detail="Manager is not assigned to this branch")
        if row["status"] != "pending":
            return {"status": row["status"], "leave_id": leave_id, "already_reviewed": True}
        conn.execute(
            "UPDATE leave_requests SET status=?, reviewed_by=?, reviewed_at=? WHERE id=?",
            (decision, manager_staff_id, datetime.datetime.now().isoformat(timespec="seconds"), leave_id),
        )
        if decision == "approved":
            start = datetime.date.fromisoformat(row["start_date"])
            end = datetime.date.fromisoformat(row["end_date"])
            for offset in range((end - start).days + 1):
                work_date = (start + datetime.timedelta(days=offset)).isoformat()
                conn.execute(
                    "INSERT INTO staff_shifts (staff_id, branch_id, work_date, status, pos_pin_locked) "
                    "VALUES (?, ?, ?, 'on_leave', 1) "
                    "ON CONFLICT(staff_id, work_date) DO UPDATE SET status='on_leave', pos_pin_locked=1",
                    (row["staff_id"], row["branch_id"], work_date),
                )
        conn.commit()
        return {"status": decision, "leave_id": leave_id, "staff_id": row["staff_id"],
                "pos_pin_locked": decision == "approved", "work_date": row["start_date"]}
    finally:
        conn.close()


@app.post("/api/line-liff/leave-requests")
def submit_leave_request(req: LeaveRequestCreate):
    """1. พนักงานกดยื่นใบลาผ่าน LINE LIFF -> บันทึกเป็น Pending และเตรียมส่ง Flex Message หาผู้จัดการ"""
    line_user_id = verify_liff_id_token(req.line_id_token or "", LINE_LOGIN_CHANNEL_ID)
    try:
        start = datetime.date.fromisoformat(req.start_date)
        end = datetime.date.fromisoformat(req.end_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid leave dates") from exc
    if end < start or (end - start).days > 90:
        raise HTTPException(status_code=400, detail="Invalid leave date range")
    if req.leave_type not in ("sick", "personal", "vacation", "swap_shift"):
        raise HTTPException(status_code=400, detail="Invalid leave type")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    staff = cur.execute("SELECT id, branch_id, name FROM staffs WHERE id=? AND line_user_id=? AND is_active=1",
                        (req.staff_id, line_user_id)).fetchone()
    if not staff:
        conn.close()
        raise HTTPException(status_code=403, detail="LINE account is not linked to this staff member")
    existing = cur.execute("SELECT leave_id FROM leave_event_ids WHERE event_id=?", (req.event_id,)).fetchone()
    if existing:
        conn.close()
        return {"status": "pending", "leave_id": existing[0], "line_flex_notification": "already_created"}
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
    managers = [row[0] for row in cur.execute(
        "SELECT line_user_id FROM staffs WHERE branch_id=? AND role IN ('manager','owner') "
        "AND is_active=1 AND line_user_id IS NOT NULL", (staff["branch_id"],))]
    conn.close()
    notification = push_leave_request(
        LINE_CHANNEL_ACCESS_TOKEN, managers,
        build_leave_flex(leave_id, staff["name"], req.leave_type, req.start_date, req.end_date, req.reason),
    )
    return {
        "status": "pending",
        "leave_id": leave_id,
        "line_flex_notification": notification,
    }


@app.post("/api/line-webhook/approve-leave")
def manager_review_leave(action: LeaveApprovalAction, request: Request):
    """
    2. ผู้จัดการกดปุ่ม [อนุมัติ] หรือ [ปฏิเสธ] บน LINE Flex Message:
       - หาก 'approved':
         1) อัปเดต staff_shifts.status = 'on_leave'
         2) ตั้งค่า pos_pin_locked = 1 เพื่อป้องกันเพื่อนร่วมงานนำรหัส PIN ไปสวมสิทธิ์เปิดบิล
         3) ตัดชื่อออกจากตัวหารค่าคอมมิชชันกองกลาง (pool_divisor) ในวันดังกล่าวอัตโนมัติ
    """
    manager = require_staff(request, roles=("manager", "owner"))
    return _review_leave(action.leave_id, manager["id"], action.decision)


@app.post("/api/line-webhook")
async def line_webhook(request: Request):
    body = await request.body()
    verify_webhook_signature(body, request.headers.get("x-line-signature"), LINE_CHANNEL_SECRET)
    try:
        events = json.loads(body).get("events", [])
    except (ValueError, AttributeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid LINE event body") from exc
    reviewed = []
    for event in events:
        if event.get("type") != "postback":
            continue
        parsed = parse_leave_postback(event.get("postback", {}).get("data", ""))
        line_user_id = event.get("source", {}).get("userId")
        if not parsed or not line_user_id:
            continue
        with closing(sqlite3.connect(DB_PATH)) as conn:
            manager = conn.execute(
                "SELECT id FROM staffs WHERE line_user_id=? AND role IN ('manager','owner') AND is_active=1",
                (line_user_id,),
            ).fetchone()
        if manager:
            reviewed.append(_review_leave(parsed[0], manager[0], parsed[1]))
    return {"status": "ok", "reviewed": reviewed}


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
def get_executive_analytics_dashboard(request: Request, benchmark: str = "WOW", branch_id: int = 1):
    require_staff(request, roles=("manager", "owner"), branch_id=branch_id)
    try:
        return build_analytics_dashboard(DB_PATH, benchmark, branch_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


app.mount("/assets", StaticFiles(directory=Path(__file__).parent / "assets"), name="assets")


@app.get("/service-worker.js")
def serve_worker():
    return FileResponse(Path(__file__).parent / "service-worker.js", media_type="application/javascript",
                        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"})


@app.get("/{asset_name}.css")
def serve_workspace_css(asset_name: str):
    if asset_name not in {"ui", "workspace", "sales-redesign", "ops-redesign", "people-redesign", "reports-restore", "reports-live", "service-call", "auth-ui", "payment-ui", "live-data", "inventory-live"}:
        raise HTTPException(404, "Stylesheet not found")
    return FileResponse(Path(__file__).parent / f"{asset_name}.css", media_type="text/css")


@app.get("/{asset_name}.js")
def serve_workspace_js(asset_name: str):
    if asset_name not in {"workspace", "sales-redesign", "ops-redesign", "people-redesign", "reports-restore", "reports-live", "service-call", "auth-ui", "payment-ui", "live-data", "inventory-live"}:
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
