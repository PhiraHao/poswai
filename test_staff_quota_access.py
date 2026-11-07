"""Leave allowance, POS access switch, day-off shifts and the shared role matrix."""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import line_pos_server as server


class StaffQuotaAndAccessTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.folder.cleanup)
        patches = [patch.object(server, "DB_PATH", Path(self.folder.name) / "quota.db"),
                   patch.object(server, "PREVIEW_ONLY", False),
                   patch.object(server, "BOOTSTRAP_MANAGER_PIN", "")]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        server.init_db()
        with sqlite3.connect(server.DB_PATH) as conn:
            conn.execute("INSERT INTO branches(id,name) VALUES(1,'One')")
            for id_, role in ((1, "owner"), (2, "manager"), (3, "staff")):
                conn.execute("INSERT INTO staffs(id,branch_id,name,role,pin_code_hash) VALUES(?,?,?,?,?)",
                             (id_, 1, f"User {id_}", role, server.hash_pin("long-test-pin")))

    @staticmethod
    def _login(client, staff_id):
        return client.post("/api/auth/login", json={"staff_id": staff_id, "pin": "long-test-pin"})

    def test_role_matrix_is_published_for_the_pwa(self):
        with TestClient(server.app) as client:
            matrix = client.get("/api/permissions")
            self.assertEqual(matrix.status_code, 200)
            roles = matrix.json()["roles"]
            self.assertEqual(len(roles["owner"]["tabs"]), 7)
            self.assertNotIn("inventory", roles["cashier"]["tabs"])
            self.assertNotIn("analytics", roles["cashier"]["tabs"])
            self.assertNotIn("cashier", roles["kitchen"]["tabs"])
            self.assertEqual(roles["staff"]["tabs"], ["customer", "staff"])

    def test_new_staff_get_a_leave_allowance_that_approved_leave_reduces(self):
        with TestClient(server.app) as manager, TestClient(server.app) as worker:
            self._login(manager, 2)
            created = manager.post("/api/staff", json={"name": "ใหม่", "role": "cashier",
                                                       "pin": "long-test-pin", "hourly_rate": 62.5,
                                                       "leave_quota": {"vacation": 10}})
            self.assertEqual(created.status_code, 200)
            new_id = created.json()["staff_id"]

            entry = next(item for item in manager.get("/api/staff/directory").json()["items"]
                         if item["id"] == new_id)
            self.assertEqual(entry["hourly_rate"], 62.5)
            self.assertEqual(entry["leave_quota"]["sick"]["left"], 30)
            self.assertEqual(entry["leave_quota"]["vacation"]["total"], 10)

            # A pre-existing account keeps the documented default until it is edited.
            mine = next(item for item in manager.get("/api/staff/directory").json()["items"] if item["id"] == 3)
            self.assertIsNone(mine["leave_quota"])
            self.assertEqual(manager.patch("/api/staff/3/profile",
                                           json={"leave_quota": {"personal": 5}}).status_code, 200)

            with sqlite3.connect(server.DB_PATH) as conn:
                conn.execute("INSERT INTO leave_requests(staff_id,leave_type,start_date,end_date,reason,status) "
                             "VALUES(3,'personal',date('now','start of year','+10 days'),"
                             "date('now','start of year','+11 days'),'ธุระ','approved')")

            quota = next(item for item in manager.get("/api/staff/overview").json()["staff"]
                         if item["id"] == 3)["leave_quota"]
            self.assertEqual(quota["personal"], {"total": 5, "used": 2, "left": 3})

            self._login(worker, 3)
            self.assertEqual(worker.get("/api/staff/me").json()["leave_quota"]["personal"]["left"], 3)

    def test_quota_rejects_impossible_values(self):
        with TestClient(server.app) as manager:
            self._login(manager, 2)
            self.assertEqual(manager.patch("/api/staff/3/profile",
                                           json={"leave_quota": {"sick": 400}}).status_code, 400)
            self.assertEqual(manager.patch("/api/staff/3/profile",
                                           json={"leave_quota": {"sick": -1}}).status_code, 400)
            self.assertEqual(manager.patch("/api/staff/3/profile", json={"hourly_rate": -5}).status_code, 400)

    def test_pos_access_switch_suspends_and_restores_one_person(self):
        with TestClient(server.app) as manager, TestClient(server.app) as worker:
            self._login(manager, 2)
            self.assertEqual(self._login(worker, 3).status_code, 200)

            self.assertEqual(manager.patch("/api/staff/3/pos-access", json={"locked": True}).status_code, 200)
            self.assertEqual(worker.get("/api/staff/me").status_code, 401)
            self.assertEqual(self._login(worker, 3).status_code, 403)
            locked_row = next(item for item in manager.get("/api/staff/overview").json()["staff"]
                              if item["id"] == 3)
            self.assertTrue(locked_row["pos_pin_locked"])
            self.assertEqual(locked_row["status"], "suspended")

            self.assertEqual(manager.patch("/api/staff/3/pos-access", json={"locked": False}).status_code, 200)
            self.assertEqual(self._login(worker, 3).status_code, 200)

            # Nobody unlocks themselves, and the owner account stays untouchable.
            self.assertEqual(manager.patch("/api/staff/2/pos-access", json={"locked": True}).status_code, 403)
            self.assertEqual(manager.patch("/api/staff/1/pos-access", json={"locked": True}).status_code, 403)
            self.assertEqual(manager.patch("/api/staff/99/pos-access", json={"locked": True}).status_code, 404)

    def test_day_off_rows_are_not_marked_absent(self):
        with TestClient(server.app) as manager:
            self._login(manager, 2)
            template = manager.post("/api/staff/shift-templates", json={"branch_id": 1, "name": "กะเช้า",
                                                                        "start_time": "08:00", "end_time": "17:00"})
            self.assertEqual(template.status_code, 200)
            today = manager.get("/api/staff/overview").json()["work_date"]

            assigned = manager.post("/api/staff/shifts", json={"branch_id": 1, "staff_id": 3, "work_date": today,
                                                               "shift_template_id": template.json()["id"]})
            self.assertEqual(assigned.json()["status"], "scheduled")

            off = manager.post("/api/staff/shifts", json={"branch_id": 1, "staff_id": 3, "work_date": today,
                                                          "shift_template_id": None})
            self.assertEqual(off.status_code, 200)
            self.assertEqual(off.json()["status"], "day_off")

            row = next(item for item in manager.get("/api/staff/overview").json()["staff"] if item["id"] == 3)
            self.assertEqual(row["status"], "day_off")
            self.assertEqual(row["shift"], "วันหยุด")
            self.assertIsNone(row["shift_template_id"])

            absence = manager.post("/api/staff/absence-check")
            self.assertEqual(absence.json()["absent_staff_ids"], [])

    def test_unknown_shift_template_is_still_rejected(self):
        with TestClient(server.app) as manager:
            self._login(manager, 2)
            today = manager.get("/api/staff/overview").json()["work_date"]
            self.assertEqual(manager.post("/api/staff/shifts", json={"branch_id": 1, "staff_id": 3,
                                                                     "work_date": today,
                                                                     "shift_template_id": 404}).status_code, 404)


if __name__ == "__main__":
    unittest.main()
