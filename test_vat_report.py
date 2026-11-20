"""รายงานภาษีขาย ภ.พ.30 และไฟล์รายบิลที่ส่งให้บัญชี

ร้านที่จดทะเบียน VAT ต้องทำรายงานภาษีขายทุกเดือนและยื่น ภ.พ.30 ภายในวันที่ 15
ของเดือนถัดไป ของเดิมร้านต้องไล่บิลทีละใบแล้วพิมพ์ลง Excel เอง ซึ่งนอกจาก
กินเวลาทั้งวันแล้ว ยังเป็นที่ที่ตัวเลขเพี้ยนได้เงียบ ๆ

วิธีลงรายการมาจากประกาศอธิบดีกรมสรรพากร ฉบับที่ 89: ใบกำกับภาษีเต็มรูปลงเป็น
รายใบ (ข้อ 7(1)) ใบกำกับภาษีอย่างย่อลงยอดรวมวันละแถวพร้อมช่วงเลขที่ (ข้อ 7(2))
และใบลดหนี้ลงเป็นรายใบ (ข้อ 7(10)) ซึ่งที่นี่ลงเป็นยอดติดลบ เพราะเป็นการลดยอดขาย
"""

import csv
import datetime as dt
import io
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

import line_pos_server as server
import poswai_vat_report as vat_report


class ChoosingTheTaxMonth(unittest.TestCase):
    """รายงานภาษีขายยื่นเป็นเดือนภาษี ช่วงคร่อมเดือนไม่มีความหมายในแบบ ภ.พ.30"""

    def test_a_month_runs_from_the_first_to_the_last(self):
        self.assertEqual(vat_report.month_range("2026-11")[:2], ("2026-11-01", "2026-11-30"))

    def test_february_knows_about_leap_years(self):
        self.assertEqual(vat_report.month_range("2028-02")[1], "2028-02-29")
        self.assertEqual(vat_report.month_range("2026-02")[1], "2026-02-28")

    def test_december_rolls_into_the_next_year(self):
        self.assertEqual(vat_report.month_range("2026-12")[:2], ("2026-12-01", "2026-12-31"))

    def test_no_month_means_the_one_we_are_in(self):
        self.assertEqual(vat_report.month_range("", dt.date(2026, 11, 15))[2], "2026-11")

    def test_anything_else_is_refused(self):
        for bad in ("พฤศจิกายน", "2026/11", "2026-13-01", "13"):
            with self.assertRaises(vat_report.VatReportError, msg=bad):
                vat_report.month_range(bad)


