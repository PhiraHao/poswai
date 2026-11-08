"""ใบกำกับภาษีเต็มรูป

เดิมเครื่องพิมพ์กระดาษที่เขียนว่า "ใบกำกับภาษีเต็มรูป" ซึ่งไม่ใช่ใบกำกับภาษี
สรรพากรต้องการเลขที่เอกสารที่ไม่ซ้ำไม่ข้าม ชื่อ-ที่อยู่-เลขภาษีของผู้ขาย
ชื่อ-เลขภาษีของผู้ซื้อ และ VAT แยกบรรทัด · ลูกค้าที่เก็บกระดาษใบนั้นไปจะรู้
ตอนปลายปีว่าใช้ไม่ได้ ซึ่งตอนนั้นเถียงอะไรไม่ได้แล้ว
"""

import datetime as dt
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import line_pos_server as server
import poswai_tax_invoice as tax_invoice

SHOP_TAX_ID = "0994000165510"
BUYER_TAX_ID = "0105536073183"


class InvoiceCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.directory.cleanup)
        server.DB_PATH = Path(self.directory.name) / "invoices.db"
        server.PREVIEW_ONLY = False
        server.BOOTSTRAP_MANAGER_PIN = ""
        server.TABLE_QR_SECRET = "e" * 48
        server.init_db()
        conn = sqlite3.connect(server.DB_PATH)
        with conn:
            conn.execute("INSERT INTO branches(id,name) VALUES(1,'Test')")
            for staff_id, role in ((1, "owner"), (2, "cashier")):
                conn.execute("INSERT INTO staffs(id,branch_id,name,role,pin_code_hash)"
                             " VALUES(?,1,?,?,?)",
                             (staff_id, role, role, server.hash_pin(f"secure-pin-{role}")))
        conn.close()
        self.conn = sqlite3.connect(server.DB_PATH)
        self.addCleanup(self.conn.close)

    def signed_in(self, staff_id=1, role="owner"):
        client = TestClient(server.app)
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        self.assertEqual(client.post("/api/auth/login",
                                     json={"staff_id": staff_id, "pin": f"secure-pin-{role}"}).status_code, 200)
        return client

    def registered_shop(self, client, **overrides):
        body = {"legal_name": "บริษัท ซีแซ่บ จำกัด", "address": "88 หมู่ 1 เชียงดาว",
                "tax_id": SHOP_TAX_ID, "vat_rate_bp": 700, "vat_inclusive": False}
        body.update(overrides)
        self.assertEqual(client.put("/api/shop/settings", json=body).status_code, 200)

    def paid_bill(self, order_no="B-1", *, subtotal=10000, vat=700, total=107.0):
        """A bill as the till would have left it: open event, items, payment."""
        with self.conn:
            self.conn.execute(
                "INSERT INTO order_events (event_id, order_no, branch_id, table_no, total_amount,"
                " status, subtotal_cents, discount_cents, service_charge_cents, vat_cents)"
                " VALUES (?,?,1,'1',?,'paid',?,0,0,?)",
                (f"e-{order_no}", order_no, total, subtotal, vat))
            self.conn.execute(
                "INSERT INTO order_items (order_no,item_id,name,quantity,unit_price,bom_json)"
                " VALUES (?,?,?,?,?,'[]')", (order_no, "M1", "ข้าวผัด", 1, 100))
            self.conn.execute(
                "INSERT INTO pos_orders (branch_id, order_no, closed_by_staff_id, total_amount,"
                " net_amount, payment_method, status) VALUES (1,?,2,?,?,'เงินสด (Cash)','paid')",
                (order_no, total, total))
        return order_no


