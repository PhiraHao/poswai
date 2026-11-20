import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from poswai_inventory import (InventoryError, apply_inventory_movement,
                              init_inventory_movements, list_inventory_movements)


class InventoryTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.db = Path(temp.name) / "stock.db"
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("CREATE TABLE branches (id INTEGER PRIMARY KEY)")
            conn.executemany("INSERT INTO branches VALUES (?)", [(1,), (2,)])
            conn.execute("""CREATE TABLE inventory (branch_id INTEGER,ingredient_id TEXT,
                stock REAL,PRIMARY KEY(branch_id,ingredient_id))""")
            conn.execute("INSERT INTO inventory VALUES(1,'ING01',10)")
            init_inventory_movements(conn)

    def move(self, **kwargs):
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            return apply_inventory_movement(conn, actor_staff_id=1, **kwargs)

    def stock(self):
        with closing(sqlite3.connect(self.db)) as conn:
            return dict(((row[0], row[1]), row[2]) for row in conn.execute(
                "SELECT branch_id,ingredient_id,stock FROM inventory"))

    def test_restock_is_persisted_and_idempotent(self):
        request = dict(event_id="receive-1", branch_id=1, ingredient_id="ING01",
                       action="restock", quantity=2.5, note="receipt 42")
        self.assertEqual(self.move(**request)["stock"], 12.5)
        self.assertEqual(self.move(**request)["status"], "existing")
        self.assertEqual(self.stock()[(1, "ING01")], 12.5)
        with self.assertRaises(InventoryError):
            self.move(**{**request, "quantity": 99})

    def test_waste_rejects_insufficient_and_cannot_go_negative(self):
        with self.assertRaises(InventoryError) as error:
            self.move(event_id="waste-1", branch_id=1, ingredient_id="ING01",
                      action="waste", quantity=11)
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(self.stock()[(1, "ING01")], 10)
        self.assertEqual(self.move(event_id="waste-2", branch_id=1,
                                   ingredient_id="ING01", action="waste", quantity=3)["stock"], 7)

    def test_transfer_is_two_sided_and_destination_must_exist(self):
        with self.assertRaises(InventoryError):
            self.move(event_id="bad-transfer", branch_id=1, ingredient_id="ING01",
                      action="transfer", quantity=2, target_branch_id=3)
        self.assertEqual(self.stock()[(1, "ING01")], 10)
        result = self.move(event_id="transfer-1", branch_id=1,
                           ingredient_id="ING01", action="transfer", quantity=2,
                           target_branch_id=2)
        self.assertEqual(result["stock"], 8)
        self.assertEqual(self.stock(), {(1, "ING01"): 8, (2, "ING01"): 2})
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(len(list_inventory_movements(conn, 1)), 1)
            self.assertEqual(len(list_inventory_movements(conn, 2)), 1)

    def test_invalid_quantity_and_action(self):
        for qty in (-1, 0, "nan", "inf", 1.1234567):
            with self.subTest(qty=qty), self.assertRaises(InventoryError):
                self.move(event_id="invalid", branch_id=1, ingredient_id="ING01",
                          action="restock", quantity=qty)
        with self.assertRaises(InventoryError):
            self.move(event_id="invalid", branch_id=1, ingredient_id="ING01",
                      action="purchase_order", quantity=1)


if __name__ == "__main__":
    unittest.main()
