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
import asyncio
import csv
import html
import io
import mimetypes
from contextlib import asynccontextmanager
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
import threading
import httpx
from contextlib import closing
from contextvars import ContextVar
from typing import List, Optional
from pathlib import Path
from urllib.parse import urlencode
from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pydantic import ValidationError
from poswai_analytics import build_analytics_dashboard
from poswai_commissions import allocate_commissions
from poswai_inventory import (InventoryError, apply_inventory_movement,
                              init_inventory_movements, list_inventory_movements)
from easyslip import SlipVerificationError, verify_bank_slip
from poswai_catalog import (CatalogError, deduct_inventory, delete_menu_item, init_catalog,
                            list_menu_categories, list_menu_items, quote_order,
                            set_menu_photo, set_menu_status, upsert_menu_item,
                            STATIONS, TAX_MODES)
from poswai_printing import (PrintError, agent_for_key, delete_agent, finish_job, init_printing,
                            issue_agent, list_agents, queue_job, take_job, waiting_count)
from poswai_tables import (TableError, add_table, delete_table, init_tables, list_tables,
                           reissue_code, resolve_code, set_active)
from poswai_dossier import (DossierError, add_asset, add_timeline_entry, branch_summary,
                            init_dossier, read_dossier, return_asset, set_document,
                            update_profile)
from poswai_commerce import (create_order as create_commerce_order, init_commerce,
                             list_customers as commerce_customers, mark_handed_off,
                             restore_cancelled_inventory, segment_for, upsert_customer,
                             upsert_social_customer, POINT_BAHT)
from line_integration import (build_leave_flex, parse_leave_postback,
                              push_leave_request, verify_liff_id_token,
                              verify_webhook_signature)
from line_notifications import enqueue as enqueue_line_notification, flush as flush_line_notifications, init_notifications
import poswai_shops as shops
import poswai_owner_auth as owner_auth
from poswai_shops import DEMO_SHOP, MAIN_SHOP, ShopError
import poswai_billing as billing

async def _line_outbox_worker():
    while True:
        try:
            if LINE_CHANNEL_ACCESS_TOKEN and (not PREVIEW_ONLY or STAFF_LIVE):
                def send_due():
                    with closing(connect_db()) as conn:
                        flush_line_notifications(conn, LINE_CHANNEL_ACCESS_TOKEN)
                await asyncio.to_thread(send_due)
        except (sqlite3.Error, OSError):
            pass  # Keep the outbox intact; the next pass will retry.
        await asyncio.sleep(60)


@asynccontextmanager
async def app_lifespan(_app: FastAPI):
    worker = asyncio.create_task(_line_outbox_worker())
    try:
        yield
    finally:
        worker.cancel()
        try:
            await worker
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="POS WAI Enterprise V3 API (Leave, Shift, POS Lock & Commission Engine)",
    version="3.0.0",
    lifespan=app_lifespan,
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
# An owner signs in with an account, not a shop code. A channel only appears on
# the sign-in page once its own credentials are set, so a button never leads to
# a dead end.
LINE_LOGIN_CHANNEL_SECRET = os.getenv("LINE_LOGIN_CHANNEL_SECRET", "")
GOOGLE_CLIENT_ID = os.getenv("POSWAI_GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("POSWAI_GOOGLE_CLIENT_SECRET", "")
# Where the provider sends an owner back after signing in. It has to match the
# callback URL registered in the LINE and Google consoles character for
# character, so it is a setting rather than something guessed from headers.
PUBLIC_BASE_URL = os.getenv("POSWAI_PUBLIC_BASE_URL", "").strip().rstrip("/")
FACEBOOK_APP_ID = os.getenv("POSWAI_FACEBOOK_APP_ID", "")
FACEBOOK_APP_SECRET = os.getenv("POSWAI_FACEBOOK_APP_SECRET", "")
OWNER_EMAIL_LOGIN = os.getenv("POSWAI_OWNER_EMAIL_LOGIN", "0") == "1"
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "")
PREVIEW_ONLY = os.getenv("POSWAI_PREVIEW_ONLY", "0") == "1"
STAFF_LIVE = os.getenv("POSWAI_STAFF_LIVE", "0") == "1"
BOOTSTRAP_MANAGER_PIN = os.getenv("POSWAI_BOOTSTRAP_MANAGER_PIN", "")
TABLE_QR_SECRET = os.getenv("POSWAI_TABLE_QR_SECRET", "")
SONGWAI_WEBHOOK_SECRET = os.getenv("SONGWAI_WEBHOOK_SECRET", "")
SONGWAI_RESTAURANT_ID = int(os.getenv("SONGWAI_RESTAURANT_ID", "0"))
SESSION_LIFETIME = 12 * 60 * 60
MAX_SHOPS = int(os.getenv("POSWAI_MAX_SHOPS", "500"))
# Monthly service fee the hosted shops pay ZZAX Studio. The receiving PromptPay
# account and its EasySlip key belong to ZZAX Studio, never to a shop, so they are
# separate settings from PROMPTPAY_ID and EASYSLIP_API_KEY above.
MONTHLY_PRICE = float(os.getenv("POSWAI_MONTHLY_PRICE", "399"))
SERVICE_PROMPTPAY_ID = re.sub(r"[\s-]", "", os.getenv("POSWAI_SERVICE_PROMPTPAY_ID", ""))
SERVICE_EASYSLIP_API_KEY = os.getenv("POSWAI_SERVICE_EASYSLIP_API_KEY", "")
# The ZZAX Studio billing page is not a staff account: it opens with this key alone.
ADMIN_KEY = os.getenv("POSWAI_ADMIN_KEY", "")
# Shown to a shop that was suspended or closed, so it knows who to call.
SUPPORT_CONTACT = os.getenv("POSWAI_SUPPORT_CONTACT", "").strip()[:120]
SUPPORT_CONTACT = f" ({SUPPORT_CONTACT})" if SUPPORT_CONTACT else ""
if not math.isfinite(MONTHLY_PRICE) or MONTHLY_PRICE <= 0:
    raise RuntimeError("Invalid POSWAI_MONTHLY_PRICE")
if SERVICE_PROMPTPAY_ID and not re.fullmatch(r"\d{10}|\d{13}|\d{15}", SERVICE_PROMPTPAY_ID):
    raise RuntimeError("POSWAI_SERVICE_PROMPTPAY_ID must be a 10, 13 or 15 digit PromptPay target")
if ADMIN_KEY and len(ADMIN_KEY) < 24:
    raise RuntimeError("POSWAI_ADMIN_KEY must be at least 24 characters")
# A cashier may cancel small unpaid orders alone; anything above these limits,
# and every refund of money already taken, needs a manager or the owner.
VOID_CASHIER_MAX_AMOUNT = float(os.getenv("POSWAI_VOID_CASHIER_MAX_AMOUNT", "200"))
VOID_CASHIER_DAILY_LIMIT = int(os.getenv("POSWAI_VOID_CASHIER_DAILY_LIMIT", "3"))
if not math.isfinite(VOID_CASHIER_MAX_AMOUNT) or VOID_CASHIER_MAX_AMOUNT < 0 or VOID_CASHIER_DAILY_LIMIT < 0:
    raise RuntimeError("Invalid cashier void limits")
STAFF_ROLES = ("manager", "cashier", "kitchen", "service", "staff")
LEAVE_TYPES = ("sick", "personal", "vacation")
DEFAULT_LEAVE_QUOTA = {"sick": 30, "personal": 3, "vacation": 6}
TAB_LABELS = {"customer": "สั่งอาหาร", "kitchen": "จอครัว", "cashier": "แคชเชียร์",
              "inventory": "สต็อก", "crm": "สมาชิก", "staff": "พนักงาน", "analytics": "รายงาน"}
ALL_TABS = tuple(TAB_LABELS)
# One matrix for the whole app: the API enforces it per endpoint and the PWA hides
# what a role may not open. Server rules stay authoritative; hiding a tab is cosmetic.
ROLE_PERMISSIONS = {
    "owner": {"label": "เจ้าของร้าน", "tabs": list(ALL_TABS),
              "allowed": ["จัดการทุกส่วนของร้าน", "ตั้งค่าบัญชีรับเงินและค่าแรง",
                          "แต่งตั้งผู้จัดการและกำหนดสิทธิ์", "ดูรายงานและเงินเดือนทั้งทีม"],
              "restricted": []},
    "manager": {"label": "ผู้จัดการร้าน", "tabs": list(ALL_TABS),
                "allowed": ["อนุมัติหรือปฏิเสธใบลา", "จัดตารางกะและระงับสิทธิ์ POS",
                            "ยกเลิกบิลทุกยอด และคืนเงินบิลที่ชำระแล้ว",
                            "ตั้งเมนูของหมดและออกใบสั่งซื้อ", "ดูรายงานและเงินเดือนทั้งทีม"],
                "restricted": ["แต่งตั้งผู้จัดการ", "แก้ไขหรือลบบัญชีเจ้าของร้าน"]},
    "cashier": {"label": "แคชเชียร์", "tabs": ["customer", "cashier", "crm", "staff"],
                "allowed": ["เปิด-ปิดกะและลิ้นชักเงินสด", "รับชำระเงิน แยกบิล ย้ายโต๊ะ",
                            "พิมพ์ใบเสร็จและใบกำกับภาษี",
                            f"ยกเลิกบิลที่ยังไม่รับเงิน ไม่เกิน {VOID_CASHIER_MAX_AMOUNT:,.0f} บาท "
                            f"และไม่เกิน {VOID_CASHIER_DAILY_LIMIT} ครั้งต่อวัน (ต้องใส่เหตุผล)",
                            "ลงเวลาและยื่นใบลาของตัวเอง"],
                "restricted": ["คืนเงินบิลที่ชำระแล้ว", "ยกเลิกบิลใหญ่หรือเกินโควตาต่อวัน",
                               "สต็อกและรายงาน", "ค่าแรงหรือเงินเดือนของคนอื่น",
                               "จัดการบัญชีพนักงาน"]},
    "kitchen": {"label": "ครัว / บาร์", "tabs": ["kitchen", "inventory", "staff"],
                "allowed": ["รับคิวและกดพร้อมเสิร์ฟ", "บันทึกของเสียและเบิกของ",
                            "ลงเวลาและยื่นใบลาของตัวเอง"],
                "restricted": ["แคชเชียร์และยอดเงิน", "สมาชิกและรายงาน",
                               "ค่าแรงหรือเงินเดือนของคนอื่น"]},
    "service": {"label": "พนักงานเสิร์ฟ", "tabs": ["customer", "staff"],
                "allowed": ["สั่งอาหารให้ลูกค้าและดูสถานะโต๊ะ", "ลงเวลาและยื่นใบลาของตัวเอง"],
                "restricted": ["คิดเงินและลิ้นชักเงินสด", "สต็อก สมาชิก และรายงาน",
                               "ค่าแรงหรือเงินเดือนของคนอื่น"]},
    "staff": {"label": "พนักงานทั่วไป", "tabs": ["customer", "staff"],
              "allowed": ["สั่งอาหารให้ลูกค้าและดูสถานะโต๊ะ", "ลงเวลาและยื่นใบลาของตัวเอง"],
              "restricted": ["คิดเงินและลิ้นชักเงินสด", "สต็อก สมาชิก และรายงาน",
                             "ค่าแรงหรือเงินเดือนของคนอื่น"]},
    "guest": {"label": "ยังไม่เข้าสู่ระบบ", "tabs": ["customer", "staff"],
              "allowed": ["ดูเมนูและสั่งอาหารผ่าน QR ของโต๊ะ"],
              "restricted": ["ข้อมูลพนักงานและยอดขายทั้งหมด"]},
}
BANGKOK_TZ = datetime.timezone(datetime.timedelta(hours=7))
# SQLite stores CURRENT_TIMESTAMP in UTC; this shifts such a column to shop time
# so "today" in a query means the same day the staff are working.
BANGKOK_SQL_OFFSET = f"{BANGKOK_TZ.utcoffset(None) // datetime.timedelta(hours=1):+d} hours"
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
# The shop a request belongs to. Background jobs and LINE/Songwai webhooks carry
# no shop cookie, so they keep working on the original shop ("main").
CURRENT_SHOP: ContextVar[str] = ContextVar("poswai_shop", default=MAIN_SHOP)
_prepared_databases: set[Path] = set()
_prepare_lock = threading.Lock()


def current_db_path() -> Path:
    """The open shop's database; other shops' files are created on first use.

    The original shop is prepared once at start-up (init_db below), as before.
    """
    if CURRENT_SHOP.get() == MAIN_SHOP:
        return DB_PATH
    path = shops.shop_db_path(DB_PATH, CURRENT_SHOP.get())
    if path not in _prepared_databases:
        with _prepare_lock:
            if path not in _prepared_databases:
                path.parent.mkdir(parents=True, exist_ok=True)
                _prepared_databases.add(path)
                try:
                    init_db()
                except Exception:
                    _prepared_databases.discard(path)
                    raise
    return path


def is_preview() -> bool:
    return PREVIEW_ONLY or CURRENT_SHOP.get() == DEMO_SHOP


def connect_db(timeout: float = 10.0) -> sqlite3.Connection:
    """Every connection shares the same concurrency settings.

    WAL lets the kitchen display keep reading while the cashier writes, and the
    busy timeout makes a locked database wait instead of failing a sale.
    """
    conn = sqlite3.connect(current_db_path(), timeout=timeout)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


