"""รายงานยอดขายตามช่วงวันที่ และกำไรเท่าที่รู้ต้นทุนจริง

แดชบอร์ดเดิมตอบได้เรื่องเดียวคือวันนี้เป็นไง เจ้าของที่ปิดเดือนต้องการอีกเรื่อง
คือสามสิบวันนี้ขายได้เท่าไหร่ เมนูไหนคุ้ม เมนูไหนไม่คุ้ม และใครเป็นคนขาย
"""

import datetime as dt
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import line_pos_server as server
import poswai_reports as reports


class ReportCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.directory.cleanup)
        server.DB_PATH = Path(self.directory.name) / "reports.db"
        server.PREVIEW_ONLY = False
        server.BOOTSTRAP_MANAGER_PIN = ""
        server.TABLE_QR_SECRET = "d" * 48
        server.init_db()
        conn = sqlite3.connect(server.DB_PATH)
        with conn:
            conn.execute("INSERT INTO branches(id,name) VALUES(1,'Test')")
            for staff_id, role, name in ((1, "owner", "เจ้าของ"), (2, "cashier", "แอน"),
                                         (3, "cashier", "บี")):
                conn.execute("INSERT INTO staffs(id,branch_id,name,role,pin_code_hash)"
                             " VALUES(?,1,?,?,?)",
                             (staff_id, name, role, server.hash_pin(f"secure-pin-{role}")))
        conn.close()
        self.conn = sqlite3.connect(server.DB_PATH)
        self.addCleanup(self.conn.close)

    def signed_in(self, staff_id=1, role="owner"):
        client = TestClient(server.app)
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        self.assertEqual(client.post("/api/auth/login",
                                     json={"staff_id": staff_id, "pin": f"secure-pin-{role}"}).status_code, 200)
        return client

    def bill(self, order_no, day, amount, *, staff_id=2, method="เงินสด (Cash)",
             status="paid", lines=(), branch_id=1):
        """A paid bill on a given Thai business day.

        Stored at 05:00 UTC, which is noon in Bangkok — comfortably inside the
        day whichever way the boundary is read.
        """
        with self.conn:
            self.conn.execute(
                "INSERT INTO pos_orders (branch_id, order_no, closed_by_staff_id, total_amount,"
                " net_amount, payment_method, status, closed_at) VALUES (?,?,?,?,?,?,?,?)",
                (branch_id, order_no, staff_id, amount, amount, method, status, f"{day} 05:00:00.000"))
            for item_id, name, qty, price, cost in lines:
                self.conn.execute(
                    "INSERT INTO order_items (order_no,item_id,name,quantity,unit_price,"
                    "bom_json,unit_cost) VALUES (?,?,?,?,?,'[]',?)",
                    (order_no, item_id, name, qty, price, cost))

    def menu(self, item_id, name, category):
        with self.conn:
            self.conn.execute(
                "INSERT INTO menu_catalog (branch_id,item_id,name,price_cents,bom_json,category)"
                " VALUES (1,?,?,0,'[]',?)", (item_id, name, category))

    def report(self, **params):
        return reports.sales_report(self.conn, 1, today=dt.date(2026, 11, 9), **params)


class TheWindow(unittest.TestCase):
    TODAY = dt.date(2026, 11, 9)

    def test_the_default_is_the_last_thirty_days(self):
        self.assertEqual(reports.date_range(today=self.TODAY), ("2026-10-11", "2026-11-09"))

    def test_a_range_the_owner_asked_for_is_kept(self):
        self.assertEqual(reports.date_range("2026-01-01", "2026-01-31", self.TODAY),
                         ("2026-01-01", "2026-01-31"))

    def test_a_single_day_is_a_range_of_one(self):
        self.assertEqual(reports.date_range("2026-11-09", "2026-11-09", self.TODAY),
                         ("2026-11-09", "2026-11-09"))

    def test_a_backwards_range_is_refused(self):
        with self.assertRaises(reports.ReportError):
            reports.date_range("2026-11-09", "2026-01-01", self.TODAY)

    def test_rubbish_dates_are_refused(self):
        for bad in ("yesterday", "9/11/2026", "2026-13-01"):
            with self.assertRaises(reports.ReportError):
                reports.date_range(bad, None, self.TODAY)

    def test_a_range_too_long_to_read_is_refused(self):
        with self.assertRaises(reports.ReportError):
            reports.date_range("2020-01-01", "2026-11-09", self.TODAY)


