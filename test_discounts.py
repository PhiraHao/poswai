"""ส่วนลดเป็นเปอร์เซ็นต์ ส่วนลดรายรายการ และเหตุผลที่ลด

เดิมลดได้อย่างเดียวคือ "กี่บาทท้ายบิล" ร้านที่อยากลด 10% ต้องคิดเลขในหัวแล้วพิมพ์
คำตอบลงไป ซึ่งผิดสองชั้น — เลขเป็นงานของเครื่อง และรายงานไม่มีทางรู้เลยว่า
ที่ลดไปนั้นคือสิบเปอร์เซ็นต์ เห็นแค่ตัวเลขที่ใครสักคนพิมพ์

ลำดับการคิดสำคัญกว่าตัวเลข: ลดรายรายการก่อน แล้วลดท้ายบิลจากยอดที่เหลือ
แล้วค่อยค่าบริการ แล้วค่อย VAT ถ้าสลับลำดับ ค่าบริการกับ VAT จะคิดจากยอดที่ผิด
"""

import base64
import hashlib
import hmac
import json
import sqlite3
import tempfile
import time
import unittest
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

import line_pos_server as server
import poswai_profile as profile


class WorkingOutWhatComesOff(unittest.TestCase):
    """discount_cents_for: ที่เดียวที่ตัดสินว่า "ลด 10%" คือกี่สตางค์"""

    def test_a_percentage_of_the_amount(self):
        self.assertEqual(profile.discount_cents_for(10000, percent=10), 1000)

    def test_a_flat_number_of_baht(self):
        self.assertEqual(profile.discount_cents_for(10000, baht=25), 2500)

    def test_both_together_add_up(self):
        self.assertEqual(profile.discount_cents_for(10000, baht=10, percent=10), 2000)

    def test_half_a_satang_rounds_up(self):
        # 333 สตางค์ ลด 50% = 166.5 สตางค์
        self.assertEqual(profile.discount_cents_for(333, percent=50), 167)

    def test_it_can_never_exceed_what_it_comes_off(self):
        self.assertEqual(profile.discount_cents_for(5000, baht=900), 5000)
        self.assertEqual(profile.discount_cents_for(5000, percent=100, baht=50), 5000)

    def test_nothing_asked_for_is_nothing_taken(self):
        self.assertEqual(profile.discount_cents_for(10000), 0)

    def test_more_than_everything_is_refused(self):
        with self.assertRaises(profile.ProfileError):
            profile.discount_cents_for(10000, percent=101)

    def test_a_negative_discount_is_refused(self):
        with self.assertRaises(profile.ProfileError):
            profile.discount_cents_for(10000, percent=-5)
        with self.assertRaises(profile.ProfileError):
            profile.discount_cents_for(10000, baht=-5)


class TheOrderTheDiscountsApply(unittest.TestCase):
    SHOP = {"vat_rate_bp": 700, "vat_inclusive": False, "service_charge_bp": 1000}

    def test_a_line_discount_lowers_what_the_service_charge_is_taken_from(self):
        """ลดรายรายการต้องมาก่อนค่าบริการ ไม่งั้นลูกค้าจ่ายค่าบริการของเงินที่ไม่ได้จ่าย"""
        charged = profile.bill(
            [{"cents": 10000, "service_charge": True, "discount_cents": 2000}],
            profile=self.SHOP)
        self.assertEqual(charged["discount_cents"], 2000)
        self.assertEqual(charged["service_charge_cents"], 800)   # 10% ของ 80 บาท
        self.assertEqual(charged["vat_cents"], 616)              # 7% ของ 88 บาท
        self.assertEqual(charged["total_cents"], 10000 - 2000 + 800 + 616)

    def test_the_bill_discount_comes_off_what_the_lines_left(self):
        """ลดสองชั้นต้องไม่รวมกันเกินยอดบิล"""
        charged = profile.bill(
            [{"cents": 10000, "discount_cents": 4000}], profile={}, discount_cents=9000)
        self.assertEqual(charged["discount_cents"], 10000)
        self.assertEqual(charged["total_cents"], 0)

    def test_the_parts_still_sum_to_the_whole(self):
        lines = [{"cents": 3333, "discount_cents": 111},
                 {"cents": 3333}, {"cents": 3334, "discount_cents": 7}]
        charged = profile.bill(lines, profile=self.SHOP, discount_cents=1000)
        self.assertEqual(
            charged["total_cents"],
            charged["subtotal_cents"] - charged["discount_cents"]
            + charged["service_charge_cents"] + charged["vat_cents"])

    def test_a_line_cannot_be_taken_below_nothing(self):
        charged = profile.bill([{"cents": 500, "discount_cents": 900}], profile={})
        self.assertEqual(charged["discount_cents"], 500)
        self.assertEqual(charged["total_cents"], 0)

    def test_no_discount_behaves_exactly_as_before(self):
        charged = profile.bill([{"cents": 10000, "service_charge": True}], profile=self.SHOP)
        self.assertEqual(charged["discount_cents"], 0)
        self.assertEqual(charged["total_cents"], 10000 + 1000 + 770)