# =====================================================================
def init_db() -> None:
    conn = sqlite3.connect(shops.shop_db_path(DB_PATH, CURRENT_SHOP.get()), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
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

    # "line:U1234", "google:5678": the account a member of staff signs in with
    # instead of typing their PIN on a busy counter.
    if "social_id" not in {row[1] for row in cur.execute("PRAGMA table_info(staffs)")}:
        cur.execute("ALTER TABLE staffs ADD COLUMN social_id TEXT")
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS staff_social_identity ON staffs(social_id)"
                " WHERE social_id IS NOT NULL")
    cur.execute("""CREATE TABLE IF NOT EXISTS inventory (
        branch_id INTEGER NOT NULL, ingredient_id TEXT NOT NULL, stock REAL NOT NULL DEFAULT 0,
        PRIMARY KEY (branch_id, ingredient_id))""")
    # A recipe says "120"; the unit says whether that is grams or bottles.
    inventory_columns = {row[1] for row in cur.execute("PRAGMA table_info(inventory)")}
    if "unit" not in inventory_columns:
        cur.execute("ALTER TABLE inventory ADD COLUMN unit TEXT NOT NULL DEFAULT 'หน่วย'")
    if "reorder_point" not in inventory_columns:
        cur.execute("ALTER TABLE inventory ADD COLUMN reorder_point REAL NOT NULL DEFAULT 0")
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
    init_notifications(conn)
    cur.execute("""CREATE TABLE IF NOT EXISTS service_calls (
        event_id TEXT PRIMARY KEY, branch_id INTEGER NOT NULL, table_no TEXT NOT NULL,
        call_type TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, acknowledged_at TEXT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS auth_sessions (
        token_hash TEXT PRIMARY KEY, staff_id INTEGER NOT NULL REFERENCES staffs(id),
        expires_at INTEGER NOT NULL)""")
    cur.execute("CREATE INDEX IF NOT EXISTS auth_sessions_expiry ON auth_sessions(expires_at)")
    init_catalog(conn)
    init_tables(conn)
    init_printing(conn)
    init_dossier(conn)
    init_inventory_movements(conn)
    init_commerce(conn)
    cur.execute("""CREATE TABLE IF NOT EXISTS auth_login_attempts (
        staff_id INTEGER PRIMARY KEY, failures INTEGER NOT NULL, first_failed_at INTEGER NOT NULL)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS order_cancellations (
        event_id TEXT PRIMARY KEY,
        order_no TEXT NOT NULL UNIQUE REFERENCES order_events(order_no),
        branch_id INTEGER NOT NULL,
        kind TEXT NOT NULL CHECK(kind IN ('void','refund')),
        amount REAL NOT NULL,
        reason TEXT NOT NULL,
        staff_id INTEGER NOT NULL REFERENCES staffs(id),
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
    cur.execute("CREATE INDEX IF NOT EXISTS order_cancellations_by_staff "
                "ON order_cancellations(staff_id,created_at)")
    cur.execute("""CREATE TABLE IF NOT EXISTS staff_leave_quotas (
        staff_id INTEGER PRIMARY KEY REFERENCES staffs(id),
        sick INTEGER NOT NULL DEFAULT 30,
        personal INTEGER NOT NULL DEFAULT 3,
        vacation INTEGER NOT NULL DEFAULT 6)""")
    # Loyalty points: the balance lives on the customer, every change in the ledger.
    if "points" not in {row[1] for row in cur.execute("PRAGMA table_info(crm_customers)")}:
        cur.execute("ALTER TABLE crm_customers ADD COLUMN points INTEGER NOT NULL DEFAULT 0")
    cur.execute("""CREATE TABLE IF NOT EXISTS crm_point_ledger (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER NOT NULL REFERENCES crm_customers(id),
        change INTEGER NOT NULL,
        reason TEXT NOT NULL,
        staff_id INTEGER,
        order_no TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
    if (CURRENT_SHOP.get() == MAIN_SHOP and BOOTSTRAP_MANAGER_PIN
            and not cur.execute("SELECT 1 FROM staffs LIMIT 1").fetchone()):
        if len(BOOTSTRAP_MANAGER_PIN) < 8:
            raise RuntimeError("POSWAI_BOOTSTRAP_MANAGER_PIN must contain at least 8 characters")
        cur.execute("INSERT OR IGNORE INTO branches (id, name) VALUES (1, 'Main branch')")
        cur.execute("INSERT INTO staffs (branch_id, name, role, pin_code_hash) VALUES (1, ?, 'owner', ?)",
                    (os.getenv("POSWAI_BOOTSTRAP_MANAGER_NAME", "Manager"), hash_pin(BOOTSTRAP_MANAGER_PIN)))

    # Everyone on the payroll has a leave allowance; accounts made before this
    # table existed start on the documented default instead of showing "not set".
    cur.execute("INSERT OR IGNORE INTO staff_leave_quotas (staff_id,sick,personal,vacation) "
                "SELECT id,?,?,? FROM staffs",
                (DEFAULT_LEAVE_QUOTA["sick"], DEFAULT_LEAVE_QUOTA["personal"], DEFAULT_LEAVE_QUOTA["vacation"]))

    conn.commit()
    conn.close()


def hash_pin(pin: str) -> str:
    if len(pin) < 8 or len(pin) > 128:
        raise HTTPException(400, "PIN ต้องยาว 8 ถึง 128 ตัวอักษร")
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


def store_leave_quota(conn: sqlite3.Connection, staff_id: int, quota: dict | None) -> None:
    """Every staff account carries a yearly leave allowance, defaulted on creation."""
    merged = dict(DEFAULT_LEAVE_QUOTA)
    for leave_type, days in (quota or {}).items():
        if days is None:
            continue
        if leave_type not in LEAVE_TYPES or not isinstance(days, int) or not 0 <= days <= 365:
            raise HTTPException(400, "Leave quota must be 0 to 365 days per leave type")
        merged[leave_type] = days
    conn.execute("INSERT INTO staff_leave_quotas (staff_id,sick,personal,vacation) VALUES (?,?,?,?) "
                 "ON CONFLICT(staff_id) DO UPDATE SET sick=excluded.sick,"
                 "personal=excluded.personal,vacation=excluded.vacation",
                 (staff_id, merged["sick"], merged["personal"], merged["vacation"]))


def leave_quota_map(conn: sqlite3.Connection, branch_id: int) -> dict:
    """Remaining leave days this calendar year, after approved leave is deducted."""
    year = str(datetime.datetime.now(BANGKOK_TZ).year)
    totals = {row[0]: {"sick": row[1], "personal": row[2], "vacation": row[3]}
              for row in conn.execute("SELECT q.staff_id,q.sick,q.personal,q.vacation "
                                      "FROM staff_leave_quotas q JOIN staffs s ON s.id=q.staff_id "
                                      "WHERE s.branch_id=?", (branch_id,))}
    used: dict[int, dict[str, int]] = {}
    for staff_id, leave_type, start_date, end_date in conn.execute(
            "SELECT l.staff_id,l.leave_type,l.start_date,l.end_date FROM leave_requests l "
            "JOIN staffs s ON s.id=l.staff_id WHERE s.branch_id=? AND l.status='approved' "
            "AND substr(l.start_date,1,4)=?", (branch_id, year)):
        if leave_type not in LEAVE_TYPES:
            continue
        try:
            days = (datetime.date.fromisoformat(end_date) - datetime.date.fromisoformat(start_date)).days + 1
        except ValueError:
            continue
        spent = used.setdefault(staff_id, {})
        spent[leave_type] = spent.get(leave_type, 0) + max(days, 0)
    quotas = {}
    for staff_id, total in totals.items():
        spent = used.get(staff_id, {})
        quotas[staff_id] = {leave_type: {"total": total[leave_type], "used": spent.get(leave_type, 0),
                                         "left": max(total[leave_type] - spent.get(leave_type, 0), 0)}
                            for leave_type in LEAVE_TYPES}
    return quotas


init_db()


@app.get("/api/permissions")
def role_permission_matrix():
    """The role matrix the staff workspace shows and the PWA uses to hide tabs."""
    return {"tab_labels": TAB_LABELS, "roles": ROLE_PERMISSIONS}


def _known_shop(slug: str) -> bool:
    return slug in (MAIN_SHOP, DEMO_SHOP) or (
        shops.get_shop(DB_PATH, slug) or {}).get("status") == "active"


def current_billing() -> dict:
    """The open shop's service-fee state. "main" and "demo" are never billed."""
    return billing.billing_state(DB_PATH, CURRENT_SHOP.get(), price=MONTHLY_PRICE)


def require_paid_subscription() -> None:
    """New orders stop when the service fee is overdue; reading never does.

    Reports, sales history, stock and the staff pages stay open, and no shop data
    is ever removed — the shop only has to pay before it can ring up another sale.
    """
    state = current_billing()
    if state["blocked"]:
        raise HTTPException(402, state["message"])


def require_admin_key(request: Request) -> None:
    """The ZZAX Studio billing page, guarded by a shared key instead of a staff PIN."""
    if not ADMIN_KEY:
        raise HTTPException(503, "ยังไม่ได้ตั้งค่ากุญแจผู้ดูแลระบบ (POSWAI_ADMIN_KEY)")
    supplied = request.headers.get("x-poswai-admin-key", "")
    if not secrets.compare_digest(supplied, ADMIN_KEY):
        raise HTTPException(401, "กุญแจผู้ดูแลระบบไม่ถูกต้อง")


OUT_OF_SERVICE = {
    "suspended": "ถูกระงับการใช้งานชั่วคราว ข้อมูลของร้านยังอยู่ครบ",
    "closed": "ปิดการใช้งานถาวรแล้ว ข้อมูลของร้านยังถูกเก็บไว้ทั้งหมด",
}


def _out_of_service_text(shop: dict) -> str:
    """Say which shop it is, why it stopped and who to call — never a silent redirect."""
    lines = [f"“{shop['name']}” {OUT_OF_SERVICE.get(shop['status'], 'ใช้งานไม่ได้ในขณะนี้')}"]
    if shop.get("status_reason"):
        lines.append(f"เหตุผล: {shop['status_reason']}")
    lines.append(f"หากต้องการเปิดใช้งานอีกครั้ง กรุณาติดต่อ ZZAX Studio{SUPPORT_CONTACT}")
    return " · ".join(lines)


def _out_of_service_page(shop: dict) -> HTMLResponse:
    body = html.escape(_out_of_service_text(shop)).replace(" · ", "<br>")
    return HTMLResponse(
        "<!doctype html><html lang=\"th\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<title>ร้านนี้ใช้งานไม่ได้ · POS WAI</title>"
        "<link rel=\"stylesheet\" href=\"/assets/fonts.css\"><style>"
        "body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;"
        "padding:24px;background:#f3f5f8;color:#17222e;font-family:'Noto Sans Thai','Prompt',system-ui,sans-serif}"
        "div{max-width:460px;background:#fff;border:1px solid #dfe5ec;border-radius:16px;padding:24px;"
        "text-align:center;line-height:1.7}h1{margin:0 0 10px;font-size:1.25rem}"
        "a{color:#1f6feb}</style></head><body><div><h1>ร้านนี้ใช้งานไม่ได้ในขณะนี้</h1>"
        f"<p>{body}</p><p><a href=\"/\">กลับไปหน้าแรกของ POS WAI</a></p></div></body></html>",
        status_code=403)


def _secure(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").split(",")[0] == "https"


def _remember_shop(request: Request, response: Response, slug: str) -> None:
    # The demo is never remembered: leaving its page returns a visitor to the real service.
    response.set_cookie("poswai_shop", slug, max_age=None if slug == DEMO_SHOP else 365 * 24 * 3600,
                        httponly=True, secure=_secure(request), samesite="lax", path="/")


@app.middleware("http")
async def protect_preview(request: Request, call_next):
    requested = request.query_params.get("shop")
    cookie_shop = request.cookies.get("poswai_shop", "")
    document = request.method == "GET" and request.url.path in ("/", "/index.html")
    if requested is not None:
        slug = requested.strip().lower() or MAIN_SHOP
    elif document and cookie_shop == DEMO_SHOP:
        slug = MAIN_SHOP
    else:
        slug = cookie_shop or MAIN_SHOP
    admin_path = request.url.path.startswith("/api/admin/")
    record = None if slug in (MAIN_SHOP, DEMO_SHOP) else shops.get_shop(DB_PATH, slug)
    if record and record["status"] != "active" and not admin_path:
        # Suspended or closed: say so. Quietly falling back to another shop used to
        # look like the shop's own data had vanished.
        if document:
            return _out_of_service_page(record)
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": _out_of_service_text(record)}, status_code=403)
    elif not record and slug not in (MAIN_SHOP, DEMO_SHOP):
        if requested is not None and request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "ไม่พบร้านนี้"}, status_code=404)
        slug = MAIN_SHOP
    CURRENT_SHOP.set(slug)
    if is_preview() and request.url.path.startswith("/api/") and request.method not in ("GET", "HEAD"):
        staff_path = request.url.path
        # Signing in and opening a new shop work from the demo page too.
        # The ZZAX Studio billing page works on the registry rather than on a shop's
        # records, so it keeps working while a shop is in preview; paying the service
        # fee has to keep working for the same reason.
        allowed_staff_write = staff_path.startswith("/api/admin/") or (
            slug == DEMO_SHOP and staff_path in ("/api/auth/login", "/api/shops")) or STAFF_LIVE and slug != DEMO_SHOP and (
            staff_path.startswith("/api/billing/") or
            staff_path.startswith("/api/auth/") or staff_path.startswith("/api/owner/") or
            staff_path == "/api/staff" or
            staff_path.startswith("/api/staff/") or staff_path == "/api/attendance" or
            staff_path.startswith("/api/line-liff/") or staff_path.startswith("/api/line-webhook") or
            staff_path.startswith("/api/line/notifications/"))
        if not allowed_staff_write:
            return JSONResponse({"detail": "ร้านตัวอย่าง: บันทึกข้อมูลจริงไม่ได้"}, status_code=403)
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.cookies.get("poswai_session"):
        origin = request.headers.get("origin")
        if origin:
            from urllib.parse import urlsplit
            source = urlsplit(origin)
            forwarded_host = request.headers.get("x-forwarded-host", request.headers.get("host", ""))
            if source.netloc != forwarded_host or source.scheme not in ("https", "http"):
                return JSONResponse({"detail": "คำขอมาจากแหล่งที่ไม่ถูกต้อง"}, status_code=403)
    response = await call_next(request)
    if document and (requested is not None or cookie_shop != slug) and slug != cookie_shop:
        if slug == MAIN_SHOP and requested is None:
            response.delete_cookie("poswai_shop", path="/")
        else:
            _remember_shop(request, response, slug)
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


def require_staff(request: Request, roles: tuple[str, ...] = (), branch_id: int | None = None) -> dict:
    token = request.cookies.get("poswai_session", "")
    if len(token) != 64 or not re.fullmatch(r"[0-9a-f]{64}", token):
        raise HTTPException(401, "กรุณาเข้าสู่ระบบพนักงานก่อน")
    with closing(connect_db()) as conn, conn:
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
                                (row["id"], datetime.datetime.now(BANGKOK_TZ).date().isoformat())).fetchone():
            conn.execute("DELETE FROM auth_sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))
            row = None
    if not row or not row["is_active"]:
        raise HTTPException(401, "กรุณาเข้าสู่ระบบพนักงานก่อน")
    staff = dict(row)
    if roles and staff["role"] not in roles:
        raise HTTPException(403, "สิทธิ์ของคุณใช้ส่วนนี้ไม่ได้")
    if branch_id is not None and staff["branch_id"] != branch_id:
        raise HTTPException(403, "คุณไม่ได้อยู่สาขานี้")
    return staff


class LoginRequest(BaseModel):
    staff_id: int
    pin: str
    shop: Optional[str] = None


def _open_session(request: Request, response: Response, conn: sqlite3.Connection, staff_id: int,
                  samesite: str = "strict") -> int:
    token = secrets.token_hex(32)
    expires = int(time.time()) + SESSION_LIFETIME
    conn.execute("DELETE FROM auth_sessions WHERE staff_id=? OR expires_at<=?", (staff_id, int(time.time())))
    conn.execute("INSERT INTO auth_sessions (token_hash,staff_id,expires_at) VALUES (?,?,?)",
                 (hashlib.sha256(token.encode()).hexdigest(), staff_id, expires))
    response.set_cookie("poswai_session", token, max_age=SESSION_LIFETIME, httponly=True,
                        secure=_secure(request), samesite=samesite, path="/")
    return expires


@app.post("/api/auth/login")
def staff_login(req: LoginRequest, request: Request, response: Response):
    if req.shop is not None:
        slug = req.shop.strip().lower() or MAIN_SHOP
        stopped = shops.get_shop(DB_PATH, slug) if slug not in (MAIN_SHOP, DEMO_SHOP) else None
        if stopped and stopped["status"] != "active":
            # The shop code is right; it is the shop that is out of service.
            raise HTTPException(403, _out_of_service_text(stopped))
        if slug == DEMO_SHOP or not _known_shop(slug):
            hash_pin("invalid-credentials")
            raise HTTPException(401, "ชื่อร้าน รหัสพนักงาน หรือ PIN ไม่ถูกต้อง")
        CURRENT_SHOP.set(slug)
    if CURRENT_SHOP.get() == DEMO_SHOP:
        raise HTTPException(401, "ร้านตัวอย่างไม่มีบัญชีพนักงาน")
    if req.staff_id < 1 or len(req.pin) > 128:
        raise HTTPException(401, "ชื่อร้าน รหัสพนักงาน หรือ PIN ไม่ถูกต้อง")
    with closing(connect_db()) as conn, conn:
        conn.row_factory = sqlite3.Row
        now = int(time.time())
        attempt = conn.execute("SELECT failures,first_failed_at FROM auth_login_attempts WHERE staff_id=?",
                               (req.staff_id,)).fetchone()
        if attempt and attempt["failures"] >= 5 and now - attempt["first_failed_at"] < 900:
            raise HTTPException(429, "ใส่ PIN ผิดหลายครั้ง กรุณารอ 15 นาทีแล้วลองใหม่")
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
            raise HTTPException(401, "ชื่อร้าน รหัสพนักงาน หรือ PIN ไม่ถูกต้อง")
        today = datetime.datetime.now(BANGKOK_TZ).date().isoformat()
        locked = conn.execute("SELECT 1 FROM staff_shifts WHERE staff_id=? AND work_date=? AND pos_pin_locked=1",
                              (row["id"], today)).fetchone()
        if locked:
            raise HTTPException(403, "บัญชีนี้ถูกระงับสิทธิ์สำหรับกะวันนี้")
        conn.execute("DELETE FROM auth_login_attempts WHERE staff_id=?", (row["id"],))
        expires = _open_session(request, response, conn, row["id"])
    _remember_shop(request, response, CURRENT_SHOP.get())
    return {"staff_id": row["id"], "branch_id": row["branch_id"], "name": row["name"],
            "role": row["role"], "expires_at": expires, "shop": CURRENT_SHOP.get()}


@app.get("/api/auth/session")
def staff_session(request: Request):
    staff = require_staff(request)
    return {"staff_id": staff["id"], "branch_id": staff["branch_id"], "name": staff["name"],
            "role": staff["role"], "expires_at": staff["expires_at"]}


@app.post("/api/auth/logout")
def staff_logout(request: Request, response: Response):
    token = request.cookies.get("poswai_session", "")
    if token:
        with closing(connect_db()) as conn, conn:
            conn.execute("DELETE FROM auth_sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))
    response.delete_cookie("poswai_session", path="/")
    return {"status": "logged_out"}


class LeaveQuotaInput(BaseModel):
    sick: Optional[int] = None
    personal: Optional[int] = None
    vacation: Optional[int] = None


class StaffCreate(BaseModel):
    name: str
    role: str
    pin: str
    line_user_id: Optional[str] = None
    hourly_rate: Optional[float] = None
    leave_quota: Optional[LeaveQuotaInput] = None


@app.post("/api/staff")
def create_staff(req: StaffCreate, request: Request):
    manager = require_staff(request, roles=("manager", "owner"))
    if not req.name.strip() or len(req.name) > 100 or req.role not in STAFF_ROLES:
        raise HTTPException(400, "ข้อมูลพนักงานไม่ถูกต้อง")
    if req.role == "manager" and manager["role"] != "owner":
        raise HTTPException(403, "เฉพาะเจ้าของร้านเท่านั้นที่ตั้งผู้จัดการได้")
    if req.line_user_id is not None and (not req.line_user_id or len(req.line_user_id) > 100):
        raise HTTPException(400, "LINE ID ไม่ถูกต้อง")
    if req.hourly_rate is not None and (not math.isfinite(req.hourly_rate) or not 0 <= req.hourly_rate <= 100000):
        raise HTTPException(400, "ค่าแรงต่อชั่วโมงไม่ถูกต้อง")
    pin_hash = hash_pin(req.pin)
    with closing(connect_db()) as conn, conn:
        try:
            if req.hourly_rate is None:
                cur = conn.execute("INSERT INTO staffs (branch_id,line_user_id,name,role,pin_code_hash) VALUES (?,?,?,?,?)",
                                   (manager["branch_id"], req.line_user_id, req.name.strip(), req.role, pin_hash))
            else:
                cur = conn.execute("INSERT INTO staffs (branch_id,line_user_id,name,role,pin_code_hash,hourly_rate) "
                                   "VALUES (?,?,?,?,?,?)",
                                   (manager["branch_id"], req.line_user_id, req.name.strip(), req.role, pin_hash,
                                    req.hourly_rate))
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, "LINE นี้ผูกกับพนักงานคนอื่นแล้ว") from exc
        store_leave_quota(conn, cur.lastrowid, req.leave_quota.model_dump() if req.leave_quota else None)
    return {"staff_id": cur.lastrowid, "branch_id": manager["branch_id"], "name": req.name.strip(),
            "role": req.role, "hourly_rate": req.hourly_rate}


def _can_manage_staff(actor: dict, target: sqlite3.Row) -> bool:
    if actor["branch_id"] != target["branch_id"]:
        return False
    if actor["role"] == "owner":
        return True
    return actor["role"] == "manager" and target["role"] not in ("owner", "manager")


@app.get("/api/staff/directory")
def staff_directory(request: Request, branch_id: int = 1):
    require_staff(request, roles=("manager", "owner"), branch_id=branch_id)
    with closing(connect_db()) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT id,name,role,is_active,hourly_rate FROM staffs WHERE branch_id=? ORDER BY is_active DESC,id",
                            (branch_id,)).fetchall()
        quotas = leave_quota_map(conn, branch_id)
    return {"items": [{"id": row["id"], "name": row["name"], "role": row["role"],
                       "is_active": bool(row["is_active"]), "hourly_rate": row["hourly_rate"],
                       "leave_quota": quotas.get(row["id"])} for row in rows],
            "default_leave_quota": DEFAULT_LEAVE_QUOTA}


class StaffProfileUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    hourly_rate: Optional[float] = None
    leave_quota: Optional[LeaveQuotaInput] = None


@app.patch("/api/staff/{staff_id}/profile")
def update_staff_profile(staff_id: int, req: StaffProfileUpdate, request: Request):
    actor = require_staff(request, roles=("manager", "owner"))
    updates = req.model_dump(exclude_none=True)
    quota = updates.pop("leave_quota", None)
    if not updates and quota is None:
        raise HTTPException(400, "ไม่มีข้อมูลที่ต้องแก้")
    if "name" in updates and (not updates["name"].strip() or len(updates["name"]) > 100):
        raise HTTPException(400, "ชื่อพนักงานไม่ถูกต้อง")
    if "role" in updates and updates["role"] not in STAFF_ROLES:
        raise HTTPException(400, "สิทธิ์ที่เลือกไม่ถูกต้อง")
    if "hourly_rate" in updates and (not math.isfinite(updates["hourly_rate"]) or not 0 <= updates["hourly_rate"] <= 100000):
        raise HTTPException(400, "ค่าแรงต่อชั่วโมงไม่ถูกต้อง")
    with closing(connect_db()) as conn, conn:
        conn.row_factory = sqlite3.Row
        target = conn.execute("SELECT id,branch_id,name,role,is_active FROM staffs WHERE id=?", (staff_id,)).fetchone()
        if not target or target["branch_id"] != actor["branch_id"]:
            raise HTTPException(404, "ไม่พบพนักงานคนนี้")
        if not _can_manage_staff(actor, target):
            raise HTTPException(403, "คุณจัดการบัญชีนี้ไม่ได้")
        if target["role"] == "owner" and ("role" in updates or "is_active" in updates):
            raise HTTPException(403, "บัญชีเจ้าของร้านลดสิทธิ์หรือปิดไม่ได้")
        if staff_id == actor["id"] and ("role" in updates or updates.get("is_active") is False):
            raise HTTPException(403, "เปลี่ยนสิทธิ์ของตัวเองไม่ได้")
        if updates.get("role") == "manager" and actor["role"] != "owner":
            raise HTTPException(403, "เฉพาะเจ้าของร้านเท่านั้นที่ตั้งผู้จัดการได้")
        if "name" in updates:
            updates["name"] = updates["name"].strip()
        if updates:
            sets = ",".join(f"{field}=?" for field in updates)
            conn.execute(f"UPDATE staffs SET {sets} WHERE id=?", (*updates.values(), staff_id))
        if quota is not None:
            store_leave_quota(conn, staff_id, quota)
        if updates.get("is_active") is False or "role" in updates:
            conn.execute("DELETE FROM auth_sessions WHERE staff_id=?", (staff_id,))
    return {"staff_id": staff_id, "status": "updated"}