class VatCase(unittest.TestCase):
    """ร้านจดทะเบียน VAT 7% ค่าบริการ 10% เมนูจานละ 100"""

    TAX_ID = "0105556000335"

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.directory.cleanup)
        server.DB_PATH = Path(self.directory.name) / "vat.db"
        server.PREVIEW_ONLY = False
        server.BOOTSTRAP_MANAGER_PIN = ""
        server.TABLE_QR_SECRET = "k" * 48
        server.init_db()
        self.conn = sqlite3.connect(server.DB_PATH)
        self.addCleanup(self.conn.close)
        with self.conn:
            self.conn.execute("INSERT INTO branches(id,name) VALUES(1,'สาขาหลัก')")
            for staff_id, name, role in ((1, "เจ้าของ", "owner"), (2, "แคชเชียร์", "cashier")):
                self.conn.execute("INSERT INTO staffs(id,branch_id,name,role,pin_code_hash)"
                                  " VALUES(?,1,?,?,?)",
                                  (staff_id, name, role, server.hash_pin(f"secure-pin-{staff_id}")))
        self.owner = self.signed_in(1)
        self.set_shop()
        self.assertEqual(self.owner.put("/api/menu/M1", json={
            "branch_id": 1, "name": "ข้าวผัด", "price": 100,
            "service_charge": True}).status_code, 200)

    def set_shop(self, **changes):
        wanted = {"vat_rate_bp": 700, "vat_inclusive": 0, "service_charge_bp": 1000,
                  "tax_id": self.TAX_ID, "address": "1 ถนนทดสอบ",
                  "legal_name": "ร้านทดสอบ จำกัด"}
        wanted.update(changes)
        have = {row[1] for row in self.conn.execute("PRAGMA table_info(shop_profile)")}
        known = {name: value for name, value in wanted.items() if name in have}
        with self.conn:
            self.conn.execute(f"UPDATE shop_profile SET {','.join(f'{k}=?' for k in known)}",
                              tuple(known.values()))

    def signed_in(self, staff_id):
        client = TestClient(server.app)
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        self.assertEqual(client.post("/api/auth/login",
                                     json={"staff_id": staff_id,
                                           "pin": f"secure-pin-{staff_id}"}).status_code, 200)
        return client

    def paid_bill(self, qty=1, *, invoice=False):
        order_no = f"ORD-{uuid.uuid4()}"
        body = {"event_id": str(uuid.uuid4()), "order_no": order_no, "branch_id": 1,
                "table_no": "1", "total_amount": 0,
                "items": [{"id": "M1", "name": "ข้าวผัด", "price": 100, "qty": qty}]}
        answer = self.owner.post("/api/orders", json=body)
        if answer.status_code == 409:
            body["total_amount"] = round(qty * 100 * 1.1 * 1.07, 2)
            answer = self.owner.post("/api/orders", json=body)
        self.assertEqual(answer.status_code, 200, answer.text)
        total = self.total_cents(order_no)
        self.assertEqual(self.owner.post("/api/payments/close", json={
            "event_id": str(uuid.uuid4()), "order_no": order_no,
            "amount": total / 100, "method": server.MANUAL_CASH}).status_code, 200)
        number = ""
        if invoice:
            made = self.owner.post("/api/tax-invoices", json={
                "branch_id": 1, "order_no": order_no, "name": "บริษัท ลูกค้า จำกัด",
                "tax_id": self.TAX_ID, "address": "2 ถนนลูกค้า", "branch": "สาขาที่ 00002"})
            self.assertEqual(made.status_code, 200, made.text)
            number = made.json()["number"]
        return order_no, total, number

    def total_cents(self, order_no):
        return round(self.conn.execute("SELECT total_amount FROM order_events WHERE order_no=?",
                                       (order_no,)).fetchone()[0] * 100)

    def line_ids(self, order_no):
        return [row[0] for row in self.conn.execute(
            "SELECT rowid FROM order_items WHERE order_no=? ORDER BY rowid", (order_no,))]

    def refund(self, order_no, line_id, qty=1, reason="จานไหม้"):
        answer = self.owner.post(f"/api/orders/{order_no}/refund-partial", json={
            "branch_id": 1, "event_id": str(uuid.uuid4()), "reason": reason,
            "picks": [{"line_id": line_id, "qty": qty}], "amount": None})
        self.assertEqual(answer.status_code, 200, answer.text)
        return answer.json()["refund"]

    def report(self, month="", *, client=None, expect=200):
        today = dt.datetime.now(vat_report.BANGKOK).date()
        month = month or f"{today.year:04d}-{today.month:02d}"
        answer = (client or self.owner).get(
            f"/api/reports/vat-sales?branch_id=1&month={month}")
        self.assertEqual(answer.status_code, expect, answer.text)
        return answer.json() if expect == 200 else answer


