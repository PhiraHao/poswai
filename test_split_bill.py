"""แยกบิล ย้ายโต๊ะ และรวมบิล

สามเรื่องที่ร้านอาหารเจอทุกวัน และของเดิมทำไม่ได้เลย ทางออกที่ร้านใช้คือยกเลิก
บิลแล้วคีย์ใหม่ ซึ่งทำให้รายงานยอดยกเลิกของวันโตขึ้นโดยไม่มีใครโกงอะไร และครัว
ได้ตั๋วซ้ำของอาหารที่ทำเสร็จไปแล้ว

สิ่งที่ต้องจริงทุกครั้ง: ผลรวมของบิลที่แยกออกมาต้องเท่ากับบิลเดิมทุกสตางค์
ถ้าไม่เท่า ร้านเก็บเงินได้ไม่เท่าที่ตกลงกับลูกค้า ซึ่งแย่กว่าการไม่มีฟีเจอร์นี้เลย
"""

import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

import line_pos_server as server
import poswai_split as split_bills


class SharingOneAmountBetweenTwoBills(unittest.TestCase):
    """_share: แบ่งยอดก้อนเดียวแล้วผลรวมต้องเท่าเดิมเสมอ"""

    def test_it_splits_in_proportion(self):
        self.assertEqual(split_bills._share([7000, 3000], 1000), [700, 300])

    def test_the_remainder_goes_to_the_larger_share(self):
        parts = split_bills._share([3333, 6667], 101)
        self.assertEqual(sum(parts), 101)
        self.assertEqual(parts, [34, 67])

    def test_nothing_to_share_is_nothing(self):
        self.assertEqual(split_bills._share([100, 200], 0), [0, 0])

    def test_no_weight_anywhere_still_keeps_the_money(self):
        """ค่าบริการที่ไม่มีรายการไหนต้องเสีย แต่คอลัมน์ยังมีเลขค้าง — เงินห้ามหาย"""
        self.assertEqual(split_bills._share([0, 0], 500), [500, 0])

    def test_one_side_empty_takes_nothing(self):
        self.assertEqual(split_bills._share([1000, 0], 77), [77, 0])