class StaffPosAccess(BaseModel):
    locked: bool


@app.patch("/api/staff/{staff_id}/pos-access")
def set_staff_pos_access(staff_id: int, req: StaffPosAccess, request: Request):
    """Suspend or restore one person's POS sign-in for today, from the roster row."""
    actor = require_staff(request, roles=("manager", "owner"))
    today = datetime.datetime.now(BANGKOK_TZ).date().isoformat()
    with closing(connect_db()) as conn, conn:
        conn.row_factory = sqlite3.Row
        target = conn.execute("SELECT id,branch_id,role FROM staffs WHERE id=? AND is_active=1", (staff_id,)).fetchone()
        if not target or target["branch_id"] != actor["branch_id"]:
            raise HTTPException(404, "ไม่พบพนักงานคนนี้")
        if not _can_manage_staff(actor, target) or target["role"] == "owner":
            raise HTTPException(403, "คุณเปลี่ยนสิทธิ์ POS ของบัญชีนี้ไม่ได้")
        if staff_id == actor["id"]:
            raise HTTPException(403, "ระงับสิทธิ์ของตัวเองไม่ได้")
        current = conn.execute("SELECT status FROM staff_shifts WHERE staff_id=? AND work_date=?",
                               (staff_id, today)).fetchone()
        if current and current["status"] == "on_leave":
            raise HTTPException(409, "วันนี้ลาอนุมัติแล้ว ระบบคุมสิทธิ์ให้เอง")
        # A manager suspending access is recorded as its own state, never as absence.
        status = "suspended" if req.locked else (
            "scheduled" if current and current["status"] in ("suspended", "absent")
            else (current["status"] if current else "scheduled"))
        conn.execute("INSERT INTO staff_shifts (staff_id,branch_id,work_date,status,pos_pin_locked) "
                     "VALUES (?,?,?,?,?) ON CONFLICT(staff_id,work_date) DO UPDATE "
                     "SET status=excluded.status,pos_pin_locked=excluded.pos_pin_locked",
                     (staff_id, actor["branch_id"], today, status, 1 if req.locked else 0))
        if req.locked:
            conn.execute("DELETE FROM auth_sessions WHERE staff_id=?", (staff_id,))
    return {"staff_id": staff_id, "pos_pin_locked": req.locked, "work_date": today}


class StaffPinReset(BaseModel):
    pin: str


@app.put("/api/staff/{staff_id}/pin")
def reset_staff_pin(staff_id: int, req: StaffPinReset, request: Request):
    actor = require_staff(request, roles=("manager", "owner"))
    pin_hash = hash_pin(req.pin)
    with closing(connect_db()) as conn, conn:
        conn.row_factory = sqlite3.Row
        target = conn.execute("SELECT id,branch_id,role FROM staffs WHERE id=?", (staff_id,)).fetchone()
        if not target or target["branch_id"] != actor["branch_id"]:
            raise HTTPException(404, "ไม่พบพนักงานคนนี้")
        if not _can_manage_staff(actor, target) or target["role"] == "owner":
            raise HTTPException(403, "คุณตั้ง PIN ใหม่ให้บัญชีนี้ไม่ได้")
        conn.execute("UPDATE staffs SET pin_code_hash=? WHERE id=?", (pin_hash, staff_id))
        conn.execute("DELETE FROM auth_sessions WHERE staff_id=?", (staff_id,))
    return {"staff_id": staff_id, "status": "pin_reset"}


class TableTokenRequest(BaseModel):
    branch_id: int
    table_no: str


def _table_signature(payload: bytes) -> str:
    return hmac.new(TABLE_QR_SECRET.encode(), payload, hashlib.sha256).hexdigest()


# A scanned sticker is good for one sitting, not for a month. Long enough that
# a slow meal never logs the guest out, short enough that a screenshotted link
# passed around afterwards is worthless.
TABLE_SCAN_TTL_SECONDS = 12 * 3600


def _mint_table_token(branch_id: int, table_no: str, ttl_seconds: int) -> str:
    expires = int(time.time()) + ttl_seconds
    payload = json.dumps({"b": branch_id, "t": table_no, "e": expires, "s": CURRENT_SHOP.get()},
                         sort_keys=True, separators=(",", ":")).encode()
    encoded = base64.urlsafe_b64encode(payload).rstrip(b"=").decode()
    return encoded + "." + _table_signature(payload)


@app.post("/api/tables/token")
def issue_table_token(req: TableTokenRequest, request: Request):
    """A one-off token for staff, for a table with no sticker yet."""
    require_staff(request, roles=("manager", "owner"), branch_id=req.branch_id)
    if len(TABLE_QR_SECRET) < 32:
        raise HTTPException(503, "ยังไม่ได้ตั้งค่ากุญแจ QR โต๊ะ")
    if req.branch_id < 1 or not re.fullmatch(r"[\w\- ]{1,24}", req.table_no, re.UNICODE):
        raise HTTPException(400, "โต๊ะไม่ถูกต้อง")
    with closing(connect_db()) as conn, conn:
        if not conn.execute("SELECT 1 FROM branches WHERE id=?", (req.branch_id,)).fetchone():
            raise HTTPException(404, "ไม่พบสาขานี้")
    token = _mint_table_token(req.branch_id, req.table_no, TABLE_SCAN_TTL_SECONDS)
    return {"token": token, "expires_at": int(time.time()) + TABLE_SCAN_TTL_SECONDS,
            "url": "/?" + urlencode({"shop": CURRENT_SHOP.get(), "table_token": token})}


class TableCreate(BaseModel):
    branch_id: int = 1
    table_no: str
    seats: int = 0
    note: str = ""


class TableActive(BaseModel):
    branch_id: int = 1
    active: bool


def _table_link(code: str) -> str:
    """What gets printed. Relative, so a shop on another domain still works."""
    return "/t/" + code + "?" + urlencode({"shop": CURRENT_SHOP.get()})


def _with_links(table: dict) -> dict:
    return {**table, "link": _table_link(table["code"])}


@app.get("/api/tables")
def get_tables(request: Request, branch_id: int = 1):
    require_staff(request, roles=("manager", "owner"), branch_id=branch_id)
    try:
        with closing(connect_db()) as conn:
            return {"branch_id": branch_id, "shop": CURRENT_SHOP.get(),
                    "tables": [_with_links(table) for table in list_tables(conn, branch_id)]}
    except TableError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


@app.post("/api/tables")
def post_table(req: TableCreate, request: Request):
    require_staff(request, roles=("manager", "owner"), branch_id=req.branch_id)
    try:
        with closing(connect_db()) as conn, conn:
            return _with_links(add_table(conn, req.branch_id, req.table_no, req.seats, req.note))
    except TableError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


@app.patch("/api/tables/{table_no}")
def patch_table(table_no: str, req: TableActive, request: Request):
    """Revoke the sticker on one table, or put it back in service."""
    require_staff(request, roles=("manager", "owner"), branch_id=req.branch_id)
    try:
        with closing(connect_db()) as conn, conn:
            return set_active(conn, req.branch_id, table_no, req.active)
    except TableError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


@app.post("/api/tables/{table_no}/reissue")
def post_table_reissue(table_no: str, request: Request, branch_id: int = 1):
    """New code for one table. Every sticker printed for it stops working."""
    require_staff(request, roles=("manager", "owner"), branch_id=branch_id)
    try:
        with closing(connect_db()) as conn, conn:
            return _with_links(reissue_code(conn, branch_id, table_no))
    except TableError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


class PrintJob(BaseModel):
    branch_id: int = 1
    title: str = ""
    body: str
    copies: int = 1


class PrintAgentName(BaseModel):
    branch_id: int = 1
    name: str = ""


def _printing_agent(request: Request) -> dict:
    """Whoever is holding a key at the machine the printer is plugged into."""
    key = request.headers.get("x-print-key", "")
    if not key or len(key) > 200:
        raise HTTPException(401, "กุญแจเครื่องพิมพ์ไม่ถูกต้อง")
    with closing(connect_db()) as conn, conn:
        try:
            return agent_for_key(conn, key)
        except PrintError as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc


@app.post("/api/print/jobs")
def add_print_job(req: PrintJob, request: Request):
    """A till that cannot reach the printer leaves the receipt here instead."""
    require_staff(request, roles=("cashier", "manager", "owner"), branch_id=req.branch_id)
    try:
        with closing(connect_db()) as conn, conn:
            return queue_job(conn, req.branch_id, req.title, req.body, req.copies)
    except PrintError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


@app.get("/api/print/next")
def next_print_job(request: Request):
    """What the agent beside the printer asks for, over and over."""
    agent = _printing_agent(request)
    with closing(connect_db()) as conn, conn:
        return {"job": take_job(conn, agent)}


@app.post("/api/print/done")
def print_job_done(req: dict, request: Request):
    agent = _printing_agent(request)
    try:
        with closing(connect_db()) as conn, conn:
            finish_job(conn, agent, int(req.get("job_id") or 0))
    except (PrintError, ValueError, TypeError) as exc:
        status = getattr(exc, "status_code", 400)
        raise HTTPException(status, str(exc)) from exc
    return {"ok": True}


@app.get("/api/print/agents")
def get_print_agents(request: Request, branch_id: int = 1):
    require_staff(request, roles=("manager", "owner"), branch_id=branch_id)
    with closing(connect_db()) as conn, conn:
        return {"agents": list_agents(conn, branch_id), "waiting": waiting_count(conn, branch_id)}


@app.post("/api/print/agents")
def create_print_agent(req: PrintAgentName, request: Request):
    """The key is in this reply and nowhere else, ever again."""
    require_staff(request, roles=("manager", "owner"), branch_id=req.branch_id)
    try:
        with closing(connect_db()) as conn, conn:
            return issue_agent(conn, req.branch_id, req.name)
    except PrintError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


@app.delete("/api/print/agents/{agent_id}")
def remove_print_agent(agent_id: int, request: Request, branch_id: int = 1):
    require_staff(request, roles=("manager", "owner"), branch_id=branch_id)
    try:
        with closing(connect_db()) as conn, conn:
            delete_agent(conn, branch_id, agent_id)
    except PrintError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    return {"ok": True}


@app.delete("/api/tables/{table_no}")
def remove_table(table_no: str, request: Request, branch_id: int = 1):
    require_staff(request, roles=("manager", "owner"), branch_id=branch_id)
    try:
        with closing(connect_db()) as conn, conn:
            delete_table(conn, branch_id, table_no)
    except TableError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    return {"branch_id": branch_id, "table_no": table_no, "deleted": True}


@app.get("/t/{code}")
def open_table(code: str, request: Request):
    """What a scanned sticker reaches. The printed paper holds no token at all;
    one is minted here, for this scan, and lives only hours."""
    if len(TABLE_QR_SECRET) < 32:
        raise HTTPException(503, "ยังไม่ได้ตั้งค่ากุญแจ QR โต๊ะ")
    try:
        with closing(connect_db()) as conn:
            table = resolve_code(conn, code)
    except TableError as exc:
        return _table_link_problem(str(exc), exc.status_code)
    token = _mint_table_token(table["branch_id"], table["table_no"], TABLE_SCAN_TTL_SECONDS)
    # The page reads the table and branch from the query, not from the token,
    # so the redirect carries them. The token is still what proves the claim.
    return RedirectResponse("/?" + urlencode(
        {"shop": CURRENT_SHOP.get(), "table_token": token,
         "table": table["table_no"], "branch_id": table["branch_id"]}), status_code=303)


def _table_link_problem(message: str, status_code: int) -> HTMLResponse:
    """A guest with a phone, not a developer: say what to do, in Thai."""
    return HTMLResponse(
        "<!doctype html><html lang=\"th\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<title>QR โต๊ะใช้ไม่ได้</title><style>body{margin:0;display:grid;place-items:center;"
        "min-height:100vh;background:#f5f7fa;color:#17222e;font-family:\"Noto Sans Thai\",system-ui,sans-serif;"
        "padding:24px;line-height:1.8}div{max-width:420px;background:#fff;border:1px solid #e4e9f0;"
        "border-radius:18px;padding:28px;text-align:center}h1{font-size:1.25rem;margin:0 0 10px}"
        "p{margin:0;color:#5d6b7a}</style></head><body><div><h1>QR โต๊ะนี้ใช้ไม่ได้</h1>"
        f"<p>{html.escape(message)}</p></div></body></html>", status_code=status_code)


def _staff_or_table_guest(request: Request, branch_id: int, table_no: str) -> Optional[dict]:
    """The signed-in member of staff, or None for a guest holding this table's
    token. Anyone else is turned away by require_table_or_staff below.

    Not signed in is the ordinary case for a guest, so it falls through; a
    signed-in account without the right role still gets its 403.
    """
    try:
        return require_staff(request, roles=("manager", "owner", "cashier"), branch_id=branch_id)
    except HTTPException as exc:
        if exc.status_code != 401:
            raise
    require_table_or_staff(request, branch_id, table_no)
    return None


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
        raise HTTPException(401, "ต้องเข้าสู่ระบบพนักงาน หรือสแกน QR ที่โต๊ะ")
    try:
        encoded, signature = token.split(".", 1)
        payload = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        data = json.loads(payload)
        valid = hmac.compare_digest(signature, _table_signature(payload))
        if (not valid or data["b"] != branch_id or data["t"] != table_no or data["e"] < int(time.time())
                or data.get("s", MAIN_SHOP) != CURRENT_SHOP.get()):
            raise ValueError("Invalid table token")
    except (ValueError, KeyError, TypeError):
        raise HTTPException(403, "QR โต๊ะไม่ถูกต้องหรือหมดอายุแล้ว")


class OrderItem(BaseModel):
    id: str | int
    name: str
    price: float
    qty: float
    bom: list[dict] = []
    course_mode: str = "FIRE"
    # Priced and deducted from the shop's own topping list, never from these.
    addons: list[str] = []
    level: str = ""


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
    category: str = ""
    description: str = ""
    cost: float = 0
    tax_mode: str = "included"
    service_charge: bool = False
    sold_out: bool = False
    option_title: str = ""
    levels: list[str] = []
    addons: list[dict] = []


@app.get("/api/menu")
def get_menu(request: Request, branch_id: int = 1, include_inactive: bool = False):
    try:
        if include_inactive:
            require_staff(request, roles=("manager", "owner"), branch_id=branch_id)
        with closing(connect_db()) as conn:
            return {"branch_id": branch_id, "items": list_menu_items(conn, branch_id, active_only=not include_inactive)}
    except CatalogError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


@app.put("/api/menu/{item_id}")
def put_menu_item(item_id: str, item: MenuUpsert, request: Request):
    require_staff(request, roles=("manager", "owner"), branch_id=item.branch_id)
    try:
        with closing(connect_db()) as conn, conn:
            if item_id.startswith("songwai-") and item.active:
                if not item.bom:
                    raise CatalogError("Add a BOM recipe before activating Songwai menu", 409)
                for part in item.bom:
                    if not conn.execute("SELECT 1 FROM inventory WHERE branch_id=? AND ingredient_id=?",
                                        (item.branch_id, part.get("ingId"))).fetchone():
                        raise CatalogError("Add ingredient stock before activating Songwai menu", 409)
            return upsert_menu_item(
                conn, item.branch_id, item_id, item.name, item.price, item.bom,
                item.active, item.station, category=item.category,
                description=item.description, cost=item.cost, tax_mode=item.tax_mode,
                service_charge=item.service_charge, sold_out=item.sold_out,
                option_title=item.option_title, levels=item.levels, addons=item.addons)
    except CatalogError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


class MenuStatus(BaseModel):
    branch_id: int = 1
    active: Optional[bool] = None
    sold_out: Optional[bool] = None


@app.patch("/api/menu/{item_id}")
def patch_menu_status(item_id: str, item: MenuStatus, request: Request):
    """Mark a dish sold out, or take it off the customer screen, from the menu
    list itself. Nothing else about the dish is touched."""
    require_staff(request, roles=("manager", "owner"), branch_id=item.branch_id)
    try:
        with closing(connect_db()) as conn, conn:
            return set_menu_status(conn, item.branch_id, item_id, item.active, item.sold_out)
    except CatalogError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


@app.delete("/api/menu/{item_id}")
def delete_menu(item_id: str, request: Request, branch_id: int = 1):
    """Remove a dish from the menu. Bills already printed keep their own copy
    of the name and price, so nothing a customer paid is rewritten."""
    require_staff(request, roles=("manager", "owner"), branch_id=branch_id)
    try:
        with closing(connect_db()) as conn, conn:
            photo = delete_menu_item(conn, branch_id, item_id)
    except CatalogError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    if photo:
        _remove_menu_photo(photo)
    return {"branch_id": branch_id, "id": item_id, "deleted": True}


@app.get("/api/menu/categories")
def get_menu_categories(request: Request, branch_id: int = 1):
    require_staff(request, roles=("manager", "owner"), branch_id=branch_id)
    return {"branch_id": branch_id, "categories": list_menu_categories_for(branch_id),
            "stations": list(STATIONS), "tax_modes": list(TAX_MODES)}


def list_menu_categories_for(branch_id: int) -> list[str]:
    with closing(connect_db()) as conn:
        return list_menu_categories(conn, branch_id)


class InventorySet(BaseModel):
    branch_id: int = 1
    stock: float
    unit: str = "หน่วย"
    reorder_point: float = 0


class InventoryEdit(BaseModel):
    """Unit and reorder point only. Stock itself moves through a movement, so
    it keeps its audit trail instead of being quietly overwritten."""
    branch_id: int = 1
    unit: str = "หน่วย"
    reorder_point: float = 0


# --- menu photos ---------------------------------------------------------
# Kept beside the shop databases so a rebuilt container does not lose them.
MENU_PHOTO_ROOT = DB_PATH.parent / "menu-photos"
MENU_PHOTO_MAX_BYTES = 3 * 1024 * 1024
MENU_PHOTO_TYPES = {
    "image/jpeg": ("jpg", (b"\xff\xd8\xff",)),
    "image/png": ("png", (b"\x89PNG\r\n\x1a\n",)),
    "image/webp": ("webp", (b"RIFF",)),
}


def _photo_dir(shop: str) -> Path:
    # The slug is already restricted to a-z, digits and dashes by the registry.
    return MENU_PHOTO_ROOT / shop


