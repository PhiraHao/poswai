import datetime as dt
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from poswai_analytics import build_analytics_dashboard


class AnalyticsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "reports.db"
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.executescript("""
                CREATE TABLE pos_orders (
                    branch_id INTEGER, order_no TEXT, net_amount REAL,
                    payment_method TEXT, status TEXT, closed_at TEXT
                );
                CREATE TABLE order_items (
                    order_no TEXT, item_id TEXT, name TEXT,
                    quantity REAL, unit_price REAL
                );
            """)

    def order(self, branch, number, amount, method, status, timestamp, item="tea"):
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("INSERT INTO pos_orders VALUES (?,?,?,?,?,?)",
                         (branch, number, amount, method, status, timestamp))
            conn.execute("INSERT INTO order_items VALUES (?,?,?,?,?)",
                         (number, item, item, 2, amount / 2))

    def test_paid_branch_sales_and_unavailable_metrics(self):
        # 2026-10-14 18:00 UTC is 2026-10-15 01:00 in Thailand.
        self.order(1, "A", 100, "cash", "paid", "2026-10-14 18:00:00")
        self.order(1, "B", 50, "card", "paid", "2026-10-15 04:00:00")
        self.order(1, "C", 500, "cash", "refunded", "2026-10-15 04:00:00")
        self.order(2, "D", 700, "cash", "paid", "2026-10-15 04:00:00")
        self.order(1, "E", 75, "cash", "paid", "2026-10-13 20:00:00")
        self.order(1, "F", 50, "cash", "paid", "2026-10-07 20:00:00")
        result = build_analytics_dashboard(self.db, today=dt.date(2026, 10, 15))
        sales = result["sales_realtime"]
        self.assertEqual(sales["today_sales"], 150)
        self.assertEqual(sales["paid_order_count"], 2)
        self.assertEqual(sales["payment_split"], {"cash": 100, "card": 50})
        self.assertEqual(sales["dod_growth_percent"], 100)
        self.assertEqual(sales["wow_growth_percent"], 200)
        self.assertEqual(result["top_selling_menu"][0]["quantity"], 4)
        self.assertEqual(result["food_cost_and_retention"]["avg_basket_size_baht"], 75)
        self.assertIsNone(result["bcg_menu_matrix"])
        self.assertIsNone(sales["channel_split"])

    def test_empty_day_does_not_invent_growth_or_cost(self):
        result = build_analytics_dashboard(self.db, today=dt.date(2026, 10, 15))
        sales = result["sales_realtime"]
        self.assertEqual(sales["today_sales"], 0)
        self.assertIsNone(sales["dod_growth_percent"])
        self.assertIsNone(sales["daily_target"])
        self.assertEqual(result["top_selling_menu"], [])
        self.assertIsNone(result["food_cost_and_retention"]["actual_food_cost_percent"])

    def test_invalid_filters(self):
        for options in ({"benchmark": "BAD"}, {"branch_id": 0}, {"daily_target": -1}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                build_analytics_dashboard(self.db, **options)


if __name__ == "__main__":
    unittest.main()