class TillCase(unittest.TestCase):
    """ร้านเดียว เมนูจานละ 100 คิด VAT 7% ค่าบริการ 10% ให้เลขตรวจได้ด้วยมือ"""

    SHOP = {"vat_rate_bp": 700, "vat_inclusive": 0, "service_charge_bp": 1000}

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.directory.cleanup)
        server.DB_PATH = Path(self.directory.name) / "split.db"
        server.PREVIEW_ONLY = False
        server.BOOTSTRAP_MANAGER_PIN = ""
        server.TABLE_QR_SECRET = "k" * 48
        server.init_db()
        self.conn = sqlite3.connect(server.DB_PATH)
        self.addCleanup(self.conn.close)
        with self.conn:
            self.conn.execute("INSERT INTO branches(id,name) VALUES(1,'ร้าน'),(2,'สาขาสอง')")
            for staff_id, name, role, branch in ((1, "เจ้าของ", "owner", 1),
                                                 (2, "แคชเชียร์", "cashier", 1),
                                                 (3, "เสิร์ฟ", "service", 1),
                                                 (4, "ครัว", "kitchen", 1),
                                                 (5, "แคชเชียร์สาขาสอง", "cashier", 2)):
                self.conn.execute("INSERT INTO staffs(id,branch_id,name,role,pin_code_hash)"
                                  " VALUES(?,?,?,?,?)",
                                  (staff_id, branch, name, role,
                                   server.hash_pin(f"secure-pin-{staff_id}")))
            assignments = ",".join(f"{name}=?" for name in self.SHOP)
            self.conn.execute(f"UPDATE shop_profile SET {assignments}", tuple(self.SHOP.values()))
        self.owner = self.signed_in(1)
        self.assertEqual(self.owner.put("/api/menu/M1", json={
            "branch_id": 1, "name": "ข้าวผัด", "price": 100,
            "service_charge": True}).status_code, 200)
        for table_no in ("1", "2", "3"):
            self.assertEqual(self.owner.post("/api/tables", json={
                "branch_id": 1, "table_no": table_no, "seats": 4}).status_code, 200)

    def signed_in(self, staff_id):
        client = TestClient(server.app)
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        self.assertEqual(client.post("/api/auth/login",
                                     json={"staff_id": staff_id,
                                           "pin": f"secure-pin-{staff_id}"}).status_code, 200)
        return client

    def order(self, *, qty=1, table="1", items=None, client=None, **extra):
        """สั่งอาหารหนึ่งบิล แล้วคืนเลขบิล — ยอดให้เซิร์ฟเวอร์คิดเอง"""
        order_no = f"ORD-{uuid.uuid4()}"
        body = {"event_id": str(uuid.uuid4()), "order_no": order_no, "branch_id": 1,
                "table_no": table, "total_amount": 0,
                "items": items or [{"id": "M1", "name": "ข้าวผัด", "price": 100, "qty": qty}]}
        body.update(extra)
        answer = (client or self.owner).post("/api/orders", json=body)
        if answer.status_code != 200:
            # ยอดที่ส่งไปไม่ตรงคือเรื่องปกติ ถามเซิร์ฟเวอร์ว่าเท่าไรแล้วส่งอีกครั้ง
            self.assertEqual(answer.status_code, 409, answer.text)
            body["total_amount"] = self.quoted(body)
            answer = (client or self.owner).post("/api/orders", json=body)
        self.assertEqual(answer.status_code, 200, answer.text)
        return order_no

    def quoted(self, body):
        """ยอดที่กฎร้านคิดได้ สำหรับชุดรายการเดียวกัน"""
        import poswai_catalog as catalog
        import poswai_profile as profile

        class Line:
            def __init__(self, raw):
                self.__dict__.update(raw)

        with sqlite3.connect(server.DB_PATH) as conn:
            quote = catalog.quote_order(conn, 1, [Line(item) for item in body["items"]])
            for line, asked in zip(quote["items"], body["items"]):
                line["discount_cents"] = profile.discount_cents_for(
                    line["cents"], baht=asked.get("discount", 0),
                    percent=asked.get("discount_percent", 0))
            after = sum(line["cents"] - line["discount_cents"] for line in quote["items"])
            charge = profile.bill(quote["items"], profile=profile.read(conn),
                                 discount_cents=profile.discount_cents_for(
                                     after, baht=body.get("discount", 0),
                                     percent=body.get("discount_percent", 0)))
        return charge["total_cents"] / 100

    def totals(self, order_no):
        row = self.conn.execute(
            "SELECT subtotal_cents,discount_cents,service_charge_cents,vat_cents,"
            "total_amount,status,table_no FROM order_events WHERE order_no=?",
            (order_no,)).fetchone()
        self.assertIsNotNone(row, f"ไม่มีบิล {order_no}")
        return {"subtotal": row[0], "discount": row[1], "service": row[2], "vat": row[3],
                "total_cents": round(row[4] * 100), "status": row[5], "table": row[6]}

    def lines(self, order_no):
        return self.conn.execute("SELECT item_id,quantity,discount_cents FROM order_items"
                                 " WHERE order_no=? ORDER BY rowid", (order_no,)).fetchall()

    def line_ids(self, order_no, client=None):
        answer = (client or self.owner).get("/api/orders?branch_id=1")
        self.assertEqual(answer.status_code, 200, answer.text)
        for order in answer.json()["orders"]:
            if order["order_no"] == order_no:
                return [item["line_id"] for item in order["items"]]
        self.fail(f"ไม่เห็นบิล {order_no} ในรายการบิลที่เปิดอยู่")

    def split(self, order_no, picks, *, client=None, expect=200, new_order_no=None):
        body = {"branch_id": 1, "event_id": str(uuid.uuid4()),
                "new_order_no": new_order_no or f"ORD-{uuid.uuid4()}",
                "picks": [{"line_id": line, "qty": qty} for line, qty in picks]}
        answer = (client or self.owner).post(f"/api/orders/{order_no}/split", json=body)
        self.assertEqual(answer.status_code, expect, answer.text)
        return body["new_order_no"], answer

    def activity(self, action):
        return self.conn.execute("SELECT staff_name,subject,detail,amount_cents FROM staff_activity"
                                 " WHERE action=? ORDER BY id", (action,)).fetchall()


