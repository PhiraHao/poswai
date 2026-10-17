"""Owner accounts for the hosted POS WAI service.

An owner signs in as a person — LINE or Google — not as "shop code plus PIN".
The account lives in the central registry (shops.db) because one account may own
several shops, and a shop may have several owners. Front-of-house staff keep the
PIN login: one tablet passes between people all day, and a PIN is faster there.

Nothing here trusts the browser. The provider's reply is checked against a state
row this server wrote, and the identity itself comes from the provider's own
verification endpoint, not from a token the page handed us.
"""

import hashlib
import os
import secrets
import sqlite3
import time
from contextlib import closing
from pathlib import Path

import httpx

import poswai_shops as shops

PROVIDERS = ("line", "google")
# Set POSWAI_LINE_EMAIL_PERMISSION=1 once LINE approves the channel for it.
LINE_EMAIL_PERMISSION = os.getenv("POSWAI_LINE_EMAIL_PERMISSION", "") not in ("", "0", "false")
STATE_LIFETIME = 600            # a sign-in that takes longer than ten minutes is stale
SESSION_LIFETIME = 30 * 24 * 3600   # an owner signs in on their own phone, not a shared till
LINE_AUTH_URL = "https://access.line.me/oauth2/v2.1/authorize"
LINE_TOKEN_URL = "https://api.line.me/oauth2/v2.1/token"
LINE_VERIFY_URL = "https://api.line.me/oauth2/v2.1/verify"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"
GOOGLE_ISSUERS = ("accounts.google.com", "https://accounts.google.com")


