"""The sticker on the table, and the guest who settles their own bill.

The printed paper holds no token. It holds a code the server trades for a
short-lived token, which is what makes a permanent sticker safe: a photograph
of it taken last week opens nothing, and one table's code can be withdrawn
without touching the paper on any other table.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import line_pos_server as server


class TableQrTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.folder.cleanup)
        for item in (patch.object(server, "DB_PATH", Path(self.folder.name) / "tables.db"),
                     patch.object(server, "PREVIEW_ONLY", False),
                     patch.object(server, "BOOTSTRAP_MANAGER_PIN", ""),
                     patch.object(server, "TABLE_QR_SECRET", "x" * 48)):
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
        self.manager.post("/api/auth/login", json={"staff_id": 1, "pin": "secure-pin-manager"})
        # A phone that has only ever scanned a sticker: no session cookie at all.
        self.guest = TestClient(server.app)
        self.guest.__enter__()
        self.addCleanup(lambda: self.guest.__exit__(None, None, None))

        self.manager.put("/api/inventory/TEA", json={"branch_id": 1, "stock": 500})
        self.manager.put("/api/menu/M001", json={"branch_id": 1, "name": "ชาเย็น", "price": 50,
                                                 "station": "บาร์น้ำ", "bom": [{"ingId": "TEA", "qty": 2}]})

    # ---- helpers --------------------------------------------------------

    def _add(self, table_no="1", **extra):
        return self.manager.post("/api/tables", json={"branch_id": 1, "table_no": table_no, **extra})

    def _scan(self, code, client=None):
        """Follow a sticker exactly as a phone would, and keep the token."""
        response = (client or self.guest).get(f"/t/{code}?shop=main", follow_redirects=False)
        if response.status_code != 303:
            return response, ""
        location = response.headers["location"]
        from urllib.parse import parse_qs, urlparse
        return response, parse_qs(urlparse(location).query)["table_token"][0]

    def _order(self, token, order_no, table_no="1", qty=1):
        return self.guest.post("/api/orders", headers={"X-Table-Token": token}, json={
            "event_id": f"evt-{order_no}", "order_no": order_no, "branch_id": 1,
            "table_no": table_no, "total_amount": 50 * qty,
            "items": [{"id": "M001", "name": "ชาเย็น", "price": 50, "qty": qty}]})

    # ---- the register ----------------------------------------------------

    def test_a_new_table_gets_its_own_unguessable_code_and_link(self):
        response = self._add("1", seats=4, note="ริมหน้าต่าง")
        self.assertEqual(response.status_code, 200, response.text)
        table = response.json()
        self.assertGreaterEqual(len(table["code"]), 16)
        self.assertEqual(table["link"], f"/t/{table['code']}?shop=main")
        self.assertEqual(table["seats"], 4)
        self.assertTrue(table["active"])
        second = self._add("2").json()
        self.assertNotEqual(second["code"], table["code"])

    def test_the_same_table_cannot_be_added_twice(self):
        self.assertEqual(self._add("1").status_code, 200)
        duplicate = self._add("1")
        self.assertEqual(duplicate.status_code, 409)
        self.assertIn("มีโต๊ะ 1 อยู่แล้ว", duplicate.json()["detail"])

    def test_a_table_name_the_furniture_cannot_carry_is_refused(self):
        for name in ("", "   ", "x" * 25, "โต๊ะ/1"):
            with self.subTest(name=name):
                self.assertEqual(self._add(name).status_code, 400)

    def test_only_a_manager_may_see_or_change_the_register(self):
        self._add("1")
        self.assertEqual(self.guest.get("/api/tables?branch_id=1").status_code, 401)
        self.assertEqual(self.guest.post("/api/tables",
                                         json={"branch_id": 1, "table_no": "9"}).status_code, 401)
        self.assertEqual(len(self.manager.get("/api/tables?branch_id=1").json()["tables"]), 1)

    # ---- scanning --------------------------------------------------------

    def test_scanning_a_sticker_hands_out_a_fresh_short_lived_token(self):
        code = self._add("1").json()["code"]
        response, token = self._scan(code)
        self.assertEqual(response.status_code, 303)
        location = response.headers["location"]
        self.assertIn("shop=main", location)
        # The page needs the table and branch spelled out; the token proves them.
        self.assertIn("table=1", location)
        self.assertIn("branch_id=1", location)
        self.assertTrue(token)
        # The token works, and only for the table the sticker is stuck to.
        self.assertEqual(self._order(token, "ORD-1").status_code, 200)
        wrong_table = self.guest.get("/api/orders?branch_id=1&table_no=2",
                                     headers={"X-Table-Token": token})
        self.assertEqual(wrong_table.status_code, 403)

    def test_two_scans_of_the_same_sticker_both_work(self):
        code = self._add("1").json()["code"]
        _, first = self._scan(code)
        _, second = self._scan(code)
        self.assertEqual(self._order(first, "ORD-1").status_code, 200)
        self.assertEqual(self._order(second, "ORD-2").status_code, 200)

    def test_a_token_lives_hours_not_a_month(self):
        code = self._add("1").json()["code"]
        _, token = self._scan(code)
        import base64
        import json
        payload = json.loads(base64.urlsafe_b64decode(
            token.split(".")[0] + "=" * (-len(token.split(".")[0]) % 4)))
        import time
        self.assertLessEqual(payload["e"] - int(time.time()), server.TABLE_SCAN_TTL_SECONDS + 5)
        self.assertEqual(payload["t"], "1")

    def test_a_code_that_was_never_issued_is_refused(self):
        response = self.guest.get("/t/" + "z" * 22 + "?shop=main", follow_redirects=False)
        self.assertEqual(response.status_code, 404)
        self.assertIn("ลิงก์โต๊ะไม่ถูกต้อง", response.text)

    def test_a_revoked_sticker_says_so_and_can_be_brought_back(self):
        code = self._add("1").json()["code"]
        self.assertEqual(self.manager.patch("/api/tables/1",
                                            json={"branch_id": 1, "active": False}).status_code, 200)
        blocked = self.guest.get(f"/t/{code}?shop=main", follow_redirects=False)
        self.assertEqual(blocked.status_code, 410)
        self.assertIn("ถูกยกเลิกแล้ว", blocked.text)
        # Revoking keeps the code, so the paper on the table still works after.
        self.assertEqual(self.manager.patch("/api/tables/1",
                                            json={"branch_id": 1, "active": True}).status_code, 200)
        self.assertEqual(self._scan(code)[0].status_code, 303)

    def test_reissuing_kills_the_old_sticker_and_leaves_other_tables_alone(self):
        first = self._add("1").json()
        other = self._add("2").json()
        fresh = self.manager.post("/api/tables/1/reissue?branch_id=1")
        self.assertEqual(fresh.status_code, 200, fresh.text)
        self.assertNotEqual(fresh.json()["code"], first["code"])
        self.assertEqual(self.guest.get(f"/t/{first['code']}?shop=main",
                                        follow_redirects=False).status_code, 404)
        self.assertEqual(self._scan(fresh.json()["code"])[0].status_code, 303)
        self.assertEqual(self._scan(other["code"])[0].status_code, 303)

    def test_deleting_a_table_stops_its_sticker(self):
        code = self._add("1").json()["code"]
        self.assertEqual(self.manager.delete("/api/tables/1?branch_id=1").status_code, 200)
        self.assertEqual(self.guest.get(f"/t/{code}?shop=main",
                                        follow_redirects=False).status_code, 404)
        self.assertEqual(self.manager.delete("/api/tables/1?branch_id=1").status_code, 404)

    def test_without_the_qr_key_no_sticker_can_be_scanned(self):
        code = self._add("1").json()["code"]
        with patch.object(server, "TABLE_QR_SECRET", ""):
            self.assertEqual(self.guest.get(f"/t/{code}?shop=main",
                                            follow_redirects=False).status_code, 503)

    # ---- the guest settles the bill --------------------------------------

    def test_a_guest_with_the_table_token_can_read_only_that_table_bill(self):
        code = self._add("1").json()["code"]
        self._add("2")
        _, token = self._scan(code)
        self._order(token, "ORD-1", qty=2)
        bill = self.guest.get("/api/orders?branch_id=1&table_no=1", headers={"X-Table-Token": token})
        self.assertEqual(bill.status_code, 200, bill.text)
        orders = bill.json()["orders"]
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0]["total_amount"], 100)
        self.assertEqual(self.guest.get("/api/orders?branch_id=1").status_code, 401)

    def test_a_guest_pays_their_own_bill_and_no_cashier_is_recorded(self):
        code = self._add("1").json()["code"]
        _, token = self._scan(code)
        self._order(token, "ORD-1")
        with patch.object(server, "verify_bank_slip", return_value="BANK-REF-1"), \
             patch.dict(server.os.environ, {"EASYSLIP_API_KEY": "test-key"}):
            response = self.guest.post("/api/payments/close-table",
                                       headers={"X-Table-Token": token},
                                       json={"event_id": "pay-1", "branch_id": 1, "table_no": "1",
                                             "order_nos": ["ORD-1"], "amount": 50,
                                             "slip_image": "data:image/png;base64,AAAA"})
        self.assertEqual(response.status_code, 200, response.text)
        with sqlite3.connect(server.DB_PATH) as conn:
            row = conn.execute("SELECT closed_by_staff_id,total_amount FROM pos_orders"
                               " WHERE order_no='ORD-1'").fetchone()
            status = conn.execute("SELECT status FROM order_events WHERE order_no='ORD-1'").fetchone()
        self.assertIsNone(row[0])      # nobody rang it up
        self.assertEqual(row[1], 50)
        self.assertEqual(status[0], "paid")

    def test_a_guest_cannot_pay_off_another_table_bill(self):
        first = self._add("1").json()["code"]
        self._add("2")
        _, token = self._scan(first)
        self._order(token, "ORD-1")
        # An order on table 2, opened by staff.
        self.manager.post("/api/orders", json={
            "event_id": "evt-2", "order_no": "ORD-2", "branch_id": 1, "table_no": "2",
            "total_amount": 50, "items": [{"id": "M001", "name": "ชาเย็น", "price": 50, "qty": 1}]})
        with patch.object(server, "verify_bank_slip", return_value="BANK-REF-2") as verify, \
             patch.dict(server.os.environ, {"EASYSLIP_API_KEY": "test-key"}):
            response = self.guest.post("/api/payments/close-table",
                                       headers={"X-Table-Token": token},
                                       json={"event_id": "pay-2", "branch_id": 1, "table_no": "2",
                                             "order_nos": ["ORD-2"], "amount": 50,
                                             "slip_image": "data:image/png;base64,AAAA"})
        self.assertEqual(response.status_code, 403)
        verify.assert_not_called()

    def test_a_stranger_with_no_token_cannot_pay_anything_off(self):
        code = self._add("1").json()["code"]
        _, token = self._scan(code)
        self._order(token, "ORD-1")
        with patch.object(server, "verify_bank_slip") as verify, \
             patch.dict(server.os.environ, {"EASYSLIP_API_KEY": "test-key"}):
            response = self.guest.post("/api/payments/close-table",
                                       json={"event_id": "pay-3", "branch_id": 1, "table_no": "1",
                                             "order_nos": ["ORD-1"], "amount": 50,
                                             "slip_image": "data:image/png;base64,AAAA"})
        self.assertEqual(response.status_code, 401)
        verify.assert_not_called()

    def test_sending_the_same_slip_twice_closes_the_bill_once(self):
        code = self._add("1").json()["code"]
        _, token = self._scan(code)
        self._order(token, "ORD-1")
        body = {"event_id": "pay-4", "branch_id": 1, "table_no": "1",
                "order_nos": ["ORD-1"], "amount": 50, "slip_image": "data:image/png;base64,AAAA"}
        with patch.object(server, "verify_bank_slip", return_value="BANK-REF-4"), \
             patch.dict(server.os.environ, {"EASYSLIP_API_KEY": "test-key"}):
            first = self.guest.post("/api/payments/close-table",
                                    headers={"X-Table-Token": token}, json=body)
            second = self.guest.post("/api/payments/close-table",
                                     headers={"X-Table-Token": token}, json=body)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertTrue(second.json()["existing"])
        with sqlite3.connect(server.DB_PATH) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM pos_orders").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