class SplittingOneBillIntoTwo(TillCase):
    def test_the_two_bills_add_up_to_the_one_they_came_from(self):
        """ข้าวผัด 3 จาน แยกออก 1 — ลูกค้ายังจ่ายรวมเท่าเดิม"""
        order_no = self.order(qty=3)
        before = self.totals(order_no)
        new_no, _ = self.split(order_no, [(self.line_ids(order_no)[0], 1)])
        kept, created = self.totals(order_no), self.totals(new_no)
        self.assertEqual(kept["total_cents"] + created["total_cents"], before["total_cents"])
        for field in ("subtotal", "discount", "service", "vat"):
            self.assertEqual(kept[field] + created[field], before[field], field)

    def test_each_bill_holds_together_on_its_own(self):
        """ยอดรวมของแต่ละใบต้องเท่ากับรายละเอียดของใบนั้น ไม่งั้นพิมพ์ใบเสร็จไม่ได้"""
        order_no = self.order(qty=3)
        new_no, _ = self.split(order_no, [(self.line_ids(order_no)[0], 1)])
        for number in (order_no, new_no):
            part = self.totals(number)
            self.assertEqual(
                part["total_cents"],
                part["subtotal"] - part["discount"] + part["service"] + part["vat"], number)

    def test_one_dish_out_of_three_costs_a_third(self):
        order_no = self.order(qty=3)
        new_no, _ = self.split(order_no, [(self.line_ids(order_no)[0], 1)])
        # 100 บาท + ค่าบริการ 10 + VAT 7% ของ 110 = 117.70
        self.assertEqual(self.totals(new_no)["total_cents"], 11770)
        self.assertEqual(self.totals(order_no)["total_cents"], 23540)

    def test_the_items_move_with_the_money(self):
        order_no = self.order(qty=3)
        new_no, _ = self.split(order_no, [(self.line_ids(order_no)[0], 1)])
        self.assertEqual(self.lines(order_no), [("M1", 2, 0)])
        self.assertEqual(self.lines(new_no), [("M1", 1, 0)])

    def test_a_whole_line_moving_leaves_no_empty_row_behind(self):
        order_no = self.order(items=[
            {"id": "M1", "name": "ข้าวผัด", "price": 100, "qty": 1},
            {"id": "M1", "name": "ข้าวผัด", "price": 100, "qty": 2}])
        first = self.line_ids(order_no)[0]
        new_no, _ = self.split(order_no, [(first, 1)])
        self.assertEqual(self.lines(order_no), [("M1", 2, 0)])
        self.assertEqual(self.lines(new_no), [("M1", 1, 0)])

    def test_a_line_discount_follows_the_dishes_it_was_given_for(self):
        """ลด 30 บาทจากข้าวผัด 3 จาน แยกออกจานหนึ่งต้องพาส่วนลด 10 บาทไปด้วย"""
        order_no = self.order(items=[{"id": "M1", "name": "ข้าวผัด", "price": 100,
                                      "qty": 3, "discount": 30}],
                              discount_reason="จานไหม้")
        before = self.totals(order_no)
        new_no, _ = self.split(order_no, [(self.line_ids(order_no)[0], 1)])
        self.assertEqual(self.lines(order_no), [("M1", 2, 2000)])
        self.assertEqual(self.lines(new_no), [("M1", 1, 1000)])
        self.assertEqual(self.totals(order_no)["total_cents"]
                         + self.totals(new_no)["total_cents"], before["total_cents"])

    def test_a_bill_wide_discount_is_shared_in_proportion(self):
        order_no = self.order(qty=3, discount_percent=10, discount_reason="ลูกค้าประจำ")
        before = self.totals(order_no)
        new_no, _ = self.split(order_no, [(self.line_ids(order_no)[0], 1)])
        self.assertEqual(self.totals(new_no)["discount"], 1000)      # 10% ของ 100 บาท
        self.assertEqual(self.totals(order_no)["discount"], 2000)
        self.assertEqual(self.totals(order_no)["total_cents"]
                         + self.totals(new_no)["total_cents"], before["total_cents"])

    def test_the_reason_for_the_discount_goes_on_both_bills(self):
        order_no = self.order(qty=2, discount_percent=10, discount_reason="ลูกค้าประจำ")
        new_no, _ = self.split(order_no, [(self.line_ids(order_no)[0], 1)])
        reason = self.conn.execute("SELECT discount_reason FROM order_events WHERE order_no=?",
                                   (new_no,)).fetchone()[0]
        self.assertEqual(reason, "ลูกค้าประจำ")

    def test_the_new_bill_sits_on_the_same_table(self):
        order_no = self.order(qty=2, table="2")
        new_no, _ = self.split(order_no, [(self.line_ids(order_no)[0], 1)])
        self.assertEqual(self.totals(new_no)["table"], "2")
        self.assertEqual(self.totals(new_no)["status"], "open")

    def test_an_odd_number_of_satang_still_adds_up(self):
        """เมนู 33.33 บาท สามจาน ลด 10% — ตรงนี้คือที่ที่การปัดเศษจะทำเงินหาย"""
        self.assertEqual(self.owner.put("/api/menu/M2", json={
            "branch_id": 1, "name": "น้ำเปล่า", "price": 33.33,
            "service_charge": True}).status_code, 200)
        order_no = self.order(items=[{"id": "M2", "name": "น้ำเปล่า", "price": 33.33, "qty": 3}],
                              discount_percent=10, discount_reason="โปร")
        before = self.totals(order_no)
        new_no, _ = self.split(order_no, [(self.line_ids(order_no)[0], 1)])
        kept, created = self.totals(order_no), self.totals(new_no)
        self.assertEqual(kept["total_cents"] + created["total_cents"], before["total_cents"])
        for field in ("subtotal", "discount", "service", "vat"):
            self.assertEqual(kept[field] + created[field], before[field], field)

    def test_a_dish_with_no_vat_carries_no_vat_to_its_own_bill(self):
        """ของที่ร้านตั้งว่าไม่คิด VAT ต้องไม่ถูกแบ่ง VAT มาใส่ตอนแยกบิล"""
        self.assertEqual(self.owner.put("/api/menu/M3", json={
            "branch_id": 1, "name": "ค่ามัดจำ", "price": 100,
            "tax_mode": "none", "service_charge": False}).status_code, 200)
        order_no = self.order(items=[
            {"id": "M1", "name": "ข้าวผัด", "price": 100, "qty": 1},
            {"id": "M3", "name": "ค่ามัดจำ", "price": 100, "qty": 1}])
        deposit_line = self.line_ids(order_no)[1]
        new_no, _ = self.split(order_no, [(deposit_line, 1)])
        created = self.totals(new_no)
        self.assertEqual(created["vat"], 0)
        self.assertEqual(created["service"], 0)
        self.assertEqual(created["total_cents"], 10000)
        self.assertEqual(self.totals(order_no)["vat"], 770)