def _photo_name(item_id: str, extension: str) -> str:
    """Name the file after a hash of the item id: an item id may contain any
    character at all, and none of them should ever reach the filesystem."""
    return hashlib.sha256(item_id.encode("utf-8")).hexdigest()[:32] + "." + extension


def _photo_kind(data: bytes, content_type: str) -> str:
    kind = MENU_PHOTO_TYPES.get((content_type or "").split(";")[0].strip().lower())
    if kind is None:
        raise HTTPException(400, "รับเฉพาะไฟล์ JPG, PNG หรือ WebP")
    extension, signatures = kind
    if not any(data.startswith(signature) for signature in signatures):
        raise HTTPException(400, "ไฟล์นี้ไม่ใช่รูปภาพจริง ลองบันทึกเป็น JPG หรือ PNG ใหม่")
    if extension == "webp" and data[8:12] != b"WEBP":
        raise HTTPException(400, "ไฟล์นี้ไม่ใช่รูปภาพจริง ลองบันทึกเป็น JPG หรือ PNG ใหม่")
    return extension


def _remove_menu_photo(photo: str) -> None:
    """Delete the file a stored photo path points at, and only such a file."""
    prefix = "/menu-photos/"
    if not photo.startswith(prefix):
        return
    parts = photo[len(prefix):].split("/")
    if len(parts) != 2:
        return
    target = _photo_dir(parts[0]) / parts[1]
    try:
        if target.resolve().parent.parent == MENU_PHOTO_ROOT.resolve():
            target.unlink(missing_ok=True)
    except OSError:
        pass


@app.post("/api/menu/{item_id}/photo")
async def upload_menu_photo(item_id: str, request: Request, branch_id: int = 1,
                            file: UploadFile = File(...)):
    require_staff(request, roles=("manager", "owner"), branch_id=branch_id)
    data = await file.read(MENU_PHOTO_MAX_BYTES + 1)
    if not data:
        raise HTTPException(400, "ไม่พบไฟล์รูป")
    if len(data) > MENU_PHOTO_MAX_BYTES:
        raise HTTPException(413, "รูปใหญ่เกิน 3 MB ย่อรูปก่อนแล้วลองใหม่")
    extension = _photo_kind(data, file.content_type or "")
    shop = CURRENT_SHOP.get()
    directory = _photo_dir(shop)
    directory.mkdir(parents=True, exist_ok=True)
    # Written to a neighbour first so a failed upload cannot leave half a photo.
    name = _photo_name(item_id, extension)
    pending = directory / (name + ".part")
    pending.write_bytes(data)
    pending.replace(directory / name)
    photo = f"/menu-photos/{shop}/{name}"
    try:
        with closing(connect_db()) as conn, conn:
            previous = conn.execute("SELECT photo FROM menu_catalog WHERE branch_id=? AND item_id=?",
                                    (branch_id, item_id)).fetchone()
            set_menu_photo(conn, branch_id, item_id, photo)
    except CatalogError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    if previous and previous[0] and previous[0] != photo:
        _remove_menu_photo(previous[0])
    return {"branch_id": branch_id, "id": item_id, "photo": photo}


@app.delete("/api/menu/{item_id}/photo")
def clear_menu_photo(item_id: str, request: Request, branch_id: int = 1):
    require_staff(request, roles=("manager", "owner"), branch_id=branch_id)
    try:
        with closing(connect_db()) as conn, conn:
            previous = conn.execute("SELECT photo FROM menu_catalog WHERE branch_id=? AND item_id=?",
                                    (branch_id, item_id)).fetchone()
            set_menu_photo(conn, branch_id, item_id, "")
    except CatalogError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    if previous and previous[0]:
        _remove_menu_photo(previous[0])
    return {"branch_id": branch_id, "id": item_id, "photo": ""}


@app.get("/menu-photos/{shop}/{name}")
def serve_menu_photo(shop: str, name: str):
    """Serve one stored photo. Both parts of the path are checked against the
    shapes this server writes, so no request can walk out of the photo store."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,28}[a-z0-9]", shop):
        raise HTTPException(404, "ไม่พบรูป")
    match = re.fullmatch(r"([0-9a-f]{32})\.(jpg|png|webp)", name)
    if not match:
        raise HTTPException(404, "ไม่พบรูป")
    target = _photo_dir(shop) / name
    if not target.is_file():
        raise HTTPException(404, "ไม่พบรูป")
    media = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}[match.group(2)]
    return FileResponse(target, media_type=media,
                        headers={"Cache-Control": "public, max-age=60"})


@app.get("/api/inventory")
def get_inventory(request: Request, branch_id: int = 1):
    require_staff(request, roles=("owner", "manager", "kitchen"), branch_id=branch_id)
    with closing(connect_db()) as conn:
        rows = conn.execute("SELECT ingredient_id,stock,unit,reorder_point FROM inventory"
                            " WHERE branch_id=? ORDER BY ingredient_id", (branch_id,)).fetchall()
    return {"branch_id": branch_id,
            "items": [{"id": row[0], "stock": row[1], "unit": row[2], "reorder_point": row[3],
                       "low": row[3] > 0 and row[1] <= row[3]} for row in rows]}


@app.put("/api/inventory/{ingredient_id}")
def put_inventory(ingredient_id: str, item: InventorySet, request: Request):
    require_staff(request, roles=("manager", "owner"), branch_id=item.branch_id)
    if not ingredient_id or len(ingredient_id) > 80 or not math.isfinite(item.stock) or item.stock < 0:
        raise HTTPException(400, "Invalid stock")
    unit, reorder_point = _ingredient_unit(item.unit), _reorder_point(item.reorder_point)
    with closing(connect_db()) as conn, conn:
        try:
            conn.execute("INSERT INTO inventory(branch_id,ingredient_id,stock,unit,reorder_point)"
                         " VALUES(?,?,?,?,?)",
                         (item.branch_id, ingredient_id, item.stock, unit, reorder_point))
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, "มีวัตถุดิบรหัสนี้แล้ว ถ้าจะเพิ่มของให้บันทึกรับเข้าแทน") from exc
    return {"branch_id": item.branch_id, "id": ingredient_id, "stock": item.stock,
            "unit": unit, "reorder_point": reorder_point}


def _ingredient_unit(value: str) -> str:
    unit = (value or "").strip() or "หน่วย"
    if len(unit) > 20:
        raise HTTPException(400, "ชื่อหน่วยนับยาวเกินไป")
    return unit


def _reorder_point(value: float) -> float:
    if not math.isfinite(value) or value < 0 or value > 1_000_000_000:
        raise HTTPException(400, "จุดแจ้งเตือนของใกล้หมดต้องเป็นเลขศูนย์ขึ้นไป")
    return float(value)


@app.patch("/api/inventory/{ingredient_id}")
def patch_inventory(ingredient_id: str, item: InventoryEdit, request: Request):
    """Change how an ingredient is counted and when it should be reordered."""
    require_staff(request, roles=("manager", "owner"), branch_id=item.branch_id)
    unit, reorder_point = _ingredient_unit(item.unit), _reorder_point(item.reorder_point)
    with closing(connect_db()) as conn, conn:
        cursor = conn.execute("UPDATE inventory SET unit=?,reorder_point=?"
                              " WHERE branch_id=? AND ingredient_id=?",
                              (unit, reorder_point, item.branch_id, ingredient_id))
    if cursor.rowcount != 1:
        raise HTTPException(404, "ไม่พบวัตถุดิบรหัสนี้")
    return {"branch_id": item.branch_id, "id": ingredient_id,
            "unit": unit, "reorder_point": reorder_point}


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
    roles = ("manager", "owner", "kitchen") if item.action == "waste" else ("manager", "owner")
    actor = require_staff(request, roles=roles, branch_id=item.branch_id)
    try:
        with closing(connect_db()) as conn, conn:
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
    require_staff(request, roles=("owner", "manager", "kitchen"), branch_id=branch_id)
    try:
        with closing(connect_db()) as conn:
            return {"branch_id": branch_id, "items": list_inventory_movements(conn, branch_id)}
    except InventoryError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


@app.post("/api/service-calls")
def create_service_call(req: ServiceCallCreate, request: Request):
    if not req.event_id or len(req.event_id) > 80 or req.branch_id < 1 or not req.table_no.strip() or len(req.table_no) > 24 or not req.call_type.strip() or len(req.call_type) > 80:
        raise HTTPException(400, "Invalid service call")
    require_table_or_staff(request, req.branch_id, req.table_no.strip())
    with closing(connect_db()) as conn, conn:
        conn.execute("INSERT OR IGNORE INTO service_calls (event_id, branch_id, table_no, call_type) VALUES (?, ?, ?, ?)",
                     (req.event_id, req.branch_id, req.table_no.strip(), req.call_type.strip()))
    return {"status": "pending", "event_id": req.event_id}


@app.get("/api/service-calls")
def list_service_calls(request: Request, branch_id: int = 1):
    if branch_id < 1:
        raise HTTPException(400, "สาขาไม่ถูกต้อง")
    require_staff(request, roles=("owner", "manager", "cashier", "service"), branch_id=branch_id)
    with closing(connect_db()) as conn, conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT event_id, branch_id, table_no, call_type, status, created_at FROM service_calls "
                            "WHERE branch_id=? AND status='pending' ORDER BY created_at DESC LIMIT 100", (branch_id,)).fetchall()
    return {"calls": [dict(row) for row in rows]}


@app.post("/api/service-calls/{event_id}/acknowledge")
def acknowledge_service_call(event_id: str, request: Request):
    with closing(connect_db()) as conn, conn:
        found = conn.execute("SELECT branch_id FROM service_calls WHERE event_id=?", (event_id,)).fetchone()
        if not found:
            raise HTTPException(404, "Service call not found")
        require_staff(request, roles=("manager", "owner", "cashier", "service"), branch_id=found[0])
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
    require_paid_subscription()
    line_id = verify_liff_id_token(req.line_id_token, LINE_LOGIN_CHANNEL_ID)
    with closing(connect_db()) as conn, conn:
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
    require_paid_subscription()
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
    with closing(connect_db()) as conn, conn:
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
    require_paid_subscription()
    external_id = "manual:" + req.channel + ":" + req.external_order_id
    with closing(connect_db()) as conn, conn:
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
    with closing(connect_db()) as conn, conn:
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
    with closing(connect_db()) as conn:
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
    with closing(connect_db()) as conn, conn:
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
    require_staff(request, roles=("owner", "manager", "cashier", "kitchen", "service"), branch_id=branch_id)
    if status not in ("active", "all"):
        raise HTTPException(400, "Invalid order filter")
    with closing(connect_db()) as conn:
        query = "SELECT order_no FROM online_orders WHERE branch_id=?"
        if status == "active":
            query += " AND status NOT IN ('handed_off','cancelled')"
        query += " ORDER BY created_at DESC LIMIT 200"
        return {"orders": [_online_order_record(conn, row[0]) for row in conn.execute(query, (branch_id,)).fetchall()]}


class OnlineStatusUpdate(BaseModel):
    status: str


@app.patch("/api/online/orders/{order_no}")
def update_online_order(order_no: str, req: OnlineStatusUpdate, request: Request):
    with closing(connect_db()) as conn, conn:
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
                restore_cancelled_inventory(conn, row[0], order_no)
            conn.execute("UPDATE online_orders SET status=?,ready_at=CASE WHEN ?='ready' THEN CURRENT_TIMESTAMP ELSE ready_at END WHERE order_no=?",
                         (req.status, req.status, order_no))
        return _online_order_record(conn, order_no)


@app.patch("/api/online/orders/{order_no}/payment")
def confirm_online_payment(order_no: str, request: Request):
    with closing(connect_db()) as conn, conn:
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
        raise HTTPException(400, "กลุ่มลูกค้าไม่ถูกต้อง")
    with closing(connect_db()) as conn:
        customers = commerce_customers(conn, branch_id, segment)
    return {"branch_id": branch_id, "segment": segment, "customers": customers}


class CustomerConsent(BaseModel):
    branch_id: int = 1
    line_id_token: str
    marketing_opt_in: bool


@app.post("/api/crm/me/consent")
def set_customer_consent(req: CustomerConsent):
    if req.branch_id < 1:
        raise HTTPException(400, "สาขาไม่ถูกต้อง")
    line_id = verify_liff_id_token(req.line_id_token, LINE_LOGIN_CHANNEL_ID)
    with closing(connect_db()) as conn, conn:
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
    with closing(connect_db()) as conn, conn:
        audience = [c for c in commerce_customers(conn, req.branch_id, req.segment)
                    if c["marketing_opt_in"] and c["line_linked"]]
        cursor = conn.execute("INSERT INTO crm_campaigns(branch_id,segment,message,created_by) VALUES(?,?,?,?)",
                              (req.branch_id, req.segment, req.message.strip(), manager["id"]))
    return {"campaign_id": cursor.lastrowid, "status": "draft", "eligible_recipients": len(audience)}


@app.get("/api/crm/campaigns/{campaign_id}")
def get_campaign(campaign_id: int, request: Request):
    with closing(connect_db()) as conn:
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
    with closing(connect_db()) as conn, conn:
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
            with closing(connect_db()) as conn, conn:
                conn.execute("UPDATE crm_campaign_deliveries SET status=? WHERE campaign_id=? AND customer_id=?",
                             (status, campaign_id, recipient["id"]))
    with closing(connect_db()) as conn, conn:
        conn.execute("UPDATE crm_campaigns SET status='submitted' WHERE id=?", (campaign_id,))
    return {"campaign_id": campaign_id, "status": "submitted", "line_accepted": accepted,
            "attempted": len(recipients), "note": "LINE HTTP acceptance does not prove message delivery"}


@app.post("/api/orders")
def create_order(req: OrderCreate, request: Request):
    if not math.isfinite(req.total_amount) or req.total_amount < 0 or not req.items or any(not math.isfinite(item.price) for item in req.items):
        raise HTTPException(400, "Invalid order")
    require_table_or_staff(request, req.branch_id, req.table_no)
    require_paid_subscription()
    with closing(connect_db()) as conn, conn:
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
        raise HTTPException(400, "สาขาไม่ถูกต้อง")
    if table_no:
        require_table_or_staff(request, branch_id, table_no)
    else:
        require_staff(request, roles=("owner", "manager", "cashier", "kitchen", "service"), branch_id=branch_id)
    query = "SELECT order_no,table_no,total_amount,status,created_at FROM order_events WHERE branch_id=? AND status='open'"
    params: list = [branch_id]
    if table_no:
        query += " AND table_no=?"
        params.append(table_no)
    query += " ORDER BY created_at DESC LIMIT 200"
    with closing(connect_db()) as conn:
        orders = []
        for row in conn.execute(query, params).fetchall():
            items = conn.execute("SELECT item_id,name,quantity,unit_price,bom_json,station,course_mode FROM order_items WHERE order_no=?", (row[0],)).fetchall()
            # What the kitchen has done with it, so a guest at the table can see
            # whether the food is still waiting, cooking, or on its way.
            tickets = [t[0] for t in conn.execute(
                "SELECT status FROM kds_station_tickets WHERE order_no=?", (row[0],))]
            if not tickets:
                kitchen = "sent"
            elif all(status == "ready" for status in tickets):
                kitchen = "ready"
            elif any(status == "held" for status in tickets):
                kitchen = "held"
            else:
                kitchen = "cooking"
            orders.append({"order_no": row[0], "table_no": row[1], "total_amount": row[2],
                           "status": row[3], "created_at": row[4], "kitchen": kitchen,
                           "items": [{"id": item[0], "name": item[1], "qty": item[2], "price": item[3],
                                      "bom": json.loads(item[4]), "station": item[5],
                                      "courseMode": item[6]} for item in items]})
    return {"branch_id": branch_id, "orders": orders}


@app.get("/api/orders/settled")
def list_settled_orders(request: Request, branch_id: int = 1, limit: int = 20):
    """Bills that are already closed, so the till can find the one to refund.

    /api/orders only carries open bills; a refund needs the paid ones, and the
    refunded ones stay in the list so the same bill is not given back twice.
    """
    if branch_id < 1 or not 1 <= limit <= 100:
        raise HTTPException(400, "คำขอไม่ถูกต้อง")
    require_staff(request, roles=("owner", "manager", "cashier"), branch_id=branch_id)
    with closing(connect_db()) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT p.order_no,p.net_amount,p.payment_method,p.status,p.closed_at,"
            "e.table_no,s.name AS closed_by FROM pos_orders p "
            "JOIN order_events e ON e.order_no=p.order_no "
            "LEFT JOIN staffs s ON s.id=p.closed_by_staff_id "
            "WHERE p.branch_id=? ORDER BY p.id DESC LIMIT ?", (branch_id, limit)).fetchall()
        reasons = {row[0]: row[1] for row in conn.execute(
            "SELECT order_no,reason FROM order_cancellations WHERE branch_id=? AND kind='refund'",
            (branch_id,))}
    return {"branch_id": branch_id,
            "orders": [{**dict(row), "refund_reason": reasons.get(row["order_no"], "")} for row in rows]}


@app.get("/api/kds")
def list_kds_tickets(request: Request, branch_id: int = 1):
    require_staff(request, roles=("owner", "manager", "cashier", "kitchen", "service"), branch_id=branch_id)
    with closing(connect_db()) as conn:
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
    with closing(connect_db()) as conn, conn:
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
    # A guest at the table may settle their own bill. Everything that makes this
    # safe is below and unchanged: the slip is verified against the exact total,
    # a slip reference is spent once, and the orders must still be open and on
    # this very table. The table token already proves which table that is.
    cashier = _staff_or_table_guest(request, req.branch_id, req.table_no.strip())
    if not os.getenv("EASYSLIP_API_KEY", ""):
        raise HTTPException(503, "EasySlip is not configured")
    order_nos = sorted(req.order_nos)
    placeholders = ",".join("?" for _ in order_nos)
    with closing(connect_db()) as conn:
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
    with closing(connect_db()) as conn, conn:
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
            # No staff id when the guest paid: nobody rang this one up, and the
            # commission rules read that column to decide who earned it.
            cursor = conn.execute("INSERT INTO pos_orders(branch_id,order_no,closed_by_staff_id,total_amount,net_amount,payment_method) VALUES (?,?,?,?,?,?)",
                                  (req.branch_id, order_no, cashier["id"] if cashier else None,
                                   amount, amount, "QR PromptPay"))
            allocate_commissions(conn, cursor.lastrowid)
    return {"status": "paid", "order_nos": order_nos, "slip_reference": slip_reference}


# Closing a bill without a machine-verified slip. The wording is stored in the
# payment record and shown in reports, so these never blur into each other.
MANUAL_CASH = "เงินสด (Cash)"
MANUAL_PROMPTPAY = "พร้อมเพย์ (ยืนยันโดยพนักงาน)"
MANUAL_PAYMENT_METHODS = (MANUAL_CASH, MANUAL_PROMPTPAY)


@app.post("/api/payments/close")
def close_payment(req: PaymentCreate, request: Request):
    if not math.isfinite(req.amount) or req.amount <= 0:
        raise HTTPException(400, "Invalid amount")
    # Cash, and a transfer a member of staff has seen land in the shop's own
    # bank app. The second one carries no slip reference by design: nothing was
    # verified by machine, and the record should not pretend otherwise. Who
    # pressed it is stored, so a shop can trace a wrong call back to a person.
    if req.method not in MANUAL_PAYMENT_METHODS or req.slip_reference:
        raise HTTPException(501, "ช่องทางนี้ยังไม่ได้เชื่อมผู้ให้บริการรับชำระเงิน")
    with closing(connect_db()) as conn, conn:
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


class OrderCancellation(BaseModel):
    event_id: str
    reason: str


def _record_cancellation(conn: sqlite3.Connection, req: OrderCancellation, order_no: str,
                         branch_id: int, kind: str, amount: float, staff: dict) -> None:
    """Write the audit row and queue the manager's LINE alert in the same transaction."""
    conn.execute("INSERT INTO order_cancellations (event_id,order_no,branch_id,kind,amount,reason,staff_id) "
                 "VALUES (?,?,?,?,?,?,?)",
                 (req.event_id, order_no, branch_id, kind, amount, req.reason.strip(), staff["id"]))
    headline = "ยกเลิกบิลก่อนรับเงิน" if kind == "void" else "คืนเงินบิลที่ชำระแล้ว"
    text = (f"⚠️ {headline}\nบิล {order_no} · {amount:,.2f} บาท\n"
            f"โดย {staff['name']} ({staff['role']})\nเหตุผล: {req.reason.strip()}")
    for (manager_line_id,) in conn.execute(
            "SELECT line_user_id FROM staffs WHERE branch_id=? AND role IN ('manager','owner') "
            "AND is_active=1 AND line_user_id IS NOT NULL", (branch_id,)):
        enqueue_line_notification(conn, f"cancel:{kind}:{order_no}", manager_line_id, branch_id,
                                  {"type": "text", "text": text})


