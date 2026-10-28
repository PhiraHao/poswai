"""Monthly service billing for the shops hosted on POS WAI.

A new shop gets a free trial; after that it pays ZZAX Studio once a month. The
paid-through date is the shop's `trial_ends_at` in the registry, which every
accepted payment pushes one month further. Nothing here ever deletes a shop or
its data: an unpaid shop keeps reading and reporting, and only loses the right
to take new orders until it pays.

The money arrives on ZZAX Studio's own PromptPay account, not the shop's, so
the receiving number and the EasySlip key used here are separate settings from
the ones a shop configures for its own customers.
"""

import calendar
import datetime
import sqlite3
from contextlib import closing

from poswai_shops import DEMO_SHOP, MAIN_SHOP, ShopError, connect_registry

# How early the app starts asking the owner to pay, and how the states are named.
WARN_DAYS = 7
STATE_HOSTED = "hosted"      # the original shop and the demo: nothing to collect
STATE_OK = "ok"
STATE_DUE_SOON = "due_soon"
STATE_OVERDUE = "overdue"
# "grant" is time given away (an apology, a pilot): it moves the due date but is
# never counted as income, so the revenue figures stay true.
METHODS = ("promptpay_slip", "manual", "grant")
GRANT = "grant"
MAX_GRANT_DAYS = 365
STATE_CLOSED = "closed"
STATE_SUSPENDED = "suspended"
MAX_MONTHS = 12
# SQLite keeps CURRENT_TIMESTAMP in UTC; shop time is what the reports mean by a month.
BANGKOK_SQL_OFFSET = "+7 hours"


def today_date() -> datetime.date:
    return datetime.date.today()


def add_months(start: datetime.date, months: int) -> datetime.date:
    """The same day number this many months later, clamped to a short month's end."""
    if months < 1:
        raise ValueError("months must be at least 1")
    month_index = start.month - 1 + months
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    return datetime.date(year, month, min(start.day, calendar.monthrange(year, month)[1]))


def _parse_date(value: str | None) -> datetime.date | None:
    try:
        return datetime.date.fromisoformat((value or "")[:10])
    except ValueError:
        return None


def _payment_summary(conn: sqlite3.Connection, slug: str) -> dict:
    """Real payments and given-away time counted apart, so income is never inflated."""
    paid, total = conn.execute("SELECT COUNT(*),COALESCE(SUM(amount),0) FROM shop_payments "
                               "WHERE slug=? AND method<>?", (slug, GRANT)).fetchone()
    grants = conn.execute("SELECT COUNT(*) FROM shop_payments WHERE slug=? AND method=?",
                          (slug, GRANT)).fetchone()[0]
    last = conn.execute("SELECT amount,method,confirmed_by,period_end,created_at FROM shop_payments "
                        "WHERE slug=? ORDER BY id DESC LIMIT 1", (slug,)).fetchone()
    return {"payments": paid, "paid_total": round(float(total), 2), "grants": grants,
            "last_payment": (dict(last) if last else None)}


def _state_for(days_left: int) -> str:
    if days_left < 0:
        return STATE_OVERDUE
    return STATE_DUE_SOON if days_left <= WARN_DAYS else STATE_OK


def _describe(state: str, days_left: int, due_date: str, on_trial: bool, price: float) -> str:
    amount = f"{price:,.0f}"
    if state == STATE_OVERDUE:
        return (f"เลยกำหนดชำระค่าบริการมา {abs(days_left)} วัน (ครบกำหนด {due_date}) "
                f"ร้านยังเปิดดูข้อมูลและรายงานได้ แต่รับออเดอร์ใหม่ไม่ได้ "
                f"จนกว่าจะชำระ {amount} บาทต่อเดือน ข้อมูลของร้านไม่ถูกลบ")
    if state == STATE_DUE_SOON:
        period = "ช่วงทดลองใช้ฟรี" if on_trial else "รอบการใช้งาน"
        if days_left == 0:
            return (f"วันนี้เป็นวันสุดท้ายของ{period} ชำระ {amount} บาทต่อเดือน "
                    "เพื่อให้ร้านรับออเดอร์ต่อได้พรุ่งนี้")
        return (f"{period}จะหมดในอีก {days_left} วัน (วันสุดท้าย {due_date}) "
                f"ชำระ {amount} บาทต่อเดือนเพื่อใช้งานต่อ")
    if on_trial:
        return f"ทดลองใช้ฟรีถึง {due_date} (เหลืออีก {days_left} วัน)"
    return f"ชำระค่าบริการแล้ว ใช้งานได้ถึง {due_date}"