class WhatSplittingRefuses(TillCase):
    def test_moving_everything_out_is_not_a_split(self):
        order_no = self.order(qty=2)
        _, answer = self.split(order_no, [(self.line_ids(order_no)[0], 2)], expect=400)
        self.assertIn("ย้ายโต๊ะ", answer.json()["detail"])

    def test_more_than_the_bill_has(self):
        order_no = self.order(qty=2)
        self.split(order_no, [(self.line_ids(order_no)[0], 3)], expect=400)

    def test_none_of_it(self):
        order_no = self.order(qty=2)
        self.split(order_no, [(self.line_ids(order_no)[0], 0)], expect=400)

    def test_nothing_chosen_at_all(self):
        order_no = self.order(qty=2)
        self.split(order_no, [], expect=400)

    def test_a_line_from_another_bill(self):
        mine = self.order(qty=2)
        theirs = self.order(qty=2)
        self.split(mine, [(self.line_ids(theirs)[0], 1)], expect=409)

    def test_the_same_line_twice(self):
        order_no = self.order(qty=3)
        line = self.line_ids(order_no)[0]
        self.split(order_no, [(line, 1), (line, 1)], expect=400)

    def test_a_bill_that_is_already_paid(self):
        order_no = self.order(qty=2)
        line = self.line_ids(order_no)[0]
        self.assertEqual(self.owner.post("/api/payments/close", json={
            "event_id": str(uuid.uuid4()), "order_no": order_no,
            "amount": self.totals(order_no)["total_cents"] / 100,
            "method": server.MANUAL_CASH}).status_code, 200)
        self.split(order_no, [(line, 1)], expect=409)

    def test_a_bill_number_that_is_already_taken(self):
        order_no = self.order(qty=3)
        taken = self.order(qty=1)
        self.split(order_no, [(self.line_ids(order_no)[0], 1)],
                   new_order_no=taken, expect=409)

    def test_a_bill_on_another_branch_looks_like_no_bill_at_all(self):
        order_no = self.order(qty=2)
        line = self.line_ids(order_no)[0]
        body = {"branch_id": 2, "event_id": str(uuid.uuid4()),
                "new_order_no": f"ORD-{uuid.uuid4()}", "picks": [{"line_id": line, "qty": 1}]}
        # แคชเชียร์สาขาสองเข้าเส้นนี้ได้ แต่บิลนี้อยู่สาขาหนึ่ง จึงต้องเป็น 404
        # ไม่ใช่ 403 — 403 เท่ากับยืนยันว่าบิลเลขนี้มีจริงในระบบ
        answer = self.signed_in(5).post(f"/api/orders/{order_no}/split", json=body)
        self.assertEqual(answer.status_code, 404, answer.text)

    def test_the_kitchen_cannot_split_bills(self):
        order_no = self.order(qty=2)
        line = self.line_ids(order_no)[0]
        self.split(order_no, [(line, 1)], client=self.signed_in(4), expect=403)

    def test_a_waiter_cannot_split_bills_either(self):
        """แยกบิลเปลี่ยนยอดที่จะเก็บ จึงเป็นเรื่องของคนที่รับเงิน"""
        order_no = self.order(qty=2)
        line = self.line_ids(order_no)[0]
        self.split(order_no, [(line, 1)], client=self.signed_in(3), expect=403)

    def test_pressing_twice_on_a_slow_connection_splits_once(self):
        order_no = self.order(qty=3)
        line = self.line_ids(order_no)[0]
        body = {"branch_id": 1, "event_id": str(uuid.uuid4()),
                "new_order_no": f"ORD-{uuid.uuid4()}", "picks": [{"line_id": line, "qty": 1}]}
        first = self.owner.post(f"/api/orders/{order_no}/split", json=body)
        self.assertEqual(first.status_code, 200, first.text)
        again = self.owner.post(f"/api/orders/{order_no}/split", json=body)
        self.assertEqual(again.status_code, 200, again.text)
        self.assertEqual(again.json()["status"], "existing")
        self.assertEqual(self.lines(order_no), [("M1", 2, 0)])

    def test_a_bill_from_before_the_server_kept_the_breakdown(self):
        """บิลเก่ามีแต่ยอดรวม แยกแล้วจะไม่รู้ว่า VAT ของแต่ละใบเท่าไร"""
        order_no = self.order(qty=2)
        line = self.line_ids(order_no)[0]
        with self.conn:
            self.conn.execute("UPDATE order_events SET subtotal_cents=0,discount_cents=0,"
                              "service_charge_cents=0,vat_cents=0 WHERE order_no=?", (order_no,))
        _, answer = self.split(order_no, [(line, 1)], expect=409)
        self.assertIn("รายละเอียดยอด", answer.json()["detail"])


