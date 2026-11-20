"""ซัพพลายเออร์และใบสั่งซื้อ

หน้าสต็อกเดิมบอกได้ว่าบนชั้นมีเท่าไหร่ และให้คนพิมพ์ตัวเลขใหม่ลงไป แต่บอกไม่ได้
ว่าอะไรกำลังมา สั่งจากใคร ราคาเท่าไหร่ ร้านที่สั่งซ้ำเพราะลืมว่าสั่งไปแล้ว
หรือจ่ายบิลที่ตรวจไม่ได้ จึงไม่มีอะไรให้ดูเลย
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import line_pos_server as server
import poswai_purchasing as purchasing


class PurchasingCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.directory.cleanup)
        server.DB_PATH = Path(self.directory.name) / "purchasing.db"
        server.PREVIEW_ONLY = False
        server.BOOTSTRAP_MANAGER_PIN = ""
        server.TABLE_QR_SECRET = "f" * 48
        server.init_db()
        conn = sqlite3.connect(server.DB_PATH)
        with conn:
            conn.execute("INSERT INTO branches(id,name) VALUES(1,'Test')")
            for staff_id, role in ((1, "owner"), (2, "cashier"), (3, "kitchen")):
                conn.execute("INSERT INTO staffs(id,branch_id,name,role,pin_code_hash)"
                             " VALUES(?,1,?,?,?)",
                             (staff_id, role, role, server.hash_pin(f"secure-pin-{role}")))
            for ingredient, stock in (("PORK", 100), ("RICE", 50)):
                conn.execute("INSERT INTO inventory(branch_id,ingredient_id,stock,unit)"
                             " VALUES(1,?,?,'กก.')", (ingredient, stock))
        conn.close()

    def signed_in(self, staff_id=1, role="owner"):
        client = TestClient(server.app)
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        self.assertEqual(client.post("/api/auth/login",
                                     json={"staff_id": staff_id, "pin": f"secure-pin-{role}"}).status_code, 200)
        return client

    def supplier(self, client, name="ร้านหมูเจ๊แดง"):
        answer = client.post("/api/suppliers", json={"name": name, "phone": "0812345678"})
        self.assertEqual(answer.status_code, 200, answer.text)
        return answer.json()["id"]

    def order(self, client, supplier_id, lines=None):
        answer = client.post("/api/purchase-orders", json={
            "branch_id": 1, "supplier_id": supplier_id,
            "lines": lines or [{"ingredient_id": "PORK", "quantity": 20, "unit_cost": 150}]})
        self.assertEqual(answer.status_code, 200, answer.text)
        return answer.json()

    def stock(self, ingredient="PORK"):
        with sqlite3.connect(server.DB_PATH) as conn:
            return conn.execute("SELECT stock FROM inventory WHERE branch_id=1 AND ingredient_id=?",
                                (ingredient,)).fetchone()[0]


class Suppliers(PurchasingCase):
    def test_a_supplier_is_saved_and_listed(self):
        owner = self.signed_in()
        self.supplier(owner)
        listed = owner.get("/api/suppliers").json()["suppliers"]
        self.assertEqual([s["name"] for s in listed], ["ร้านหมูเจ๊แดง"])

    def test_two_suppliers_cannot_share_a_name(self):
        """A shop that cannot tell its own orders apart a month later."""
        owner = self.signed_in()
        self.supplier(owner)
        self.assertEqual(owner.post("/api/suppliers",
                                    json={"name": "ร้านหมูเจ๊แดง"}).status_code, 409)

    def test_a_supplier_needs_a_name(self):
        self.assertEqual(self.signed_in().post("/api/suppliers",
                                               json={"name": "   "}).status_code, 400)

    def test_a_supplier_can_be_renamed(self):
        owner = self.signed_in()
        supplier_id = self.supplier(owner)
        renamed = owner.put(f"/api/suppliers/{supplier_id}",
                            json={"name": "ร้านหมูเจ๊ดำ", "phone": "0899999999"})
        self.assertEqual(renamed.status_code, 200, renamed.text)
        self.assertEqual(renamed.json()["name"], "ร้านหมูเจ๊ดำ")

    def test_one_that_stopped_selling_drops_off_the_list_but_stays_on_old_orders(self):
        owner = self.signed_in()
        supplier_id = self.supplier(owner)
        placed = self.order(owner, supplier_id)
        owner.put(f"/api/suppliers/{supplier_id}",
                  json={"name": "ร้านหมูเจ๊แดง", "active": False})
        self.assertEqual(owner.get("/api/suppliers").json()["suppliers"], [])
        kept = owner.get("/api/purchase-orders?branch_id=1").json()["orders"]
        self.assertEqual(kept[0]["supplier"]["name"], "ร้านหมูเจ๊แดง")
        self.assertEqual(kept[0]["number"], placed["number"])

    def test_a_cashier_cannot_add_a_supplier(self):
        self.assertEqual(self.signed_in(2, "cashier").post("/api/suppliers",
                                                           json={"name": "x"}).status_code, 403)


class WritingAnOrder(PurchasingCase):
    def test_an_order_is_numbered_and_totalled(self):
        owner = self.signed_in()
        placed = self.order(owner, self.supplier(owner),
                            lines=[{"ingredient_id": "PORK", "quantity": 20, "unit_cost": 150},
                                   {"ingredient_id": "RICE", "quantity": 10, "unit_cost": 25}])
        self.assertTrue(placed["number"].startswith("PO-"))
        self.assertEqual(placed["status"], "draft")
        self.assertEqual(placed["total"], 20 * 150 + 10 * 25)

    def test_writing_an_order_moves_no_stock(self):
        """Ordering is not receiving. The shelf has not changed."""
        owner = self.signed_in()
        before = self.stock()
        self.order(owner, self.supplier(owner))
        self.assertEqual(self.stock(), before)

    def test_the_same_ingredient_twice_in_one_order_is_refused(self):
        owner = self.signed_in()
        answer = owner.post("/api/purchase-orders", json={
            "branch_id": 1, "supplier_id": self.supplier(owner),
            "lines": [{"ingredient_id": "PORK", "quantity": 5, "unit_cost": 1},
                      {"ingredient_id": "PORK", "quantity": 7, "unit_cost": 1}]})
        self.assertEqual(answer.status_code, 400)

    def test_an_empty_order_is_refused(self):
        owner = self.signed_in()
        self.assertEqual(owner.post("/api/purchase-orders",
                                    json={"branch_id": 1, "supplier_id": self.supplier(owner),
                                          "lines": []}).status_code, 400)

    def test_a_zero_quantity_is_refused(self):
        owner = self.signed_in()
        self.assertEqual(owner.post("/api/purchase-orders", json={
            "branch_id": 1, "supplier_id": self.supplier(owner),
            "lines": [{"ingredient_id": "PORK", "quantity": 0, "unit_cost": 1}]}).status_code, 400)

    def test_a_supplier_that_does_not_exist_is_refused(self):
        owner = self.signed_in()
        self.assertEqual(owner.post("/api/purchase-orders", json={
            "branch_id": 1, "supplier_id": 999,
            "lines": [{"ingredient_id": "PORK", "quantity": 1, "unit_cost": 1}]}).status_code, 404)

    def test_numbers_run_on_within_the_month(self):
        owner = self.signed_in()
        supplier_id = self.supplier(owner)
        first = self.order(owner, supplier_id)["number"]
        second = self.order(owner, supplier_id)["number"]
        self.assertNotEqual(first, second)
        self.assertEqual(int(second.rsplit("-", 1)[1]), int(first.rsplit("-", 1)[1]) + 1)


class ReceivingIt(PurchasingCase):
    def placed(self, lines=None):
        owner = self.signed_in()
        return owner, self.order(owner, self.supplier(owner), lines)

    def test_receiving_puts_the_stock_on_the_shelf(self):
        owner, placed = self.placed()
        before = self.stock()
        received = owner.post(f"/api/purchase-orders/{placed['id']}/receive?branch_id=1", json={})
        self.assertEqual(received.status_code, 200, received.text)
        self.assertEqual(received.json()["status"], "received")
        self.assertEqual(self.stock(), before + 20)

    def test_what_turned_up_is_recorded_not_what_was_ordered(self):
        """A supplier who sends nine of ten is the normal case, and a system
        that records ten makes the shelf disagree from that day on."""
        owner, placed = self.placed()
        before = self.stock()
        received = owner.post(f"/api/purchase-orders/{placed['id']}/receive?branch_id=1",
                              json={"received": {"PORK": 18}})
        self.assertEqual(received.status_code, 200, received.text)
        self.assertEqual(self.stock(), before + 18)
        line = received.json()["lines"][0]
        self.assertEqual(line["quantity"], 20)           # what was ordered
        self.assertEqual(line["received_quantity"], 18)  # what arrived

    def test_a_line_that_never_turned_up_is_recorded_as_zero(self):
        owner, placed = self.placed(
            lines=[{"ingredient_id": "PORK", "quantity": 20, "unit_cost": 150},
                   {"ingredient_id": "RICE", "quantity": 10, "unit_cost": 25}])
        before = self.stock("RICE")
        received = owner.post(f"/api/purchase-orders/{placed['id']}/receive?branch_id=1",
                              json={"received": {"RICE": 0}}).json()
        self.assertEqual(self.stock("RICE"), before)
        rice = next(line for line in received["lines"] if line["ingredient_id"] == "RICE")
        self.assertEqual(rice["received_quantity"], 0)
        self.assertEqual(rice["quantity"], 10)   # still says what was expected

    def test_the_stock_change_goes_through_the_audit_ledger(self):
        """A purchase order with its own private route into the shelf would be
        a second set of books."""
        owner, placed = self.placed()
        owner.post(f"/api/purchase-orders/{placed['id']}/receive?branch_id=1", json={})
        movements = owner.get("/api/inventory/movements?branch_id=1").json()["items"]
        mine = [m for m in movements if placed["number"] in (m.get("note") or "")]
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0]["action"], "restock")

    def test_receiving_twice_is_refused_so_stock_is_not_doubled(self):
        owner, placed = self.placed()
        owner.post(f"/api/purchase-orders/{placed['id']}/receive?branch_id=1", json={})
        after_once = self.stock()
        again = owner.post(f"/api/purchase-orders/{placed['id']}/receive?branch_id=1", json={})
        self.assertEqual(again.status_code, 409)
        self.assertEqual(self.stock(), after_once)

    def test_an_ingredient_that_was_never_ordered_cannot_be_received(self):
        owner, placed = self.placed()
        refused = owner.post(f"/api/purchase-orders/{placed['id']}/receive?branch_id=1",
                             json={"received": {"RICE": 5}})
        self.assertEqual(refused.status_code, 400)

    def test_the_kitchen_can_receive_a_delivery(self):
        """They are the ones at the back door when it arrives."""
        owner, placed = self.placed()
        kitchen = self.signed_in(3, "kitchen")
        self.assertEqual(kitchen.post(f"/api/purchase-orders/{placed['id']}/receive?branch_id=1",
                                      json={}).status_code, 200)

    def test_a_cashier_cannot(self):
        owner, placed = self.placed()
        till = self.signed_in(2, "cashier")
        self.assertEqual(till.post(f"/api/purchase-orders/{placed['id']}/receive?branch_id=1",
                                   json={}).status_code, 403)


class SendingAndCancelling(PurchasingCase):
    def placed(self):
        owner = self.signed_in()
        return owner, self.order(owner, self.supplier(owner))

    def test_sending_marks_it_placed_and_moves_nothing(self):
        owner, placed = self.placed()
        before = self.stock()
        sent = owner.post(f"/api/purchase-orders/{placed['id']}/send?branch_id=1")
        self.assertEqual(sent.status_code, 200, sent.text)
        self.assertEqual(sent.json()["status"], "sent")
        self.assertTrue(sent.json()["sent_at"])
        self.assertEqual(self.stock(), before)

    def test_sending_twice_is_refused(self):
        owner, placed = self.placed()
        owner.post(f"/api/purchase-orders/{placed['id']}/send?branch_id=1")
        self.assertEqual(owner.post(f"/api/purchase-orders/{placed['id']}/send?branch_id=1").status_code, 409)

    def test_cancelling_needs_a_reason_and_keeps_the_record(self):
        owner, placed = self.placed()
        self.assertEqual(owner.post(f"/api/purchase-orders/{placed['id']}/cancel?branch_id=1",
                                    json={"reason": " "}).status_code, 400)
        cancelled = owner.post(f"/api/purchase-orders/{placed['id']}/cancel?branch_id=1",
                               json={"reason": "ของขึ้นราคา"})
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assertEqual(cancelled.json()["status"], "cancelled")
        self.assertEqual(cancelled.json()["cancel_reason"], "ของขึ้นราคา")

    def test_an_order_whose_goods_arrived_cannot_be_cancelled(self):
        owner, placed = self.placed()
        owner.post(f"/api/purchase-orders/{placed['id']}/receive?branch_id=1", json={})
        refused = owner.post(f"/api/purchase-orders/{placed['id']}/cancel?branch_id=1",
                             json={"reason": "เปลี่ยนใจ"})
        self.assertEqual(refused.status_code, 409)
        self.assertIn("ของเสีย", refused.json()["detail"])

    def test_a_cancelled_order_cannot_be_received(self):
        owner, placed = self.placed()
        owner.post(f"/api/purchase-orders/{placed['id']}/cancel?branch_id=1",
                   json={"reason": "ยกเลิก"})
        self.assertEqual(owner.post(f"/api/purchase-orders/{placed['id']}/receive?branch_id=1",
                                    json={}).status_code, 409)


class WhatIsOnItsWay(PurchasingCase):
    def test_open_orders_are_counted_as_coming(self):
        """So a shop stops ordering a second time because it forgot the first."""
        owner = self.signed_in()
        supplier_id = self.supplier(owner)
        self.order(owner, supplier_id)
        sent = self.order(owner, supplier_id, lines=[{"ingredient_id": "PORK", "quantity": 5,
                                                      "unit_cost": 150}])
        owner.post(f"/api/purchase-orders/{sent['id']}/send?branch_id=1")
        coming = owner.get("/api/purchase-orders?branch_id=1").json()["on_the_way"]
        self.assertEqual(coming["PORK"], 25)

    def test_what_has_arrived_is_no_longer_on_its_way(self):
        owner = self.signed_in()
        placed = self.order(owner, self.supplier(owner))
        owner.post(f"/api/purchase-orders/{placed['id']}/receive?branch_id=1", json={})
        self.assertEqual(owner.get("/api/purchase-orders?branch_id=1").json()["on_the_way"], {})

    def test_a_cancelled_order_is_not_coming_either(self):
        owner = self.signed_in()
        placed = self.order(owner, self.supplier(owner))
        owner.post(f"/api/purchase-orders/{placed['id']}/cancel?branch_id=1",
                   json={"reason": "ไม่เอาแล้ว"})
        self.assertEqual(owner.get("/api/purchase-orders?branch_id=1").json()["on_the_way"], {})

    def test_orders_can_be_filtered_by_what_stage_they_are_at(self):
        owner = self.signed_in()
        supplier_id = self.supplier(owner)
        self.order(owner, supplier_id)
        sent = self.order(owner, supplier_id)
        owner.post(f"/api/purchase-orders/{sent['id']}/send?branch_id=1")
        only_sent = owner.get("/api/purchase-orders?branch_id=1&status=sent").json()["orders"]
        self.assertEqual([o["number"] for o in only_sent], [sent["number"]])


if __name__ == "__main__":
    unittest.main()
