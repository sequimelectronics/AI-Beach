# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""The projector's picture loop: when a description is due, look at the show and put one line on the screen.

Pace (the keeper's choice, 11-03): a SHORT line every 15 s and a LONGER one every 30 s, but only when the picture has
changed since the last description (a talking head gets one line, a magic act many), and at once when a watcher asks
with /look. Lines go to the screen as "(seen) ...". Pictures are kept in memory only, never saved.

Everything model-specific lives in describer.py; this loop only needs four things handed to it, so it works the same
for a program window, a shared browser tab, or anything else that can produce a picture:
    grab()          -> a PIL image of the show right now, or None
    describe(jpeg, detail, context) -> one line (any describer from describer.make_describer)
    heard()         -> the show's recent spoken lines (optional: the story so far + names the show says)
    send(lines)     -> put lines on the screen; False when the show has ended
    wants()         -> True when a watcher asked for a look (the Beach's GET /drivein/projector/wants)
"""

from __future__ import annotations

import threading
import time

import describer as _describer
import frames as _frames

SHORT_EVERY_S = 15
LONG_EVERY_S = 30
POLL_S = 3
GIVE_UP_AFTER = 5           # describer failures in a row before pictures stop for this show (words carry on)
HEARD_LINES = 4             # the show's last spoken lines handed over with each picture
SEEN_LINES = 2              # this loop's own last descriptions handed over too


class PictureLoop(threading.Thread):
    def __init__(self, grab, describer, send, wants=None, allowed_words=(), short_every=SHORT_EVERY_S,
                 long_every=LONG_EVERY_S, poll=POLL_S, say=print, clock=time.monotonic, sleep=None, heard=None,
                 story=True):
        super().__init__(name="drivein-pictures", daemon=True)
        self.grab, self.describer, self.send, self.wants = grab, describer, send, wants or (lambda: False)
        # The story so far (the keeper, 11-03): the show's last spoken lines and this loop's own last descriptions go
        # with each picture, and names the show itself says are let through the name net.
        self.heard = heard or (lambda: [])
        self.story = story                    # False: no story so far in the prompt (names the show says still pass)
        self.recent_seen: list[str] = []
        self.allowed = {w.strip() for w in allowed_words if str(w).strip()}
        self.short_every, self.long_every, self.poll = short_every, long_every, poll
        self.say, self.clock = say, clock
        self.stop_event = threading.Event()
        self._sleep = sleep or self.stop_event.wait
        self.last_short = self.last_long = -1e9
        self.last_thumb: bytes | None = None
        self.failures = 0
        self.posted = 0

    def stop(self) -> None:
        self.stop_event.set()

    def step(self) -> str | None:
        """One check: describe if due. Returns the line posted (for tests and the console), or None."""
        now = self.clock()
        try:
            asked = bool(self.wants())
        except Exception:                                         # the Beach being slow never stops the pictures
            asked = False
        due_long = now - self.last_long >= self.long_every
        due_short = now - self.last_short >= self.short_every
        if not (asked or due_long or due_short):
            return None
        img = self.grab()
        if img is None or _frames.looks_blank(img):
            return None
        t = _frames.thumb(img)
        if not asked and not _frames.changed(self.last_thumb, t):
            return None                                           # same picture: nothing new to say
        detail = "long" if (asked or due_long) else "short"
        try:
            spoken = [str(s) for s in (self.heard() or [])][-HEARD_LINES:]
        except Exception:
            spoken = []
        context = "\n".join([f"(seen) {s}" for s in self.recent_seen] + spoken) if self.story else ""
        try:
            line = self.describer.describe(_frames.to_jpeg(img), detail, context=context)
        except _describer.DescriberError as e:
            self.failures += 1
            self.say(f"(pictures: {e})")
            if self.failures >= GIVE_UP_AFTER:
                self.say("(pictures: stopped for this show after repeated failures; the words carry on)")
                self.stop()
            return None
        self.failures = 0
        line = _describer.scrub(line, self.allowed | _describer.names_in(spoken))
        if not line:
            return None
        self.recent_seen = (self.recent_seen + [line])[-SEEN_LINES:]
        self.last_thumb, self.last_short = t, now
        if detail == "long":
            self.last_long = now
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
