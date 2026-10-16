"""Staff roster actions and role boundaries used by the live staff workspace."""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import line_pos_server as server


class StaffRolesTest(unittest.TestCase):
    def test_directory_management_and_attendance_permissions(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder, patch.object(server, "DB_PATH", Path(folder) / "roles.db"), \
             patch.object(server, "PREVIEW_ONLY", False), patch.object(server, "BOOTSTRAP_MANAGER_PIN", ""):
            server.init_db()
            with sqlite3.connect(server.DB_PATH) as conn:
                conn.execute("INSERT INTO branches(id,name) VALUES(1,'One'),(2,'Two')")
                for id_, branch, role in ((1, 1, "owner"), (2, 1, "manager"),
                                          (3, 1, "staff"), (4, 1, "kitchen"), (5, 2, "staff")):
                    conn.execute("INSERT INTO staffs(id,branch_id,name,role,pin_code_hash) VALUES(?,?,?,?,?)",
                                 (id_, branch, f"User {id_}", role, server.hash_pin("long-test-pin")))

            with TestClient(server.app) as owner, TestClient(server.app) as manager, \
                 TestClient(server.app) as worker, TestClient(server.app) as kitchen:
                for client, staff_id in ((owner, 1), (manager, 2), (worker, 3), (kitchen, 4)):
                    self.assertEqual(client.post("/api/auth/login", json={"staff_id": staff_id,
                                                                             "pin": "long-test-pin"}).status_code, 200)

                self.assertEqual(worker.get("/api/staff/directory").status_code, 403)
                self.assertEqual(worker.get("/api/inventory").status_code, 403)
                self.assertEqual(worker.get("/api/kds").status_code, 403)
                self.assertEqual(kitchen.get("/api/inventory").status_code, 200)
                self.assertEqual(manager.get("/api/staff/directory").status_code, 200)
                self.assertEqual(manager.get("/api/staff/directory", params={"branch_id": 2}).status_code, 403)

                self.assertEqual(manager.post("/api/staff", json={"name": "Other manager", "role": "manager",
                                                                    "pin": "long-test-pin"}).status_code, 403)
                self.assertEqual(owner.post("/api/staff", json={"name": "Other manager", "role": "manager",
                                                                  "pin": "long-test-pin"}).status_code, 200)
                self.assertEqual(manager.patch("/api/staff/1/profile", json={"is_active": False}).status_code, 403)
                self.assertEqual(manager.patch("/api/staff/2/profile", json={"is_active": False}).status_code, 403)
                self.assertEqual(owner.patch("/api/staff/1/profile", json={"is_active": False}).status_code, 403)
                self.assertEqual(manager.patch("/api/staff/3/profile", json={"role": "cashier"}).status_code, 200)
                self.assertEqual(manager.patch("/api/staff/3/profile", json={"role": "manager"}).status_code, 403)
                self.assertEqual(manager.put("/api/staff/3/pin", json={"pin": "new-test-pin"}).status_code, 200)
                self.assertEqual(worker.get("/api/staff/me").status_code, 401)
                self.assertEqual(worker.post("/api/auth/login", json={"staff_id": 3,
                                                                        "pin": "new-test-pin"}).status_code, 200)

                self.assertEqual(manager.get("/api/staff/overview").json()["staff"][2]["status"], "scheduled")
                self.assertEqual(manager.post("/api/attendance", json={"event_id": "clock-a", "staff_id": 3,
                                                                          "action": "clock_in"}).status_code, 200)
                self.assertEqual(worker.get("/api/staff/me").json()["status"], "clocked_in")
                self.assertEqual(manager.get("/api/staff/overview").json()["staff"][2]["status"], "clocked_in")
                self.assertEqual(manager.post("/api/attendance", json={"event_id": "clock-b", "staff_id": 3,
                                                                          "action": "clock_in"}).status_code, 409)
                self.assertEqual(manager.post("/api/attendance", json={"event_id": "clock-c", "staff_id": 3,
                                                                          "action": "clock_out"}).status_code, 200)
                self.assertEqual(worker.get("/api/staff/me").json()["status"], "clocked_out")
                self.assertEqual(manager.post("/api/attendance", json={"event_id": "clock-d", "staff_id": 1,
                                                                          "action": "clock_in"}).status_code, 403)
                self.assertEqual(manager.patch("/api/staff/3/profile", json={"is_active": False}).status_code, 200)
                self.assertEqual(worker.get("/api/staff/me").status_code, 401)
                self.assertEqual(manager.patch("/api/staff/3/profile", json={"is_active": True}).status_code, 200)


if __name__ == "__main__":
    unittest.main()
