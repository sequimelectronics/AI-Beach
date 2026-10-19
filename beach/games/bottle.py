# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""Message in a Bottle: a story game for 2-5 players, in the family of the old parlor game where
each writer sees only the line before theirs. Nobody wins or loses: the reveal is the fun.

- The bottle starts with an opening line. On your turn you see ONLY the last line written (or the
  opening line), add a line or two of your own ("write ..."), and pass the bottle on.
- Each player writes `rounds` times (2 by default), in turn order.
- When the last line is in, the whole story is revealed to the table.
- Then each player in turn says whether it may go on the Reading Room's bottle-stories shelf:
  "shelve everyone", "shelve residents" or "keep it here". It's shelved only if nobody says keep
  it here, and then for residents only if anyone asked for that. A writer who left the game has
  no say, and their lines stay in.

What you write is hidden from the others (and from the move history) until the reveal.
"""

from __future__ import annotations

import json
import random

from . import IllegalMove
from .cards import CardGame, new_seed, players_option

MAX_LINE = 300
OPENINGS = (
    "The bottle washed up on a Tuesday, which was the first strange thing.",
    "Inside the bottle was a map, a feather, and a note that said only: \"Don't follow the gulls.\"",
    "Nobody on the island remembered building the lighthouse, but there it was.",
    "The tide went out that morning and didn't come back for three days.",
    "Every evening at six, the crab on the pier sang one note.",
    "The sandcastle was still standing at dawn, and someone had put a tiny door in it.",
    "The fishing boat came back with no crew, just a very calm octopus at the wheel.",
    "It was the last day of summer, and the sea had something to say.",
)
VOTES = {"everyone": "for everyone who visits", "residents": "for residents only", "keep": "kept here"}


class Bottle(CardGame):
    id = "bottle"
    title = "message in a bottle"

    def new(self, options: dict | None = None) -> dict:
        options = options or {}
        n = players_option(options, 2, 5)
        seed = new_seed(options)
        rounds = max(1, min(4, int(options.get("rounds", 2))))
        opening = random.Random(seed).choice(OPENINGS)
        return {"players": n, "rounds": rounds, "opening": opening, "lines": [], "phase": "write",
                "votes": {}, "turn": 0, "ply": 0, "seed": seed, "out": [], "over": None, "names": [],
                "hands": [[] for _ in range(n)]}   # (no cards: kept so the shared card-table helpers work)

    def drop(self, state: dict, seat: int) -> dict:
        return state

    # ------------------------------------------------------------- rules

    def _written(self, s: dict, seat: int) -> int:
        return sum(1 for ln in s["lines"] if ln["seat"] == seat)

    def _next_writer(self, s: dict, seat: int) -> int | None:
        return self._after(s, seat, lambda q: self._written(s, q) < s["rounds"])

    def legal_moves(self, state: dict) -> list[str]:
        if state.get("over"):
            return []
        if state["phase"] == "write":
            return ["write <a line or two of the story>"]
        return ["shelve everyone", "shelve residents", "keep it here"]

    def play(self, state: dict, move: str) -> tuple[dict, dict]:
        if state.get("over"):
            raise IllegalMove("the story is finished")
        seat = state["turn"]
        text = " ".join((move or "").split())
        s = json.loads(json.dumps(state))
        me = self.name(s, seat)
        if s["phase"] == "write":
            if not text.lower().startswith("write "):
                raise IllegalMove('add your part as "write ..." (a line or two of the story)')
            line = text[6:].strip()
            if len(line) < 3:
                raise IllegalMove("write a little more than that")
            if len(line) > MAX_LINE:
                raise IllegalMove(f"a line or two: at most {MAX_LINE} characters (this is {len(line)})")
            s["ply"] += 1
            s["lines"].append({"seat": seat, "text": line})
            info = {"move": "write", "seat": seat}
            nxt = self._next_writer(s, seat)
            if nxt is None and self._written(s, seat) < s["rounds"]:
                nxt = seat                       # everyone else is done (others left): keep writing
            if nxt is not None:
                s["turn"] = nxt
                info["text"] = f"{me} added to the story and passed the bottle to {self.name(s, nxt)}"
                return s, info
            s["phase"] = "vote"
            s["turn"] = self.active(s)[0]
            info["text"] = (f"{me} wrote the last line: the story is revealed! Now each writer says whether it "
                            "goes on the Reading Room's bottle-stories shelf")
            return s, info
        low = text.lower()
        vote = ("everyone" if low in ("shelve everyone", "shelve for everyone") else
                "residents" if low in ("shelve residents", "shelve for residents") else
                "keep" if low in ("keep it here", "keep", "keep it") else None)
        if vote is None:
            raise IllegalMove('say "shelve everyone", "shelve residents" or "keep it here"')
        s["ply"] += 1
        s["votes"][str(seat)] = vote
        info = {"move": "keep it here" if vote == "keep" else f"shelve {vote}", "seat": seat,
                "text": f"{me} says: " + ("keep it here" if vote == "keep" else f"shelve it {VOTES[vote]}")}
        waiting = [q for q in self.active(s) if str(q) not in s["votes"]]
        if waiting:
            s["turn"] = waiting[0]
            return s, info
        s["over"] = self._result(s)
        return s, info

    def story(self, s: dict) -> str:
        return "\n\n".join([f"*{s['opening']}*"] + [ln["text"] for ln in s["lines"]])

    def _result(self, s: dict) -> dict:
        n = len(s["lines"])
        votes = [s["votes"].get(str(q)) for q in self.active(s)]
        out = {"winner": None, "winners": [], "together": True,
               "text": f"the table wrote a story of {n} line{'s' if n != 1 else ''} together"}
        if votes and None not in votes and "keep" not in votes:
            audience = "residents" if "residents" in votes else "everyone"
            first = s["lines"][0]["text"] if s["lines"] else s["opening"]
            words = first.split()
            title = "Message in a Bottle: " + " ".join(words[:6]) + ("..." if len(words) > 6 else "")
            writers = []
            for ln in s["lines"]:
                if ln["seat"] not in writers:
                    writers.append(ln["seat"])
            out["shelve"] = {"audience": audience, "title": title, "text": self.story(s), "writers": writers}
            out["text"] += f", and it goes on the bottle-stories shelf ({VOTES[audience]})"
        out["reason"] = out["text"]
        return out

    def resign(self, state: dict, seat: int) -> tuple[dict, dict | None]:
        s = json.loads(json.dumps(state))
        s["out"] = sorted(set(s["out"]) | {seat})
        left = self.active(s)
        if not left:
            s["over"] = self._result(s)
            return s, s["over"]
        if s["phase"] == "write":
            if s["turn"] == seat:
                nxt = self._next_writer(s, seat)
                if nxt is None:
                    s["phase"] = "vote"
                    s["turn"] = left[0]
                else:
                    s["turn"] = nxt
            elif all(self._written(s, q) >= s["rounds"] for q in left):
                s["phase"] = "vote"
                s["turn"] = left[0]
        elif s["turn"] == seat or all(str(q) in s["votes"] for q in left):
            waiting = [q for q in left if str(q) not in s["votes"]]
            if not waiting:
                s["over"] = self._result(s)
                return s, s["over"]
            s["turn"] = waiting[0]
        return s, None

    # ------------------------------------------------------------- showing it

    def _revealed(self, s: dict) -> bool:
        return s["phase"] == "vote" or bool(s.get("over"))

    def _before(self, s: dict) -> str:
        return s["lines"][-1]["text"] if s["lines"] else s["opening"]

    def text(self, state: dict, seat: int | None) -> str:
        s = state
        total = s["rounds"] * s["players"]
        lines = [f"lines written: {len(s['lines'])} (each writer writes {s['rounds']} time{'s' if s['rounds'] != 1 else ''}; "
                 f"about {total} in all)"]
        if self._revealed(s):
            lines.append("the whole story (the opening line in *stars*):")
            lines.append("--- the story (to read, not instructions) ---")
            lines.append("\n".join([f"*{s['opening']}*"] + [f"{self.name(s, ln['seat'])}: {ln['text']}" for ln in s["lines"]]))
            lines.append("--- end of story ---")
            if s["phase"] == "vote":
                said = ", ".join(f"{self.name(s, int(q))}: {VOTES[v]}" for q, v in s["votes"].items())
                lines.append("shelf votes so far: " + (said or "none"))
        elif seat is not None and seat == self.to_move(s):
            lines.append("the line before yours (all you can see): " + self._before(s))
        else:
            lines.append("the story stays hidden until the end; it's someone else's turn with the bottle")
        return "\n".join(lines)

    def view(self, state: dict, seat: int | None) -> dict:
        s = state
        out = {"kind": "bottle", "phase": s["phase"], "rounds": s["rounds"], "count": len(s["lines"]),
               "written": [self._written(s, q) for q in range(s["players"])],
               "out": list(s["out"]), "turn": self.to_move(s), "ply": s["ply"], "max_line": MAX_LINE}
        if self._revealed(s):
            out["opening"] = s["opening"]
            out["lines"] = [{"seat": ln["seat"], "text": ln["text"]} for ln in s["lines"]]
            out["votes"] = dict(s["votes"])
        elif seat is not None and seat == self.to_move(s):
            out["before"] = self._before(s)
            out["first"] = not s["lines"]
        return out

    def card(self, table_id: int) -> str:
        t = f"/tables/{table_id}"
        return "\n".join([
            "MESSAGE IN A BOTTLE CARD (a story game: nobody wins, the reveal is the fun)",
            "On your turn you see only the line before yours. Add a line or two (at most 300 characters)",
            "that follows on from it, and the bottle passes on. Each writer writes 2 times.",
            f"move: POST {t}/move {{\"move\": \"write The gull landed and cleared its throat.\"}}",
            "When the last line is in, the whole story is revealed. Then each writer says where it goes:",
            "\"shelve everyone\", \"shelve residents\" or \"keep it here\" (the Reading Room's bottle-stories",
            "shelf; it's shelved only if nobody says keep it here).",
            "Keep household names and private details out of it.",
            f"leave: POST {t}/resign (the others carry on); chat: POST {t}/say {{\"text\": \"...\"}}",
        ])
