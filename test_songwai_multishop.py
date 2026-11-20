"""Songwai links to each POS WAI shop separately, not once per server.

The pilot kept the Songwai restaurant ID in one server-wide setting, so only the
first shop could ever receive delivery orders. Every shop now stores its own ID,
and the shop slug travels inside the signed body so a captured order cannot be
replayed into somebody else's kitchen.
"""

import hashlib
import hmac
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import line_pos_server as server

SECRET = "s" * 48


def signup(client, slug, name="ร้านทดสอบ", pin="owner-pin-123"):
    return client.post("/api/shops", json={"shop_name": name, "slug": slug, "owner_name": "เจ้าของ",
                                           "phone": "0812345678", "pin": pin, "accept_terms": True},
                       headers={"x-forwarded-for": f"10.0.0.{len(slug)}"})


class SongwaiMultiShopTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.folder.cleanup)
        for item in (patch.object(server, "DB_PATH", Path(self.folder.name) / "main.db"),
                     patch.object(server, "PREVIEW_ONLY", False),
                     patch.object(server, "STAFF_LIVE", True),
                     patch.object(server, "BOOTSTRAP_MANAGER_PIN", ""),
                     patch.object(server, "LINE_CHANNEL_ACCESS_TOKEN", ""),
                     patch.object(server, "SONGWAI_WEBHOOK_SECRET", SECRET),
                     patch.object(server, "SONGWAI_RESTAURANT_ID", 37),
                     patch.object(server, "_prepared_databases", set())):
            item.start()
            self.addCleanup(item.stop)
        server.init_db()
        with sqlite3.connect(server.DB_PATH) as conn:
            conn.execute("INSERT INTO branches(id,name) VALUES(1,'Main')")
            conn.execute("INSERT INTO staffs(id,branch_id,name,role,pin_code_hash) VALUES(1,1,'เดิม','owner',?)",
                         (server.hash_pin("main-owner-pin"),))

    def client(self):
        client = TestClient(server.app)
        client.__enter__()
        self.addCleanup(lambda: client.__exit__(None, None, None))
        return client

    def _songwai(self, payload, *, shop=None, secret=SECRET):
        """POST a signed order the way lib/poswaiBridge.js does on the Songwai side."""
        body = json.dumps(payload, separators=(",", ":")).encode()
        stamp = str(int(time.time()))
        sig = hmac.new(secret.encode(), stamp.encode() + b"." + body, hashlib.sha256).hexdigest()
        url = "/api/integrations/songwai/orders" + (f"?shop={shop}" if shop else "")
        return self.client().post(url, content=body,
                                  headers={"X-Songwai-Timestamp": stamp,
                                           "X-Songwai-Signature": "sha256=" + sig,
                                           "Content-Type": "application/json"})

    def _ready_shop(self, slug, restaurant_id, item_id="RICE"):
        """Open a shop, give it one sellable item and link it to a Songwai restaurant."""
        owner = self.client()
        self.assertEqual(signup(owner, slug).status_code, 200)
        menu = owner.put(f"/api/menu/{item_id}", json={"branch_id": 1, "name": "ข้าวผัด", "price": 60,
                                                       "station": "ครัวร้อน", "bom": []})
        self.assertEqual(menu.status_code, 200, menu.text)
        linked = owner.put("/api/integrations/songwai/link",
                           json={"branch_id": 1, "restaurant_id": restaurant_id})
        self.assertEqual(linked.status_code, 200, linked.text)
        self.assertEqual(linked.json()["shop"], slug)
        mapped = owner.put("/api/integrations/songwai/menu-map",
                           json={"branch_id": 1, "restaurant_id": restaurant_id,
                                 "songwai_menu_id": 101, "pos_item_id": item_id})
        self.assertEqual(mapped.status_code, 200, mapped.text)
        return owner

    def test_two_shops_each_receive_only_their_own_restaurant(self):
        self._ready_shop("ban-kaew", 101)
        self._ready_shop("ban-sai", 202)
        order = {"order_id": 9001, "restaurant_id": 101, "delivery_mode": "rider", "shop": "ban-kaew",
                 "customer_name": "สมชาย", "contact_phone": "0812345678",
                 "items": [{"menu_id": 101, "qty": 2}]}

        accepted = self._songwai(order, shop="ban-kaew")
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertEqual(accepted.json()["total_amount"], 120)

        # เลขร้านของร้านแรก ยิงใส่ร้านที่สอง = ไม่ใช่ของเขา
        foreign = self._songwai(dict(order, shop="ban-sai"), shop="ban-sai")
        self.assertEqual(foreign.status_code, 403, foreign.text)

        # ใบเดิมที่เซ็นแล้ว (slug อยู่ในลายเซ็น) เอาไปยิงใส่ ?shop= ของร้านอื่นไม่ได้
        replayed = self._songwai(order, shop="ban-sai")
        self.assertEqual(replayed.status_code, 403, replayed.text)

        for slug, expected in (("ban-kaew", 1), ("ban-sai", 0)):
            with sqlite3.connect(server.DB_PATH.parent / "shops" / f"{slug}.db") as conn:
                count = conn.execute("SELECT COUNT(*) FROM online_orders WHERE source='songwai'").fetchone()[0]
            self.assertEqual(count, expected, slug)

    def test_shop_without_a_link_takes_no_order_and_says_so(self):
        owner = self.client()
        self.assertEqual(signup(owner, "ban-mai").status_code, 200)
        state = owner.get("/api/integrations/songwai/link").json()
        self.assertEqual((state["shop"], state["restaurant_id"], state["source"]), ("ban-mai", 0, "none"))
        self.assertTrue(state["secret_ready"])
        # ร้านที่ยังไม่ผูกต้องไม่ยืมค่าตั้งของเซิร์ฟเวอร์ (เลข 37 ของร้านหลัก)
        rejected = self._songwai({"order_id": 9002, "restaurant_id": 37, "delivery_mode": "pickup",
                                  "shop": "ban-mai", "items": [{"menu_id": 101, "qty": 1}]}, shop="ban-mai")
        self.assertEqual(rejected.status_code, 403, rejected.text)
        # จับคู่เมนูก่อนผูกร้านก็ไม่ได้ ไม่งั้นจับคู่ไว้กับร้านที่ไม่มีอยู่
        early = owner.put("/api/integrations/songwai/menu-map",
                          json={"branch_id": 1, "restaurant_id": 101, "songwai_menu_id": 1, "pos_item_id": "RICE"})
        self.assertEqual(early.status_code, 409, early.text)

    def test_main_shop_still_falls_back_to_the_server_setting(self):
        """ร้านหลักที่ตั้งค่าไว้ก่อนหน้านี้ต้องไม่หลุดเพราะยังไม่เคยกดผูก"""
        main = self.client()
        self.assertEqual(main.post("/api/auth/login", json={"shop": "main", "staff_id": 1,
                                                            "pin": "main-owner-pin"}).status_code, 200)
        state = main.get("/api/integrations/songwai/link").json()
        self.assertEqual((state["restaurant_id"], state["source"]), (37, "server"))
        menu = main.put("/api/menu/NOODLE", json={"branch_id": 1, "name": "บะหมี่", "price": 50,
                                                  "station": "ครัวร้อน", "bom": []})
        self.assertEqual(menu.status_code, 200, menu.text)
        self.assertEqual(main.put("/api/integrations/songwai/menu-map",
                                  json={"branch_id": 1, "restaurant_id": 37, "songwai_menu_id": 480,
                                        "pos_item_id": "NOODLE"}).status_code, 200)
        # ส่งไวรุ่นเก่าที่ยังไม่ส่ง slug มาด้วย ต้องเข้าร้านหลักได้เหมือนเดิม
        legacy = self._songwai({"order_id": 9003, "restaurant_id": 37, "delivery_mode": "rider",
                                "items": [{"menu_id": 480, "qty": 1}]})
        self.assertEqual(legacy.status_code, 200, legacy.text)

    def test_relinking_clears_menu_pairs_that_belong_to_the_old_restaurant(self):
        owner = self._ready_shop("ban-nok", 303)
        self.assertEqual(len(owner.get("/api/integrations/songwai/menu-map").json()["mappings"]), 1)
        moved = owner.put("/api/integrations/songwai/link", json={"branch_id": 1, "restaurant_id": 404})
        self.assertEqual(moved.status_code, 200, moved.text)
        state = owner.get("/api/integrations/songwai/link").json()
        self.assertEqual((state["restaurant_id"], state["source"]), (404, "shop"))
        # เลขเมนู 101 เป็นของร้าน 303 — ปล่อยค้างไว้จะทำอาหารผิดจาน
        self.assertEqual(owner.get("/api/integrations/songwai/menu-map").json()["mappings"], [])
        orphan = self._songwai({"order_id": 9004, "restaurant_id": 404, "delivery_mode": "pickup",
                                "shop": "ban-nok", "items": [{"menu_id": 101, "qty": 1}]}, shop="ban-nok")
        self.assertEqual(orphan.status_code, 409, orphan.text)

    def test_only_managers_link_a_shop_and_the_id_must_be_sane(self):
        owner = self.client()
        self.assertEqual(signup(owner, "ban-rim").status_code, 200)
        for bad in (0, -5, 10_000_001):
            self.assertEqual(owner.put("/api/integrations/songwai/link",
                                       json={"branch_id": 1, "restaurant_id": bad}).status_code, 400)
        stranger = self.client()
        self.assertEqual(stranger.put("/api/integrations/songwai/link?shop=ban-rim",
                                      json={"branch_id": 1, "restaurant_id": 505}).status_code, 401)


if __name__ == "__main__":
    unittest.main()
