"""Allocate configured commission from a paid order, once per staff/order.

Call this with the payment transaction's SQLite connection. The caller owns
commit/rollback, so a failed payment cannot leave commission records behind.
Rules store a fractional rate (0.03 means three percent). No rule means no
commission; unsupported rule types/targets are reported without guessing.
"""

from __future__ import annotations

import sqlite3
from decimal import Decimal, ROUND_HALF_UP


def _cents(amount: Decimal) -> int:
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def allocate_commissions(conn: sqlite3.Connection, order_id: int) -> dict:
    """Insert missing commission records for one paid order (transaction-safe).

    The caller must use this in the same write transaction as order closure.
    Retrying with the same order is idempotent even if the rule later changes.
    """
    order = conn.execute(
        "SELECT id, branch_id, closed_by_staff_id, net_amount, status, "
        "date(closed_at, '+7 hours') AS period_date FROM pos_orders WHERE id=?",
        (order_id,),
    ).fetchone()
    if not order:
        return {"status": "order_not_found", "records_created": 0}
    order_id, branch_id, cashier_id, amount, status, period_date = order
    if status != "paid":
        return {"status": "order_not_paid", "records_created": 0}

    # Existing rows fix the allocation policy for this order, including after
    # a rule edit. This also keeps a repeated payment request from double pay.
    if conn.execute("SELECT 1 FROM commission_records WHERE order_id=? LIMIT 1", (order_id,)).fetchone():
        return {"status": "already_allocated", "records_created": 0}

    rule = conn.execute(
        "SELECT type, rate_percent, min_sales_target FROM commission_rules "
        "WHERE branch_id=? ORDER BY id DESC LIMIT 1", (branch_id,),
    ).fetchone()
    if not rule:
        return {"status": "unconfigured", "records_created": 0}
    rule_type, raw_rate, raw_target = rule
    try:
        rate = Decimal(str(raw_rate))
        target = Decimal(str(raw_target or 0))
    except Exception:
        return {"status": "invalid_rule", "records_created": 0}
    if rate < 0 or rate > 1 or target < 0:
        return {"status": "invalid_rule", "records_created": 0}
    if target > 0 or rule_type not in {"individual", "pooled_equal"}:
        return {"status": "unsupported_rule", "records_created": 0}

    if rule_type == "pooled_equal":
        eligible = [row[0] for row in conn.execute(
            "SELECT s.id FROM staffs s WHERE s.branch_id=? AND s.is_active=1 "
            "AND EXISTS (SELECT 1 FROM attendances a WHERE a.staff_id=s.id AND date(a.clock_in)=?) "
            "AND NOT EXISTS (SELECT 1 FROM staff_shifts sh WHERE sh.staff_id=s.id "
            "AND sh.work_date=? AND sh.status IN ('on_leave','absent')) "
            "AND NOT EXISTS (SELECT 1 FROM leave_requests lr WHERE lr.staff_id=s.id "
            "AND lr.status='approved' AND lr.start_date<=? AND lr.end_date>=?) "
            "ORDER BY s.id",
            (branch_id, period_date, period_date, period_date, period_date),
        )]
    else:
        eligible = [row[0] for row in conn.execute(
            "SELECT s.id FROM staffs s WHERE s.id=? AND s.branch_id=? AND s.is_active=1 "
            "AND NOT EXISTS (SELECT 1 FROM staff_shifts sh WHERE sh.staff_id=s.id "
            "AND sh.work_date=? AND sh.status IN ('on_leave','absent')) "
            "AND NOT EXISTS (SELECT 1 FROM leave_requests lr WHERE lr.staff_id=s.id "
            "AND lr.status='approved' AND lr.start_date<=? AND lr.end_date>=?)",
            (cashier_id, branch_id, period_date, period_date, period_date),
        )] if cashier_id is not None else []

    if not eligible:
        return {"status": "no_eligible_staff", "records_created": 0}

    pool_cents = _cents(Decimal(str(amount)) * rate)
    divisor = len(eligible)
    share_cents, remainder = divmod(pool_cents, divisor)
    for index, staff_id in enumerate(eligible):
        cents = share_cents + (1 if index < remainder else 0)
        conn.execute(
            "INSERT INTO commission_records "
            "(staff_id, order_id, period_date, base_sales_amount, calculated_amount, pool_divisor) "
            "VALUES (?,?,?,?,?,?)",
            (staff_id, order_id, period_date, float(amount), cents / 100, divisor),
        )
    return {"status": "allocated", "records_created": divisor, "pool_amount": pool_cents / 100}
