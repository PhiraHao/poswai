"""Focused tests for POS access boundaries."""

import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from fastapi.testclient import TestClient

import line_pos_server as server


def _staff_session_table_qr_and_privileged_access(db_path):
    server.DB_PATH = db_path
    server.PREVIEW_ONLY = False
    server.TABLE_QR_SECRET = "s" * 48
    server.BOOTSTRAP_MANAGER_PIN = ""
    server.init_db()
    with sqlite3.connect(server.DB_PATH) as conn:
        conn.execute("INSERT INTO branches (id,name) VALUES (1,'Test')")
        conn.execute("INSERT INTO staffs (id,branch_id,name,role,pin_code_hash) VALUES (1,1,'Manager','manager',?)",
                     (server.hash_pin("secure-manager-pin"),))
        conn.execute("INSERT INTO staffs (id,branch_id,name,role,pin_code_hash) VALUES (2,1,'Cashier','cashier',?)",
                     (server.hash_pin("secure-cashier-pin"),))
        server.upsert_menu_item(conn, 1, 1, "Tea", 20, [])
    conn.close()

    with TestClient(server.app) as guest:
        assert guest.get("/api/staff/payroll", params={"month": "2026-10"}).status_code == 401
        assert guest.post("/api/orders", json={"event_id": "e1", "order_no": "o1", "branch_id": 1,
                                               "table_no": "T1", "total_amount": 20,
                                               "items": [{"id": 1, "name": "Tea", "price": 20, "qty": 1, "bom": []}]}).status_code == 401
        assert guest.post("/api/auth/login", json={"staff_id": 1, "pin": "wrong"}).status_code == 401
        assert guest.post("/api/auth/login", json={"staff_id": 1, "pin": "secure-manager-pin"}).status_code == 200
        assert guest.get("/api/auth/session").json()["role"] == "manager"
        token_response = guest.post("/api/tables/token", json={"branch_id": 1, "table_no": "T1"})
        assert token_response.status_code == 200
        token = token_response.json()["token"]
        assert guest.get("/api/staff/payroll", params={"month": "2026-10"}).status_code == 200
        assert guest.post("/api/auth/logout").status_code == 200
        assert guest.get("/api/auth/session").status_code == 401

    with TestClient(server.app) as customer:
        order = {"event_id": "e1", "order_no": "o1", "branch_id": 1, "table_no": "T1",
                 "total_amount": 20, "items": [{"id": 1, "name": "Tea", "price": 20, "qty": 1, "bom": []}]}
        assert customer.post("/api/orders", headers={"X-Table-Token": token}, json=order).status_code == 200
        assert customer.post("/api/orders", headers={"X-Table-Token": token},
                             json={**order, "order_no": "o2", "event_id": "e2", "table_no": "T2"}).status_code == 403
        assert customer.get("/api/service-calls").status_code == 401

    with TestClient(server.app) as cashier:
        assert cashier.post("/api/auth/login", json={"staff_id": 2, "pin": "secure-cashier-pin"}).status_code == 200
        assert cashier.get("/api/staff/payroll", params={"month": "2026-10"}).status_code == 403
        assert cashier.post("/api/tables/token", json={"branch_id": 1, "table_no": "T2"}).status_code == 403


def _preview_stays_closed(db_path):
    server.DB_PATH = db_path
    server.PREVIEW_ONLY = True
    server.BOOTSTRAP_MANAGER_PIN = ""
    server.init_db()
    with TestClient(server.app) as client:
        assert client.post("/api/auth/login", json={"staff_id": 1, "pin": "anything"}).status_code == 403
        assert client.post("/api/service-calls", json={"event_id": "x", "branch_id": 1,
                                                       "table_no": "T1", "call_type": "help"}).status_code == 403


class AuthSecurityTest(unittest.TestCase):
    def test_staff_session_table_qr_and_privileged_access(self):
        with tempfile.TemporaryDirectory() as directory:
            _staff_session_table_qr_and_privileged_access(Path(directory) / "auth.db")

    def test_preview_stays_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            _preview_stays_closed(Path(directory) / "preview.db")


if __name__ == "__main__":
    unittest.main()