class ClosingBothHalves(TillCase):
    def test_both_bills_take_money_like_any_other(self):
        order_no = self.order(qty=3)
        before = self.totals(order_no)
        new_no, _ = self.split(order_no, [(self.line_ids(order_no)[0], 1)])
        for number in (order_no, new_no):
            answer = self.owner.post("/api/payments/close", json={
                "event_id": str(uuid.uuid4()), "order_no": number,
                "amount": self.totals(number)["total_cents"] / 100,
                "method": server.MANUAL_CASH})
            self.assertEqual(answer.status_code, 200, answer.text)
        taken = self.conn.execute("SELECT COUNT(*),COALESCE(SUM(net_amount),0)"
                                  " FROM pos_orders WHERE status='paid'").fetchone()
        self.assertEqual(taken[0], 2)
        self.assertEqual(round(taken[1] * 100), before["total_cents"])

    def test_the_kitchen_keeps_the_food_it_already_has(self):
        """ตั๋วครัวตามเลขบิลใหม่ไป ไม่ใช่สร้างตั๋วใหม่ของอาหารที่เสิร์ฟแล้ว"""
        order_no = self.order(qty=3)
        with self.conn:
            self.conn.execute("UPDATE kds_station_tickets SET status='ready' WHERE order_no=?",
                              (order_no,))
        new_no, _ = self.split(order_no, [(self.line_ids(order_no)[0], 1)])
        moved = self.conn.execute("SELECT station,status FROM kds_station_tickets"
                                  " WHERE order_no=?", (new_no,)).fetchall()
        self.assertEqual(moved, [("ครัวร้อน", "ready")])

    def test_a_station_left_with_no_food_loses_its_ticket(self):
        self.assertEqual(self.owner.put("/api/menu/M4", json={
            "branch_id": 1, "name": "ชาเย็น", "price": 50,
            "station": "บาร์น้ำ"}).status_code, 200)
        order_no = self.order(items=[
            {"id": "M1", "name": "ข้าวผัด", "price": 100, "qty": 1},
            {"id": "M4", "name": "ชาเย็น", "price": 50, "qty": 1}])
        bar_line = self.line_ids(order_no)[1]
        new_no, _ = self.split(order_no, [(bar_line, 1)])
        self.assertEqual(
            [row[0] for row in self.conn.execute(
                "SELECT station FROM kds_station_tickets WHERE order_no=? ORDER BY station",
                (order_no,))], ["ครัวร้อน"])
        self.assertEqual(
            [row[0] for row in self.conn.execute(
                "SELECT station FROM kds_station_tickets WHERE order_no=?", (new_no,))], ["บาร์น้ำ"])

    def test_the_log_says_who_split_which_bill(self):
        order_no = self.order(qty=3)
        new_no, _ = self.split(order_no, [(self.line_ids(order_no)[0], 1)],
                               client=self.signed_in(2))
        rows = self.activity("split_bill")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "แคชเชียร์")
        self.assertIn(new_no, rows[0][1])
        self.assertIn(order_no, rows[0][1])
        self.assertEqual(rows[0][3], self.totals(new_no)["total_cents"])


