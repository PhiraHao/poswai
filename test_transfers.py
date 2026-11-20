"""ใบโอนของข้ามสาขา

เดิมโอนของข้ามสาขาแล้วของย้ายทันทีทั้งสองฝั่ง เหมือนรถส่งของที่ไม่มีวันเสีย
พอกล่องหายระหว่างทาง บัญชีทั้งสองสาขาบอกว่าของถึงแล้ว แล้วไปโผล่อีกหลาย
สัปดาห์เป็นยอดนับสต็อกที่ไม่มีใครอธิบายได้
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import line_pos_server as server


class TransferCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.directory.cleanup)
        server.DB_PATH = Path(self.directory.name) / "transfers.db"
        server.PREVIEW_ONLY = False
        server.BOOTSTRAP_MANAGER_PIN = ""
        server.TABLE_QR_SECRET = "g" * 48
        server.init_db()
        conn = sqlite3.connect(server.DB_PATH)
        with conn:
            conn.execute("INSERT INTO branches(id,name) VALUES(1,'สาขาหนึ่ง')")
            conn.execute("INSERT INTO branches(id,name) VALUES(2,'สาขาสอง')")
            conn.execute("INSERT INTO staffs(id,branch_id,name,role,pin_code_hash)"
                         " VALUES(1,1,'เจ้าของ','owner',?)", (server.hash_pin("secure-pin-owner"),))
            conn.execute("INSERT INTO staffs(id,branch_id,name,role,pin_code_hash)"
                         " VALUES(2,1,'ผจก.หนึ่ง','manager',?)", (server.hash_pin("secure-pin-one"),))
            conn.execute("INSERT INTO staffs(id,branch_id,name,role,pin_code_hash)"
                         " VALUES(3,2,'ผจก.สอง','manager',?)", (server.hash_pin("secure-pin-two"),))
            conn.execute("INSERT INTO inventory(branch_id,ingredient_id,stock,unit)"
                         " VALUES(1,'PORK',100,'กก.')")
            conn.execute("INSERT INTO inventory(branch_id,ingredient_id,stock,unit)"
                         " VALUES(2,'PORK',5,'กก.')")
        conn.close()

    def signed_in(self, staff_id=1, pin="secure-pin-owner"):
        client = TestClient(server.app)
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        self.assertEqual(client.post("/api/auth/login",
                                     json={"staff_id": staff_id, "pin": pin}).status_code, 200)
        return client

    def stock(self, branch_id, ingredient="PORK"):
        with sqlite3.connect(server.DB_PATH) as conn:
            row = conn.execute("SELECT stock FROM inventory WHERE branch_id=? AND ingredient_id=?",
                               (branch_id, ingredient)).fetchone()
        return row[0] if row else 0

    def sent(self, client=None, quantity=20):
        client = client or self.signed_in()
        answer = client.post("/api/transfers", json={
            "from_branch_id": 1, "to_branch_id": 2,
            "lines": [{"ingredient_id": "PORK", "quantity": quantity}]})
        self.assertEqual(answer.status_code, 200, answer.text)
        return client, answer.json()


class SendingIt(TransferCase):
    def test_a_transfer_is_numbered_and_names_both_branches(self):
        _, note = self.sent()
        self.assertTrue(note["number"].startswith("TR-"))
        self.assertEqual(note["status"], "sent")
        self.assertEqual(note["from_branch"], "สาขาหนึ่ง")
        self.assertEqual(note["to_branch"], "สาขาสอง")

    def test_sending_moves_no_stock_yet(self):
        """Stock moves when the far branch says what arrived, because that is
        the only moment anyone actually knows."""
        before_one, before_two = self.stock(1), self.stock(2)
        self.sent()
        self.assertEqual(self.stock(1), before_one)
        self.assertEqual(self.stock(2), before_two)

    def test_a_branch_cannot_send_more_than_it_has(self):
        """Refused while the person can still put the box back."""
        owner = self.signed_in()
        refused = owner.post("/api/transfers", json={
            "from_branch_id": 1, "to_branch_id": 2,
            "lines": [{"ingredient_id": "PORK", "quantity": 500}]})
        self.assertEqual(refused.status_code, 409)

    def test_sending_to_itself_is_refused(self):
        owner = self.signed_in()
        self.assertEqual(owner.post("/api/transfers", json={
            "from_branch_id": 1, "to_branch_id": 1,
            "lines": [{"ingredient_id": "PORK", "quantity": 1}]}).status_code, 400)

    def test_a_branch_that_does_not_exist_is_refused(self):
        owner = self.signed_in()
        self.assertEqual(owner.post("/api/transfers", json={
            "from_branch_id": 1, "to_branch_id": 99,
            "lines": [{"ingredient_id": "PORK", "quantity": 1}]}).status_code, 404)

    def test_the_same_ingredient_twice_in_one_note_is_refused(self):
        owner = self.signed_in()
        self.assertEqual(owner.post("/api/transfers", json={
            "from_branch_id": 1, "to_branch_id": 2,
            "lines": [{"ingredient_id": "PORK", "quantity": 1},
                      {"ingredient_id": "PORK", "quantity": 2}]}).status_code, 400)

    def test_both_branches_see_the_note(self):
        self.sent()
        for staff_id, pin, branch in ((2, "secure-pin-one", 1), (3, "secure-pin-two", 2)):
            client = self.signed_in(staff_id, pin)
            seen = client.get(f"/api/transfers?branch_id={branch}").json()["transfers"]
            self.assertEqual(len(seen), 1, branch)


class ReceivingIt(TransferCase):
    def far_branch(self):
        return self.signed_in(3, "secure-pin-two")

    def test_confirming_in_full_moves_all_of_it(self):
        _, note = self.sent()
        before_one, before_two = self.stock(1), self.stock(2)
        far = self.far_branch()
        got = far.post(f"/api/transfers/{note['id']}/receive",
                       json={"branch_id": 2, "received": {}})
        self.assertEqual(got.status_code, 200, got.text)
        self.assertEqual(got.json()["status"], "received")
        self.assertEqual(self.stock(1), before_one - 20)
        self.assertEqual(self.stock(2), before_two + 20)

    def test_only_what_arrived_moves_and_the_rest_is_flagged(self):
        """Ten sent, eight arrived: the two stay on the sending branch's books
        and the note says they are missing. Nothing is written off."""
        _, note = self.sent(quantity=10)
        before_one, before_two = self.stock(1), self.stock(2)
        got = self.far_branch().post(f"/api/transfers/{note['id']}/receive",
                                     json={"branch_id": 2, "received": {"PORK": 8}})
        self.assertEqual(got.status_code, 200, got.text)
        self.assertEqual(self.stock(1), before_one - 8)
        self.assertEqual(self.stock(2), before_two + 8)
        line = got.json()["lines"][0]
        self.assertEqual(line["quantity"], 10)
        self.assertEqual(line["received_quantity"], 8)
        self.assertEqual(line["missing"], 2)
        self.assertTrue(got.json()["shortfall"])

    def test_a_box_that_never_arrived_moves_nothing(self):
        _, note = self.sent()
        before_one, before_two = self.stock(1), self.stock(2)
        got = self.far_branch().post(f"/api/transfers/{note['id']}/receive",
                                     json={"branch_id": 2, "received": {"PORK": 0}})
        self.assertEqual(got.status_code, 200, got.text)
        self.assertEqual(self.stock(1), before_one)
        self.assertEqual(self.stock(2), before_two)
        self.assertEqual(got.json()["lines"][0]["missing"], 20)

    def test_more_cannot_arrive_than_was_sent(self):
        _, note = self.sent()
        refused = self.far_branch().post(f"/api/transfers/{note['id']}/receive",
                                         json={"branch_id": 2, "received": {"PORK": 50}})
        self.assertEqual(refused.status_code, 400)

    def test_the_sending_branch_cannot_sign_for_its_own_delivery(self):
        """Which is the whole point of two branches confirming."""
        _, note = self.sent()
        near = self.signed_in(2, "secure-pin-one")
        refused = near.post(f"/api/transfers/{note['id']}/receive",
                            json={"branch_id": 2, "received": {}})
        self.assertEqual(refused.status_code, 403)

    def test_the_owner_may_confirm_either_branch(self):
        owner, note = self.sent()
        self.assertEqual(owner.post(f"/api/transfers/{note['id']}/receive",
                                    json={"branch_id": 2, "received": {}}).status_code, 200)

    def test_confirming_twice_does_not_move_the_stock_again(self):
        _, note = self.sent()
        far = self.far_branch()
        far.post(f"/api/transfers/{note['id']}/receive", json={"branch_id": 2, "received": {}})
        after = self.stock(2)
        again = far.post(f"/api/transfers/{note['id']}/receive",
                         json={"branch_id": 2, "received": {}})
        self.assertEqual(again.status_code, 409)
        self.assertEqual(self.stock(2), after)

    def test_an_ingredient_not_on_the_note_cannot_be_received(self):
        _, note = self.sent()
        refused = self.far_branch().post(f"/api/transfers/{note['id']}/receive",
                                         json={"branch_id": 2, "received": {"RICE": 5}})
        self.assertEqual(refused.status_code, 400)

    def test_the_move_goes_through_the_shared_ledger(self):
        owner, note = self.sent()
        self.far_branch().post(f"/api/transfers/{note['id']}/receive",
                               json={"branch_id": 2, "received": {}})
        moves = owner.get("/api/inventory/movements?branch_id=1").json()["items"]
        mine = [m for m in moves if note["number"] in (m.get("note") or "")]
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0]["action"], "transfer")


class CallingItOff(TransferCase):
    def test_cancelling_needs_a_reason_and_moves_nothing(self):
        owner, note = self.sent()
        before = self.stock(1)
        self.assertEqual(owner.post(f"/api/transfers/{note['id']}/cancel",
                                    json={"branch_id": 1, "reason": " "}).status_code, 400)
        cancelled = owner.post(f"/api/transfers/{note['id']}/cancel",
                               json={"branch_id": 1, "reason": "รถเสีย ยกกลับแล้ว"})
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assertEqual(cancelled.json()["status"], "cancelled")
        self.assertEqual(self.stock(1), before)

    def test_a_cancelled_note_cannot_be_received(self):
        owner, note = self.sent()
        owner.post(f"/api/transfers/{note['id']}/cancel",
                   json={"branch_id": 1, "reason": "ยกเลิก"})
        self.assertEqual(self.signed_in(3, "secure-pin-two").post(
            f"/api/transfers/{note['id']}/receive",
            json={"branch_id": 2, "received": {}}).status_code, 409)

    def test_a_note_already_confirmed_cannot_be_cancelled(self):
        owner, note = self.sent()
        self.signed_in(3, "secure-pin-two").post(f"/api/transfers/{note['id']}/receive",
                                                 json={"branch_id": 2, "received": {}})
        refused = owner.post(f"/api/transfers/{note['id']}/cancel",
                             json={"branch_id": 1, "reason": "เปลี่ยนใจ"})
        self.assertEqual(refused.status_code, 409)
        self.assertIn("โอนกลับ", refused.json()["detail"])


class WhatIsOnTheVan(TransferCase):
    def test_each_branch_sees_its_own_side_of_the_journey(self):
        self.sent()
        near = self.signed_in(2, "secure-pin-one").get("/api/transfers?branch_id=1").json()
        far = self.signed_in(3, "secure-pin-two").get("/api/transfers?branch_id=2").json()
        self.assertEqual(near["in_transit"]["outgoing"]["PORK"], 20)
        self.assertEqual(near["in_transit"]["incoming"], {})
        self.assertEqual(far["in_transit"]["incoming"]["PORK"], 20)
        self.assertEqual(far["in_transit"]["outgoing"], {})

    def test_once_confirmed_nothing_is_on_the_van(self):
        _, note = self.sent()
        far = self.signed_in(3, "secure-pin-two")
        far.post(f"/api/transfers/{note['id']}/receive", json={"branch_id": 2, "received": {}})
        self.assertEqual(far.get("/api/transfers?branch_id=2").json()["in_transit"]["incoming"], {})

    def test_a_cancelled_note_is_not_on_the_van_either(self):
        owner, note = self.sent()
        owner.post(f"/api/transfers/{note['id']}/cancel",
                   json={"branch_id": 1, "reason": "ยกเลิก"})
        seen = owner.get("/api/transfers?branch_id=1").json()
        self.assertEqual(seen["in_transit"]["outgoing"], {})


if __name__ == "__main__":
    unittest.main()


class TheOwnerAcrossBranches(TransferCase):
    """เจ้าของเป็นเจ้าของทุกสาขา การบังคับให้ไปล็อกอินทีละสาขาเพื่อดูใบโอน
    คือการให้เขาหาทางอ้อมระบบของตัวเอง"""

    def test_the_owner_reads_any_branch_s_transfers(self):
        self.sent()
        owner = self.signed_in()
        for branch_id in (1, 2):
            answer = owner.get(f"/api/transfers?branch_id={branch_id}")
            self.assertEqual(answer.status_code, 200, f"สาขา {branch_id}: {answer.text}")
            self.assertEqual(len(answer.json()["transfers"]), 1)

    def test_a_manager_still_only_reads_their_own(self):
        self.sent()
        near = self.signed_in(2, "secure-pin-one")
        self.assertEqual(near.get("/api/transfers?branch_id=1").status_code, 200)
        self.assertEqual(near.get("/api/transfers?branch_id=2").status_code, 403)

    def test_the_owner_may_send_from_any_branch(self):
        owner = self.signed_in()
        answer = owner.post("/api/transfers", json={
            "from_branch_id": 2, "to_branch_id": 1,
            "lines": [{"ingredient_id": "PORK", "quantity": 2}]})
        self.assertEqual(answer.status_code, 200, answer.text)


class SeeingBothEnds(TransferCase):
    def test_the_owner_reads_the_shelf_at_either_branch(self):
        """A transfer is worth nothing if the owner cannot see both ends."""
        owner = self.signed_in()
        for branch_id in (1, 2):
            answer = owner.get(f"/api/inventory?branch_id={branch_id}")
            self.assertEqual(answer.status_code, 200, f"สาขา {branch_id}: {answer.text}")

    def test_a_manager_reads_only_their_own_shelf(self):
        near = self.signed_in(2, "secure-pin-one")
        self.assertEqual(near.get("/api/inventory?branch_id=1").status_code, 200)
        self.assertEqual(near.get("/api/inventory?branch_id=2").status_code, 403)
