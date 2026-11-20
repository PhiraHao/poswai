"""คืนเงินบางส่วน และใบลดหนี้ ตามมาตรา 86/10

ลูกค้าสั่งห้าจาน จานหนึ่งมาผิด ร้านคืนเงินจานนั้นจานเดียว ของเดิมทำได้อย่างเดียว
คือคืนทั้งบิลแล้วคีย์ใหม่สี่จาน ซึ่งทำให้ยอดขายของวันมีบิลผีเพิ่มหนึ่งใบ ยอดคืนเงิน
เกินจริงไปทั้งบิล และคอมมิชชันของพนักงานถูกหักเต็มทั้งที่ขายได้สี่จาน

เรื่องที่ต้องจริงทุกครั้ง: ยอดขายที่รายงานเห็น ต้องลดลงเท่ากับเงินที่ออกจากลิ้นชัก
และบิลที่เคยออกใบกำกับภาษีไว้ ต้องออกใบลดหนี้ได้ พร้อม VAT ของส่วนที่ลด —
ถ้าไม่มีใบลดหนี้ ร้านต้องนำส่ง VAT ของเงินที่คืนไปแล้ว
"""

import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

import line_pos_server as server
import poswai_tax_invoice as tax_invoice


class RefundCase(unittest.TestCase):
    """ร้านจดทะเบียน VAT 7% ค่าบริการ 10% เมนูจานละ 100 ให้เลขตรวจได้ด้วยมือ"""

    SHOP = {"vat_rate_bp": 700, "vat_inclusive": 0, "service_charge_bp": 1000,
            "tax_id": "0105556000335", "address": "1 ถนนทดสอบ กรุงเทพฯ", "shop_name": "ร้านทดสอบ"}

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.directory.cleanup)
        server.DB_PATH = Path(self.directory.name) / "refund.db"
        server.PREVIEW_ONLY = False
        server.BOOTSTRAP_MANAGER_PIN = ""
        server.TABLE_QR_SECRET = "k" * 48
        server.init_db()
        self.conn = sqlite3.connect(server.DB_PATH)
        self.addCleanup(self.conn.close)
        with self.conn:
            self.conn.execute("INSERT INTO branches(id,name) VALUES(1,'ร้าน')")
            for staff_id, name, role in ((1, "เจ้าของ", "owner"), (2, "แคชเชียร์", "cashier"),
                                         (3, "ผู้จัดการ", "manager")):
                self.conn.execute("INSERT INTO staffs(id,branch_id,name,role,pin_code_hash)"
                                  " VALUES(?,1,?,?,?)",
                                  (staff_id, name, role, server.hash_pin(f"secure-pin-{staff_id}")))
            known = {name: value for name, value in self.SHOP.items()
                     if name in {row[1] for row in self.conn.execute("PRAGMA table_info(shop_profile)")}}
            assignments = ",".join(f"{name}=?" for name in known)
            self.conn.execute(f"UPDATE shop_profile SET {assignments}", tuple(known.values()))
        self.owner = self.signed_in(1)
        self.assertEqual(self.owner.put("/api/menu/M1", json={
            "branch_id": 1, "name": "ข้าวผัด", "price": 100,
            "service_charge": True}).status_code, 200)

    def signed_in(self, staff_id):
        client = TestClient(server.app)
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        self.assertEqual(client.post("/api/auth/login",
                                     json={"staff_id": staff_id,
                                           "pin": f"secure-pin-{staff_id}"}).status_code, 200)
        return client

    def paid_bill(self, qty=5):
        """บิลหนึ่งใบที่รับเงินแล้ว คืนเลขบิลกับยอดเป็นสตางค์"""
        order_no = f"ORD-{uuid.uuid4()}"
        body = {"event_id": str(uuid.uuid4()), "order_no": order_no, "branch_id": 1,
                "table_no": "1", "total_amount": 0,
                "items": [{"id": "M1", "name": "ข้าวผัด", "price": 100, "qty": qty}]}
        answer = self.owner.post("/api/orders", json=body)
        if answer.status_code == 409:
            # 100 บาทต่อจาน + ค่าบริการ 10% + VAT 7% ของยอดหลังค่าบริการ
            body["total_amount"] = round(qty * 100 * 1.1 * 1.07, 2)
            answer = self.owner.post("/api/orders", json=body)
        self.assertEqual(answer.status_code, 200, answer.text)
        total = self.total_cents(order_no)
        close = self.owner.post("/api/payments/close", json={
            "event_id": str(uuid.uuid4()), "order_no": order_no,
            "amount": total / 100, "method": server.MANUAL_CASH})
        self.assertEqual(close.status_code, 200, close.text)
        return order_no, total

    def total_cents(self, order_no):
        return round(self.conn.execute("SELECT total_amount FROM order_events WHERE order_no=?",
                                       (order_no,)).fetchone()[0] * 100)

    def net_cents(self, order_no):
        return round(self.conn.execute("SELECT net_amount FROM pos_orders WHERE order_no=?",
                                       (order_no,)).fetchone()[0] * 100)

    def line_ids(self, order_no):
        return [row[0] for row in self.conn.execute(
            "SELECT rowid FROM order_items WHERE order_no=? ORDER BY rowid", (order_no,))]

    def refund(self, order_no, *, picks=(), amount=None, reason="จานหนึ่งมาผิด",
               client=None, expect=200, override=""):
        body = {"branch_id": 1, "event_id": str(uuid.uuid4()), "reason": reason,
                "picks": [{"line_id": line, "qty": qty} for line, qty in picks],
                "amount": amount, "override": override}
        answer = (client or self.owner).post(
            f"/api/orders/{order_no}/refund-partial", json=body)
        self.assertEqual(answer.status_code, expect, answer.text)
        return answer

    def invoice(self, order_no):
        answer = self.owner.post("/api/tax-invoices", json={
            "branch_id": 1, "order_no": order_no, "name": "บริษัท ทดสอบ จำกัด",
            "tax_id": "0105556000335", "address": "2 ถนนลูกค้า", "branch": "สำนักงานใหญ่"})
        self.assertEqual(answer.status_code, 200, answer.text)
        return answer.json()


