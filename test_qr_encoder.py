"""Every QR this shop prints has to be readable by an actual reader.

The encoder this replaced drew symbols whose finder patterns were correct, so
a camera found them, and whose contents no reader could decode. It had been
live the whole time, including on the PromptPay codes customers were meant to
scan in order to pay. Nobody caught it, because looking at a picture of a QR
code tells you nothing and no real payment had been attempted yet.

So this file checks two things, in order of how much they would hurt:

1. the symbols still match ones that were decoded successfully (qr_golden.json)
2. where a decoder is installed, that the symbols really do decode

The first needs nothing but node and always runs. The second needs OpenCV and
is skipped without it, so whoever has it gets the stronger check.
"""

import json
import subprocess
import unittest
from pathlib import Path

try:
    import cv2
    import numpy as np
except ImportError:                                  # pragma: no cover
    cv2 = None

HERE = Path(__file__).parent
GOLDEN = json.loads((HERE / "qr_golden.json").read_text(encoding="utf-8"))
PAYLOADS = {
    "two letters": "HI",
    "table sticker": "https://poswai.zzaxstudio.com/t/4JwtBGGxTfxu38KriyFC9Q?shop=guohao",
    "promptpay bill": "00020101021129370016A000000677010111011300668951851885802TH530376463040B7D",
}
EXTRA = {
    "short link": "https://a.co/x",
    "thai text": "ร้านกะเพราหมูสับ โต๊ะ A1",
    "long link": "https://poswai.zzaxstudio.com/t/" + "z" * 60 + "?shop=" + "w" * 30,
}

SHIM = """
globalThis.window = globalThis;
globalThis.TextEncoder = require('util').TextEncoder;
require(%s);
const out = {};
for (const [name, text] of Object.entries(%s)) {
  out[name] = window.poswaiQr.modules(text).map(row => row.map(v => (v ? 1 : 0)).join(''));
}
process.stdout.write(JSON.stringify(out));
"""


def encode(payloads):
    """Run the browser's encoder under node and hand back its module grids."""
    script = SHIM % (json.dumps(str(HERE / "qr.js")), json.dumps(payloads))
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True,
                            encoding="utf-8", check=True)
    return json.loads(result.stdout)


def as_image(rows, scale=10, quiet=4):
    """The grid as a picture, with the quiet zone a reader needs around it."""
    grid = np.array([[0 if ch == "1" else 255 for ch in row] for row in rows], np.uint8)
    big = np.kron(grid, np.ones((scale, scale), np.uint8))
    pad = quiet * scale
    image = np.full((big.shape[0] + 2 * pad,) * 2, 255, np.uint8)
    image[pad:pad + big.shape[0], pad:pad + big.shape[1]] = big
    return image


class QrEncoderTest(unittest.TestCase):
    def test_the_symbols_have_not_drifted_from_ones_known_to_decode(self):
        produced = encode(PAYLOADS)
        for name in PAYLOADS:
            with self.subTest(payload=name):
                self.assertEqual(
                    produced[name], GOLDEN[name],
                    f"{name}: the symbol changed; decode it for real before updating the fixture")

    def test_the_symbol_grows_with_the_payload(self):
        produced = encode({**PAYLOADS, **EXTRA})
        self.assertEqual(len(produced["two letters"]), 21)        # version 1
        self.assertEqual(len(produced["table sticker"]), 37)      # version 5
        self.assertGreater(len(produced["long link"]), 37)

    def test_an_empty_string_is_refused_rather_than_drawn_blank(self):
        script = SHIM % (json.dumps(str(HERE / "qr.js")), json.dumps({"empty": ""}))
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True,
                                encoding="utf-8")
        self.assertNotEqual(result.returncode, 0)

    def test_a_payload_too_large_is_refused_rather_than_truncated(self):
        script = SHIM % (json.dumps(str(HERE / "qr.js")), json.dumps({"huge": "x" * 400}))
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True,
                                encoding="utf-8")
        self.assertNotEqual(result.returncode, 0)

    @unittest.skipIf(cv2 is None, "OpenCV is not installed")
    def test_a_reader_gets_back_exactly_what_went_in(self):
        payloads = {**PAYLOADS, **EXTRA}
        produced = encode(payloads)
        detector = cv2.QRCodeDetector()
        for name, text in payloads.items():
            with self.subTest(payload=name):
                decoded, points, _ = detector.detectAndDecode(as_image(produced[name]))
                self.assertIsNotNone(points, f"{name}: no symbol found at all")
                self.assertEqual(decoded, text, f"{name}: decoded to something else")


if __name__ == "__main__":
    unittest.main()
