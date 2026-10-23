"""Closing a bill on a transfer a member of staff saw arrive.

The shop has no slip-checking subscription. Without this, a customer who paid
by transfer could only be rung up as cash, which quietly corrupts both the
cash drawer count and the payment-method report. So the till records what
really happened: a transfer, confirmed by a named person, with no pretence
that any machine verified it.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import line_pos_server as server

TRANSFER = "พร้อมเพย์ (ยืนยันโดยพนักงาน)"
CASH = "เงินสด (Cash)"


class ManualPaymentTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.folder.cleanup)
        for item in (patch.object(server, "DB_PATH", Path(self.folder.name) / "pay.db"),
                     patch.object(server, "PREVIEW_ONLY", False),
                     patch.object(server, "BOOTSTRAP_MANAGER_PIN", "")):
            item.start()
            self.addCleanup(item.stop)
        server.init_db()
        with sqlite3.connect(server.DB_PATH) as conn:
            conn.execute("INSERT INTO branches(id,name) VALUES(1,'One')")
            for staff_id, role in ((1, "manager"), (2, "cashier"), (3, "kitchen")):
                conn.execute("INSERT INTO staffs(id,branch_id,name,role,pin_code_hash) VALUES(?,1,?,?,?)",
                             (staff_id, role, role, server.hash_pin("secure-pin-" + role)))
            for number in ("O1", "O2", "O3"):
                conn.execute("INSERT INTO order_events(event_id,order_no,branch_id,table_no,total_amount)"
                             " VALUES(?,?,1,'T1',100)", ("c-" + number, number))

        self.cashier = TestClient(server.app)
        self.cashier.__enter__()
        self.addCleanup(lambda: self.cashier.__exit__(None, None, None))
        self.cashier.post("/api/auth/login", json={"staff_id": 2, "pin": "secure-pin-cashier"})
        self.kitchen = TestClient(server.app)
        self.kitchen.__enter__()
        self.addCleanup(lambda: self.kitchen.__exit__(None, None, None))
        self.kitchen.post("/api/auth/login", json={"staff_id": 3, "pin": "secure-pin-kitchen"})

    def _close(self, order_no, method, client=None, **extra):
        body = {"event_id": "pay-" + order_no, "order_no": order_no,
                "amount": 100, "method": method}
        body.update(extra)
        return (client or self.cashier).post("/api/payments/close", json=body)

    def _stored(self, order_no):
        with sqlite3.connect(server.DB_PATH) as conn:
            return conn.execute(
                "SELECT p.method, o.closed_by_staff_id, o.payment_method FROM payment_events p"
                " JOIN pos_orders o ON o.order_no=p.order_no WHERE p.order_no=?",
                (order_no,)).fetchone()

    def test_a_transfer_the_staff_saw_closes_the_bill(self):
        response = self._close("O1", TRANSFER)
        self.assertEqual(response.status_code, 200, response.text)
        method, closed_by, recorded = self._stored("O1")
        self.assertEqual(method, TRANSFER)
        self.assertEqual(recorded, TRANSFER)
        self.assertEqual(closed_by, 2)        # the person who pressed it

    def test_it_is_not_recorded_as_cash(self):
        self._close("O1", TRANSFER)
        self._close("O2", CASH)
        with sqlite3.connect(server.DB_PATH) as conn:
            methods = dict(conn.execute("SELECT order_no,payment_method FROM pos_orders"))
        self.assertEqual(methods["O1"], TRANSFER)
        self.assertEqual(methods["O2"], CASH)

    def test_a_manual_close_may_not_claim_a_verified_slip(self):
        response = self._close("O1", TRANSFER, slip_reference="MADE-UP-REF")
        self.assertEqual(response.status_code, 501)
        self.assertIsNone(self._stored("O1"))

    def test_channels_with_no_provider_behind_them_are_still_refused(self):
        for method in ("บัตรเครดิต/เดบิต (EDC)", "e-Wallet (TrueMoney/LINE Pay)",
                       "QR PromptPay (ตรวจสลิปแล้ว)"):
            with self.subTest(method=method):
                self.assertEqual(self._close("O1", method).status_code, 501)
        self.assertIsNone(self._stored("O1"))

    def test_the_amount_must_match_the_bill(self):
        response = self.cashier.post("/api/payments/close", json={
            "event_id": "pay-wrong", "order_no": "O1", "amount": 99, "method": TRANSFER})
        self.assertEqual(response.status_code, 409)

    def test_a_bill_cannot_be_closed_twice(self):
        self.assertEqual(self._close("O1", TRANSFER).status_code, 200)
        again = self.cashier.post("/api/payments/close", json={
            "event_id": "pay-again", "order_no": "O1", "amount": 100, "method": TRANSFER})
        self.assertEqual(again.status_code, 409)

    def test_sending_the_same_press_twice_closes_it_once(self):
        first = self._close("O1", TRANSFER)
        second = self._close("O1", TRANSFER)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        with sqlite3.connect(server.DB_PATH) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM pos_orders").fetchone()[0], 1)

    def test_the_kitchen_cannot_close_bills(self):
        self.assertEqual(self._close("O1", TRANSFER, client=self.kitchen).status_code, 403)

    def test_a_stranger_cannot_close_bills(self):
        with TestClient(server.app) as guest:
            self.assertEqual(guest.post("/api/payments/close", json={
                "event_id": "pay-x", "order_no": "O1", "amount": 100,
                "method": TRANSFER}).status_code, 401)


if __name__ == "__main__":
    unittest.main()