class WhatTheRangeDid(ReportCase):
    def test_an_empty_range_reports_zero_rather_than_breaking(self):
        report = self.report()
        self.assertEqual(report["bills"], 0)
        self.assertEqual(report["revenue"], 0)
        self.assertEqual(report["average_bill"], 0)
        self.assertIsNone(report["profit"]["margin_percent"])

    def test_bills_inside_the_range_are_counted_and_those_outside_are_not(self):
        self.bill("A", "2026-11-05", 100)
        self.bill("B", "2026-11-09", 200)
        self.bill("C", "2026-09-01", 900)   # before the default window
        report = self.report()
        self.assertEqual(report["bills"], 2)
        self.assertEqual(report["revenue"], 300)
        self.assertEqual(report["average_bill"], 150)

    def test_a_refunded_bill_is_not_a_sale(self):
        self.bill("A", "2026-11-05", 100)
        self.bill("B", "2026-11-05", 500, status="refunded")
        self.assertEqual(self.report()["revenue"], 100)

    def test_each_day_is_listed_in_order(self):
        self.bill("A", "2026-11-07", 100)
        self.bill("B", "2026-11-05", 50)
        self.bill("C", "2026-11-05", 70)
        days = self.report()["by_day"]
        self.assertEqual([d["date"] for d in days], ["2026-11-05", "2026-11-07"])
        self.assertEqual(days[0]["revenue"], 120)
        self.assertEqual(days[0]["bills"], 2)

    def test_a_bill_late_at_night_bangkok_time_stays_on_its_own_day(self):
        """18:00 UTC is 1am the next day in Bangkok. Reading it as UTC would
        file the shop's busiest hour under yesterday."""
        with self.conn:
            self.conn.execute(
                "INSERT INTO pos_orders (branch_id, order_no, closed_by_staff_id, total_amount,"
                " net_amount, payment_method, status, closed_at)"
                " VALUES (1,'LATE',2,100,100,'เงินสด (Cash)','paid','2026-11-05 18:00:00.000')")
        self.assertEqual(self.report()["by_day"][0]["date"], "2026-11-06")

    def test_takings_are_split_by_how_they_were_paid(self):
        self.bill("A", "2026-11-05", 100, method="เงินสด (Cash)")
        self.bill("B", "2026-11-05", 300, method="พร้อมเพย์ (ยืนยันโดยพนักงาน)")
        methods = {m["method"]: m["revenue"] for m in self.report()["by_method"]}
        self.assertEqual(methods["เงินสด (Cash)"], 100)
        self.assertEqual(methods["พร้อมเพย์ (ยืนยันโดยพนักงาน)"], 300)

    def test_takings_are_split_by_who_closed_the_bill(self):
        self.bill("A", "2026-11-05", 100, staff_id=2)
        self.bill("B", "2026-11-05", 400, staff_id=3)
        by_staff = {s["name"]: s["revenue"] for s in self.report()["by_staff"]}
        self.assertEqual(by_staff["แอน"], 100)
        self.assertEqual(by_staff["บี"], 400)

    def test_items_are_ranked_by_what_they_brought_in(self):
        self.bill("A", "2026-11-05", 300, lines=[("M1", "ข้าวผัด", 2, 100, 40),
                                                 ("M2", "ชาเย็น", 2, 50, 10)])
        items = self.report()["by_item"]
        self.assertEqual(items[0]["name"], "ข้าวผัด")
        self.assertEqual(items[0]["revenue"], 200)
        self.assertEqual(items[0]["qty"], 2)

    def test_items_are_grouped_into_the_shop_s_own_categories(self):
        self.menu("M1", "ข้าวผัด", "จานหลัก")
        self.menu("M2", "ชาเย็น", "เครื่องดื่ม")
        self.bill("A", "2026-11-05", 300, lines=[("M1", "ข้าวผัด", 2, 100, 40),
                                                 ("M2", "ชาเย็น", 2, 50, 10)])
        categories = {c["category"]: c["revenue"] for c in self.report()["by_category"]}
        self.assertEqual(categories["จานหลัก"], 200)
        self.assertEqual(categories["เครื่องดื่ม"], 100)

    def test_an_item_no_longer_on_the_menu_still_appears_under_no_category(self):
        self.bill("A", "2026-11-05", 100, lines=[("GONE", "เมนูเก่า", 1, 100, 0)])
        self.assertEqual(self.report()["by_category"][0]["category"], "ไม่ระบุหมวด")


