"""Receipts queued by a till that cannot reach the printer.

The shop's till may be an iPhone, which cannot drive a USB or Bluetooth 58mm
printer at all. So the receipt is left here and collected by a small program
on the machine the printer is actually plugged into. What these tests care
about is that a receipt is never silently lost on the way.
"""

import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import line_pos_server as server


class PrintQueueTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.folder.cleanup)
        for item in (patch.object(server, "DB_PATH", Path(self.folder.name) / "print.db"),
                     patch.object(server, "PREVIEW_ONLY", False),
                     patch.object(server, "BOOTSTRAP_MANAGER_PIN", ""),
                     patch.object(server, "_prepared_databases", set())):
            item.start()
            self.addCleanup(item.stop)
        server.init_db()
        with sqlite3.connect(server.DB_PATH) as conn:
            conn.execute("INSERT INTO branches(id,name) VALUES(1,'One')")
            for staff_id, role in ((1, "manager"), (2, "cashier"), (3, "kitchen")):
                conn.execute("INSERT INTO staffs(id,branch_id,name,role,pin_code_hash)"
                             " VALUES(?,1,?,?,?)",
                             (staff_id, role, role, server.hash_pin("secure-pin-" + role)))
        self.manager = self._signed_in(1, "manager")
        self.cashier = self._signed_in(2, "cashier")
        self.agent = TestClient(server.app)
        self.agent.__enter__()
        self.addCleanup(lambda: self.agent.__exit__(None, None, None))

    def _signed_in(self, staff_id, role):
        client = TestClient(server.app)
        client.__enter__()
        self.addCleanup(lambda: client.__exit__(None, None, None))
        response = client.post("/api/auth/login", json={"staff_id": staff_id,
                                                        "pin": "secure-pin-" + role})
        self.assertEqual(response.status_code, 200, response.text)
        return client

    def _key(self, name="หน้าร้าน"):
        response = self.manager.post("/api/print/agents", json={"branch_id": 1, "name": name})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["key"]

    def _queue(self, body="ใบเสร็จ\nกะเพรา  50", title="ใบเสร็จ"):
        return self.cashier.post("/api/print/jobs",
                                 json={"branch_id": 1, "title": title, "body": body})

    # ------------------------------------------------------------------ the queue
    def test_a_receipt_waits_until_the_machine_with_the_printer_collects_it(self):
        key = self._key()
        queued = self._queue()
        self.assertEqual(queued.status_code, 200, queued.text)
        taken = self.agent.get("/api/print/next", headers={"X-Print-Key": key})
        self.assertEqual(taken.status_code, 200, taken.text)
        job = taken.json()["job"]
        self.assertEqual(job["title"], "ใบเสร็จ")
        self.assertIn("กะเพรา", job["body"])
        self.assertEqual(self.agent.post("/api/print/done", json={"job_id": job["job_id"]},
                                         headers={"X-Print-Key": key}).status_code, 200)
        after = self.agent.get("/api/print/next", headers={"X-Print-Key": key})
        self.assertIsNone(after.json()["job"])

    def test_a_job_taken_and_never_finished_comes_back(self):
        """A laptop that sleeps mid-receipt must not swallow the bill.

        The customer is still at the counter waiting for it, so the job goes
        back in the queue rather than sitting in 'taken' forever."""
        key = self._key()
        self._queue()
        first = self.agent.get("/api/print/next", headers={"X-Print-Key": key}).json()["job"]
        self.assertIsNotNone(first)
        self.assertIsNone(self.agent.get("/api/print/next",
                                         headers={"X-Print-Key": key}).json()["job"])
        with patch.object(server, "take_job", server.take_job), \
             patch("poswai_printing.time.time", return_value=time.time() + 600):
            again = self.agent.get("/api/print/next", headers={"X-Print-Key": key}).json()["job"]
        self.assertEqual(again["job_id"], first["job_id"])

    def test_receipts_come_out_in_the_order_they_were_rung_up(self):
        key = self._key()
        for table in ("โต๊ะ 1", "โต๊ะ 2", "โต๊ะ 3"):
            self._queue(body=f"บิล {table}", title=table)
        seen = []
        for _ in range(3):
            job = self.agent.get("/api/print/next", headers={"X-Print-Key": key}).json()["job"]
            seen.append(job["title"])
            self.agent.post("/api/print/done", json={"job_id": job["job_id"]},
                            headers={"X-Print-Key": key})
        self.assertEqual(seen, ["โต๊ะ 1", "โต๊ะ 2", "โต๊ะ 3"])

    # ------------------------------------------------------------------ the key
    def test_the_key_is_shown_once_and_never_stored_in_the_clear(self):
        key = self._key()
        listed = self.manager.get("/api/print/agents?branch_id=1").json()
        self.assertEqual(len(listed["agents"]), 1)
        self.assertNotIn("key", listed["agents"][0])
        with sqlite3.connect(server.DB_PATH) as conn:
            stored = conn.execute("SELECT key_hash FROM print_agents").fetchone()[0]
        self.assertNotIn(key, stored)

    def test_a_wrong_key_collects_nothing(self):
        self._key()
        self._queue()
        for key in ("", "not-a-key", "x" * 300):
            with self.subTest(key=key[:10]):
                response = self.agent.get("/api/print/next", headers={"X-Print-Key": key})
                self.assertEqual(response.status_code, 401)

    def test_a_deleted_agent_stops_collecting(self):
        key = self._key()
        agent_id = self.manager.get("/api/print/agents?branch_id=1").json()["agents"][0]["id"]
        self.assertEqual(self.manager.delete(f"/api/print/agents/{agent_id}?branch_id=1")
                         .status_code, 200)
        self.assertEqual(self.agent.get("/api/print/next",
                                        headers={"X-Print-Key": key}).status_code, 401)

    def test_only_a_manager_hands_out_keys(self):
        self.assertEqual(self.cashier.post("/api/print/agents", json={"branch_id": 1}).status_code,
                         403)
        self.assertEqual(self.agent.get("/api/print/agents?branch_id=1").status_code, 401)

    # ------------------------------------------------------------------ refusals
    def test_queueing_with_no_printer_set_up_says_so(self):
        response = self._queue()
        self.assertEqual(response.status_code, 409)
        self.assertIn("ยังไม่ได้ตั้งค่าเครื่องพิมพ์", response.json()["detail"])

    def test_an_empty_or_enormous_receipt_is_refused(self):
        self._key()
        for body in ("", "   ", "x" * 9000):
            with self.subTest(length=len(body)):
                self.assertEqual(self._queue(body=body).status_code, 400)

    def test_the_kitchen_screen_does_not_print_receipts(self):
        self._key()
        kitchen = self._signed_in(3, "kitchen")
        self.assertEqual(kitchen.post("/api/print/jobs",
                                      json={"branch_id": 1, "body": "บิล"}).status_code, 403)