class DiscountApiCase(unittest.TestCase):
    """ร้านเดียว เจ้าของคนเดียว เมนูจานเดียวราคา 100 ให้คิดเลขง่าย"""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.directory.cleanup)
        server.DB_PATH = Path(self.directory.name) / "discounts.db"
        server.PREVIEW_ONLY = False
        server.BOOTSTRAP_MANAGER_PIN = ""
        server.TABLE_QR_SECRET = "k" * 48
        server.init_db()
        self.conn = sqlite3.connect(server.DB_PATH)
        self.addCleanup(self.conn.close)
        with self.conn:
            self.conn.execute("INSERT INTO branches(id,name) VALUES(1,'ร้าน')")
            self.conn.execute("INSERT INTO staffs(id,branch_id,name,role,pin_code_hash)"
                              " VALUES(1,1,'เจ้าของ','owner',?)",
                              (server.hash_pin("secure-pin-owner"),))
        self.owner = self.signed_in()
        self.assertEqual(self.owner.put("/api/menu/M1", json={
            "branch_id": 1, "name": "ข้าวผัด", "price": 100}).status_code, 200)

    def signed_in(self):
        client = TestClient(server.app)
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        self.assertEqual(client.post("/api/auth/login",
                                     json={"staff_id": 1, "pin": "secure-pin-owner"}).status_code, 200)
        return client

    def order(self, client=None, *, qty=1, expect=200, **extra):
        body = {"event_id": str(uuid.uuid4()), "order_no": f"ORD-{uuid.uuid4()}",
                "branch_id": 1, "table_no": "1", "total_amount": 0,
                "items": [{"id": "M1", "name": "ข้าวผัด", "price": 100, "qty": qty}]}
        body.update(extra)
        # The server recomputes the total, so ask it what the bill comes to by
        # sending the subtotal and letting it correct us if a discount applies.
        answer = (client or self.owner).post("/api/orders", json=body)
        self.assertEqual(answer.status_code, expect, answer.text)
        return body["order_no"], answer

    def recorded(self, order_no):
        row = self.conn.execute(
            "SELECT subtotal_cents, discount_cents, total_amount, discount_reason"
            " FROM order_events WHERE order_no=?", (order_no,)).fetchone()
        return {"subtotal": row[0], "discount": row[1], "total": row[2], "reason": row[3]}