class Profit(ReportCase):
    def test_profit_is_revenue_less_the_cost_recorded_on_the_bill(self):
        self.bill("A", "2026-11-05", 200, lines=[("M1", "ข้าวผัด", 2, 100, 40)])
        profit = self.report()["profit"]
        self.assertEqual(profit["revenue_with_cost"], 200)
        self.assertEqual(profit["cost"], 80)
        self.assertEqual(profit["gross_profit"], 120)
        self.assertEqual(profit["margin_percent"], 60)
        self.assertTrue(profit["complete"])

    def test_sales_with_no_cost_recorded_are_kept_out_and_named(self):
        """Treating an unknown cost as zero reads as a very profitable shop,
        right up until the owner believes it."""
        self.bill("A", "2026-11-05", 200, lines=[("M1", "ข้าวผัด", 2, 100, 40)])
        self.bill("B", "2026-11-06", 500, lines=[("OLD", "เมนูเก่า", 1, 500, 0)])
        profit = self.report()["profit"]
        self.assertEqual(profit["gross_profit"], 120)
        self.assertEqual(profit["revenue_without_cost"], 500)
        self.assertFalse(profit["complete"])

    def test_the_cost_used_is_the_one_from_the_day_of_the_sale(self):
        """A shop that raises its ingredient prices today must not see last
        month's profit change."""
        self.bill("A", "2026-11-05", 100, lines=[("M1", "ข้าวผัด", 1, 100, 30)])
        self.menu("M1", "ข้าวผัด", "จานหลัก")   # today's menu row, cost 0
        self.assertEqual(self.report()["profit"]["cost"], 30)

    def test_a_dish_sold_below_its_cost_shows_a_loss(self):
        self.bill("A", "2026-11-05", 50, lines=[("M1", "ข้าวผัด", 1, 50, 80)])
        self.assertEqual(self.report()["by_item"][0]["profit"], -30)


class TheEndpoints(ReportCase):
    def test_the_owner_reads_the_report(self):
        self.bill("A", "2026-11-05", 100)
        answer = self.signed_in().get("/api/reports/sales?branch_id=1&start=2026-11-01&end=2026-11-30")
        self.assertEqual(answer.status_code, 200, answer.text)
        self.assertEqual(answer.json()["revenue"], 100)

    def test_a_cashier_cannot(self):
        """Their own shift is their screen; last month's margins are not."""
        self.assertEqual(self.signed_in(2, "cashier").get("/api/reports/sales?branch_id=1").status_code, 403)

    def test_a_bad_date_is_refused_with_a_message_not_a_crash(self):
        answer = self.signed_in().get("/api/reports/sales?branch_id=1&start=เมื่อวาน")
        self.assertEqual(answer.status_code, 400)

    def test_the_csv_comes_back_as_a_file_excel_will_open(self):
        self.bill("A", "2026-11-05", 100, lines=[("M1", "ข้าวผัด", 1, 100, 40)])
        answer = self.signed_in().get("/api/reports/sales.csv?branch_id=1&start=2026-11-01&end=2026-11-30")
        self.assertEqual(answer.status_code, 200, answer.text)
        self.assertIn("text/csv", answer.headers["content-type"])
        self.assertIn("attachment", answer.headers["content-disposition"])
        body = answer.content.decode("utf-8")
        # The BOM is what makes Excel on Thai Windows read it as UTF-8.
        self.assertTrue(body.startswith("﻿"))
        self.assertIn("ข้าวผัด", body)
        self.assertIn("2026-11-01", body)

    def test_a_field_with_a_comma_in_it_does_not_split_the_column(self):
        report = {"start": "2026-11-01", "end": "2026-11-30", "bills": 1, "revenue": 100,
                  "average_bill": 100,
                  "profit": {"gross_profit": 0, "revenue_without_cost": 0},
                  "by_day": [], "by_method": [], "by_staff": [], "by_category": [],
                  "by_item": [{"name": 'ข้าวผัด, พิเศษ "เผ็ด"', "qty": 1, "revenue": 100,
                               "cost": 0, "profit": 100}]}
        csv = reports.sales_csv(report)
        self.assertIn('"ข้าวผัด, พิเศษ ""เผ็ด"""', csv)


if __name__ == "__main__":
    unittest.main()