def _existing_cancellation(conn: sqlite3.Connection, req: OrderCancellation, order_no: str, kind: str):
    prior = conn.execute("SELECT order_no,kind FROM order_cancellations WHERE event_id=?",
                         (req.event_id,)).fetchone()
    if not prior:
        return None
    if prior[0] != order_no or prior[1] != kind:
        raise HTTPException(409, "Cancellation event already belongs to another bill")
    return {"status": prior[1], "order_no": order_no, "existing": True}


@app.post("/api/orders/{order_no}/void")
def void_open_order(order_no: str, req: OrderCancellation, request: Request):
    """Cancel an unpaid bill. Small ones are a cashier's call; the rest are a manager's."""
    if not req.event_id or len(req.event_id) > 80 or not 3 <= len(req.reason.strip()) <= 200:
        raise HTTPException(400, "A cancellation needs an event id and a reason of 3 to 200 characters")
    with closing(connect_db()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        order = conn.execute("SELECT branch_id,status,total_amount FROM order_events WHERE order_no=?",
                             (order_no,)).fetchone()
        if not order:
            raise HTTPException(404, "Order not found")
        branch_id, status, amount = order[0], order[1], float(order[2])
        staff = require_staff(request, roles=("manager", "owner", "cashier"), branch_id=branch_id)
        done = _existing_cancellation(conn, req, order_no, "void")
        if done:
            return done
        if status != "open":
            raise HTTPException(409, "Only an open bill can be cancelled; use the refund flow once it is paid")
        if staff["role"] == "cashier":
            today = datetime.datetime.now(BANGKOK_TZ).date().isoformat()
            # created_at is SQLite's UTC CURRENT_TIMESTAMP, so it has to be shifted to
            # Bangkok before the dates are compared. Without the shift the count was
            # always zero between midnight and 07:00 local time — exactly when a late
            # shift runs — so the daily ceiling quietly disappeared every night.
            used = conn.execute("SELECT COUNT(*) FROM order_cancellations WHERE staff_id=? AND kind='void' "
                                "AND date(created_at,?)=?",
                                (staff["id"], BANGKOK_SQL_OFFSET, today)).fetchone()[0]
            if amount > VOID_CASHIER_MAX_AMOUNT:
                raise HTTPException(403, f"บิลเกิน {VOID_CASHIER_MAX_AMOUNT:,.0f} บาท ต้องให้ผู้จัดการยกเลิก")
            if used >= VOID_CASHIER_DAILY_LIMIT:
                raise HTTPException(403, f"ยกเลิกเองครบ {VOID_CASHIER_DAILY_LIMIT} ครั้งแล้ววันนี้ ต้องให้ผู้จัดการยกเลิก")
        restore_cancelled_inventory(conn, branch_id, order_no)
        conn.execute("UPDATE order_events SET status='void' WHERE order_no=?", (order_no,))
        conn.execute("DELETE FROM kds_station_tickets WHERE order_no=?", (order_no,))
        _record_cancellation(conn, req, order_no, branch_id, "void", amount, staff)
    return {"status": "void", "order_no": order_no, "amount": amount, "voided_by": staff["id"]}


@app.post("/api/payments/{order_no}/refund")
def refund_paid_order(order_no: str, req: OrderCancellation, request: Request):
    """Give money back on a closed bill. Always a manager or the owner, never a cashier."""
    if not req.event_id or len(req.event_id) > 80 or not 3 <= len(req.reason.strip()) <= 200:
        raise HTTPException(400, "A refund needs an event id and a reason of 3 to 200 characters")
    with closing(connect_db()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        order = conn.execute("SELECT branch_id,status,total_amount FROM order_events WHERE order_no=?",
                             (order_no,)).fetchone()
        if not order:
            raise HTTPException(404, "Order not found")
        branch_id, status, amount = order[0], order[1], float(order[2])
        manager = require_staff(request, roles=("manager", "owner"), branch_id=branch_id)
        done = _existing_cancellation(conn, req, order_no, "refund")
        if done:
            return done
        if status != "paid":
            raise HTTPException(409, "Only a paid bill can be refunded")
        paid = conn.execute("SELECT id FROM pos_orders WHERE order_no=? AND status='paid'", (order_no,)).fetchone()
        if not paid:
            raise HTTPException(409, "No settled payment to refund")
        restore_cancelled_inventory(conn, branch_id, order_no)
        conn.execute("UPDATE order_events SET status='refunded' WHERE order_no=?", (order_no,))
        conn.execute("UPDATE pos_orders SET status='refunded' WHERE id=?", (paid[0],))
        # Commission earned on this bill is reversed with mirrored rows, so the
        # payroll history keeps both the credit and the clawback.
        reversed_rows = conn.execute(
            "INSERT INTO commission_records (staff_id,order_id,period_date,base_sales_amount,"
            "calculated_amount,pool_divisor) SELECT staff_id,order_id,period_date,-base_sales_amount,"
            "-calculated_amount,pool_divisor FROM commission_records WHERE order_id=? AND calculated_amount>0",
            (paid[0],)).rowcount
        _record_cancellation(conn, req, order_no, branch_id, "refund", amount, manager)
    return {"status": "refunded", "order_no": order_no, "amount": amount,
            "refunded_by": manager["id"], "commission_entries_reversed": reversed_rows}


# =====================================================================
# แฟ้มประวัติพนักงาน: ข้อมูลการจ้าง เอกสาร ทรัพย์สินของร้าน และไทม์ไลน์
# =====================================================================
class DossierProfileUpdate(BaseModel):
    nickname: Optional[str] = None
    phone: Optional[str] = None
    line_display: Optional[str] = None
    start_date: Optional[str] = None
    employment_type: Optional[str] = None
    probation_end_date: Optional[str] = None
    bank_name: Optional[str] = None
    bank_account: Optional[str] = None
    emergency_contact: Optional[str] = None
    emergency_phone: Optional[str] = None
    medical_note: Optional[str] = None


class DocumentUpdate(BaseModel):
    received: bool
    expires_on: Optional[str] = None
    note: str = ""


class AssetCreate(BaseModel):
    item: str
    issued_on: Optional[str] = None


class AssetReturn(BaseModel):
    returned: bool


class TimelineCreate(BaseModel):
    kind: str
    detail: str
    event_date: Optional[str] = None


def _dossier_reader(request: Request, staff_id: int, conn: sqlite3.Connection) -> dict:
    """A dossier holds pay, bank and health notes: the person or their manager only."""
    actor = require_staff(request)
    owner_row = conn.execute("SELECT branch_id,role FROM staffs WHERE id=?", (staff_id,)).fetchone()
    if not owner_row:
        raise HTTPException(404, "ไม่พบพนักงานคนนี้")
    if actor["id"] == staff_id:
        return actor
    if actor["role"] not in ("manager", "owner") or actor["branch_id"] != owner_row[0]:
        raise HTTPException(403, "Only this staff member or a manager can open the dossier")
    return actor


def _dossier_editor(request: Request, staff_id: int, conn: sqlite3.Connection) -> dict:
    actor = require_staff(request, roles=("manager", "owner"))
    conn.row_factory = sqlite3.Row
    target = conn.execute("SELECT id,branch_id,role FROM staffs WHERE id=?", (staff_id,)).fetchone()
    if not target or target["branch_id"] != actor["branch_id"]:
        raise HTTPException(404, "ไม่พบพนักงานคนนี้")
    if not _can_manage_staff(actor, target) and actor["id"] != staff_id:
        raise HTTPException(403, "Cannot edit this staff dossier")
    return actor


def _today() -> datetime.date:
    return datetime.datetime.now(BANGKOK_TZ).date()


@app.get("/api/staff/dossier-summary")
def dossier_summary(request: Request, branch_id: int = 1):
    """The manager's checklist: who still owes paperwork, whose card is expiring."""
    require_staff(request, roles=("manager", "owner"), branch_id=branch_id)
    with closing(connect_db()) as conn, conn:
        return {"branch_id": branch_id, "work_date": _today().isoformat(),
                "staff": branch_summary(conn, branch_id, _today())}


@app.get("/api/staff/{staff_id}/dossier")
def get_staff_dossier(staff_id: int, request: Request):
    with closing(connect_db()) as conn, conn:
        _dossier_reader(request, staff_id, conn)
        try:
            return read_dossier(conn, staff_id, _today())
        except DossierError as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc


@app.patch("/api/staff/{staff_id}/dossier")
def update_staff_dossier(staff_id: int, req: DossierProfileUpdate, request: Request):
    with closing(connect_db()) as conn, conn:
        _dossier_editor(request, staff_id, conn)
        try:
            update_profile(conn, staff_id, req.model_dump(exclude_none=True))
            return read_dossier(conn, staff_id, _today())
        except DossierError as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc


@app.put("/api/staff/{staff_id}/documents/{doc_type}")
def set_staff_document(staff_id: int, doc_type: str, req: DocumentUpdate, request: Request):
    """Records that a document was handed in and when it expires, not the file itself."""
    with closing(connect_db()) as conn, conn:
        actor = _dossier_editor(request, staff_id, conn)
        try:
            set_document(conn, staff_id, doc_type, req.received, req.expires_on, req.note, actor["id"])
            return read_dossier(conn, staff_id, _today())
        except DossierError as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc


@app.post("/api/staff/{staff_id}/assets")
def add_staff_asset(staff_id: int, req: AssetCreate, request: Request):
    with closing(connect_db()) as conn, conn:
        _dossier_editor(request, staff_id, conn)
        try:
            add_asset(conn, staff_id, req.item, req.issued_on, _today())
            return read_dossier(conn, staff_id, _today())
        except DossierError as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc


@app.patch("/api/staff/{staff_id}/assets/{asset_id}")
def return_staff_asset(staff_id: int, asset_id: int, req: AssetReturn, request: Request):
    with closing(connect_db()) as conn, conn:
        _dossier_editor(request, staff_id, conn)
        try:
            return_asset(conn, staff_id, asset_id, req.returned, _today())
            return read_dossier(conn, staff_id, _today())
        except DossierError as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc


@app.post("/api/staff/{staff_id}/timeline")
def add_staff_timeline(staff_id: int, req: TimelineCreate, request: Request):
    with closing(connect_db()) as conn, conn:
        actor = _dossier_editor(request, staff_id, conn)
        try:
            add_timeline_entry(conn, staff_id, req.event_date, req.kind, req.detail,
                               actor["id"], _today())
            return read_dossier(conn, staff_id, _today())
        except DossierError as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc


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
    with closing(connect_db()) as conn, conn:
        target = conn.execute("SELECT branch_id,is_active,role FROM staffs WHERE id=?", (req.staff_id,)).fetchone()
        if not target or not target[1]:
            raise HTTPException(404, "Active staff not found")
        if target[0] != staff["branch_id"]:
            raise HTTPException(403, "คุณไม่ได้อยู่สาขานี้")
        if req.staff_id != staff["id"] and staff["role"] == "manager" and target[2] in ("manager", "owner"):
            raise HTTPException(403, "Manager cannot record another manager's attendance")
        today = datetime.datetime.now(BANGKOK_TZ).date().isoformat()
        locked = conn.execute("SELECT 1 FROM staff_shifts WHERE staff_id=? AND work_date=? AND pos_pin_locked=1",
                              (req.staff_id, today)).fetchone()
        if locked:
            raise HTTPException(403, "บัญชีนี้ถูกระงับสิทธิ์สำหรับกะวันนี้")
    with closing(connect_db()) as conn, conn:
        cur = conn.cursor()
        existing_event = cur.execute("SELECT staff_id,action FROM attendance_events WHERE event_id=?", (req.event_id,)).fetchone()
        if existing_event:
            if existing_event != (req.staff_id, req.action):
                raise HTTPException(409, "Attendance event ID belongs to another action")
            return {"status": "already_recorded"}
        open_shift = cur.execute("SELECT id FROM attendances WHERE staff_id=? AND clock_out IS NULL ORDER BY id DESC LIMIT 1",
                                 (req.staff_id,)).fetchone()
        if req.action == "clock_in" and open_shift:
            raise HTTPException(409, "Staff is already clocked in")
        if req.action == "clock_out" and not open_shift:
            raise HTTPException(409, "No open attendance to clock out")
        cur.execute("INSERT OR IGNORE INTO attendance_events (event_id, staff_id, action) VALUES (?,?,?)",
                    (req.event_id, req.staff_id, req.action))
        if cur.rowcount:
            now = datetime.datetime.now(BANGKOK_TZ).replace(tzinfo=None).isoformat(timespec="seconds")
            if req.action == "clock_in":
                cur.execute("INSERT INTO attendances (staff_id, clock_in) VALUES (?,?)", (req.staff_id, now))
            else:
                cur.execute("UPDATE attendances SET clock_out=? WHERE id=(SELECT id FROM attendances "
                            "WHERE staff_id=? AND clock_out IS NULL ORDER BY id DESC LIMIT 1)",
                            (now, req.staff_id))
    return {"status": "recorded"}


class StaffPayRate(BaseModel):
    hourly_rate: float


@app.patch("/api/staff/{staff_id}/pay-rate")
def set_staff_pay_rate(staff_id: int, req: StaffPayRate, request: Request):
    manager = require_staff(request, roles=("manager", "owner"))
    if not math.isfinite(req.hourly_rate) or req.hourly_rate < 0 or req.hourly_rate > 100000:
        raise HTTPException(400, "ค่าแรงต่อชั่วโมงไม่ถูกต้อง")
    with closing(connect_db()) as conn, conn:
        changed = conn.execute("UPDATE staffs SET hourly_rate=? WHERE id=? AND branch_id=? AND is_active=1",
                               (req.hourly_rate, staff_id, manager["branch_id"]))
        if not changed.rowcount:
            raise HTTPException(404, "Active staff not found")
    return {"staff_id": staff_id, "hourly_rate": req.hourly_rate}


class ShiftTemplateCreate(BaseModel):
    branch_id: int
    name: str
    start_time: str
    end_time: str


@app.post("/api/staff/shift-templates")
def create_shift_template(req: ShiftTemplateCreate, request: Request):
    require_staff(request, roles=("manager", "owner"), branch_id=req.branch_id)
    if not req.name.strip() or len(req.name) > 80 or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", req.start_time) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", req.end_time) or req.start_time == req.end_time:
        raise HTTPException(400, "Invalid shift template")
    with closing(connect_db()) as conn, conn:
        cur = conn.execute("INSERT INTO shift_templates (branch_id,name,start_time,end_time) VALUES (?,?,?,?)",
                           (req.branch_id, req.name.strip(), req.start_time, req.end_time))
    return {"id": cur.lastrowid, **req.model_dump()}


@app.get("/api/staff/shift-templates")
def list_shift_templates(request: Request, branch_id: int = 1):
    require_staff(request, roles=("manager", "owner"), branch_id=branch_id)
    with closing(connect_db()) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT id,name,start_time,end_time FROM shift_templates WHERE branch_id=? ORDER BY id",
                            (branch_id,)).fetchall()
    return {"items": [dict(row) for row in rows]}


class ShiftAssignment(BaseModel):
    staff_id: int
    branch_id: int
    work_date: str
    shift_template_id: Optional[int] = None  # None books the day off


@app.post("/api/staff/shifts")
def assign_shift(req: ShiftAssignment, request: Request):
    require_staff(request, roles=("manager", "owner"), branch_id=req.branch_id)
    try:
        datetime.date.fromisoformat(req.work_date)
    except ValueError as exc:
        raise HTTPException(400, "Invalid work date") from exc
    with closing(connect_db()) as conn, conn:
        staff = conn.execute("SELECT 1 FROM staffs WHERE id=? AND branch_id=? AND is_active=1",
                             (req.staff_id, req.branch_id)).fetchone()
        template = req.shift_template_id is None or conn.execute(
            "SELECT 1 FROM shift_templates WHERE id=? AND branch_id=?",
            (req.shift_template_id, req.branch_id)).fetchone()
        if not staff or not template:
            raise HTTPException(404, "Staff or shift template not found")
        current = conn.execute("SELECT status FROM staff_shifts WHERE staff_id=? AND work_date=?",
                               (req.staff_id, req.work_date)).fetchone()
        if current and current[0] in ("on_leave", "absent"):
            raise HTTPException(409, "Cannot replace leave or absence shift")
        status = "day_off" if req.shift_template_id is None else "scheduled"
        conn.execute("INSERT INTO staff_shifts (staff_id,branch_id,work_date,shift_template_id,status) "
                     "VALUES (?,?,?,?,?) ON CONFLICT(staff_id,work_date) DO UPDATE "
                     "SET shift_template_id=excluded.shift_template_id,status=excluded.status",
                     (req.staff_id, req.branch_id, req.work_date, req.shift_template_id, status))
    return {"status": status, **req.model_dump()}