class MovingABillToAnotherTable(TillCase):
    def move(self, order_no, table_no, *, client=None, expect=200):
        answer = (client or self.owner).post(f"/api/orders/{order_no}/move",
                                             json={"branch_id": 1, "table_no": table_no})
        self.assertEqual(answer.status_code, expect, answer.text)
        return answer

    def test_the_bill_follows_the_customer(self):
        order_no = self.order(qty=2, table="1")
        self.move(order_no, "3")
        self.assertEqual(self.totals(order_no)["table"], "3")

    def test_the_money_does_not_change(self):
        order_no = self.order(qty=2, table="1")
        before = self.totals(order_no)
        self.move(order_no, "3")
        self.assertEqual(self.totals(order_no)["total_cents"], before["total_cents"])

    def test_a_waiter_may_move_a_table(self):
        """คนที่ยืนอยู่ตรงนั้นคือพนักงานเสิร์ฟ ไม่ใช่แคชเชียร์"""
        order_no = self.order(qty=1)
        self.move(order_no, "2", client=self.signed_in(3))
        self.assertEqual(self.totals(order_no)["table"], "2")

    def test_the_kitchen_cannot(self):
        order_no = self.order(qty=1)
        self.move(order_no, "2", client=self.signed_in(4), expect=403)

    def test_a_table_the_shop_does_not_have(self):
        order_no = self.order(qty=1)
        self.move(order_no, "99", expect=404)

    def test_a_table_that_is_switched_off(self):
        order_no = self.order(qty=1)
        self.assertEqual(self.owner.patch("/api/tables/3",
                                          json={"branch_id": 1, "active": False}).status_code, 200)
        self.move(order_no, "3", expect=409)

    def test_the_table_it_is_already_on(self):
        order_no = self.order(qty=1, table="1")
        self.move(order_no, "1", expect=409)

    def test_a_paid_bill_stays_where_it_was(self):
        order_no = self.order(qty=1)
        self.assertEqual(self.owner.post("/api/payments/close", json={
            "event_id": str(uuid.uuid4()), "order_no": order_no,
            "amount": self.totals(order_no)["total_cents"] / 100,
            "method": server.MANUAL_CASH}).status_code, 200)
        self.move(order_no, "2", expect=409)

    def test_the_log_says_which_table_it_came_from(self):
        order_no = self.order(qty=1, table="1")
        self.move(order_no, "3", client=self.signed_in(3))
        rows = self.activity("move_table")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "เสิร์ฟ")
        self.assertIn("โต๊ะ 1", rows[0][2])
        self.assertIn("โต๊ะ 3", rows[0][2])


