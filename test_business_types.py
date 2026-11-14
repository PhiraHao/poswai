"""ร้านที่ไม่ใช่ร้านอาหาร: ประเภทธุรกิจ บาร์โค้ด และตัวเลือกที่มีราคา

POS WAI เขียนขึ้นเพื่อร้านอาหาร ทุกหน้าจึงพูดว่า "สั่งอาหาร" "จอครัว" "โต๊ะ"
ร้านขายเสื้อที่เปิดมาเจอแบบนี้จะปิดทิ้ง เทสต์ชุดนี้คุมสามเรื่องที่ทำให้
ร้านแบบอื่นใช้งานได้จริง
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import line_pos_server as server
import poswai_profile as profile


class BusinessCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.directory.cleanup)
        server.DB_PATH = Path(self.directory.name) / "business.db"
        server.PREVIEW_ONLY = False
        server.BOOTSTRAP_MANAGER_PIN = ""
        server.TABLE_QR_SECRET = "b" * 48
        server.init_db()
        conn = sqlite3.connect(server.DB_PATH)
        with conn:
            conn.execute("INSERT INTO branches(id,name) VALUES(1,'Test')")
            conn.execute("INSERT INTO staffs(id,branch_id,name,role,pin_code_hash) VALUES(1,1,'Owner','owner',?)",
                         (server.hash_pin("secure-pin-owner"),))
            conn.execute("INSERT INTO staffs(id,branch_id,name,role,pin_code_hash) VALUES(2,1,'Till','cashier',?)",
                         (server.hash_pin("secure-pin-till"),))
        conn.close()

    def signed_in(self, staff_id=1, pin="secure-pin-owner"):
        client = TestClient(server.app)
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        self.assertEqual(client.post("/api/auth/login",
                                     json={"staff_id": staff_id, "pin": pin}).status_code, 200)
        return client

    def save_item(self, client, item_id, **overrides):
        body = {"branch_id": 1, "name": "เสื้อยืด", "price": 250, "bom": [], "station": "ครัวร้อน"}
        body.update(overrides)
        return client.put(f"/api/menu/{item_id}", json=body)


class WhatTheShopSells(BusinessCase):
    def test_a_shop_that_never_chose_is_a_restaurant(self):
        """Which is every shop already open, and none of them may change."""
        with TestClient(server.app) as anyone:
            business = anyone.get("/api/config").json()["business"]
        self.assertEqual(business["type"], "restaurant")
        self.assertEqual(business["tabs_hidden"], [])

    def test_a_retail_shop_gets_its_own_words_and_loses_the_kitchen(self):
        owner = self.signed_in()
        self.assertEqual(owner.put("/api/shop/settings",
                                   json={"business_type": "retail"}).status_code, 200)
        with TestClient(server.app) as anyone:
            business = anyone.get("/api/config").json()["business"]
        self.assertEqual(business["type"], "retail")
        self.assertEqual(business["words"]["sell"], "ขายสินค้า")
        self.assertIn("kitchen", business["tabs_hidden"])

    def test_the_screens_are_told_before_anyone_signs_in(self):
        """The first screen a customer sees is already named by the type."""
        self.signed_in().put("/api/shop/settings", json={"business_type": "service"})
        with TestClient(server.app) as stranger:
            self.assertEqual(stranger.get("/api/config").json()["business"]["type"], "service")

    def test_an_invented_business_type_is_refused(self):
        self.assertEqual(self.signed_in().put("/api/shop/settings",
                                              json={"business_type": "spaceship"}).status_code, 400)

    def test_a_cashier_cannot_change_what_the_shop_is(self):
        till = self.signed_in(2, "secure-pin-till")
        self.assertEqual(till.put("/api/shop/settings",
                                  json={"business_type": "retail"}).status_code, 403)

    def test_switching_type_keeps_every_item_the_shop_already_had(self):
        """A shop trying retail for an afternoon must find its menu intact."""
        owner = self.signed_in()
        self.assertEqual(self.save_item(owner, "M1", name="ข้าวผัด", price=60,
                                        station="ครัวร้อน").status_code, 200)
        owner.put("/api/shop/settings", json={"business_type": "retail"})
        names = [item["name"] for item in owner.get("/api/menu?branch_id=1").json()["items"]]
        self.assertEqual(names, ["ข้าวผัด"])
        # And it can still be edited, though its station belongs to a kitchen.
        self.assertEqual(self.save_item(owner, "M1", name="ข้าวผัด", price=65,
                                        station="ครัวร้อน").status_code, 200)

    def test_a_retail_shop_is_offered_its_own_station_names(self):
        owner = self.signed_in()
        owner.put("/api/shop/settings", json={"business_type": "retail"})
        listing = owner.get("/api/menu/categories?branch_id=1").json()
        self.assertEqual(listing["stations"], ["หน้าร้าน"])
        self.assertEqual(listing["business_type"], "retail")
        self.assertEqual(self.save_item(owner, "S1", station="หน้าร้าน").status_code, 200)


class Barcodes(BusinessCase):
    def test_an_item_is_found_by_the_number_on_its_packet(self):
        owner = self.signed_in()
        self.save_item(owner, "S1", barcode="8850001234567")
        found = owner.get("/api/menu/barcode/8850001234567?branch_id=1")
        self.assertEqual(found.status_code, 200, found.text)
        self.assertEqual(found.json()["id"], "S1")

    def test_spaces_and_dashes_a_scanner_sends_are_ignored(self):
        owner = self.signed_in()
        self.save_item(owner, "S1", barcode="885-000 1234567")
        self.assertEqual(owner.get("/api/menu/barcode/8850001234567?branch_id=1").status_code, 200)

    def test_two_products_cannot_share_one_number(self):
        """Otherwise every scan rings up whichever row came back first, and the
        shop finds out from its stock count weeks later."""
        owner = self.signed_in()
        self.save_item(owner, "S1", barcode="8850001234567")
        clash = self.save_item(owner, "S2", name="กางเกง", barcode="8850001234567")
        self.assertEqual(clash.status_code, 409)

    def test_an_item_may_keep_its_own_number_when_it_is_edited(self):
        owner = self.signed_in()
        self.save_item(owner, "S1", barcode="8850001234567")
        again = self.save_item(owner, "S1", price=290, barcode="8850001234567")
        self.assertEqual(again.status_code, 200, again.text)

    def test_most_items_have_no_barcode_and_that_is_fine(self):
        owner = self.signed_in()
        self.assertEqual(self.save_item(owner, "S1").status_code, 200)
        self.assertEqual(self.save_item(owner, "S2", name="กางเกง").status_code, 200)

    def test_a_number_nobody_uses_is_a_plain_not_found(self):
        self.assertEqual(self.signed_in().get("/api/menu/barcode/999?branch_id=1").status_code, 404)

    def test_a_rubbish_barcode_is_refused_when_saving(self):
        self.assertEqual(self.save_item(self.signed_in(), "S1", barcode="!!").status_code, 400)

    def test_an_item_that_is_off_sale_says_so_instead_of_ringing_up(self):
        owner = self.signed_in()
        self.save_item(owner, "S1", barcode="8850001234567", active=False)
        refused = owner.get("/api/menu/barcode/8850001234567?branch_id=1")
        self.assertEqual(refused.status_code, 409)
        self.assertIn("ปิดขาย", refused.json()["detail"])

    def test_a_guest_at_a_table_cannot_read_the_catalogue_by_number(self):
        owner = self.signed_in()
        self.save_item(owner, "S1", barcode="8850001234567")
        token = owner.post("/api/tables/token", json={"branch_id": 1, "table_no": "T1"}).json()["token"]
        with TestClient(server.app) as guest:
            answer = guest.get("/api/menu/barcode/8850001234567?branch_id=1",
                               headers={"X-Table-Token": token})
        self.assertIn(answer.status_code, (401, 403), answer.text)


class PricedSizes(BusinessCase):
    def order(self, client, order_no, total, *, level="", price=250, qty=1):
        return client.post("/api/orders", json={
            "event_id": order_no, "order_no": order_no, "branch_id": 1, "table_no": "1",
            "total_amount": total,
            "items": [{"id": "S1", "name": "เสื้อยืด", "price": price, "qty": qty,
                       "course_mode": "FIRE", "bom": [], "level": level}]})

    def test_a_size_can_cost_more_than_the_base_price(self):
        """The till sends the line at its full price, size included, exactly as
        it already does for a topping."""
        owner = self.signed_in()
        self.save_item(owner, "S1", levels=[{"name": "M", "price": 0}, {"name": "XL", "price": 50}])
        answer = self.order(owner, "B-1", 300, level="XL", price=300)
        self.assertEqual(answer.status_code, 200, answer.text)

    def test_the_plain_size_still_costs_the_plain_price(self):
        owner = self.signed_in()
        self.save_item(owner, "S1", levels=[{"name": "M", "price": 0}, {"name": "XL", "price": 50}])
        self.assertEqual(self.order(owner, "B-2", 250, level="M").status_code, 200)

    def test_the_till_cannot_decide_what_a_size_costs(self):
        owner = self.signed_in()
        self.save_item(owner, "S1", levels=[{"name": "XL", "price": 50}])
        self.assertEqual(self.order(owner, "B-3", 250, level="XL").status_code, 409)

    def test_a_size_the_shop_never_listed_is_refused(self):
        owner = self.signed_in()
        self.save_item(owner, "S1", levels=[{"name": "M", "price": 0}])
        self.assertEqual(self.order(owner, "B-4", 250, level="XXXL").status_code, 409)

    def test_plain_names_still_work_and_cost_nothing_extra(self):
        """Every drink whose sweetness is free was saved this way."""
        owner = self.signed_in()
        self.save_item(owner, "S1", levels=["หวานน้อย", "หวานปกติ"])
        self.assertEqual(self.order(owner, "B-5", 250, level="หวานน้อย").status_code, 200)

    def test_the_old_field_still_carries_plain_names_for_a_shipped_app(self):
        """The Android till on a shop's phone reads `levels` as names. Changing
        that field's shape would stop it selling until Google pushes a build."""
        owner = self.signed_in()
        self.save_item(owner, "S1", levels=[{"name": "M", "price": 0}, {"name": "XL", "price": 50}])
        item = owner.get("/api/menu?branch_id=1").json()["items"][0]
        self.assertEqual(item["levels"], ["M", "XL"])
        self.assertEqual(item["level_prices"],
                         [{"name": "M", "price": 0}, {"name": "XL", "price": 50}])

    def test_a_size_cannot_discount_an_item_below_nothing(self):
        owner = self.signed_in()
        self.save_item(owner, "S1", price=50, levels=[{"name": "เล็ก", "price": -100}])
        self.assertEqual(self.order(owner, "B-6", 0, level="เล็ก", price=50).status_code, 409)


