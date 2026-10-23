"""Integration tests for signed Songwai intake, online pickup and CRM consent."""

import hashlib
import hmac
import json
import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path
import unittest.mock
from unittest.mock import patch

from fastapi.testclient import TestClient

import line_pos_server as server


class CommerceTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.db = Path(temp.name) / "commerce.db"
        patches = [
            patch.object(server, "DB_PATH", self.db),
            patch.object(server, "PREVIEW_ONLY", False),
            patch.object(server, "BOOTSTRAP_MANAGER_PIN", ""),
            patch.object(server, "LINE_LOGIN_CHANNEL_ID", "line-channel"),
            patch.object(server, "SONGWAI_WEBHOOK_SECRET", "s" * 48),
            patch.object(server, "SONGWAI_RESTAURANT_ID", 37),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        server.init_db()
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("INSERT INTO branches(id,name) VALUES(1,'Main')")
            conn.execute("INSERT INTO staffs(id,branch_id,name,role,pin_code_hash) VALUES(1,1,'Manager','manager',?)",
                         (server.hash_pin("secure-manager-pin"),))
            server.upsert_menu_item(conn, 1, "beef", "Beef", 50, [{"ingId": "meat", "qty": 2}])
            conn.execute("INSERT INTO inventory(branch_id,ingredient_id,stock) VALUES(1,'meat',10)")
        self.client = TestClient(server.app)

    def _songwai(self, payload, *, secret="s" * 48):
        body = json.dumps(payload, separators=(",", ":")).encode()
        stamp = str(int(time.time()))
        sig = hmac.new(secret.encode(), stamp.encode() + b"." + body, hashlib.sha256).hexdigest()
        return self.client.post("/api/integrations/songwai/orders", content=body,
                                headers={"X-Songwai-Timestamp": stamp,
                                         "X-Songwai-Signature": "sha256=" + sig,
                                         "Content-Type": "application/json"})

    def _login(self):
        response = self.client.post("/api/auth/login", json={"staff_id": 1, "pin": "secure-manager-pin"})
        self.assertEqual(response.status_code, 200)

    def test_signed_songwai_order_is_idempotent_and_uses_pos_stock(self):
        payload = {"order_id": 991, "restaurant_id": 37, "user_id": 55,
                   "delivery_mode": "rider", "payment_status": "paid",
                   "items": [{"menu_id": 480, "qty": 2}]}
        self.assertEqual(self._songwai(payload).status_code, 409)
        self.assertEqual(self._songwai(payload, secret="wrong" * 10).status_code, 401)
        self._login()
        mapped = self.client.put("/api/integrations/songwai/menu-map", json={
            "branch_id": 1, "restaurant_id": 37, "songwai_menu_id": 480, "pos_item_id": "beef"})
        self.assertEqual(mapped.status_code, 200)
        first = self._songwai(payload)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["fulfillment"], "rider_pickup")
        self.assertEqual(first.json()["total_amount"], 100)
        second = self._songwai(payload)
        self.assertEqual(second.json()["order_no"], first.json()["order_no"])
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute("SELECT stock FROM inventory WHERE ingredient_id='meat'").fetchone()[0], 6)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM kds_station_tickets").fetchone()[0], 1)
        order_no = first.json()["order_no"]
        for status in ("accepted", "preparing", "ready", "handed_off"):
            response = self.client.patch(f"/api/online/orders/{order_no}", json={"status": status})
            self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.patch(f"/api/online/orders/{order_no}", json={"status": "handed_off"}).status_code, 200)
        customers = self.client.get("/api/crm/customers").json()["customers"]
        self.assertEqual(customers[0]["completed_orders"], 1)
        self.assertEqual(customers[0]["lifetime_amount"], 100)

    def test_songwai_order_pushes_line_alert_once_per_recipient(self):
        """Thai shops watch LINE, not the POS screen - a delivery order must ping them."""
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("UPDATE staffs SET line_user_id='U-manager' WHERE id=1")
            conn.execute("INSERT INTO staffs(id,branch_id,name,role,pin_code_hash,line_user_id) "
                         "VALUES(2,1,'Cook','kitchen',?,'U-cook')", (server.hash_pin("secure-cook-pin"),))
            conn.execute("INSERT INTO staffs(id,branch_id,name,role,pin_code_hash,line_user_id) "
                         "VALUES(3,1,'Waiter','service',?,'U-waiter')", (server.hash_pin("secure-waiter-pin"),))
        self._login()
        self.client.put("/api/integrations/songwai/menu-map", json={
            "branch_id": 1, "restaurant_id": 37, "songwai_menu_id": 480, "pos_item_id": "beef"})
        payload = {"order_id": 993, "restaurant_id": 37, "delivery_mode": "rider",
                   "customer_name": "Somchai", "contact_phone": "0812345678",
                   "items": [{"menu_id": 480, "qty": 2}]}
        with patch.object(server, "LINE_CHANNEL_ACCESS_TOKEN", ""):
            order = self._songwai(payload)
        self.assertEqual(order.status_code, 200, order.text)
        order_no = order.json()["order_no"]
        with closing(sqlite3.connect(self.db)) as conn:
            rows = conn.execute("SELECT recipient,message_json,status FROM line_notification_outbox "
                                "WHERE event_key=? ORDER BY recipient", (f"online-order:{order_no}",)).fetchall()
        self.assertEqual([row[0] for row in rows], ["U-cook", "U-manager"])  # service staff stays out of it
        text = json.loads(rows[0][1])["text"]
        for fragment in (order_no, "Beef", "Somchai", "0812345678", "100.00"):
            self.assertIn(fragment, text)
        self.assertTrue(all(row[2] == "pending" for row in rows))

        # ยิงซ้ำด้วยใบเดิม ต้องไม่เกิดข้อความใหม่ (PRIMARY KEY กันไว้) และต้องพยายามส่งเมื่อมีโทเคน
        with patch.object(server, "LINE_CHANNEL_ACCESS_TOKEN", "token"), \
             patch.object(server, "flush_line_notifications") as flush:
            self.assertEqual(self._songwai(payload).json()["order_no"], order_no)
            flush.assert_not_called()   # ใบซ้ำคืนของเดิม ไม่ต้องยิงอะไรอีก
            fresh = dict(payload, order_id=994)
            self.assertEqual(self._songwai(fresh).status_code, 200)
            self.assertEqual(flush.call_count, 1)
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM line_notification_outbox "
                                          "WHERE event_key=?", (f"online-order:{order_no}",)).fetchone()[0], 2)

    def test_what_the_customer_chose_reaches_the_kitchen_ticket(self):
        """ครัวได้แต่ชื่อจาน = ทําผิดตามที่ลูกค้าสั่ง เป็นของเสียจริง ไม่ใช่แค่ข้อมูลหาย"""
        self._login()
        self.client.put("/api/integrations/songwai/menu-map", json={
            "branch_id": 1, "restaurant_id": 37, "songwai_menu_id": 480, "pos_item_id": "beef"})
        order = self._songwai({"order_id": 995, "restaurant_id": 37, "delivery_mode": "rider",
                               "items": [{"menu_id": 480, "qty": 1,
                                          "options": "เผ็ดมาก, ไข่ดาว"}]})
        self.assertEqual(order.status_code, 200, order.text)
        with closing(sqlite3.connect(self.db)) as conn:
            options = conn.execute("SELECT options FROM order_items WHERE order_no=?",
                                   (order.json()["order_no"],)).fetchone()[0]
        self.assertEqual(options, "เผ็ดมาก, ไข่ดาว")
        # ตั๋วครัวอ่านค่านี้ได้จริง ไม่ใช่แค่เก็บไว้ในฐานข้อมูล
        ticket = next(t for t in self.client.get("/api/kds").json()["tickets"]
                      if t["order_no"] == order.json()["order_no"])
        self.assertEqual(ticket["items"][0]["options"], "เผ็ดมาก, ไข่ดาว")

        # ไม่ส่งตัวเลือกมา = ช่องว่าง ไม่ใช่คำว่า None ไปโผล่บนตั๋ว
        plain = self._songwai({"order_id": 996, "restaurant_id": 37, "delivery_mode": "rider",
                               "items": [{"menu_id": 480, "qty": 1}]})
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute("SELECT options FROM order_items WHERE order_no=?",
                                          (plain.json()["order_no"],)).fetchone()[0], "")

    def test_cancelled_order_restores_bom_once(self):
        self._login()
        self.client.put("/api/integrations/songwai/menu-map", json={
            "branch_id": 1, "restaurant_id": 37, "songwai_menu_id": 480, "pos_item_id": "beef"})
        payload = {"order_id": 992, "restaurant_id": 37, "delivery_mode": "pickup",
                   "items": [{"menu_id": 480, "qty": 2}]}
        order = self._songwai(payload).json()
        order_no = order["order_no"]
        self.assertEqual(self.client.patch(f"/api/online/orders/{order_no}",
                         json={"status": "cancelled"}).status_code, 200)
        self.assertEqual(self.client.patch(f"/api/online/orders/{order_no}",
                         json={"status": "cancelled"}).status_code, 200)
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute("SELECT stock FROM inventory WHERE ingredient_id='meat'").fetchone()[0], 10)

    def test_songwai_draft_import_does_not_activate_or_overwrite_recipe(self):
        self._login()
        payload = [{"id": 480, "name": "เนื้อวัวผัดขึ้นฉ่าย", "price": 50, "restaurant_id": 37}]
        with patch.object(server.httpx, "get") as get:
            get.return_value.status_code = 200
            get.return_value.json.return_value = payload
            first = self.client.post("/api/integrations/songwai/import-drafts")
            second = self.client.post("/api/integrations/songwai/import-drafts")
        self.assertEqual(first.json()["imported"], 1)
        self.assertEqual(second.json()["imported"], 0)
        items = self.client.get("/api/menu?include_inactive=true").json()["items"]
        draft = next(item for item in items if item["id"] == "songwai-480")
        self.assertFalse(draft["active"])
        self.assertEqual(draft["bom"], [])
        self.assertEqual(self.client.put("/api/menu/songwai-480", json={
            "name": draft["name"], "price": 50, "bom": [], "active": True}).status_code, 409)
        self.assertEqual(self.client.get("/api/menu").json()["items"][0]["id"], "beef")

    def test_imported_drafts_carry_the_songwai_photo_over(self):
        """เมนูไม่มีรูปทำให้จอครัวอ่านยาก ทั้งที่รูปชุดเดียวกันมีอยู่แล้วในส่งไว"""
        self._login()
        png = (b"\x89PNG\r\n\x1a\n" + b"0" * 64, "image/png")
        payload = [
            {"id": 480, "name": "เนื้อวัวผัดขึ้นฉ่าย", "price": 50, "restaurant_id": 37,
             "image_url": "/uploads/media_480.png"},
            {"id": 481, "name": "เนื้อวัวผัดผักกาดดอง", "price": 50, "restaurant_id": 37,
             "image_url": None},                      # ส่งไวเองก็ไม่มีรูปทุกจาน
            {"id": 482, "name": "เนื้อวัวผัดหน่อไม้", "price": 50, "restaurant_id": 37,
             "image_url": "../../etc/passwd"},        # ที่อยู่มาจาก API ภายนอก เชื่อไม่ได้
        ]

        def fake_get(url, *args, **kwargs):
            response = unittest.mock.Mock()
            response.status_code = 200
            response.raise_for_status.return_value = None
            if url.endswith("/menus"):
                response.json.return_value = payload
            else:
                response.content, response.headers = png[0], {"content-type": png[1]}
            return response

        with patch.object(server.httpx, "get", side_effect=fake_get) as get:
            result = self.client.post("/api/integrations/songwai/import-drafts").json()
            # ดึงรูปจากโดเมนส่งไวเท่านั้น และไม่แตะที่อยู่ที่ไต่ออกนอกโฟลเดอร์
            fetched = [call.args[0] for call in get.call_args_list if not call.args[0].endswith("/menus")]
            self.assertEqual(fetched, ["https://songwai.online/uploads/media_480.png"])
        self.assertEqual((result["imported"], result["photos"]), (3, 1))

        items = {item["id"]: item for item in self.client.get("/api/menu?include_inactive=true").json()["items"]}
        self.assertTrue(items["songwai-480"]["photo"].startswith("/menu-photos/"))
        self.assertFalse(items["songwai-481"]["photo"])
        self.assertFalse(items["songwai-482"]["photo"])
        self.assertFalse(items["songwai-480"]["active"])   # รูปไม่ได้ทำให้จานเปิดขายเอง

        # กดซ้ำ: ไม่สร้างเมนูใหม่ และไม่ทับรูปที่มีอยู่แล้ว
        with patch.object(server.httpx, "get", side_effect=fake_get) as again:
            second = self.client.post("/api/integrations/songwai/import-drafts").json()
            self.assertEqual([c.args[0] for c in again.call_args_list if not c.args[0].endswith("/menus")], [])
        self.assertEqual((second["imported"], second["photos"]), (0, 0))

    def test_manual_partner_order_is_labeled_idempotent_and_uses_stock(self):
        payload = {"branch_id": 1, "channel": "GrabFood", "external_order_id": "GF-123",
                   "fulfillment": "rider_pickup", "items": [{"id": "beef", "qty": 2}]}
        self.assertEqual(self.client.post("/api/online/manual-orders", json=payload).status_code, 401)
        self._login()
        first = self.client.post("/api/online/manual-orders", json=payload)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["channel"], "GrabFood")
        second = self.client.post("/api/online/manual-orders", json=payload)
        self.assertEqual(second.json()["order_no"], first.json()["order_no"])
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute("SELECT stock FROM inventory WHERE ingredient_id='meat'").fetchone()[0], 6)
        payload["channel"] = "FakeFood"
        self.assertEqual(self.client.post("/api/online/manual-orders", json=payload).status_code, 400)

    def test_commerce_assets_are_served_for_pwa(self):
        for path in ("/commerce-ui.css", "/commerce-ui.js"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertTrue(response.content)

    def test_pickup_requires_verified_line_and_consent_for_campaign(self):
        payload = {"event_id": "test-online-123", "branch_id": 1,
                   "fulfillment": "self_pickup", "items": [{"id": "beef", "qty": 1}],
                   "line_id_token": "token", "customer_name": "Customer", "marketing_opt_in": True}
        with patch.object(server, "verify_liff_id_token", return_value="U-customer"):
            first = self.client.post("/api/online/orders", json=payload)
            self.assertEqual(first.status_code, 200, first.text)
            again = self.client.post("/api/online/orders", json=payload)
            self.assertEqual(again.json()["order_no"], first.json()["order_no"])
        with patch.object(server, "verify_liff_id_token", return_value="U-other"):
            self.assertEqual(self.client.post("/api/online/orders", json=payload).status_code, 409)
        self._login()
        customers = self.client.get("/api/crm/customers").json()["customers"]
        self.assertEqual(customers[0]["marketing_opt_in"], 1)
        draft = self.client.post("/api/crm/campaigns", json={
            "branch_id": 1, "segment": "new", "message": "โปรโมชันสำหรับสมาชิก"})
        self.assertEqual(draft.status_code, 200)
        self.assertEqual(draft.json()["eligible_recipients"], 1)
        with patch.object(server, "verify_liff_id_token", return_value="U-customer"):
            self.assertEqual(self.client.post("/api/crm/me/consent", json={
                "branch_id": 1, "line_id_token": "token", "marketing_opt_in": False}).status_code, 200)
        self.assertEqual(self.client.get(f"/api/crm/campaigns/{draft.json()['campaign_id']}").json()["eligible_recipients"], 0)

    def test_preview_blocks_online_mutations(self):
        server.PREVIEW_ONLY = True
        response = self._songwai({"order_id": 1, "restaurant_id": 37, "delivery_mode": "rider", "items": []})
        self.assertEqual(response.status_code, 403)

    def test_dormant_30_day_segment_and_opt_in_line_only(self):
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("""INSERT INTO crm_customers(branch_id,line_user_id,display_name,marketing_opt_in,
                completed_orders,last_order_at) VALUES(1,'U-dormant','Past customer',1,2,date('now','-31 day'))""")
            conn.execute("""INSERT INTO crm_customers(branch_id,songwai_user_id,display_name,marketing_opt_in,
                completed_orders,last_order_at) VALUES(1,'77','Songwai customer',0,2,date('now','-31 day'))""")
        self._login()
        customers = self.client.get('/api/crm/customers?segment=dormant30').json()['customers']
        self.assertEqual(len(customers), 2)
        draft = self.client.post('/api/crm/campaigns', json={
            'branch_id':1, 'segment':'dormant30', 'message':'กลับมาทานอาหารกันนะ'}).json()
        self.assertEqual(draft['eligible_recipients'], 1)
        with patch.object(server, 'LINE_CHANNEL_ACCESS_TOKEN', 'test-token'):
            with patch.object(server.httpx, 'Client') as client:
                client.return_value.__enter__.return_value.post.return_value.status_code = 200
                first = self.client.post(f"/api/crm/campaigns/{draft['campaign_id']}/send")
                second = self.client.post(f"/api/crm/campaigns/{draft['campaign_id']}/send")
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()['attempted'], 1)
        self.assertEqual(second.status_code, 409)


if __name__ == "__main__":
    unittest.main()
