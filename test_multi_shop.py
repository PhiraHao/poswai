"""Opening shops, keeping their data apart, the read-only demo and shop members."""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import line_pos_server as server


def signup(client, slug, name="ร้านทดสอบ", pin="owner-pin-123"):
    return client.post("/api/shops", json={"shop_name": name, "slug": slug, "owner_name": "เจ้าของ",
                                           "phone": "0812345678", "pin": pin, "accept_terms": True},
                       headers={"x-forwarded-for": f"10.0.0.{len(slug)}"})


class MultiShopTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.folder.cleanup)
        for item in (patch.object(server, "DB_PATH", Path(self.folder.name) / "main.db"),
                     patch.object(server, "PREVIEW_ONLY", False),
                     patch.object(server, "STAFF_LIVE", True),
                     patch.object(server, "BOOTSTRAP_MANAGER_PIN", ""),
                     patch.object(server, "TABLE_QR_SECRET", "x" * 40),
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

    def test_opening_a_shop_signs_the_owner_in_with_its_own_data(self):
        owner = self.client()
        response = signup(owner, "ban-kaew")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual((body["staff_id"], body["role"], body["shop"]["slug"]), (1, "owner", "ban-kaew"))
        self.assertEqual(owner.get("/api/auth/session").json()["name"], "เจ้าของ")
        self.assertEqual(owner.get("/api/config").json()["shop"]["name"], "ร้านทดสอบ")
        self.assertTrue((server.DB_PATH.parent / "shops" / "ban-kaew.db").exists())

        menu = owner.put("/api/menu/RICE", json={"branch_id": 1, "name": "ข้าวผัด", "price": 50,
                                                 "station": "ครัวร้อน", "bom": []})
        self.assertEqual(menu.status_code, 200, menu.text)
        # The original shop never sees the new shop's menu, and the reverse.
        main = self.client()
        self.assertEqual(main.get("/api/menu?branch_id=1").json()["items"], [])
        self.assertEqual([item["id"] for item in owner.get("/api/menu?branch_id=1").json()["items"]], ["RICE"])

    def test_login_needs_the_right_shop_code(self):
        signup(self.client(), "shop-one")
        staff = self.client()
        wrong = staff.post("/api/auth/login", json={"shop": "shop-two", "staff_id": 1, "pin": "owner-pin-123"})
        self.assertEqual(wrong.status_code, 401)
        # The original shop's owner is staff 1 too, but the PIN belongs to another shop.
        main = staff.post("/api/auth/login", json={"shop": "main", "staff_id": 1, "pin": "owner-pin-123"})
        self.assertEqual(main.status_code, 401)
        ok = staff.post("/api/auth/login", json={"shop": "SHOP-ONE", "staff_id": 1, "pin": "owner-pin-123"})
        self.assertEqual(ok.status_code, 200, ok.text)
        self.assertEqual(ok.json()["shop"], "shop-one")
        self.assertEqual(staff.get("/api/config").json()["shop"]["slug"], "shop-one")
        legacy = self.client().post("/api/auth/login", json={"staff_id": 1, "pin": "main-owner-pin"})
        self.assertEqual(legacy.status_code, 200)

    def test_shop_codes_are_unique_and_checked(self):
        client = self.client()
        self.assertEqual(signup(client, "noodle-house").status_code, 200)
        self.assertEqual(signup(self.client(), "noodle-house").status_code, 409)
        for bad in ("ab", "demo", "main", "Bad Code", "-dash"):
            self.assertIn(signup(self.client(), bad).status_code, (400, 409), bad)
        check = client.get("/api/shops/check?slug=noodle-house").json()
        self.assertEqual((check["valid"], check["available"]), (True, False))
        weak = client.post("/api/shops", json={"shop_name": "x", "slug": "weak-pin", "owner_name": "x",
                                               "phone": "0812345678", "pin": "1234", "accept_terms": True})
        self.assertEqual(weak.status_code, 400)
        self.assertFalse((server.DB_PATH.parent / "shops" / "weak-pin.db").exists())

    def test_one_address_cannot_open_shops_in_a_burst(self):
        codes = [signup(self.client(), f"burst-{n}x").status_code for n in range(4)]
        self.assertEqual(codes[:3], [200, 200, 200])
        self.assertEqual(codes[3], 429)

    def test_demo_is_read_only_and_never_remembered(self):
        visitor = self.client()
        page = visitor.get("/?shop=demo")
        self.assertEqual(page.status_code, 200)
        config = visitor.get("/api/config").json()
        self.assertTrue(config["preview_only"])
        self.assertTrue(config["shop"]["is_demo"])
        blocked = visitor.put("/api/menu/X", json={"branch_id": 1, "name": "x", "price": 1, "station": "ครัวร้อน", "bom": []})
        self.assertEqual(blocked.status_code, 403)
        visitor.get("/")
        self.assertFalse(visitor.get("/api/config").json()["shop"]["is_demo"])

    def test_table_qr_from_one_shop_does_not_open_another(self):
        owner = self.client()
        signup(owner, "qr-shop")
        token = owner.post("/api/tables/token", json={"branch_id": 1, "table_no": "1"}).json()
        self.assertIn("shop=qr-shop", token["url"])
        guest = self.client()
        guest.get("/?shop=qr-shop")
        ok = guest.get("/api/orders?branch_id=1&table_no=1", headers={"x-table-token": token["token"]})
        self.assertEqual(ok.status_code, 200, ok.text)
        other = self.client()
        other.get("/?shop=main")
        stolen = other.get("/api/orders?branch_id=1&table_no=1", headers={"x-table-token": token["token"]})
        self.assertEqual(stolen.status_code, 403)

    def test_owner_sets_shop_name_and_promptpay(self):
        owner = self.client()
        signup(owner, "pay-shop")
        bad = owner.put("/api/shop/settings", json={"promptpay_id": "12"})
        self.assertEqual(bad.status_code, 400)
        saved = owner.put("/api/shop/settings", json={"name": "ร้านใหม่", "promptpay_id": "081-234-5678"})
        self.assertEqual(saved.status_code, 200, saved.text)
        config = owner.get("/api/config").json()
        self.assertEqual((config["promptpay_id"], config["shop"]["name"]), ("0812345678", "ร้านใหม่"))


class MembersTest(MultiShopTest.__base__):
    setUp = MultiShopTest.setUp
    client = MultiShopTest.client

    def test_customer_joins_with_line_and_cashier_adds_and_redeems_points(self):
        owner = self.client()
        signup(owner, "member-shop")
        customer = self.client()
        customer.get("/?shop=member-shop")
        with patch.object(server, "verify_liff_id_token", return_value="U-line-1"):
            card = customer.post("/api/members/me", json={"line_id_token": "t", "display_name": "ลูกค้า",
                                                           "phone": "089-111-2222", "marketing_opt_in": True})
        self.assertEqual(card.status_code, 200, card.text)
        self.assertEqual((card.json()["points"], card.json()["display_name"]), (0, "ลูกค้า"))

        earned = owner.post("/api/members/points", json={"phone": "0891112222", "spend_amount": 255})
        self.assertEqual(earned.status_code, 200, earned.text)
        self.assertEqual((earned.json()["change"], earned.json()["points"]), (25, 25))
        too_many = owner.post("/api/members/points", json={"phone": "0891112222", "redeem_points": 30})
        self.assertEqual(too_many.status_code, 409)
        used = owner.post("/api/members/points", json={"phone": "0891112222", "redeem_points": 20})
        self.assertEqual(used.json()["points"], 5)
        self.assertEqual(owner.post("/api/members/points", json={"phone": "0800000000", "spend_amount": 99}).status_code, 404)

        with patch.object(server, "verify_liff_id_token", return_value="U-line-1"):
            again = customer.post("/api/members/me", json={"line_id_token": "t"})
        self.assertEqual(again.json()["points"], 5)
        self.assertEqual([h["change"] for h in again.json()["history"]], [-20, 25])
        listed = owner.get("/api/crm/customers?branch_id=1").json()["customers"]
        self.assertEqual(listed[0]["points"], 5)
        # Points are kept per shop: the original shop has no such member.
        main = self.client()
        main.post("/api/auth/login", json={"staff_id": 1, "pin": "main-owner-pin"})
        self.assertEqual(main.post("/api/members/points", json={"phone": "0891112222", "spend_amount": 50}).status_code, 404)

    def test_staff_sign_a_walk_in_customer_up_without_line(self):
        owner = self.client()
        signup(owner, "counter-shop")
        card = owner.post("/api/members", json={"display_name": "ป้าแดง", "phone": "089-555-1111"})
        self.assertEqual(card.status_code, 200, card.text)
        self.assertEqual((card.json()["points"], card.json()["phone"]), (0, "0895551111"))
        self.assertEqual(owner.post("/api/members", json={"display_name": "ซ้ำ", "phone": "0895551111"}).status_code, 409)
        self.assertEqual(owner.post("/api/members", json={"display_name": "x", "phone": "123"}).status_code, 400)
        earned = owner.post("/api/members/points", json={"phone": "0895551111", "spend_amount": 480})
        self.assertEqual(earned.json()["points"], 48)
        guest = self.client()
        guest.get("/?shop=counter-shop")
        self.assertEqual(guest.post("/api/members", json={"display_name": "x", "phone": "0812223333"}).status_code, 401)

    def test_guests_cannot_award_points(self):
        guest = self.client()
        self.assertEqual(guest.post("/api/members/points", json={"phone": "0891112222", "spend_amount": 50}).status_code, 401)


if __name__ == "__main__":
    unittest.main()
