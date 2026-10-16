"""Shop registry for the hosted POS WAI service.

Every shop keeps its own SQLite file, so one shop's staff, sales and customers
can never appear in another shop's queries. The registry only records which
shops exist, how to reach their file and the public settings they chose.

The original single-shop database stays where it was and is the shop "main".
"demo" is a read-only sample shop whose pages use the built-in sample data.
"""

import datetime
import hashlib
import re
import sqlite3
import time
from contextlib import closing
from pathlib import Path

MAIN_SHOP = "main"
DEMO_SHOP = "demo"
SLUG_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9-]{1,28}[a-z0-9])")
RESERVED_SLUGS = frozenset({
    MAIN_SHOP, DEMO_SHOP, "api", "admin", "www", "assets", "static", "app", "poswai", "pos",
    "login", "signup", "help", "support", "shop", "shops", "test", "root", "system",
})
TRIAL_DAYS = 30
SIGNUPS_PER_HOUR = 3
SIGNUPS_PER_DAY = 10


class ShopError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def registry_path(main_db: Path) -> Path:
    return main_db.parent / "shops.db"


def shop_db_path(main_db: Path, slug: str) -> Path:
    if slug == MAIN_SHOP:
        return main_db
    return main_db.parent / "shops" / f"{slug}.db"


def _connect(main_db: Path) -> sqlite3.Connection:
    path = registry_path(main_db)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("""CREATE TABLE IF NOT EXISTS shops (
        slug TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        owner_name TEXT NOT NULL,
        phone TEXT NOT NULL,
        promptpay_id TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','suspended')),
        trial_ends_at TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS shop_signups (
        ip_hash TEXT NOT NULL,
        created_at INTEGER NOT NULL)""")
    conn.execute("CREATE INDEX IF NOT EXISTS shop_signups_ip ON shop_signups(ip_hash,created_at)")
    # Monthly service payments to ZZAX Studio. poswai_billing.py owns the rules;
    # the table is created here so the registry file always carries it.
    conn.execute("""CREATE TABLE IF NOT EXISTS shop_payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        slug TEXT NOT NULL REFERENCES shops(slug),
        event_id TEXT NOT NULL,
        amount REAL NOT NULL,
        method TEXT NOT NULL,
        slip_reference TEXT UNIQUE,
        confirmed_by TEXT NOT NULL DEFAULT '',
        period_start TEXT NOT NULL,
        period_end TEXT NOT NULL,
        note TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(slug,event_id))""")
    conn.execute("CREATE INDEX IF NOT EXISTS shop_payments_slug ON shop_payments(slug,id)")
    return conn


def connect_registry(main_db: Path) -> sqlite3.Connection:
    """The registry connection with every table created. Billing shares it."""
    return _connect(main_db)


def valid_slug(slug: str) -> bool:
    return bool(SLUG_PATTERN.fullmatch(slug or ""))


def get_shop(main_db: Path, slug: str) -> dict | None:
    """Registered shops only; "main" and "demo" are built in and never stored here."""
    if not valid_slug(slug) or slug in RESERVED_SLUGS:
        return None
    with closing(_connect(main_db)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT slug,name,owner_name,phone,promptpay_id,status,trial_ends_at,created_at "
                           "FROM shops WHERE slug=?", (slug,)).fetchone()
    return dict(row) if row else None


def slug_available(main_db: Path, slug: str) -> bool:
    if not valid_slug(slug) or slug in RESERVED_SLUGS:
        return False
    return get_shop(main_db, slug) is None and not shop_db_path(main_db, slug).exists()


def reserve_shop(main_db: Path, *, slug: str, name: str, owner_name: str, phone: str,
                 client_key: str, max_shops: int) -> dict:
    """Record a new shop, refusing duplicates, bursts from one address and a full service."""
    ip_hash = hashlib.sha256(client_key.encode()).hexdigest()
    now = int(time.time())
    with closing(_connect(main_db)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM shop_signups WHERE created_at<?", (now - 86400,))
        recent = conn.execute("SELECT COUNT(*) FROM shop_signups WHERE ip_hash=? AND created_at>=?",
                              (ip_hash, now - 3600)).fetchone()[0]
        daily = conn.execute("SELECT COUNT(*) FROM shop_signups WHERE ip_hash=?", (ip_hash,)).fetchone()[0]
        if recent >= SIGNUPS_PER_HOUR or daily >= SIGNUPS_PER_DAY:
            raise ShopError(429, "เปิดร้านจากเครื่องนี้บ่อยเกินไป กรุณาลองใหม่ภายหลัง")
        if conn.execute("SELECT COUNT(*) FROM shops").fetchone()[0] >= max_shops:
            raise ShopError(503, "ขณะนี้รับร้านใหม่เต็มแล้ว กรุณาติดต่อทีมงาน")
        if not slug_available(main_db, slug):
            raise ShopError(409, "รหัสร้านนี้ถูกใช้แล้ว กรุณาเลือกรหัสอื่น")
        trial_ends = (datetime.date.today() + datetime.timedelta(days=TRIAL_DAYS)).isoformat()
        conn.execute("INSERT INTO shops(slug,name,owner_name,phone,trial_ends_at) VALUES(?,?,?,?,?)",
                     (slug, name, owner_name, phone, trial_ends))
        conn.execute("INSERT INTO shop_signups(ip_hash,created_at) VALUES(?,?)", (ip_hash, now))
    return get_shop(main_db, slug)


def release_shop(main_db: Path, slug: str) -> None:
    """Undo a reservation whose database could not be created."""
    with closing(_connect(main_db)) as conn, conn:
        conn.execute("DELETE FROM shops WHERE slug=?", (slug,))


def update_shop(main_db: Path, slug: str, *, name: str | None = None, promptpay_id: str | None = None) -> dict:
    changes, values = [], []
    if name is not None:
        changes.append("name=?")
        values.append(name)
    if promptpay_id is not None:
        changes.append("promptpay_id=?")
        values.append(promptpay_id)
    if changes:
        with closing(_connect(main_db)) as conn, conn:
            conn.execute(f"UPDATE shops SET {','.join(changes)} WHERE slug=?", (*values, slug))
    return get_shop(main_db, slug)