class GivingBackPartOfABill(RefundCase):
    def test_one_dish_out_of_five(self):
        """คืนจานเดียวจากห้าจาน = หนึ่งในห้าของยอดบิล รวมค่าบริการและ VAT"""
        order_no, total = self.paid_bill(qty=5)
        answer = self.refund(order_no, picks=[(self.line_ids(order_no)[0], 1)]).json()
        self.assertEqual(round(answer["refund"]["amount"] * 100), total // 5)

    def test_what_the_shop_actually_kept_goes_down(self):
        """รายงานทุกตัวอ่าน net_amount ยอดขายจึงต้องลดลงทันทีโดยไม่ต้องแก้รายงาน"""
        order_no, total = self.paid_bill(qty=5)
        self.refund(order_no, picks=[(self.line_ids(order_no)[0], 1)])
        self.assertEqual(self.net_cents(order_no), total - total // 5)

    def test_the_bill_itself_still_says_what_the_customer_paid(self):
        order_no, total = self.paid_bill(qty=5)
        self.refund(order_no, picks=[(self.line_ids(order_no)[0], 1)])
        self.assertEqual(self.total_cents(order_no), total)

    def test_the_vat_of_the_refunded_part_is_recorded(self):
        """เลขนี้คือเลขที่ต้องลงใบลดหนี้ ถ้าไม่เก็บไว้ ใบลดหนี้ก็ออกไม่ได้"""
        order_no, _ = self.paid_bill(qty=5)
        answer = self.refund(order_no, picks=[(self.line_ids(order_no)[0], 1)]).json()
        # 100 บาท + ค่าบริการ 10 = 110 · VAT 7% = 7.70
        self.assertEqual(answer["refund"]["vat"], 7.70)
        self.assertEqual(answer["refund"]["service_charge"], 10.0)

    def test_refunding_a_plain_amount_carries_its_share_of_vat(self):
        """คืนเงินเปล่า ๆ โดยไม่คืน VAT แปลว่าร้านจ่าย VAT ของเงินที่ไม่ได้รับ"""
        order_no, total = self.paid_bill(qty=5)
        answer = self.refund(order_no, amount=total / 200).json()   # ครึ่งบิล
        self.assertGreater(answer["refund"]["vat"], 0)
        whole_vat = self.conn.execute("SELECT vat_cents FROM order_events WHERE order_no=?",
                                      (order_no,)).fetchone()[0]
        self.assertEqual(answer["refund"]["vat_cents"], whole_vat // 2)

    def test_several_refunds_on_one_bill_add_up(self):
        order_no, total = self.paid_bill(qty=5)
        lines = self.line_ids(order_no)
        first = self.refund(order_no, picks=[(lines[0], 1)]).json()
        second = self.refund(order_no, picks=[(lines[0], 2)]).json()
        given = round((first["refund"]["amount"] + second["refund"]["amount"]) * 100)
        self.assertEqual(self.net_cents(order_no), total - given)

    def test_refunding_everything_closes_the_bill_as_refunded(self):
        """คืนจนครบยอดแล้ว บิลนี้เท่ากับถูกคืนทั้งใบ รายงานต้องไม่นับเป็นยอดขาย"""
        order_no, total = self.paid_bill(qty=2)
        lines = self.line_ids(order_no)
        self.refund(order_no, picks=[(lines[0], 2)])
        row = self.conn.execute("SELECT e.status,p.status FROM order_events e"
                                " JOIN pos_orders p ON p.order_no=e.order_no"
                                " WHERE e.order_no=?", (order_no,)).fetchone()
        self.assertEqual(row, ("refunded", "refunded"))

    def test_the_stock_of_the_refunded_dishes_comes_back(self):
        self.assertEqual(self.owner.put("/api/inventory/ข้าว", json={
            "branch_id": 1, "stock": 100, "unit": "กรัม"}).status_code, 200)
        self.assertEqual(self.owner.put("/api/menu/M9", json={
            "branch_id": 1, "name": "ข้าวเปล่า", "price": 20,
            "bom": [{"ingId": "ข้าว", "qty": 10}]}).status_code, 200)
        order_no = f"ORD-{uuid.uuid4()}"
        body = {"event_id": str(uuid.uuid4()), "order_no": order_no, "branch_id": 1,
                "table_no": "1", "total_amount": 0,
                "items": [{"id": "M9", "name": "ข้าวเปล่า", "price": 20, "qty": 3}]}
        answer = self.owner.post("/api/orders", json=body)
        if answer.status_code == 409:
            body["total_amount"] = round(3 * 20 * 1.07, 2)
            answer = self.owner.post("/api/orders", json=body)
        self.assertEqual(answer.status_code, 200, answer.text)
        self.assertEqual(self.owner.post("/api/payments/close", json={
            "event_id": str(uuid.uuid4()), "order_no": order_no,
            "amount": self.total_cents(order_no) / 100,
            "method": server.MANUAL_CASH}).status_code, 200)
        left = lambda: self.conn.execute(
            "SELECT stock FROM inventory WHERE branch_id=1 AND ingredient_id='ข้าว'").fetchone()[0]
        before = left()
        self.refund(order_no, picks=[(self.line_ids(order_no)[0], 1)])
        self.assertEqual(left(), before + 10)

    def test_the_log_says_who_gave_money_back_and_why(self):
        order_no, _ = self.paid_bill(qty=5)
        self.refund(order_no, picks=[(self.line_ids(order_no)[0], 1)],
                    reason="ลูกค้าแพ้อาหาร", client=self.signed_in(3))
        row = self.conn.execute("SELECT staff_name,subject,detail,amount_cents FROM staff_activity"
                                " WHERE action='refund_partial'").fetchone()
        self.assertEqual(row[0], "ผู้จัดการ")
        self.assertIn(order_no, row[1])
        self.assertEqual(row[2], "ลูกค้าแพ้อาหาร")


class WhatARefundRefuses(RefundCase):
    def test_more_than_the_bill_has_left(self):
        order_no, total = self.paid_bill(qty=2)
        self.refund(order_no, amount=total / 100 + 1, expect=409)

    def test_the_same_dish_twice_over(self):
        order_no, _ = self.paid_bill(qty=2)
        line = self.line_ids(order_no)[0]
        self.refund(order_no, picks=[(line, 2)])
        self.refund(order_no, picks=[(line, 1)], expect=409)

    def test_items_and_an_amount_together(self):
        """สองคำตอบว่า VAT ที่คืนคือเท่าไร และใบลดหนี้ต้องมีคำตอบเดียว"""
        order_no, _ = self.paid_bill(qty=2)
        self.refund(order_no, picks=[(self.line_ids(order_no)[0], 1)], amount=10, expect=400)

    def test_neither_items_nor_an_amount(self):
        order_no, _ = self.paid_bill(qty=2)
        self.refund(order_no, expect=400)

    def test_no_reason(self):
        order_no, _ = self.paid_bill(qty=2)
        self.refund(order_no, picks=[(self.line_ids(order_no)[0], 1)], reason="ก", expect=400)

    def test_a_bill_nobody_has_paid_for_yet(self):
        order_no = f"ORD-{uuid.uuid4()}"
        body = {"event_id": str(uuid.uuid4()), "order_no": order_no, "branch_id": 1,
                "table_no": "1", "total_amount": 0,
                "items": [{"id": "M1", "name": "ข้าวผัด", "price": 100, "qty": 1}]}
        answer = self.owner.post("/api/orders", json=body)
        if answer.status_code == 409:
            body["total_amount"] = round(100 * 1.1 * 1.07, 2)
            self.owner.post("/api/orders", json=body)
        self.refund(order_no, amount=10, expect=409)

    def test_a_cashier_needs_a_manager(self):
        order_no, _ = self.paid_bill(qty=2)
        self.refund(order_no, picks=[(self.line_ids(order_no)[0], 1)],
                    client=self.signed_in(2), expect=403)

    def test_a_cashier_with_the_managers_approval_may(self):
        order_no, total = self.paid_bill(qty=2)
        cashier = self.signed_in(2)
        granted = cashier.post("/api/auth/override", json={
            "branch_id": 1, "action": "refund", "staff_id": 3, "pin": "secure-pin-3"})
        self.assertEqual(granted.status_code, 200, granted.text)
        answer = self.refund(order_no, picks=[(self.line_ids(order_no)[0], 1)],
                             client=cashier, override=granted.json()["token"]).json()
        self.assertEqual(round(answer["refund"]["amount"] * 100), total // 2)
        row = self.conn.execute("SELECT detail FROM staff_activity"
                                " WHERE action='refund_partial'").fetchone()
        self.assertIn("ผู้จัดการ", row[0])

    def test_pressing_twice_on_a_slow_connection_refunds_once(self):
        order_no, total = self.paid_bill(qty=5)
        body = {"branch_id": 1, "event_id": str(uuid.uuid4()), "reason": "จานไหม้",
                "picks": [{"line_id": self.line_ids(order_no)[0], "qty": 1}], "amount": None}
        first = self.owner.post(f"/api/orders/{order_no}/refund-partial", json=body)
        self.assertEqual(first.status_code, 200, first.text)
        again = self.owner.post(f"/api/orders/{order_no}/refund-partial", json=body)
        self.assertEqual(again.status_code, 200, again.text)
        self.assertEqual(again.json()["status"], "existing")
        self.assertEqual(self.net_cents(order_no), total - total // 5)


class WhatTheScreenAsksFirst(RefundCase):
    def test_it_says_how_much_is_left_and_what_is_left_to_give_back(self):
        order_no, total = self.paid_bill(qty=5)
        self.refund(order_no, picks=[(self.line_ids(order_no)[0], 2)])
        answer = self.owner.get(f"/api/orders/{order_no}/refundable?branch_id=1")
        self.assertEqual(answer.status_code, 200, answer.text)
        sheet = answer.json()
        self.assertEqual(round(sheet["total"] * 100), total)
        self.assertEqual(sheet["lines"][0]["left"], 3)
        self.assertEqual(len(sheet["refunds"]), 1)

    def test_it_says_whether_a_tax_invoice_was_issued(self):
        """บิลที่เคยออกใบกำกับภาษี ต้องตามด้วยใบลดหนี้ หน้าจอต้องรู้ตั้งแต่ก่อนกด"""
        order_no, _ = self.paid_bill(qty=5)
        plain = self.owner.get(f"/api/orders/{order_no}/refundable?branch_id=1").json()
        self.assertEqual(plain["tax_invoice"], "")
        number = self.invoice(order_no)["number"]
        after = self.owner.get(f"/api/orders/{order_no}/refundable?branch_id=1").json()
        self.assertEqual(after["tax_invoice"], number)

    def test_the_screen_is_served(self):
        answer = TestClient(server.app).get("/refund-partial.js")
        self.assertEqual(answer.status_code, 200, answer.text)


class TheCreditNote(RefundCase):
    def note_for(self, order_no, number, refund_id, *, expect=200, client=None):
        answer = (client or self.owner).post(
            f"/api/tax-invoices/{number}/credit-note",
            json={"branch_id": 1, "refund_id": refund_id})
        self.assertEqual(answer.status_code, expect, answer.text)
        return answer

    def test_it_states_everything_section_86_10_asks_for(self):
        order_no, total = self.paid_bill(qty=5)
        invoice = self.invoice(order_no)
        given = self.refund(order_no, picks=[(self.line_ids(order_no)[0], 1)],
                            reason="ลูกค้าแพ้อาหาร").json()["refund"]
        note = self.note_for(order_no, invoice["number"], given["id"]).json()
        # เลขใบกำกับภาษีเดิม มูลค่าตามใบเดิม มูลค่าที่ถูกต้อง ผลต่าง และ VAT ของผลต่าง
        self.assertEqual(note["original_invoice"]["number"], invoice["number"])
        self.assertEqual(round(note["original_invoice"]["total"] * 100), total)
        self.assertEqual(round(note["corrected_total"] * 100), total - total // 5)
        self.assertEqual(round(note["difference"]["total"] * 100), total // 5)
        self.assertEqual(note["difference"]["vat"], 7.70)
        self.assertEqual(note["reason"], "ลูกค้าแพ้อาหาร")
        self.assertTrue(note["seller"]["tax_id"])
        self.assertEqual(note["buyer"]["name"], "บริษัท ทดสอบ จำกัด")

    def test_its_number_is_its_own_series(self):
        """เลขปนกับใบกำกับภาษีไม่ได้ สรรพากรดูสองชุดนี้แยกกัน"""
        order_no, _ = self.paid_bill(qty=5)
        invoice = self.invoice(order_no)
        given = self.refund(order_no, picks=[(self.line_ids(order_no)[0], 1)]).json()["refund"]
        number = self.note_for(order_no, invoice["number"], given["id"]).json()["number"]
        self.assertTrue(number.startswith("CN"), number)
        self.assertNotEqual(number, invoice["number"])

    def test_the_numbers_run_without_repeating(self):
        order_no, _ = self.paid_bill(qty=5)
        invoice = self.invoice(order_no)
        numbers = []
        for _ in range(3):
            given = self.refund(order_no, picks=[(self.line_ids(order_no)[0], 1)]).json()["refund"]
            numbers.append(self.note_for(order_no, invoice["number"], given["id"]).json()["number"])
        self.assertEqual(len(set(numbers)), 3)
        self.assertEqual(numbers, sorted(numbers))

    def test_asking_twice_hands_back_the_same_one(self):
        """ขอซ้ำคืออยากได้เอกสาร ไม่ใช่อยากได้ใบที่สองของการคืนครั้งเดียว"""
        order_no, _ = self.paid_bill(qty=5)
        invoice = self.invoice(order_no)
        given = self.refund(order_no, picks=[(self.line_ids(order_no)[0], 1)]).json()["refund"]
        first = self.note_for(order_no, invoice["number"], given["id"]).json()
        again = self.note_for(order_no, invoice["number"], given["id"]).json()
        self.assertEqual(first["number"], again["number"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM credit_notes").fetchone()[0], 1)

    def test_several_notes_keep_lowering_the_corrected_value(self):
        order_no, total = self.paid_bill(qty=5)
        invoice = self.invoice(order_no)
        line = self.line_ids(order_no)[0]
        first = self.refund(order_no, picks=[(line, 1)]).json()["refund"]
        self.note_for(order_no, invoice["number"], first["id"])
        second = self.refund(order_no, picks=[(line, 1)]).json()["refund"]
        note = self.note_for(order_no, invoice["number"], second["id"]).json()
        self.assertEqual(round(note["corrected_total"] * 100), total - 2 * (total // 5))

    def test_a_cancelled_tax_invoice_gets_no_credit_note(self):
        order_no, _ = self.paid_bill(qty=5)
        invoice = self.invoice(order_no)
        given = self.refund(order_no, picks=[(self.line_ids(order_no)[0], 1)]).json()["refund"]
        self.assertEqual(self.owner.post(f"/api/tax-invoices/{invoice['number']}/cancel",
                                         json={"reason": "ออกผิดใบ"}).status_code, 200)
        self.note_for(order_no, invoice["number"], given["id"], expect=409)

    def test_a_refund_from_another_bill(self):
        first_no, _ = self.paid_bill(qty=5)
        other_no, _ = self.paid_bill(qty=5)
        invoice = self.invoice(first_no)
        given = self.refund(other_no, picks=[(self.line_ids(other_no)[0], 1)]).json()["refund"]
        self.note_for(other_no, invoice["number"], given["id"], expect=409)

    def test_a_refund_that_does_not_exist(self):
        order_no, _ = self.paid_bill(qty=5)
        invoice = self.invoice(order_no)
        self.note_for(order_no, invoice["number"], 9999, expect=404)

    def test_it_can_be_printed_again_exactly_as_issued(self):
        order_no, _ = self.paid_bill(qty=5)
        invoice = self.invoice(order_no)
        given = self.refund(order_no, picks=[(self.line_ids(order_no)[0], 1)]).json()["refund"]
        made = self.note_for(order_no, invoice["number"], given["id"]).json()
        again = self.owner.get(f"/api/credit-notes/{made['number']}")
        self.assertEqual(again.status_code, 200, again.text)
        self.assertEqual(again.json(), made)

    def test_the_owner_can_list_them(self):
        order_no, _ = self.paid_bill(qty=5)
        invoice = self.invoice(order_no)
        given = self.refund(order_no, picks=[(self.line_ids(order_no)[0], 1)]).json()["refund"]
        self.note_for(order_no, invoice["number"], given["id"])
        answer = self.owner.get("/api/credit-notes?branch_id=1")
        self.assertEqual(answer.status_code, 200, answer.text)
        self.assertEqual(len(answer.json()["credit_notes"]), 1)

    def test_a_guest_cannot_read_one(self):
        self.assertEqual(TestClient(server.app).get("/api/credit-notes?branch_id=1").status_code, 401)
        self.assertEqual(TestClient(server.app).get("/api/credit-notes/CN2611-0001").status_code, 401)

    def test_the_log_says_which_invoice_was_reduced(self):
        order_no, _ = self.paid_bill(qty=5)
        invoice = self.invoice(order_no)
        given = self.refund(order_no, picks=[(self.line_ids(order_no)[0], 1)]).json()["refund"]
        made = self.note_for(order_no, invoice["number"], given["id"]).json()
        row = self.conn.execute("SELECT subject,detail,amount_cents FROM staff_activity"
                                " WHERE action='credit_note'").fetchone()
        self.assertIn(made["number"], row[0])
        self.assertIn(invoice["number"], row[1])
        self.assertEqual(row[2], round(made["difference"]["total"] * 100))


class TheNumberingItself(unittest.TestCase):
    """เลขใบลดหนี้ต้องไม่ซ้ำและไม่ย้อน แม้ใบก่อนหน้าถูกยกเลิก"""

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        tax_invoice.init_tax_invoices(self.conn)
        tax_invoice.init_credit_notes(self.conn)

    def test_it_starts_at_one_for_the_month(self):
        import datetime as dt
        self.assertEqual(tax_invoice.next_credit_number(self.conn, dt.date(2026, 11, 15)),
                         "CN2611-0001")

    def test_a_cancelled_note_still_burns_its_number(self):
        import datetime as dt
        day = dt.date(2026, 11, 15)
        self.conn.execute(
            "INSERT INTO credit_notes (number,tax_invoice_id,refund_id,order_no,branch_id,"
            "issued_by,reason,original_total_cents,corrected_total_cents,diff_total_cents,"
            "cancelled_at) VALUES ('CN2611-0001',1,1,'ORD-1',1,1,'ผิด',100,0,100,'now')")
        self.assertEqual(tax_invoice.next_credit_number(self.conn, day), "CN2611-0002")


if __name__ == "__main__":
    unittest.main()
