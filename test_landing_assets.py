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

    def test_index_loads_landing_after_auth_and_worker_caches_it(self):
        index = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertLess(index.index("/auth-ui.js"), index.index("/landing.js"))
        worker = (ROOT / "service-worker.js").read_text(encoding="utf-8")
        for asset in re.findall(r'"(/assets/landing/[^"]+)"', worker):
            self.assertTrue((ROOT / asset.lstrip("/")).exists(), asset)
        self.assertIn("/landing.js", worker)


if __name__ == "__main__":
    unittest.main()
