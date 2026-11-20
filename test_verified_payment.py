"""Payment gateway boundary and atomic table close tests (no live API call)."""
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import line_pos_server as server


class VerifiedTablePaymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        server.DB_PATH = Path(self.temp.name) / 'payments.db'
        server.PREVIEW_ONLY = False
        server.BOOTSTRAP_MANAGER_PIN = ''
        server.init_db()
        with closing(sqlite3.connect(server.DB_PATH)) as conn, conn:
            conn.execute("INSERT INTO branches(id,name) VALUES(1,'Test')")
            for number, amount in [('O1', 60), ('O2', 40)]:
                conn.execute("INSERT INTO order_events(event_id,order_no,branch_id,table_no,total_amount) VALUES(?,?,?,?,?)",
                             ('create-' + number, number, 1, 'T1', amount))
        self.client = TestClient(server.app)
        self.client.__enter__()
        self.payload = {'event_id':'close-T1','branch_id':1,'table_no':'T1','order_nos':['O1','O2'],
                        'amount':100,'slip_image':'image-data'}

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def test_close_two_orders_and_reject_slip_reuse(self):
        with patch.object(server, 'require_staff', return_value={'id':1,'branch_id':1,'role':'cashier'}), \
             patch.object(server, 'verify_bank_slip', return_value='BANK-REF-1'), \
             patch.dict(server.os.environ, {'EASYSLIP_API_KEY':'test-key'}):
            response = self.client.post('/api/payments/close-table', json=self.payload)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['order_nos'], ['O1', 'O2'])
            replay = self.client.post('/api/payments/close-table', json=self.payload)
            self.assertEqual(replay.status_code, 200)
            self.assertTrue(replay.json()['existing'])
        with closing(sqlite3.connect(server.DB_PATH)) as conn, conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM pos_orders WHERE status='paid'").fetchone()[0], 2)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM table_payment_events").fetchone()[0], 1)

    def test_rejects_wrong_amount_before_gateway(self):
        with patch.object(server, 'require_staff', return_value={'id':1,'branch_id':1,'role':'cashier'}), \
             patch.object(server, 'verify_bank_slip') as verify, \
             patch.dict(server.os.environ, {'EASYSLIP_API_KEY':'test-key'}):
            response = self.client.post('/api/payments/close-table', json={**self.payload,'amount':99})
            self.assertEqual(response.status_code, 409)
            verify.assert_not_called()

    def test_rejects_without_gateway_key(self):
        with patch.object(server, 'require_staff', return_value={'id':1,'branch_id':1,'role':'cashier'}), \
             patch.dict(server.os.environ, {'EASYSLIP_API_KEY':''}):
            response = self.client.post('/api/payments/close-table', json=self.payload)
            self.assertEqual(response.status_code, 503)

    def test_rejects_same_slip_for_another_table(self):
        with closing(sqlite3.connect(server.DB_PATH)) as conn, conn:
            conn.execute("INSERT INTO order_events(event_id,order_no,branch_id,table_no,total_amount) VALUES(?,?,?,?,?)",
                         ('create-O3', 'O3', 1, 'T2', 100))
        with patch.object(server, 'require_staff', return_value={'id':1,'branch_id':1,'role':'cashier'}), \
             patch.object(server, 'verify_bank_slip', return_value='BANK-REF-1'), \
             patch.dict(server.os.environ, {'EASYSLIP_API_KEY':'test-key'}):
            self.assertEqual(self.client.post('/api/payments/close-table', json=self.payload).status_code, 200)
            second = self.client.post('/api/payments/close-table', json={**self.payload,
                'event_id':'close-T2','table_no':'T2','order_nos':['O3']})
            self.assertEqual(second.status_code, 409)
        with closing(sqlite3.connect(server.DB_PATH)) as conn:
            self.assertEqual(conn.execute("SELECT status FROM order_events WHERE order_no='O3'").fetchone()[0], 'open')

    def test_rejects_nonfinite_amount(self):
        with patch.object(server, 'require_staff', return_value={'id':1,'branch_id':1,'role':'cashier'}), \
             patch.dict(server.os.environ, {'EASYSLIP_API_KEY':'test-key'}):
            response = self.client.post('/api/payments/close-table', json={**self.payload,'amount':'NaN'})
            self.assertEqual(response.status_code, 400)


if __name__ == '__main__':
    unittest.main()
