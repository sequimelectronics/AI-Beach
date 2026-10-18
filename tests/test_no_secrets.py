# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""Nothing private gets committed: no token, key or server file in the repository, and no word from a
household's own list. Runs with every test pass, so a slip fails the suite before it can be pushed.

Two layers. The generic checks live here: secret shapes (a Beach token, a private key, a known API-key prefix),
home-folder paths, private network addresses outside the documentation ranges, and secret-type file names.
The words that would identify a particular household (its machine names, its addresses, its people) can't be
written here without publishing them, so each Beach keeps its own list in `_local/guard_terms.txt` (one word or
phrase per line, `#` for comments; `_local/` is never committed) and this test reads it when it's there."""

from __future__ import annotations

import ipaddress
import os
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

from test_spdx import ROOT, repo_files  # noqa: E402

TEXT = {".py", ".js", ".cjs", ".mjs", ".lua", ".css", ".html", ".sh", ".md", ".txt", ".json", ".toml", ".yml",
        ".yaml", ".cfg", ".ini", ".patch", ".svg", ".xml", ".csv", ".ps1", ".cmd", ".bat", ""}   # "": LICENSE, etc.
VENDOR = "worlds/beach/static/vendor/"
TERMS_FILE = ROOT / "_local" / "guard_terms.txt"

# A Beach token is secrets.token_urlsafe(24): 32 URL-safe characters, almost always mixing upper, lower and digits.
TOKEN = re.compile(r"(?<![A-Za-z0-9_\-])(?=[A-Za-z0-9_\-]{32}(?![A-Za-z0-9_\-]))"
                   r"(?=[^\s]*[A-Z])(?=[^\s]*[a-z])(?=[^\s]*[0-9])[A-Za-z0-9_\-]{32}")
SHAPES = {
    "a private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "an API key": re.compile(r"\b(sk-[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"
                             r"|AKIA[0-9A-Z]{16}|xox[bpa]-[A-Za-z0-9-]{10,}|hf_[A-Za-z0-9]{30,})"),
    "a bearer token": re.compile(r"Bearer [A-Za-z0-9_\-]{24,}"),
    "a home-folder path": re.compile(r"(?i)\b[A-Z]:[\\/]+Users[\\/]+(?!<|\{|%|\$|you|name|me\b)[A-Za-z0-9._-]+"
                                     r"|/home/(?!<|\$|you|user\b)[a-z0-9._-]+|/Users/(?!<|\$|you|Shared\b)[A-Za-z0-9._-]+"),
}
IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
# Addresses examples may use: documentation ranges, loopback, and the made-up home network the tests use.
EXAMPLE_NETS = [ipaddress.ip_network(n) for n in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24",
                                                    "127.0.0.0/8", "0.0.0.0/8", "192.168.1.0/24", "10.0.0.0/24")]
# File names that only ever hold secrets or a Beach's own data.
SECRET_NAMES = re.compile(r"(?i)(^|/)(\.env(\..*)?|caddyfile|admin_token|[a-z_-]*_token|bridge-[a-z]+|"
                          r".*\.(db|sqlite3?|db-wal|db-shm|key|pem|p12|pfx|crt|bak))$")


def texts():
    for p in repo_files():
        if p.startswith(VENDOR) or Path(p).suffix.lower() not in TEXT:
            continue
        try:
            yield p, (ROOT / p).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue


def guard_terms() -> list[tuple[int, str]]:
    """(line number in the file, word or phrase); the report names the line, never the word."""
    try:
        lines = TERMS_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [(i, ln.strip()) for i, ln in enumerate(lines, 1) if ln.strip() and not ln.lstrip().startswith("#")]


class NoSecretsTest(unittest.TestCase):
    def test_no_secret_files(self):
        bad = [p for p in repo_files() if SECRET_NAMES.search(p)]
        self.assertEqual(bad, [], "these hold secrets or a Beach's own data: keep them out (see .gitignore)")

    def test_no_secret_shapes(self):
        found = []
        for p, t in texts():
            for m in TOKEN.finditer(t):
                found.append(f"{p}: something shaped like a Beach token ({m.group(0)[:4]}…)")
            for what, rx in SHAPES.items():
                for m in rx.finditer(t):
                    found.append(f"{p}: {what} ({m.group(0)[:12]}…)")
        self.assertEqual(found, [], "a secret, or something that looks like one: use a placeholder like <token>")

    def test_no_real_private_addresses(self):
        found = []
        for p, t in texts():
            for m in IPV4.finditer(t):
                try:
                    ip = ipaddress.ip_address(m.group(0))
                except ValueError:
                    continue
                if ip.is_private and not any(ip in n for n in EXAMPLE_NETS) and not m.group(0).endswith(".0"):
                    found.append(f"{p}: {m.group(0)}")
        self.assertEqual(found, [], "a real-looking private address: examples use 192.168.1.x, 10.0.0.x or 192.0.2.x")

    def test_no_household_words(self):
        terms = guard_terms()
        if not terms:
            self.skipTest("no _local/guard_terms.txt on this machine (each Beach keeps its own)")
        found = []
        for p, t in texts():
            for line, w in terms:
                if re.search(r"(?<![A-Za-z0-9])" + re.escape(w) + r"(?![A-Za-z0-9])", t, re.IGNORECASE):
                    found.append(f"{p}: the word on line {line} of _local/guard_terms.txt")
        self.assertEqual(found, [], "a household's own word made it into the repository")

    def test_the_checks_catch_what_they_should(self):
        # The guard proves itself on planted examples, so a broken pattern can't pass silently.
        # (Built from pieces, so this file never holds a whole example for the guard to find in itself.)
        fake_token = "Ab3" + "x" * 26 + "Q9z"
        self.assertTrue(TOKEN.search(f"token = '{fake_token}'"))
        self.assertFalse(TOKEN.search("def test_a_long_name_with_words_ok(self)"))
        self.assertTrue(SHAPES["a private key"].search("-----BEGIN EC " + "PRIVATE KEY-----"))
        self.assertTrue(SHAPES["a home-folder path"].search("C:\\" + "Users\\someone\\secret"))
        self.assertFalse(SHAPES["a home-folder path"].search(r"C:\Users\<you>\beach"))
        self.assertTrue(SECRET_NAMES.search("data/beach.db") and SECRET_NAMES.search("Caddyfile"))
        self.assertFalse(SECRET_NAMES.search("beach/tokens.py"))


if __name__ == "__main__":
    unittest.main()
