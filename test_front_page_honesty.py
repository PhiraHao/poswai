"""Guards for three things the page used to get wrong in a real shop.

None of this is reachable from Python at runtime — it is browser code — but
all three were silent failures that no one noticed for weeks, and a text
assertion costs nothing next to a shop printing an illegal receipt.
"""
import re
import unittest
from pathlib import Path

HERE = Path(__file__).parent
INDEX = (HERE / "index.html").read_text(encoding="utf-8")
LIVE = (HERE / "live-data.js").read_text(encoding="utf-8")
WORKER = (HERE / "service-worker.js").read_text(encoding="utf-8")


class ReceiptNamesWhatTheShopMayIssue(unittest.TestCase):
    """A shop with no VAT registration may not print "ใบกำกับภาษี" at all."""

    def test_title_is_chosen_not_hard_coded(self):
        self.assertIn("function receiptDocTitle", INDEX)
        self.assertIn("printReceiptForTable(tStr, receiptDocTitle(method), false)", INDEX)

    def test_tax_wording_only_behind_the_check(self):
        # Every mention of the phrase has to sit inside the helper that asks
        # whether the shop is registered.
        helper = INDEX[INDEX.index("function shopIssuesTaxReceipt"):
                       INDEX.index("function getTableGrandTotalWithTax")]
        self.assertEqual(INDEX.count("ใบกำกับภาษีอย่างย่อ"),
                         helper.count("ใบกำกับภาษีอย่างย่อ"))

    def test_registration_needs_both_a_number_and_a_rate(self):
        helper = INDEX[INDEX.index("function shopIssuesTaxReceipt"):
                       INDEX.index("function receiptDocTitle")]
        self.assertIn("tax_id", helper)
        self.assertIn("vat_rate_bp", helper)


class LiveModeKeepsNoSampleRecords(unittest.TestCase):
    """A real shop must not read the sample shop's history, orders or tables."""

    def test_the_three_that_were_missed_are_cleared(self):
        live = LIVE[LIVE.index("const enterLive"):]
        live = live[:live.index("const KEY")]
        for key in ("state.auditLogs", "state.deliveryLogs", "state.tablesList"):
            self.assertIn(key, live, f"{key} survives into live mode")

    def test_table_picker_invents_no_zone_names(self):
        self.assertIn("loadRealTables", LIVE)
        # The fallback list carries empty zones; names like "VIP" would be
        # someone else's floor plan.
        self.assertIn("zone: ''", LIVE)

    def test_no_placeholder_buttons_left(self):
        self.assertNotIn("ยังไม่พร้อม", INDEX)


class OfflineCacheMatchesThePage(unittest.TestCase):
    """ignoreSearch:true means a stale ?v= is served instead of the real file."""

    @staticmethod
    def versions(text, quoted):
        pattern = (r'"/([A-Za-z0-9._-]+\.(?:js|css))\?v=(\d+)"' if quoted
                   else r"/?([A-Za-z0-9._-]+\.(?:js|css))\?v=(\d+)")
        found = {}
        for name, version in re.findall(pattern, text):
            found.setdefault(name, set()).add(version)
        return found

    def test_every_cached_file_is_the_version_the_page_asks_for(self):
        page = self.versions(INDEX, quoted=False)
        for name, cached in self.versions(WORKER, quoted=True).items():
            if name in page:
                self.assertTrue(cached <= page[name],
                                f"{name}: cache has {cached}, page asks {page[name]}")

    def test_the_screens_needed_offline_are_cached(self):
        for name in ("guest-ui.js", "guest-ui.css", "offline-review.js"):
            self.assertIn(f'"/{name}', WORKER, f"{name} is missing when the net drops")


if __name__ == "__main__":
    unittest.main()
