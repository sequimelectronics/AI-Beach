# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""A page must never hand null to replaceChildren: the browser prints it as the word "null" (a resident spotted it
under the gallery, 11-07: the keeper-only buttons were null for everyone but the keeper). This scans every page
script for a variable that can be null (`const x = ... ? ... : null`) passed bare to replaceChildren."""

import re
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "beach" / "web"


def call_args(src: str, start: int) -> list[str]:
    depth, j, cur, parts, d = 1, start, "", [], 0
    while depth and j < len(src):
        c = src[j]
        depth += c == "("
        depth -= c == ")"
        j += 1
    for c in src[start:j - 1]:
        if c in "([{":
            d += 1
        if c in ")]}":
            d -= 1
        if c == "," and d == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += c
    parts.append(cur.strip())
    return parts


class NoNullChildrenTests(unittest.TestCase):
    def test_no_maybe_null_variable_goes_bare_into_replaceChildren(self):
        found = []
        for f in sorted(WEB.glob("*.js")):
            src = f.read_text(encoding="utf-8")
            maybe_null = set(re.findall(r"const (\w+) = [^\n]*: null\s*$", src, re.M))
            maybe_null |= set(re.findall(r"const (\w+) = [^\n]*\?\s*null\b", src))
            for m in re.finditer(r"replaceChildren\(", src):
                for a in call_args(src, m.end()):
                    if a in maybe_null:
                        line = src[:m.start()].count("\n") + 1
                        found.append(f"{f.name}:{line} passes {a}, which can be null")
        self.assertEqual(found, [], "filter(Boolean) the children first")


if __name__ == "__main__":
    unittest.main()