class OwnerAuthError(Exception):
    """A failure with a message the owner can act on, and a short code for the page."""

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _connect(main_db: Path) -> sqlite3.Connection:
    """The registry connection with the owner-account tables created."""
    conn = shops.connect_registry(main_db)
    conn.execute("""CREATE TABLE IF NOT EXISTS owner_accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        provider TEXT NOT NULL,
        external_id TEXT NOT NULL,
        email TEXT NOT NULL DEFAULT '',
        display_name TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        last_login_at TEXT,
        UNIQUE(provider,external_id))""")
    conn.execute("CREATE INDEX IF NOT EXISTS owner_accounts_email ON owner_accounts(email)")
    # staff_id is the owner's own row inside that shop's database, so entering a
    # shop from an account reuses the ordinary staff session and role checks.
    conn.execute("""CREATE TABLE IF NOT EXISTS owner_shops (
        account_id INTEGER NOT NULL REFERENCES owner_accounts(id),
        slug TEXT NOT NULL,
        staff_id INTEGER NOT NULL,
        role TEXT NOT NULL DEFAULT 'owner',
        linked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(account_id,slug))""")
    conn.execute("CREATE INDEX IF NOT EXISTS owner_shops_slug ON owner_shops(slug)")
    conn.execute("""CREATE TABLE IF NOT EXISTS owner_sessions (
        token_hash TEXT PRIMARY KEY,
        account_id INTEGER NOT NULL REFERENCES owner_accounts(id),
        expires_at INTEGER NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
    # One row per sign-in attempt. The browser only ever carries the state value;
    # which shop is being linked, and to which staff row, stays on the server.
    conn.execute("""CREATE TABLE IF NOT EXISTS owner_login_states (
        state_hash TEXT PRIMARY KEY,
        provider TEXT NOT NULL,
        nonce TEXT NOT NULL,
        mode TEXT NOT NULL DEFAULT 'login',
        slug TEXT NOT NULL DEFAULT '',
        staff_id INTEGER,
        created_at INTEGER NOT NULL)""")
    return conn


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ---------------------------------------------------------------- the handshake
def start_login(main_db: Path, *, provider: str, mode: str = "login", slug: str = "",
                staff_id: int | None = None) -> dict:
    """Record one sign-in attempt and return the state and nonce to send out."""
    if provider not in PROVIDERS:
        raise OwnerAuthError("provider", "ช่องทางเข้าสู่ระบบนี้ไม่มีในระบบ", 404)
    if mode not in ("login", "link", "member"):
        raise OwnerAuthError("mode", "คำขอเข้าสู่ระบบไม่ถูกต้อง", 400)
    state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
    now = int(time.time())
    with closing(_connect(main_db)) as conn, conn:
        conn.execute("DELETE FROM owner_login_states WHERE created_at<?", (now - STATE_LIFETIME,))
        conn.execute("INSERT INTO owner_login_states(state_hash,provider,nonce,mode,slug,staff_id,created_at)"
                     " VALUES(?,?,?,?,?,?,?)",
                     (_hash(state), provider, nonce, mode, slug, staff_id, now))
    return {"state": state, "nonce": nonce}


def consume_state(main_db: Path, *, provider: str, state: str) -> dict:
    """Take a state row once and never again, so a replayed callback is refused."""
    if not state:
        raise OwnerAuthError("state", "คำขอเข้าสู่ระบบไม่ถูกต้อง กรุณาลองใหม่", 400)
    now = int(time.time())
    with closing(_connect(main_db)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT provider,nonce,mode,slug,staff_id,created_at FROM owner_login_states"
                           " WHERE state_hash=?", (_hash(state),)).fetchone()
        conn.execute("DELETE FROM owner_login_states WHERE state_hash=?", (_hash(state),))
    if not row or row[0] != provider or now - row[5] > STATE_LIFETIME:
        raise OwnerAuthError("state", "คำขอเข้าสู่ระบบหมดอายุหรือไม่ถูกต้อง กรุณาลองใหม่", 400)
    return {"provider": row[0], "nonce": row[1], "mode": row[2], "slug": row[3], "staff_id": row[4]}


# ---------------------------------------------------------------- the providers
def _post_form(url: str, data: dict) -> dict:
    """Wrapped so tests can stand in for a provider without faking signed tokens."""
    try:
        response = httpx.post(url, data=data, timeout=8)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise OwnerAuthError("provider", "ติดต่อผู้ให้บริการเข้าสู่ระบบไม่สำเร็จ กรุณาลองใหม่", 502) from exc


def _get_json(url: str, params: dict) -> dict:
    try:
        response = httpx.get(url, params=params, timeout=8)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise OwnerAuthError("provider", "ตรวจสอบบัญชีกับผู้ให้บริการไม่สำเร็จ กรุณาลองใหม่", 502) from exc


def authorize_url(provider: str, *, client_id: str, redirect_uri: str, state: str, nonce: str) -> str:
    from urllib.parse import urlencode
    if provider == "line":
        # LINE hands out the email scope only to channels that applied for it,
        # and bot_prompt only means anything on a channel linked to an official
        # account. Asking for either without that turns the login page into
        # "เกิดข้อผิดพลาดที่ไม่ทราบสาเหตุ", which tells the customer nothing.
        # The email is a nicety here, so it is asked for only once the shop
        # says the permission came through.
        scope = "openid profile email" if LINE_EMAIL_PERMISSION else "openid profile"
        query = {"response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri,
                 "state": state, "scope": scope, "nonce": nonce}
        return f"{LINE_AUTH_URL}?{urlencode(query)}"
    query = {"response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri,
             "state": state, "scope": "openid email profile", "nonce": nonce,
             "access_type": "online", "prompt": "select_account"}
    return f"{GOOGLE_AUTH_URL}?{urlencode(query)}"


def identity_from_code(provider: str, *, code: str, nonce: str, client_id: str, client_secret: str,
                       redirect_uri: str) -> dict:
    """Exchange the code and return the identity the provider itself vouches for."""
    if not code:
        raise OwnerAuthError("code", "ไม่ได้รับรหัสยืนยันจากผู้ให้บริการ กรุณาลองใหม่", 400)
    if not client_id or not client_secret:
        raise OwnerAuthError("unconfigured", "ยังไม่ได้เปิดใช้ช่องทางนี้", 503)
    token_url = LINE_TOKEN_URL if provider == "line" else GOOGLE_TOKEN_URL
    token = _post_form(token_url, {"grant_type": "authorization_code", "code": code,
                                   "redirect_uri": redirect_uri, "client_id": client_id,
                                   "client_secret": client_secret})
    id_token = token.get("id_token") or ""
    if not id_token:
        raise OwnerAuthError("id_token", "ผู้ให้บริการไม่ได้ส่งข้อมูลยืนยันตัวตนมา กรุณาลองใหม่", 502)
    if provider == "line":
        # LINE verifies the signature and the nonce for us; we still check every claim.
        claims = _post_form(LINE_VERIFY_URL, {"id_token": id_token, "client_id": client_id,
                                              "nonce": nonce})
        if claims.get("aud") != client_id:
            raise OwnerAuthError("id_token", "ข้อมูลยืนยันตัวตนไม่ตรงกับช่องทางนี้", 401)
    else:
        claims = _get_json(GOOGLE_TOKENINFO_URL, {"id_token": id_token})
        if claims.get("aud") != client_id or claims.get("iss") not in GOOGLE_ISSUERS:
            raise OwnerAuthError("id_token", "ข้อมูลยืนยันตัวตนไม่ตรงกับช่องทางนี้", 401)
    if claims.get("nonce") != nonce:
        raise OwnerAuthError("nonce", "ข้อมูลยืนยันตัวตนไม่ตรงกับคำขอนี้ กรุณาลองใหม่", 401)
    try:
        expires = float(claims.get("exp", 0))
    except (TypeError, ValueError):
        expires = 0
    if expires <= time.time():
        raise OwnerAuthError("id_token", "ข้อมูลยืนยันตัวตนหมดอายุ กรุณาลองใหม่", 401)
    external_id = str(claims.get("sub") or "")
    if not external_id:
        raise OwnerAuthError("id_token", "ผู้ให้บริการไม่ได้บอกว่าเป็นบัญชีใด", 401)
    verified = claims.get("email_verified")
    email = str(claims.get("email") or "")
    if provider == "google" and verified not in (True, "true", 1, "1"):
        email = ""
    return {"provider": provider, "external_id": external_id, "email": email.lower(),
            "display_name": str(claims.get("name") or "")[:100]}


# ------------------------------------------------------------------- the account
def upsert_account(main_db: Path, identity: dict) -> dict:
    with closing(_connect(main_db)) as conn, conn:
        conn.execute("INSERT INTO owner_accounts(provider,external_id,email,display_name,last_login_at)"
                     " VALUES(?,?,?,?,CURRENT_TIMESTAMP)"
                     " ON CONFLICT(provider,external_id) DO UPDATE SET"
                     " email=excluded.email,display_name=excluded.display_name,"
                     "last_login_at=CURRENT_TIMESTAMP",
                     (identity["provider"], identity["external_id"], identity.get("email", ""),
                      identity.get("display_name", "")))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT id,provider,external_id,email,display_name FROM owner_accounts"
                           " WHERE provider=? AND external_id=?",
                           (identity["provider"], identity["external_id"])).fetchone()
    return dict(row)


def account_shops(main_db: Path, account_id: int) -> list[dict]:
    """The shops this account may enter, newest link last. Closed shops are left out."""
    with closing(_connect(main_db)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT o.slug,o.staff_id,o.role,s.name,s.status,s.trial_ends_at FROM owner_shops o"
            " JOIN shops s ON s.slug=o.slug WHERE o.account_id=? AND s.status!='closed'"
            " ORDER BY o.linked_at", (account_id,)).fetchall()
    return [dict(row) for row in rows]


def shop_accounts(main_db: Path, slug: str) -> list[dict]:
    """Who can sign into this shop with an account, for the shop's own settings page."""
    with closing(_connect(main_db)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT a.id,a.provider,a.email,a.display_name,o.linked_at,o.staff_id"
                            " FROM owner_shops o JOIN owner_accounts a ON a.id=o.account_id"
                            " WHERE o.slug=? ORDER BY o.linked_at", (slug,)).fetchall()
    return [dict(row) for row in rows]


def link_shop(main_db: Path, *, account_id: int, slug: str, staff_id: int, role: str = "owner") -> None:
    """Bind an account to a shop. Linking again only refreshes which staff row it is."""
    with closing(_connect(main_db)) as conn, conn:
        conn.execute("INSERT INTO owner_shops(account_id,slug,staff_id,role) VALUES(?,?,?,?)"
                     " ON CONFLICT(account_id,slug) DO UPDATE SET staff_id=excluded.staff_id,"
                     "role=excluded.role", (account_id, slug, staff_id, role))


def unlink_shop(main_db: Path, *, account_id: int, slug: str) -> None:
    with closing(_connect(main_db)) as conn, conn:
        conn.execute("DELETE FROM owner_shops WHERE account_id=? AND slug=?", (account_id, slug))


def shop_membership(main_db: Path, *, account_id: int, slug: str) -> dict | None:
    with closing(_connect(main_db)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT slug,staff_id,role FROM owner_shops WHERE account_id=? AND slug=?",
                           (account_id, slug)).fetchone()
    return dict(row) if row else None


# ------------------------------------------------------------------ the session
def open_session(main_db: Path, account_id: int) -> tuple[str, int]:
    token = secrets.token_hex(32)
    expires = int(time.time()) + SESSION_LIFETIME
    with closing(_connect(main_db)) as conn, conn:
        conn.execute("DELETE FROM owner_sessions WHERE expires_at<=?", (int(time.time()),))
        conn.execute("INSERT INTO owner_sessions(token_hash,account_id,expires_at) VALUES(?,?,?)",
                     (_hash(token), account_id, expires))
    return token, expires


def session_account(main_db: Path, token: str) -> dict | None:
    if not token or len(token) != 64:
        return None
    with closing(_connect(main_db)) as conn, conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT a.id,a.provider,a.email,a.display_name,s.expires_at"
                           " FROM owner_sessions s JOIN owner_accounts a ON a.id=s.account_id"
                           " WHERE s.token_hash=?", (_hash(token),)).fetchone()
        if row and row["expires_at"] <= int(time.time()):
            conn.execute("DELETE FROM owner_sessions WHERE token_hash=?", (_hash(token),))
            row = None
    return dict(row) if row else None


def close_session(main_db: Path, token: str) -> None:
    if not token:
        return
    with closing(_connect(main_db)) as conn, conn:
        conn.execute("DELETE FROM owner_sessions WHERE token_hash=?", (_hash(token),))
