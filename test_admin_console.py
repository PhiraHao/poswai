"""The ZZAX Studio page: free extensions, suspending a shop, reminders and exports."""

import datetime
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import line_pos_server as server
import poswai_billing as billing
import poswai_shops as shops

ADMIN_KEY = "zzax-admin-key-for-tests-0123456789"


class AdminConsoleTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.folder.cleanup)
        for item in (patch.object(server, "DB_PATH", Path(self.folder.name) / "main.db"),
                     patch.object(server, "PREVIEW_ONLY", False),
                     patch.object(server, "STAFF_LIVE", True),
                     patch.object(server, "BOOTSTRAP_MANAGER_PIN", ""),
                     patch.object(server, "TABLE_QR_SECRET", "x" * 40),
                     patch.object(server, "MONTHLY_PRICE", 399.0),
                     patch.object(server, "SERVICE_PROMPTPAY_ID", "0899999999"),
                     patch.object(server, "ADMIN_KEY", ADMIN_KEY),
                     patch.object(server, "SUPPORT_CONTACT", " (LINE @poswai)"),
                     patch.object(server, "_prepared_databases", set())):
            item.start()
            self.addCleanup(item.stop)
        server.init_db()
        self.studio = self.client()

    def client(self):
        client = TestClient(server.app)
        client.__enter__()
        self.addCleanup(lambda: client.__exit__(None, None, None))
        return client

    def open_shop(self, slug="ran-kaew", name="ร้านแก้ว", pin="owner-pin-1234"):
        client = self.client()
        response = client.post("/api/shops", json={"shop_name": name, "slug": slug,
                                                   "owner_name": "เจ้าของ", "phone": "0812345678",
                                                   "pin": pin, "accept_terms": True},
                               headers={"x-forwarded-for": f"10.9.0.{len(slug)}"})
        self.assertEqual(response.status_code, 200, response.text)
        return client

    def set_due_date(self, slug, due: datetime.date):
        with closing(shops.connect_registry(server.DB_PATH)) as conn, conn:
            conn.execute("UPDATE shops SET trial_ends_at=? WHERE slug=?", (due.isoformat(), slug))

    def admin(self, method, path, **kwargs):
        return self.studio.request(method, path, headers={"x-poswai-admin-key": ADMIN_KEY}, **kwargs)

    def shop_row(self, slug, include_closed=False):
        listed = self.admin("GET", f"/api/admin/shops?include_closed={str(include_closed).lower()}").json()
        return next((shop for shop in listed["shops"] if shop["slug"] == slug), None)

    # ------------------------------------------------------- free extensions
    def test_free_days_move_the_due_date_without_counting_as_income(self):
        owner = self.open_shop()
        due = datetime.date.today() - datetime.timedelta(days=2)
        self.set_due_date("ran-kaew", due)
        granted = self.admin("POST", "/api/admin/shops/ran-kaew/grants",
                             json={"event_id": "grant-1", "days": 10, "reason": "ชดเชยระบบล่ม 2 วัน"})
        self.assertEqual(granted.status_code, 200, granted.text)
        body = granted.json()
        self.assertEqual(body["paid_until"], (datetime.date.today() + datetime.timedelta(days=10)).isoformat())
        self.assertEqual((body["days"], body["months"]), (10, None))
        self.assertFalse(body["billing"]["blocked"])

        row = self.shop_row("ran-kaew")
        self.assertEqual((row["paid_total"], row["payments"], row["grants"]), (0.0, 0, 1))
        self.assertTrue(row["on_trial"])  # a gift does not turn them into a paying customer
        self.assertEqual(self.admin("GET", "/api/admin/revenue").json()["months"], [])
        history = self.admin("GET", "/api/admin/shops/ran-kaew/payments").json()["payments"]
        self.assertEqual((history[0]["method"], history[0]["amount"]), ("grant", 0.0))
        self.assertEqual(history[0]["note"], "ชดเชยระบบล่ม 2 วัน")
        self.assertEqual(owner.get("/api/billing").json()["billing"]["state"], "ok")

    def test_a_free_extension_has_to_say_why_and_stay_inside_a_year(self):
        self.open_shop()
        for payload, status in (({"event_id": "g-1", "days": 7, "reason": "  "}, 400),
                                ({"event_id": "g-2", "days": 0, "reason": "ชดเชย"}, 400),
                                ({"event_id": "g-3", "days": 400, "reason": "ชดเชย"}, 400),
                                ({"event_id": "x", "days": 7, "reason": "ชดเชย"}, 400)):
            response = self.admin("POST", "/api/admin/shops/ran-kaew/grants", json=payload)
            self.assertEqual(response.status_code, status, response.text)
        self.assertEqual(self.admin("POST", "/api/admin/shops/ran-mai/grants",
                                    json={"event_id": "g-4", "days": 7, "reason": "ชดเชย"}).status_code, 404)
        repeat = {"event_id": "g-same", "days": 5, "reason": "ชดเชย"}
        first = self.admin("POST", "/api/admin/shops/ran-kaew/grants", json=repeat)
        again = self.admin("POST", "/api/admin/shops/ran-kaew/grants", json=repeat)
        self.assertTrue(again.json()["existing"])
        self.assertEqual(again.json()["paid_until"], first.json()["paid_until"])

    def test_money_received_by_hand_is_still_counted_as_income(self):
        self.open_shop()
        self.admin("POST", "/api/admin/shops/ran-kaew/payments",
                   json={"event_id": "manual-1", "amount": 399, "note": "โอนมา"})
        row = self.shop_row("ran-kaew")
        self.assertEqual((row["paid_total"], row["payments"], row["grants"]), (399.0, 1, 0))
        self.assertFalse(row["on_trial"])
        months = self.admin("GET", "/api/admin/revenue").json()["months"]
        self.assertEqual(len(months), 1)
        self.assertEqual((months[0]["amount"], months[0]["payments"], months[0]["shops"]), (399.0, 1, 1))
        self.assertTrue(months[0]["is_current"])

    # ----------------------------------------------------- suspend and close
    def test_a_suspended_shop_is_told_so_instead_of_landing_in_another_shop(self):
        owner = self.open_shop()
        stopped = self.admin("POST", "/api/admin/shops/ran-kaew/status",
                             json={"status": "suspended", "reason": "ค้างชำระหลายเดือน"})
        self.assertEqual(stopped.status_code, 200, stopped.text)
        self.assertTrue(stopped.json()["data_kept"])

        visitor = self.client()
        page = visitor.get("/?shop=ran-kaew")
        self.assertEqual(page.status_code, 403)
        self.assertIn("ถูกระงับการใช้งานชั่วคราว", page.text)
        self.assertIn("ค้างชำระหลายเดือน", page.text)
        self.assertIn("LINE @poswai", page.text)
        self.assertNotIn("โหมดตัวอย่าง", page.text)  # never quietly the main shop instead

        refused = visitor.get("/api/config?shop=ran-kaew")
        self.assertEqual(refused.status_code, 403)
        self.assertIn("ร้านแก้ว", refused.json()["detail"])
        login = visitor.post("/api/auth/login", json={"shop": "ran-kaew", "staff_id": 1, "pin": "owner-pin-1234"})
        self.assertEqual(login.status_code, 403)
        self.assertIn("ถูกระงับ", login.json()["detail"])
        # An owner who was already signed in cannot keep working either.
        self.assertEqual(owner.get("/api/auth/session").status_code, 403)
        self.assertEqual(self.shop_row("ran-kaew")["state"], "suspended")

        back = self.admin("POST", "/api/admin/shops/ran-kaew/status", json={"status": "active"})
        self.assertEqual(back.status_code, 200, back.text)
        self.assertEqual(owner.get("/api/auth/session").status_code, 200)
        self.assertEqual(self.shop_row("ran-kaew")["state"], "ok")

    def test_closing_a_shop_hides_it_without_deleting_anything(self):
        owner = self.open_shop()
        database = server.DB_PATH.parent / "shops" / "ran-kaew.db"
        self.assertTrue(database.exists())
        closed = self.admin("POST", "/api/admin/shops/ran-kaew/status",
                            json={"status": "closed", "reason": "เจ้าของเลิกกิจการ"})
        self.assertEqual(closed.status_code, 200, closed.text)

        self.assertIsNone(self.shop_row("ran-kaew"))
        hidden = self.shop_row("ran-kaew", include_closed=True)
        self.assertEqual((hidden["state"], hidden["status_reason"]), ("closed", "เจ้าของเลิกกิจการ"))
        self.assertTrue(database.exists())
        self.assertEqual(owner.get("/api/auth/session").status_code, 403)
        page = self.client().get("/?shop=ran-kaew")
        self.assertIn("ปิดการใช้งานถาวร", page.text)
        self.assertIn("ข้อมูลของร้านยังถูกเก็บไว้", page.text)

        reopened = self.admin("POST", "/api/admin/shops/ran-kaew/status", json={"status": "active"})
        self.assertEqual(reopened.status_code, 200, reopened.text)
        self.assertEqual(owner.get("/api/auth/session").status_code, 200)
        self.assertEqual(self.shop_row("ran-kaew")["state"], "ok")

    def test_stopping_a_shop_needs_a_reason_and_a_known_status(self):
        self.open_shop()
        self.assertEqual(self.admin("POST", "/api/admin/shops/ran-kaew/status",
                                    json={"status": "suspended", "reason": "x"}).status_code, 400)
        self.assertEqual(self.admin("POST", "/api/admin/shops/ran-kaew/status",
                                    json={"status": "deleted", "reason": "เลิกใช้"}).status_code, 400)
        self.assertEqual(self.admin("POST", "/api/admin/shops/ran-mai/status",
                                    json={"status": "suspended", "reason": "เลิกใช้"}).status_code, 404)
        self.assertEqual(self.shop_row("ran-kaew")["status"], "active")

    def test_an_overdue_shop_is_not_treated_as_suspended(self):
        self.open_shop()
        self.set_due_date("ran-kaew", datetime.date.today() - datetime.timedelta(days=1))
        row = self.shop_row("ran-kaew")
        self.assertEqual((row["state"], row["status"], row["in_service"]), ("overdue", "active", True))
        self.assertEqual(self.client().get("/?shop=ran-kaew").status_code, 200)

    # ------------------------------------------------------------ reminders
    def _link_owner_line(self, slug, line_id):
        with sqlite3.connect(server.DB_PATH.parent / "shops" / f"{slug}.db") as conn:
            conn.execute("UPDATE staffs SET line_user_id=? WHERE role='owner'", (line_id,))

    def test_reminders_go_to_linked_owners_and_leave_the_rest_to_be_sent_by_hand(self):
        self.open_shop("ran-link", name="ร้านผูกไลน์")
        self.open_shop("ran-phone", name="ร้านยังไม่ผูก")
        self.open_shop("ran-ok", name="ร้านยังไม่ถึงกำหนด")
        self._link_owner_line("ran-link", "U-owner-1")
        self.set_due_date("ran-link", datetime.date.today() + datetime.timedelta(days=2))
        self.set_due_date("ran-phone", datetime.date.today() - datetime.timedelta(days=3))

        sent = self.admin("POST", "/api/admin/reminders")
        self.assertEqual(sent.status_code, 200, sent.text)
        body = sent.json()
        self.assertEqual(body["due"], 2)
        self.assertEqual([entry["slug"] for entry in body["queued"]], ["ran-link"])
        self.assertEqual([entry["slug"] for entry in body["manual"]], ["ran-phone"])
        self.assertEqual(body["failed"], [])
        manual = body["manual"][0]
        self.assertEqual(manual["phone"], "0812345678")
        self.assertIn("เลยกำหนดมาแล้ว 3 วัน", manual["message"])
        self.assertIn("399", manual["message"])

        # The queue the background worker drains is the main database's outbox.
        with sqlite3.connect(server.DB_PATH) as conn:
            queued = conn.execute("SELECT recipient,message_json FROM line_notification_outbox").fetchall()
        self.assertEqual(len(queued), 1)
        self.assertEqual(queued[0][0], "U-owner-1")
        self.assertIn("ร้านผูกไลน์", queued[0][1])

        # Sending twice on the same due date does not queue the same message again.
        self.assertEqual(self.admin("POST", "/api/admin/reminders").status_code, 200)
        with sqlite3.connect(server.DB_PATH) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM line_notification_outbox").fetchone()[0], 1)

    def test_reminders_skip_shops_that_are_out_of_service(self):
        self.open_shop("ran-stop")
        self._link_owner_line("ran-stop", "U-owner-stop")
        self.set_due_date("ran-stop", datetime.date.today() - datetime.timedelta(days=1))
        self.admin("POST", "/api/admin/shops/ran-stop/status",
                   json={"status": "suspended", "reason": "ค้างชำระ"})
        body = self.admin("POST", "/api/admin/reminders").json()
        self.assertEqual((body["due"], body["queued"], body["manual"]), (0, [], []))

    # -------------------------------------------------------------- exports
    def test_the_exports_open_in_thai_excel_and_cover_closed_shops_and_grants(self):
        self.open_shop("ran-csv", name="ร้านซีเอสวี")
        self.admin("POST", "/api/admin/shops/ran-csv/payments",
                   json={"event_id": "manual-csv", "amount": 399, "note": "โอนมา 17 ต.ค."})
        self.admin("POST", "/api/admin/shops/ran-csv/grants",
                   json={"event_id": "grant-csv", "days": 3, "reason": "ชดเชย"})
        self.admin("POST", "/api/admin/shops/ran-csv/status",
                   json={"status": "closed", "reason": "เลิกกิจการ"})

        listed = self.admin("GET", "/api/admin/export/shops.csv")
        self.assertEqual(listed.status_code, 200)
        self.assertTrue(listed.text.startswith("﻿"))  # Excel in Thai needs the BOM
        self.assertIn("text/csv", listed.headers["content-type"])
        self.assertIn("poswai-shops.csv", listed.headers["content-disposition"])
        self.assertIn("ร้านซีเอสวี", listed.text)
        self.assertIn("closed", listed.text)  # a closed shop is still in the export

        payments = self.admin("GET", "/api/admin/export/payments.csv")
        self.assertTrue(payments.text.startswith("﻿"))
        self.assertIn("โอนมา 17 ต.ค.", payments.text)
        self.assertIn("grant", payments.text)
        self.assertEqual(len([line for line in payments.text.strip().splitlines() if "ran-csv" in line]), 2)

    # ----------------------------------------------------------- the key
    def test_every_new_admin_route_needs_the_key(self):
        self.open_shop()
        anyone = self.client()
        for method, path, payload in (
                ("POST", "/api/admin/shops/ran-kaew/grants", {"event_id": "g-9", "days": 1, "reason": "ชดเชย"}),
                ("POST", "/api/admin/shops/ran-kaew/status", {"status": "suspended", "reason": "ทดสอบ"}),
                ("POST", "/api/admin/reminders", {}),
                ("GET", "/api/admin/revenue", None),
                ("GET", "/api/admin/export/shops.csv", None),
                ("GET", "/api/admin/export/payments.csv", None)):
            refused = anyone.request(method, path, **({"json": payload} if payload is not None else {}))
            self.assertEqual(refused.status_code, 401, f"{method} {path}: {refused.text}")
            wrong = anyone.request(method, path, headers={"x-poswai-admin-key": "nope"},
                                   **({"json": payload} if payload is not None else {}))
            self.assertEqual(wrong.status_code, 401, f"{method} {path}")
        self.assertEqual(self.shop_row("ran-kaew")["status"], "active")