class ProfileDefaults(unittest.TestCase):
    def test_every_business_type_names_all_the_words_the_screens_ask_for(self):
        """A missing word leaves a screen with a blank heading."""
        expected = set(profile.BUSINESS_TYPES["restaurant"]["words"])
        for name, shape in profile.BUSINESS_TYPES.items():
            self.assertEqual(set(shape["words"]), expected, name)
            self.assertTrue(shape["label"], name)

    def test_a_database_naming_a_type_that_no_longer_exists_reads_as_restaurant(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        profile.ensure_schema(conn)
        conn.execute("UPDATE shop_profile SET business_type='bakery-2019' WHERE id=1")
        self.assertEqual(profile.read(conn)["business_type"], "restaurant")


if __name__ == "__main__":
    unittest.main()


class TheLastOfTheRestaurantWording(BusinessCase):
    """ชื่อแท็บเบราว์เซอร์ การ์ดเข้าระบบ และหน้าแรกการตลาด เคยบอกว่าเป็นระบบ
    ร้านอาหารไม่ว่าร้านนั้นจะขายอะไร"""

    def words(self, kind):
        self.signed_in().put("/api/shop/settings", json={"business_type": kind})
        with TestClient(server.app) as anyone:
            return anyone.get("/api/config").json()["business"]["words"]

    def test_every_type_names_its_own_browser_tab(self):
        self.assertEqual(self.words("restaurant")["title"], "POS WAI — ระบบจัดการร้านอาหาร")
        self.assertEqual(self.words("retail")["title"], "POS WAI — ระบบขายหน้าร้าน")
        self.assertEqual(self.words("service")["title"], "POS WAI — ระบบเปิดบิลรับงาน")

    def test_the_sign_in_card_tells_a_shop_what_it_is(self):
        retail = self.words("retail")
        self.assertIn("สินค้า", retail["guest_note"])
        self.assertNotIn("อาหาร", retail["guest_note"])

    def test_the_marketing_page_no_longer_says_restaurants_only(self):
        """It is POS WAI's own pitch, shown before any shop is chosen."""
        landing = (Path(server.__file__).parent / "landing.js").read_text(encoding="utf-8")
        self.assertNotIn("สำหรับร้านอาหาร", landing)
        self.assertIn("ร้านค้า", landing)

    def test_the_installed_app_is_named_for_what_it_does(self):
        """One manifest serves every shop on the site, so it cannot follow one."""
        import json
        manifest = json.loads((Path(server.__file__).parent / "manifest.json")
                              .read_text(encoding="utf-8"))
        self.assertNotIn("ร้านอาหาร", manifest["name"])
