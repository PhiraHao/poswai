import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from poswai_commissions import allocate_commissions


class CommissionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "commissions.db"
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.executescript("""
                CREATE TABLE pos_orders (id INTEGER PRIMARY KEY, branch_id INTEGER,
                    closed_by_staff_id INTEGER, net_amount REAL, status TEXT, closed_at TEXT);
                CREATE TABLE staffs (id INTEGER PRIMARY KEY, branch_id INTEGER, is_active INTEGER);
                CREATE TABLE attendances (staff_id INTEGER, clock_in TEXT);
                CREATE TABLE staff_shifts (staff_id INTEGER, work_date TEXT, status TEXT);
                CREATE TABLE leave_requests (staff_id INTEGER, start_date TEXT, end_date TEXT, status TEXT);
                CREATE TABLE commission_rules (id INTEGER PRIMARY KEY, branch_id INTEGER,
                    type TEXT, rate_percent REAL, min_sales_target REAL);
                CREATE TABLE commission_records (staff_id INTEGER, order_id INTEGER,
                    period_date TEXT, base_sales_amount REAL, calculated_amount REAL, pool_divisor INTEGER);
            """)
            conn.execute("INSERT INTO pos_orders VALUES (1,1,1,101,'paid','2026-10-14 18:00:00')")
            conn.executemany("INSERT INTO staffs VALUES (?,?,1)", [(1, 1), (2, 1), (3, 1), (4, 2)])
            conn.executemany("INSERT INTO attendances VALUES (?,?)", [
                (1, "2026-10-15T09:00:00"), (2, "2026-10-15T09:01:00"),
                (3, "2026-10-15T09:02:00"), (4, "2026-10-15T09:00:00")])

    def rule(self, mode="pooled_equal", rate=0.03, target=0):
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("INSERT INTO commission_rules (branch_id,type,rate_percent,min_sales_target) "
                         "VALUES (1,?,?,?)", (mode, rate, target))

    def records(self):
        with closing(sqlite3.connect(self.db)) as conn:
            return conn.execute("SELECT staff_id,period_date,calculated_amount,pool_divisor "
                                "FROM commission_records ORDER BY staff_id").fetchall()

    def allocate(self):
        with closing(sqlite3.connect(self.db)) as conn, conn:
            return allocate_commissions(conn, 1)

    def test_pooled_allocates_exact_cents_and_retry_is_idempotent(self):
        self.rule()
        self.assertEqual(self.allocate()["status"], "allocated")
        rows = self.records()
        self.assertEqual(len(rows), 3)
        self.assertEqual(sum(round(row[2] * 100) for row in rows), 303)
        self.assertEqual({row[1] for row in rows}, {"2026-10-15"})
        self.assertEqual({row[3] for row in rows}, {3})
        self.assertEqual(self.allocate()["status"], "already_allocated")
        self.assertEqual(self.records(), rows)

    def test_excludes_approved_leave_absence_and_other_branch(self):
        self.rule()
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("INSERT INTO staff_shifts VALUES (2,'2026-10-15','absent')")
            conn.execute("INSERT INTO leave_requests VALUES (3,'2026-10-14','2026-10-16','approved')")
        result = self.allocate()
        self.assertEqual(result["records_created"], 1)
        self.assertEqual(self.records(), [(1, "2026-10-15", 3.03, 1)])

    def test_individual_credits_cashier_only(self):
        self.rule("individual", 0.05)
        self.assertEqual(self.allocate()["pool_amount"], 5.05)
        self.assertEqual(self.records(), [(1, "2026-10-15", 5.05, 1)])

    def test_no_rule_and_unsupported_rule_never_invent_payment(self):
        self.assertEqual(self.allocate()["status"], "unconfigured")
        self.rule("tiered")
        self.assertEqual(self.allocate()["status"], "unsupported_rule")
        self.rule("pooled_equal", target=1000)
        self.assertEqual(self.allocate()["status"], "unsupported_rule")
        self.assertEqual(self.records(), [])

    def test_transaction_rollback_takes_commissions_with_payment(self):
        self.rule()
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute("BEGIN")
            self.assertEqual(allocate_commissions(conn, 1)["status"], "allocated")
            conn.rollback()
        self.assertEqual(self.records(), [])


if __name__ == "__main__":
    unittest.main()
