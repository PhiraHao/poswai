"""Sign in with Apple, from inside the iPhone app.

Apple asks every iPhone app that offers LINE or Google to offer Apple as well
(App Review 4.8). The app signs in with Apple natively and hands this server the
identity token Apple signed; the server checks that signature against Apple's
own published keys. Here a key made for the test stands in for Apple's, so the
signature, audience, issuer, expiry and nonce checks are the real ones.
"""

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

import line_pos_server as server
import poswai_owner_auth as owner_auth
from test_owner_accounts import OwnerAuthCase

BUNDLE_ID = "com.zzaxstudio.poswai"
APPLE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def published_keys() -> dict:
    """Apple's key set, as https://appleid.apple.com/auth/keys would answer."""
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(APPLE_KEY.public_key()))
    jwk.update({"kid": "apple-test-key", "use": "sig", "alg": "RS256"})
    return {"keys": [jwk]}


def hashed(nonce: str) -> str:
    """The app hands Apple the nonce's SHA-256, so that is what the token carries."""
    return hashlib.sha256(nonce.encode()).hexdigest()


class AppleCase(OwnerAuthCase):
    """Apple's keys stood in for, and the helpers the Apple tests share."""

    def setUp(self):
        super().setUp()
        for item in (patch.object(owner_auth, "_apple_keys", published_keys),
                     patch.object(server, "APPLE_AUDIENCES", (BUNDLE_ID,))):
            item.start()
            self.addCleanup(item.stop)

    # ------------------------------------------------------------------ helpers
    def token(self, nonce: str, *, key=APPLE_KEY, kid="apple-test-key", **overrides) -> str:
        claims = {"iss": owner_auth.APPLE_ISSUER, "aud": BUNDLE_ID, "sub": "001234.apple-owner",
                  "iat": int(time.time()), "exp": int(time.time()) + 600, "nonce": hashed(nonce),
                  "email": "abc123@privaterelay.appleid.com", "email_verified": "true"}
        claims.update(overrides)
        return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})

    def begin(self, client, path="/api/owner/auth/apple/start", **params):
        response = client.get(path, params=params, follow_redirects=False)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["state"] and body["nonce"])
        return body["state"], body["nonce"]

    def finish(self, client, state, token, name=""):
        return client.post("/api/auth/apple/native",
                           json={"state": state, "identity_token": token, "name": name})

    def link(self, response) -> dict:
        self.assertEqual(response.status_code, 200, response.text)
        link = response.json()["link"]
        self.assertTrue(link.startswith("poswai://auth"), link)
        return {key: values[0] for key, values in parse_qs(urlsplit(link).query).items()}


