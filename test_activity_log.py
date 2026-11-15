"""บันทึกว่าใครทำอะไร และผู้จัดการอนุมัติด้วยรหัสที่หน้าจอเดิม

กะกับลิ้นชักตอบได้ว่าเงินหาย แต่ไม่เคยตอบว่าหายตรงไหน เพราะไม่มีที่ไหนจดว่า
ใครกดส่วนลด ใครแก้ราคาเมนู ใครนำเงินออกจากลิ้นชัก

ส่วนใบอนุมัติมีไว้แทนสิ่งที่ร้านทำกันจริงตอนผู้จัดการไม่อยู่ — บอก PIN ของตัวเอง
ให้แคชเชียร์จำ ซึ่งทำให้บันทึกทุกแถวหลังจากนั้นโกหกว่าผู้จัดการเป็นคนทำ
"""

import sqlite3
import tempfile
import time
import unittest
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

import line_pos_server as server


class ShopWithTwoPeople(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.directory.cleanup)
        server.DB_PATH = Path(self.directory.name) / "activity.db"
        server.PREVIEW_ONLY = False
        server.BOOTSTRAP_MANAGER_PIN = ""
        server.TABLE_QR_SECRET = "m" * 48
        server.init_db()
        self.conn = sqlite3.connect(server.DB_PATH)
        self.addCleanup(self.conn.close)
        with self.conn:
            self.conn.execute("INSERT INTO branches(id,name) VALUES(1,'สาขาหนึ่ง')")
            self.conn.execute("INSERT INTO branches(id,name) VALUES(2,'สาขาสอง')")
            for staff_id, branch, role, pin in (
                    (1, 1, "owner", "secure-pin-owner"),
                    (2, 1, "cashier", "secure-pin-cashier"),
                    (3, 1, "manager", "secure-pin-manager"),
                    (4, 2, "manager", "secure-pin-other")):
                self.conn.execute(
                    "INSERT INTO staffs(id,branch_id,name,role,pin_code_hash) VALUES(?,?,?,?,?)",
                    (staff_id, branch, f"คน{staff_id}", role, server.hash_pin(pin)))
        self.owner = self.signed_in(1, "secure-pin-owner")

    def signed_in(self, staff_id, pin):
        client = TestClient(server.app)
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        answer = client.post("/api/auth/login", json={"staff_id": staff_id, "pin": pin})
        self.assertEqual(answer.status_code, 200, answer.text)
        return client

    def cashier(self):
        return self.signed_in(2, "secure-pin-cashier")

    def manager(self):
        return self.signed_in(3, "secure-pin-manager")

    def entries(self, action=None):
        sql = "SELECT action, staff_id, subject, detail, amount_cents FROM staff_activity"
        params = ()
        if action:
            sql += " WHERE action=?"
            params = (action,)
        return self.conn.execute(sql + " ORDER BY id", params).fetchall()

    def dish(self, price=100, item_id="M1"):
        answer = self.owner.put(f"/api/menu/{item_id}",
                                json={"branch_id": 1, "name": "ข้าวผัด", "price": price})
        self.assertEqual(answer.status_code, 200, answer.text)


