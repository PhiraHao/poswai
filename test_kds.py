"""Kitchen tickets persist and honor staff roles and course transitions."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import line_pos_server as server


class KitchenTicketsTest(unittest.TestCase):
    def test_held_course_requires_fire_then_kitchen_marks_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            server.DB_PATH = Path(directory) / "kds.db"
            server.PREVIEW_ONLY = False
            server.BOOTSTRAP_MANAGER_PIN = ""
            server.TABLE_QR_SECRET = "t" * 48
            server.init_db()
            conn = sqlite3.connect(server.DB_PATH)
            with conn:
                conn.execute("INSERT INTO branches(id,name) VALUES(1,'Test')")
                for staff_id, role in ((1, "manager"), (2, "kitchen"), (3, "service")):
                    conn.execute("INSERT INTO staffs(id,branch_id,name,role,pin_code_hash) VALUES(?,1,?,?,?)",
                                 (staff_id, role, role, server.hash_pin("secure-pin-" + role)))
            conn.close()

            with TestClient(server.app) as manager:
                self.assertEqual(manager.post("/api/auth/login", json={"staff_id": 1, "pin": "secure-pin-manager"}).status_code, 200)
                response = manager.put("/api/menu/TEA", json={"branch_id": 1, "name": "Tea",
                    "price": 35, "bom": [], "station": "บาร์น้ำ"})
                self.assertEqual(response.status_code, 200, response.text)
                token = manager.post("/api/tables/token", json={"branch_id": 1, "table_no": "T1"}).json()["token"]

            with TestClient(server.app) as customer:
                order = customer.post("/api/orders", headers={"X-Table-Token": token}, json={
                    "event_id": "order-1", "order_no": "KDS-1", "branch_id": 1, "table_no": "T1",
                    "total_amount": 35, "items": [{"id": "TEA", "name": "Ignored", "price": 35,
                    "qty": 1, "course_mode": "HOLD", "bom": []}],
                })
                self.assertEqual(order.status_code, 200, order.text)
                self.assertEqual(customer.get("/api/kds").status_code, 401)

            with TestClient(server.app) as kitchen:
                self.assertEqual(kitchen.post("/api/auth/login", json={"staff_id": 2, "pin": "secure-pin-kitchen"}).status_code, 200)
                path = "/api/kds/KDS-1/%E0%B8%9A%E0%B8%B2%E0%B8%A3%E0%B9%8C%E0%B8%99%E0%B9%89%E0%B8%B3"
                tickets = kitchen.get("/api/kds").json()["tickets"]
                self.assertEqual(len(tickets), 1)
                self.assertEqual(tickets[0]["status"], "held")
                self.assertEqual(tickets[0]["items"][0]["name"], "Tea")
                self.assertEqual(kitchen.post(path + "/ready").status_code, 409)
                self.assertEqual(kitchen.post(path + "/fire").json()["status"], "queued")
                self.assertEqual(kitchen.post(path + "/fire").json()["status"], "queued")
                self.assertEqual(kitchen.post(path + "/ready").json()["status"], "ready")
                self.assertEqual(kitchen.post(path + "/ready").json()["status"], "ready")

            with TestClient(server.app) as service:
                self.assertEqual(service.post("/api/auth/login", json={"staff_id": 3, "pin": "secure-pin-service"}).status_code, 200)
                self.assertEqual(service.post(path + "/ready").status_code, 403)

            conn = sqlite3.connect(server.DB_PATH)
            self.assertEqual(conn.execute("SELECT status FROM kds_station_tickets WHERE order_no='KDS-1'").fetchone()[0], "ready")
            self.assertEqual(conn.execute("SELECT course_mode FROM order_items WHERE order_no='KDS-1'").fetchone()[0], "FIRE")
            conn.close()


if __name__ == "__main__":
    unittest.main()
