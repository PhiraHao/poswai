"""The monthly service fee: the notice, paying with a slip, the block and the ZZAX page."""

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
SERVICE_PROMPTPAY = "0899999999"


class ServiceBillingTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.folder.cleanup)
        for item in (patch.object(server, "DB_PATH", Path(self.folder.name) / "main.db"),
                     patch.object(server, "PREVIEW_ONLY", False),
                     patch.object(server, "STAFF_LIVE", True),
                     patch.object(server, "BOOTSTRAP_MANAGER_PIN", ""),
                     patch.object(server, "TABLE_QR_SECRET", "x" * 40),
                     patch.object(server, "MONTHLY_PRICE", 399.0),
                     patch.object(server, "SERVICE_PROMPTPAY_ID", SERVICE_PROMPTPAY),
                     patch.object(server, "SERVICE_EASYSLIP_API_KEY", "service-slip-key"),
                     patch.object(server, "ADMIN_KEY", ADMIN_KEY),
                     patch.object(server, "_prepared_databases", set())):
            item.start()
            self.addCleanup(item.stop)
        server.init_db()

    def client(self):
        client = TestClient(server.app)
        client.__enter__()
        self.addCleanup(lambda: client.__exit__(None, None, None))
        return client

    def open_shop(self, slug="ran-kaew", pin="owner-pin-1234"):
        client = self.client()
        response = client.post("/api/shops", json={"shop_name": "ร้านแก้ว", "slug": slug,
                                                   "owner_name": "เจ้าของ", "phone": "0812345678",
                                                   "pin": pin, "accept_terms": True},
                               headers={"x-forwarded-for": "10.9.0.1"})
        self.assertEqual(response.status_code, 200, response.text)
        self.add_menu(client)
        return client

    def add_menu(self, owner):
        self.assertEqual(owner.put("/api/inventory/ING-TEA", json={"branch_id": 1, "stock": 500}).status_code, 200)
        menu = owner.put("/api/menu/TEA", json={"branch_id": 1, "name": "ชาเย็น", "price": 50,
                                                "station": "บาร์น้ำ", "bom": [{"ingId": "ING-TEA", "qty": 2}]})
        self.assertEqual(menu.status_code, 200, menu.text)

    def set_due_date(self, slug, due: datetime.date):
        with closing(shops.connect_registry(server.DB_PATH)) as conn, conn:
            conn.execute("UPDATE shops SET trial_ends_at=? WHERE slug=?", (due.isoformat(), slug))

    def order(self, client, order_no):
        return client.post("/api/orders", json={
            "event_id": f"evt-{order_no}", "order_no": order_no, "branch_id": 1, "table_no": "T1",
            "total_amount": 50, "items": [{"id": "TEA", "name": "ชาเย็น", "price": 50, "qty": 1, "bom": []}]})

    def admin(self, client, method, path, **kwargs):
        return client.request(method, path, headers={"x-poswai-admin-key": ADMIN_KEY}, **kwargs)

    # ---------------------------------------------------------------- the trial
    def test_a_new_shop_is_on_a_thirty_day_trial_and_nothing_is_due_yet(self):
        owner = self.open_shop()
        config = owner.get("/api/config").json()["billing"]
        self.assertTrue(config["applicable"])
        self.assertEqual((config["state"], config["days_left"], config["on_trial"]), ("ok", shops.TRIAL_DAYS, True))
        self.assertEqual(config["price"], 399.0)

        body = owner.get("/api/billing").json()
        self.assertEqual(body["billing"]["state"], "ok")
        self.assertEqual(body["service_promptpay_id"], SERVICE_PROMPTPAY)
        self.assertTrue(body["slip_check_ready"] and body["may_pay"])
        self.assertEqual(body["payments"], [])
        self.assertEqual(self.order(owner, "A-1").status_code, 200)

    def test_the_app_warns_when_the_trial_is_nearly_over_and_when_it_has_passed(self):
        owner = self.open_shop()
        today = datetime.date.today()
        self.set_due_date("ran-kaew", today + datetime.timedelta(days=3))
        warning = owner.get("/api/config").json()["billing"]
        self.assertEqual((warning["state"], warning["days_left"], warning["blocked"]), ("due_soon", 3, False))
        self.assertIn("399", warning["message"])
        self.assertIn("3 วัน", warning["message"])

        self.set_due_date("ran-kaew", today)
        last_day = owner.get("/api/config").json()["billing"]
        self.assertEqual((last_day["state"], last_day["days_left"], last_day["blocked"]), ("due_soon", 0, False))
        self.assertIn("วันสุดท้าย", last_day["message"])

        self.set_due_date("ran-kaew", today - datetime.timedelta(days=2))
        late = owner.get("/api/config").json()["billing"]
        self.assertEqual((late["state"], late["days_left"], late["blocked"]), ("overdue", -2, True))
        self.assertIn("รับออเดอร์ใหม่ไม่ได้", late["message"])
        self.assertIn("ไม่ถูกลบ", late["message"])

    # ------------------------------------------------------- the overdue block
    def test_an_overdue_shop_keeps_its_data_and_reports_but_takes_no_new_order(self):
        owner = self.open_shop()
        self.assertEqual(self.order(owner, "BEFORE-1").status_code, 200)
        self.set_due_date("ran-kaew", datetime.date.today() - datetime.timedelta(days=1))

        blocked = self.order(owner, "AFTER-1")
        self.assertEqual(blocked.status_code, 402, blocked.text)
        self.assertIn("รับออเดอร์ใหม่ไม่ได้", blocked.json()["detail"])
        manual = owner.post("/api/online/manual-orders", json={
            "branch_id": 1, "channel": "GrabFood", "external_order_id": "GF-1",
            "fulfillment": "rider_pickup", "items": [{"id": "TEA", "qty": 1}]})
        self.assertEqual(manual.status_code, 402, manual.text)

        # Everything that only reads keeps working, and the earlier sale is still there.
        self.assertEqual(owner.get("/api/auth/session").status_code, 200)
        self.assertEqual([item["id"] for item in owner.get("/api/menu?branch_id=1").json()["items"]], ["TEA"])
        self.assertIn("BEFORE-1", [order["order_no"] for order in owner.get("/api/orders").json()["orders"]])
        self.assertEqual(owner.get("/api/enterprise/analytics-dashboard").status_code, 200)
        self.assertEqual(owner.get("/api/staff/overview").status_code, 200)
        self.assertTrue((server.DB_PATH.parent / "shops" / "ran-kaew.db").exists())

    def test_closing_a_bill_already_open_still_works_when_overdue(self):
        owner = self.open_shop()
        self.assertEqual(self.order(owner, "OPEN-1").status_code, 200)
        self.set_due_date("ran-kaew", datetime.date.today() - datetime.timedelta(days=5))
        paid = owner.post("/api/payments/close", json={"event_id": "pay-open-1", "order_no": "OPEN-1",
                                                       "amount": 50, "method": "เงินสด (Cash)"})
        self.assertEqual(paid.status_code, 200, paid.text)

    def test_the_original_shop_and_the_demo_are_never_billed(self):
        with sqlite3.connect(server.DB_PATH) as conn:
            conn.execute("INSERT INTO branches(id,name) VALUES(1,'Main')")
            conn.execute("INSERT INTO staffs(id,branch_id,name,role,pin_code_hash) VALUES(1,1,'เจ้าของ','owner',?)",
                         (server.hash_pin("main-owner-pin"),))
        main = self.client()
        self.assertFalse(main.get("/api/config").json()["billing"]["applicable"])
        self.assertEqual(main.post("/api/auth/login", json={"staff_id": 1, "pin": "main-owner-pin"}).status_code, 200)
        self.add_menu(main)
        self.assertEqual(self.order(main, "MAIN-1").status_code, 200)
        body = main.get("/api/billing").json()
        self.assertEqual(body["billing"]["state"], "hosted")
        self.assertNotIn("payments", body)
        self.assertEqual(main.post("/api/billing/pay", json={"event_id": "fee-main-1", "amount": 399,
                                                             "slip_image": "x"}).status_code, 409)

    # ------------------------------------------------------- paying with a slip
    def test_a_verified_slip_moves_the_due_date_one_month_and_reopens_ordering(self):
        owner = self.open_shop()
        due = datetime.date.today() - datetime.timedelta(days=3)
        self.set_due_date("ran-kaew", due)
        with patch.object(server, "verify_bank_slip", return_value="TRANSREF-1") as slip:
            paid = owner.post("/api/billing/pay", json={"event_id": "fee-1", "amount": 399,
                                                        "slip_image": "data:image/png;base64,AAAA"})
        self.assertEqual(paid.status_code, 200, paid.text)
        body = paid.json()
        expected = billing.add_months(datetime.date.today(), 1).isoformat()
        self.assertEqual((body["paid_until"], body["months"], body["existing"]), (expected, 1, False))
        self.assertEqual(body["slip_reference"], "TRANSREF-1")
        self.assertEqual(slip.call_args.args[1], 399.0)
        self.assertEqual(slip.call_args.args[2], "service-slip-key")
        self.assertEqual(body["billing"]["state"], "ok")
        self.assertFalse(body["billing"]["on_trial"])
        self.assertEqual(self.order(owner, "AFTER-PAY").status_code, 200)

        history = owner.get("/api/billing").json()["payments"]
        self.assertEqual(len(history), 1)
        self.assertEqual((history[0]["amount"], history[0]["method"], history[0]["confirmed_by"]),
                         (399.0, "promptpay_slip", "easyslip"))

    def test_paying_early_adds_to_the_days_that_are_left(self):
        owner = self.open_shop()
        due = datetime.date.today() + datetime.timedelta(days=10)
        self.set_due_date("ran-kaew", due)
        with patch.object(server, "verify_bank_slip", return_value="TRANSREF-EARLY"):
            paid = owner.post("/api/billing/pay", json={"event_id": "fee-early", "amount": 399,
                                                        "slip_image": "data:image/png;base64,AAAA"})
        self.assertEqual(paid.status_code, 200, paid.text)
        self.assertEqual(paid.json()["paid_until"], billing.add_months(due, 1).isoformat())

    def test_three_months_at_once_cost_three_times_the_price(self):
        owner = self.open_shop()
        due = datetime.date.today()
        self.set_due_date("ran-kaew", due)
        with patch.object(server, "verify_bank_slip", return_value="TRANSREF-3M"):
            wrong = owner.post("/api/billing/pay", json={"event_id": "fee-3m", "amount": 399, "months": 3,
                                                         "slip_image": "data:image/png;base64,AAAA"})
            self.assertEqual(wrong.status_code, 409, wrong.text)
            self.assertIn("1,197.00", wrong.json()["detail"])
            paid = owner.post("/api/billing/pay", json={"event_id": "fee-3m", "amount": 1197, "months": 3,
                                                        "slip_image": "data:image/png;base64,AAAA"})
        self.assertEqual(paid.status_code, 200, paid.text)
        self.assertEqual(paid.json()["paid_until"], billing.add_months(due, 3).isoformat())

    def test_a_retried_payment_does_not_buy_a_second_month(self):
        owner = self.open_shop()
        self.set_due_date("ran-kaew", datetime.date.today())
        with patch.object(server, "verify_bank_slip", return_value="TRANSREF-RETRY"):
            first = owner.post("/api/billing/pay", json={"event_id": "fee-retry", "amount": 399,
                                                         "slip_image": "data:image/png;base64,AAAA"})
            again = owner.post("/api/billing/pay", json={"event_id": "fee-retry", "amount": 399,
                                                         "slip_image": "data:image/png;base64,AAAA"})
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(again.status_code, 200, again.text)
        self.assertTrue(again.json()["existing"])
        self.assertEqual(again.json()["paid_until"], first.json()["paid_until"])
        self.assertEqual(len(owner.get("/api/billing").json()["payments"]), 1)

    def test_the_same_slip_cannot_pay_twice_under_a_new_event_id(self):
        owner = self.open_shop()
        self.set_due_date("ran-kaew", datetime.date.today())
        with patch.object(server, "verify_bank_slip", return_value="TRANSREF-SAME"):
            self.assertEqual(owner.post("/api/billing/pay", json={"event_id": "fee-a", "amount": 399,
                                                                  "slip_image": "data:image/png;base64,AAAA"}).status_code, 200)
            reused = owner.post("/api/billing/pay", json={"event_id": "fee-b", "amount": 399,
                                                          "slip_image": "data:image/png;base64,AAAA"})
        self.assertEqual(reused.status_code, 409, reused.text)
        self.assertIn("สลิปนี้", reused.json()["detail"])

    def test_a_rejected_slip_changes_nothing(self):
        owner = self.open_shop()
        due = datetime.date.today() - datetime.timedelta(days=1)
        self.set_due_date("ran-kaew", due)
        with patch.object(server, "verify_bank_slip",
                          side_effect=server.SlipVerificationError("ยอดโอนในสลิปไม่ตรงกับยอดบิล")):
            rejected = owner.post("/api/billing/pay", json={"event_id": "fee-bad", "amount": 399,
                                                            "slip_image": "data:image/png;base64,AAAA"})
        self.assertEqual(rejected.status_code, 422)
        self.assertEqual(owner.get("/api/billing").json()["billing"]["due_date"], due.isoformat())
        self.assertEqual(self.order(owner, "STILL-BLOCKED").status_code, 402)

    def test_only_the_owner_or_manager_can_pay_the_service_fee(self):
        owner = self.open_shop()
        created = owner.post("/api/staff", json={"branch_id": 1, "name": "แคชเชียร์", "role": "cashier",
                                                 "pin": "cashier-pin-12345"})
        self.assertEqual(created.status_code, 200, created.text)
        cashier = self.client()
        signed_in = cashier.post("/api/auth/login", json={"shop": "ran-kaew", "staff_id": created.json()["staff_id"],
                                                          "pin": "cashier-pin-12345"})
        self.assertEqual(signed_in.status_code, 200, signed_in.text)
        seen = cashier.get("/api/billing").json()
        self.assertTrue(seen["billing"]["applicable"])
        self.assertFalse(seen["may_pay"])
        self.assertNotIn("payments", seen)
        refused = cashier.post("/api/billing/pay", json={"event_id": "fee-cashier", "amount": 399,
                                                         "slip_image": "data:image/png;base64,AAAA"})
        self.assertEqual(refused.status_code, 403)
        self.assertEqual(self.client().get("/api/billing").status_code, 401)

    def test_paying_needs_the_service_account_and_slip_check_to_be_configured(self):
        owner = self.open_shop()
        with patch.object(server, "SERVICE_EASYSLIP_API_KEY", ""):
            unset = owner.post("/api/billing/pay", json={"event_id": "fee-noslip", "amount": 399,
                                                         "slip_image": "data:image/png;base64,AAAA"})
        self.assertEqual(unset.status_code, 503)
        self.assertIn("ZZAX Studio", unset.json()["detail"])
        with patch.object(server, "SERVICE_PROMPTPAY_ID", ""):
            no_account = owner.post("/api/billing/pay", json={"event_id": "fee-noacct", "amount": 399,
                                                              "slip_image": "data:image/png;base64,AAAA"})
            self.assertEqual(no_account.status_code, 503)
            self.assertEqual(owner.get("/api/billing").json()["service_promptpay_id"], "")
        bad_months = owner.post("/api/billing/pay", json={"event_id": "fee-months", "amount": 399, "months": 13,
                                                          "slip_image": "data:image/png;base64,AAAA"})
        self.assertEqual(bad_months.status_code, 400)
        bad_event = owner.post("/api/billing/pay", json={"event_id": "x", "amount": 399,
                                                         "slip_image": "data:image/png;base64,AAAA"})
        self.assertEqual(bad_event.status_code, 400)

    # -------------------------------------------------------- the ZZAX Studio page
    def test_the_zzax_page_lists_every_shop_with_its_payment_state(self):
        self.open_shop("ran-nueng")
        self.open_shop("ran-song", pin="owner-pin-5678")
        self.set_due_date("ran-song", datetime.date.today() - datetime.timedelta(days=4))
        studio = self.client()
        listed = self.admin(studio, "GET", "/api/admin/shops")
        self.assertEqual(listed.status_code, 200, listed.text)
        body = listed.json()
        self.assertEqual(body["price"], 399.0)
        self.assertEqual(body["service_promptpay_id"], SERVICE_PROMPTPAY)
        states = {shop["slug"]: shop["state"] for shop in body["shops"]}
        self.assertEqual(states, {"ran-nueng": "ok", "ran-song": "overdue"})
        late = next(shop for shop in body["shops"] if shop["slug"] == "ran-song")
        self.assertEqual((late["days_left"], late["payments"], late["paid_total"], late["on_trial"]),
                         (-4, 0, 0.0, True))
        self.assertEqual((late["owner_name"], late["phone"]), ("เจ้าของ", "0812345678"))
        self.assertEqual(self.admin(studio, "GET", "/api/admin/shops/ran-nueng/payments").json()["payments"], [])
        self.assertEqual(self.admin(studio, "GET", "/api/admin/shops/ran-mai/payments").status_code, 404)
        self.assertEqual(studio.get("/admin").status_code, 200)

    def test_the_zzax_page_is_closed_without_the_right_key(self):
        self.open_shop()
        anyone = self.client()
        self.assertEqual(anyone.get("/api/admin/shops").status_code, 401)
        self.assertEqual(anyone.get("/api/admin/shops", headers={"x-poswai-admin-key": "wrong-key"}).status_code, 401)
        # A shop's owner session is not a way in either.
        owner = self.open_shop("ran-sam", pin="owner-pin-9999")
        self.assertEqual(owner.get("/api/admin/shops").status_code, 401)
        self.assertEqual(owner.post("/api/admin/shops/ran-sam/payments",
                                    json={"event_id": "self-serve", "amount": 1}).status_code, 401)
        with patch.object(server, "ADMIN_KEY", ""):
            self.assertEqual(self.admin(anyone, "GET", "/api/admin/shops").status_code, 503)

    def test_the_studio_can_confirm_a_transfer_by_hand_and_reopen_the_shop(self):
        owner = self.open_shop()
        self.set_due_date("ran-kaew", datetime.date.today() - datetime.timedelta(days=6))
        self.assertEqual(self.order(owner, "BLOCKED-1").status_code, 402)
        studio = self.client()
        confirmed = self.admin(studio, "POST", "/api/admin/shops/RAN-KAEW/payments",
                               json={"event_id": "manual-1", "amount": 399, "note": "โอนมา 17 ต.ค."})
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertEqual(confirmed.json()["paid_until"], billing.add_months(datetime.date.today(), 1).isoformat())
        self.assertEqual(self.order(owner, "REOPENED-1").status_code, 200)

        repeat = self.admin(studio, "POST", "/api/admin/shops/ran-kaew/payments",
                            json={"event_id": "manual-1", "amount": 399})
        self.assertTrue(repeat.json()["existing"])
        self.assertEqual(self.admin(studio, "POST", "/api/admin/shops/ran-mai/payments",
                                    json={"event_id": "manual-2", "amount": 399}).status_code, 404)
        self.assertEqual(self.admin(studio, "POST", "/api/admin/shops/ran-kaew/payments",
                                    json={"event_id": "manual-3", "amount": 0}).status_code, 400)
        self.assertEqual(self.admin(studio, "POST", "/api/admin/shops/ran-kaew/payments",
                                    json={"event_id": "manual-4", "amount": 399, "months": 99}).status_code, 400)
        history = self.admin(studio, "GET", "/api/admin/shops/ran-kaew/payments").json()
        self.assertEqual(len(history["payments"]), 1)
        self.assertEqual((history["payments"][0]["confirmed_by"], history["payments"][0]["note"]),
                         ("zzax-admin", "โอนมา 17 ต.ค."))
        self.assertIsNone(history["payments"][0]["slip_reference"])