class MergingTwoBillsIntoOne(TillCase):
    def merge(self, order_no, into, *, client=None, expect=200):
        answer = (client or self.owner).post(f"/api/orders/{order_no}/merge",
                                             json={"branch_id": 1, "into_order_no": into})
        self.assertEqual(answer.status_code, expect, answer.text)
        return answer

    def test_the_totals_add_up_onto_the_bill_that_stays(self):
        first = self.order(qty=1, table="1")
        second = self.order(qty=2, table="2")
        money = self.totals(first)["total_cents"] + self.totals(second)["total_cents"]
        self.merge(second, first)
        self.assertEqual(self.totals(first)["total_cents"], money)

    def test_the_food_moves_too(self):
        first = self.order(qty=1, table="1")
        second = self.order(qty=2, table="2")
        self.merge(second, first)
        self.assertEqual([row[1] for row in self.lines(first)], [1, 2])
        self.assertEqual(self.lines(second), [])

    def test_the_bill_that_was_merged_away_is_worth_nothing(self):
        """ปล่อยยอดไว้เท่ากับให้รายงานนับเงินก้อนเดียวสองครั้ง"""
        first = self.order(qty=1)
        second = self.order(qty=2)
        self.merge(second, first)
        gone = self.totals(second)
        self.assertEqual(gone["status"], "merged")
        self.assertEqual(gone["total_cents"], 0)
        self.assertEqual(gone["subtotal"], 0)

    def test_it_drops_out_of_the_bills_waiting_to_be_paid(self):
        first = self.order(qty=1)
        second = self.order(qty=2)
        self.merge(second, first)
        numbers = [order["order_no"] for order
                   in self.owner.get("/api/orders?branch_id=1").json()["orders"]]
        self.assertEqual(numbers, [first])

    def test_one_payment_closes_the_lot(self):
        first = self.order(qty=1)
        second = self.order(qty=2)
        money = self.totals(first)["total_cents"] + self.totals(second)["total_cents"]
        self.merge(second, first)
        answer = self.owner.post("/api/payments/close", json={
            "event_id": str(uuid.uuid4()), "order_no": first,
            "amount": money / 100, "method": server.MANUAL_CASH})
        self.assertEqual(answer.status_code, 200, answer.text)
        taken = self.conn.execute("SELECT COUNT(*),SUM(net_amount) FROM pos_orders"
                                  " WHERE status='paid'").fetchone()
        self.assertEqual(taken[0], 1)
        self.assertEqual(round(taken[1] * 100), money)

    def test_food_still_being_cooked_does_not_disappear_from_the_kitchen(self):
        """ใบหนึ่งกดว่าเสร็จแล้ว อีกใบยังทำอยู่ — รวมแล้วครัวต้องยังเห็นว่าค้าง"""
        first = self.order(qty=1)
        second = self.order(qty=2)
        with self.conn:
            self.conn.execute("UPDATE kds_station_tickets SET status='ready' WHERE order_no=?",
                              (first,))
        self.merge(second, first)
        tickets = self.conn.execute("SELECT order_no,status FROM kds_station_tickets").fetchall()
        self.assertEqual(tickets, [(first, "queued")])

    def test_merging_a_bill_into_itself(self):
        order_no = self.order(qty=1)
        self.merge(order_no, order_no, expect=400)

    def test_merging_into_a_bill_that_is_already_paid(self):
        first = self.order(qty=1)
        second = self.order(qty=1)
        self.assertEqual(self.owner.post("/api/payments/close", json={
            "event_id": str(uuid.uuid4()), "order_no": first,
            "amount": self.totals(first)["total_cents"] / 100,
            "method": server.MANUAL_CASH}).status_code, 200)
        self.merge(second, first, expect=409)

    def test_a_waiter_cannot_merge_bills(self):
        first = self.order(qty=1)
        second = self.order(qty=1)
        self.merge(second, first, client=self.signed_in(3), expect=403)

    def test_the_log_says_which_bill_went_where(self):
        first = self.order(qty=1, table="1")
        second = self.order(qty=2, table="2")
        amount = self.totals(second)["total_cents"]
        self.merge(second, first, client=self.signed_in(2))
        rows = self.activity("merge_bill")
        self.assertEqual(len(rows), 1)
        self.assertIn(second, rows[0][1])
        self.assertIn(first, rows[0][1])
        self.assertEqual(rows[0][3], amount)


