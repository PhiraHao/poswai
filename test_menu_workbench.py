"""The fuller menu item: its fields, its photo, its toppings, and deleting it.

What matters here is that the shop's own record stays the authority. A request
may ask for a topping by name, but the price it adds and the stock it consumes
are read from the catalog, so a customer cannot invent a cheap one.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import line_pos_server as server

PNG = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
JPEG = (b"\xff\xd8\xff\xe0" + b"\x00" * 64)


class MenuWorkbenchTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.folder.cleanup)
        root = Path(self.folder.name)
        for item in (patch.object(server, "DB_PATH", root / "menu.db"),
                     patch.object(server, "PREVIEW_ONLY", False),
                     patch.object(server, "BOOTSTRAP_MANAGER_PIN", ""),
                     patch.object(server, "MENU_PHOTO_ROOT", root / "menu-photos")):
            item.start()
            self.addCleanup(item.stop)
        server.init_db()
        with sqlite3.connect(server.DB_PATH) as conn:
            conn.execute("INSERT INTO branches(id,name) VALUES(1,'One')")
            for staff_id, role in ((1, "manager"), (2, "cashier")):
                conn.execute("INSERT INTO staffs(id,branch_id,name,role,pin_code_hash) VALUES(?,1,?,?,?)",
                             (staff_id, role, role, server.hash_pin("secure-pin-" + role)))

        self.manager = TestClient(server.app)
        self.manager.__enter__()
        self.addCleanup(lambda: self.manager.__exit__(None, None, None))
        self.cashier = TestClient(server.app)
        self.cashier.__enter__()
        self.addCleanup(lambda: self.cashier.__exit__(None, None, None))
        self.manager.post("/api/auth/login", json={"staff_id": 1, "pin": "secure-pin-manager"})
        self.cashier.post("/api/auth/login", json={"staff_id": 2, "pin": "secure-pin-cashier"})
        for ingredient, stock, unit in (("PORK", 1000, "กรัม"), ("EGG", 50, "ฟอง")):
            self.assertEqual(self.manager.put(f"/api/inventory/{ingredient}", json={
                "branch_id": 1, "stock": stock, "unit": unit, "reorder_point": 10}).status_code, 200)

    # ---- helpers --------------------------------------------------------

    def _save(self, item_id="M001", **overrides):
        body = {"branch_id": 1, "name": "กะเพราหมูสับ", "price": 60,
                "bom": [{"ingId": "PORK", "qty": 120}]}
        body.update(overrides)
        return self.manager.put(f"/api/menu/{item_id}", json=body)

    def _billed(self, order_no):
        """What the shop's own record says the open bill comes to."""
        with sqlite3.connect(server.DB_PATH) as conn:
            rows = conn.execute("SELECT unit_price,quantity FROM order_items WHERE order_no=?",
                                (order_no,)).fetchall()
        return sum(price * quantity for price, quantity in rows)

    def _stock(self, ingredient):
        items = self.manager.get("/api/inventory").json()["items"]
        return next(item["stock"] for item in items if item["id"] == ingredient)

    def _order(self, order_no, total=60, **line):
        """``total`` is what the till believes the bill comes to, and each
        line states its own price too. The server refuses a bill that
        disagrees with its own prices, so a caller cannot leave them out."""
        item = {"id": "M001", "name": "กะเพราหมูสับ", "price": 60, "qty": 1}
        item.update(line)
        return self.cashier.post("/api/orders", json={
            "event_id": f"evt-{order_no}", "order_no": order_no, "branch_id": 1,
            "table_no": "T1", "total_amount": total, "items": [item]})

    # ---- the new fields -------------------------------------------------

    def test_every_field_survives_a_round_trip(self):
        response = self._save(
            category="จานหลัก", description="หมูสับผัดใบกะเพรา", cost=22,
            tax_mode="excluded", service_charge=True, station="ครัวร้อน",
            option_title="เลือกระดับความเผ็ด", levels=["ไม่เผ็ด", "เผ็ดมาก"],
            addons=[{"name": "เพิ่มไข่ดาว", "price": 10, "ingId": "EGG", "qty": 1}])
        self.assertEqual(response.status_code, 200, response.text)
        item = self.manager.get("/api/menu").json()["items"][0]
        self.assertEqual(item["category"], "จานหลัก")
        self.assertEqual(item["description"], "หมูสับผัดใบกะเพรา")
        self.assertEqual(item["cost"], 22)
        self.assertEqual(item["tax_mode"], "excluded")
        self.assertTrue(item["service_charge"])
        self.assertFalse(item["sold_out"])
        self.assertEqual(item["option_title"], "เลือกระดับความเผ็ด")
        self.assertEqual(item["levels"], ["ไม่เผ็ด", "เผ็ดมาก"])
        self.assertEqual(item["addons"],
                         [{"name": "เพิ่มไข่ดาว", "price": 10, "ingId": "EGG", "qty": 1.0}])

    def test_a_shop_cannot_invent_a_tax_mode_or_a_blank_topping(self):
        self.assertEqual(self._save(tax_mode="maybe").status_code, 400)
        self.assertEqual(self._save(addons=[{"name": "   ", "price": 5}]).status_code, 400)
        self.assertEqual(self._save(addons=[{"name": "ไข่", "price": 1}, {"name": "ไข่", "price": 2}]).status_code, 400)
        self.assertEqual(self._save(levels=["ปกติ", "ปกติ"]).status_code, 400)

    def test_categories_are_listed_from_what_the_shop_typed(self):
        self._save("M001", category="จานหลัก")
        self._save("M002", name="ชาเย็น", price=40, station="บาร์น้ำ", bom=[], category="เครื่องดื่ม")
        self._save("M003", name="ข้าวผัด", price=55, bom=[], category="จานหลัก")
        listing = self.manager.get("/api/menu/categories").json()
        self.assertEqual(listing["categories"], ["จานหลัก", "เครื่องดื่ม"])
        self.assertIn("ครัวร้อน", listing["stations"])
        self.assertIn("included", listing["tax_modes"])

    # ---- toppings are priced by the shop, not by the customer -----------

    def test_a_chosen_topping_adds_its_own_price_and_its_own_stock(self):
        self._save(addons=[{"name": "เพิ่มไข่ดาว", "price": 10, "ingId": "EGG", "qty": 2}])
        before = self._stock("EGG")
        response = self._order("ORD-1", (60 + 10) * 3, price=70, qty=3,
                               addons=["เพิ่มไข่ดาว"], level="เผ็ดมาก")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self._billed("ORD-1"), (60 + 10) * 3)
        self.assertEqual(self._stock("EGG"), before - 6)
        self.assertEqual(self._stock("PORK"), 1000 - 360)

    def test_a_topping_the_shop_never_offered_is_refused(self):
        self._save(addons=[{"name": "เพิ่มไข่ดาว", "price": 10, "ingId": "EGG", "qty": 1}])
        response = self._order("ORD-2", addons=["เพิ่มทองคำเปลว"])
        self.assertEqual(response.status_code, 409)
        self.assertIn("ไม่มีตัวเลือกเพิ่มนี้", response.json()["detail"])
        self.assertEqual(self._stock("PORK"), 1000)

    def test_the_same_topping_twice_is_still_charged_once(self):
        self._save(addons=[{"name": "เพิ่มไข่ดาว", "price": 10, "ingId": "EGG", "qty": 1}])
        response = self._order("ORD-3", 70, price=70, addons=["เพิ่มไข่ดาว", "เพิ่มไข่ดาว"])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self._billed("ORD-3"), 70)
        self.assertEqual(self._stock("EGG"), 49)

    def test_a_discount_topping_lowers_the_price_but_never_below_zero(self):
        self._save(price=5, bom=[], addons=[{"name": "นำแก้วมาเอง", "price": -5},
                                            {"name": "ส่วนลดพนักงาน", "price": -4}])
        paid = self._order("ORD-4", 0, price=0, addons=["นำแก้วมาเอง"])
        self.assertEqual(paid.status_code, 200, paid.text)
        self.assertEqual(self._billed("ORD-4"), 0)
        refused = self._order("ORD-5", 0, price=0, addons=["นำแก้วมาเอง", "ส่วนลดพนักงาน"])
        self.assertEqual(refused.status_code, 400)

    # ---- selling, and not selling ---------------------------------------

    def test_a_sold_out_dish_cannot_be_ordered_but_still_shows_on_the_menu(self):
        self._save(sold_out=True)
        response = self._order("ORD-6")
        self.assertEqual(response.status_code, 409)
        self.assertIn("ขายหมดชั่วคราว", response.json()["detail"])
        self.assertTrue(self.manager.get("/api/menu").json()["items"][0]["sold_out"])
        self.assertEqual(self._stock("PORK"), 1000)

    def test_availability_flips_on_its_own_without_touching_the_dish(self):
        """The switch on the menu row sends only what it changes."""
        self._save(category="จานหลัก", cost=22, addons=[{"name": "ไข่ดาว", "price": 10}])
        response = self.manager.patch("/api/menu/M001", json={"branch_id": 1, "sold_out": True})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["sold_out"])
        self.assertTrue(response.json()["active"])
        item = self.manager.get("/api/menu").json()["items"][0]
        self.assertTrue(item["sold_out"])
        # Everything the form owns is still exactly as it was.
        self.assertEqual(item["category"], "จานหลัก")
        self.assertEqual(item["cost"], 22)
        self.assertEqual(item["price"], 60)
        self.assertEqual([addon["name"] for addon in item["addons"]], ["ไข่ดาว"])
        self.assertEqual(item["bom"], [{"ingId": "PORK", "qty": 120}])

    def test_hiding_a_dish_takes_it_off_the_customer_menu_only(self):
        self._save()
        self.assertEqual(self.manager.patch("/api/menu/M001",
                                            json={"branch_id": 1, "active": False}).status_code, 200)
        self.assertEqual(self.manager.get("/api/menu").json()["items"], [])
        hidden = self.manager.get("/api/menu?include_inactive=true").json()["items"]
        self.assertEqual(len(hidden), 1)
        self.assertFalse(hidden[0]["active"])
        self.assertEqual(self._order("ORD-H").status_code, 409)

    def test_a_status_change_needs_a_real_dish_and_something_to_change(self):
        self._save()
        self.assertEqual(self.manager.patch("/api/menu/NOPE",
                                            json={"branch_id": 1, "sold_out": True}).status_code, 404)
        self.assertEqual(self.manager.patch("/api/menu/M001",
                                            json={"branch_id": 1}).status_code, 400)
        self.assertEqual(self.cashier.patch("/api/menu/M001",
                                            json={"branch_id": 1, "sold_out": True}).status_code, 403)

    def test_clearing_sold_out_lets_the_dish_sell_again(self):
        self._save(sold_out=True)
        self._save(sold_out=False)
        self.assertEqual(self._order("ORD-7").status_code, 200)

    # ---- deleting --------------------------------------------------------

    def test_deleting_a_dish_removes_it_without_touching_past_bills(self):
        self._save()
        self.assertEqual(self._order("ORD-8").status_code, 200)
        response = self.manager.delete("/api/menu/M001?branch_id=1")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.manager.get("/api/menu").json()["items"], [])
        lines = self.manager.get("/api/orders?branch_id=1").json()["orders"][0]["items"]
        self.assertEqual(lines[0]["name"], "กะเพราหมูสับ")
        self.assertEqual(self.manager.delete("/api/menu/M001?branch_id=1").status_code, 404)

    def test_a_cashier_cannot_delete_a_dish(self):
        self._save()
        self.assertEqual(self.cashier.delete("/api/menu/M001?branch_id=1").status_code, 403)
        self.assertEqual(len(self.manager.get("/api/menu").json()["items"]), 1)

    # ---- photos ----------------------------------------------------------

    def test_a_photo_is_stored_served_and_replaced(self):
        self._save()
        upload = self.manager.post("/api/menu/M001/photo?branch_id=1",
                                   files={"file": ("dish.png", PNG, "image/png")})
        self.assertEqual(upload.status_code, 200, upload.text)
        photo = upload.json()["photo"]
        self.assertTrue(photo.startswith("/menu-photos/main/"))
        self.assertEqual(self.manager.get("/api/menu").json()["items"][0]["photo"], photo)
        served = self.manager.get(photo)
        self.assertEqual(served.status_code, 200)
        self.assertEqual(served.headers["content-type"], "image/png")

        replaced = self.manager.post("/api/menu/M001/photo?branch_id=1",
                                     files={"file": ("dish.jpg", JPEG, "image/jpeg")})
        self.assertEqual(replaced.status_code, 200, replaced.text)
        self.assertNotEqual(replaced.json()["photo"], photo)
        self.assertEqual(self.manager.get(photo).status_code, 404)

    def test_saving_the_form_again_keeps_the_photo(self):
        self._save()
        photo = self.manager.post("/api/menu/M001/photo?branch_id=1",
                                  files={"file": ("dish.png", PNG, "image/png")}).json()["photo"]
        self._save(name="กะเพราหมูกรอบ", price=70)
        self.assertEqual(self.manager.get("/api/menu").json()["items"][0]["photo"], photo)

    def test_a_file_that_is_not_an_image_is_refused(self):
        self._save()
        for name, data, kind in (("x.png", b"<?php echo 1; ?>", "image/png"),
                                 ("x.svg", b"<svg onload=alert(1)>", "image/svg+xml"),
                                 ("x.webp", b"RIFF" + b"\x00" * 20, "image/webp")):
            with self.subTest(name=name):
                response = self.manager.post("/api/menu/M001/photo?branch_id=1",
                                             files={"file": (name, data, kind)})
                self.assertEqual(response.status_code, 400)
        self.assertEqual(self.manager.get("/api/menu").json()["items"][0]["photo"], "")

    def test_an_oversized_photo_is_refused(self):
        self._save()
        huge = PNG + b"\x00" * (3 * 1024 * 1024)
        response = self.manager.post("/api/menu/M001/photo?branch_id=1",
                                     files={"file": ("big.png", huge, "image/png")})
        self.assertEqual(response.status_code, 413)

    def test_the_photo_route_refuses_a_path_it_did_not_write(self):
        for path in ("/menu-photos/main/..%2F..%2Fmenu.db",
                     "/menu-photos/main/notahash.png",
                     "/menu-photos/MAIN/" + "a" * 32 + ".png"):
            with self.subTest(path=path):
                self.assertEqual(self.manager.get(path).status_code, 404)

    def test_deleting_a_dish_removes_its_photo_file(self):
        self._save()
        photo = self.manager.post("/api/menu/M001/photo?branch_id=1",
                                  files={"file": ("dish.png", PNG, "image/png")}).json()["photo"]
        stored = server.MENU_PHOTO_ROOT / "main" / photo.rsplit("/", 1)[1]
        self.assertTrue(stored.is_file())
        self.assertEqual(self.manager.delete("/api/menu/M001?branch_id=1").status_code, 200)
        self.assertFalse(stored.is_file())

    def test_a_cashier_cannot_upload_a_photo(self):
        self._save()
        response = self.cashier.post("/api/menu/M001/photo?branch_id=1",
                                     files={"file": ("dish.png", PNG, "image/png")})
        self.assertEqual(response.status_code, 403)

    # ---- the stock cupboard ---------------------------------------------

    def test_an_ingredient_carries_its_unit_and_warns_when_it_runs_low(self):
        items = {item["id"]: item for item in self.manager.get("/api/inventory").json()["items"]}
        self.assertEqual(items["PORK"]["unit"], "กรัม")
        self.assertEqual(items["PORK"]["reorder_point"], 10)
        self.assertFalse(items["PORK"]["low"])

        self._save(bom=[{"ingId": "PORK", "qty": 995}])
        self.assertEqual(self._order("ORD-9").status_code, 200)
        low = next(item for item in self.manager.get("/api/inventory").json()["items"]
                   if item["id"] == "PORK")
        self.assertEqual(low["stock"], 5)
        self.assertTrue(low["low"])

    def test_unit_and_reorder_point_can_be_corrected_later(self):
        response = self.manager.patch("/api/inventory/PORK",
                                      json={"branch_id": 1, "unit": "กิโลกรัม", "reorder_point": 2})
        self.assertEqual(response.status_code, 200, response.text)
        item = next(row for row in self.manager.get("/api/inventory").json()["items"]
                    if row["id"] == "PORK")
        self.assertEqual(item["unit"], "กิโลกรัม")
        self.assertEqual(item["reorder_point"], 2)
        self.assertEqual(self.manager.patch("/api/inventory/NOPE",
                                            json={"branch_id": 1, "unit": "ชิ้น"}).status_code, 404)
        self.assertEqual(self.manager.patch("/api/inventory/PORK",
                                            json={"branch_id": 1, "reorder_point": -1}).status_code, 400)

    def test_a_cashier_cannot_change_how_stock_is_counted(self):
        self.assertEqual(self.cashier.patch("/api/inventory/PORK",
                                            json={"branch_id": 1, "unit": "ชิ้น"}).status_code, 403)


if __name__ == "__main__":
    unittest.main()
