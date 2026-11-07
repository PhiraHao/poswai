"""Live staff ledger read permissions and branch scoping."""

import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

import line_pos_server as server


def test_staff_overview_is_live_and_manager_scoped():
    with TemporaryDirectory(ignore_cleanup_errors=True) as folder:
        database = Path(folder) / "staff.db"
        with patch.object(server, "DB_PATH", database), patch.object(server, "PREVIEW_ONLY", False), \
             patch.object(server, "BOOTSTRAP_MANAGER_PIN", ""):
            server.init_db()
            with closing(sqlite3.connect(database)) as conn, conn:
                conn.execute("INSERT INTO branches (id,name) VALUES (1,'One'),(2,'Two')")
                conn.execute("INSERT INTO staffs (id,branch_id,name,role,pin_code_hash) VALUES (1,1,'Manager','manager',?)",
                             (server.hash_pin("manager-long-pin"),))
                conn.execute("INSERT INTO staffs (id,branch_id,name,role,pin_code_hash) VALUES (2,1,'Worker','staff',?)",
                             (server.hash_pin("worker-long-pin"),))
                conn.execute("INSERT INTO staffs (id,branch_id,name,role,pin_code_hash) VALUES (3,2,'Other branch','staff',?)",
                             (server.hash_pin("other-long-pin"),))
                conn.execute("INSERT INTO leave_requests (staff_id,leave_type,start_date,end_date,reason) VALUES (2,'sick','2026-10-20','2026-10-20','Test')")
            with TestClient(server.app) as client:
                assert client.get("/api/staff/overview").status_code == 401
                assert client.post("/api/auth/login", json={"staff_id": 2, "pin": "worker-long-pin"}).status_code == 200
                assert client.get("/api/staff/overview").status_code == 403
                assert client.post("/api/auth/login", json={"staff_id": 1, "pin": "manager-long-pin"}).status_code == 200
                response = client.get("/api/staff/overview", params={"branch_id": 1})
                assert response.status_code == 200
                result = response.json()
                assert {s["id"] for s in result["staff"]} == {1, 2}
                assert result["leave_requests"][0]["staff_name"] == "Worker"
                assert client.get("/api/staff/overview", params={"branch_id": 2}).status_code == 403


if __name__ == "__main__":
    test_staff_overview_is_live_and_manager_scoped()
