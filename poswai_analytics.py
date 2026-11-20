"""Read-only executive metrics computed from paid POS records.

SQLite CURRENT_TIMESTAMP values are UTC. Reports use the restaurant's Thailand
business day, so the SQL date/hour expressions shift those values to UTC+7.
The current schema has no channel, ingredient cost, member, or KDS event data;
those metrics deliberately remain unavailable rather than looking measured.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from contextlib import closing
from pathlib import Path
from zoneinfo import ZoneInfo


THAILAND = ZoneInfo("Asia/Bangkok")
BUSINESS_DATE = "date(closed_at, '+7 hours')"


def _money(value: object) -> float:
    return round(float(value or 0), 2)


def _growth(current: float, previous: float) -> float | None:
    return round((current - previous) / previous * 100, 2) if previous > 0 else None


def build_analytics_dashboard(
    db_path: str | Path,
    benchmark: str = "WOW",
    branch_id: int = 1,
    today: dt.date | None = None,
    daily_target: float | None = None,
) -> dict:
    """Return factual sales metrics; unavailable measures are null or empty.

    Only paid, non-refunded ``pos_orders`` are counted. All monetary fields are
    in baht. ``today`` is injectable to keep edge cases deterministic in tests.
    """
    benchmark = benchmark.upper()
    if benchmark not in {"WOW", "DOD"}:
        raise ValueError("benchmark must be WOW or DOD")
    if branch_id < 1:
        raise ValueError("branch_id must be positive")
    if daily_target is not None and daily_target < 0:
        raise ValueError("daily_target cannot be negative")

    business_day = today or dt.datetime.now(THAILAND).date()
    previous_day = business_day - dt.timedelta(days=1)
    previous_week = business_day - dt.timedelta(days=7)
    dates = (business_day.isoformat(), previous_day.isoformat(), previous_week.isoformat())

    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        totals = {
            row["business_day"]: (_money(row["sales"]), int(row["orders"]))
            for row in conn.execute(
                f"SELECT {BUSINESS_DATE} AS business_day, "
                "COALESCE(SUM(net_amount), 0) AS sales, COUNT(*) AS orders "
                "FROM pos_orders WHERE branch_id=? AND status='paid' "
                f"AND {BUSINESS_DATE} IN (?,?,?) GROUP BY business_day",
                (branch_id, *dates),
            )
        }
        payments = {
            row["method"]: _money(row["sales"])
            for row in conn.execute(
                "SELECT COALESCE(NULLIF(TRIM(payment_method), ''), 'unknown') AS method, "
                "SUM(net_amount) AS sales FROM pos_orders "
                f"WHERE branch_id=? AND status='paid' AND {BUSINESS_DATE}=? "
                "GROUP BY method ORDER BY sales DESC, method",
                (branch_id, dates[0]),
            )
        }
        menu = [
            {
                "item_id": row["item_id"],
                "name": row["name"],
                "quantity": _money(row["quantity"]),
                "gross_sales": _money(row["gross_sales"]),
            }
            for row in conn.execute(
                "SELECT oi.item_id, oi.name, SUM(oi.quantity) AS quantity, "
                "SUM(oi.quantity * oi.unit_price) AS gross_sales "
                "FROM order_items oi JOIN pos_orders po ON po.order_no=oi.order_no "
                f"WHERE po.branch_id=? AND po.status='paid' AND {BUSINESS_DATE}=? "
                "GROUP BY oi.item_id, oi.name ORDER BY quantity DESC, gross_sales DESC LIMIT 20",
                (branch_id, dates[0]),
            )
        ]
        hourly = [
            {"hour": int(row["hour"]), "orders": int(row["orders"]), "sales": _money(row["sales"])}
            for row in conn.execute(
                "SELECT strftime('%H', closed_at, '+7 hours') AS hour, COUNT(*) AS orders, "
                "SUM(net_amount) AS sales FROM pos_orders "
                f"WHERE branch_id=? AND status='paid' AND {BUSINESS_DATE}=? "
                "GROUP BY hour ORDER BY hour",
                (branch_id, dates[0]),
            )
        ]

    today_sales, order_count = totals.get(dates[0], (0.0, 0))
    yesterday_sales = totals.get(dates[1], (0.0, 0))[0]
    last_week_sales = totals.get(dates[2], (0.0, 0))[0]
    return {
        "source": "sqlite_paid_orders",
        "business_date": dates[0],
        "branch_id": branch_id,
        "sales_realtime": {
            "today_sales": today_sales,
            "paid_order_count": order_count,
            "daily_target": daily_target,
            "benchmark_mode": benchmark,
            "yesterday_sales": yesterday_sales,
            "last_week_same_day_sales": last_week_sales,
            "dod_growth_percent": _growth(today_sales, yesterday_sales),
            "wow_growth_percent": _growth(today_sales, last_week_sales),
            "channel_split": None,
            "payment_split": payments,
        },
        "top_selling_menu": menu,
        "hourly_sales": hourly,
        "bcg_menu_matrix": None,
        "kds_and_predictive_roster": None,
        "food_cost_and_retention": {
            "actual_food_cost_percent": None,
            "target_corridor_percent": None,
            "waste_cost_baht": None,
            "returning_member_ratio_percent": None,
            "avg_basket_size_baht": round(today_sales / order_count, 2) if order_count else None,
            "spending_per_head_baht": None,
            "customer_ltv_baht": None,
        },
        "unavailable_metrics": [
            "channel_split", "menu_cost_and_margin", "kds_speed", "staffing_forecast",
            "ingredient_cost", "waste_cost", "member_retention", "spending_per_head", "customer_ltv",
        ],
    }
