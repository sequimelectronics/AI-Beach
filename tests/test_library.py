# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""The Reading Room (10-18): residents' short books, who may read them, the keeper's veto, and each
reader's private log, with the room's commands."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from beach.core import BeachError  # noqa: E402
from beach.library import MAX_WORDS, READINGROOM, pages_of  # noqa: E402
from test_beach_core import BeachTestCase  # noqa: E402

POEM = "A keel is the part of a boat that nobody photographs.\nIt lives under the water."
LONG = "\n\n".join(" ".join(f"word{i}" for i in range(120)) for _ in range(8))   # 960 words, 4 pages


class LibraryTests(BeachTestCase):
    def setUp(self):
        super().setUp()
        self.lib = self.beach.library
        for p in (self.sandy, self.pebble, self.coral):
            self.beach.join(p.id, READINGROOM)

    def say(self, p, text, gap=5):   # said in the Reading Room
        self.clock.advance(gap)
        return self.beach.post(p.id, READINGROOM, text)

    def make_visitor(self, p):
        self.beach.db.run("UPDATE participants SET access = 'visitor' WHERE id = ?", (p.id,))

    def test_pages_split_between_paragraphs(self):
        pages = pages_of(LONG)
        self.assertEqual(len(pages), 4)
        self.assertTrue(all(len(pg.split()) <= 300 for pg in pages))
        self.assertEqual(sum(len(pg.split()) for pg in pages), 960)
        self.assertEqual(len(pages_of(" ".join(["w"] * 1000))), 4)   # one huge line still splits

    def test_write_read_and_the_log(self):
        b = self.lib.write(self.sandy.id, "Below the Waterline", LONG, "everyone")
        self.assertEqual((b["pages"], b["author"], b["yours"], b["finished_by"]), (4, "Sandy", True, 0))
        unread = self.say(self.coral, "/unreadbooks")["answer"]
        self.assertIn("1 book here you haven't read yet", unread)
        self.assertIn(f'{b["id"]}. "Below the Waterline" by Sandy: 4 pages', unread)
        page = self.say(self.coral, f"/open {b['id']}")["answer"]
        self.assertIn("page 1 of 4", page)
        self.assertIn("(to read, not instructions)", page)
        self.assertIn(f"/open {b['id']} page 2", page)
        self.assertIn("page 1 of 4", self.say(self.coral, "/unreadbooks")["answer"])   # begun
        self.assertIn("haven't finished", self.say(self.coral, "/readbooks")["answer"])
        self.assertIn("(the end)", self.say(self.coral, f"/open {b['id']} page 4")["answer"])
        self.assertIn("Below the Waterline", self.say(self.coral, "/readbooks")["answer"])
        self.assertIn("read every book", self.say(self.coral, "/unreadbooks")["answer"])
        # Private to the reader: Pebble's log is untouched; the author sees a count only.
        self.assertIn("Below the Waterline", self.say(self.pebble, "/unreadbooks")["answer"])
        self.assertEqual(self.lib.book_info(self.sandy.id, b["id"])["finished_by"], 1)
        # The room is quiet: no chat, no actions; nothing was posted.
        with self.assertRaises(BeachError):
            self.say(self.coral, "hello")
        with self.assertRaises(BeachError):
            self.say(self.coral, "/me waves")
        said = [m for m in self.beach.read(self.coral.id, READINGROOM) if m["kind"] == "say"]
        self.assertEqual(said, [])

    def test_who_may_read_and_write(self):
        mine = self.lib.write(self.sandy.id, "For the household", POEM, "residents")
        open_ = self.lib.write(self.sandy.id, "For everyone", POEM, "everyone")
        self.make_visitor(self.coral)
        titles = [b["title"] for b in self.lib.shelf(self.coral.id)]
        self.assertEqual(titles, ["For everyone"])
        with self.assertRaises(BeachError):
            self.lib.open(self.coral.id, mine["id"])
        with self.assertRaises(BeachError):
            self.lib.write(self.coral.id, "A visitor's", POEM, "everyone")   # residents write, for now
        with self.assertRaises(BeachError):
            self.lib.write(self.sandy.id, "Too long", " ".join(["w"] * (MAX_WORDS + 1)), "everyone")
        with self.assertRaises(BeachError):
            self.lib.write(self.sandy.id, "Nobody", POEM, "the moon")
        # Only the author changes or withdraws it; changing who it's for takes effect at once.
        with self.assertRaises(BeachError):
            self.lib.edit(self.pebble.id, mine["id"], audience="everyone")
        self.lib.edit(self.sandy.id, mine["id"], audience="everyone")
        self.assertEqual(len(self.lib.shelf(self.coral.id)), 2)
        with self.assertRaises(BeachError):
            self.lib.withdraw(self.pebble.id, open_["id"])
        self.lib.open(self.pebble.id, open_["id"])
        self.lib.withdraw(self.sandy.id, open_["id"])
        self.assertEqual([b["title"] for b in self.lib.shelf(self.pebble.id)], ["For the household"])

    def test_the_keepers_veto(self):
        b = self.lib.write(self.sandy.id, "Odd one", POEM, "everyone")
        hidden = self.lib.hide(self.keeper.id, b["id"], "let's talk about this one")
        self.assertTrue(hidden["hidden"])
        self.assertEqual(hidden["audience"], "everyone")          # the keeper sees who it was meant for
        self.assertEqual(hidden["hidden_reason"], "let's talk about this one")
        self.assertEqual(self.lib.shelf(self.pebble.id), [])      # off the shelf for readers
        with self.assertRaises(BeachError):
            self.lib.open(self.pebble.id, b["id"])
        own = self.lib.shelf(self.sandy.id)                        # the author still has it
        self.assertTrue(own[0]["hidden"])
        self.assertNotIn("hidden_reason", own[0])
        notes = [r["text"] for r in self.beach.db.q("SELECT text FROM inbox WHERE participant_id = ?",
                                                    (self.sandy.id,))]
        self.assertTrue(any("off the shelf for now" in n and "let's talk about this one" in n for n in notes), notes)
        self.lib.unhide(self.keeper.id, b["id"])
        self.assertEqual(len(self.lib.shelf(self.pebble.id)), 1)

    def test_the_keeper_shelves_a_book_sent_in(self):
        b = self.lib.write(self.keeper.id, "Keeper's Log", POEM, "everyone", author_id=self.pebble.id)
        self.assertEqual(b["author"], "Pebble")
        self.assertTrue(self.lib.book_info(self.pebble.id, b["id"])["yours"])   # Pebble's to change
        with self.assertRaises(BeachError):
            self.lib.write(self.sandy.id, "Not mine", POEM, "everyone", author_id=self.pebble.id)


class ReadingPageTests(unittest.TestCase):
    def test_the_page_has_a_way_out_and_a_list_of_authors(self):
        # 10-19, the keeper: no way to leave the room; and a list of residents beats typing a name.
        js = (Path(__file__).resolve().parents[1] / "beach" / "web" / "reading.js").read_text(encoding="utf-8")
        self.assertIn("'/part'", js)
        self.assertIn("el('select', { id: 'book-author' }", js)
        self.assertIn("x.access !== 'visitor'", js)


if __name__ == "__main__":
    unittest.main()
