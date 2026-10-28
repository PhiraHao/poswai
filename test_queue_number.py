"""เลขคิวที่ลูกค้าถือไปนั่งรอ และพนักงานกดเรียกบนเพจเจอร์

คาเฟ่สั่งที่เคาน์เตอร์แล้วลูกค้าไปนั่งมุมไหนก็ได้ เลขโต๊ะจึงบอกอะไรไม่ได้
สิ่งที่ใช้เรียกคือเลขคิว — ต้องไล่ 1, 2, 3 ไม่ซ้ำ ไม่ข้าม และต้องส่งถึงทั้ง
หน้าลูกค้าและจอครัว ไม่งั้นเรียกคนละเลขกันคนละทาง
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import line_pos_server as server


class QueueNumberTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        server.DB_PATH = Path(self.directory.name) / "queue.db"
        server.PREVIEW_ONLY = False
        server.BOOTSTRAP_MANAGER_PIN = ""
        server.TABLE_QR_SECRET = "q" * 48
        server.init_db()
        conn = sqlite3.connect(server.DB_PATH)
        with conn:
            conn.execute("INSERT INTO branches(id,name) VALUES(1,'Test')")
            conn.execute("INSERT INTO staffs(id,branch_id,name,role,pin_code_hash) VALUES(1,1,'Owner','owner',?)",
                         (server.hash_pin("secure-pin-owner"),))
        conn.close()

    def _order(self, client, token, order_no):
        return client.post("/api/orders", headers={"X-Table-Token": token}, json={
            "event_id": order_no, "order_no": order_no, "branch_id": 1, "table_no": "T1",
            "total_amount": 35, "items": [{"id": "TEA", "name": "Tea", "price": 35,
                                           "qty": 1, "course_mode": "FIRE", "bom": []}]})

    def test_each_bill_takes_the_next_number_and_both_screens_see_it(self):
        with TestClient(server.app) as owner:
            self.assertEqual(owner.post("/api/auth/login", json={"staff_id": 1, "pin": "secure-pin-owner"}).status_code, 200)
            self.assertEqual(owner.put("/api/menu/TEA", json={"branch_id": 1, "name": "Tea", "price": 35,
                                                              "bom": [], "station": "บาร์น้ำ"}).status_code, 200)
            token = owner.post("/api/tables/token", json={"branch_id": 1, "table_no": "T1"}).json()["token"]

            with TestClient(server.app) as guest:
                for order_no in ("Q-1", "Q-2", "Q-3"):
                    r = self._order(guest, token, order_no); self.assertEqual(r.status_code, 200, r.text)

            orders = {o["order_no"]: o["queue_no"] for o in owner.get("/api/orders?branch_id=1").json()["orders"]}
            self.assertEqual(orders, {"Q-1": 1, "Q-2": 2, "Q-3": 3})

            # จอครัวต้องเห็นเลขเดียวกัน ไม่งั้นคนชงกดเพจเจอร์ผิดใบ
            kds = {t["order_no"]: t["queue_no"] for t in owner.get("/api/kds?branch_id=1").json()["tickets"]}
            self.assertEqual(kds, {"Q-1": 1, "Q-2": 2, "Q-3": 3})

    def test_a_new_day_starts_at_one_again(self):
        with TestClient(server.app) as owner:
            self.assertEqual(owner.post("/api/auth/login", json={"staff_id": 1, "pin": "secure-pin-owner"}).status_code, 200)
            self.assertEqual(owner.put("/api/menu/TEA", json={"branch_id": 1, "name": "Tea", "price": 35,
                                                              "bom": [], "station": "บาร์น้ำ"}).status_code, 200)
            token = owner.post("/api/tables/token", json={"branch_id": 1, "table_no": "T1"}).json()["token"]
            with TestClient(server.app) as guest:
                self.assertEqual(self._order(guest, token, "Y-1").status_code, 200)
            # บิลของเมื่อวาน ไม่ควรดันเลขของวันนี้ให้เริ่มที่สอง
            conn = sqlite3.connect(server.DB_PATH)
            with conn:
                conn.execute("UPDATE order_events SET created_at=datetime('now','-1 day') WHERE order_no='Y-1'")
            conn.close()
            with TestClient(server.app) as guest:
                self.assertEqual(self._order(guest, token, "T-1").status_code, 200)
            today = {o["order_no"]: o["queue_no"] for o in owner.get("/api/orders?branch_id=1").json()["orders"]}
            self.assertEqual(today["T-1"], 1)


    def test_a_member_who_linked_line_is_told_when_the_order_is_ready(self):
        with TestClient(server.app) as owner:
            self.assertEqual(owner.post("/api/auth/login", json={"staff_id": 1, "pin": "secure-pin-owner"}).status_code, 200)
            self.assertEqual(owner.put("/api/menu/TEA", json={"branch_id": 1, "name": "Tea", "price": 35,
                                                              "bom": [], "station": "บาร์น้ำ"}).status_code, 200)
            token = owner.post("/api/tables/token", json={"branch_id": 1, "table_no": "T1"}).json()["token"]
            with TestClient(server.app) as guest:
                self.assertEqual(self._order(guest, token, "M-1").status_code, 200)

            # สมาชิกที่ผูกไลน์ไว้แล้ว และบิลนี้เป็นของเขา
            conn = sqlite3.connect(server.DB_PATH)
            with conn:
                conn.execute("INSERT INTO crm_customers(id,branch_id,display_name,line_user_id)"
                             " VALUES(7,1,'คุณเอ','U-line-7')")
                conn.execute("UPDATE order_events SET customer_id=7 WHERE order_no='M-1'")
            conn.close()

            ready = owner.post("/api/kds/M-1/%E0%B8%9A%E0%B8%B2%E0%B8%A3%E0%B9%8C%E0%B8%99%E0%B9%89%E0%B8%B3/ready")
            self.assertEqual(ready.status_code, 200, ready.text)

            conn = sqlite3.connect(server.DB_PATH)
            queued = conn.execute("SELECT recipient,message_json FROM line_notification_outbox"
                                  " WHERE event_key='ready:M-1'").fetchall()
            conn.close()
            self.assertEqual(len(queued), 1, "สมาชิกต้องได้ข้อความเดียว ไม่ใช่ศูนย์และไม่ใช่สองรอบ")
            self.assertEqual(queued[0][0], "U-line-7")
            self.assertIn("คิวที่ 1", queued[0][1])

    def test_a_walk_in_with_no_member_card_is_not_chased_for_a_line_id(self):
        with TestClient(server.app) as owner:
            self.assertEqual(owner.post("/api/auth/login", json={"staff_id": 1, "pin": "secure-pin-owner"}).status_code, 200)
            self.assertEqual(owner.put("/api/menu/TEA", json={"branch_id": 1, "name": "Tea", "price": 35,
                                                              "bom": [], "station": "บาร์น้ำ"}).status_code, 200)
            token = owner.post("/api/tables/token", json={"branch_id": 1, "table_no": "T1"}).json()["token"]
            with TestClient(server.app) as guest:
                self.assertEqual(self._order(guest, token, "W-1").status_code, 200)
            ready = owner.post("/api/kds/W-1/%E0%B8%9A%E0%B8%B2%E0%B8%A3%E0%B9%8C%E0%B8%99%E0%B9%89%E0%B8%B3/ready")
            self.assertEqual(ready.status_code, 200, ready.text)
            conn = sqlite3.connect(server.DB_PATH)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM line_notification_outbox").fetchone()[0], 0)
            conn.close()


if __name__ == "__main__":
    unittest.main()