class TheSalesVatReport(VatCase):
    def test_a_plain_days_takings_are_one_row_for_the_day(self):
        """ใบกำกับภาษีอย่างย่อลงยอดรวมวันละแถว ไม่ใช่แถวละบิล (ข้อ 7(2))"""
        for _ in range(3):
            self.paid_bill()
        rows = self.report()["rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "abbreviated")
        self.assertIn("3 ใบ", rows[0]["buyer"])

    def test_that_row_says_which_receipt_numbers_it_covers(self):
        """ข้อ 7(2)(ค) บังคับให้บอกช่วงเลขที่ในช่องเลขที่"""
        self.paid_bill()
        self.paid_bill()
        self.assertIn("ถึงเลขที่", self.report()["rows"][0]["number"])

    def test_a_single_bill_names_itself(self):
        self.paid_bill()
        number = self.report()["rows"][0]["number"]
        self.assertIn("เลขที่", number)
        self.assertNotIn("ถึง", number)

    def test_the_value_is_before_vat_and_the_vat_is_its_own_column(self):
        """100 บาท + ค่าบริการ 10 = 110 · VAT 7% = 7.70 · รวม 117.70"""
        self.paid_bill()
        row = self.report()["rows"][0]
        self.assertEqual(row["value"], 110.0)
        self.assertEqual(row["vat"], 7.70)

    def test_a_full_tax_invoice_gets_its_own_row(self):
        """ข้อ 7(1) ลงเป็นรายใบ พร้อมเลขผู้เสียภาษีและสถานประกอบการของผู้ซื้อ"""
        _, _, number = self.paid_bill(invoice=True)
        rows = self.report()["rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "full")
        self.assertEqual(rows[0]["number"], number)
        self.assertEqual(rows[0]["buyer"], "บริษัท ลูกค้า จำกัด")
        self.assertEqual(rows[0]["buyer_tax_id"], self.TAX_ID)
        self.assertEqual(rows[0]["place"], "สาขาที่ 00002")

    def test_a_bill_with_an_invoice_is_not_counted_twice(self):
        self.paid_bill(invoice=True)
        report = self.report()
        self.assertEqual(len(report["rows"]), 1)
        self.assertEqual(report["totals"]["vat"], 7.70)

    def test_a_credit_note_is_a_negative_row_of_its_own(self):
        """ข้อ 7(10) ลงเป็นรายใบ · ติดลบเพราะเป็นการลดยอดขาย"""
        order_no, _, number = self.paid_bill(qty=2, invoice=True)
        given = self.refund(order_no, self.line_ids(order_no)[0])
        made = self.owner.post(f"/api/tax-invoices/{number}/credit-note",
                               json={"branch_id": 1, "refund_id": given["id"]})
        self.assertEqual(made.status_code, 200, made.text)
        rows = self.report()["rows"]
        credit = [row for row in rows if row["kind"] == "credit"]
        self.assertEqual(len(credit), 1)
        self.assertEqual(credit[0]["vat"], -7.70)
        self.assertEqual(credit[0]["value"], -110.0)
        self.assertIn(number, credit[0]["number"])

    def test_refunding_a_plain_bill_lowers_that_days_row(self):
        """บิลอย่างย่อไม่มีใบลดหนี้มาลบให้ ยอดของวันจึงต้องลดลงเอง"""
        order_no, _, _ = self.paid_bill(qty=2)
        self.refund(order_no, self.line_ids(order_no)[0])
        row = self.report()["rows"][0]
        self.assertEqual(row["value"], 110.0)
        self.assertEqual(row["vat"], 7.70)

    def test_a_bill_refunded_in_full_leaves_the_report(self):
        order_no, _, _ = self.paid_bill()
        self.refund(order_no, self.line_ids(order_no)[0])
        self.assertEqual(self.report()["rows"], [])

    def test_the_rows_are_numbered_in_order(self):
        self.paid_bill()
        self.paid_bill(invoice=True)
        rows = self.report()["rows"]
        self.assertEqual([row["no"] for row in rows], list(range(1, len(rows) + 1)))

    def test_the_header_names_the_shop_the_way_the_invoice_does(self):
        """สองที่ที่อ่านชื่อร้านคนละทาง คือสองชื่อร้านบนเอกสารที่ยื่นสรรพากร"""
        self.paid_bill()
        seller = self.report()["seller"]
        self.assertEqual(seller["name"], "ร้านทดสอบ จำกัด")
        self.assertEqual(seller["tax_id"], self.TAX_ID)
        self.assertEqual(seller["place"], "สำนักงานใหญ่")
        self.assertEqual(seller["branch_name"], "สาขาหลัก")

    def test_last_month_is_empty_when_the_shop_opened_this_month(self):
        self.paid_bill()
        today = dt.datetime.now(vat_report.BANGKOK).date()
        before = (today.replace(day=1) - dt.timedelta(days=1))
        report = self.report(f"{before.year:04d}-{before.month:02d}")
        self.assertEqual(report["rows"], [])
        self.assertEqual(report["totals"]["vat"], 0)


class TheNumbersForThePp30(VatCase):
    def test_the_output_tax_is_the_sum_of_the_rows(self):
        self.paid_bill()
        self.paid_bill(invoice=True)
        report = self.report()
        self.assertEqual(report["pp30"]["output_tax"], report["totals"]["vat"])
        self.assertEqual(report["pp30"]["taxable_sales"], report["totals"]["value"])

    def test_a_credit_note_lowers_the_tax_to_be_paid(self):
        order_no, _, number = self.paid_bill(qty=2, invoice=True)
        before = self.report()["pp30"]["output_tax"]
        given = self.refund(order_no, self.line_ids(order_no)[0])
        self.assertEqual(self.owner.post(f"/api/tax-invoices/{number}/credit-note",
                                         json={"branch_id": 1, "refund_id": given["id"]}
                                         ).status_code, 200)
        self.assertEqual(self.report()["pp30"]["output_tax"], round(before - 7.70, 2))

    def test_it_says_the_rate_it_used(self):
        self.paid_bill()
        self.assertEqual(self.report()["pp30"]["vat_rate"], 7.0)


class WhoMayReadIt(VatCase):
    def test_a_cashier_may_not(self):
        """รายงานนี้คือยอดขายทั้งเดือนของร้าน ไม่ใช่ของคนที่ยืนอยู่หน้าเครื่อง"""
        self.report(client=self.signed_in(2), expect=403)

    def test_a_guest_may_not(self):
        answer = TestClient(server.app).get("/api/reports/vat-sales?branch_id=1")
        self.assertEqual(answer.status_code, 401)

    def test_a_shop_that_is_not_registered_for_vat_is_told_so(self):
        """เอกสารนี้ยื่นต่อสรรพากร ร้านที่ไม่ได้จด VAT ไม่ควรได้ไฟล์ที่ดูเหมือนทำแล้ว"""
        self.set_shop(tax_id="")
        answer = self.report(expect=409)
        self.assertIn("จดทะเบียน VAT", answer.json()["detail"])


class TheFilesTheAccountantGets(VatCase):
    def read_csv(self, text):
        return list(csv.reader(io.StringIO(text)))

    def test_the_report_downloads_as_a_csv_excel_can_open(self):
        self.paid_bill()
        today = dt.datetime.now(vat_report.BANGKOK).date()
        answer = self.owner.get(f"/api/reports/vat-sales?branch_id=1&download=csv"
                                f"&month={today.year:04d}-{today.month:02d}")
        self.assertEqual(answer.status_code, 200, answer.text)
        self.assertIn("text/csv", answer.headers["content-type"])
        self.assertIn("attachment", answer.headers["content-disposition"])
        # Excel บนวินโดวส์ภาษาไทยอ่าน UTF-8 ได้ก็ต่อเมื่อมี BOM นำหน้า
        self.assertTrue(answer.content.startswith(b"\xef\xbb\xbf"))

    def test_it_carries_the_header_the_report_must_show(self):
        self.paid_bill()
        today = dt.datetime.now(vat_report.BANGKOK).date()
        text = self.owner.get(f"/api/reports/vat-sales?branch_id=1&download=csv"
                              f"&month={today.year:04d}-{today.month:02d}").content.decode("utf-8-sig")
        self.assertIn("รายงานภาษีขาย", text)
        self.assertIn("ร้านทดสอบ จำกัด", text)
        self.assertIn(self.TAX_ID, text)
        for column in vat_report.COLUMNS:
            self.assertIn(column, text)

    def test_the_bill_export_has_one_line_per_bill(self):
        self.paid_bill()
        self.paid_bill(invoice=True)
        answer = self.owner.get("/api/reports/bills-export?branch_id=1")
        self.assertEqual(answer.status_code, 200, answer.text)
        rows = self.read_csv(answer.content.decode("utf-8-sig"))
        self.assertEqual(rows[0], list(vat_report.BILL_COLUMNS))
        self.assertEqual(len(rows), 3)

    def test_the_bill_export_carries_the_tax_documents_of_each_bill(self):
        order_no, _, number = self.paid_bill(qty=2, invoice=True)
        given = self.refund(order_no, self.line_ids(order_no)[0])
        made = self.owner.post(f"/api/tax-invoices/{number}/credit-note",
                               json={"branch_id": 1, "refund_id": given["id"]}).json()
        rows = self.read_csv(self.owner.get(
            "/api/reports/bills-export?branch_id=1").content.decode("utf-8-sig"))
        line = rows[1]
        self.assertEqual(line[13], number)
        self.assertEqual(line[14], "บริษัท ลูกค้า จำกัด")
        self.assertEqual(line[16], made["number"])

    def test_the_bill_export_shows_what_was_given_back(self):
        order_no, total, _ = self.paid_bill(qty=2)
        given = self.refund(order_no, self.line_ids(order_no)[0])
        rows = self.read_csv(self.owner.get(
            "/api/reports/bills-export?branch_id=1").content.decode("utf-8-sig"))
        line = rows[1]
        self.assertEqual(line[10], f"{total / 100:.2f}")
        self.assertEqual(line[11], f"{given['amount']:.2f}")
        self.assertEqual(line[12], f"{(total - round(given['amount'] * 100)) / 100:.2f}")

    def test_a_bill_given_back_in_full_nets_nothing(self):
        order_no, total, _ = self.paid_bill()
        self.refund(order_no, self.line_ids(order_no)[0])
        rows = self.read_csv(self.owner.get(
            "/api/reports/bills-export?branch_id=1").content.decode("utf-8-sig"))
        self.assertEqual(rows[1][11], f"{total / 100:.2f}")
        self.assertEqual(rows[1][12], "0.00")

    def test_a_cashier_cannot_download_the_shops_whole_month(self):
        self.assertEqual(self.signed_in(2).get(
            "/api/reports/bills-export?branch_id=1").status_code, 403)

    def test_the_screen_is_served(self):
        answer = TestClient(server.app).get("/vat-report.js")
        self.assertEqual(answer.status_code, 200, answer.text)


if __name__ == "__main__":
    unittest.main()