class TheTillSendsADiscount(DiscountApiCase):
    def test_a_percentage_is_worked_out_by_the_server(self):
        order_no, _ = self.order(total_amount=90, discount_percent=10,
                                 discount_reason="ลูกค้าประจำ")
        kept = self.recorded(order_no)
        self.assertEqual(kept["subtotal"], 10000)
        self.assertEqual(kept["discount"], 1000)
        self.assertEqual(kept["total"], 90)
        self.assertEqual(kept["reason"], "ลูกค้าประจำ")

    def test_a_discount_on_one_line_only(self):
        order_no, _ = self.order(
            total_amount=180,
            items=[{"id": "M1", "name": "ข้าวผัด", "price": 100, "qty": 2,
                    "discount": 20}],
            discount_reason="จานหนึ่งไหม้")
        self.assertEqual(self.recorded(order_no)["discount"], 2000)
        line = self.conn.execute("SELECT discount_cents FROM order_items"
                                 " WHERE order_no=?", (order_no,)).fetchone()
        self.assertEqual(line[0], 2000)

    def test_a_line_percentage_too(self):
        order_no, _ = self.order(
            total_amount=90,
            items=[{"id": "M1", "name": "ข้าวผัด", "price": 100, "qty": 1,
                    "discount_percent": 10}],
            discount_reason="โปรวันเกิด")
        self.assertEqual(self.recorded(order_no)["discount"], 1000)

    def test_both_levels_together(self):
        """ลดรายรายการ 20 แล้วลดท้ายบิลอีก 10% ของ 80 ที่เหลือ = 28"""
        order_no, _ = self.order(
            total_amount=72, discount_percent=10,
            items=[{"id": "M1", "name": "ข้าวผัด", "price": 100, "qty": 1, "discount": 20}],
            discount_reason="ของเสียกับส่วนลดร้าน")
        self.assertEqual(self.recorded(order_no)["discount"], 2800)

    def test_a_discount_with_no_reason_is_refused(self):
        self.order(total_amount=90, discount_percent=10, expect=400)

    def test_the_shipped_android_till_can_still_close_a_bill(self):
        """แอปที่ลงเครื่องร้านไปแล้วส่ง discount เปล่า ๆ ไม่มีเหตุผลมาด้วย
        ถ้าบังคับเหตุผลกับช่องนี้ ร้านที่ใช้แอปเดิมจะปิดบิลไม่ได้
        หน้าจอของตัวใหม่ถามเหตุผลก่อนส่งอยู่แล้ว"""
        order_no, _ = self.order(total_amount=80, discount=20)
        kept = self.recorded(order_no)
        self.assertEqual(kept["discount"], 2000)
        self.assertEqual(kept["reason"], "")

    def test_a_bill_with_no_discount_needs_no_reason(self):
        order_no, _ = self.order(total_amount=100)
        self.assertEqual(self.recorded(order_no)["discount"], 0)

    def test_more_than_the_bill_is_capped_not_negative(self):
        order_no, _ = self.order(total_amount=0, discount=500,
                                 discount_reason="แถมให้ทั้งบิล")
        kept = self.recorded(order_no)
        self.assertEqual(kept["discount"], 10000)
        self.assertEqual(kept["total"], 0)

    def test_a_guest_at_the_table_cannot_discount_their_own_food(self):
        guest = TestClient(server.app)
        payload = json.dumps({"b": 1, "t": "1", "e": int(time.time()) + 3600,
                              "s": server.CURRENT_SHOP.get()}, separators=(",", ":")).encode()
        encoded = base64.urlsafe_b64encode(payload).decode().rstrip("=")
        signature = hmac.new(server.TABLE_QR_SECRET.encode(), payload, hashlib.sha256).hexdigest()
        ticket = f"{encoded}.{signature}"
        def guest_order(**extra):
            body = {"event_id": str(uuid.uuid4()), "order_no": f"ORD-{uuid.uuid4()}",
                    "branch_id": 1, "table_no": "1", "total_amount": 100,
                    "items": [{"id": "M1", "name": "ข้าวผัด", "price": 100, "qty": 1}]}
            body.update(extra)
            return guest.post("/api/orders", json=body, headers={"X-Table-Token": ticket})

        # ตัวคุม: โทเคนนี้สั่งได้จริง การถูกปฏิเสธข้างล่างจึงเป็นเพราะส่วนลด
        # ไม่ใช่เพราะโทเคนเสีย
        self.assertEqual(guest_order().status_code, 200)
        refused = guest_order(total_amount=90, discount_percent=10,
                              discount_reason="อยากลด")
        self.assertEqual(refused.status_code, 403, refused.text)
        self.assertIn("ลดราคา", refused.json()["detail"])


class TheReportSaysWhoDiscountedAndWhy(DiscountApiCase):
    def test_a_discounted_bill_shows_up_with_its_reason(self):
        order_no, _ = self.order(total_amount=90, discount_percent=10,
                                 discount_reason="ลูกค้าประจำ")
        with self.conn:
            self.conn.execute(
                "INSERT INTO pos_orders (branch_id, order_no, closed_by_staff_id, total_amount,"
                " net_amount, payment_method, status, closed_at)"
                " VALUES (1,?,1,90,90,'เงินสด (Cash)','paid',"
                " strftime('%Y-%m-%d %H:%M:%f','now'))", (order_no,))
        report = self.owner.get("/api/reports/sales?branch_id=1")
        self.assertEqual(report.status_code, 200, report.text)
        discounts = report.json()["discounts"]
        self.assertEqual(discounts["total"], 10)
        self.assertEqual(discounts["bills"], 1)
        self.assertEqual(discounts["by_staff"][0]["name"], "เจ้าของ")
        self.assertEqual(discounts["recent"][0]["reason"], "ลูกค้าประจำ")

    def test_a_bill_with_no_discount_is_not_listed(self):
        order_no, _ = self.order(total_amount=100)
        with self.conn:
            self.conn.execute(
                "INSERT INTO pos_orders (branch_id, order_no, closed_by_staff_id, total_amount,"
                " net_amount, payment_method, status, closed_at)"
                " VALUES (1,?,1,100,100,'เงินสด (Cash)','paid',"
                " strftime('%Y-%m-%d %H:%M:%f','now'))", (order_no,))
        discounts = self.owner.get("/api/reports/sales?branch_id=1").json()["discounts"]
        self.assertEqual(discounts["bills"], 0)
        self.assertEqual(discounts["recent"], [])


if __name__ == "__main__":
    unittest.main()
