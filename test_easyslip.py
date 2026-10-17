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


def refusing_client(status, body):
    """EasySlip answering with one of its own error codes."""
    return httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(status, json=body)))


class EasySlipRefusalTests(unittest.TestCase):
    """What the shop is told when EasySlip says no.

    Every refusal used to read "ติดต่อ EasySlip ไม่สำเร็จ กรุณาลองใหม่", so a
    shop whose subscription had expired was told to check its connection and
    kept retrying something that could never work.
    """

    def _message(self, status, body):
        with refusing_client(status, body) as client:
            with self.assertRaises(SlipVerificationError) as caught:
                verify_bank_slip(IMAGE, Decimal("120.00"), "secret", client)
        return str(caught.exception)

    def test_an_expired_subscription_says_so(self):
        message = self._message(403, {"success": False, "error": {
            "code": "SERVICE_EXPIRED", "message": "Service has expired"}})
        self.assertIn("หมดอายุ", message)
        self.assertNotIn("ติดต่อ EasySlip ไม่สำเร็จ", message)

    def test_each_known_refusal_gets_its_own_wording(self):
        cases = {
            "INVALID_API_KEY": "API key",
            "QUOTA_EXCEEDED": "โควตา",
            "SLIP_NOT_FOUND": "อ่านสลิปนี้ไม่ออก",
            "SLIP_PENDING": "รอสักครู่",
            "RATE_LIMIT_EXCEEDED": "ถี่เกินไป",
        }
        for code, expected in cases.items():
            with self.subTest(code=code):
                message = self._message(400, {"success": False,
                                              "error": {"code": code, "message": "x"}})
                self.assertIn(expected, message)

    def test_an_unknown_code_is_shown_rather_than_hidden(self):
        message = self._message(418, {"success": False, "error": {
            "code": "BRAND_NEW_CODE", "message": "something new"}})
        self.assertIn("BRAND_NEW_CODE", message)

    def test_a_refusal_with_no_body_still_names_the_status(self):
        with httpx.Client(transport=httpx.MockTransport(
                lambda request: httpx.Response(502, text="<html>gateway</html>"))) as client:
            with self.assertRaises(SlipVerificationError) as caught:
                verify_bank_slip(IMAGE, Decimal("120.00"), "secret", client)
        self.assertIn("502", str(caught.exception))

    def test_only_a_transport_failure_says_it_could_not_connect(self):
        def explode(request):
            raise httpx.ConnectError("no route", request=request)
        with httpx.Client(transport=httpx.MockTransport(explode)) as client:
            with self.assertRaises(SlipVerificationError) as caught:
                verify_bank_slip(IMAGE, Decimal("120.00"), "secret", client)
        self.assertIn("ติดต่อ EasySlip ไม่สำเร็จ", str(caught.exception))


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
