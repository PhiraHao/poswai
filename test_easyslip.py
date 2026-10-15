import base64
import unittest
from decimal import Decimal

import httpx

from easyslip import SlipVerificationError, verify_bank_slip


IMAGE = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"test").decode()


def fake_client(data):
    def handler(request):
        assert request.url == "https://api.easyslip.com/v2/verify/bank"
        assert request.headers["Authorization"] == "Bearer secret"
        assert request.read().find(b'"matchAccount":true') >= 0
        return httpx.Response(200, json=data)
    return httpx.Client(transport=httpx.MockTransport(handler))


def good_data():
    return {"success": True, "data": {"isDuplicate": False, "matchedAccount": {"bankNumber": "123"},
        "isAmountMatched": True, "amountInSlip": 120.0,
        "rawSlip": {"transRef": "ABC123", "amount": {"local": {"currency": "THB"}}}}}


class EasySlipTests(unittest.TestCase):
    def test_accepts_verified_amount_receiver_and_unique_ref(self):
        with fake_client(good_data()) as client:
            self.assertEqual(verify_bank_slip(IMAGE, Decimal("120.00"), "secret", client), "ABC123")

    def test_rejects_duplicate_unmatched_account_and_wrong_amount(self):
        for change in ({"isDuplicate": True}, {"matchedAccount": None}, {"isAmountMatched": False}, {"amountInSlip": 119.0}):
            with self.subTest(change=change):
                data = good_data(); data["data"].update(change)
                with fake_client(data) as client:
                    with self.assertRaises(SlipVerificationError):
                        verify_bank_slip(IMAGE, Decimal("120.00"), "secret", client)

    def test_rejects_bad_image_or_unconfigured_key(self):
        with self.assertRaises(SlipVerificationError):
            verify_bank_slip("data:image/png;base64,bad!", Decimal("120"), "secret")
        with self.assertRaises(SlipVerificationError):
            verify_bank_slip(IMAGE, Decimal("120"), "")


if __name__ == "__main__":
    unittest.main()