def billing_state(main_db, slug: str, *, price: float, today: datetime.date | None = None) -> dict:
    """What this shop owes right now, and whether it may still take new orders."""
    if slug in (MAIN_SHOP, DEMO_SHOP):
        return {"slug": slug, "state": STATE_HOSTED, "applicable": False, "blocked": False,
                "due_date": None, "days_left": None, "on_trial": False, "price": price,
                "payments": 0, "paid_total": 0.0, "grants": 0, "last_payment": None,
                "status": "active", "status_reason": "", "in_service": True,
                "message": "ร้านนี้ดูแลโดย ZZAX Studio ไม่มีค่าบริการรายเดือนในระบบ"}
    with closing(connect_registry(main_db)) as conn:
        conn.row_factory = sqlite3.Row
        shop = conn.execute("SELECT slug,name,status,status_reason,trial_ends_at FROM shops WHERE slug=?",
                            (slug,)).fetchone()
        if not shop:
            raise ShopError(404, "ไม่พบร้านนี้")
        summary = _payment_summary(conn, slug)
    now = today or today_date()
    due_date = _parse_date(shop["trial_ends_at"]) or now
    days_left = (due_date - now).days
    state = _state_for(days_left)
    on_trial = summary["payments"] == 0
    message = _describe(state, days_left, due_date.isoformat(), on_trial, price)
    # A shop the studio suspended or closed is not "behind on its bill": it is out of
    # service, and saying so plainly beats showing it an invoice it cannot act on.
    if shop["status"] != "active":
        state = STATE_CLOSED if shop["status"] == "closed" else STATE_SUSPENDED
        message = ("ร้านนี้ปิดการใช้งานถาวรแล้ว ข้อมูลยังถูกเก็บไว้ทั้งหมด"
                   if shop["status"] == "closed" else "ร้านนี้ถูกระงับการใช้งานชั่วคราว")
        if shop["status_reason"]:
            message += f" ({shop['status_reason']})"
    return {"slug": slug, "name": shop["name"], "state": state, "applicable": True,
            "blocked": state == STATE_OVERDUE, "due_date": due_date.isoformat(),
            "days_left": days_left, "on_trial": on_trial, "price": price,
            "status": shop["status"], "status_reason": shop["status_reason"],
            "in_service": shop["status"] == "active", "message": message, **summary}


def record_payment(main_db, slug: str, *, amount: float, method: str, event_id: str,
                   confirmed_by: str, price: float, slip_reference: str | None = None,
                   note: str = "", months: int = 1, days: int | None = None,
                   today: datetime.date | None = None) -> dict:
    """Extend the paid-through date, once per event and per slip.

    `months` buys whole months; `days` adds free days and is how a "grant" is
    written. Repeating the same `event_id` returns the first result instead of
    extending again, so a request retried after a timeout cannot buy two months.
    """
    if slug in (MAIN_SHOP, DEMO_SHOP):
        raise ShopError(400, "ร้านนี้ไม่มีค่าบริการรายเดือนในระบบ")
    if method not in METHODS:
        raise ShopError(400, "ช่องทางชำระเงินไม่ถูกต้อง")
    if not event_id or len(event_id) > 80:
        raise ShopError(400, "รหัสรายการชำระเงินไม่ถูกต้อง")
    if days is not None and (days < 1 or days > MAX_GRANT_DAYS):
        raise ShopError(400, f"ขยายเวลาได้ 1–{MAX_GRANT_DAYS} วัน")
    if days is None and (months < 1 or months > MAX_MONTHS):
        raise ShopError(400, f"ชำระล่วงหน้าได้ 1–{MAX_MONTHS} เดือน")
    if method == GRANT:
        # Free time has to say why: the note is the only record of who was compensated.
        if not note.strip():
            raise ShopError(400, "การขยายเวลาให้ฟรีต้องระบุเหตุผล")
        if amount:
            raise ShopError(400, "การขยายเวลาให้ฟรีต้องมียอดเงินเป็นศูนย์")
    elif not (amount > 0) or amount > 1_000_000:
        raise ShopError(400, "ยอดชำระไม่ถูกต้อง")
    now = today or today_date()
    with closing(connect_registry(main_db)) as conn, conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")
        shop = conn.execute("SELECT trial_ends_at FROM shops WHERE slug=?", (slug,)).fetchone()
        if not shop:
            raise ShopError(404, "ไม่พบร้านนี้")
        done = conn.execute("SELECT period_end FROM shop_payments WHERE slug=? AND event_id=?",
                            (slug, event_id)).fetchone()
        if done:
            return {"existing": True, "paid_until": done["period_end"]}
        if slip_reference and conn.execute("SELECT 1 FROM shop_payments WHERE slip_reference=?",
                                           (slip_reference,)).fetchone():
            raise ShopError(409, "สลิปนี้ถูกใช้ยืนยันการชำระแล้ว")
        # Paying early adds to the days that are left; paying late starts today, so a
        # shop that stopped paying for months owes one month to reopen, not all of them.
        start = max(_parse_date(shop["trial_ends_at"]) or now, now)
        period_end = (start + datetime.timedelta(days=days)) if days is not None else add_months(start, months)
        conn.execute("INSERT INTO shop_payments(slug,event_id,amount,method,slip_reference,"
                     "confirmed_by,period_start,period_end,note) VALUES(?,?,?,?,?,?,?,?,?)",
                     (slug, event_id, round(float(amount), 2), method, slip_reference or None,
                      confirmed_by, start.isoformat(), period_end.isoformat(), note[:300]))
        conn.execute("UPDATE shops SET trial_ends_at=? WHERE slug=?", (period_end.isoformat(), slug))
    return {"existing": False, "paid_until": period_end.isoformat(),
            "months": None if days is not None else months, "days": days,
            "billing": billing_state(main_db, slug, price=price, today=now)}


