import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from poswai_catalog import (
    CatalogError, deduct_inventory, init_catalog, list_menu_items,
    quote_order, upsert_menu_item,
)


class CatalogTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.db = Path(temp.name) / "catalog.db"
        with closing(sqlite3.connect(self.db)) as conn, conn:
            init_catalog(conn)
            conn.execute("""CREATE TABLE inventory (
                branch_id INTEGER, ingredient_id TEXT, stock REAL,
                PRIMARY KEY(branch_id,ingredient_id))""")
            upsert_menu_item(conn, 1, 1, "Noodles", "65.00",
                             [{"ingId": "flour", "qty": 0.25},
                              {"ingId": "egg", "qty": 1}])
            upsert_menu_item(conn, 1, 2, "Tea", "20.50",
                             [{"ingId": "tea", "qty": 0.1}])
            upsert_menu_item(conn, 2, 1, "Branch two noodles", "70", [])
            conn.executemany("INSERT INTO inventory VALUES (1,?,?)",
                             [("flour", 1), ("egg", 4), ("tea", 1)])

    def test_quote_ignores_forged_client_price_name_and_bom(self):
        with closing(sqlite3.connect(self.db)) as conn:
            quote = quote_order(conn, 1, [
                {"id": 1, "qty": 2, "name": "Free", "price": 0, "bom": []},
                {"id": 2, "qty": 1, "price": -100},
            ])
        self.assertEqual(quote["total_cents"], 15050)
        self.assertEqual(quote["items"][0]["name"], "Noodles")
        self.assertEqual(quote["items"][0]["price"], 65)
        self.assertEqual(quote["deductions"], {"egg": 2.0, "flour": 0.5, "tea": 0.1})

    def test_branch_isolation_inactive_and_invalid_quantities(self):
        with closing(sqlite3.connect(self.db)) as conn, conn:
            self.assertEqual(quote_order(conn, 2, [{"id": 1, "qty": 1}])["total_cents"], 7000)
            upsert_menu_item(conn, 1, 2, "Tea", 20.5, [], active=False)
            self.assertEqual(len(list_menu_items(conn, 1)), 1)
            with self.assertRaises(CatalogError):
                quote_order(conn, 1, [{"id": 2, "qty": 1}])
            for qty in (0, -1, 1.5, "nan", 1001):
                with self.subTest(qty=qty), self.assertRaises(CatalogError):
                    quote_order(conn, 1, [{"id": 1, "qty": qty}])

    def test_stock_atomic_rollback_when_one_ingredient_short(self):
        with closing(sqlite3.connect(self.db)) as conn:
            quote = quote_order(conn, 1, [{"id": 1, "qty": 2}])
            with self.assertRaises(CatalogError):
                deduct_inventory(conn, 1, {**quote["deductions"], "missing": 1})
            conn.rollback()
            self.assertEqual(dict(conn.execute("SELECT ingredient_id,stock FROM inventory")),
                             {"flour": 1, "egg": 4, "tea": 1})

    def test_bom_and_price_validation(self):
        with closing(sqlite3.connect(self.db)) as conn:
            for price in (-1, "nan", 1.001, "1000000.01"):
                with self.subTest(price=price), self.assertRaises(CatalogError):
                    upsert_menu_item(conn, 1, "bad", "Bad", price, [])
            for bom in ([{"ingId": "egg", "qty": -1}],
                        [{"ingId": "NONE", "qty": 1}],
                        [{"ingId": "egg", "qty": "nan"}]):
                with self.subTest(bom=bom), self.assertRaises(CatalogError):
                    upsert_menu_item(conn, 1, "bad", "Bad", 10, bom)


if __name__ == "__main__":
    unittest.main()
