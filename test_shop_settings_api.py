"""ตั้งค่าร้านของเจ้าของ และยอดบิลที่เซิร์ฟเวอร์คิดจากการตั้งค่านั้น

ก่อนหน้านี้ร้านตั้งได้แค่ชื่อกับพร้อมเพย์ ใบเสร็จจึงพิมพ์เลขผู้เสียภาษีของ
บริษัทอื่นที่ฝังอยู่ในโค้ดให้ทุกร้าน และ VAT กับค่าบริการถูกปิดไว้ทั้งระบบ
เทสต์ชุดนี้คุมสองเรื่องนั้น
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import line_pos_server as server


class ShopSettingsCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.directory.cleanup)
        server.DB_PATH = Path(self.directory.name) / "settings.db"
        server.PREVIEW_ONLY = False
        server.BOOTSTRAP_MANAGER_PIN = ""
        server.TABLE_QR_SECRET = "s" * 48
        server.init_db()
        conn = sqlite3.connect(server.DB_PATH)
        with conn:
            conn.execute("INSERT INTO branches(id,name) VALUES(1,'Test')")
            conn.execute("INSERT INTO staffs(id,branch_id,name,role,pin_code_hash) VALUES(1,1,'Owner','owner',?)",
                         (server.hash_pin("secure-pin-owner"),))
            conn.execute("INSERT INTO staffs(id,branch_id,name,role,pin_code_hash) VALUES(2,1,'Till','cashier',?)",
                         (server.hash_pin("secure-pin-till"),))
        conn.close()

    def owner(self):
        client = TestClient(server.app)
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        self.assertEqual(client.post("/api/auth/login",
                                     json={"staff_id": 1, "pin": "secure-pin-owner"}).status_code, 200)
        return client

    def menu(self, client, item_id, price, *, service_charge=False, tax_mode="included"):
        body = {"branch_id": 1, "name": item_id, "price": price, "bom": [],
                "station": "บาร์น้ำ", "service_charge": service_charge, "tax_mode": tax_mode}
        self.assertEqual(client.put(f"/api/menu/{item_id}", json=body).status_code, 200)

    def order(self, client, order_no, items, total, *, discount=0, table="T1"):
        return client.post("/api/orders", json={
            "event_id": order_no, "order_no": order_no, "branch_id": 1, "table_no": table,
            "total_amount": total, "discount": discount, "items": items})


class WhoMaySeeAndChange(ShopSettingsCase):
    def test_the_owner_reads_the_settings_including_the_new_ones(self):
        settings = self.owner().get("/api/shop/settings").json()
        for field in ("address", "tax_id", "vat_rate_bp", "service_charge_bp", "receipt_footer"):
            self.assertIn(field, settings)

    def test_a_cashier_at_the_same_till_cannot_read_them(self):
        """The shop's bank account and tax number are the owner's business."""
        with TestClient(server.app) as till:
            till.post("/api/auth/login", json={"staff_id": 2, "pin": "secure-pin-till"})
            self.assertEqual(till.get("/api/shop/settings").status_code, 403)

    def test_a_cashier_cannot_change_them_either(self):
        with TestClient(server.app) as till:
            till.post("/api/auth/login", json={"staff_id": 2, "pin": "secure-pin-till"})
            self.assertEqual(till.put("/api/shop/settings", json={"tax_id": ""}).status_code, 403)

    def test_the_first_shop_can_now_set_its_own_receipt_details(self):
        """It has no registry row, so it used to be the one shop stuck with the
        hard-coded tax number it could never change."""
        owner = self.owner()
        saved = owner.put("/api/shop/settings", json={
            "address": "88 หมู่ 1 ต.เมืองนะ อ.เชียงดาว", "tax_id": "0994000165510",
            "receipt_footer": "ขอบคุณครับ"}).json()
        self.assertEqual(saved["tax_id"], "0994000165510")
        self.assertEqual(owner.get("/api/shop/settings").json()["address"],
                         "88 หมู่ 1 ต.เมืองนะ อ.เชียงดาว")

    def test_the_first_shop_is_still_refused_a_name_or_bank_account_change(self):
        """Those two live with the host, not with the shop."""
        self.assertEqual(self.owner().put("/api/shop/settings",
                                          json={"name": "ร้านใหม่"}).status_code, 409)

    def test_a_tax_number_that_fails_its_check_digit_is_refused(self):
        self.assertEqual(self.owner().put("/api/shop/settings",
                                          json={"tax_id": "1111111111111"}).status_code, 400)

    def test_a_rate_above_one_hundred_percent_is_refused(self):
        self.assertEqual(self.owner().put("/api/shop/settings",
                                          json={"vat_rate_bp": 20000}).status_code, 400)


class ReceiptDetailsReachTheTill(ShopSettingsCase):
    def test_the_till_is_told_what_to_print_before_anyone_signs_in(self):
        """A cashier is not the owner, so the receipt lines cannot come from
        the owner-only settings route."""
        self.owner().put("/api/shop/settings", json={"legal_name": "ซีแซ่บ จำกัด",
                                                     "tax_id": "0994000165510"})
        with TestClient(server.app) as anyone:
            receipt = anyone.get("/api/config").json()["receipt"]
        self.assertEqual(receipt["legal_name"], "ซีแซ่บ จำกัด")
        self.assertEqual(receipt["tax_id"], "0994000165510")

    def test_a_shop_that_set_nothing_sends_no_tax_number_at_all(self):
        with TestClient(server.app) as anyone:
            self.assertEqual(anyone.get("/api/config").json()["receipt"]["tax_id"], "")


class BillsFollowTheSettings(ShopSettingsCase):
    def totals(self, client, order_no):
        orders = client.get("/api/orders?branch_id=1").json()["orders"]
        return next(o for o in orders if o["order_no"] == order_no)

    def test_a_shop_that_set_nothing_charges_the_menu_price(self):
        """Every shop open today is this one. None of their totals may move."""
        owner = self.owner()
        self.menu(owner, "TEA", 35)
        items = [{"id": "TEA", "name": "Tea", "price": 35, "qty": 2, "course_mode": "FIRE", "bom": []}]
        self.assertEqual(self.order(owner, "B-1", items, 70).status_code, 200)
        self.assertEqual(self.totals(owner, "B-1")["total_amount"], 70)

    def test_vat_on_top_is_added_to_the_bill(self):
        owner = self.owner()
        owner.put("/api/shop/settings", json={"vat_rate_bp": 700, "vat_inclusive": False})
        self.menu(owner, "TEA", 100)
        items = [{"id": "TEA", "name": "Tea", "price": 100, "qty": 1, "course_mode": "FIRE", "bom": []}]
        self.assertEqual(self.order(owner, "B-2", items, 107).status_code, 200)
        order = self.totals(owner, "B-2")
        self.assertEqual(order["total_amount"], 107)
        self.assertEqual(order["totals"]["vat"], 7)

    def test_vat_inside_the_price_leaves_the_bill_where_it_was(self):
        owner = self.owner()
        owner.put("/api/shop/settings", json={"vat_rate_bp": 700, "vat_inclusive": True})
        self.menu(owner, "TEA", 107)
        items = [{"id": "TEA", "name": "Tea", "price": 107, "qty": 1, "course_mode": "FIRE", "bom": []}]
        self.assertEqual(self.order(owner, "B-3", items, 107).status_code, 200)
        order = self.totals(owner, "B-3")
        self.assertEqual(order["total_amount"], 107)
        self.assertEqual(order["totals"]["vat"], 7)

    def test_service_charge_reaches_only_the_items_marked_for_it(self):
        owner = self.owner()
        owner.put("/api/shop/settings", json={"service_charge_bp": 1000})
        self.menu(owner, "FOOD", 100, service_charge=True)
        self.menu(owner, "WATER", 100, service_charge=False)
        items = [{"id": "FOOD", "name": "Food", "price": 100, "qty": 1, "course_mode": "FIRE", "bom": []},
                 {"id": "WATER", "name": "Water", "price": 100, "qty": 1, "course_mode": "FIRE", "bom": []}]
        self.assertEqual(self.order(owner, "B-4", items, 210).status_code, 200)
        self.assertEqual(self.totals(owner, "B-4")["totals"]["service_charge"], 10)

    def test_a_till_may_discount_the_whole_bill(self):
        owner = self.owner()
        self.menu(owner, "TEA", 100)
        items = [{"id": "TEA", "name": "Tea", "price": 100, "qty": 1, "course_mode": "FIRE", "bom": []}]
        self.assertEqual(self.order(owner, "B-5", items, 80, discount=20).status_code, 200)
        order = self.totals(owner, "B-5")
        self.assertEqual(order["total_amount"], 80)
        self.assertEqual(order["totals"]["discount"], 20)

    def test_a_total_that_disagrees_with_the_shop_rules_is_refused(self):
        """The till may not decide the tax for itself."""
        owner = self.owner()
        owner.put("/api/shop/settings", json={"vat_rate_bp": 700, "vat_inclusive": False})
        self.menu(owner, "TEA", 100)
        items = [{"id": "TEA", "name": "Tea", "price": 100, "qty": 1, "course_mode": "FIRE", "bom": []}]
        self.assertEqual(self.order(owner, "B-6", items, 100).status_code, 409)

    def test_a_guest_at_the_table_cannot_discount_their_own_food(self):
        owner = self.owner()
        self.menu(owner, "TEA", 100)
        token = owner.post("/api/tables/token", json={"branch_id": 1, "table_no": "T1"}).json()["token"]
        items = [{"id": "TEA", "name": "Tea", "price": 100, "qty": 1, "course_mode": "FIRE", "bom": []}]
        with TestClient(server.app) as guest:
            answer = guest.post("/api/orders", headers={"X-Table-Token": token}, json={
                "event_id": "B-7", "order_no": "B-7", "branch_id": 1, "table_no": "T1",
                "total_amount": 50, "discount": 50, "items": items})
        self.assertEqual(answer.status_code, 403)

    def test_the_bill_with_tax_can_actually_be_closed(self):
        """It used to be refused at the till, which made the setting useless."""
        owner = self.owner()
        owner.put("/api/shop/settings", json={"vat_rate_bp": 700, "vat_inclusive": False,
                                              "service_charge_bp": 1000})
        self.menu(owner, "FOOD", 100, service_charge=True)
        items = [{"id": "FOOD", "name": "Food", "price": 100, "qty": 1, "course_mode": "FIRE", "bom": []}]
        self.assertEqual(self.order(owner, "B-8", items, 117.7).status_code, 200)
        paid = owner.post("/api/payments/close", json={
            "event_id": "pay-B-8", "order_no": "B-8", "amount": 117.7, "method": "เงินสด (Cash)"})
        self.assertEqual(paid.status_code, 200, paid.text)


if __name__ == "__main__":
    unittest.main()
