"""ออเดอร์เก่าและบิลที่จ่ายก่อนเสิร์ฟ ต้องยังกดว่าครัวเสร็จแล้วได้อยู่

เจ้าของร้านเจอว่าออเดอร์ค้างในหน้า "กำลังทำ" แล้วกดปุ่มเท่าไรก็ไม่ขยับ
สองสาเหตุที่ไล่เจอ และเทสต์ชุดนี้กันไม่ให้กลับมา

1. `/api/kds` ตัดตั๋วที่เสร็จแล้วและเก่าเกินหนึ่งวันทิ้ง ซึ่งถูกสำหรับจอครัว
   แต่หน้าออเดอร์ใช้รายการเดียวกันเป็นตัวบอกสถานะ พอตั๋วหายทั้งที่บิลยังเปิด
   หน้าจอเลยไม่รู้ว่าครัวทำอะไรไปแล้ว และย้อนกลับไปเป็น "กำลังทำ" ตลอดกาล
2. ปิดบิลแล้วไม่ได้แตะตั๋วครัว ร้านที่เก็บเงินก่อนเสิร์ฟจึงมีบิลที่จ่ายแล้ว
   แต่ครัวยังต้องทำต่อ ถ้าบิลหายจากหน้าออเดอร์ทันทีที่จ่าย จะไม่เหลือใคร
   กดว่าอาหารเสร็จได้อีกเลย
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote

from fastapi.testclient import TestClient

import line_pos_server as server

STATION = "ครัวร้อน"


class StaleOrderKitchenTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        server.DB_PATH = Path(self._dir.name) / "stale.db"
        server.PREVIEW_ONLY = False
        server.BOOTSTRAP_MANAGER_PIN = ""
        server.TABLE_QR_SECRET = "s" * 48
        server.init_db()
        conn = sqlite3.connect(server.DB_PATH)
        with conn:
            conn.execute("INSERT INTO branches(id,name) VALUES(1,'Test')")
            conn.execute("INSERT INTO staffs(id,branch_id,name,role,pin_code_hash) VALUES(1,1,'owner','owner',?)",
                         (server.hash_pin("secure-pin-owner"),))
        conn.close()
        self.ready_path = f"/api/kds/{{}}/{quote(STATION)}/ready"

    def _sign_in(self, client):
        self.assertEqual(client.post("/api/auth/login",
                                     json={"staff_id": 1, "pin": "secure-pin-owner"}).status_code, 200)
        self.assertEqual(client.put("/api/menu/PAD", json={"branch_id": 1, "name": "ผัด", "price": 50,
                                                           "bom": [], "station": STATION}).status_code, 200)

    def _order(self, client, order_no, table):
        token = client.post("/api/tables/token", json={"branch_id": 1, "table_no": table}).json()["token"]
        response = client.post("/api/orders", headers={"X-Table-Token": token}, json={
            "event_id": "ev-" + order_no, "order_no": order_no, "branch_id": 1, "table_no": table,
            "total_amount": 50, "items": [{"id": "PAD", "name": "ผัด", "price": 50, "qty": 1,
                                           "course_mode": "FIRE", "bom": []}]})
        self.assertEqual(response.status_code, 200, response.text)

    def _age_days(self, order_no, days):
        conn = sqlite3.connect(server.DB_PATH)
        with conn:
            conn.execute("UPDATE kds_station_tickets SET created_at=datetime('now',?) WHERE order_no=?",
                         (f"-{days} day", order_no))
        conn.close()

    @staticmethod
    def _tickets(client, order_no):
        return [t["status"] for t in client.get("/api/kds?branch_id=1").json()["tickets"]
                if t["order_no"] == order_no]

    def test_open_bill_keeps_its_tickets_however_old(self):
        """บิลที่ยังเปิดอยู่ ต่อให้ตั๋วเก่าและเสร็จแล้ว ก็ต้องยังเห็นว่าเสร็จ"""
        with TestClient(server.app) as client:
            self._sign_in(client)
            self._order(client, "OLD-1", "T1")
            self._age_days("OLD-1", 2)
            self.assertEqual(self._tickets(client, "OLD-1"), ["queued"])
            self.assertEqual(client.post(self.ready_path.format("OLD-1")).json()["status"], "ready")
            # เดิมตรงนี้ได้ [] ทำให้หน้าออเดอร์อ่านว่า "ยังไม่เสร็จ" แล้วค้างถาวร
            self.assertEqual(self._tickets(client, "OLD-1"), ["ready"],
                             "ตั๋วของบิลที่ยังเปิดอยู่หายไปจากรายการ หน้าออเดอร์จะค้าง")

    def test_closed_bill_old_tickets_still_age_off_the_kitchen_screen(self):
        """จอครัวต้องไม่รกไปด้วยตั๋วของบิลที่ปิดไปแล้วเมื่อวาน"""
        with TestClient(server.app) as client:
            self._sign_in(client)
            self._order(client, "DONE-1", "T2")
            self.assertEqual(client.post(self.ready_path.format("DONE-1")).json()["status"], "ready")
            self.assertEqual(client.post("/api/payments/close", json={
                "event_id": "pay-done", "order_no": "DONE-1", "amount": 50,
                "method": "เงินสด (Cash)"}).status_code, 200)
            self._age_days("DONE-1", 2)
            self.assertEqual(self._tickets(client, "DONE-1"), [])

    def test_bill_paid_before_the_food_can_still_be_marked_ready(self):
        """เก็บเงินก่อนเสิร์ฟ: บิลต้องยังอยู่ให้ครัวกดเสร็จย้อนหลังได้"""
        with TestClient(server.app) as client:
            self._sign_in(client)
            self._order(client, "PREPAID-1", "T3")
            self.assertEqual(client.post("/api/payments/close", json={
                "event_id": "pay-pre", "order_no": "PREPAID-1", "amount": 50,
                "method": "เงินสด (Cash)"}).status_code, 200)

            # จ่ายเงินแล้วไม่ไปยุ่งกับครัว ร้านที่เก็บเงินก่อนยังต้องทำอาหารต่อ
            self.assertEqual(self._tickets(client, "PREPAID-1"), ["queued"])

            plain = client.get("/api/orders?branch_id=1").json()["orders"]
            self.assertEqual([o for o in plain if o["order_no"] == "PREPAID-1"], [],
                             "บิลที่จ่ายแล้วต้องไม่โผล่ในรายการปกติ ไม่งั้นโต๊ะจะขึ้นว่ายังค้างจ่าย")

            pending = client.get("/api/orders?branch_id=1&kitchen_pending=true").json()["orders"]
            waiting = [o for o in pending if o["order_no"] == "PREPAID-1"]
            self.assertEqual(len(waiting), 1, "บิลที่จ่ายแล้วแต่ครัวยังไม่เสร็จต้องเรียกกลับมาได้")
            self.assertTrue(waiting[0]["paid"], "ต้องติดธงว่าจ่ายแล้ว หน้าจอจะได้ไม่เก็บเงินซ้ำ")

            # แล้วต้องกดว่าเสร็จย้อนหลังได้จริง
            self.assertEqual(client.post(self.ready_path.format("PREPAID-1")).json()["status"], "ready")
            after = client.get("/api/orders?branch_id=1&kitchen_pending=true").json()["orders"]
            self.assertEqual([o for o in after if o["order_no"] == "PREPAID-1"], [],
                             "ครัวเสร็จแล้วบิลที่จ่ายแล้วต้องหลุดออกจากหน้าออเดอร์")

    def test_guest_at_the_table_never_sees_a_paid_bill(self):
        """ลูกค้าที่โต๊ะต้องไม่เห็นบิลที่จ่ายไปแล้ว ถึงจะใส่พารามิเตอร์มาเองก็ตาม"""
        with TestClient(server.app) as client:
            self._sign_in(client)
            self._order(client, "PREPAID-2", "T4")
            self.assertEqual(client.post("/api/payments/close", json={
                "event_id": "pay-guest", "order_no": "PREPAID-2", "amount": 50,
                "method": "เงินสด (Cash)"}).status_code, 200)
            token = client.post("/api/tables/token", json={"branch_id": 1, "table_no": "T4"}).json()["token"]

        with TestClient(server.app) as guest:
            seen = guest.get("/api/orders?branch_id=1&table_no=T4&kitchen_pending=true",
                             headers={"X-Table-Token": token}).json()["orders"]
            self.assertEqual([o for o in seen if o["order_no"] == "PREPAID-2"], [])


if __name__ == "__main__":
    unittest.main()