def payment_history(main_db, slug: str, limit: int = 24) -> list[dict]:
    with closing(connect_registry(main_db)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT amount,method,confirmed_by,slip_reference,period_start,"
                            "period_end,note,created_at FROM shop_payments WHERE slug=? "
                            "ORDER BY id DESC LIMIT ?", (slug, max(1, min(limit, 200)))).fetchall()
    return [dict(row) for row in rows]


def all_shops_billing(main_db, *, price: float, today: datetime.date | None = None,
                      include_closed: bool = False) -> list[dict]:
    """Every registered shop with its billing state, for the ZZAX Studio page.

    A shop closed for good is left out unless it is asked for: it owes nothing and
    should not sit in the overdue count, but its row and its data are still there.
    """
    now = today or today_date()
    with closing(connect_registry(main_db)) as conn:
        conn.row_factory = sqlite3.Row
        where = "" if include_closed else " WHERE status<>'closed'"
        rows = conn.execute("SELECT slug,name,owner_name,phone,status,status_reason,status_changed_at,"
                            f"trial_ends_at,created_at FROM shops{where} "
                            "ORDER BY trial_ends_at ASC, slug ASC").fetchall()
        summaries = {row["slug"]: _payment_summary(conn, row["slug"]) for row in rows}
    listed = []
    for row in rows:
        summary = summaries[row["slug"]]
        due_date = _parse_date(row["trial_ends_at"]) or now
        days_left = (due_date - now).days
        state = _state_for(days_left)
        if row["status"] != "active":
            state = STATE_CLOSED if row["status"] == "closed" else STATE_SUSPENDED
        listed.append({**dict(row), "state": state, "days_left": days_left,
                       "due_date": due_date.isoformat(), "on_trial": summary["payments"] == 0,
                       "in_service": row["status"] == "active", "price": price, **summary})
    return listed


def monthly_revenue(main_db, *, months: int = 12, today: datetime.date | None = None) -> list[dict]:
    """Money actually received, by calendar month in shop time. Grants are not income.

    created_at is SQLite's UTC stamp, so it is shifted to Bangkok before the month
    is read off it — otherwise every payment taken after 07:00 UTC on the last day
    of a month would land in the wrong month's total.
    """
    now = today or today_date()
    with closing(connect_registry(main_db)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT strftime('%Y-%m', datetime(created_at,?)) AS month, "
            "COUNT(*) AS payments, COUNT(DISTINCT slug) AS shops, "
            "COALESCE(SUM(amount),0) AS amount FROM shop_payments WHERE method<>? "
            "GROUP BY month ORDER BY month DESC LIMIT ?",
            (BANGKOK_SQL_OFFSET, GRANT, max(1, min(months, 120)))).fetchall()
        granted = {row["month"]: row["grants"] for row in conn.execute(
            "SELECT strftime('%Y-%m', datetime(created_at,?)) AS month, "
            "COUNT(*) AS grants FROM shop_payments WHERE method=? GROUP BY month",
            (BANGKOK_SQL_OFFSET, GRANT))}
    return [{"month": row["month"], "payments": row["payments"], "shops": row["shops"],
             "amount": round(float(row["amount"]), 2), "grants": granted.get(row["month"], 0),
             "is_current": row["month"] == now.strftime("%Y-%m")} for row in rows]
