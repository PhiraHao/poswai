"""Signing in from the POS WAI app, where there is no cookie jar.

The app ships its own pages, so every call it makes to a shop's server is
cross-origin and no cookie survives the trip — iOS refuses one outright. These
tests pin the swap down from both sides: the app's header is accepted, the
page's cookie still works exactly as before, and a finished Google sign-in comes
back over the app's own link rather than landing on a web page.
"""

import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient

import line_pos_server as server
import poswai_mobile as mobile
import poswai_owner_auth as owner_auth

GOOGLE_ID = "poswai.apps.googleusercontent.com"
APP_HEADERS = {mobile.APP_HEADER: "1"}


class AppSessionTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.folder.cleanup)
        for item in (patch.object(server, "DB_PATH", Path(self.folder.name) / "main.db"),
                     patch.object(server, "PREVIEW_ONLY", False),
                     patch.object(server, "STAFF_LIVE", True),
                     patch.object(server, "BOOTSTRAP_MANAGER_PIN", ""),
                     patch.object(server, "TABLE_QR_SECRET", "x" * 40),
                     patch.object(server, "GOOGLE_CLIENT_ID", GOOGLE_ID),
                     patch.object(server, "GOOGLE_CLIENT_SECRET", "google-secret"),
                     patch.object(server, "PUBLIC_BASE_URL", "https://poswai.example.com"),
                     patch.object(server, "_prepared_databases", set())):
            item.start()
            self.addCleanup(item.stop)
        server.init_db()
        self.pin = "cashier-pin-9876"
        with sqlite3.connect(server.DB_PATH) as conn:
            conn.execute("INSERT INTO branches(id,name) VALUES(1,'Main')")
            conn.execute(
                "INSERT INTO staffs(id,branch_id,name,role,pin_code_hash) VALUES(1,1,'ฟ้า','owner',?)",
                (server.hash_pin(self.pin),))
        self.google = {"aud": GOOGLE_ID, "iss": "https://accounts.google.com", "sub": "G-owner",
                       "exp": time.time() + 600, "email": "owner@gmail.com",
                       "email_verified": "true", "name": "เจ้าของร้าน"}
        for item in (patch.object(owner_auth, "_post_form", self._post_form),
                     patch.object(owner_auth, "_get_json", self._get_json)):
            item.start()
            self.addCleanup(item.stop)

    def _post_form(self, url, data):
        return {"id_token": "signed-by-the-provider", "access_token": "opaque"}

    def _get_json(self, url, params):
        return dict(self.google)

    def client(self):
        client = TestClient(server.app, base_url="https://poswai.example.com")
        client.__enter__()
        self.addCleanup(lambda: client.__exit__(None, None, None))
        return client

    def login(self, client, headers=None):
        return client.post("/api/auth/login", json={"staff_id": 1, "pin": self.pin},
                           headers=headers or {})

    # ------------------------------------------------------- the staff session
    def test_app_login_is_handed_the_token(self):
        body = self.login(self.client(), APP_HEADERS).json()
        self.assertEqual(len(body["session"]), 64)

    def test_the_page_is_never_handed_the_token(self):
        """A browser keeps httponly; handing it the token would give that up."""
        self.assertNotIn("session", self.login(self.client()).json())

    def test_an_app_origin_alone_is_enough(self):
        """A phone whose request loses the header is still recognisably the app."""
        body = self.login(self.client(), {"origin": mobile.APP_ORIGINS[0]}).json()
        self.assertEqual(len(body["session"]), 64)

    def test_the_header_opens_the_shop(self):
        client = self.client()
        token = self.login(client, APP_HEADERS).json()["session"]
        client.cookies.clear()          # the app has no cookie jar at all
        seen = client.get("/api/auth/session", headers={mobile.STAFF_HEADER: token})
        self.assertEqual(seen.status_code, 200, seen.text)
        self.assertEqual(seen.json()["name"], "ฟ้า")

    def test_no_session_at_all_is_refused(self):
        self.assertEqual(self.client().get("/api/auth/session").status_code, 401)

    def test_a_made_up_token_is_refused(self):
        seen = self.client().get("/api/auth/session", headers={mobile.STAFF_HEADER: "a" * 64})
        self.assertEqual(seen.status_code, 401)

    def test_the_cookie_still_works(self):
        """The web page is untouched by any of this."""
        client = self.client()
        self.login(client)
        self.assertEqual(client.get("/api/auth/session").status_code, 200)

    def test_logging_out_by_header_closes_the_session(self):
        client = self.client()
        token = self.login(client, APP_HEADERS).json()["session"]
        client.cookies.clear()
        headers = {mobile.STAFF_HEADER: token}
        self.assertEqual(client.post("/api/auth/logout", headers=headers).status_code, 200)
        self.assertEqual(client.get("/api/auth/session", headers=headers).status_code, 401)

    def test_the_app_writes_without_an_origin_check(self):
        """The origin check guards the cookie against other sites. A header is
        never sent automatically, so the app needs no such guard — and must not
        be refused for lacking a matching origin."""
        client = self.client()
        token = self.login(client, APP_HEADERS).json()["session"]
        client.cookies.clear()
        seen = client.post("/api/attendance", json={"staff_id": 1, "kind": "in"},
                           headers={mobile.STAFF_HEADER: token, "origin": mobile.APP_ORIGINS[0]})
        self.assertNotEqual(seen.status_code, 403, seen.text)

    # -------------------------------------------------- several screens at once
    def sign_in_as(self, staff_id, pin):
        """A fresh device: its own client, no cookie, the token it was handed."""
        token = self.client().post("/api/auth/login", json={"staff_id": staff_id, "pin": pin},
                                   headers=APP_HEADERS).json()["session"]
        return {mobile.STAFF_HEADER: token}

    def still_in(self, headers):
        return self.client().get("/api/auth/session", headers=headers).status_code == 200

    def test_two_devices_stay_signed_in_together(self):
        """The owner's computer and the app on their phone, side by side. Signing
        in on one used to sign the other out."""
        computer = self.sign_in_as(1, self.pin)
        phone = self.sign_in_as(1, self.pin)
        self.assertTrue(self.still_in(computer))
        self.assertTrue(self.still_in(phone))

    def test_only_the_oldest_device_beyond_the_limit_is_let_go(self):
        devices = [self.sign_in_as(1, self.pin) for _ in range(server.STAFF_DEVICE_LIMIT + 1)]
        self.assertFalse(self.still_in(devices[0]))
        self.assertTrue(all(self.still_in(device) for device in devices[1:]))

    def test_a_new_pin_still_signs_out_every_device(self):
        """Several devices is a convenience; a changed PIN must still end them all."""
        with sqlite3.connect(server.DB_PATH) as conn:
            conn.execute("INSERT INTO staffs(id,branch_id,name,role,pin_code_hash) VALUES(2,1,'แคชเชียร์','cashier',?)",
                         (server.hash_pin("cashier-old-pin"),))
        till = self.sign_in_as(2, "cashier-old-pin")
        tablet = self.sign_in_as(2, "cashier-old-pin")
        owner = self.sign_in_as(1, self.pin)
        changed = self.client().put("/api/staff/2/pin", json={"pin": "cashier-new-pin"}, headers=owner)
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertFalse(self.still_in(till))
        self.assertFalse(self.still_in(tablet))
        self.assertTrue(self.still_in(owner))

    # ----------------------------------------------------- the owner's sign-in
    def app_sign_in(self, client):
        started = client.get("/api/owner/auth/google/start", params={"app": "1"},
                             follow_redirects=False)
        self.assertEqual(started.status_code, 302, started.text)
        query = parse_qs(urlsplit(started.headers["location"]).query)
        self.google["nonce"] = query["nonce"][0]
        return client.get("/api/owner/auth/google/callback",
                          params={"code": "auth-code", "state": query["state"][0]},
                          follow_redirects=False)

    def test_the_sign_in_comes_back_over_the_app_link(self):
        landed = urlsplit(self.app_sign_in(self.client()).headers["location"])
        self.assertEqual(landed.scheme, mobile.APP_LINK_SCHEME)
        self.assertEqual(landed.netloc, "auth")
        handed = parse_qs(landed.query)
        self.assertEqual(len(handed["owner"][0]), 64)
        # No shop is linked to a brand-new account, so the app opens sign-up.
        self.assertEqual(handed["outcome"][0], "new")
        self.assertNotIn("shop", handed)

    def test_the_handed_token_opens_the_owner_session(self):
        client = self.client()
        token = parse_qs(urlsplit(self.app_sign_in(client).headers["location"]).query)["owner"][0]
        client.cookies.clear()
        seen = client.get("/api/owner/session", headers={mobile.OWNER_HEADER: token})
        self.assertEqual(seen.status_code, 200, seen.text)
        self.assertEqual(seen.json()["account"]["email"], "owner@gmail.com")

    def test_the_web_sign_in_still_lands_on_a_page(self):
        client = self.client()
        started = client.get("/api/owner/auth/google/start", follow_redirects=False)
        query = parse_qs(urlsplit(started.headers["location"]).query)
        self.google["nonce"] = query["nonce"][0]
        landed = client.get("/api/owner/auth/google/callback",
                            params={"code": "auth-code", "state": query["state"][0]},
                            follow_redirects=False)
        self.assertEqual(urlsplit(landed.headers["location"]).scheme, "")
        self.assertIn(server.OWNER_COOKIE, landed.cookies)

    def test_linking_a_provider_cannot_come_from_the_app(self):
        """mode=link needs the staff session the web page holds, not an app link."""
        seen = self.client().get("/api/owner/auth/google/start",
                                 params={"app": "1", "mode": "link"}, follow_redirects=False)
        self.assertEqual(seen.status_code, 400)

    def test_a_replayed_app_callback_is_refused(self):
        client = self.client()
        started = client.get("/api/owner/auth/google/start", params={"app": "1"},
                             follow_redirects=False)
        query = parse_qs(urlsplit(started.headers["location"]).query)
        self.google["nonce"] = query["nonce"][0]
        state = query["state"][0]
        first = client.get("/api/owner/auth/google/callback",
                           params={"code": "auth-code", "state": state}, follow_redirects=False)
        self.assertEqual(urlsplit(first.headers["location"]).scheme, mobile.APP_LINK_SCHEME)
        again = client.get("/api/owner/auth/google/callback",
                           params={"code": "auth-code", "state": state}, follow_redirects=False)
        self.assertIn("owner_error", again.headers["location"])

    # ------------------------------------------------------------ the app link
    def test_the_app_link_drops_what_did_not_happen(self):
        self.assertEqual(mobile.app_link("auth", owner="t", shop="", outcome=None),
                         "poswai://auth?owner=t")


if __name__ == "__main__":
    unittest.main()