class WhatGetsWrittenDown(ShopWithTwoPeople):
    def test_a_discount_is_recorded_with_its_reason(self):
        self.dish()
        answer = self.owner.post("/api/orders", json={
            "event_id": str(uuid.uuid4()), "order_no": "ORD-D1", "branch_id": 1,
            "table_no": "1", "total_amount": 90, "discount_percent": 10,
            "discount_reason": "ลูกค้าประจำ",
            "items": [{"id": "M1", "name": "ข้าวผัด", "price": 100, "qty": 1}]})
        self.assertEqual(answer.status_code, 200, answer.text)
        rows = self.entries("discount")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], 1)
        self.assertEqual(rows[0][3], "ลูกค้าประจำ")
        self.assertEqual(rows[0][4], 1000)

    def test_a_bill_with_no_discount_writes_nothing(self):
        self.dish()
        self.owner.post("/api/orders", json={
            "event_id": str(uuid.uuid4()), "order_no": "ORD-D2", "branch_id": 1,
            "table_no": "1", "total_amount": 100,
            "items": [{"id": "M1", "name": "ข้าวผัด", "price": 100, "qty": 1}]})
        self.assertEqual(self.entries("discount"), [])

    def test_a_price_change_says_what_it_was(self):
        self.dish(price=100)
        self.dish(price=120)
        rows = self.entries("menu_price")
        # แถวแรกคือตอนสร้างเมนู แถวที่สองคือตอนขึ้นราคา
        self.assertEqual(len(rows), 2)
        self.assertIn("ของใหม่", rows[0][3])
        self.assertIn("฿100.00 → ฿120.00", rows[1][3])

    def test_editing_a_dish_without_touching_its_price_writes_nothing_new(self):
        self.dish(price=100)
        answer = self.owner.put("/api/menu/M1", json={
            "branch_id": 1, "name": "ข้าวผัดหมู", "price": 100, "description": "ใส่ไข่"})
        self.assertEqual(answer.status_code, 200, answer.text)
        self.assertEqual(len(self.entries("menu_price")), 1)

    def test_money_leaving_the_drawer_is_recorded_with_its_reason(self):
        self.assertEqual(self.owner.post("/api/shifts/open",
                                         json={"branch_id": 1, "opening": 1000}).status_code, 200)
        answer = self.owner.post("/api/shifts/cash", json={
            "branch_id": 1, "kind": "out", "amount": 250, "reason": "ซื้อน้ำแข็ง"})
        self.assertEqual(answer.status_code, 200, answer.text)
        rows = self.entries("cash_out")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][3], "ซื้อน้ำแข็ง")
        self.assertEqual(rows[0][4], 25000)
        self.assertEqual(len(self.entries("shift_open")), 1)

    def test_changing_the_shop_settings_is_recorded(self):
        answer = self.owner.put("/api/shop/settings",
                                json={"vat_rate_bp": 700, "service_charge_bp": 1000})
        self.assertEqual(answer.status_code, 200, answer.text)
        rows = self.entries("shop_settings")
        self.assertEqual(len(rows), 1)
        self.assertIn("vat_rate_bp", rows[0][3])


class WhoMayReadIt(ShopWithTwoPeople):
    def test_the_owner_can_read_it(self):
        self.dish()
        answer = self.owner.get("/api/reports/activity?branch_id=1")
        self.assertEqual(answer.status_code, 200, answer.text)
        body = answer.json()
        self.assertTrue(body["entries"])
        self.assertEqual(body["entries"][0]["action_label"], "แก้ราคาเมนู")

    def test_a_manager_reads_their_own_branch(self):
        self.dish()
        self.assertEqual(self.manager().get("/api/reports/activity?branch_id=1").status_code, 200)

    def test_a_manager_cannot_read_another_branch(self):
        other = self.signed_in(4, "secure-pin-other")
        self.assertEqual(other.get("/api/reports/activity?branch_id=1").status_code, 403)

    def test_a_cashier_cannot_read_it_at_all(self):
        """หน้านี้มีไว้ตรวจแคชเชียร์ ถ้าแคชเชียร์เปิดดูได้ก็รู้ว่าอะไรถูกจับตาอยู่"""
        self.assertEqual(self.cashier().get("/api/reports/activity?branch_id=1").status_code, 403)

    def test_it_groups_by_person_and_by_what_they_did(self):
        self.dish()
        body = self.owner.get("/api/reports/activity?branch_id=1").json()
        self.assertEqual(body["by_staff"][0]["staff_id"], 1)
        self.assertEqual(body["by_action"][0]["action"], "menu_price")


