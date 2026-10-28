"""Opening a POS WAI shop from an existing Songwai shop, and signing in with its code.

A shop already trading on Songwai has its name, phone, menu, prices and photos
there. Making the owner type all of it again is the reason they never finish
setting up, so the shop code that opens their Songwai shop page opens POS WAI
too: once to create the shop, and afterwards to sign in. Only the owner — staff
keep their own number and PIN.
"""

import sqlite3
import tempfile
import unittest
import unittest.mock
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import line_pos_server as server

SECRET = "s" * 48
TOKEN = "ร้านโคตรเนื้อ-A1"          # Songwai shop codes may be Thai
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
SHOP = {
    "restaurant_id": 37, "poswai_shop": None, "name": "โคตรเนื้อ", "phone": "0903216618",
    "address": "บ้านอรุโณทัย", "poswai_enabled": False,
    "menus": [{"id": 480, "name": "เนื้อวัวผัดกะเพรา", "price": 50, "image_url": "/uploads/a.png"},
              {"id": 1490, "name": "หมูผัดขึ้นฉ่าย", "price": 45, "image_url": None}],
}


def _reply(status=200, payload=None):
    response = unittest.mock.Mock()
    response.status_code = status
    response.json.return_value = payload if payload is not None else {}
    response.raise_for_status.return_value = None
    response.content, response.headers = PNG, {"content-type": "image/png"}
    return response


class SongwaiOnboardingTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.folder.cleanup)
        for item in (patch.object(server, "DB_PATH", Path(self.folder.name) / "main.db"),
                     patch.object(server, "PREVIEW_ONLY", False),
                     patch.object(server, "STAFF_LIVE", True),
                     patch.object(server, "BOOTSTRAP_MANAGER_PIN", ""),
                     patch.object(server, "SONGWAI_WEBHOOK_SECRET", SECRET),
                     patch.object(server, "_prepared_databases", set())):
            item.start()
            self.addCleanup(item.stop)
        server.init_db()
        with sqlite3.connect(server.DB_PATH) as conn:
            conn.execute("INSERT INTO branches(id,name) VALUES(1,'Main')")

    def client(self):
        client = TestClient(server.app)
        client.__enter__()
        self.addCleanup(lambda: client.__exit__(None, None, None))
        return client

    def _open(self, client, *, shop_state=None, slug="khotnuea", token=TOKEN, status=200):
        """Create the POS WAI shop the way the sign-up screen does."""
        with patch.object(server.httpx, "post", return_value=_reply(status, shop_state or SHOP)) as post, \
             patch.object(server.httpx, "get", return_value=_reply()):
            response = client.post("/api/shops/from-songwai", json={
                "token": token, "slug": slug, "pin": "secure-owner-pin", "accept_terms": True})
        return response, post

    def test_the_shop_arrives_with_its_menu_photos_and_pairings(self):
        owner = self.client()
        response, post = self._open(owner)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["shop"]["name"], "โคตรเนื้อ")
        self.assertEqual((body["role"], body["songwai"]["restaurant_id"]), ("owner", 37))
        self.assertEqual((body["songwai"]["imported"], body["songwai"]["photos"]), (2, 1))
        # ชื่อร้านใน POS WAI ถูกส่งไปผูกที่ส่งไวด้วย ไม่ใช่แค่จำไว้ฝั่งนี้
        self.assertEqual(post.call_args.kwargs["json"], {"token": TOKEN, "shop": "khotnuea"})

        items = {i["id"]: i for i in owner.get("/api/menu?include_inactive=true").json()["items"]}
        self.assertEqual(sorted(items), ["songwai-1490", "songwai-480"])
        # ฉบับร่างเสมอ — เจ้าของต้องได้ดูก่อนว่าจะขายจานไหน
        self.assertFalse(any(i["active"] for i in items.values()))
        self.assertTrue(items["songwai-480"]["photo"].startswith("/menu-photos/"))
        self.assertFalse(items["songwai-1490"]["photo"])   # ส่งไวเองก็ไม่มีรูปจานนี้
        pairs = owner.get("/api/integrations/songwai/menu-map").json()
        self.assertEqual(pairs["restaurant_id"], 37)
        self.assertEqual([p["songwai_menu_id"] for p in pairs["mappings"]], [480, 1490])
        # เจ้าของร้านเข้าระบบอยู่แล้วทันที ไม่ต้องล็อกอินซ้ำหลังเปิดร้าน
        self.assertEqual(owner.get("/api/auth/session").json()["role"], "owner")

    def test_the_same_code_signs_the_owner_in_afterwards(self):
        self._open(self.client())
        linked = dict(SHOP, poswai_shop="khotnuea")
        phone = self.client()
        with patch.object(server.httpx, "post", return_value=_reply(200, linked)):
            response = phone.post("/api/auth/songwai-token", json={"token": TOKEN})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual((response.json()["role"], response.json()["shop"]["slug"]),
                         ("owner", "khotnuea"))
        self.assertEqual(phone.get("/api/auth/session").json()["role"], "owner")

    def test_a_code_that_songwai_refuses_opens_nothing(self):
        stranger = self.client()
        with patch.object(server.httpx, "post", return_value=_reply(404)):
            response = stranger.post("/api/auth/songwai-token", json={"token": "เดามั่ว"})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(stranger.get("/api/auth/session").status_code, 401)

    def test_a_shop_not_opened_in_pos_wai_yet_is_told_what_to_do(self):
        newcomer = self.client()
        with patch.object(server.httpx, "post", return_value=_reply(200, SHOP)):
            response = newcomer.post("/api/auth/songwai-token", json={"token": TOKEN})
        self.assertEqual(response.status_code, 404)
        self.assertIn("เปิดร้าน", response.json()["detail"])

    def test_a_code_pointing_at_another_restaurant_is_refused(self):
        """การผูกที่ค้างอยู่ผิดร้านต้องไม่กลายเป็นประตูเข้าร้านคนอื่น"""
        self._open(self.client())
        impostor = dict(SHOP, poswai_shop="khotnuea", restaurant_id=99)
        with patch.object(server.httpx, "post", return_value=_reply(200, impostor)):
            response = self.client().post("/api/auth/songwai-token", json={"token": "tok-99"})
        self.assertEqual(response.status_code, 403, response.text)

    def test_guessing_the_code_is_slowed_down(self):
        guesser = self.client()
        with patch.object(server.httpx, "post", return_value=_reply(404)):
            codes = [guesser.post("/api/auth/songwai-token", json={"token": f"เดา{n}"}).status_code
                     for n in range(server.SONGWAI_TOKEN_TRIES_PER_HOUR + 2)]
        self.assertEqual(codes[0], 404)
        self.assertEqual(codes[-1], 429)
        self.assertLessEqual(codes.count(404), server.SONGWAI_TOKEN_TRIES_PER_HOUR)

    def test_a_shop_already_linked_elsewhere_cannot_be_taken_over(self):
        taken = self.client()
        with patch.object(server.httpx, "post", return_value=_reply(409)):
            response = taken.post("/api/shops/from-songwai", json={
                "token": TOKEN, "slug": "ban-kaew", "pin": "secure-owner-pin", "accept_terms": True})
        self.assertEqual(response.status_code, 409)
        self.assertFalse((server.DB_PATH.parent / "shops" / "ban-kaew.db").exists())

    def test_the_terms_and_the_shop_code_are_both_required(self):
        client = self.client()
        with patch.object(server.httpx, "post", return_value=_reply(200, SHOP)) as post:
            refused = client.post("/api/shops/from-songwai", json={
                "token": TOKEN, "slug": "ban-mai", "pin": "secure-owner-pin", "accept_terms": False})
            blank = client.post("/api/shops/from-songwai", json={
                "token": "   ", "slug": "ban-mai", "pin": "secure-owner-pin", "accept_terms": True})
        self.assertEqual((refused.status_code, blank.status_code), (400, 400))
        post.assert_not_called()   # ไม่ยิงไปถามส่งไวจนกว่าข้อมูลจะครบ


if __name__ == "__main__":
    unittest.main()
