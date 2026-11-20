"""The staff dossier: employment facts, document checklist, assets and history."""

import datetime
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import line_pos_server as server
import poswai_dossier as dossier


class TenureTest(unittest.TestCase):
    def test_service_length_reads_the_way_a_roster_talks(self):
        today = datetime.date(2026, 10, 16)
        self.assertEqual(dossier.tenure("2025-08-01", today)["text"], "1 ปี 2 เดือน")
        self.assertEqual(dossier.tenure("2026-10-01", today)["text"], "น้อยกว่า 1 เดือน")
        self.assertEqual(dossier.tenure("2026-09-20", today)["text"], "น้อยกว่า 1 เดือน")
        self.assertEqual(dossier.tenure("2025-10-16", today)["text"], "1 ปี")
        self.assertEqual(dossier.tenure("2026-04-16", today)["text"], "6 เดือน")
        self.assertIsNone(dossier.tenure(None, today)["months"])
        # A future start date never reads as negative service.
        self.assertEqual(dossier.tenure("2026-12-01", today)["months"], 0)


class StaffDossierTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.folder.cleanup)
        for item in (patch.object(server, "DB_PATH", Path(self.folder.name) / "dossier.db"),
                     patch.object(server, "PREVIEW_ONLY", False),
                     patch.object(server, "BOOTSTRAP_MANAGER_PIN", "")):
            item.start()
            self.addCleanup(item.stop)
        server.init_db()
        with sqlite3.connect(server.DB_PATH) as conn:
            conn.execute("INSERT INTO branches(id,name) VALUES(1,'One'),(2,'Two')")
            for staff_id, branch, role in ((1, 1, "manager"), (2, 1, "staff"),
                                           (3, 1, "cashier"), (4, 2, "manager")):
                conn.execute("INSERT INTO staffs(id,branch_id,name,role,pin_code_hash) VALUES(?,?,?,?,?)",
                             (staff_id, branch, f"User {staff_id}", role, server.hash_pin("secure-pin-x")))
        self.manager = self._client(1)
        self.worker = self._client(2)

    def _client(self, staff_id):
        client = TestClient(server.app)
        client.__enter__()
        self.addCleanup(lambda c=client: c.__exit__(None, None, None))
        self.assertEqual(client.post("/api/auth/login",
                                     json={"staff_id": staff_id, "pin": "secure-pin-x"}).status_code, 200)
        return client

    def test_a_new_dossier_starts_empty_and_lists_every_required_document(self):
        body = self.manager.get("/api/staff/2/dossier").json()
        self.assertEqual(body["staff"]["name"], "User 2")
        self.assertEqual(body["tenure"]["text"], "ยังไม่ได้บันทึกวันเริ่มงาน")
        self.assertEqual(len(body["documents"]), 7)
        # The work permit only applies to foreign staff, so it is not counted as a gap.
        self.assertEqual(len(body["documents_missing"]), 6)
        self.assertEqual(next(doc for doc in body["documents"]
                              if doc["key"] == "work_permit")["state"], "optional")
        self.assertIn("บัตรผ่านการอบรมผู้สัมผัสอาหาร", body["documents_missing"])
        self.assertEqual(body["assets"], [])
        self.assertEqual(body["timeline"], [])

    def test_manager_fills_in_employment_facts_and_probation_is_tracked(self):
        today = datetime.datetime.now(server.BANGKOK_TZ).date()
        saved = self.manager.patch("/api/staff/2/dossier", json={
            "nickname": "น้ำ", "phone": "086-777-8899", "line_display": "@wipa_serv",
            "start_date": "2025-08-01", "employment_type": "probation",
            "probation_end_date": (today + datetime.timedelta(days=10)).isoformat(),
            "bank_name": "กรุงไทย", "bank_account": "981-0-44556-7",
            "emergency_contact": "คุณปราณี (มารดา)", "emergency_phone": "085-444-3322",
            "medical_note": "แพ้อาหารทะเล"})
        self.assertEqual(saved.status_code, 200, saved.text)
        body = saved.json()
        self.assertEqual(body["profile"]["nickname"], "น้ำ")
        self.assertEqual(body["employment_label"], "ทดลองงาน")
        self.assertTrue(body["probation"]["on_probation"])
        self.assertEqual(body["probation"]["days_left"], 10)
        self.assertIn("ใกล้ครบกำหนดประเมิน", body["probation"]["status"])

        passed = self.manager.patch("/api/staff/2/dossier", json={"employment_type": "full_time"}).json()
        self.assertEqual(passed["probation"]["status"], "ผ่านทดลองงานแล้ว")
        self.assertFalse(passed["probation"]["on_probation"])

    def test_bad_dates_and_unknown_fields_are_refused(self):
        self.assertEqual(self.manager.patch("/api/staff/2/dossier",
                                            json={"start_date": "01/08/2025"}).status_code, 400)
        self.assertEqual(self.manager.patch("/api/staff/2/dossier",
                                            json={"employment_type": "ceo"}).status_code, 400)
        self.assertEqual(self.manager.patch("/api/staff/2/dossier",
                                            json={"nickname": "x" * 200}).status_code, 400)
        self.assertEqual(self.manager.patch("/api/staff/2/dossier", json={}).status_code, 400)

    def test_document_states_cover_missing_received_expiring_and_expired(self):
        today = datetime.datetime.now(server.BANGKOK_TZ).date()
        self.assertEqual(self.manager.put("/api/staff/2/documents/id_card",
                                          json={"received": True, "note": "เก็บแฟ้มหน้าร้าน"}).status_code, 200)
        soon = (today + datetime.timedelta(days=12)).isoformat()
        self.manager.put("/api/staff/2/documents/food_handler", json={"received": True, "expires_on": soon})
        gone = (today - datetime.timedelta(days=3)).isoformat()
        body = self.manager.put("/api/staff/2/documents/medical_certificate",
                                json={"received": True, "expires_on": gone}).json()

        states = {doc["key"]: doc["state"] for doc in body["documents"]}
        self.assertEqual(states["id_card"], "received")
        self.assertEqual(states["food_handler"], "expiring")
        self.assertEqual(states["medical_certificate"], "expired")
        self.assertEqual(states["contract"], "missing")
        self.assertEqual(len(body["documents_attention"]), 2)
        self.assertEqual(len(body["documents_missing"]), 3)

        self.assertEqual(self.manager.put("/api/staff/2/documents/passport",
                                          json={"received": True}).status_code, 404)
        self.assertEqual(self.manager.put("/api/staff/2/documents/contract",
                                          json={"received": True, "expires_on": "nope"}).status_code, 400)

    def test_store_assets_are_issued_and_checked_back_in(self):
        self.manager.post("/api/staff/2/assets", json={"item": "เสื้อยูนิฟอร์ม x2"})
        body = self.manager.post("/api/staff/2/assets", json={"item": "กุญแจล็อกเกอร์ #03"}).json()
        self.assertEqual(body["assets_outstanding"], 2)
        asset_id = next(item["id"] for item in body["assets"] if item["item"] == "เสื้อยูนิฟอร์ม x2")

        returned = self.manager.patch(f"/api/staff/2/assets/{asset_id}", json={"returned": True}).json()
        self.assertEqual(returned["assets_outstanding"], 1)
        self.assertTrue(next(item for item in returned["assets"] if item["id"] == asset_id)["returned_on"])

        self.assertEqual(self.manager.post("/api/staff/2/assets", json={"item": " "}).status_code, 400)
        self.assertEqual(self.manager.patch("/api/staff/2/assets/999",
                                            json={"returned": True}).status_code, 404)

    def test_timeline_keeps_raises_and_warnings_newest_first(self):
        self.manager.post("/api/staff/2/timeline", json={"kind": "milestone", "detail": "เริ่มงานวันแรก",
                                                         "event_date": "2025-08-01"})
        body = self.manager.post("/api/staff/2/timeline", json={"kind": "pay_change",
                                                                "detail": "ปรับเป็น 60 บาท/ชั่วโมง",
                                                                "event_date": "2026-02-01"}).json()
        self.assertEqual([item["event_date"] for item in body["timeline"]], ["2026-02-01", "2025-08-01"])
        self.assertEqual(body["timeline"][0]["kind_label"], "ปรับค่าแรง")
        self.assertEqual(self.manager.post("/api/staff/2/timeline",
                                           json={"kind": "fired", "detail": "x"}).status_code, 400)
        self.assertEqual(self.manager.post("/api/staff/2/timeline",
                                           json={"kind": "note", "detail": ""}).status_code, 400)

    def test_a_dossier_is_readable_by_its_owner_and_their_manager_only(self):
        self.assertEqual(self.worker.get("/api/staff/2/dossier").status_code, 200)
        self.assertEqual(self.worker.get("/api/staff/3/dossier").status_code, 403)
        self.assertEqual(self.worker.patch("/api/staff/2/dossier",
                                           json={"bank_name": "กสิกร"}).status_code, 403)
        self.assertEqual(self.worker.post("/api/staff/2/assets", json={"item": "กุญแจร้าน"}).status_code, 403)

        other_branch = self._client(4)
        self.assertEqual(other_branch.get("/api/staff/2/dossier").status_code, 403)
        self.assertEqual(other_branch.patch("/api/staff/2/dossier",
                                            json={"nickname": "x"}).status_code, 404)
        self.assertEqual(self.worker.get("/api/staff/dossier-summary").status_code, 403)

    def test_summary_tells_the_manager_who_still_owes_paperwork(self):
        self.manager.patch("/api/staff/2/dossier", json={"start_date": "2025-08-01"})
        for doc in ("id_card", "house_registration", "bank_book", "contract",
                    "medical_certificate", "food_handler", "work_permit"):
            self.manager.put(f"/api/staff/2/documents/{doc}", json={"received": True})
        self.manager.post("/api/staff/2/assets", json={"item": "กุญแจร้าน"})

        summary = self.manager.get("/api/staff/dossier-summary").json()["staff"]
        mine = next(row for row in summary if row["id"] == 2)
        other = next(row for row in summary if row["id"] == 3)
        self.assertEqual(mine["missing"], 0)
        self.assertEqual(mine["assets_outstanding"], 1)
        self.assertEqual(mine["tenure"], dossier.tenure("2025-08-01",
                                                        datetime.datetime.now(server.BANGKOK_TZ).date())["text"])
        self.assertEqual(other["missing"], 6)
        self.assertEqual(len(summary), 3)  # branch 1 only


if __name__ == "__main__":
    unittest.main()
