"""Cancelling an unpaid bill and refunding a paid one, with the manager limits."""

import datetime
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import line_pos_server as server


class VoidAndRefundTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.folder.cleanup)
        for item in (patch.object(server, "DB_PATH", Path(self.folder.name) / "void.db"),
                     patch.object(server, "PREVIEW_ONLY", False),
                     patch.object(server, "BOOTSTRAP_MANAGER_PIN", ""),
                     patch.object(server, "VOID_CASHIER_MAX_AMOUNT", 200.0),
                     patch.object(server, "VOID_CASHIER_DAILY_LIMIT", 2)):
            item.start()
            self.addCleanup(item.stop)
        server.init_db()
        with sqlite3.connect(server.DB_PATH) as conn:
            conn.execute("INSERT INTO branches(id,name) VALUES(1,'One')")
            for staff_id, role in ((1, "manager"), (2, "cashier")):
                conn.execute("INSERT INTO staffs(id,branch_id,name,role,pin_code_hash) VALUES(?,1,?,?,?)",
                             (staff_id, role, role, server.hash_pin("secure-pin-" + role)))
            conn.execute("INSERT INTO commission_rules(branch_id,type,rate_percent) VALUES(1,'individual',0.03)")

        self.manager = TestClient(server.app)
        self.manager.__enter__()
        self.addCleanup(lambda: self.manager.__exit__(None, None, None))
        self.cashier = TestClient(server.app)
        self.cashier.__enter__()
        self.addCleanup(lambda: self.cashier.__exit__(None, None, None))
        self.manager.post("/api/auth/login", json={"staff_id": 1, "pin": "secure-pin-manager"})
        self.cashier.post("/api/auth/login", json={"staff_id": 2, "pin": "secure-pin-cashier"})

        self.assertEqual(self.manager.put("/api/inventory/ING-TEA",
                                          json={"branch_id": 1, "stock": 100}).status_code, 200)
        self.assertEqual(self.manager.put("/api/menu/TEA", json={"branch_id": 1, "name": "ชาเย็น",
            "price": 50, "station": "บาร์น้ำ", "bom": [{"ingId": "ING-TEA", "qty": 2}]}).status_code, 200)

    def _stock(self):
        items = self.manager.get("/api/inventory").json()["items"]
        return next(item["stock"] for item in items if item["id"] == "ING-TEA")

    def _open_order(self, order_no, qty=1):
        response = self.cashier.post("/api/orders", json={
            "event_id": f"evt-{order_no}", "order_no": order_no, "branch_id": 1, "table_no": "T1",
            "total_amount": 50 * qty,
            "items": [{"id": "TEA", "name": "ชาเย็น", "price": 50, "qty": qty, "bom": []}]})
        self.assertEqual(response.status_code, 200, response.text)
        return response

    def test_cashier_voids_a_small_unpaid_bill_and_stock_comes_back(self):
        self._open_order("B-1")
        self.assertEqual(self._stock(), 98)
        self.assertEqual(len(self.manager.get("/api/kds").json()["tickets"]), 1)

        voided = self.cashier.post("/api/orders/B-1/void",
                                   json={"event_id": "void-1", "reason": "ลูกค้าเปลี่ยนใจก่อนชงน้ำ"})
        self.assertEqual(voided.status_code, 200, voided.text)
        self.assertEqual(voided.json()["status"], "void")
        self.assertEqual(self._stock(), 100)
        self.assertEqual(self.manager.get("/api/kds").json()["tickets"], [])

        with sqlite3.connect(server.DB_PATH) as conn:
            row = conn.execute("SELECT kind,amount,reason,staff_id FROM order_cancellations "
                               "WHERE order_no='B-1'").fetchone()
        self.assertEqual(row, ("void", 50.0, "ลูกค้าเปลี่ยนใจก่อนชงน้ำ", 2))

        # Replaying the same event is harmless; a fresh one on a closed bill is not.
        replay = self.cashier.post("/api/orders/B-1/void",
                                   json={"event_id": "void-1", "reason": "ลูกค้าเปลี่ยนใจก่อนชงน้ำ"})
        self.assertEqual(replay.status_code, 200)
        self.assertTrue(replay.json()["existing"])
        self.assertEqual(self._stock(), 100)
        self.assertEqual(self.cashier.post("/api/orders/B-1/void",
                                           json={"event_id": "void-2", "reason": "กดซ้ำ"}).status_code, 409)

    def test_a_reason_is_required(self):
        self._open_order("B-2")
        self.assertEqual(self.cashier.post("/api/orders/B-2/void",
                                           json={"event_id": "void-3", "reason": "  "}).status_code, 400)
        self.assertEqual(self.cashier.post("/api/orders/B-2/void",
                                           json={"event_id": "void-4", "reason": "x" * 201}).status_code, 400)

    def test_big_bills_and_repeat_voids_need_a_manager(self):
        self._open_order("B-BIG", qty=5)  # 250 baht, over the cashier's ceiling
        blocked = self.cashier.post("/api/orders/B-BIG/void",
                                    json={"event_id": "void-5", "reason": "ลูกค้ายกเลิกทั้งโต๊ะ"})
        self.assertEqual(blocked.status_code, 403)
        self.assertIn("ผู้จัดการ", blocked.json()["detail"])
        self.assertEqual(self.manager.post("/api/orders/B-BIG/void",
                                           json={"event_id": "void-6", "reason": "ลูกค้ายกเลิกทั้งโต๊ะ"}).status_code, 200)

        for index in (1, 2):
            self._open_order(f"B-S{index}")
            self.assertEqual(self.cashier.post(f"/api/orders/B-S{index}/void",
                                               json={"event_id": f"void-s{index}", "reason": "กดผิดเมนู"}).status_code, 200)
        self._open_order("B-S3")
        over = self.cashier.post("/api/orders/B-S3/void", json={"event_id": "void-s3", "reason": "กดผิดเมนู"})
        self.assertEqual(over.status_code, 403)
        self.assertIn("ผู้จัดการ", over.json()["detail"])
        self.assertEqual(self.manager.post("/api/orders/B-S3/void",
                                           json={"event_id": "void-s4", "reason": "กดผิดเมนู"}).status_code, 200)

    def test_the_till_lists_closed_bills_so_a_refund_can_be_found(self):
        """/api/orders carries open bills only, so the refund list has its own endpoint."""
        self._open_order("B-SETTLED")
        self.assertEqual(self.cashier.get("/api/orders/settled").json()["orders"], [])
        self._pay("B-SETTLED")

        listed = self.cashier.get("/api/orders/settled")
        self.assertEqual(listed.status_code, 200, listed.text)
        row = listed.json()["orders"][0]
        self.assertEqual((row["order_no"], row["status"], row["table_no"]), ("B-SETTLED", "paid", "T1"))
        self.assertEqual(row["closed_by"], "cashier")
        self.assertEqual(row["refund_reason"], "")

        self.assertEqual(self.manager.post("/api/payments/B-SETTLED/refund",
                                           json={"event_id": "ref-list", "reason": "ลูกค้าได้อาหารผิด"}).status_code, 200)
        after = self.cashier.get("/api/orders/settled").json()["orders"][0]
        self.assertEqual(after["status"], "refunded")
        self.assertEqual(after["refund_reason"], "ลูกค้าได้อาหารผิด")
        # An open bill never appears here, and a guest never sees the list at all.
        self.assertNotIn("B-SETTLED-OPEN", [item["order_no"] for item in self.cashier.get("/api/orders/settled").json()["orders"]])
        self.assertEqual(TestClient(server.app).get("/api/orders/settled").status_code, 401)
        self.assertEqual(self.cashier.get("/api/orders/settled?limit=0").status_code, 400)

    def test_the_till_is_told_the_cashier_limits(self):
        limits = self.cashier.get("/api/config").json()["void_limits"]
        self.assertEqual((limits["max_amount"], limits["daily_limit"]), (200.0, 2))

    def _pay(self, order_no):
        paid = self.cashier.post("/api/payments/close", json={"event_id": f"pay-{order_no}", "order_no": order_no,
                                                              "amount": 50, "method": "เงินสด (Cash)"})
        self.assertEqual(paid.status_code, 200, paid.text)
        return paid

    def test_refund_is_manager_only_and_reverses_commission(self):
        self._open_order("B-3")
        self._pay("B-3")
        with sqlite3.connect(server.DB_PATH) as conn:
            earned = conn.execute("SELECT COALESCE(SUM(calculated_amount),0) FROM commission_records "
                                  "WHERE staff_id=2").fetchone()[0]
        self.assertGreater(earned, 0)

        self.assertEqual(self.cashier.post("/api/orders/B-3/void",
                                           json={"event_id": "void-7", "reason": "ลูกค้าขอคืนเงิน"}).status_code, 409)
        denied = self.cashier.post("/api/payments/B-3/refund",
                                   json={"event_id": "refund-1", "reason": "ลูกค้าขอคืนเงิน"})
        self.assertEqual(denied.status_code, 403)

        refunded = self.manager.post("/api/payments/B-3/refund",
                                     json={"event_id": "refund-1", "reason": "อาหารผิดรายการ"})
        self.assertEqual(refunded.status_code, 200, refunded.text)
        self.assertEqual(refunded.json()["status"], "refunded")
        self.assertEqual(refunded.json()["commission_entries_reversed"], 1)
        self.assertEqual(self._stock(), 100)

        with sqlite3.connect(server.DB_PATH) as conn:
            self.assertEqual(conn.execute("SELECT status FROM pos_orders WHERE order_no='B-3'").fetchone()[0],
                             "refunded")
            self.assertEqual(conn.execute("SELECT COALESCE(SUM(calculated_amount),0) FROM commission_records "
                                          "WHERE staff_id=2").fetchone()[0], 0)
        # The day's report drops the refunded bill from both sales and the pool.
        today = datetime.datetime.now(server.BANGKOK_TZ).date().isoformat()
        report = self.manager.get("/api/commissions", params={"work_date": today}).json()
        self.assertEqual((report["sales"], report["pool"]), (0, 0))

        replay = self.manager.post("/api/payments/B-3/refund",
                                   json={"event_id": "refund-1", "reason": "อาหารผิดรายการ"})
        self.assertTrue(replay.json()["existing"])
        self.assertEqual(self.manager.post("/api/payments/B-3/refund",
                                           json={"event_id": "refund-2", "reason": "กดซ้ำ"}).status_code, 409)

    def test_unpaid_bills_cannot_be_refunded(self):
        self._open_order("B-4")
        self.assertEqual(self.manager.post("/api/payments/B-4/refund",
                                           json={"event_id": "refund-3", "reason": "ยังไม่ได้รับเงิน"}).status_code, 409)
        self.assertEqual(self.manager.post("/api/payments/B-404/refund",
                                           json={"event_id": "refund-4", "reason": "ไม่มีบิลนี้"}).status_code, 404)

    def test_the_daily_ceiling_still_counts_voids_made_after_midnight(self):
        """Shop time, not UTC: a void at 00:30 belongs to the day that is starting.

        The audit rows carry SQLite's UTC timestamp, so a count that compared them
        with the Bangkok date missed every void made between midnight and 07:00 —
        the hours a late shift is open — and left the cashier without a ceiling.
        """
        early = datetime.datetime.now(server.BANGKOK_TZ).replace(hour=0, minute=30, second=0, microsecond=0)
        stored = early.astimezone(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        self.assertNotEqual(stored[:10], early.date().isoformat())  # the two dates really do differ
        with sqlite3.connect(server.DB_PATH) as conn:
            for index in range(server.VOID_CASHIER_DAILY_LIMIT):
                conn.execute("INSERT INTO order_events(event_id,order_no,branch_id,table_no,total_amount,status) "
                             "VALUES(?,?,1,'T1',50,'void')", (f"early-{index}", f"B-EARLY{index}"))
                conn.execute("INSERT INTO order_cancellations(event_id,order_no,branch_id,kind,amount,reason,"
                             "staff_id,created_at) VALUES(?,?,1,'void',50,'กดผิดเมนู',2,?)",
                             (f"void-early-{index}", f"B-EARLY{index}", stored))
        self._open_order("B-NIGHT")
        blocked = self.cashier.post("/api/orders/B-NIGHT/void",
                                    json={"event_id": "void-night", "reason": "ลูกค้ายกเลิก"})
        self.assertEqual(blocked.status_code, 403, blocked.text)
        self.assertIn("ผู้จัดการ", blocked.json()["detail"])
        self.assertEqual(self.manager.post("/api/orders/B-NIGHT/void",
                                           json={"event_id": "void-night-mgr", "reason": "ลูกค้ายกเลิก"}).status_code, 200)

    def test_managers_are_alerted_on_LINE_when_a_bill_is_cancelled(self):
        with sqlite3.connect(server.DB_PATH) as conn:
            conn.execute("UPDATE staffs SET line_user_id='U-manager' WHERE id=1")
        self._open_order("B-5")
        self.assertEqual(self.cashier.post("/api/orders/B-5/void",
                                           json={"event_id": "void-8", "reason": "ลูกค้าไม่รอ"}).status_code, 200)
        with sqlite3.connect(server.DB_PATH) as conn:
            message = conn.execute("SELECT recipient,message_json FROM line_notification_outbox "
                                   "WHERE event_key='cancel:void:B-5'").fetchone()
        self.assertEqual(message[0], "U-manager")
        self.assertIn("ลูกค้าไม่รอ", message[1])
        self.assertIn("B-5", message[1])


if __name__ == "__main__":
    unittest.main()
