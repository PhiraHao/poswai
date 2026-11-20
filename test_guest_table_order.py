"""A guest ordering from the table QR has to reach a person, not just the kitchen screen.

Before this, such an order created kitchen tickets and nothing else: the table
quietly turned to "กำลังทาน" and no one at the front was told. A small shop with
nobody watching the kitchen screen found out when the customer came looking.
"""

import hashlib
import hmac
import base64
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import line_pos_server as server

QR_SECRET = "t" * 40


class GuestTableOrderTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(temp.cleanup)
        self.db = Path(temp.name) / "guest.db"
        for item in (patch.object(server, "DB_PATH", self.db),
                     patch.object(server, "PREVIEW_ONLY", False),
                     patch.object(server, "BOOTSTRAP_MANAGER_PIN", ""),
                     patch.object(server, "TABLE_QR_SECRET", QR_SECRET),
                     patch.object(server, "LINE_CHANNEL_ACCESS_TOKEN", ""),
                     patch.object(server, "_prepared_databases", set())):
            item.start()
            self.addCleanup(item.stop)
        server.init_db()
        with sqlite3.connect(self.db) as conn:
            conn.execute("INSERT INTO branches(id,name) VALUES(1,'Main')")
            conn.execute("INSERT INTO staffs(id,branch_id,name,role,pin_code_hash,line_user_id) "
                         "VALUES(1,1,'เจ้าของ','owner',?,'U-owner')", (server.hash_pin("secure-owner-pin"),))
            conn.execute("INSERT INTO staffs(id,branch_id,name,role,pin_code_hash,line_user_id) "
                         "VALUES(2,1,'เสิร์ฟ','service',?,'U-waiter')", (server.hash_pin("secure-waiter-pin"),))
            server.upsert_menu_item(conn, 1, "RICE", "ข้าวผัด", 60, [])
        self.client = TestClient(server.app)

    def _table_token(self, table_no="A1", branch_id=1):
        """The signed token the QR at the table carries."""
        payload = json.dumps({"b": branch_id, "t": table_no, "e": int(time.time()) + 3600,
                              "s": server.CURRENT_SHOP.get()}, separators=(",", ":")).encode()
        encoded = base64.urlsafe_b64encode(payload).decode().rstrip("=")
        signature = hmac.new(QR_SECRET.encode(), payload, hashlib.sha256).hexdigest()
        return f"{encoded}.{signature}"

    def _order(self, order_no, *, headers=None, table_no="A1"):
        return self.client.post("/api/orders", headers=headers or {}, json={
            "event_id": "evt-" + order_no, "order_no": order_no, "branch_id": 1,
            "table_no": table_no, "total_amount": 60,
            "items": [{"id": "RICE", "name": "ข้าวผัด", "price": 60, "qty": 1}]})

    def _login_owner(self):
        self.assertEqual(self.client.post("/api/auth/login",
                                          json={"staff_id": 1, "pin": "secure-owner-pin"}).status_code, 200)

    def test_a_guest_order_pings_line_and_is_marked_as_the_guests_own(self):
        placed = self._order("G-001", headers={"X-Table-Token": self._table_token()})
        self.assertEqual(placed.status_code, 200, placed.text)
        self.assertEqual(placed.json()["ordered_by"], "guest")
        with sqlite3.connect(self.db) as conn:
            rows = conn.execute("SELECT recipient FROM line_notification_outbox "
                                "WHERE event_key='guest-order:G-001' ORDER BY recipient").fetchall()
            text = conn.execute("SELECT message_json FROM line_notification_outbox "
                                "WHERE event_key='guest-order:G-001' LIMIT 1").fetchone()[0]
        # เจ้าของได้รับ เด็กเสิร์ฟไม่ได้รับ (ตำแหน่งเดียวกับแจ้งเตือนออเดอร์เดลิเวอรี)
        self.assertEqual([row[0] for row in rows], ["U-owner"])
        for fragment in ("A1", "G-001", "ข้าวผัด", "60.00"):
            self.assertIn(fragment, text)

    def test_an_order_rung_up_by_staff_does_not_ping_anyone(self):
        """คนที่กดเองรู้อยู่แล้ว เตือนซ้ำคือเสียงรบกวนที่ทำให้คนเลิกสนใจป้าย"""
        self._login_owner()
        placed = self._order("S-001")
        self.assertEqual(placed.status_code, 200, placed.text)
        self.assertEqual(placed.json()["ordered_by"], "staff")
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM line_notification_outbox").fetchone()[0], 0)

    def test_the_cashier_sees_guest_orders_until_the_bill_is_closed(self):
        self._order("G-002", headers={"X-Table-Token": self._table_token()})
        self._order("G-003", headers={"X-Table-Token": self._table_token("A2")}, table_no="A2")
        self._login_owner()
        self._order("S-002")      # ของพนักงานเองต้องไม่ไปโผล่ในรายการนี้

        waiting = self.client.get("/api/orders/guest-waiting").json()["orders"]
        self.assertEqual({row["order_no"] for row in waiting}, {"G-002", "G-003"})
        self.assertEqual({row["table_no"] for row in waiting}, {"A1", "A2"})

        # ปิดบิลแล้วหายจากรายการเอง ไม่ต้องกดรับทราบให้เป็นภาระอีกขั้น
        with sqlite3.connect(self.db) as conn:
            conn.execute("INSERT INTO payment_events(event_id,order_no,amount,method) "
                         "VALUES('pay-1','G-002',60,'cash')")
        left = self.client.get("/api/orders/guest-waiting").json()["orders"]
        self.assertEqual([row["order_no"] for row in left], ["G-003"])

    def test_only_the_front_of_house_may_read_the_waiting_list(self):
        signed_out = TestClient(server.app)
        self.assertEqual(signed_out.get("/api/orders/guest-waiting").status_code, 401)
        self.assertEqual(self.client.post("/api/auth/login",
                                          json={"staff_id": 2, "pin": "secure-waiter-pin"}).status_code, 200)
        self.assertEqual(self.client.get("/api/orders/guest-waiting").status_code, 403)

    def test_a_forged_table_token_orders_nothing(self):
        bad = self._order("X-001", headers={"X-Table-Token": "forged.signature"})
        self.assertEqual(bad.status_code, 403)
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM order_events").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM line_notification_outbox").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