class ReceiptRasterTest(unittest.TestCase):
    """What the agent beside the printer turns a receipt into.

    Thai is drawn rather than typed because these printers carry a Chinese
    character set and whichever Thai code page the factory felt like; a
    bitmap of real letters comes out right on all of them. The check is that
    the bytes decode back into the picture that went in — wrong bit order or
    a missed inversion prints a page of noise, which no amount of staring at
    the code reveals.
    """

    def setUp(self):
        try:
            from PIL import Image            # noqa: F401
        except ImportError:
            self.skipTest("Pillow is not installed")
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "print_agent", Path(__file__).with_name("print-agent.py"))
        self.agent = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.agent)
        self.font = next((path for path in self.agent.THAI_FONTS if Path(path).exists()), "")
        if not self.font:
            self.skipTest("no Thai font on this machine")

    def _decode(self, data):
        from PIL import Image
        start = data.index(bytes([0x1d, 0x76, 0x30, 0x00])) + 4
        width_bytes = data[start] | (data[start + 1] << 8)
        height = data[start + 2] | (data[start + 3] << 8)
        raster = data[start + 4:start + 4 + width_bytes * height]
        self.assertEqual(len(raster), width_bytes * height, "raster is the wrong length")
        return Image.frombytes("1", (width_bytes * 8, height),
                               bytes(byte ^ 0xFF for byte in raster))

    def test_thai_comes_out_as_thai_shaped_ink(self):
        picture = self._decode(self.agent.render("ขอบคุณที่ใช้บริการครับ", self.font))
        self.assertEqual(picture.width, self.agent.PAPER_DOTS)
        inked = picture.histogram()[0]
        self.assertGreater(inked, 200, "nothing was drawn")
        self.assertLess(inked, picture.width * picture.height // 2, "the paper came out black")

    def test_a_long_line_is_broken_rather_than_clipped(self):
        one_line = self._decode(self.agent.render("สั้น", self.font))
        wrapped = self._decode(self.agent.render("ก" * 80, self.font))
        self.assertGreater(wrapped.height, one_line.height * 2)

    def test_the_slip_ends_with_enough_paper_to_tear(self):
        data = self.agent.render("บิล", self.font)
        self.assertTrue(data.startswith(bytes([0x1b, 0x40])), "the printer is not reset first")
        self.assertGreaterEqual(data.count(bytes([0x0a])), 3,
                                "no room left to tear the slip off")


if __name__ == "__main__":
    unittest.main()