class TheNumber(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        tax_invoice.init_tax_invoices(self.conn)

    def test_the_first_one_of_the_month_starts_at_one(self):
        self.assertEqual(tax_invoice.next_number(self.conn, dt.date(2026, 11, 9)), "2611-0001")

    def test_numbers_run_on_within_the_month(self):
        for n in range(1, 4):
            self.conn.execute("INSERT INTO tax_invoices (number, order_no, branch_id, issued_by,"
                              " buyer_name, seller_json, subtotal_cents, total_cents, lines_json)"
                              " VALUES (?,?,1,1,'x','{}',0,0,'[]')", (f"2611-{n:04d}", f"o{n}"))
        self.assertEqual(tax_invoice.next_number(self.conn, dt.date(2026, 11, 20)), "2611-0004")

    def test_a_new_month_starts_again_at_one(self):
        self.conn.execute("INSERT INTO tax_invoices (number, order_no, branch_id, issued_by,"
                          " buyer_name, seller_json, subtotal_cents, total_cents, lines_json)"
                          " VALUES ('2611-0007','o1',1,1,'x','{}',0,0,'[]')")
        self.assertEqual(tax_invoice.next_number(self.conn, dt.date(2026, 12, 1)), "2612-0001")

    def test_a_cancelled_invoice_still_burns_its_number(self):
        """A gap is a question the shop can answer; a reused number is not."""
        self.conn.execute("INSERT INTO tax_invoices (number, order_no, branch_id, issued_by,"
                          " buyer_name, seller_json, subtotal_cents, total_cents, lines_json,"
                          " cancelled_at) VALUES ('2611-0001','o1',1,1,'x','{}',0,0,'[]','now')")
        self.assertEqual(tax_invoice.next_number(self.conn, dt.date(2026, 11, 9)), "2611-0002")


class TheBuyersTaxId(unittest.TestCase):
    def test_a_real_number_passes(self):
        self.assertTrue(tax_invoice.valid_tax_id(BUYER_TAX_ID))

    def test_a_typo_is_caught(self):
        self.assertFalse(tax_invoice.valid_tax_id("0105536073184"))


class IssuingOne(InvoiceCase):
    def test_a_registered_shop_issues_a_numbered_invoice(self):
        owner = self.signed_in()
        self.registered_shop(owner)
        self.paid_bill()
        answer = owner.post("/api/tax-invoices", json={
            "branch_id": 1, "order_no": "B-1", "name": "บริษัท ลูกค้า จำกัด",
            "tax_id": BUYER_TAX_ID, "address": "1 ถนนสีลม กรุงเทพฯ"})
        self.assertEqual(answer.status_code, 200, answer.text)
        invoice = answer.json()
        self.assertTrue(invoice["number"].endswith("-0001"))
        self.assertEqual(invoice["seller"]["tax_id"], SHOP_TAX_ID)
        self.assertEqual(invoice["buyer"]["tax_id"], BUYER_TAX_ID)
        self.assertEqual(invoice["vat"], 7)
        self.assertEqual(invoice["total"], 107)
        self.assertEqual(invoice["lines"][0]["name"], "ข้าวผัด")

    def test_a_shop_with_no_tax_number_is_told_why_it_cannot(self):
        """Printing one anyway is how a shop finds out at the end of the year."""
        owner = self.signed_in()
        self.registered_shop(owner, tax_id="")
        self.paid_bill()
        refused = owner.post("/api/tax-invoices",
                             json={"branch_id": 1, "order_no": "B-1", "name": "ลูกค้า"})
        self.assertEqual(refused.status_code, 409)
        self.assertIn("เลขประจำตัวผู้เสียภาษี", refused.json()["detail"])

    def test_a_shop_with_no_address_is_refused_too(self):
        owner = self.signed_in()
        self.registered_shop(owner, address="")
        self.paid_bill()
        self.assertEqual(owner.post("/api/tax-invoices",
                                    json={"branch_id": 1, "order_no": "B-1",
                                          "name": "ลูกค้า"}).status_code, 409)

    def test_the_head_office_is_said_when_no_branch_was_set(self):
        owner = self.signed_in()
        self.registered_shop(owner)
        self.paid_bill()
        invoice = owner.post("/api/tax-invoices",
                             json={"branch_id": 1, "order_no": "B-1", "name": "ลูกค้า"}).json()
        self.assertEqual(invoice["seller"]["branch"], "สำนักงานใหญ่")

    def test_a_shop_that_is_a_branch_prints_its_own_number(self):
        owner = self.signed_in()
        self.registered_shop(owner, tax_branch="สาขาที่ 00002")
        self.paid_bill()
        invoice = owner.post("/api/tax-invoices",
                             json={"branch_id": 1, "order_no": "B-1", "name": "ลูกค้า"}).json()
        self.assertEqual(invoice["seller"]["branch"], "สาขาที่ 00002")

    def test_asking_twice_hands_back_the_same_document(self):
        """The customer asking again wants the document, not a second one that
        would not survive an audit."""
        owner = self.signed_in()
        self.registered_shop(owner)
        self.paid_bill()
        body = {"branch_id": 1, "order_no": "B-1", "name": "ลูกค้า"}
        first = owner.post("/api/tax-invoices", json=body).json()
        second = owner.post("/api/tax-invoices", json=body).json()
        self.assertEqual(first["number"], second["number"])
        self.assertEqual(first["id"], second["id"])

    def test_a_bill_that_was_never_paid_gets_no_invoice(self):
        owner = self.signed_in()
        self.registered_shop(owner)
        with self.conn:
            self.conn.execute(
                "INSERT INTO order_events (event_id, order_no, branch_id, table_no, total_amount,"
                " subtotal_cents, vat_cents) VALUES ('e-OPEN','OPEN',1,'1',107,10000,700)")
        refused = owner.post("/api/tax-invoices",
                             json={"branch_id": 1, "order_no": "OPEN", "name": "ลูกค้า"})
        self.assertEqual(refused.status_code, 409)

    def test_a_bill_that_does_not_exist_is_a_plain_not_found(self):
        owner = self.signed_in()
        self.registered_shop(owner)
        self.assertEqual(owner.post("/api/tax-invoices",
                                    json={"branch_id": 1, "order_no": "NOPE",
                                          "name": "ลูกค้า"}).status_code, 404)

    def test_a_buyer_needs_a_name(self):
        owner = self.signed_in()
        self.registered_shop(owner)
        self.paid_bill()
        self.assertEqual(owner.post("/api/tax-invoices",
                                    json={"branch_id": 1, "order_no": "B-1",
                                          "name": "  "}).status_code, 400)

    def test_a_wrong_buyer_tax_number_is_refused_before_it_is_printed(self):
        owner = self.signed_in()
        self.registered_shop(owner)
        self.paid_bill()
        self.assertEqual(owner.post("/api/tax-invoices",
                                    json={"branch_id": 1, "order_no": "B-1", "name": "ลูกค้า",
                                          "tax_id": "1111111111111"}).status_code, 400)

    def test_a_buyer_without_a_tax_number_may_still_have_one_issued(self):
        """A person, not a company, can still ask for the document."""
        owner = self.signed_in()
        self.registered_shop(owner)
        self.paid_bill()
        self.assertEqual(owner.post("/api/tax-invoices",
                                    json={"branch_id": 1, "order_no": "B-1",
                                          "name": "คุณสมชาย"}).status_code, 200)

    def test_a_cashier_may_issue_one_at_the_till(self):
        owner = self.signed_in()
        self.registered_shop(owner)
        self.paid_bill()
        till = self.signed_in(2, "cashier")
        self.assertEqual(till.post("/api/tax-invoices",
                                   json={"branch_id": 1, "order_no": "B-1",
                                         "name": "ลูกค้า"}).status_code, 200)


class ReprintingAndVoiding(InvoiceCase):
    def issued(self):
        owner = self.signed_in()
        self.registered_shop(owner)
        self.paid_bill()
        invoice = owner.post("/api/tax-invoices",
                             json={"branch_id": 1, "order_no": "B-1",
                                   "name": "บริษัท ลูกค้า จำกัด",
                                   "tax_id": BUYER_TAX_ID}).json()
        return owner, invoice

    def test_reprinting_hands_back_what_was_issued(self):
        owner, invoice = self.issued()
        again = owner.get(f"/api/tax-invoices/{invoice['number']}")
        self.assertEqual(again.status_code, 200, again.text)
        self.assertEqual(again.json()["buyer"]["name"], "บริษัท ลูกค้า จำกัด")

    def test_the_seller_on_the_document_does_not_move_when_the_shop_changes(self):
        """A shop that corrects its address next month must not change what it
        already handed a customer."""
        owner, invoice = self.issued()
        owner.put("/api/shop/settings", json={"address": "ที่อยู่ใหม่ 999"})
        again = owner.get(f"/api/tax-invoices/{invoice['number']}").json()
        self.assertEqual(again["seller"]["address"], "88 หมู่ 1 เชียงดาว")

    def test_a_number_nobody_issued_is_not_found(self):
        owner, _ = self.issued()
        self.assertEqual(owner.get("/api/tax-invoices/2611-9999").status_code, 404)

    def test_voiding_keeps_the_row_and_the_number(self):
        owner, invoice = self.issued()
        voided = owner.post(f"/api/tax-invoices/{invoice['number']}/cancel",
                            json={"reason": "ลูกค้าให้เลขภาษีผิด"})
        self.assertEqual(voided.status_code, 200, voided.text)
        self.assertTrue(voided.json()["cancelled_at"])
        self.assertEqual(voided.json()["cancel_reason"], "ลูกค้าให้เลขภาษีผิด")
        # Still readable, still numbered.
        self.assertEqual(owner.get(f"/api/tax-invoices/{invoice['number']}").status_code, 200)

    def test_voiding_needs_a_reason(self):
        owner, invoice = self.issued()
        self.assertEqual(owner.post(f"/api/tax-invoices/{invoice['number']}/cancel",
                                    json={"reason": " "}).status_code, 400)

    def test_voiding_twice_is_refused(self):
        owner, invoice = self.issued()
        owner.post(f"/api/tax-invoices/{invoice['number']}/cancel", json={"reason": "ผิด"})
        self.assertEqual(owner.post(f"/api/tax-invoices/{invoice['number']}/cancel",
                                    json={"reason": "ผิดอีก"}).status_code, 409)

    def test_a_cashier_cannot_void_one(self):
        owner, invoice = self.issued()
        till = self.signed_in(2, "cashier")
        self.assertEqual(till.post(f"/api/tax-invoices/{invoice['number']}/cancel",
                                   json={"reason": "ผิด"}).status_code, 403)

    def test_the_owner_sees_the_book_of_them(self):
        owner, invoice = self.issued()
        listing = owner.get("/api/tax-invoices?branch_id=1")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json()["invoices"][0]["number"], invoice["number"])

    def test_a_cashier_cannot_read_the_whole_book(self):
        owner, _ = self.issued()
        self.assertEqual(self.signed_in(2, "cashier").get("/api/tax-invoices?branch_id=1").status_code, 403)


if __name__ == "__main__":
    unittest.main()
