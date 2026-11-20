"""กะการขายและลิ้นชักเงินสด

ร้านรู้มาตลอดว่าขายอะไรไป แต่ไม่เคยรู้ว่าในลิ้นชักมีเงินเท่าไหร่จริง ๆ
ส่วนต่างของสองอย่างนี้คือที่เดียวที่ร้านจะรู้ว่าเงินหาย
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import line_pos_server as server
import poswai_shifts as shifts


class ShiftCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.directory.cleanup)
        server.DB_PATH = Path(self.directory.name) / "shifts.db"
        server.PREVIEW_ONLY = False
        server.BOOTSTRAP_MANAGER_PIN = ""
        server.TABLE_QR_SECRET = "c" * 48
        server.init_db()
        conn = sqlite3.connect(server.DB_PATH)
        with conn:
            conn.execute("INSERT INTO branches(id,name) VALUES(1,'Test')")
            conn.execute("INSERT INTO branches(id,name) VALUES(2,'Second')")
            for staff_id, role in ((1, "owner"), (2, "cashier"), (3, "kitchen")):
                conn.execute("INSERT INTO staffs(id,branch_id,name,role,pin_code_hash)"
                             " VALUES(?,1,?,?,?)",
                             (staff_id, role, role, server.hash_pin(f"secure-pin-{role}")))
        conn.close()

    def signed_in(self, staff_id=2, role="cashier"):
        client = TestClient(server.app)
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        self.assertEqual(client.post("/api/auth/login",
                                     json={"staff_id": staff_id, "pin": f"secure-pin-{role}"}).status_code, 200)
        return client

    def sell_for_cash(self, amount, *, method="เงินสด (Cash)", branch_id=1):
        """A paid bill, written straight in: the till's own route needs a menu,
        a table and a queue number, none of which this is about.

        Stamped to the millisecond exactly as the real till stamps it, so the
        shift boundary is tested the way it actually behaves.
        """
        with sqlite3.connect(server.DB_PATH) as conn:
            conn.execute("INSERT INTO pos_orders (branch_id, order_no, closed_by_staff_id,"
                         " total_amount, net_amount, payment_method, closed_at)"
                         " VALUES (?,?,?,?,?,?,strftime('%Y-%m-%d %H:%M:%f','now'))",
                         (branch_id, f"ORD-{amount}-{method}-{branch_id}", 2, amount, amount, method))


class OpeningAndClosing(ShiftCase):
    def test_no_shift_is_open_to_begin_with(self):
        answer = self.signed_in().get("/api/shifts/current?branch_id=1")
        self.assertEqual(answer.status_code, 200)
        self.assertIsNone(answer.json()["shift"])

    def test_a_shift_opens_on_the_float_that_is_in_the_drawer(self):
        till = self.signed_in()
        opened = till.post("/api/shifts/open", json={"branch_id": 1, "opening": 1000})
        self.assertEqual(opened.status_code, 200, opened.text)
        shift = opened.json()["shift"]
        self.assertEqual(shift["opening"], 1000)
        self.assertEqual(shift["expected"], 1000)
        self.assertEqual(shift["status"], "open")

    def test_a_second_shift_cannot_open_on_top_of_the_first(self):
        till = self.signed_in()
        till.post("/api/shifts/open", json={"branch_id": 1, "opening": 1000})
        again = till.post("/api/shifts/open", json={"branch_id": 1, "opening": 500})
        self.assertEqual(again.status_code, 409)

    def test_two_branches_each_keep_their_own_drawer(self):
        """One open shift per branch, not one for the whole shop."""
        with sqlite3.connect(server.DB_PATH) as conn:
            shifts.init_shifts(conn)
            first = shifts.open_shift(conn, 1, 2, 1000)
            second = shifts.open_shift(conn, 2, 2, 2000)
            self.assertNotEqual(first["id"], second["id"])
            self.assertEqual(shifts.current_shift(conn, 1)["opening"], 1000)
            self.assertEqual(shifts.current_shift(conn, 2)["opening"], 2000)
            with self.assertRaises(shifts.ShiftError):
                shifts.open_shift(conn, 1, 2, 500)

    def test_a_cashier_only_opens_the_drawer_of_their_own_branch(self):
        self.assertEqual(self.signed_in().post("/api/shifts/open",
                                               json={"branch_id": 2, "opening": 1000}).status_code, 403)

    def test_cash_sales_during_the_shift_are_expected_in_the_drawer(self):
        till = self.signed_in()
        till.post("/api/shifts/open", json={"branch_id": 1, "opening": 1000})
        self.sell_for_cash(250)
        shift = till.get("/api/shifts/current?branch_id=1").json()["shift"]
        self.assertEqual(shift["cash_sales"], 250)
        self.assertEqual(shift["expected"], 1250)

    def test_a_transfer_is_money_in_the_bank_not_in_the_drawer(self):
        """Counting it here would make every drawer look short by the day's
        transfers."""
        till = self.signed_in()
        till.post("/api/shifts/open", json={"branch_id": 1, "opening": 1000})
        self.sell_for_cash(250, method="พร้อมเพย์ (ยืนยันโดยพนักงาน)")
        shift = till.get("/api/shifts/current?branch_id=1").json()["shift"]
        self.assertEqual(shift["cash_sales"], 0)
        self.assertEqual(shift["expected"], 1000)
        # It still counts as something the shift sold.
        self.assertEqual(shift["takings"], 250)

    def test_a_sale_from_before_the_shift_opened_is_not_this_drawer(self):
        self.sell_for_cash(500)
        till = self.signed_in()
        till.post("/api/shifts/open", json={"branch_id": 1, "opening": 1000})
        self.assertEqual(till.get("/api/shifts/current?branch_id=1").json()["shift"]["expected"], 1000)

    def test_closing_records_what_was_counted_beside_what_was_expected(self):
        till = self.signed_in()
        till.post("/api/shifts/open", json={"branch_id": 1, "opening": 1000})
        self.sell_for_cash(250)
        closed = till.post("/api/shifts/close", json={"branch_id": 1, "counted": 1250})
        self.assertEqual(closed.status_code, 200, closed.text)
        shift = closed.json()["shift"]
        self.assertEqual(shift["status"], "closed")
        self.assertEqual(shift["expected"], 1250)
        self.assertEqual(shift["counted"], 1250)
        self.assertEqual(shift["difference"], 0)

    def test_a_drawer_that_is_short_stays_short_on_the_record(self):
        """A shift 200 baht short is a fact the owner needs to see, not a
        number to be quietly adjusted away."""
        till = self.signed_in()
        till.post("/api/shifts/open", json={"branch_id": 1, "opening": 1000})
        self.sell_for_cash(250)
        shift = till.post("/api/shifts/close",
                          json={"branch_id": 1, "counted": 1050}).json()["shift"]
        self.assertEqual(shift["difference"], -200)

    def test_a_drawer_with_too_much_in_it_is_recorded_the_same_way(self):
        till = self.signed_in()
        till.post("/api/shifts/open", json={"branch_id": 1, "opening": 1000})
        shift = till.post("/api/shifts/close",
                          json={"branch_id": 1, "counted": 1100}).json()["shift"]
        self.assertEqual(shift["difference"], 100)

    def test_a_closed_shift_does_not_move_when_later_sales_arrive(self):
        till = self.signed_in()
        till.post("/api/shifts/open", json={"branch_id": 1, "opening": 1000})
        till.post("/api/shifts/close", json={"branch_id": 1, "counted": 900})
        self.sell_for_cash(400)   # the next shift's money
        past = till.get("/api/shifts/current?branch_id=1").json()["shift"]
        self.assertIsNone(past)
        owner = self.signed_in(1, "owner")
        history = owner.get("/api/shifts?branch_id=1").json()["shifts"]
        self.assertEqual(history[0]["difference"], -100)

    def test_closing_with_no_shift_open_is_refused(self):
        self.assertEqual(self.signed_in().post("/api/shifts/close",
                                               json={"branch_id": 1, "counted": 0}).status_code, 409)

    def test_a_new_shift_may_open_after_the_last_one_closed(self):
        till = self.signed_in()
        till.post("/api/shifts/open", json={"branch_id": 1, "opening": 1000})
        till.post("/api/shifts/close", json={"branch_id": 1, "counted": 1000})
        self.assertEqual(till.post("/api/shifts/open",
                                   json={"branch_id": 1, "opening": 500}).status_code, 200)


class TheDrawerInBetween(ShiftCase):
    def opened(self):
        till = self.signed_in()
        till.post("/api/shifts/open", json={"branch_id": 1, "opening": 1000})
        return till

    def test_money_put_in_raises_what_the_drawer_should_hold(self):
        till = self.opened()
        answer = till.post("/api/shifts/cash",
                           json={"branch_id": 1, "kind": "in", "amount": 500, "reason": "เติมเงินทอน"})
        self.assertEqual(answer.status_code, 200, answer.text)
        self.assertEqual(answer.json()["shift"]["expected"], 1500)

    def test_money_taken_out_lowers_it(self):
        till = self.opened()
        shift = till.post("/api/shifts/cash",
                          json={"branch_id": 1, "kind": "out", "amount": 300,
                                "reason": "นำไปฝากธนาคาร"}).json()["shift"]
        self.assertEqual(shift["expected"], 700)
        self.assertEqual(shift["cash_out"], 300)

    def test_paying_for_something_out_of_the_drawer_is_recorded_as_spending(self):
        till = self.opened()
        shift = till.post("/api/shifts/cash",
                          json={"branch_id": 1, "kind": "expense", "amount": 120,
                                "reason": "ซื้อน้ำแข็ง"}).json()["shift"]
        self.assertEqual(shift["expected"], 880)
        self.assertEqual(shift["movements"][0]["reason"], "ซื้อน้ำแข็ง")

    def test_money_cannot_leave_the_drawer_without_a_reason(self):
        """"Where did the 500 go" is the question this table exists to answer."""
        till = self.opened()
        self.assertEqual(till.post("/api/shifts/cash",
                                   json={"branch_id": 1, "kind": "out", "amount": 500}).status_code, 400)

    def test_money_put_in_needs_no_reason(self):
        till = self.opened()
        self.assertEqual(till.post("/api/shifts/cash",
                                   json={"branch_id": 1, "kind": "in", "amount": 500}).status_code, 200)

    def test_an_invented_kind_of_movement_is_refused(self):
        till = self.opened()
        self.assertEqual(till.post("/api/shifts/cash",
                                   json={"branch_id": 1, "kind": "ยืม", "amount": 500,
                                         "reason": "x"}).status_code, 400)

    def test_zero_and_negative_amounts_are_refused(self):
        till = self.opened()
        for amount in (0, -100):
            self.assertEqual(till.post("/api/shifts/cash",
                                       json={"branch_id": 1, "kind": "in",
                                             "amount": amount}).status_code, 400, amount)

    def test_nothing_can_be_recorded_before_a_shift_is_open(self):
        self.assertEqual(self.signed_in().post("/api/shifts/cash",
                                               json={"branch_id": 1, "kind": "in",
                                                     "amount": 100}).status_code, 409)

    def test_the_whole_drawer_adds_up(self):
        till = self.opened()
        self.sell_for_cash(250)
        till.post("/api/shifts/cash", json={"branch_id": 1, "kind": "in", "amount": 200})
        till.post("/api/shifts/cash", json={"branch_id": 1, "kind": "expense",
                                            "amount": 120, "reason": "น้ำแข็ง"})
        # 1000 float + 250 sold - 120 spent + 200 put in
        self.assertEqual(till.get("/api/shifts/current?branch_id=1").json()["shift"]["expected"], 1330)


class WhoMayTouchIt(ShiftCase):
    def test_the_kitchen_cannot_open_or_count_the_drawer(self):
        kitchen = self.signed_in(3, "kitchen")
        self.assertEqual(kitchen.post("/api/shifts/open",
                                      json={"branch_id": 1, "opening": 1000}).status_code, 403)

    def test_a_stranger_cannot_read_the_drawer(self):
        with TestClient(server.app) as stranger:
            self.assertEqual(stranger.get("/api/shifts/current?branch_id=1").status_code, 401)

    def test_a_cashier_cannot_read_past_shifts(self):
        """Yesterday's short drawer is the owner's business, not the next
        cashier's."""
        self.assertEqual(self.signed_in().get("/api/shifts?branch_id=1").status_code, 403)

    def test_the_owner_can(self):
        self.assertEqual(self.signed_in(1, "owner").get("/api/shifts?branch_id=1").status_code, 200)


class MoneyMaths(unittest.TestCase):
    def test_the_sign_of_every_kind_of_movement_is_decided(self):
        self.assertEqual(set(shifts.MOVEMENT_SIGN), set(shifts.MOVEMENT_KINDS))


if __name__ == "__main__":
    unittest.main()