class TheManagerApprovesAtTheSameScreen(ShopWithTwoPeople):
    def open_bill(self, order_no, total):
        self.dish(price=total)
        answer = self.cashier_client.post("/api/orders", json={
            "event_id": str(uuid.uuid4()), "order_no": order_no, "branch_id": 1,
            "table_no": "1", "total_amount": total,
            "items": [{"id": "M1", "name": "ข้าวผัด", "price": total, "qty": 1}]})
        self.assertEqual(answer.status_code, 200, answer.text)

    def setUp(self):
        super().setUp()
        self.cashier_client = self.cashier()

    def approval(self, action="void", staff_id=3, pin="secure-pin-manager", client=None):
        return (client or self.cashier_client).post("/api/auth/override", json={
            "branch_id": 1, "action": action, "staff_id": staff_id, "pin": pin})

    def void(self, order_no, override="", client=None):
        return (client or self.cashier_client).post(f"/api/orders/{order_no}/void", json={
            "event_id": str(uuid.uuid4()), "reason": "ลูกค้าเปลี่ยนใจ", "override": override})

    def test_a_big_bill_is_refused_without_an_approval(self):
        self.open_bill("ORD-V1", 900)
        refused = self.void("ORD-V1")
        self.assertEqual(refused.status_code, 403, refused.text)
        self.assertIn("อนุมัติ", refused.json()["detail"])

    def test_with_the_managers_pin_it_goes_through(self):
        self.open_bill("ORD-V2", 900)
        token = self.approval()
        self.assertEqual(token.status_code, 200, token.text)
        self.assertEqual(token.json()["approved_by"], "คน3")
        done = self.void("ORD-V2", override=token.json()["token"])
        self.assertEqual(done.status_code, 200, done.text)
        # บันทึกต้องบอกว่าแคชเชียร์เป็นคนทำ และใครอนุมัติ
        rows = self.entries("void")
        self.assertEqual(rows[0][1], 2)
        self.assertIn("อนุมัติโดย คน3", rows[0][3])
        self.assertEqual(len(self.entries("manager_override")), 1)

    def test_one_approval_cannot_be_used_twice(self):
        self.open_bill("ORD-V3", 900)
        self.open_bill("ORD-V4", 900)
        token = self.approval().json()["token"]
        self.assertEqual(self.void("ORD-V3", override=token).status_code, 200)
        again = self.void("ORD-V4", override=token)
        self.assertEqual(again.status_code, 403, again.text)

    def test_an_approval_for_one_thing_does_not_approve_another(self):
        self.open_bill("ORD-V5", 900)
        token = self.approval(action="refund").json()["token"]
        refused = self.void("ORD-V5", override=token)
        self.assertEqual(refused.status_code, 403, refused.text)

    def test_an_expired_approval_is_no_approval(self):
        self.open_bill("ORD-V6", 900)
        token = self.approval().json()["token"]
        with self.conn:
            self.conn.execute("UPDATE manager_overrides SET expires_at=? WHERE token=?",
                              (int(time.time()) - 1, token))
        refused = self.void("ORD-V6", override=token)
        self.assertEqual(refused.status_code, 403, refused.text)

    def test_a_cashier_cannot_approve_for_themselves(self):
        refused = self.approval(staff_id=2, pin="secure-pin-cashier")
        self.assertEqual(refused.status_code, 401, refused.text)

    def test_a_manager_from_another_branch_cannot_approve_here(self):
        refused = self.approval(staff_id=4, pin="secure-pin-other")
        self.assertEqual(refused.status_code, 401, refused.text)

    def test_the_wrong_pin_is_refused(self):
        refused = self.approval(pin="secure-pin-wrong")
        self.assertEqual(refused.status_code, 401, refused.text)

    def test_a_small_bill_still_needs_no_approval(self):
        self.open_bill("ORD-V7", 100)
        self.assertEqual(self.void("ORD-V7").status_code, 200)
        self.assertEqual(self.entries("manager_override"), [])

    def paid_bill(self, order_no="ORD-R1", total=300):
        self.open_bill(order_no, total)
        with self.conn:
            self.conn.execute("UPDATE order_events SET status='paid' WHERE order_no=?", (order_no,))
            self.conn.execute(
                "INSERT INTO pos_orders (branch_id, order_no, closed_by_staff_id, total_amount,"
                " net_amount, payment_method, status, closed_at)"
                " VALUES (1,?,2,?,?,'เงินสด (Cash)','paid',"
                " strftime('%Y-%m-%d %H:%M:%f','now'))", (order_no, total, total))
        return order_no

    def refund(self, order_no, override=""):
        return self.cashier_client.post(f"/api/payments/{order_no}/refund", json={
            "event_id": str(uuid.uuid4()), "reason": "ลูกค้าขอคืนเงิน", "override": override})

    def test_a_refund_by_a_cashier_needs_an_approval(self):
        """คืนเงินยังเป็นเรื่องของผู้จัดการเหมือนเดิม แค่ไม่ต้องสลับบัญชี"""
        order_no = self.paid_bill()
        refused = self.refund(order_no)
        self.assertEqual(refused.status_code, 403, refused.text)
        self.assertIn("อนุมัติ", refused.json()["detail"])

    def test_with_an_approval_the_cashier_may_refund(self):
        order_no = self.paid_bill("ORD-R2")
        token = self.approval(action="refund").json()["token"]
        done = self.refund(order_no, override=token)
        self.assertEqual(done.status_code, 200, done.text)
        rows = self.entries("refund")
        self.assertEqual(rows[0][1], 2)
        self.assertIn("อนุมัติโดย คน3", rows[0][3])

    def test_a_manager_still_refunds_without_any_approval(self):
        order_no = self.paid_bill("ORD-R3")
        done = self.manager().post(f"/api/payments/{order_no}/refund", json={
            "event_id": str(uuid.uuid4()), "reason": "ลูกค้าขอคืนเงิน"})
        self.assertEqual(done.status_code, 200, done.text)


if __name__ == "__main__":
    unittest.main()