class AppleSignInTest(AppleCase):
    # ---------------------------------------------------------------- the owner
    def test_the_app_is_handed_a_state_and_nonce_instead_of_a_redirect(self):
        """Apple's sheet is the phone's own, so there is no page to send anyone to."""
        state, nonce = self.begin(self.client())
        self.assertNotEqual(state, nonce)

    def test_a_first_apple_sign_in_returns_an_owner_session_to_the_app(self):
        client = self.client()
        state, nonce = self.begin(client)
        handed = self.link(self.finish(client, state, self.token(nonce), name="สมชาย ใจดี"))
        self.assertEqual(handed["outcome"], "new")
        self.assertEqual(len(handed["owner"]), 64)
        account = client.get("/api/owner/session", headers={"x-poswai-owner": handed["owner"]}).json()
        self.assertEqual(account["account"]["provider"], "apple")
        self.assertEqual(account["account"]["email"], "abc123@privaterelay.appleid.com")
        # Apple tells the app the name once, on the first sign-in only.
        self.assertEqual(account["account"]["name"], "สมชาย ใจดี")

    def test_a_token_signed_by_anyone_but_apple_is_refused(self):
        client = self.client()
        state, nonce = self.begin(client)
        self.assertEqual(self.finish(client, state, self.token(nonce, key=OTHER_KEY)).status_code, 401)

    def test_a_token_from_a_key_apple_never_published_is_refused(self):
        client = self.client()
        state, nonce = self.begin(client)
        self.assertEqual(self.finish(client, state, self.token(nonce, kid="nobody")).status_code, 401)

    def test_a_token_for_another_app_is_refused(self):
        client = self.client()
        state, nonce = self.begin(client)
        token = self.token(nonce, aud="com.example.other")
        self.assertEqual(self.finish(client, state, token).status_code, 401)

    def test_a_token_from_another_issuer_is_refused(self):
        client = self.client()
        state, nonce = self.begin(client)
        token = self.token(nonce, iss="https://accounts.google.com")
        self.assertEqual(self.finish(client, state, token).status_code, 401)

    def test_an_expired_token_is_refused(self):
        client = self.client()
        state, nonce = self.begin(client)
        token = self.token(nonce, exp=int(time.time()) - 60)
        self.assertEqual(self.finish(client, state, token).status_code, 401)

    def test_a_token_from_another_sign_in_is_refused(self):
        client = self.client()
        state, _ = self.begin(client)
        _, other_nonce = self.begin(client)
        self.assertEqual(self.finish(client, state, self.token(other_nonce)).status_code, 401)

    def test_a_state_is_good_for_one_sign_in_only(self):
        client = self.client()
        state, nonce = self.begin(client)
        self.link(self.finish(client, state, self.token(nonce)))
        self.assertEqual(self.finish(client, state, self.token(nonce)).status_code, 400)

    def test_a_state_issued_for_line_cannot_be_spent_on_apple(self):
        client = self.client()
        started = client.get("/api/owner/auth/line/start", follow_redirects=False)
        state = parse_qs(urlsplit(started.headers["location"]).query)["state"][0]
        self.assertEqual(self.finish(client, state, self.token("whatever")).status_code, 400)

    def test_an_unverified_email_is_not_kept(self):
        client = self.client()
        state, nonce = self.begin(client)
        handed = self.link(self.finish(client, state, self.token(nonce, email_verified="false")))
        account = client.get("/api/owner/session", headers={"x-poswai-owner": handed["owner"]}).json()
        self.assertEqual(account["account"]["email"], "")

    def test_an_owner_links_apple_in_the_app_and_enters_with_it_next_time(self):
        owner = self.client()
        self.signup(owner, "ban-kaew")
        session = owner.get("/api/auth/session").json()
        self.assertEqual(session["role"], "owner")
        state, nonce = self.begin(owner, mode="link")
        handed = self.link(self.finish(owner, state, self.token(nonce)))
        self.assertEqual((handed["staff"], handed["shop"]), ("linked", "ban-kaew"))

        phone = self.client()
        state, nonce = self.begin(phone)
        handed = self.link(self.finish(phone, state, self.token(nonce)))
        self.assertEqual((handed["outcome"], handed["shop"]), ("enter", "ban-kaew"))

    def test_only_the_shops_owner_may_link_apple(self):
        self.assertEqual(self.client().get("/api/owner/auth/apple/start",
                                           params={"mode": "link"}).status_code, 401)

    # ---------------------------------------------------------------- the staff
    def test_staff_bind_apple_once_and_then_skip_the_pin(self):
        till = self.client()
        self.assertEqual(till.post("/api/auth/login",
                                   json={"staff_id": 1, "pin": "main-owner-pin"}).status_code, 200)
        state, nonce = self.begin(till, "/api/staff/auth/apple/start", mode="link")
        self.assertEqual(self.link(self.finish(till, state, self.token(nonce)))["staff"], "linked")
        with sqlite3.connect(server.DB_PATH) as conn:
            bound = conn.execute("SELECT social_id FROM staffs WHERE id=1").fetchone()[0]
        self.assertEqual(bound, "apple:001234.apple-owner")

        tomorrow = self.client()
        state, nonce = self.begin(tomorrow, "/api/staff/auth/apple/start")
        handed = self.link(self.finish(tomorrow, state, self.token(nonce)))
        self.assertEqual(handed["staff"], "in")
        session = tomorrow.get("/api/auth/session", headers={"x-poswai-session": handed["session"]})
        self.assertEqual(session.status_code, 200, session.text)
        self.assertEqual(session.json()["staff_id"], 1)

    def test_an_apple_account_nobody_bound_opens_no_till(self):
        stranger = self.client()
        state, nonce = self.begin(stranger, "/api/staff/auth/apple/start")
        self.assertEqual(self.link(self.finish(stranger, state, self.token(nonce)))["staff_error"],
                         "unlinked")


