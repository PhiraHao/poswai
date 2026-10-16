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


if __name__ == "__main__":
    unittest.main()