class RegistryUpgradeTest(unittest.TestCase):
    """A registry written before "closed" existed keeps its rows when it is upgraded."""

    def test_an_old_registry_gains_the_closed_status_without_losing_shops(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            main_db = Path(folder) / "main.db"
            registry = shops.registry_path(main_db)
            registry.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(registry)) as conn, conn:
                conn.execute("""CREATE TABLE shops (
                    slug TEXT PRIMARY KEY, name TEXT NOT NULL, owner_name TEXT NOT NULL,
                    phone TEXT NOT NULL, promptpay_id TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','suspended')),
                    trial_ends_at TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
                conn.execute("INSERT INTO shops(slug,name,owner_name,phone,trial_ends_at) "
                             "VALUES('ran-kao','ร้านเก่า','เจ้าของ','0812345678','2026-12-31')")

            # Reading it through the current code upgrades the table in place.
            self.assertEqual(shops.get_shop(main_db, "ran-kao")["status"], "active")
            kept = shops.set_status(main_db, "ran-kao", "closed", "เลิกกิจการ")
            self.assertEqual((kept["status"], kept["status_reason"], kept["trial_ends_at"]),
                             ("closed", "เลิกกิจการ", "2026-12-31"))
            listed = billing.all_shops_billing(main_db, price=399, include_closed=True)
            self.assertEqual([entry["slug"] for entry in listed], ["ran-kao"])
            self.assertEqual(billing.all_shops_billing(main_db, price=399), [])


if __name__ == "__main__":
    unittest.main()