class TheScreenThatDoesThis(TillCase):
    def test_the_bill_list_says_which_line_is_which(self):
        """ชื่อเมนูซ้ำกันในบิลเดียวได้ หน้าจอจึงต้องชี้แถวได้ ไม่ใช่ชี้ชื่อ"""
        order_no = self.order(items=[
            {"id": "M1", "name": "ข้าวผัด", "price": 100, "qty": 1},
            {"id": "M1", "name": "ข้าวผัด", "price": 100, "qty": 2}])
        ids = self.line_ids(order_no)
        self.assertEqual(len(ids), 2)
        self.assertEqual(len(set(ids)), 2)

    def test_the_board_shows_free_tables_and_open_bills(self):
        order_no = self.order(qty=1, table="2")
        answer = self.owner.get("/api/tables/board?branch_id=1")
        self.assertEqual(answer.status_code, 200, answer.text)
        board = answer.json()
        self.assertEqual([table["table_no"] for table in board["tables"]], ["1", "2", "3"])
        self.assertEqual(board["open_bills"]["2"][0]["order_no"], order_no)
        self.assertNotIn("1", board["open_bills"])

    def test_the_board_is_not_for_guests(self):
        answer = TestClient(server.app).get("/api/tables/board?branch_id=1")
        self.assertEqual(answer.status_code, 401)

    def test_the_screen_is_served(self):
        answer = TestClient(server.app).get("/split-bill.js")
        self.assertEqual(answer.status_code, 200, answer.text)
        self.assertIn("javascript", answer.headers["content-type"])


if __name__ == "__main__":
    unittest.main()