class BillingRulesTest(unittest.TestCase):
    """The date arithmetic on its own, including the months that are too short."""

    def test_adding_a_month_clamps_to_the_end_of_a_short_month(self):
        self.assertEqual(billing.add_months(datetime.date(2026, 1, 31), 1), datetime.date(2026, 2, 28))
        self.assertEqual(billing.add_months(datetime.date(2028, 1, 31), 1), datetime.date(2028, 2, 29))
        self.assertEqual(billing.add_months(datetime.date(2026, 3, 31), 1), datetime.date(2026, 4, 30))
        self.assertEqual(billing.add_months(datetime.date(2026, 12, 15), 1), datetime.date(2027, 1, 15))
        self.assertEqual(billing.add_months(datetime.date(2026, 10, 17), 12), datetime.date(2027, 10, 17))
        with self.assertRaises(ValueError):
            billing.add_months(datetime.date(2026, 10, 17), 0)

    def test_an_unknown_shop_has_no_billing_state(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            main_db = Path(folder) / "main.db"
            with self.assertRaises(shops.ShopError) as caught:
                billing.billing_state(main_db, "ran-ที่ไม่มี", price=399)
            self.assertEqual(caught.exception.status, 404)
            self.assertEqual(billing.all_shops_billing(main_db, price=399), [])

    def test_the_state_follows_the_days_that_are_left(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            main_db = Path(folder) / "main.db"
            shops.reserve_shop(main_db, slug="ran-test", name="ร้าน", owner_name="เจ้าของ",
                               phone="0812345678", client_key="1.2.3.4", max_shops=10)
            today = datetime.date.today()
            for offset, expected in ((20, "ok"), (billing.WARN_DAYS, "due_soon"), (0, "due_soon"), (-1, "overdue")):
                with closing(shops.connect_registry(main_db)) as conn, conn:
                    conn.execute("UPDATE shops SET trial_ends_at=? WHERE slug='ran-test'",
                                 ((today + datetime.timedelta(days=offset)).isoformat(),))
                state = billing.billing_state(main_db, "ran-test", price=399)
                self.assertEqual(state["state"], expected, offset)
                self.assertEqual(state["blocked"], expected == "overdue")

    def test_a_late_shop_owes_one_month_from_today_not_every_missed_month(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            main_db = Path(folder) / "main.db"
            shops.reserve_shop(main_db, slug="ran-late", name="ร้าน", owner_name="เจ้าของ",
                               phone="0812345678", client_key="1.2.3.4", max_shops=10)
            today = datetime.date.today()
            with closing(shops.connect_registry(main_db)) as conn, conn:
                conn.execute("UPDATE shops SET trial_ends_at=? WHERE slug='ran-late'",
                             ((today - datetime.timedelta(days=200)).isoformat(),))
            result = billing.record_payment(main_db, "ran-late", amount=399, method="manual",
                                            event_id="one-month", confirmed_by="zzax-admin", price=399)
            self.assertEqual(result["paid_until"], billing.add_months(today, 1).isoformat())
            self.assertFalse(result["billing"]["blocked"])

    def test_billing_refuses_an_unknown_method_or_the_hosted_shops(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            main_db = Path(folder) / "main.db"
            shops.reserve_shop(main_db, slug="ran-guard", name="ร้าน", owner_name="เจ้าของ",
                               phone="0812345678", client_key="1.2.3.4", max_shops=10)
            for kwargs, status in (
                    ({"slug": "main"}, 400),
                    ({"slug": "demo"}, 400),
                    ({"slug": "ran-guard", "method": "cash"}, 400),
                    ({"slug": "ran-guard", "event_id": ""}, 400),
                    ({"slug": "ran-guard", "months": 0}, 400),
                    ({"slug": "ran-guard", "amount": -1}, 400),
                    ({"slug": "ran-mai-mi"}, 404)):
                call = {"amount": 399.0, "method": "manual", "event_id": "guard-" + str(status),
                        "confirmed_by": "zzax-admin", "price": 399.0, **kwargs}
                slug = call.pop("slug")
                with self.assertRaises(shops.ShopError) as caught:
                    billing.record_payment(main_db, slug, **call)
                self.assertEqual(caught.exception.status, status, call)


if __name__ == "__main__":
    unittest.main()
