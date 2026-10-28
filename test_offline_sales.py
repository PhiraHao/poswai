"""Sales a till made while the shop's internet was down.

When the line comes back the queue reaches the server — sometimes after a dish
sold out, a price changed or the stock ran short. The food was served and the
money taken by then, so the server records what happened, at the price the
customer paid, and writes down every difference for the owner to check. A
guest ordering from a table QR is still held to today's menu.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import line_pos_server as server

CASH = "เงินสด (Cash)"


class OfflineSalesTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.folder.cleanup)
        for item in (patch.object(server, "DB_PATH", Path(self.folder.name) / "offline.db"),
                     patch.object(server, "PREVIEW_ONLY", False),
                     patch.object(server, "STAFF_LIVE", True),
                     patch.object(server, "BOOTSTRAP_MANAGER_PIN", ""),
                     patch.object(server, "TABLE_QR_SECRET", "x" * 40),
                     patch.object(server, "_prepared_databases", set())):
            item.start()
            self.addCleanup(item.stop)
        server.init_db()
        with sqlite3.connect(server.DB_PATH) as conn:
            conn.execute("INSERT INTO branches(id,name) VALUES(1,'One')")
            for staff_id, role in ((1, "manager"), (2, "cashier"), (3, "kitchen"), (4, "cashier")):
                conn.execute("INSERT INTO staffs(id,branch_id,name,role,pin_code_hash) VALUES(?,1,?,?,?)",
                             (staff_id, f"{role}{staff_id}", role, server.hash_pin(f"secure-pin-{staff_id}")))
        self.manager = self.signed_in(1)
        for item_id, name, price in (("M1", "ต้มยำกุ้ง", 120), ("M2", "ชาไทย", 50)):
            self.assertEqual(self.manager.put(f"/api/menu/{item_id}", json={
                "branch_id": 1, "name": name, "price": price,
                "bom": [{"ingId": "shrimp", "qty": 2}] if item_id == "M1" else []}).status_code, 200)
        with sqlite3.connect(server.DB_PATH) as conn:
            conn.execute("INSERT INTO inventory(branch_id,ingredient_id,stock) VALUES(1,'shrimp',3)")
        self.cashier = self.signed_in(2)

    def signed_in(self, staff_id):
        client = TestClient(server.app)
        client.__enter__()
        self.addCleanup(lambda: client.__exit__(None, None, None))
        self.assertEqual(client.post("/api/auth/login", json={
            "staff_id": staff_id, "pin": f"secure-pin-{staff_id}"}).status_code, 200)
        return client

    def order(self, client, order_no, items, total, offline=True):
        body = {"event_id": "e-" + order_no, "order_no": order_no, "branch_id": 1, "table_no": "5",
                "total_amount": total,
                "items": [{"id": item_id, "name": name, "price": price, "qty": qty}
                          for item_id, name, price, qty in items]}
        if offline:
            body["offline_at"] = "2026-10-18T19:05:00Z"
        return client.post("/api/orders", json=body)

    def notes(self, order_no):
        with sqlite3.connect(server.DB_PATH) as conn:
            row = conn.execute("SELECT notes_json,taken_by FROM offline_sales WHERE order_no=?",
                               (order_no,)).fetchone()
        return row

    def stock(self, ingredient="shrimp"):
        with sqlite3.connect(server.DB_PATH) as conn:
            return conn.execute("SELECT stock FROM inventory WHERE branch_id=1 AND ingredient_id=?",
                                (ingredient,)).fetchone()[0]

    # ------------------------------------------------------------ the order
    def test_a_dish_sold_out_since_is_recorded_and_flagged(self):
        self.assertEqual(self.manager.patch("/api/menu/M2", json={"branch_id": 1, "sold_out": True}).status_code, 200)
        reply = self.order(self.cashier, "OFF1", [("M2", "ชาไทย", 50, 1)], 50)
        self.assertEqual(reply.status_code, 200, reply.text)
        self.assertIn("ชาไทย ถูกตั้งว่าหมดไปแล้ว", self.notes("OFF1")[0])

    def test_the_price_the_customer_paid_is_the_price_recorded(self):
        self.manager.put("/api/menu/M2", json={"branch_id": 1, "name": "ชาไทย", "price": 60})
        reply = self.order(self.cashier, "OFF2", [("M2", "ชาไทย", 50, 2)], 100)
        self.assertEqual(reply.status_code, 200, reply.text)
        with sqlite3.connect(server.DB_PATH) as conn:
            total = conn.execute("SELECT total_amount FROM order_events WHERE order_no='OFF2'").fetchone()[0]
            unit = conn.execute("SELECT unit_price FROM order_items WHERE order_no='OFF2'").fetchone()[0]
        self.assertEqual((total, unit), (100, 50))
        self.assertIn("ชาไทย ขาย 50.00 บาท (เมนูตอนนี้ 60.00)", self.notes("OFF2")[0])

    def test_oversold_stock_goes_negative_and_is_flagged(self):
        reply = self.order(self.cashier, "OFF3", [("M1", "ต้มยำกุ้ง", 120, 2)], 240)
        self.assertEqual(reply.status_code, 200, reply.text)
        self.assertEqual(self.stock(), -1)
        self.assertIn("สต็อก shrimp ไม่พอ", self.notes("OFF3")[0])

    def test_a_discount_given_offline_is_kept_and_named(self):
        reply = self.order(self.cashier, "OFF4", [("M2", "ชาไทย", 50, 2)], 90)
        self.assertEqual(reply.status_code, 200, reply.text)
        self.assertIn("ส่วนลด 10.00 บาท", self.notes("OFF4")[0])

    def test_a_total_above_its_own_items_is_refused(self):
        self.assertEqual(self.order(self.cashier, "OFF5", [("M2", "ชาไทย", 50, 1)], 80).status_code, 409)

    def test_a_dish_never_on_the_menu_is_still_refused(self):
        self.assertEqual(self.order(self.cashier, "OFF6", [("NOPE", "?", 10, 1)], 10).status_code, 409)

    def test_the_kitchen_cannot_claim_an_offline_sale(self):
        kitchen = self.signed_in(3)
        self.assertEqual(self.order(kitchen, "OFF7", [("M2", "ชาไทย", 50, 1)], 50).status_code, 403)

    def test_no_session_cannot_claim_an_offline_sale(self):
        stranger = TestClient(server.app)
        self.assertEqual(self.order(stranger, "OFF8", [("M2", "ชาไทย", 50, 1)], 50).status_code, 401)

    def test_an_order_sent_online_is_held_to_todays_menu(self):
        self.manager.patch("/api/menu/M2", json={"branch_id": 1, "sold_out": True})
        self.assertEqual(self.order(self.cashier, "ON1", [("M2", "ชาไทย", 50, 1)], 50,
                                    offline=False).status_code, 409)

    def test_sending_the_same_offline_order_twice_records_it_once(self):
        first = self.order(self.cashier, "OFF9", [("M2", "ชาไทย", 50, 1)], 50)
        again = self.order(self.cashier, "OFF9", [("M2", "ชาไทย", 50, 1)], 50)
        self.assertEqual((first.status_code, again.json()["status"]), (200, "existing"))

    # ------------------------------------------------------------ the kitchen
    def test_the_kitchen_sees_the_choices_and_the_note(self):
        """Spice level, toppings and the note reach the kitchen screen; without
        them the dish comes out the way the guest asked it not to."""
        self.assertEqual(self.manager.put("/api/menu/M3", json={
            "branch_id": 1, "name": "กะเพรา", "price": 45,
            "levels": ["ไม่เผ็ด", "เผ็ดน้อย"],
            "addons": [{"name": "ไข่ดาว", "price": 10, "ingId": "NONE", "qty": 0}]}).status_code, 200)
        body = {"event_id": "e-K1", "order_no": "K1", "branch_id": 1, "table_no": "5",
                "total_amount": 55, "note": "  ไม่ใส่ผัก   ",
                "items": [{"id": "M3", "name": "กะเพรา", "price": 55, "qty": 1,
                           "level": "เผ็ดน้อย", "addons": ["ไข่ดาว"]}]}
        self.assertEqual(self.cashier.post("/api/orders", json=body).status_code, 200)
        ticket = next(t for t in self.manager.get("/api/kds").json()["tickets"] if t["order_no"] == "K1")
        self.assertEqual((ticket["note"], ticket["items"][0]["options"]), ("ไม่ใส่ผัก", "เผ็ดน้อย, ไข่ดาว"))
        order = next(o for o in self.manager.get("/api/orders").json()["orders"] if o["order_no"] == "K1")
        self.assertEqual((order["note"], order["items"][0]["options"]), ("ไม่ใส่ผัก", "เผ็ดน้อย, ไข่ดาว"))

    # ------------------------------------------------------------ the close
    def close(self, client, order_no, amount, **extra):
        body = {"event_id": "close-" + order_no, "order_no": order_no, "amount": amount, "method": CASH}
        body.update(extra)
        return client.post("/api/payments/close", json=body)

    def closed_by(self, order_no):
        with sqlite3.connect(server.DB_PATH) as conn:
            return conn.execute("SELECT closed_by_staff_id FROM pos_orders WHERE order_no=?",
                                (order_no,)).fetchone()[0]

    def test_the_money_is_credited_to_who_took_it_not_who_sent_it(self):
        self.order(self.cashier, "OFF10", [("M2", "ชาไทย", 50, 1)], 50)
        sender = self.signed_in(4)
        reply = self.close(sender, "OFF10", 50, offline_at="2026-10-18T19:10:00Z", taken_by=2)
        self.assertEqual(reply.status_code, 200, reply.text)
        self.assertEqual(self.closed_by("OFF10"), 2)

    def test_taken_by_cannot_credit_someone_who_may_not_close_bills(self):
        self.order(self.cashier, "OFF11", [("M2", "ชาไทย", 50, 1)], 50)
        self.close(self.cashier, "OFF11", 50, offline_at="2026-10-18T19:10:00Z", taken_by=3)
        self.assertEqual(self.closed_by("OFF11"), 2)

    def test_taken_by_means_nothing_on_a_close_made_online(self):
        self.order(self.cashier, "ON2", [("M2", "ชาไทย", 50, 1)], 50, offline=False)
        self.close(self.cashier, "ON2", 50, taken_by=4)
        self.assertEqual(self.closed_by("ON2"), 2)

    def test_a_second_close_from_another_till_is_refused_not_hidden(self):
        """Two tills, both offline, both took money for the same bill: the
        second must come back refused so someone sees it."""
        self.order(self.cashier, "OFF12", [("M2", "ชาไทย", 50, 1)], 50)
        first = self.close(self.cashier, "OFF12", 50, event_id="close-OFF12-tillA")
        second = self.close(self.signed_in(4), "OFF12", 50, event_id="close-OFF12-tillB")
        self.assertEqual((first.status_code, second.status_code), (200, 409))

    def test_settled_bills_carry_the_offline_flag_for_the_owner(self):
        self.manager.put("/api/menu/M2", json={"branch_id": 1, "name": "ชาไทย", "price": 60})
        self.order(self.cashier, "OFF13", [("M2", "ชาไทย", 50, 1)], 50)
        self.close(self.cashier, "OFF13", 50, offline_at="2026-10-18T19:12:00Z", taken_by=2)
        self.order(self.cashier, "ON3", [("M2", "ชาไทย", 60, 1)], 60, offline=False)
        self.close(self.cashier, "ON3", 60)
        settled = {row["order_no"]: row for row in self.manager.get("/api/orders/settled").json()["orders"]}
        self.assertTrue(settled["OFF13"]["offline"])
        self.assertTrue(any("เมนูตอนนี้ 60.00" in note for note in settled["OFF13"]["offline_notes"]))
        self.assertFalse(settled["ON3"]["offline"])

    # ------------------------------------------------------------ the review
    def test_the_owner_sees_the_offline_bills_and_can_tick_them_off(self):
        self.manager.put("/api/menu/M2", json={"branch_id": 1, "name": "ชาไทย", "price": 60})
        self.order(self.cashier, "OFF20", [("M2", "ชาไทย", 50, 1)], 50)
        self.close(self.cashier, "OFF20", 50, offline_at="2026-10-18T19:20:00Z", taken_by=2)
        listed = self.manager.get("/api/reports/offline-sales").json()
        self.assertEqual(listed["unreviewed"], 1)
        sale = listed["sales"][0]
        self.assertEqual((sale["order_no"], sale["status"], sale["taken_by_name"]), ("OFF20", "paid", "cashier2"))
        self.assertTrue(any("เมนูตอนนี้ 60.00" in note for note in sale["notes"]))
        self.assertEqual(self.manager.post("/api/reports/offline-sales/OFF20/review").status_code, 200)
        self.assertEqual(self.manager.get("/api/reports/offline-sales").json()["unreviewed"], 0)
        history = self.manager.get("/api/reports/offline-sales", params={"show": "all"}).json()["sales"]
        self.assertEqual(history[0]["reviewed_by_name"], "manager1")

    def test_a_cashier_cannot_see_or_tick_the_review_list(self):
        self.order(self.cashier, "OFF21", [("M2", "ชาไทย", 50, 1)], 50)
        self.assertEqual(self.cashier.get("/api/reports/offline-sales").status_code, 403)
        self.assertEqual(self.cashier.post("/api/reports/offline-sales/OFF21/review").status_code, 403)


if __name__ == "__main__":
    unittest.main()