@app.post("/api/staff/absence-check")
def check_staff_absences(request: Request, branch_id: int = 1):
    """Mark scheduled staff absent after the shift start plus 60 minutes."""
    require_staff(request, roles=("manager", "owner"), branch_id=branch_id)
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=7)))
    today = now.date().isoformat()
    absent_ids = []
    with closing(connect_db()) as conn, conn:
        rows = conn.execute("SELECT ss.staff_id,st.start_time FROM staff_shifts ss "
                            "JOIN shift_templates st ON st.id=ss.shift_template_id AND st.branch_id=ss.branch_id "
                            "WHERE ss.branch_id=? AND ss.work_date=? AND ss.status='scheduled' "
                            "AND ss.pos_pin_locked=0", (branch_id, today)).fetchall()
        for staff_id, start_time in rows:
            start = datetime.datetime.fromisoformat(f"{today}T{start_time}").replace(tzinfo=now.tzinfo)
            if now < start + datetime.timedelta(minutes=60):
                continue
            worked = conn.execute("SELECT 1 FROM attendances WHERE staff_id=? AND substr(clock_in,1,10)=? LIMIT 1",
                                  (staff_id, today)).fetchone()
            if worked:
                continue
            updated = conn.execute("UPDATE staff_shifts SET status='absent',pos_pin_locked=1 "
                                   "WHERE staff_id=? AND work_date=? AND status='scheduled'",
                                   (staff_id, today))
            if updated.rowcount:
                conn.execute("DELETE FROM auth_sessions WHERE staff_id=?", (staff_id,))
                absent_ids.append(staff_id)
    return {"work_date": today, "absent_staff_ids": absent_ids}


