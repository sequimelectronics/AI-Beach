# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""The keeper page's QR codes (beach/web/qr.js; the keeper, 10-23: getting an invite onto a phone was "a pain"):
checked module for module against the Python `qrcode` package, for every mask and for versions 1 to 10, so a
phone's camera reads exactly what a standard encoder would draw. Skipped where node or qrcode isn't installed."""

import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QR_JS = ROOT / "beach" / "web" / "qr.js"

try:
    import qrcode
    HAVE_QRCODE = True
except ImportError:
    HAVE_QRCODE = False


def js_matrix(text: str, mask: int | None) -> dict:
    script = ("const q = require(process.argv[1]); const r = q.matrix(process.argv[2], process.argv[3] === '' ? undefined"
              " : Number(process.argv[3])); process.stdout.write(JSON.stringify({version: r.version, mask: r.mask,"
              " rows: r.modules.map(row => row.map(v => v ? 1 : 0).join(''))}))")
    out = subprocess.run(["node", "-e", script, str(QR_JS), text, "" if mask is None else str(mask)],
                         capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    if out.returncode:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout)


def py_matrix(text: str, version: int, mask: int) -> list[str]:
    q = qrcode.QRCode(version=version, error_correction=qrcode.constants.ERROR_CORRECT_M, border=0, mask_pattern=mask)
    q.add_data(qrcode.util.QRData(text.encode("utf-8"), mode=qrcode.util.MODE_8BIT_BYTE))
    q.make(fit=False)
    return ["".join("1" if v else "0" for v in row) for row in q.get_matrix()]


@unittest.skipUnless(HAVE_QRCODE and shutil.which("node"), "needs node and the qrcode package")
class QrTests(unittest.TestCase):
    TEXTS = ["hi",
             "https://beach.example.org/#c=ABCD-EFGH-JKLM-NPQR",                       # an invite link's shape
             "https://beach.example.org/#t=" + "x" * 40 + "&n=Coral",
             "Sandy's beach 🌊 " + "lanterns " * 12,                                  # UTF-8, a mid version
             "z" * 200]                                                                 # version 10

    def test_matches_a_standard_encoder_module_for_module(self):
        for text in self.TEXTS:
            for mask in range(8):
                mine = js_matrix(text, mask)
                theirs = py_matrix(text, mine["version"], mask)
                self.assertEqual(mine["rows"], theirs, f"{text[:30]!r} mask {mask} version {mine['version']}")

    def test_picks_the_smallest_version_and_a_mask_by_itself(self):
        r = js_matrix("https://beach.example.org/#c=ABCD-EFGH-JKLM-NPQR", None)
        self.assertLessEqual(r["version"], 4)
        self.assertIn(r["mask"], range(8))
        self.assertEqual(r["rows"], py_matrix("https://beach.example.org/#c=ABCD-EFGH-JKLM-NPQR", r["version"], r["mask"]))

    def test_too_long_is_refused_not_garbled(self):
        with self.assertRaises(AssertionError):
            js_matrix("z" * 300, None)


if __name__ == "__main__":
    unittest.main()
