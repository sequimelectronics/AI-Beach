# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""No invisible characters in the repository's text: control characters, zero-width characters, byte-order
marks, and above all direction overrides ("Trojan Source": they can make code read differently from what it
does). Where code needs one, it writes the escape (a backslash, u, and four hex digits), never the character.
Found 10-20: an editing tool had turned typed escapes into the real characters, in a regex that strips them."""

import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BINARY = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".woff", ".woff2", ".ttf", ".otf", ".glb", ".bin", ".db"}


def invisible(ch: str) -> bool:
    o = ord(ch)
    return ((o < 32 and ch not in "\t\r\n") or 0x7F <= o <= 0x9F or 0x200B <= o <= 0x200F
            or 0x202A <= o <= 0x202E or 0x2066 <= o <= 0x2069 or o == 0xFEFF)


class InvisibleCharacterTests(unittest.TestCase):
    def test_no_tracked_text_file_holds_an_invisible_character(self):
        files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True,
                               stdin=subprocess.DEVNULL).stdout.split("\n")
        problems = []
        for name in filter(None, files):
            p = ROOT / name
            if p.suffix.lower() in BINARY or not p.is_file():
                continue
            try:
                text = p.read_bytes().decode("utf-8")
            except UnicodeDecodeError:
                continue
            for n, line in enumerate(text.splitlines(), 1):
                found = [ch for ch in line if invisible(ch)]
                if found:
                    problems.append(f"{name}:{n}: U+{ord(found[0]):04X}")
                    break
        self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main()
