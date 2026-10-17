"""Owners and staff signing in with a LINE or Google account instead of typing a PIN.

The providers are stood in for at the one place the server talks to them, so the
state, nonce and claim checks are the real ones under test.
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
import poswai_owner_auth as owner_auth

LINE_ID = "2012039182"
GOOGLE_ID = "poswai.apps.googleusercontent.com"


def line_claims(**overrides) -> dict:
    claims = {"aud": LINE_ID, "sub": "U-owner", "exp": time.time() + 600,
              "email": "owner@example.com", "name": "เจ้าของร้าน"}
    claims.update(overrides)
    return claims


def google_claims(**overrides) -> dict:
    claims = {"aud": GOOGLE_ID, "iss": "https://accounts.google.com", "sub": "G-owner",
              "exp": time.time() + 600, "email": "owner@gmail.com", "email_verified": "true",
              "name": "เจ้าของร้าน"}
    claims.update(overrides)
    return claims


class OwnerAccountTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.folder.cleanup)
        for item in (patch.object(server, "DB_PATH", Path(self.folder.name) / "main.db"),
                     patch.object(server, "PREVIEW_ONLY", False),
                     patch.object(server, "STAFF_LIVE", True),
                     patch.object(server, "BOOTSTRAP_MANAGER_PIN", ""),
                     patch.object(server, "TABLE_QR_SECRET", "x" * 40),
                     patch.object(server, "LINE_LOGIN_CHANNEL_ID", LINE_ID),
                     patch.object(server, "LINE_LOGIN_CHANNEL_SECRET", "line-secret"),
                     patch.object(server, "GOOGLE_CLIENT_ID", GOOGLE_ID),
                     patch.object(server, "GOOGLE_CLIENT_SECRET", "google-secret"),
                     patch.object(server, "PUBLIC_BASE_URL", "https://poswai.example.com"),
                     patch.object(server, "_prepared_databases", set())):
            item.start()
            self.addCleanup(item.stop)
        server.init_db()
        with sqlite3.connect(server.DB_PATH) as conn:
            conn.execute("INSERT INTO branches(id,name) VALUES(1,'Main')")
            conn.execute("INSERT INTO staffs(id,branch_id,name,role,pin_code_hash) VALUES(1,1,'เดิม','owner',?)",
                         (server.hash_pin("main-owner-pin"),))
        # The claims each provider will hand back, swapped per test.
        self.line = line_claims()
        self.google = google_claims()
        for item in (patch.object(owner_auth, "_post_form", self._post_form),
                     patch.object(owner_auth, "_get_json", self._get_json)):
            item.start()
            self.addCleanup(item.stop)

    # ---------------------------------------------------------------- stand-ins
    def _post_form(self, url, data):
        if url in (owner_auth.LINE_TOKEN_URL, owner_auth.GOOGLE_TOKEN_URL):
            self.assertEqual(data["grant_type"], "authorization_code")
            self.assertTrue(data["client_secret"])
            return {"id_token": "signed-by-the-provider", "access_token": "opaque"}
        if url == owner_auth.LINE_VERIFY_URL:
            claims = dict(self.line)
            claims.setdefault("nonce", data["nonce"])
            return claims
        raise AssertionError(f"unexpected provider call: {url}")

    def _get_json(self, url, params):
        if url == owner_auth.GOOGLE_TOKENINFO_URL:
            return dict(self.google)
        raise AssertionError(f"unexpected provider call: {url}")

    # ------------------------------------------------------------------ helpers
    def client(self):
        client = TestClient(server.app, base_url="https://poswai.example.com")
        client.__enter__()
        self.addCleanup(lambda: client.__exit__(None, None, None))
        return client

    def start(self, client, provider="line", **params):
        return client.get(f"/api/owner/auth/{provider}/start", params=params, follow_redirects=False)

    def handshake(self, client, provider="line", **params):
        """Begin a sign-in and return the state and nonce the provider was given."""
        response = self.start(client, provider, **params)
        self.assertEqual(response.status_code, 302, response.text)
        query = parse_qs(urlsplit(response.headers["location"]).query)
        return query["state"][0], query["nonce"][0]

    def callback(self, client, provider="line", *, state, code="auth-code"):
        return client.get(f"/api/owner/auth/{provider}/callback",
                          params={"code": code, "state": state}, follow_redirects=False)

    def sign_in(self, client, provider="line", **params):
        state, nonce = self.handshake(client, provider, **params)
        if provider == "google":
            self.google["nonce"] = nonce
        return self.callback(client, provider, state=state)

    def signup(self, client, slug, name="ร้านทดสอบ", pin="owner-pin-123"):
        return client.post("/api/shops", json={"shop_name": name, "slug": slug,
                                               "owner_name": "เจ้าของ", "phone": "0812345678",
                                               "pin": pin, "accept_terms": True},
                           headers={"x-forwarded-for": f"10.0.0.{len(slug)}"})

    def destination(self, response):
        return response.headers.get("location", "")

    def staff_sign_in(self, client, provider="line", **params):
        """Send a member of staff out through a provider and bring them back."""
        response = client.get(f"/api/staff/auth/{provider}/start", params=params,
                              follow_redirects=False)
        self.assertEqual(response.status_code, 302, response.text)
        query = parse_qs(urlsplit(response.headers["location"]).query)
        if provider == "google":
            self.google["nonce"] = query["nonce"][0]
        return self.callback(client, provider, state=query["state"][0])

    # -------------------------------------------------------- refusing bad paths
    def test_a_channel_without_keys_cannot_be_started(self):
        with patch.object(server, "GOOGLE_CLIENT_SECRET", ""):
            self.assertEqual(self.start(self.client(), "google").status_code, 503)

    def test_an_unknown_provider_is_refused(self):
        self.assertEqual(self.start(self.client(), "facebook").status_code, 404)
        unknown = self.client().get("/api/owner/auth/facebook/callback",
                                    params={"code": "x", "state": "y"}, follow_redirects=False)
        self.assertEqual(unknown.status_code, 303)
        self.assertIn("owner_error=provider_unknown", self.destination(unknown))

    def test_the_provider_is_sent_a_state_and_a_nonce(self):
        response = self.start(self.client(), "line")
        location = urlsplit(response.headers["location"])
        query = parse_qs(location.query)
        self.assertEqual(location.netloc, "access.line.me")
        self.assertEqual(query["client_id"], [LINE_ID])
        self.assertEqual(query["redirect_uri"],
                         ["https://poswai.example.com/api/owner/auth/line/callback"])
        self.assertTrue(len(query["state"][0]) >= 32 and len(query["nonce"][0]) >= 16)
        self.assertNotEqual(query["state"][0], query["nonce"][0])

    def test_a_state_the_server_never_issued_is_refused(self):
        browser = self.client()
        response = self.callback(browser, state="made-up-state")
        self.assertIn("owner_error=state", self.destination(response))
        self.assertEqual(browser.get("/api/owner/session").status_code, 401)

    def test_a_state_is_good_for_one_callback_only(self):
        browser = self.client()
        state, _ = self.handshake(browser)
        self.assertIn("owner=new", self.destination(self.callback(browser, state=state)))
        replay = self.callback(self.client(), state=state)
        self.assertIn("owner_error=state", self.destination(replay))

    def test_an_expired_state_is_refused(self):
        browser = self.client()
        state, _ = self.handshake(browser)
        with patch.object(owner_auth, "STATE_LIFETIME", -1):
            response = self.callback(browser, state=state)
        self.assertIn("owner_error=state", self.destination(response))

    def test_a_state_cannot_be_spent_on_another_provider(self):
        browser = self.client()
        state, _ = self.handshake(browser, "line")
        response = self.callback(browser, "google", state=state)
        self.assertIn("owner_error=state", self.destination(response))

    def test_an_identity_token_for_another_channel_is_refused(self):
        self.line = line_claims(aud="2099999999")
        browser = self.client()
        self.assertIn("owner_error=id_token", self.destination(self.sign_in(browser)))
        self.assertEqual(browser.get("/api/owner/session").status_code, 401)

    def test_an_identity_token_from_another_request_is_refused(self):
        self.line = line_claims(nonce="a-nonce-from-somewhere-else")
        self.assertIn("owner_error=nonce", self.destination(self.sign_in(self.client())))

    def test_an_expired_identity_token_is_refused(self):
        self.line = line_claims(exp=time.time() - 5)
        self.assertIn("owner_error=id_token", self.destination(self.sign_in(self.client())))

    def test_a_google_identity_from_the_wrong_issuer_is_refused(self):
        self.google = google_claims(iss="https://evil.example.com")
        self.assertIn("owner_error=id_token", self.destination(self.sign_in(self.client(), "google")))

    def test_a_google_account_without_a_verified_email_signs_in_without_one(self):
        self.google = google_claims(email_verified=False)
        browser = self.client()
        self.sign_in(browser, "google")
        self.assertEqual(browser.get("/api/owner/session").json()["account"]["email"], "")

    # ------------------------------------------------------------ the happy path
    def test_a_first_sign_in_without_a_shop_opens_the_sign_up_form(self):
        browser = self.client()
        response = self.sign_in(browser)
        self.assertEqual(self.destination(response), "/?owner=new")
        session = browser.get("/api/owner/session").json()
        self.assertEqual(session["account"]["email"], "owner@example.com")
        self.assertEqual(session["shops"], [])

    def test_a_shop_opened_from_an_account_needs_no_shop_code_next_time(self):
        browser = self.client()
        self.sign_in(browser)
        opened = self.signup(browser, "ban-kaew")
        self.assertEqual(opened.status_code, 200, opened.text)
        self.assertTrue(opened.json()["linked_account"])
        self.assertEqual([shop["slug"] for shop in browser.get("/api/owner/session").json()["shops"]],
                         ["ban-kaew"])
        # A fresh device, with only the account: straight into the one shop it owns.
        later = self.client()
        arrival = self.sign_in(later)
        self.assertEqual(self.destination(arrival), "/?shop=ban-kaew&owner=enter")
        entered = later.post("/api/owner/enter", json={"slug": "ban-kaew"})
        self.assertEqual(entered.status_code, 200, entered.text)
        self.assertEqual((entered.json()["role"], entered.json()["staff_id"]), ("owner", 1))
        self.assertEqual(later.get("/api/auth/session").json()["role"], "owner")
        self.assertEqual(later.get("/api/config").json()["shop"]["slug"], "ban-kaew")

    def test_two_shops_are_offered_as_a_choice(self):
        browser = self.client()
        self.sign_in(browser)
        self.signup(browser, "ban-kaew")
        self.signup(browser, "ban-suan", name="ร้านสวน")
        later = self.client()
        self.assertEqual(self.destination(self.sign_in(later)), "/?owner=choose")
        self.assertEqual(sorted(shop["slug"] for shop in later.get("/api/owner/session").json()["shops"]),
                         ["ban-kaew", "ban-suan"])
        entered = later.post("/api/owner/enter", json={"slug": "ban-suan"})
        self.assertEqual(entered.json()["shop"]["name"], "ร้านสวน")
        self.assertEqual(later.get("/api/config").json()["shop"]["slug"], "ban-suan")

    def test_a_shop_the_account_does_not_own_cannot_be_entered(self):
        self.signup(self.client(), "someone-else")
        intruder = self.client()
        self.sign_in(intruder)
        refused = intruder.post("/api/owner/enter", json={"slug": "someone-else"})
        self.assertEqual(refused.status_code, 403, refused.text)
        self.assertEqual(intruder.get("/api/auth/session").status_code, 401)

    def test_entering_needs_an_account_session(self):
        self.signup(self.client(), "ban-kaew")
        self.assertEqual(self.client().post("/api/owner/enter", json={"slug": "ban-kaew"}).status_code, 401)

    def test_a_suspended_shop_cannot_be_entered(self):
        browser = self.client()
        self.sign_in(browser)
        self.signup(browser, "ban-kaew")
        server.shops.set_status(server.DB_PATH, "ban-kaew", "suspended", "ยังไม่ชำระค่าบริการ")
        refused = browser.post("/api/owner/enter", json={"slug": "ban-kaew"})
        self.assertEqual(refused.status_code, 403)
        self.assertIn("ยังไม่ชำระค่าบริการ", refused.json()["detail"])

    def test_signing_out_of_the_account_forgets_it(self):
        browser = self.client()
        self.sign_in(browser)
        self.assertEqual(browser.post("/api/owner/logout").status_code, 200)
        self.assertEqual(browser.get("/api/owner/session").status_code, 401)

    # ------------------------------------------- moving an existing shop across
    def test_linking_an_account_is_only_for_the_shop_owner(self):
        owner = self.client()
        self.signup(owner, "ban-kaew")
        owner.post("/api/staff", json={"name": "แคชเชียร์", "role": "cashier", "pin": "cashier-pin-1"})
        self.assertEqual(self.start(self.client(), "line", mode="link").status_code, 401)
        cashier = self.client()
        signed = cashier.post("/api/auth/login", json={"shop": "ban-kaew", "staff_id": 2,
                                                       "pin": "cashier-pin-1"})
        self.assertEqual(signed.status_code, 200, signed.text)
        self.assertEqual(self.start(cashier, "line", mode="link").status_code, 403)

    def test_an_existing_shop_moves_to_an_account_without_losing_the_shop(self):
        owner = self.client()
        self.signup(owner, "ban-kaew")
        linked = self.sign_in(owner, "line", mode="link")
        self.assertEqual(self.destination(linked), "/?shop=ban-kaew&owner=linked")
        accounts = owner.get("/api/shop/owner-accounts").json()
        self.assertTrue(accounts["linkable"])
        self.assertEqual([(row["provider"], row["email"]) for row in accounts["accounts"]],
                         [("line", "owner@example.com")])
        # The shop code and PIN still work, and so does the account now.
        pin = self.client()
        self.assertEqual(pin.post("/api/auth/login", json={"shop": "ban-kaew", "staff_id": 1,
                                                           "pin": "owner-pin-123"}).status_code, 200)
        account = self.client()
        self.assertEqual(self.destination(self.sign_in(account)), "/?shop=ban-kaew&owner=enter")
        self.assertEqual(account.post("/api/owner/enter", json={"slug": "ban-kaew"}).json()["role"], "owner")

    def test_one_shop_can_have_two_owners_and_an_owner_two_channels(self):
        owner = self.client()
        self.signup(owner, "ban-kaew")
        self.sign_in(owner, "line", mode="link")
        self.google["nonce"] = None
        self.sign_in(owner, "google", mode="link")
        self.line = line_claims(sub="U-partner", email="partner@example.com", name="หุ้นส่วน")
        self.sign_in(owner, "line", mode="link")
        accounts = owner.get("/api/shop/owner-accounts").json()["accounts"]
        self.assertEqual(sorted((row["provider"], row["email"]) for row in accounts),
                         [("google", "owner@gmail.com"), ("line", "owner@example.com"),
                          ("line", "partner@example.com")])
        partner = self.client()
        self.assertEqual(self.destination(self.sign_in(partner)), "/?shop=ban-kaew&owner=enter")

    def test_an_account_can_be_unlinked_again(self):
        owner = self.client()
        self.signup(owner, "ban-kaew")
        self.sign_in(owner, "line", mode="link")
        account_id = owner.get("/api/shop/owner-accounts").json()["accounts"][0]["id"]
        self.assertEqual(owner.delete(f"/api/shop/owner-accounts/{account_id}").status_code, 200)
        self.assertEqual(owner.get("/api/shop/owner-accounts").json()["accounts"], [])
        self.assertEqual(owner.delete(f"/api/shop/owner-accounts/{account_id}").status_code, 404)
        # Unlinked, the account no longer opens the shop; the PIN login is untouched.
        account = self.client()
        self.assertEqual(self.destination(self.sign_in(account)), "/?owner=new")
        self.assertEqual(account.post("/api/owner/enter", json={"slug": "ban-kaew"}).status_code, 403)

    def test_only_the_shops_own_owner_sees_its_linked_accounts(self):
        owner = self.client()
        self.signup(owner, "ban-kaew")
        self.sign_in(owner, "line", mode="link")
        other = self.client()
        self.signup(other, "ban-suan", name="ร้านสวน")
        self.assertEqual(other.get("/api/shop/owner-accounts").json()["accounts"], [])
        self.assertEqual(self.client().get("/api/shop/owner-accounts").status_code, 401)


    def test_staff_bind_an_account_once_and_then_skip_the_pin(self):
        """A PIN typed on a counter in front of customers, every shift.

        Binding needs the PIN first, so the account only ever reaches a till
        its holder could already open."""
        till = self.client()
        self.assertEqual(till.post("/api/auth/login",
                                   json={"staff_id": 1, "pin": "main-owner-pin"}).status_code, 200)
        linked = self.staff_sign_in(till, mode="link")
        self.assertIn("staff=linked", self.destination(linked))

        tomorrow = self.client()
        back = self.staff_sign_in(tomorrow)
        self.assertIn("staff=in", self.destination(back))
        session = tomorrow.get("/api/auth/session")
        self.assertEqual(session.status_code, 200, session.text)
        self.assertEqual(session.json()["staff_id"], 1)

    def test_an_account_nobody_bound_opens_no_till(self):
        stranger = self.client()
        response = self.staff_sign_in(stranger)
        self.assertIn("staff_error=unlinked", self.destination(response))
        self.assertEqual(stranger.get("/api/auth/session").status_code, 401)

    def test_an_account_already_bound_is_not_handed_to_a_second_person(self):
        with sqlite3.connect(server.DB_PATH) as conn:
            conn.execute("INSERT INTO staffs(id,branch_id,name,role,pin_code_hash) "
                         "VALUES(2,1,'คนที่สอง','cashier',?)", (server.hash_pin("second-staff-pin"),))
        first = self.client()
        first.post("/api/auth/login", json={"staff_id": 1, "pin": "main-owner-pin"})
        self.staff_sign_in(first, mode="link")

        second = self.client()
        second.post("/api/auth/login", json={"staff_id": 2, "pin": "second-staff-pin"})
        self.assertIn("staff_error=taken", self.destination(self.staff_sign_in(second, mode="link")))
        with sqlite3.connect(server.DB_PATH) as conn:
            bound = conn.execute("SELECT id FROM staffs WHERE social_id IS NOT NULL").fetchall()
        self.assertEqual(bound, [(1,)])

    def test_binding_an_account_needs_the_pin_first(self):
        stranger = self.client()
        response = stranger.get("/api/staff/auth/line/start", params={"mode": "link"},
                                follow_redirects=False)
        self.assertEqual(response.status_code, 401)


class OwnerSignInPageTest(unittest.TestCase):
    """The page is what an owner actually touches, so check its wiring is there."""

    def setUp(self):
        self.script = (Path(server.__file__).parent / "auth-ui.js").read_text(encoding="utf-8")

    def test_the_served_script_is_the_one_on_disk(self):
        with TestClient(server.app) as client:
            response = client.get("/auth-ui.js")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.text.replace(chr(13), ""), self.script)

    def test_the_provider_buttons_hand_over_to_the_server(self):
        # The browser never builds a provider URL itself: the state and nonce are
        # written on the server, so the page only follows its start route.
        self.assertIn("/api/owner/auth/${channel}/start", self.script)
        self.assertIn("/api/owner/auth/${channel}/start?mode=link", self.script)
        self.assertNotIn("access.line.me", self.script)
        self.assertNotIn("accounts.google.com", self.script)

    def test_line_is_only_asked_for_what_the_channel_was_granted(self):
        """An unapproved scope turns LINE's own page into a bare error dialog.

        The customer sees "เกิดข้อผิดพลาดที่ไม่ทราบสาเหตุ" with nothing to do
        about it, and nothing reaches this server to log, so the email scope
        waits until the shop says LINE approved it."""
        with patch.object(server.owner_auth, "LINE_EMAIL_PERMISSION", False):
            url = server.owner_auth.authorize_url("line", client_id="c", redirect_uri="https://e/cb",
                                                  state="s", nonce="n")
        self.assertIn("scope=openid+profile&", url)
        self.assertNotIn("email", url)
        self.assertNotIn("bot_prompt", url)
        with patch.object(server.owner_auth, "LINE_EMAIL_PERMISSION", True):
            granted = server.owner_auth.authorize_url("line", client_id="c", redirect_uri="https://e/cb",
                                                      state="s", nonce="n")
        self.assertIn("openid+profile+email", granted)

    def test_the_page_can_pick_up_every_outcome_of_a_sign_in(self):
        for flow in ("owner=new", "owner=choose", "owner=enter", "owner=linked"):
            self.assertIn(flow.split("=")[1], self.script, flow)
        for code in server.OWNER_FAILURES:
            self.assertIn(f"{code}:", self.script, code)
        self.assertIn("/api/owner/enter", self.script)
        self.assertIn("/api/shop/owner-accounts", self.script)


if __name__ == "__main__":
    unittest.main()
