"""Hourly, daily and monthly wages — a restaurant hires all three.

Paying only by the hour meant a full-time cook on a monthly salary could not be
entered at all. The amount still lives in one column; `pay_type` says what the
number is per, and payroll converts it to an hourly figure for overtime so a
salaried cook earns overtime against their own salary, not someone else's rate.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import line_pos_server as server


class StaffPayTypeTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(temp.cleanup)
        self.db = Path(temp.name) / "pay.db"
        for item in (patch.object(server, "DB_PATH", self.db),
                     patch.object(server, "PREVIEW_ONLY", False),
                     patch.object(server, "BOOTSTRAP_MANAGER_PIN", ""),
                     patch.object(server, "_prepared_databases", set())):
            item.start()
            self.addCleanup(item.stop)
        server.init_db()
        with sqlite3.connect(self.db) as conn:
            conn.execute("INSERT INTO branches(id,name) VALUES(1,'Main')")
            conn.execute("INSERT INTO staffs(id,branch_id,name,role,pin_code_hash) VALUES(1,1,'เจ้าของ','owner',?)",
                         (server.hash_pin("secure-owner-pin"),))
        self.client = TestClient(server.app)
        self.assertEqual(self.client.post("/api/auth/login",
                                          json={"staff_id": 1, "pin": "secure-owner-pin"}).status_code, 200)

    def _hire(self, name, **pay):
        return self.client.post("/api/staff", json={
            "name": name, "role": "kitchen", "pin": "secure-staff-pin", **pay})

    def _work(self, staff_id, day, hours):
        """One worked day, recorded the way clocking in and out leaves it."""
        with sqlite3.connect(self.db) as conn:
            conn.execute("INSERT INTO attendances(staff_id,clock_in,clock_out) VALUES(?,?,?)",
                         (staff_id, f"{day}T08:00:00", f"{day}T{8 + int(hours):02d}:00:00"))

    def test_each_pay_type_is_stored_and_read_back(self):
        hourly = self._hire("พาร์ตไทม์", pay_type="hourly", pay_amount=60)
        daily = self._hire("รายวัน", pay_type="daily", pay_amount=450)
        monthly = self._hire("ประจำ", pay_type="monthly", pay_amount=15000)
        for response, kind, amount in ((hourly, "hourly", 60), (daily, "daily", 450),
                                       (monthly, "monthly", 15000)):
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual((response.json()["pay_type"], response.json()["pay_amount"]), (kind, amount))
        listed = {row["name"]: row for row in self.client.get("/api/staff/directory").json()["items"]}
        self.assertEqual(listed["ประจำ"]["pay_type"], "monthly")
        self.assertEqual(listed["ประจำ"]["pay_amount"], 15000)
        # ชื่อเดิมยังอยู่ แอปรุ่นที่ยังไม่อัปเดตจึงไม่พัง
        self.assertEqual(listed["ประจำ"]["hourly_rate"], 15000)

    def test_payroll_pays_the_month_the_days_and_the_hours_differently(self):
        hourly = self._hire("พาร์ตไทม์", pay_type="hourly", pay_amount=60).json()["staff_id"]
        daily = self._hire("รายวัน", pay_type="daily", pay_amount=450).json()["staff_id"]
        monthly = self._hire("ประจำ", pay_type="monthly", pay_amount=15000).json()["staff_id"]
        for staff_id in (hourly, daily, monthly):
            for day in ("2026-11-02", "2026-11-03"):
                self._work(staff_id, day, 8)
        payroll = {row["name"]: row for row in
                   self.client.get("/api/staff/payroll?month=2026-11").json()["staff"]}

        self.assertEqual(payroll["พาร์ตไทม์"]["base_pay"], 16 * 60)      # ตามชั่วโมง
        self.assertEqual(payroll["รายวัน"]["base_pay"], 2 * 450)          # ตามวันที่มา
        # รายเดือนได้เต็มเดือนไม่ว่ามากี่วัน — หักขาด/ลาเป็นนโยบายที่ตั้งแยก
        self.assertEqual(payroll["ประจำ"]["base_pay"], 15000)
        self.assertEqual(payroll["ประจำ"]["work_days"], 2)

    def test_overtime_uses_each_persons_own_hourly_equivalent(self):
        daily = self._hire("รายวัน", pay_type="daily", pay_amount=480).json()["staff_id"]
        monthly = self._hire("ประจำ", pay_type="monthly", pay_amount=19200).json()["staff_id"]
        for staff_id in (daily, monthly):
            self._work(staff_id, "2026-11-02", 10)        # ทำ 10 ชม. = OT 2 ชม.
        payroll = {row["name"]: row for row in
                   self.client.get("/api/staff/payroll?month=2026-11").json()["staff"]}
        # รายวัน 480 ต่อ 8 ชม. = 60 บาท/ชม.
        self.assertEqual(payroll["รายวัน"]["hourly_equivalent"], 60)
        self.assertEqual(payroll["รายวัน"]["ot_pay"], round(2 * 60 * 1.5, 2))
        # รายเดือน 19,200 ต่อ 30 วัน ต่อ 8 ชม. = 80 บาท/ชม.
        self.assertEqual(payroll["ประจำ"]["hourly_equivalent"], 80)
        self.assertEqual(payroll["ประจำ"]["ot_pay"], round(2 * 80 * 1.5, 2))

    def test_an_amount_in_the_wrong_box_is_caught(self):
        """เงินเดือนที่กรอกในช่องรายชั่วโมงต้องไม่ผ่าน"""
        too_big = self._hire("พิมพ์ผิด", pay_type="hourly", pay_amount=15000)
        self.assertEqual(too_big.status_code, 400, too_big.text)
        self.assertIn("รายชั่วโมง", too_big.json()["detail"])
        self.assertEqual(self._hire("ประเภทมั่ว", pay_type="yearly", pay_amount=100).status_code, 400)
        # เงินเดือน 15,000 ในช่องรายเดือนผ่านตามปกติ
        self.assertEqual(self._hire("ประจำ", pay_type="monthly", pay_amount=15000).status_code, 200)

    def test_changing_only_the_amount_keeps_the_pay_type(self):
        """แอปรุ่นเก่าส่งมาแค่ยอด — ถ้ารีเซ็ตประเภททิ้ง เงินเดือนจะกลายเป็นค่าชั่วโมง"""
        staff_id = self._hire("ประจำ", pay_type="monthly", pay_amount=15000).json()["staff_id"]
        bumped = self.client.patch(f"/api/staff/{staff_id}/pay-rate", json={"hourly_rate": 16000})
        self.assertEqual(bumped.status_code, 200, bumped.text)
        self.assertEqual((bumped.json()["pay_type"], bumped.json()["pay_amount"]), ("monthly", 16000))
        moved = self.client.patch(f"/api/staff/{staff_id}/pay-rate",
                                  json={"pay_type": "daily", "pay_amount": 500})
        self.assertEqual(moved.json()["pay_type"], "daily")
        listed = {row["name"]: row for row in self.client.get("/api/staff/directory").json()["items"]}
        self.assertEqual((listed["ประจำ"]["pay_type"], listed["ประจำ"]["pay_amount"]), ("daily", 500))

    def test_permanent_and_temporary_are_told_apart(self):
        """ลูกจ้างรายวันเป็นคนประจําก็ได้ มาเฉพาะเสาร์อาทิตย์ก็ได้ — คนละเรื่องกับวิธีจ่ายเงิน"""
        part = self._hire("เสาร์อาทิตย์", pay_type="daily", pay_amount=450,
                          employment_type="temporary")
        full = self._hire("คนประจํา", pay_type="daily", pay_amount=450,
                          employment_type="permanent")
        self.assertEqual(part.json()["employment_type"], "temporary")
        self.assertEqual(full.json()["employment_type"], "permanent")

        listed = {row["name"]: row for row in self.client.get("/api/staff/directory").json()["items"]}
        self.assertEqual(listed["เสาร์อาทิตย์"]["employment_type"], "temporary")
        # ไม่ระบุมา = ประจํา ตามค่าตั้งต้นของคอลัมน์
        self.assertEqual(self._hire("ไม่ระบุ").json()["employment_type"], "permanent")
        self.assertEqual(self._hire("ประเภทมั่ว", employment_type="freelance").status_code, 400)

        # เปลี่ยนทีหลังได้ คนชั่วคราวที่ร้านรับเข้าประจํามีจริง
        staff_id = part.json()["staff_id"]
        moved = self.client.patch(f"/api/staff/{staff_id}/profile",
                                  json={"employment_type": "permanent"})
        self.assertEqual(moved.status_code, 200, moved.text)
        listed = {row["id"]: row for row in self.client.get("/api/staff/directory").json()["items"]}
        self.assertEqual(listed[staff_id]["employment_type"], "permanent")

        self._work(staff_id, "2026-11-02", 8)
        payroll = {row["name"]: row for row in
                   self.client.get("/api/staff/payroll?month=2026-11").json()["staff"]}
        self.assertEqual(payroll["เสาร์อาทิตย์"]["employment_type"], "permanent")

    def test_staff_hired_before_this_existed_stay_hourly(self):
        with sqlite3.connect(self.db) as conn:
            # ไม่ระบุ pay_type เหมือนแถวที่มีมาก่อนการย้ายโครงสร้าง
            conn.execute("INSERT INTO staffs(id,branch_id,name,role,pin_code_hash,hourly_rate) "
                         "VALUES(9,1,'คนเดิม','cashier',?,70)", (server.hash_pin("secure-old-pin"),))
        self._work(9, "2026-11-02", 8)
        payroll = {row["name"]: row for row in
                   self.client.get("/api/staff/payroll?month=2026-11").json()["staff"]}
        self.assertEqual(payroll["คนเดิม"]["pay_type"], "hourly")
        self.assertEqual(payroll["คนเดิม"]["base_pay"], 8 * 70)


if __name__ == "__main__":
    unittest.main()
