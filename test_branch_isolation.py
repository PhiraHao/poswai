"""เอกสารของสาขาไหน สาขานั้นเท่านั้นที่แตะได้

เดิมเส้นทางรับของ ยกเลิกใบสั่งซื้อ อ่านและยกเลิกใบกำกับภาษี และยกเลิกใบโอน
เชื่อเลขสาขาที่ไคลเอนต์ส่งมา โดยไม่เคยเทียบกับสาขาที่เขียนอยู่บนเอกสาร
ผู้จัดการสาขาหนึ่งจึงเอื้อมไปปิดใบของอีกสาขาได้ และเลขใบกำกับภาษีก็เดาได้
เพราะรันเป็น 2611-0001 ขึ้นไป

รวมของอีกสามอย่างที่ตรวจเจอรอบเดียวกันไว้ที่นี่ด้วย เพราะเป็นเรื่อง
"ใครเห็นอะไรได้" เหมือนกัน
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import line_pos_server as server

SHOP_TAX_ID = "0105536073183"


class ThreeBranches(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.directory.cleanup)
        server.DB_PATH = Path(self.directory.name) / "branches.db"
        server.PREVIEW_ONLY = False
        server.BOOTSTRAP_MANAGER_PIN = ""
        server.TABLE_QR_SECRET = "h" * 48
        server.init_db()
        self.conn = sqlite3.connect(server.DB_PATH)
        self.addCleanup(self.conn.close)
        with self.conn:
            for branch_id, name in ((1, "สาขาหนึ่ง"), (2, "สาขาสอง"), (3, "สาขาสาม")):
                self.conn.execute("INSERT INTO branches(id,name) VALUES(?,?)", (branch_id, name))
            for staff_id, branch_id, role, pin in (
                    (1, 1, "owner", "secure-pin-owner"),
                    (2, 1, "manager", "secure-pin-one"),
                    (3, 2, "manager", "secure-pin-two"),
                    (4, 3, "manager", "secure-pin-three"),
                    (5, 2, "cashier", "secure-pin-cashier")):
                self.conn.execute(
                    "INSERT INTO staffs(id,branch_id,name,role,pin_code_hash) VALUES(?,?,?,?,?)",
                    (staff_id, branch_id, f"{role}{staff_id}", role, server.hash_pin(pin)))
            for branch_id in (1, 2, 3):
                self.conn.execute("INSERT INTO inventory(branch_id,ingredient_id,stock,unit)"
                                  " VALUES(?,'PORK',100,'กก.')", (branch_id,))

    def signed_in(self, staff_id, pin):
        client = TestClient(server.app)
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        answer = client.post("/api/auth/login", json={"staff_id": staff_id, "pin": pin})
        self.assertEqual(answer.status_code, 200, answer.text)
        return client

    def owner(self):
        return self.signed_in(1, "secure-pin-owner")

    def manager_two(self):
        return self.signed_in(3, "secure-pin-two")

    def manager_three(self):
        return self.signed_in(4, "secure-pin-three")

    def cashier_two(self):
        return self.signed_in(5, "secure-pin-cashier")


class PurchaseOrdersStayInTheirBranch(ThreeBranches):
    def sent_order(self):
        owner = self.owner()
        supplier = owner.post("/api/suppliers", json={"name": "ร้านหมู"})
        self.assertEqual(supplier.status_code, 200, supplier.text)
        order = owner.post("/api/purchase-orders", json={
            "branch_id": 1, "supplier_id": supplier.json()["id"],
            "lines": [{"ingredient_id": "PORK", "quantity": 20, "unit_cost": 150}]})
        self.assertEqual(order.status_code, 200, order.text)
        order_id = order.json()["id"]
        self.assertEqual(owner.post(f"/api/purchase-orders/{order_id}/send?branch_id=1").status_code, 200)
        return order_id

    def stock(self, branch_id):
        row = self.conn.execute("SELECT stock FROM inventory WHERE branch_id=? AND ingredient_id='PORK'",
                                (branch_id,)).fetchone()
        return row[0] if row else 0

    def test_another_branch_cannot_receive_your_delivery(self):
        """รับของแทนสาขาอื่นได้ = เติมสต็อกให้เขาเท่าไหร่ก็ได้ แล้วใบถูกล็อก
        ของจริงที่มาถึงทีหลังรับเข้าระบบไม่ได้อีก"""
        order_id = self.sent_order()
        before = self.stock(1)
        refused = self.manager_two().post(
            f"/api/purchase-orders/{order_id}/receive?branch_id=2",
            json={"received": {"PORK": 999}})
        self.assertEqual(refused.status_code, 404, refused.text)
        self.assertEqual(self.stock(1), before)

    def test_another_branch_cannot_cancel_your_order(self):
        order_id = self.sent_order()
        refused = self.manager_two().post(f"/api/purchase-orders/{order_id}/cancel?branch_id=2",
                                          json={"reason": "ไม่เอาแล้ว"})
        self.assertEqual(refused.status_code, 404, refused.text)

    def test_the_branch_that_ordered_still_receives_normally(self):
        order_id = self.sent_order()
        before = self.stock(1)
        answer = self.owner().post(f"/api/purchase-orders/{order_id}/receive?branch_id=1",
                                   json={"received": {"PORK": 20}})
        self.assertEqual(answer.status_code, 200, answer.text)
        self.assertEqual(self.stock(1), before + 20)


class TaxInvoicesStayInTheirBranch(ThreeBranches):
    def issued(self):
        owner = self.owner()
        self.assertEqual(owner.put("/api/shop/settings", json={
            "legal_name": "บริษัท ซีแซ่บ จำกัด", "address": "88 หมู่ 1 เชียงดาว",
            "tax_id": SHOP_TAX_ID, "vat_rate_bp": 700, "vat_inclusive": False}).status_code, 200)
        with self.conn:
            self.conn.execute(
                "INSERT INTO order_events (event_id, order_no, branch_id, table_no, total_amount,"
                " status, subtotal_cents, discount_cents, service_charge_cents, vat_cents)"
                " VALUES ('e-B1','B-1',1,'1',107.0,'paid',10000,0,0,700)")
            self.conn.execute(
                "INSERT INTO order_items (order_no,item_id,name,quantity,unit_price,bom_json)"
                " VALUES ('B-1','M1','ข้าวผัด',1,100,'[]')")
            self.conn.execute(
                "INSERT INTO pos_orders (branch_id, order_no, closed_by_staff_id, total_amount,"
                " net_amount, payment_method, status)"
                " VALUES (1,'B-1',2,107.0,107.0,'เงินสด (Cash)','paid')")
        answer = owner.post("/api/tax-invoices", json={
            "branch_id": 1, "order_no": "B-1", "name": "บริษัท ลูกค้า จำกัด",
            "tax_id": "0994000158441", "address": "1 ถนนสีลม กรุงเทพฯ"})
        self.assertEqual(answer.status_code, 200, answer.text)
        return answer.json()["number"]

    def test_a_cashier_elsewhere_cannot_read_it(self):
        """เลขใบรันเป็น 2611-0001 ขึ้นไป เดาได้หมด ถ้าอ่านข้ามสาขาได้
        ก็กวาดชื่อ ที่อยู่ และเลขผู้เสียภาษีของลูกค้าทุกสาขาได้"""
        number = self.issued()
        refused = self.cashier_two().get(f"/api/tax-invoices/{number}")
        self.assertEqual(refused.status_code, 404, refused.text)

    def test_a_manager_elsewhere_cannot_void_it(self):
        number = self.issued()
        refused = self.manager_two().post(f"/api/tax-invoices/{number}/cancel",
                                          json={"reason": "ลูกค้าขอ"})
        self.assertEqual(refused.status_code, 404, refused.text)
        still = self.owner().get(f"/api/tax-invoices/{number}")
        self.assertEqual(still.status_code, 200)
        self.assertIsNone(still.json()["cancelled_at"])

    def test_the_owner_still_sees_every_branch(self):
        number = self.issued()
        self.assertEqual(self.owner().get(f"/api/tax-invoices/{number}").status_code, 200)


class TransfersStayWithTheirTwoBranches(ThreeBranches):
    def sent(self):
        answer = self.owner().post("/api/transfers", json={
            "from_branch_id": 1, "to_branch_id": 2,
            "lines": [{"ingredient_id": "PORK", "quantity": 10}]})
        self.assertEqual(answer.status_code, 200, answer.text)
        return answer.json()["id"]

    def test_a_branch_on_neither_end_cannot_cancel_it(self):
        """ของอยู่บนรถไปแล้ว ยกเลิกได้ = ปลายทางรับเข้าระบบไม่ได้อีก"""
        transfer_id = self.sent()
        refused = self.manager_three().post(f"/api/transfers/{transfer_id}/cancel",
                                            json={"branch_id": 3, "reason": "ไม่เอา"})
        self.assertEqual(refused.status_code, 404, refused.text)

    def test_the_sending_branch_can_still_cancel_it(self):
        transfer_id = self.sent()
        answer = self.owner().post(f"/api/transfers/{transfer_id}/cancel",
                                   json={"branch_id": 1, "reason": "รถเสีย"})
        self.assertEqual(answer.status_code, 200, answer.text)


class TheMenuKeepsTheShopsMarginToItself(ThreeBranches):
    def add_dish(self):
        answer = self.owner().put("/api/menu/M1", json={
            "branch_id": 1, "name": "ข้าวหมูกรอบ", "price": 60, "cost": 22,
            "bom": [{"ingId": "PORK", "qty": 0.12}]})
        self.assertEqual(answer.status_code, 200, answer.text)

    def test_a_customer_sees_the_price_but_not_the_cost_or_the_recipe(self):
        self.add_dish()
        guest = TestClient(server.app)
        answer = guest.get("/api/menu?branch_id=1")
        self.assertEqual(answer.status_code, 200, answer.text)
        dish = answer.json()["items"][0]
        self.assertEqual(dish["price"], 60)
        self.assertNotIn("cost", dish)
        self.assertNotIn("bom", dish)

    def test_staff_still_get_both(self):
        self.add_dish()
        dish = self.owner().get("/api/menu?branch_id=1").json()["items"][0]
        self.assertEqual(dish["cost"], 22)
        self.assertEqual(dish["bom"][0]["ingId"], "PORK")


class OpeningStockGoesThroughTheLedger(ThreeBranches):
    def test_creating_an_ingredient_with_stock_leaves_a_movement(self):
        """ของที่โผล่มาบนชั้นโดยไม่มีแถวในบัญชีเคลื่อนไหว คือของที่สอบยอดไม่ได้"""
        answer = self.owner().put("/api/inventory/BEEF", json={
            "branch_id": 1, "stock": 40, "unit": "กก.", "reorder_point": 5})
        self.assertEqual(answer.status_code, 200, answer.text)
        rows = self.conn.execute(
            "SELECT action,quantity FROM inventory_movements"
            " WHERE branch_id=1 AND ingredient_id='BEEF'").fetchall()
        self.assertEqual(rows, [("restock", 40)])
        stock = self.conn.execute("SELECT stock FROM inventory WHERE branch_id=1"
                                  " AND ingredient_id='BEEF'").fetchone()
        self.assertEqual(stock[0], 40)

    def test_an_ingredient_with_no_opening_stock_writes_no_movement(self):
        self.assertEqual(self.owner().put("/api/inventory/SALT", json={
            "branch_id": 1, "stock": 0, "unit": "กก.", "reorder_point": 0}).status_code, 200)
        rows = self.conn.execute("SELECT 1 FROM inventory_movements"
                                 " WHERE ingredient_id='SALT'").fetchall()
        self.assertEqual(rows, [])


class CountingAgainstTheRightAddress(unittest.TestCase):
    """X-Forwarded-For ถูก "ต่อท้าย" ไม่ใช่ "ทับ" ตัวซ้ายสุดจึงเป็นของที่ผู้เรียกเขียนเอง"""

    @staticmethod
    def asking(forwarded=None, peer="10.0.0.9"):
        class Client:
            host = peer

        class Request:
            headers = {} if forwarded is None else {"x-forwarded-for": forwarded}
            client = Client()

        return Request()

    def test_the_hop_our_proxy_added_is_the_one_counted(self):
        self.assertEqual(server._client_address(self.asking("1.2.3.4, 203.0.113.7")),
                         "203.0.113.7")

    def test_a_made_up_header_cannot_buy_a_fresh_quota(self):
        first = server._client_address(self.asking("9.9.9.9, 203.0.113.7"))
        second = server._client_address(self.asking("8.8.8.8, 203.0.113.7"))
        self.assertEqual(first, second)

    def test_with_no_proxy_the_socket_answers(self):
        self.assertEqual(server._client_address(self.asking(None)), "10.0.0.9")

    def test_an_empty_header_falls_back_too(self):
        self.assertEqual(server._client_address(self.asking("  ")), "10.0.0.9")


class MoneyIsComparedInWholeSatang(unittest.TestCase):
    def test_a_satang_short_is_short(self):
        self.assertFalse(server._same_money(107.00, 106.99))

    def test_float_dust_is_not_a_difference(self):
        self.assertTrue(server._same_money(0.1 + 0.2, 0.3))

    def test_the_same_amount_matches(self):
        self.assertTrue(server._same_money(107.0, 107.00))


if __name__ == "__main__":
    unittest.main()
