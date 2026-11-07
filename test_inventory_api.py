import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import line_pos_server as server


class InventoryApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        server.DB_PATH = Path(self.temp.name) / 'inventory.db'
        server.PREVIEW_ONLY = False
        server.BOOTSTRAP_MANAGER_PIN = ''
        server.init_db()
        with closing(sqlite3.connect(server.DB_PATH)) as conn, conn:
            conn.execute("INSERT INTO branches(id,name) VALUES(1,'Test')")
        self.client = TestClient(server.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def test_restock_waste_and_idempotent_replay(self):
        manager = {'id':1,'branch_id':1,'role':'manager'}
        with patch.object(server, 'require_staff', return_value=manager):
            restock = {'event_id':'r1','branch_id':1,'ingredient_id':'RICE',
                       'action':'restock','quantity':10,'note':'delivery'}
            self.assertEqual(self.client.post('/api/inventory/movements', json=restock).json()['stock'], 10)
            self.assertEqual(self.client.post('/api/inventory/movements', json=restock).json()['status'], 'existing')
            waste = {**restock, 'event_id':'w1','action':'waste','quantity':2,'note':'spoiled'}
            self.assertEqual(self.client.post('/api/inventory/movements', json=waste).json()['stock'], 8)
            history = self.client.get('/api/inventory/movements?branch_id=1')
            self.assertEqual(history.status_code, 200)
            self.assertEqual(len(history.json()['items']), 2)
            self.assertEqual(self.client.get('/api/inventory?branch_id=1').json()['items'][0]['stock'], 8)


if __name__ == '__main__':
    unittest.main()