@app.get("/api/commissions")
def commissions(request: Request, work_date: str, branch_id: int = 1):
    require_staff(request, roles=("manager", "owner"), branch_id=branch_id)
    try:
        datetime.date.fromisoformat(work_date)
    except ValueError:
        raise HTTPException(400, "work_date must be YYYY-MM-DD")
    with closing(connect_db()) as conn, conn:
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
        raise HTTPException(400, "สาขาไม่ถูกต้อง")
    start = datetime.date.fromisoformat(f"{month}-01")
    end = (start.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
    with closing(connect_db()) as conn, conn:
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
    with closing(connect_db()) as conn:
        conn.row_factory = sqlite3.Row
        staff_rows = conn.execute(
            "SELECT s.id,s.name,s.role,s.branch_id,ss.status,ss.pos_pin_locked,ss.shift_template_id,"
            "st.name AS shift_name,st.start_time,st.end_time,a.clock_in,a.clock_out "
            "FROM staffs s LEFT JOIN staff_shifts ss ON ss.staff_id=s.id AND ss.work_date=? "
            "LEFT JOIN shift_templates st ON st.id=ss.shift_template_id "
            "LEFT JOIN attendances a ON a.id=(SELECT id FROM attendances WHERE staff_id=s.id "
            "AND substr(clock_in,1,10)=? ORDER BY id DESC LIMIT 1) "
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
        quotas = leave_quota_map(conn, branch_id)
    by_staff_commission = {row["staff_id"]: round(float(row["amount"]), 2) for row in commissions}
    staff = [{"id": row["id"], "name": row["name"], "role": row["role"],
              "shift": row["shift_name"] or (f"{row['start_time']}–{row['end_time']}" if row["start_time"] else
                                             "วันหยุด" if row["status"] == "day_off" else "—"),
              "shift_template_id": row["shift_template_id"],
              "status": row["status"] if row["status"] in ("on_leave", "absent", "day_off", "suspended") else
                        ("clocked_out" if row["clock_out"] else "clocked_in" if row["clock_in"] else "scheduled"),
              "pos_pin_locked": bool(row["pos_pin_locked"]), "clock_in": row["clock_in"],
              "clock_out": row["clock_out"], "leave_quota": quotas.get(row["id"]),
              "commission_today": by_staff_commission.get(row["id"], 0.0)} for row in staff_rows]
    return {"branch_id": branch_id, "work_date": today, "staff": staff,
            "leave_requests": [dict(row) for row in leaves],
            "note": "Only recorded shifts, attendance, approved leave and commission entries are shown."}


@app.get("/api/staff/me")
def my_staff_status(request: Request):
    actor = require_staff(request)
    today = datetime.datetime.now(BANGKOK_TZ).date().isoformat()
    with closing(connect_db()) as conn:
        row = conn.execute("SELECT a.clock_in,a.clock_out,ss.status,ss.pos_pin_locked,st.name "
                           "FROM staffs s LEFT JOIN staff_shifts ss ON ss.staff_id=s.id AND ss.work_date=? "
                           "LEFT JOIN shift_templates st ON st.id=ss.shift_template_id "
                           "LEFT JOIN attendances a ON a.id=(SELECT id FROM attendances WHERE staff_id=s.id "
                           "AND substr(clock_in,1,10)=? ORDER BY id DESC LIMIT 1) WHERE s.id=?",
                           (today, today, actor["id"])).fetchone()
        quota = leave_quota_map(conn, actor["branch_id"]).get(actor["id"])
    status = row[2] if row[2] in ("on_leave", "absent", "day_off", "suspended") else (
        "clocked_out" if row[1] else "clocked_in" if row[0] else "scheduled")
    return {"id": actor["id"], "name": actor["name"], "role": actor["role"],
            "shift": row[4] or ("วันหยุด" if status == "day_off" else "—"), "status": status,
            "pos_pin_locked": bool(row[3]), "leave_quota": quota,
            "clock_in": row[0], "clock_out": row[1]}


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
    with closing(connect_db()) as conn, conn:
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
    conn = connect_db()
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT l.staff_id, l.start_date, l.end_date, l.status, s.branch_id, s.line_user_id "
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
        if row["line_user_id"]:
            decision_text = "อนุมัติ" if decision == "approved" else "ไม่อนุมัติ"
            enqueue_line_notification(conn, f"leave-result:{leave_id}", row["line_user_id"], row["branch_id"],
                                      {"type": "text", "text": f"คำขอลา #{leave_id} ของคุณ: {decision_text}"})
        conn.commit()
        notification = flush_line_notifications(conn, LINE_CHANNEL_ACCESS_TOKEN, row["branch_id"])
        return {"status": decision, "leave_id": leave_id, "staff_id": row["staff_id"],
                "pos_pin_locked": decision == "approved", "work_date": row["start_date"],
                "line_notification": notification["status"]}
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
    conn = connect_db()
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
    managers = [row[0] for row in cur.execute(
        "SELECT line_user_id FROM staffs WHERE branch_id=? AND role IN ('manager','owner') "
        "AND is_active=1 AND line_user_id IS NOT NULL", (staff["branch_id"],))]
    message = build_leave_flex(leave_id, staff["name"], req.leave_type, req.start_date, req.end_date, req.reason)
    for manager_line_id in managers:
        enqueue_line_notification(conn, f"leave-request:{leave_id}", manager_line_id, staff["branch_id"], message)
    conn.commit()
    notification = flush_line_notifications(conn, LINE_CHANNEL_ACCESS_TOKEN, staff["branch_id"])
    conn.close()
    return {
        "status": "pending",
        "leave_id": leave_id,
        "line_flex_notification": "no_bound_manager" if not managers else notification["status"],
    }


@app.post("/api/line/notifications/retry")
def retry_line_notifications(request: Request, branch_id: int = 1):
    require_staff(request, roles=("manager", "owner"), branch_id=branch_id)
    with closing(connect_db()) as conn:
        return flush_line_notifications(conn, LINE_CHANNEL_ACCESS_TOKEN, branch_id, limit=100)


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
        with closing(connect_db()) as conn:
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
    conn = connect_db()
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
        return build_analytics_dashboard(current_db_path(), benchmark, branch_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


# The slim container image carries no /etc/mime.types, so Python would label every
# .webp as text/plain. With the nosniff header this page sends, the browser then
# refuses to draw the image, so the types are registered here instead.
for suffix, media_type in ((".webp", "image/webp"), (".svg", "image/svg+xml"),
                           (".woff2", "font/woff2"), (".json", "application/json")):
    mimetypes.add_type(media_type, suffix)

app.mount("/assets", StaticFiles(directory=Path(__file__).parent / "assets"), name="assets")


@app.get("/service-worker.js")
def serve_worker():
    return FileResponse(Path(__file__).parent / "service-worker.js", media_type="application/javascript",
                        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"})


@app.get("/{asset_name}.css")
def serve_workspace_css(asset_name: str):
    if asset_name not in {"ui", "workspace", "sales-redesign", "ops-redesign", "people-redesign", "staff-admin", "staff-dossier", "reports-restore", "reports-live", "service-call", "auth-ui", "payment-ui", "live-data", "inventory-live", "commerce-ui", "landing", "billing-ui", "legal"}:
        raise HTTPException(404, "Stylesheet not found")
    return FileResponse(Path(__file__).parent / f"{asset_name}.css", media_type="text/css")


@app.get("/{asset_name}.js")
def serve_workspace_js(asset_name: str):
    if asset_name not in {"workspace", "sales-redesign", "ops-redesign", "people-redesign", "staff-admin", "staff-dossier", "reports-restore", "reports-live", "service-call", "auth-ui", "payment-ui", "live-data", "inventory-live", "commerce-ui", "landing", "billing-ui", "cashier-void", "tables-ui", "print-agent-ui", "qr"}:
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


@app.get("/privacy", response_class=HTMLResponse)
@app.get("/privacy.html", response_class=HTMLResponse)
def serve_privacy():
    """Public, and linked wherever consent is asked for."""
    return (Path(__file__).parent / "privacy.html").read_text(encoding="utf-8")


@app.get("/terms", response_class=HTMLResponse)
@app.get("/terms.html", response_class=HTMLResponse)
def serve_terms():
    return (Path(__file__).parent / "terms.html").read_text(encoding="utf-8")


@app.get("/line_pos_prototype.html")
def serve_prototype():
    """The old prototype copy is gone; keep saved links working on the real app."""
    return RedirectResponse("/", status_code=301)


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
    slug = CURRENT_SHOP.get()
    shop = shops.get_shop(DB_PATH, slug) if slug not in (MAIN_SHOP, DEMO_SHOP) else None
    return {"void_limits": {"max_amount": VOID_CASHIER_MAX_AMOUNT, "daily_limit": VOID_CASHIER_DAILY_LIMIT},
            "login_channels": {"line": bool(LINE_LOGIN_CHANNEL_ID and LINE_LOGIN_CHANNEL_SECRET),
                               "google": bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET),
                               "facebook": bool(FACEBOOK_APP_ID and FACEBOOK_APP_SECRET),
                               "email": OWNER_EMAIL_LOGIN},
            "promptpay_id": shop["promptpay_id"] if shop else (PROMPTPAY_ID if slug == MAIN_SHOP else ""),
            "line_liff_id": LINE_LIFF_ID, "preview_only": is_preview(),
            "staff_live": STAFF_LIVE and slug != DEMO_SHOP,
            "shop": {"slug": slug, "name": shop["name"] if shop else "",
                     "is_demo": slug == DEMO_SHOP, "trial_ends_at": shop["trial_ends_at"] if shop else None},
            "billing": _billing_notice(slug),
            "point_baht": POINT_BAHT}


def _billing_notice(slug: str) -> dict:
    """Just enough for the app to show its own notice before anyone signs in."""
    if slug in (MAIN_SHOP, DEMO_SHOP) or not shops.get_shop(DB_PATH, slug):
        return {"applicable": False, "state": billing.STATE_HOSTED}
    state = billing.billing_state(DB_PATH, slug, price=MONTHLY_PRICE)
    return {"applicable": True, "state": state["state"], "blocked": state["blocked"],
            "days_left": state["days_left"], "due_date": state["due_date"],
            "on_trial": state["on_trial"], "price": MONTHLY_PRICE, "message": state["message"]}


# =====================================================================
# Opening a new shop
class ShopSignup(BaseModel):
    shop_name: str
    slug: str
    owner_name: str
    phone: str
    pin: str
    accept_terms: bool


@app.get("/api/shops/check")
def check_shop_slug(slug: str):
    slug = slug.strip().lower()
    return {"slug": slug, "valid": shops.valid_slug(slug),
            "available": shops.slug_available(DB_PATH, slug)}


@app.post("/api/shops")
def open_shop(req: ShopSignup, request: Request, response: Response):
    slug = req.slug.strip().lower()
    shop_name, owner_name = req.shop_name.strip(), req.owner_name.strip()
    phone = re.sub(r"[\s-]", "", req.phone)
    if not req.accept_terms:
        raise HTTPException(400, "กรุณายอมรับเงื่อนไขการใช้งาน")
    if not shop_name or len(shop_name) > 80 or not owner_name or len(owner_name) > 100:
        raise HTTPException(400, "กรุณากรอกชื่อร้านและชื่อเจ้าของร้าน")
    if not re.fullmatch(r"\+?\d{9,15}", phone):
        raise HTTPException(400, "เบอร์โทรไม่ถูกต้อง")
    if not shops.valid_slug(slug):
        raise HTTPException(400, "ชื่อร้านในลิงก์ใช้ a-z ตัวเลข และขีดกลาง ยาว 3–30 ตัว")
    pin_hash = hash_pin(req.pin)
    client = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (
        request.client.host if request.client else "unknown")
    try:
        shop = shops.reserve_shop(DB_PATH, slug=slug, name=shop_name, owner_name=owner_name,
                                  phone=phone, client_key=client, max_shops=MAX_SHOPS)
    except ShopError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    CURRENT_SHOP.set(slug)
    try:
        with closing(connect_db()) as conn, conn:
            conn.execute("INSERT INTO branches (id,name) VALUES (1,?)", (shop_name,))
            cur = conn.execute("INSERT INTO staffs (branch_id,name,role,pin_code_hash) VALUES (1,?,'owner',?)",
                               (owner_name, pin_hash))
            store_leave_quota(conn, cur.lastrowid, None)
            owner_id = cur.lastrowid
            expires = _open_session(request, response, conn, owner_id)
    except Exception:
        _prepared_databases.discard(shops.shop_db_path(DB_PATH, slug))
        shops.shop_db_path(DB_PATH, slug).unlink(missing_ok=True)
        shops.release_shop(DB_PATH, slug)
        raise
    account = owner_auth.session_account(DB_PATH, request.cookies.get(OWNER_COOKIE, ""))
    if account:
        # Opened from an owner account: bind it now so the next sign-in needs no shop code.
        owner_auth.link_shop(DB_PATH, account_id=account["id"], slug=slug, staff_id=owner_id)
    _remember_shop(request, response, slug)
    return {"shop": {"slug": slug, "name": shop["name"], "trial_ends_at": shop["trial_ends_at"]},
            "staff_id": owner_id, "branch_id": 1, "name": owner_name, "role": "owner",
            "expires_at": expires, "linked_account": bool(account)}


class ShopSettings(BaseModel):
    name: Optional[str] = None
    promptpay_id: Optional[str] = None


@app.get("/api/shop/settings")
def read_shop_settings(request: Request):
    require_staff(request, roles=("owner",))
    slug = CURRENT_SHOP.get()
    shop = shops.get_shop(DB_PATH, slug)
    if not shop:
        return {"slug": slug, "name": "", "promptpay_id": PROMPTPAY_ID, "editable": False}
    return {"slug": slug, "name": shop["name"], "promptpay_id": shop["promptpay_id"],
            "trial_ends_at": shop["trial_ends_at"], "editable": True}


@app.put("/api/shop/settings")
def save_shop_settings(req: ShopSettings, request: Request):
    require_staff(request, roles=("owner",))
    slug = CURRENT_SHOP.get()
    if not shops.get_shop(DB_PATH, slug):
        raise HTTPException(409, "ร้านหลักตั้งค่าผ่านไฟล์ตั้งค่าเซิร์ฟเวอร์")
    name = req.name.strip() if req.name is not None else None
    promptpay = re.sub(r"[\s-]", "", req.promptpay_id) if req.promptpay_id is not None else None
    if name is not None and (not name or len(name) > 80):
        raise HTTPException(400, "ชื่อร้านต้องยาว 1–80 ตัวอักษร")
    if promptpay and not re.fullmatch(r"\d{10}|\d{13}|\d{15}", promptpay):
        raise HTTPException(400, "พร้อมเพย์ต้องเป็นเบอร์โทร 10 หลัก เลขบัตร 13 หลัก หรือ e-Wallet 15 หลัก")
    shop = shops.update_shop(DB_PATH, slug, name=name, promptpay_id=promptpay)
    if name is not None:
        with closing(connect_db()) as conn, conn:
            conn.execute("UPDATE branches SET name=? WHERE id=1", (name,))
    return {"slug": slug, "name": shop["name"], "promptpay_id": shop["promptpay_id"]}


# =====================================================================
# Owner accounts: an owner signs in as a person, not as a shop code
# The PIN login stays for front-of-house, where one tablet passes between people.
OWNER_COOKIE = "poswai_owner"
OWNER_FAILURES = {
    "state": "คำขอเข้าสู่ระบบหมดอายุหรือไม่ถูกต้อง กรุณาลองใหม่",
    "denied": "คุณยกเลิกการเข้าสู่ระบบ หรือผู้ให้บริการไม่อนุญาต",
    "provider": "ติดต่อผู้ให้บริการเข้าสู่ระบบไม่สำเร็จ กรุณาลองใหม่",
    "id_token": "ข้อมูลยืนยันตัวตนไม่ถูกต้อง กรุณาลองใหม่",
    "nonce": "ข้อมูลยืนยันตัวตนไม่ตรงกับคำขอนี้ กรุณาลองใหม่",
    "code": "ไม่ได้รับรหัสยืนยันจากผู้ให้บริการ กรุณาลองใหม่",
    "shop": "ร้านที่จะผูกบัญชีใช้งานไม่ได้แล้ว",
    "unconfigured": "ยังไม่ได้เปิดใช้ช่องทางนี้",
    "provider_unknown": "ช่องทางเข้าสู่ระบบนี้ไม่มีในระบบ",
}
OWNER_CHANNELS = {"line": "LINE", "google": "Google"}


def _provider_credentials(provider: str) -> tuple[str, str]:
    if provider == "line":
        return LINE_LOGIN_CHANNEL_ID, LINE_LOGIN_CHANNEL_SECRET
    if provider == "google":
        return GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
    raise HTTPException(404, OWNER_FAILURES["provider_unknown"])


def _owner_redirect_uri(request: Request, provider: str) -> str:
    """The callback the consoles know. Falls back to this request's own host in
    development, where no public URL is configured."""
    base = PUBLIC_BASE_URL or str(request.base_url).rstrip("/")
    return f"{base}/api/owner/auth/{provider}/callback"


def _owner_failure(code: str) -> RedirectResponse:
    """Send the browser home with a reason the sign-in page can read out in Thai."""
    return RedirectResponse(f"/?owner_error={code if code in OWNER_FAILURES else 'provider'}",
                            status_code=303)


def _owner_account(request: Request) -> dict:
    account = owner_auth.session_account(DB_PATH, request.cookies.get(OWNER_COOKIE, ""))
    if not account:
        raise HTTPException(401, "กรุณาเข้าสู่ระบบด้วยบัญชีเจ้าของร้านก่อน")
    return account


def _set_owner_cookie(request: Request, response: Response, token: str) -> None:
    # "lax" rather than "strict": the owner arrives back here from the provider's
    # own page, and a strict cookie would not be sent on that first navigation.
    response.set_cookie(OWNER_COOKIE, token, max_age=owner_auth.SESSION_LIFETIME, httponly=True,
                        secure=_secure(request), samesite="lax", path="/")


@app.get("/api/owner/auth/{provider}/start")
def owner_login_start(provider: str, request: Request, mode: str = "login"):
    """Begin a sign-in, or — with mode=link — bind a provider to the open shop."""
    client_id, client_secret = _provider_credentials(provider)
    if not client_id or not client_secret:
        raise HTTPException(503, f"ยังไม่ได้เปิดใช้การเข้าสู่ระบบด้วย {OWNER_CHANNELS[provider]}")
    slug, staff_id = "", None
    if mode == "link":
        # Only the owner already signed into this shop may hand it to an account.
        staff = require_staff(request, roles=("owner",))
        slug = CURRENT_SHOP.get()
        if slug in (MAIN_SHOP, DEMO_SHOP) or not shops.get_shop(DB_PATH, slug):
            raise HTTPException(409, "ร้านนี้ผูกบัญชีไม่ได้ ร้านหลักตั้งค่าที่เซิร์ฟเวอร์")
        staff_id = staff["id"]
    try:
        handshake = owner_auth.start_login(DB_PATH, provider=provider, mode=mode, slug=slug,
                                           staff_id=staff_id)
    except owner_auth.OwnerAuthError as exc:
        raise HTTPException(exc.status, exc.message) from exc
    return RedirectResponse(owner_auth.authorize_url(
        provider, client_id=client_id, redirect_uri=_owner_redirect_uri(request, provider),
        state=handshake["state"], nonce=handshake["nonce"]), status_code=302)


MEMBER_COOKIE = "poswai_member"


@app.get("/api/members/auth/{provider}/start")
def member_login_start(provider: str, request: Request):
    """A customer signing in with the account they already have.

    It shares the owner's callback, and so the redirect URI already registered
    with each provider; what tells the two apart is the mode on the state row.
    """
    client_id, client_secret = _provider_credentials(provider)
    if not client_id or not client_secret:
        raise HTTPException(503, f"ยังไม่ได้เปิดใช้การเข้าสู่ระบบด้วย {OWNER_CHANNELS[provider]}")
    if len(TABLE_QR_SECRET) < 32:
        raise HTTPException(503, "ยังไม่ได้ตั้งค่ากุญแจของร้าน")
    try:
        handshake = owner_auth.start_login(DB_PATH, provider=provider, mode="member",
                                           slug=CURRENT_SHOP.get())
    except owner_auth.OwnerAuthError as exc:
        raise HTTPException(exc.status, exc.message) from exc
    return RedirectResponse(owner_auth.authorize_url(
        provider, client_id=client_id, redirect_uri=_owner_redirect_uri(request, provider),
        state=handshake["state"], nonce=handshake["nonce"]), status_code=302)


def _finish_member_login(request: Request, slug: str, identity: dict) -> RedirectResponse:
    """Hand the customer their card back on the shop's own page.

    The provider's callback carries no shop, so the slug recorded when the
    sign-in began is what says whose member list this is."""
    shop_token = CURRENT_SHOP.set(slug)
    try:
        with closing(connect_db()) as conn, conn:
            customer_id = upsert_social_customer(
                conn, branch_id=1, provider=identity["provider"],
                subject=identity["external_id"], display_name=identity.get("display_name", ""))
        member_token = _mint_member_token(customer_id)
    finally:
        CURRENT_SHOP.reset(shop_token)
    response = RedirectResponse(f"/?shop={slug}&member=in", status_code=303)
    response.set_cookie(MEMBER_COOKIE, member_token, max_age=MEMBER_TOKEN_TTL_SECONDS,
                        httponly=True, secure=_secure(request), samesite="lax", path="/")
    return response


@app.get("/api/staff/auth/{provider}/start")
def staff_login_start(provider: str, request: Request, mode: str = "login"):
    """Sign a member of staff in with their own account, or — with mode=link —
    bind that account to the staff record already signed in here.

    Binding needs the PIN first, so an account only ever reaches the till that
    its owner could already open."""
    client_id, client_secret = _provider_credentials(provider)
    if not client_id or not client_secret:
        raise HTTPException(503, f"ยังไม่ได้เปิดใช้การเข้าสู่ระบบด้วย {OWNER_CHANNELS[provider]}")
    slug = CURRENT_SHOP.get()
    if slug == DEMO_SHOP:
        raise HTTPException(403, "ร้านตัวอย่างไม่มีบัญชีพนักงาน")
    staff_id = require_staff(request)["id"] if mode == "link" else None
    try:
        handshake = owner_auth.start_login(DB_PATH, provider=provider,
                                           mode="staff_link" if mode == "link" else "staff",
                                           slug=slug, staff_id=staff_id)
    except owner_auth.OwnerAuthError as exc:
        raise HTTPException(exc.status, exc.message) from exc
    return RedirectResponse(owner_auth.authorize_url(
        provider, client_id=client_id, redirect_uri=_owner_redirect_uri(request, provider),
        state=handshake["state"], nonce=handshake["nonce"]), status_code=302)


def _staff_landing(slug: str, outcome: str) -> RedirectResponse:
    return RedirectResponse(f"/?shop={slug}&{outcome}", status_code=303)


def _finish_staff_login(request: Request, pending: dict, identity: dict) -> RedirectResponse:
    """Finish a staff sign-in that went out through a provider.

    The callback carries no shop, so the slug recorded when it began is what
    says whose till this is."""
    slug = pending["slug"] or MAIN_SHOP
    social_id = f"{identity['provider']}:{identity['external_id']}"
    linking = pending["mode"] == "staff_link"
    shop_token = CURRENT_SHOP.set(slug)
    try:
        with closing(connect_db()) as conn, conn:
            conn.row_factory = sqlite3.Row
            held = conn.execute("SELECT id FROM staffs WHERE social_id=?", (social_id,)).fetchone()
            if linking:
                if held and held["id"] != int(pending["staff_id"] or 0):
                    return _staff_landing(slug, "staff_error=taken")
                conn.execute("UPDATE staffs SET social_id=? WHERE id=?",
                             (social_id, int(pending["staff_id"] or 0)))
                return _staff_landing(slug, "staff=linked")
            if not held:
                return _staff_landing(slug, "staff_error=unlinked")
            row = conn.execute("SELECT id,is_active FROM staffs WHERE id=?", (held["id"],)).fetchone()
            if not row["is_active"]:
                return _staff_landing(slug, "staff_error=inactive")
            today = datetime.datetime.now(BANGKOK_TZ).date().isoformat()
            if conn.execute("SELECT 1 FROM staff_shifts WHERE staff_id=? AND work_date=? AND pos_pin_locked=1",
                            (row["id"], today)).fetchone():
                return _staff_landing(slug, "staff_error=locked")
            response = _staff_landing(slug, "staff=in")
            # "lax", not the PIN login's "strict": the browser arrives here from
            # the provider's own page, and a strict cookie would not come back.
            _open_session(request, response, conn, row["id"], samesite="lax")
    finally:
        CURRENT_SHOP.reset(shop_token)
    _remember_shop(request, response, slug)
    return response


@app.get("/api/owner/auth/{provider}/callback")
def owner_login_callback(provider: str, request: Request, code: str = "", state: str = "",
                         error: str = ""):
    """Finish a sign-in. Nothing here is believed without the state row and the
    provider's own verification of the identity token."""
    if provider not in owner_auth.PROVIDERS:
        return _owner_failure("provider_unknown")
    if error:
        return _owner_failure("denied")
    client_id, client_secret = _provider_credentials(provider)
    try:
        pending = owner_auth.consume_state(DB_PATH, provider=provider, state=state)
        identity = owner_auth.identity_from_code(
            provider, code=code, nonce=pending["nonce"], client_id=client_id,
            client_secret=client_secret, redirect_uri=_owner_redirect_uri(request, provider))
        account = owner_auth.upsert_account(DB_PATH, identity)
    except owner_auth.OwnerAuthError as exc:
        return _owner_failure(exc.code)
    if pending["mode"] in ("staff", "staff_link"):
        return _finish_staff_login(request, pending, identity)
    if pending["mode"] == "member":
        return _finish_member_login(request, pending["slug"] or MAIN_SHOP, identity)
    if pending["mode"] == "link":
        record = shops.get_shop(DB_PATH, pending["slug"])
        if not record or record["status"] != "active" or not pending["staff_id"]:
            return _owner_failure("shop")
        owner_auth.link_shop(DB_PATH, account_id=account["id"], slug=pending["slug"],
                             staff_id=int(pending["staff_id"]))
        response = RedirectResponse(f"/?shop={pending['slug']}&owner=linked", status_code=303)
    else:
        linked = owner_auth.account_shops(DB_PATH, account["id"])
        if not linked:
            # A new owner: the sign-up form opens with the account already bound.
            response = RedirectResponse("/?owner=new", status_code=303)
        elif len(linked) == 1:
            response = RedirectResponse(f"/?shop={linked[0]['slug']}&owner=enter", status_code=303)
        else:
            response = RedirectResponse("/?owner=choose", status_code=303)
    token, _ = owner_auth.open_session(DB_PATH, account["id"])
    _set_owner_cookie(request, response, token)
    return response


@app.get("/api/owner/session")
def owner_session(request: Request):
    """Who is signed in and which shops they may open."""
    account = _owner_account(request)
    return {"account": {"id": account["id"], "provider": account["provider"],
                        "email": account["email"], "name": account["display_name"]},
            "shops": [{"slug": row["slug"], "name": row["name"], "role": row["role"],
                       "status": row["status"], "trial_ends_at": row["trial_ends_at"]}
                      for row in owner_auth.account_shops(DB_PATH, account["id"])]}


class OwnerShopChoice(BaseModel):
    slug: str


@app.post("/api/owner/enter")
def owner_enter_shop(req: OwnerShopChoice, request: Request, response: Response):
    """Open a shop from an owner account: this is where the staff session starts."""
    account = _owner_account(request)
    slug = req.slug.strip().lower()
    membership = owner_auth.shop_membership(DB_PATH, account_id=account["id"], slug=slug)
    if not membership:
        raise HTTPException(403, "บัญชีนี้ไม่ได้เป็นเจ้าของร้านนี้")
    record = shops.get_shop(DB_PATH, slug)
    if not record:
        raise HTTPException(404, "ไม่พบร้านนี้")
    if record["status"] != "active":
        raise HTTPException(403, _out_of_service_text(record))
    CURRENT_SHOP.set(slug)
    with closing(connect_db()) as conn, conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT id,branch_id,name,role,is_active FROM staffs WHERE id=?",
                           (membership["staff_id"],)).fetchone()
        if not row or not row["is_active"]:
            raise HTTPException(409, "บัญชีพนักงานของเจ้าของร้านนี้ถูกปิดใช้งาน "
                                     "กรุณาเข้าด้วยรหัสร้านและ PIN แล้วผูกบัญชีใหม่")
        expires = _open_session(request, response, conn, row["id"])
    _remember_shop(request, response, slug)
    return {"shop": {"slug": slug, "name": record["name"]}, "staff_id": row["id"],
            "branch_id": row["branch_id"], "name": row["name"], "role": row["role"],
            "expires_at": expires}


@app.post("/api/owner/logout")
def owner_logout(request: Request, response: Response):
    owner_auth.close_session(DB_PATH, request.cookies.get(OWNER_COOKIE, ""))
    response.delete_cookie(OWNER_COOKIE, path="/")
    return {"status": "logged_out"}


@app.get("/api/shop/owner-accounts")
def list_shop_owner_accounts(request: Request):
    """The accounts that can open this shop, for the owner's own settings page."""
    require_staff(request, roles=("owner",))
    slug = CURRENT_SHOP.get()
    hosted = slug not in (MAIN_SHOP, DEMO_SHOP) and bool(shops.get_shop(DB_PATH, slug))
    channels = {name: bool(_provider_credentials(name)[0] and _provider_credentials(name)[1])
                for name in owner_auth.PROVIDERS}
    return {"slug": slug, "linkable": hosted, "channels": channels,
            "accounts": [{"id": row["id"], "provider": row["provider"], "email": row["email"],
                          "name": row["display_name"], "linked_at": row["linked_at"]}
                         for row in (owner_auth.shop_accounts(DB_PATH, slug) if hosted else [])]}


@app.delete("/api/shop/owner-accounts/{account_id}")
def remove_shop_owner_account(account_id: int, request: Request):
    """Unlink an account. The shop code and PIN keep working either way."""
    require_staff(request, roles=("owner",))
    slug = CURRENT_SHOP.get()
    if not any(row["id"] == account_id for row in owner_auth.shop_accounts(DB_PATH, slug)):
        raise HTTPException(404, "บัญชีนี้ไม่ได้ผูกกับร้านนี้")
    owner_auth.unlink_shop(DB_PATH, account_id=account_id, slug=slug)
    return {"status": "unlinked", "account_id": account_id}


# =====================================================================
# The monthly service fee a hosted shop pays ZZAX Studio
class ServicePayment(BaseModel):
    event_id: str
    amount: float
    slip_image: str
    months: int = 1


class AdminPaymentEntry(BaseModel):
    event_id: str
    amount: float
    months: int = 1
    note: str = ""


@app.get("/api/billing")
def read_billing(request: Request):
    """What this shop owes, for the notice the app shows every signed-in user."""
    staff = require_staff(request)
    state = current_billing()
    body = {"billing": state, "price": MONTHLY_PRICE,
            "service_promptpay_id": SERVICE_PROMPTPAY_ID if state["applicable"] else "",
            "slip_check_ready": bool(SERVICE_EASYSLIP_API_KEY),
            "may_pay": staff["role"] in ("owner", "manager")}
    if state["applicable"] and body["may_pay"]:
        body["payments"] = billing.payment_history(DB_PATH, CURRENT_SHOP.get())
    return body


@app.post("/api/billing/pay")
def pay_service_fee(req: ServicePayment, request: Request):
    """Close one month of service against a slip paid to ZZAX Studio's account."""
    require_staff(request, roles=("owner", "manager"))
    slug = CURRENT_SHOP.get()
    if not current_billing()["applicable"]:
        raise HTTPException(409, "ร้านนี้ไม่มีค่าบริการรายเดือนในระบบ")
    if not re.fullmatch(r"[A-Za-z0-9_:-]{4,80}", req.event_id):
        raise HTTPException(400, "รหัสรายการชำระเงินไม่ถูกต้อง")
    if req.months < 1 or req.months > billing.MAX_MONTHS:
        raise HTTPException(400, f"ชำระล่วงหน้าได้ 1–{billing.MAX_MONTHS} เดือน")
    if not SERVICE_PROMPTPAY_ID:
        raise HTTPException(503, "ยังไม่ได้ตั้งค่าบัญชีพร้อมเพย์ของผู้ให้บริการ กรุณาติดต่อ ZZAX Studio")
    if not SERVICE_EASYSLIP_API_KEY:
        raise HTTPException(503, "ยังไม่ได้เปิดระบบตรวจสลิปของผู้ให้บริการ "
                                 "กรุณาส่งสลิปให้ทีมงาน ZZAX Studio ยืนยันให้")
    expected = round(MONTHLY_PRICE * req.months, 2)
    if not math.isfinite(req.amount) or round(req.amount, 2) != expected:
        raise HTTPException(409, f"ยอดโอนต้องเท่ากับ {expected:,.2f} บาท สำหรับ {req.months} เดือน")
    try:
        slip_reference = verify_bank_slip(req.slip_image, expected, SERVICE_EASYSLIP_API_KEY)
    except SlipVerificationError as exc:
        raise HTTPException(422, str(exc)) from exc
    try:
        result = billing.record_payment(DB_PATH, slug, amount=expected, method="promptpay_slip",
                                        event_id=req.event_id, confirmed_by="easyslip",
                                        slip_reference=slip_reference, months=req.months,
                                        price=MONTHLY_PRICE)
    except ShopError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    return {**result, "slip_reference": slip_reference}


# =====================================================================
# The ZZAX Studio billing page. It is opened with POSWAI_ADMIN_KEY, never with a
# shop's staff account, and it can read every shop but never a shop's own records.
@app.get("/admin", response_class=HTMLResponse)
def serve_admin_page():
    return (Path(__file__).parent / "admin.html").read_text(encoding="utf-8")


@app.get("/api/admin/shops")
def admin_list_shops(request: Request, include_closed: bool = False):
    require_admin_key(request)
    return {"price": MONTHLY_PRICE, "service_promptpay_id": SERVICE_PROMPTPAY_ID,
            "today": billing.today_date().isoformat(), "warn_days": billing.WARN_DAYS,
            "shops": billing.all_shops_billing(DB_PATH, price=MONTHLY_PRICE,
                                               include_closed=include_closed),
            "revenue": billing.monthly_revenue(DB_PATH)}


@app.get("/api/admin/shops/{slug}/payments")
def admin_shop_payments(slug: str, request: Request):
    require_admin_key(request)
    slug = slug.strip().lower()
    if not shops.get_shop(DB_PATH, slug):
        raise HTTPException(404, "ไม่พบร้านนี้")
    return {"slug": slug, "payments": billing.payment_history(DB_PATH, slug),
            "billing": billing.billing_state(DB_PATH, slug, price=MONTHLY_PRICE)}


@app.post("/api/admin/shops/{slug}/payments")
def admin_confirm_payment(slug: str, req: AdminPaymentEntry, request: Request):
    """Record a transfer the team checked by hand and move the due date on."""
    require_admin_key(request)
    slug = slug.strip().lower()
    if not shops.get_shop(DB_PATH, slug):
        raise HTTPException(404, "ไม่พบร้านนี้")
    if not re.fullmatch(r"[A-Za-z0-9_:-]{4,80}", req.event_id):
        raise HTTPException(400, "รหัสรายการชำระเงินไม่ถูกต้อง")
    if len(req.note) > 300:
        raise HTTPException(400, "บันทึกช่วยจำยาวเกิน 300 ตัวอักษร")
    try:
        return billing.record_payment(DB_PATH, slug, amount=req.amount, method="manual",
                                      event_id=req.event_id, confirmed_by="zzax-admin",
                                      note=req.note.strip(), months=req.months,
                                      price=MONTHLY_PRICE)
    except ShopError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


class AdminGrant(BaseModel):
    event_id: str
    days: int = 7
    reason: str


class AdminShopStatus(BaseModel):
    status: str
    reason: str = ""


@app.post("/api/admin/shops/{slug}/grants")
def admin_grant_free_days(slug: str, req: AdminGrant, request: Request):
    """Give a shop free days without pretending money arrived.

    Compensation used to have to go through "payment received", which inflated the
    revenue figures. A grant moves the date and is left out of every total.
    """
    require_admin_key(request)
    slug = slug.strip().lower()
    if not shops.get_shop(DB_PATH, slug):
        raise HTTPException(404, "ไม่พบร้านนี้")
    if not re.fullmatch(r"[A-Za-z0-9_:-]{4,80}", req.event_id):
        raise HTTPException(400, "รหัสรายการไม่ถูกต้อง")
    if not 3 <= len(req.reason.strip()) <= 300:
        raise HTTPException(400, "เหตุผลต้องยาว 3–300 ตัวอักษร")
    try:
        return billing.record_payment(DB_PATH, slug, amount=0.0, method=billing.GRANT,
                                      event_id=req.event_id, confirmed_by="zzax-admin",
                                      note=req.reason.strip(), days=req.days, price=MONTHLY_PRICE)
    except ShopError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@app.post("/api/admin/shops/{slug}/status")
def admin_set_shop_status(slug: str, req: AdminShopStatus, request: Request):
    """Suspend a shop, close it for good, or put it back in service.

    None of these touch the shop's database file. "closed" keeps every record and
    can be undone; it exists so that nothing has to be deleted to end a contract.
    """
    require_admin_key(request)
    slug = slug.strip().lower()
    shop = shops.get_shop(DB_PATH, slug)
    if not shop:
        raise HTTPException(404, "ไม่พบร้านนี้")
    if req.status not in shops.STATUSES:
        raise HTTPException(400, "สถานะร้านไม่ถูกต้อง")
    if req.status != "active" and not 3 <= len(req.reason.strip()) <= 200:
        raise HTTPException(400, "ต้องระบุเหตุผลยาว 3–200 ตัวอักษร")
    try:
        updated = shops.set_status(DB_PATH, slug, req.status, req.reason.strip())
    except ShopError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    return {"slug": slug, "status": updated["status"], "status_reason": updated["status_reason"],
            "database_file": str(shops.shop_db_path(DB_PATH, slug).name), "data_kept": True,
            "billing": billing.billing_state(DB_PATH, slug, price=MONTHLY_PRICE)}


def _owner_line_recipients(slug: str) -> list[str]:
    """The LINE accounts of that shop's owners and managers, read and nothing else."""
    token = CURRENT_SHOP.set(slug)
    try:
        with closing(connect_db()) as conn:
            return [row[0] for row in conn.execute(
                "SELECT DISTINCT line_user_id FROM staffs WHERE role IN ('owner','manager') "
                "AND is_active=1 AND line_user_id IS NOT NULL AND line_user_id<>''")]
    finally:
        CURRENT_SHOP.reset(token)


def _reminder_text(shop: dict) -> str:
    days = shop["days_left"]
    when = (f"เหลืออีก {days} วัน (ครบกำหนด {shop['due_date']})" if days >= 0
            else f"เลยกำหนดมาแล้ว {abs(days)} วัน (ครบกำหนด {shop['due_date']})")
    tail = ("ตอนนี้ร้านรับออเดอร์ใหม่ไม่ได้จนกว่าจะชำระ ข้อมูลของร้านยังอยู่ครบ"
            if days < 0 else "ชำระก่อนครบกำหนดเพื่อให้ร้านใช้งานต่อได้ไม่สะดุด")
    return (f"แจ้งค่าบริการ POS WAI ร้าน {shop['name']}\n{when}\n"
            f"ค่าบริการ {MONTHLY_PRICE:,.0f} บาทต่อเดือน\n{tail}\n"
            "ชำระได้ที่หน้าแอป กดแถบแจ้งเตือนด้านบน แล้วแนบสลิป")


@app.post("/api/admin/reminders")
def admin_send_due_reminders(request: Request):
    """Queue a LINE reminder for every shop near or past its due date.

    The push goes to the owner's linked LINE account when there is one. A shop with
    nobody linked is reported back with its phone number and the exact message, for
    the team to send by hand. One shop failing never stops the rest.
    """
    require_admin_key(request)
    listed = [shop for shop in billing.all_shops_billing(DB_PATH, price=MONTHLY_PRICE)
              if shop["in_service"] and shop["state"] in (billing.STATE_DUE_SOON, billing.STATE_OVERDUE)]
    queued, manual, failed = [], [], []
    for shop in listed:
        text = _reminder_text(shop)
        try:
            recipients = _owner_line_recipients(shop["slug"])
        except (sqlite3.Error, OSError) as exc:
            failed.append({"slug": shop["slug"], "name": shop["name"], "error": type(exc).__name__})
            continue
        if not recipients:
            manual.append({"slug": shop["slug"], "name": shop["name"], "phone": shop["phone"],
                           "days_left": shop["days_left"], "message": text})
            continue
        try:
            # The outbox the background worker drains lives in the main database, so
            # the reminders are queued there even though the recipients come from the
            # shop's own staff records.
            with closing(connect_db()) as conn, conn:
                for recipient in recipients:
                    enqueue_line_notification(conn, f"billing:{shop['slug']}:{shop['due_date']}",
                                              recipient, 1, {"type": "text", "text": text})
        except sqlite3.Error as exc:
            failed.append({"slug": shop["slug"], "name": shop["name"], "error": type(exc).__name__})
            continue
        queued.append({"slug": shop["slug"], "name": shop["name"], "recipients": len(recipients),
                       "days_left": shop["days_left"]})
    return {"due": len(listed), "queued": queued, "manual": manual, "failed": failed,
            "line_ready": bool(LINE_CHANNEL_ACCESS_TOKEN)}


@app.get("/api/admin/revenue")
def admin_revenue(request: Request, months: int = 12):
    require_admin_key(request)
    return {"price": MONTHLY_PRICE, "months": billing.monthly_revenue(DB_PATH, months=months)}


def _csv_response(filename: str, header: list[str], rows: list[list]) -> Response:
    """UTF-8 with a BOM, because Excel in Thai reads a plain UTF-8 CSV as gibberish."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    return Response("﻿" + buffer.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"',
                             "Cache-Control": "no-store"})


@app.get("/api/admin/export/shops.csv")
def admin_export_shops(request: Request):
    require_admin_key(request)
    shops_listed = billing.all_shops_billing(DB_PATH, price=MONTHLY_PRICE, include_closed=True)
    rows = [[shop["slug"], shop["name"], shop["owner_name"], shop["phone"], shop["status"],
             shop["state"], shop["due_date"], shop["days_left"], "ใช่" if shop["on_trial"] else "ไม่",
             shop["payments"], f"{shop['paid_total']:.2f}", shop["grants"], shop["created_at"]]
            for shop in shops_listed]
    return _csv_response("poswai-shops.csv",
                         ["รหัสร้าน", "ชื่อร้าน", "เจ้าของ", "เบอร์โทร", "สถานะร้าน", "สถานะการจ่าย",
                          "ใช้ได้ถึง", "เหลือ (วัน)", "ยังทดลองใช้", "จ่ายแล้ว (ครั้ง)",
                          "ยอดรวม (บาท)", "แถมฟรี (ครั้ง)", "เปิดร้านเมื่อ"], rows)


@app.get("/api/admin/export/payments.csv")
def admin_export_payments(request: Request):
    require_admin_key(request)
    names = {shop["slug"]: shop["name"] for shop
             in billing.all_shops_billing(DB_PATH, price=MONTHLY_PRICE, include_closed=True)}
    rows = []
    for slug, name in names.items():
        for entry in billing.payment_history(DB_PATH, slug, limit=200):
            rows.append([entry["created_at"], slug, name, f"{entry['amount']:.2f}", entry["method"],
                         entry["confirmed_by"], entry["slip_reference"] or "",
                         entry["period_start"], entry["period_end"], entry["note"]])
    rows.sort(key=lambda row: str(row[0]), reverse=True)
    return _csv_response("poswai-payments.csv",
                         ["เวลาบันทึก (UTC)", "รหัสร้าน", "ชื่อร้าน", "ยอด (บาท)", "ช่องทาง",
                          "ผู้ยืนยัน", "รหัสสลิป", "เริ่มรอบ", "ถึงวันที่", "บันทึกช่วยจำ"], rows)


# =====================================================================
# Shop members: customers join with LINE and collect points
class MemberJoin(BaseModel):
    branch_id: int = 1
    line_id_token: str
    display_name: Optional[str] = None
    phone: Optional[str] = None
    marketing_opt_in: Optional[bool] = None


def _member_card(conn: sqlite3.Connection, customer_id: int) -> dict:
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT id,display_name,phone,points,completed_orders,lifetime_cents,"
                       "marketing_opt_in,created_at FROM crm_customers WHERE id=?", (customer_id,)).fetchone()
    history = conn.execute("SELECT change,reason,created_at FROM crm_point_ledger WHERE customer_id=? "
                           "ORDER BY id DESC LIMIT 10", (customer_id,)).fetchall()
    return {"member_id": row["id"], "display_name": row["display_name"], "phone": row["phone"],
            "points": row["points"], "completed_orders": row["completed_orders"],
            "lifetime_amount": row["lifetime_cents"] / 100, "marketing_opt_in": bool(row["marketing_opt_in"]),
            "member_since": row["created_at"], "point_baht": POINT_BAHT,
            "history": [dict(item) for item in history]}


@app.post("/api/members/me")
def join_or_read_membership(req: MemberJoin):
    if req.branch_id < 1:
        raise HTTPException(400, "สาขาไม่ถูกต้อง")
    if req.display_name is not None and len(req.display_name.strip()) > 100:
        raise HTTPException(400, "ชื่อยาวเกินไป")
    phone = re.sub(r"[\s-]", "", req.phone or "")
    if phone and not re.fullmatch(r"\+?\d{9,15}", phone):
        raise HTTPException(400, "เบอร์โทรไม่ถูกต้อง")
    line_id = verify_liff_id_token(req.line_id_token, LINE_LOGIN_CHANNEL_ID)
    with closing(connect_db()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        if not conn.execute("SELECT 1 FROM branches WHERE id=?", (req.branch_id,)).fetchone():
            raise HTTPException(404, "ไม่พบสาขานี้")
        customer_id = upsert_customer(conn, branch_id=req.branch_id, source="line", external_id=line_id,
                                      display_name=(req.display_name or "").strip(), phone=phone,
                                      marketing_opt_in=req.marketing_opt_in)
        return _member_card(conn, customer_id)


class CounterMember(BaseModel):
    branch_id: int = 1
    display_name: str
    phone: str
    marketing_opt_in: bool = False


# A membership unlocks nothing except its own points, so it is not a staff
# session and gets no session cookie. The phone that signed in keeps the token,
# and it lasts about as long as a paper stamp card would before the customer
# has to give their name and number again.
MEMBER_TOKEN_TTL_SECONDS = 180 * 24 * 3600


def _member_signature(payload: bytes) -> str:
    return hmac.new(TABLE_QR_SECRET.encode(), b"member:" + payload, hashlib.sha256).hexdigest()


def _mint_member_token(member_id: int) -> str:
    if len(TABLE_QR_SECRET) < 32:
        raise HTTPException(503, "ยังไม่ได้ตั้งค่ากุญแจของร้าน")
    payload = json.dumps({"m": member_id, "e": int(time.time()) + MEMBER_TOKEN_TTL_SECONDS,
                          "s": CURRENT_SHOP.get()},
                         sort_keys=True, separators=(",", ":")).encode()
    encoded = base64.urlsafe_b64encode(payload).rstrip(b"=").decode()
    return encoded + "." + _member_signature(payload)


def _signed_in_member(request: Request) -> int:
    token = request.headers.get("x-member-token", "") or request.cookies.get(MEMBER_COOKIE, "")
    if len(TABLE_QR_SECRET) < 32 or len(token) > 512 or "." not in token:
        raise HTTPException(401, "กรุณาเข้าสู่ระบบลูกค้าอีกครั้ง")
    try:
        encoded, signature = token.split(".", 1)
        payload = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        data = json.loads(payload)
        if (not hmac.compare_digest(signature, _member_signature(payload))
                or data["e"] < int(time.time())
                or data.get("s", MAIN_SHOP) != CURRENT_SHOP.get()):
            raise ValueError("Invalid member token")
        return int(data["m"])
    except (ValueError, KeyError, TypeError):
        raise HTTPException(401, "กรุณาเข้าสู่ระบบลูกค้าอีกครั้ง")


def _signed_in_card(conn: sqlite3.Connection, member_id: int) -> dict:
    """The card plus what keeps the customer signed in on this phone."""
    return {**_member_card(conn, member_id), "token": _mint_member_token(member_id)}


def _clean_member_details(display_name: str, phone: str) -> tuple:
    name = display_name.strip()
    phone = re.sub(r"[\s-]", "", phone)
    if not name or len(name) > 100:
        raise HTTPException(400, "กรุณากรอกชื่อลูกค้า")
    if not re.fullmatch(r"\+?\d{9,15}", phone):
        raise HTTPException(400, "เบอร์โทรไม่ถูกต้อง")
    return name, phone


def _add_member(branch_id: int, display_name: str, phone: str, marketing_opt_in: bool) -> dict:
    name, phone = _clean_member_details(display_name, phone)
    with closing(connect_db()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM crm_customers WHERE branch_id=? AND phone=?",
                        (branch_id, phone)).fetchone():
            raise HTTPException(409, "เบอร์นี้เป็นสมาชิกอยู่แล้ว")
        cur = conn.execute("INSERT INTO crm_customers(branch_id,display_name,phone,marketing_opt_in) "
                           "VALUES(?,?,?,?)", (branch_id, name, phone, int(marketing_opt_in)))
        return _member_card(conn, cur.lastrowid)


@app.post("/api/members")
def register_member_at_counter(req: CounterMember, request: Request):
    """Staff sign a walk-in customer up at the till, for customers who do not use LINE."""
    require_staff(request, roles=("cashier", "manager", "owner"), branch_id=req.branch_id)
    return _add_member(req.branch_id, req.display_name, req.phone, req.marketing_opt_in)


class SelfMember(CounterMember):
    table_no: str


@app.post("/api/members/self")
def register_member_from_table(req: SelfMember, request: Request):
    """A guest at a table signs themselves up, with no LINE account needed.

    Membership used to require a LINE id token, which a phone that simply
    scanned the table sticker does not have; the customer was pushed to the
    shop's own staff sign-in and reasonably gave up. Being at the table is
    proof enough to leave a name and a number.

    Members have no password of any kind, so a customer who signed up last
    week has nothing to log in with. Giving their own name and their own
    number back is what identifies them, and the card comes up again. A
    number on the list under a different name is refused rather than handed
    over, so knowing only someone's phone does not show you their points.
    """
    require_table_or_staff(request, req.branch_id, req.table_no.strip())
    name, phone = _clean_member_details(req.display_name, req.phone)
    with closing(connect_db()) as conn:
        row = conn.execute("SELECT id,display_name FROM crm_customers WHERE branch_id=? AND phone=?",
                           (req.branch_id, phone)).fetchone()
        if row:
            if _same_person(row[1], name):
                return _signed_in_card(conn, row[0])
            raise HTTPException(409, "เบอร์นี้เป็นสมาชิกอยู่แล้วในชื่ออื่น แจ้งพนักงานเพื่อดูแต้มได้เลย")
    card = _add_member(req.branch_id, name, phone, req.marketing_opt_in)
    return {**card, "token": _mint_member_token(card["member_id"])}


def _same_person(stored: str, given: str) -> bool:
    """A name typed again by its owner, allowing for spacing and case."""
    def squash(text):
        return re.sub(r"\s+", "", text or "").casefold()
    return squash(stored) == squash(given)


class MemberLogin(BaseModel):
    branch_id: int = 1
    display_name: str
    phone: str


@app.post("/api/members/login")
def sign_in_member(req: MemberLogin, request: Request):
    """The customer's own door, next to the owner's and the staff's.

    Everyone who sat down and signed up at a table had nowhere to go
    afterwards: the only sign-in on offer was the shop's own, for its owner
    and its staff, which is not theirs and which they cannot pass. A customer
    has no password to type, so their own name and their own number are what
    they give, and the phone keeps the card from then on.
    """
    name, phone = _clean_member_details(req.display_name, req.phone)
    with closing(connect_db()) as conn:
        row = conn.execute("SELECT id,display_name FROM crm_customers WHERE branch_id=? AND phone=?",
                           (req.branch_id, phone)).fetchone()
        if not row or not _same_person(row[1], name):
            raise HTTPException(404, "ไม่พบสมาชิกที่ชื่อและเบอร์นี้ สมัครได้ที่โต๊ะ หรือแจ้งพนักงาน")
        return _signed_in_card(conn, row[0])


@app.post("/api/members/logout")
def sign_out_member(response: Response):
    response.delete_cookie(MEMBER_COOKIE, path="/")
    return {"ok": True}


@app.get("/api/members/card")
def read_member_card(request: Request):
    """What the phone asks for when the app opens again days later."""
    member_id = _signed_in_member(request)
    with closing(connect_db()) as conn:
        if not conn.execute("SELECT 1 FROM crm_customers WHERE id=?", (member_id,)).fetchone():
            raise HTTPException(401, "กรุณาเข้าสู่ระบบลูกค้าอีกครั้ง")
        return _member_card(conn, member_id)


class PointChange(BaseModel):
    branch_id: int = 1
    phone: str
    spend_amount: Optional[float] = None
    redeem_points: Optional[int] = None
    note: str = ""


@app.post("/api/members/points")
def change_member_points(req: PointChange, request: Request):
    staff = require_staff(request, roles=("cashier", "manager", "owner"), branch_id=req.branch_id)
    phone = re.sub(r"[\s-]", "", req.phone)
    if not re.fullmatch(r"\+?\d{9,15}", phone):
        raise HTTPException(400, "เบอร์โทรไม่ถูกต้อง")
    if (req.spend_amount is None) == (req.redeem_points is None):
        raise HTTPException(400, "เลือกสะสมแต้มจากยอดซื้อ หรือใช้แต้ม อย่างใดอย่างหนึ่ง")
    if req.spend_amount is not None and (not math.isfinite(req.spend_amount) or not 0 < req.spend_amount <= 1_000_000):
        raise HTTPException(400, "ยอดซื้อไม่ถูกต้อง")
    if req.redeem_points is not None and not 0 < req.redeem_points <= 1_000_000:
        raise HTTPException(400, "จำนวนแต้มไม่ถูกต้อง")
    if len(req.note) > 200:
        raise HTTPException(400, "หมายเหตุยาวเกินไป")
    with closing(connect_db()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute("SELECT id,points FROM crm_customers WHERE branch_id=? AND phone=?",
                            (req.branch_id, phone)).fetchall()
        if not rows:
            raise HTTPException(404, "ไม่พบสมาชิกเบอร์นี้ สมัครสมาชิกให้ลูกค้าก่อน หรือให้ลูกค้าสมัครเองผ่าน LINE")
        if len(rows) > 1:
            raise HTTPException(409, "มีสมาชิกใช้เบอร์นี้มากกว่าหนึ่งคน กรุณาตรวจในหน้าสมาชิก")
        customer_id, balance = rows[0]
        if req.spend_amount is not None:
            change, reason = int(req.spend_amount // POINT_BAHT), f"ซื้อ {req.spend_amount:,.2f} บาท"
            if change == 0:
                raise HTTPException(400, f"ยอดซื้อต้องถึง {POINT_BAHT} บาทจึงได้แต้ม")
        else:
            if req.redeem_points > balance:
                raise HTTPException(409, f"แต้มไม่พอ มีอยู่ {balance} แต้ม")
            change, reason = -req.redeem_points, "ใช้แต้ม"
        if req.note.strip():
            reason += " · " + req.note.strip()
        conn.execute("UPDATE crm_customers SET points=points+?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                     (change, customer_id))
        conn.execute("INSERT INTO crm_point_ledger(customer_id,change,reason,staff_id) VALUES(?,?,?,?)",
                     (customer_id, change, reason, staff["id"]))
        return {"change": change, **_member_card(conn, customer_id)}


if __name__ == "__main__":
    print("POS WAI Enterprise V3 Database & Leave/Commission Engine initialized successfully.")
