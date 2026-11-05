# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""The projector's picture loop: watch the show, and when the picture changes, say what happened.

How it decides (the keeper's design, 11-03): the picture is checked often (a tiny thumbnail compare, nearly free), and
the model is asked only when it really changed: fast action gets many lines, a slow conversation few. Each look shows
the model TWO pictures, the one it last described and the one now, and asks what is happening and what changed, with
the show's words spoken since its last look (each line once, never twice). A still scene still gets a fresh look now and
then, and a watcher's /look gets one at once. Lines go to the screen as "(seen) ...". Pictures stay in memory only.

The PACE (1 calm .. 5 max) is the projectionist's: in projector.json ("pace") and live, with + and - in the projector's
window. Everything model-specific lives in describer.py; this loop needs only:
    grab()                 -> a PIL image of the show right now, or None
    describe(jpeg, detail, context=..., previous=...) -> one line (any describer from describer.make_describer)
    heard()                -> the show's spoken lines as (monotonic time, text) pairs (optional)
    send(lines)            -> put lines on the screen; False when the show has ended
    wants()                -> True when a watcher asked for a look (the Beach's GET /drivein/projector/wants)
"""

from __future__ import annotations

import re
import threading
import time

import describer as _describer
import frames as _frames

# pace: (seconds at least between lines, lines at most per minute, a fresh look at a still scene every N seconds)
PACES = {1: (15, 4, 60), 2: (8, 6, 45), 3: (5, 8, 30), 4: (3, 12, 30), 5: (2, 20, 20)}
PACE_NAMES = {1: "calm", 2: "relaxed", 3: "normal", 4: "busy", 5: "max"}
DEFAULT_PACE = 3
POLL_S = 1                  # how often the picture is checked (a thumbnail compare; the model isn't asked)
GIVE_UP_AFTER = 5           # describer failures in a row before pictures stop for this show (words carry on)
NOTES_WORDS = 25            # the projectionist's show notes: 25 words at most (the keeper, 11-04)

# A line that says nearly the same as the last one isn't posted (a still stretch gave six "the man holds the white
# chicken" lines in a row; Harold's notes from a review stream: one promo line six times). Compared on content words,
# with plurals and -ing folded, so "holds a chicken in his hands" and "is holding a chicken in his hand" match.
REPEAT_SIMILAR = 0.6
REPEAT_WINDOW = 3           # compared with the last few lines posted: a model alternates wordings ("in his hands",
                            # "in his arms", "in his hands" again), so comparing with the last line alone let 13 of 16
                            # lines of one still stretch through
_SMALL = {"the", "and", "while", "with", "his", "her", "their", "its", "him", "them", "they", "she", "now", "still",
          "into", "from", "over", "onto", "this", "that", "are", "was", "has", "have", "who", "one", "two"}


def _content(line: str) -> set[str]:
    words = set()
    for w in re.findall(r"[a-z]+", line.lower()):
        if len(w) < 3 or w in _SMALL:
            continue
        for end in ("ing", "es", "s"):
            if w.endswith(end) and len(w) - len(end) >= 3:
                w = w[: -len(end)]
                break
        words.add(w)
    return words


def similar(a: str, b: str) -> bool:
    """Nearly the same line: most content words shared (Jaccard >= REPEAT_SIMILAR)."""
    sa, sb = _content(a), _content(b)
    if not sa or not sb:
        return a.strip(" .").lower() == b.strip(" .").lower()
    return len(sa & sb) / len(sa | sb) >= REPEAT_SIMILAR


def clip_notes(text: str) -> str:
    """The projectionist's show notes, at most NOTES_WORDS words, on one line."""
    return " ".join(str(text or "").split()[:NOTES_WORDS])


class PictureLoop(threading.Thread):
    def __init__(self, grab, describer, send, wants=None, allowed_words=(), pace=DEFAULT_PACE, poll=POLL_S,
                 say=print, clock=time.monotonic, sleep=None, heard=None, story=True, genre="", notes=""):
        super().__init__(name="drivein-pictures", daemon=True)
        self.grab, self.describer, self.send, self.wants = grab, describer, send, wants or (lambda: False)
        self.heard = heard or (lambda: [])
        self.story = story                   # False: no spoken words and no previous picture (each look on its own)
        self.allowed = {w.strip() for w in allowed_words if str(w).strip()}
        # Names the show has said at any point this show stay allowed through the name net all show (the keeper's
        # title card came out "The Magic of someone" when the narrator had said the name minutes before, not since
        # the last look). The CONTEXT stays since-the-last-look only.
        self.show_names: set[str] = set()
        self.pace = max(1, min(5, int(pace)))
        self.poll, self.say, self.clock = poll, say, clock
        self.stop_event = threading.Event()
        self._sleep = sleep or self.stop_event.wait
        self.last_line = self.last_look = -1e9
        self.last_thumb: bytes | None = None
        self.last_jpeg: bytes | None = None
        self.recent: list[float] = []       # when lines went out (the per-minute cap)
        self.failures = 0
        self.posted = 0
        self.last_texts: list[str] = []      # the last lines posted (to drop near-repeats)
        # The projectionist's optional genre and show notes (the keeper, 11-04): what is ON STAGE, not what happens.
        self.genre = " ".join(str(genre or "").split())
        self.notes = clip_notes(notes)

    def about(self) -> str:
        parts = [f"Genre: {self.genre}."] if self.genre else []
        if self.notes:
            parts.append(f"Show notes: {self.notes}")
        return " ".join(parts)

    def set_notes(self, notes: str) -> str:
        """New show notes (between acts); empty clears them. Says what the model will get."""
        self.notes = clip_notes(notes)
        self.say(f"(pictures: show notes now: {self.notes})" if self.notes else "(pictures: show notes cleared)")
        return self.notes

    # ------------------------------------------------------------------ the projectionist's knob
    def set_pace(self, pace: int) -> int:
        self.pace = max(1, min(5, int(pace)))
        gap, cap, still = PACES[self.pace]
        self.say(f"(pictures: pace {self.pace}, {PACE_NAMES[self.pace]}: a line at most every {gap} s, up to {cap} a "
                 f"minute, a still scene every {still} s)")
        return self.pace

    def stop(self) -> None:
        self.stop_event.set()

    def _spoken_since_last_look(self) -> list[str]:
        """The show's words since the model last looked (the keeper: each line once, never twice or out of order)."""
        try:
            return [str(text) for t, text in (self.heard() or []) if t > self.last_look]
        except Exception:
            return []

    def step(self) -> str | None:
        """One check. Returns the line posted (for tests and the console), or None."""
        now = self.clock()
        gap, cap, still = PACES[self.pace]
        try:
            asked = bool(self.wants())
        except Exception:                                         # the Beach being slow never stops the pictures
            asked = False
        self.recent = [t for t in self.recent if now - t < 60]
        if not asked and (now - self.last_line < gap or len(self.recent) >= cap):
            return None
        img = self.grab()
        if img is None or _frames.looks_blank(img):
            return None
        t = _frames.thumb(img)
        moved = _frames.changed(self.last_thumb, t)
        if not (asked or moved or now - self.last_line >= still):
            return None                                           # nothing new, and not yet time for a fresh look
        jpeg = _frames.to_jpeg(img)
        previous = self.last_jpeg if (self.story and moved and self.last_jpeg) else None
        spoken = self._spoken_since_last_look()
        self.show_names |= _describer.names_in(spoken)
        context = "\n".join(spoken) if self.story else ""
        detail = "change" if previous else ("long" if (asked or not moved) else "short")
        try:
            line = self.describer.describe(jpeg, detail, context=context, previous=previous, about=self.about())
        except _describer.DescriberError as e:
            self.failures += 1
            self.say(f"(pictures: {e})")
            if self.failures >= GIVE_UP_AFTER:
                self.say("(pictures: stopped for this show after repeated failures; the words carry on)")
                self.stop()
            return None
        self.failures = 0
        self.last_look = now
        line = _describer.scrub(line, self.allowed | self.show_names)
        if not line or line.strip(" .").upper() == "SAME":
            return None
        self.last_thumb, self.last_jpeg, self.last_line = t, jpeg, now
        if not asked and any(similar(line, before) for before in self.last_texts):
            return None          # a quiet look: nearly what the screen already says (a watcher's /look always posts)
        self.recent.append(now)
        self.last_texts = (self.last_texts + [line])[-REPEAT_WINDOW:]
        text = "(seen) " + line
        if self.send([text]) is False:
            self.stop()
        self.posted += 1
        return text

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.step()
            except Exception as e:                                # never take the show down with it
                self.say(f"(pictures: unexpected trouble, {type(e).__name__}: {e})")
            self._sleep(self.poll)
