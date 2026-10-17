"""The public landing page and everything it draws are served, and listed for offline use."""

import re
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import line_pos_server as server

ROOT = Path(server.__file__).parent


class LandingAssetsTest(unittest.TestCase):
    def test_landing_files_are_served(self):
        with TestClient(server.app) as client:
            css = client.get("/landing.css")
            self.assertEqual(css.status_code, 200)
            self.assertIn("text/css", css.headers["content-type"])
            self.assertEqual(client.get("/landing.js").status_code, 200)
            for path in re.findall(r"/assets/landing/[\w.-]+", css.text + client.get("/landing.js").text):
                self.assertEqual(client.get(path).status_code, 200, path)

    def test_images_are_served_as_images(self):
        """The page sends nosniff, so a wrong media type stops the browser drawing it."""
        with TestClient(server.app) as client:
            for path, expected in (("/assets/brand-logo.webp", "image/webp"),
                                   ("/assets/menu/menu-1.webp", "image/webp"),
                                   ("/assets/landing/prompt-700-thai.woff2", "font/woff2"),
                                   ("/icon-192.png", "image/png")):
                response = client.get(path)
                self.assertEqual(response.status_code, 200, path)
                self.assertEqual(response.headers["content-type"].split(";")[0], expected, path)

    def test_every_sample_dish_has_its_photo(self):
        index = (ROOT / "index.html").read_text(encoding="utf-8")
        ids = re.findall(r'\{ id: (\d+), photo: "([^"]+)"', index)
        self.assertEqual(len(ids), 13)
        for item_id, photo in ids:
            self.assertEqual(photo, f"/assets/menu/menu-{item_id}.webp")
            self.assertTrue((ROOT / photo.lstrip("/")).exists(), photo)

    def test_the_policy_pages_are_public_and_linked_where_consent_is_asked(self):
        """The sign-up box asks people to accept these, so they have to open."""
        with TestClient(server.app) as client:
            for path in ("/privacy", "/terms", "/privacy.html", "/terms.html"):
                page = client.get(path)
                self.assertEqual(page.status_code, 200, path)
                self.assertIn("ZZAX Studio", page.text)
            self.assertEqual(client.get("/legal.css").status_code, 200)
            privacy = client.get("/privacy").text
            self.assertIn("/terms", privacy)       # each page links to the other
            self.assertIn("กัวลาลัมเปอร์", privacy)  # where the data actually sits
        auth = (ROOT / "auth-ui.js").read_text(encoding="utf-8")
        self.assertIn('href="/terms"', auth)
        self.assertIn('href="/privacy"', auth)
        landing = (ROOT / "landing.js").read_text(encoding="utf-8")
        self.assertIn("/privacy", landing)

    def test_index_loads_landing_after_auth_and_worker_caches_it(self):
        index = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertLess(index.index("/auth-ui.js"), index.index("/landing.js"))
        worker = (ROOT / "service-worker.js").read_text(encoding="utf-8")
        for asset in re.findall(r'"(/assets/landing/[^"]+)"', worker):
            self.assertTrue((ROOT / asset.lstrip("/")).exists(), asset)
        self.assertIn("/landing.js", worker)


if __name__ == "__main__":
    unittest.main()
