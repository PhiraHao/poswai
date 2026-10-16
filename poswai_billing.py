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
METHODS = ("promptpay_slip", "manual")
MAX_MONTHS = 12


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


def _payment_summary(conn: sqlite3.Connection, slug: str) -> tuple[int, dict | None]:
    count = conn.execute("SELECT COUNT(*) FROM shop_payments WHERE slug=?", (slug,)).fetchone()[0]
    last = conn.execute("SELECT amount,method,confirmed_by,period_end,created_at FROM shop_payments "
                        "WHERE slug=? ORDER BY id DESC LIMIT 1", (slug,)).fetchone()
    return count, (dict(last) if last else None)


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
                "payments": 0, "last_payment": None,
                "message": "ร้านนี้ดูแลโดย ZZAX Studio ไม่มีค่าบริการรายเดือนในระบบ"}
    with closing(connect_registry(main_db)) as conn:
        conn.row_factory = sqlite3.Row
        shop = conn.execute("SELECT slug,name,status,trial_ends_at FROM shops WHERE slug=?",
                            (slug,)).fetchone()
        if not shop:
            raise ShopError(404, "ไม่พบร้านนี้")
        payments, last = _payment_summary(conn, slug)
    now = today or today_date()
    due_date = _parse_date(shop["trial_ends_at"]) or now
    days_left = (due_date - now).days
    state = _state_for(days_left)
    on_trial = payments == 0
    return {"slug": slug, "name": shop["name"], "state": state, "applicable": True,
            "blocked": state == STATE_OVERDUE, "due_date": due_date.isoformat(),
            "days_left": days_left, "on_trial": on_trial, "price": price,
            "status": shop["status"], "payments": payments, "last_payment": last,
            "message": _describe(state, days_left, due_date.isoformat(), on_trial, price)}


def record_payment(main_db, slug: str, *, amount: float, method: str, event_id: str,
                   confirmed_by: str, price: float, slip_reference: str | None = None,
                   note: str = "", months: int = 1, today: datetime.date | None = None) -> dict:
    """Extend the paid-through date by whole months, once per event and per slip.

    Repeating the same `event_id` returns the first result instead of extending
    again, so a request retried after a timeout cannot buy two months.
    """
    if slug in (MAIN_SHOP, DEMO_SHOP):
        raise ShopError(400, "ร้านนี้ไม่มีค่าบริการรายเดือนในระบบ")
    if method not in METHODS:
        raise ShopError(400, "ช่องทางชำระเงินไม่ถูกต้อง")
    if not event_id or len(event_id) > 80:
        raise ShopError(400, "รหัสรายการชำระเงินไม่ถูกต้อง")
    if months < 1 or months > MAX_MONTHS:
        raise ShopError(400, f"ชำระล่วงหน้าได้ 1–{MAX_MONTHS} เดือน")
    if not (amount > 0) or amount > 1_000_000:
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
        period_end = add_months(start, months)
        conn.execute("INSERT INTO shop_payments(slug,event_id,amount,method,slip_reference,"
                     "confirmed_by,period_start,period_end,note) VALUES(?,?,?,?,?,?,?,?,?)",
                     (slug, event_id, round(float(amount), 2), method, slip_reference or None,
                      confirmed_by, start.isoformat(), period_end.isoformat(), note[:300]))
        conn.execute("UPDATE shops SET trial_ends_at=? WHERE slug=?", (period_end.isoformat(), slug))
    return {"existing": False, "paid_until": period_end.isoformat(), "months": months,
            "billing": billing_state(main_db, slug, price=price, today=now)}


def payment_history(main_db, slug: str, limit: int = 24) -> list[dict]:
    with closing(connect_registry(main_db)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT amount,method,confirmed_by,slip_reference,period_start,"
                            "period_end,note,created_at FROM shop_payments WHERE slug=? "
                            "ORDER BY id DESC LIMIT ?", (slug, max(1, min(limit, 200)))).fetchall()
    return [dict(row) for row in rows]


def all_shops_billing(main_db, *, price: float, today: datetime.date | None = None) -> list[dict]:
    """Every registered shop with its billing state, for the ZZAX Studio page."""
    now = today or today_date()
    with closing(connect_registry(main_db)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT slug,name,owner_name,phone,status,trial_ends_at,created_at "
                            "FROM shops ORDER BY trial_ends_at ASC, slug ASC").fetchall()
        summaries = {}
        for row in rows:
            payments, last = _payment_summary(conn, row["slug"])
            paid_total = conn.execute("SELECT COALESCE(SUM(amount),0) FROM shop_payments WHERE slug=?",
                                      (row["slug"],)).fetchone()[0]
            summaries[row["slug"]] = (payments, last, round(float(paid_total), 2))
    listed = []
    for row in rows:
        payments, last, paid_total = summaries[row["slug"]]
        due_date = _parse_date(row["trial_ends_at"]) or now
        days_left = (due_date - now).days
        listed.append({**dict(row), "state": _state_for(days_left), "days_left": days_left,
                       "due_date": due_date.isoformat(), "on_trial": payments == 0,
                       "payments": payments, "last_payment": last, "paid_total": paid_total,
                       "price": price})
    return listed