class CustomerSignInFromTheAppTest(AppleCase):
    """A customer signing in from the iPhone app gets their card in the app.

    On the web the card lands in a cookie. The app's browser tab has its own
    cookie jar, so a card left there never reached the app; the finished
    sign-in now comes back over poswai://auth, like an owner's or staff's."""

    def card(self, client, token):
        return client.get("/api/members/card", headers={"X-Member-Token": token})

    def test_a_customers_line_sign_in_comes_back_to_the_app(self):
        client = self.client()
        started = client.get("/api/members/auth/line/start", params={"app": "1"},
                             follow_redirects=False)
        self.assertEqual(started.status_code, 302, started.text)
        state = parse_qs(urlsplit(started.headers["location"]).query)["state"][0]
        handed = self.link(_as_json(self.callback(client, "line", state=state)))
        self.assertEqual(handed["shop"], server.MAIN_SHOP)
        card = self.card(self.client(), handed["member"])
        self.assertEqual(card.status_code, 200, card.text)
        self.assertEqual(card.json()["display_name"], "เจ้าของร้าน")

    def test_a_customer_on_the_web_still_gets_a_cookie(self):
        client = self.client()
        started = client.get("/api/members/auth/line/start", follow_redirects=False)
        state = parse_qs(urlsplit(started.headers["location"]).query)["state"][0]
        landed = self.callback(client, "line", state=state)
        self.assertIn("member=in", landed.headers["location"])
        self.assertEqual(client.get("/api/members/card").status_code, 200)

    def test_a_customer_signs_in_with_apple_and_gets_their_card(self):
        client = self.client()
        state, nonce = self.begin(client, "/api/members/auth/apple/start")
        handed = self.link(self.finish(client, state, self.token(nonce), name="คุณแอปเปิล"))
        card = self.card(self.client(), handed["member"])
        self.assertEqual(card.status_code, 200, card.text)
        self.assertEqual(card.json()["display_name"], "คุณแอปเปิล")

    def test_the_same_apple_id_comes_back_to_the_same_card(self):
        seen = []
        for name in ("คุณแอปเปิล", ""):     # Apple gives the name the first time only
            client = self.client()
            state, nonce = self.begin(client, "/api/members/auth/apple/start")
            handed = self.link(self.finish(client, state, self.token(nonce), name=name))
            body = self.card(client, handed["member"]).json()
            seen.append((body["member_id"], body["display_name"]))
        self.assertEqual(seen[0], seen[1])


def _as_json(redirect):
    """A browser-tab sign-in answers with a redirect; present it as the native one does."""
    class Reply:
        status_code = 200

        @staticmethod
        def json():
            return {"link": redirect.headers["location"]}

        text = redirect.text
    return Reply()


class AppleSignInPageTest(OwnerAuthCase):
    """The button is only real on an iPhone, where the native sheet exists."""

    def test_apple_buttons_sit_beside_every_provider_the_app_offers(self):
        script = (Path(server.__file__).parent / "auth-ui.js").read_text(encoding="utf-8")
        for marker in ('data-channel="apple"', 'data-staff-channel="apple"',
                       'data-staff-link-channel="apple"', 'data-link-channel="apple"',
                       'data-member-channel="apple"'):
            self.assertIn(marker, script)
