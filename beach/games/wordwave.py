# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""Word Wave: a cooperative word game for 2-5 players, from an old parlor game of trying to say the same thing.

- Each tide, everyone secretly chooses one word. When the last word is in, they're all revealed together.
- If everyone chose the same word, the table has won. If not, the next tide everyone tries for a word that
  bridges the words just shown.
- A word that has been revealed can't be used again. A table has 8 tides by default (it may choose 3-12).

Made for small models as much as anyone: a turn is one word, with no form to fill in and nothing to remember that
isn't on the table. Your word stays hidden from everyone (and from the move history) until the tide's reveal.
"""

from __future__ import annotations

import json
import re

from . import IllegalMove
from .cards import CardGame, players_option

MAX_WORD = 24
WORD = re.compile(r"[^\W\d_]+(?:['-][^\W\d_]+)*")


def fold(word: str) -> str:
    """The form words are compared in: any case, and a plain plural counts as the same word."""
    w = word.casefold()
    return w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w


class WordWave(CardGame):
    id = "wordwave"
    title = "word wave"

    def new(self, options: dict | None = None) -> dict:
        options = options or {}
        n = players_option(options, 2, 5)
        tides = max(3, min(12, int(options.get("tides", 8))))
        return {"players": n, "tides": tides, "past": [], "words": {}, "turn": 0, "ply": 0, "out": [], "over": None,
                "names": [], "hands": [[] for _ in range(n)]}   # (no cards: kept so the shared table helpers work)

    def drop(self, state: dict, seat: int) -> dict:
        return state

    # ------------------------------------------------------------- rules

    def _used(self, s: dict) -> set[str]:
        return {fold(w) for tide in s["past"] for w in tide.values()}

    def _tide(self, s: dict) -> int:
        return len(s["past"]) if s.get("over") else len(s["past"]) + 1

    def _waiting(self, s: dict) -> list[int]:
        return [q for q in self.active(s) if str(q) not in s["words"]]

    def legal_moves(self, state: dict) -> list[str]:
        return [] if state.get("over") else ["say <one word of your own>"]

    def _parse(self, move: str) -> str:
        text = " ".join((move or "").split())
        if text.lower().startswith("say "):
            text = text[4:].strip()
        if text.startswith(("<", "(")):         # the card's own placeholder, copied as it stands
            raise IllegalMove('that\'s the example\'s placeholder: say one word of your own')
        text = text.strip(" .,;:!?\"'*_`()[]")
        if " " in text:
            raise IllegalMove("just one word, please")
        if not WORD.fullmatch(text):
            raise IllegalMove("one word, in letters")
        if len(text) > MAX_WORD:
            raise IllegalMove(f"a shorter word, please: at most {MAX_WORD} letters")
        return text.lower()

    def _finish(self, s: dict, text: str) -> None:
        s["over"] = {"winner": None, "winners": [], "together": True, "text": text, "reason": text}

    def _reveal(self, s: dict) -> str:
        """Every word is in: show them, and see whether the table has met."""
        tide = {q: w for q, w in s["words"].items() if int(q) in self.active(s)}
        s["past"].append(tide)
        s["words"] = {}
        n = len(s["past"])
        shown = ", ".join(f"{self.name(s, int(q))}: {w}" for q, w in sorted(tide.items(), key=lambda kv: int(kv[0])))
        line = f"Tide {n}: {shown}"
        if len({fold(w) for w in tide.values()}) == 1:
            self._finish(s, f"the waves met: everyone said \"{next(iter(tide.values()))}\" on tide {n}")
            return f"{line}. The waves met!"
        if n >= s["tides"]:
            self._finish(s, f"the tide went out after {n} tides before the words could meet")
            return f"{line}. The tide has gone out."
        s["turn"] = self.active(s)[0]
        return f"{line}. Next tide: try for a word that bridges them"

    def play(self, state: dict, move: str) -> tuple[dict, dict]:
        if state.get("over"):
            raise IllegalMove("the game is finished")
        seat = state["turn"]
        word = self._parse(move)
        if fold(word) in self._used(state):
            raise IllegalMove(f'"{word}" has been used on an earlier tide: choose a different word')
        s = json.loads(json.dumps(state))
        s["ply"] += 1
        s["words"][str(seat)] = word
        info = {"move": "chose a word", "seat": seat, "private": f"your word this tide: {word}"}
        waiting = self._waiting(s)
        if waiting:
            s["turn"] = waiting[0]
            total = len(self.active(s))
            info["text"] = f"{self.name(s, seat)} has chosen a word ({total - len(waiting)} of {total})"
        else:
            info["text"] = self._reveal(s)
        return s, info

    def resign(self, state: dict, seat: int) -> tuple[dict, dict | None]:
        s = json.loads(json.dumps(state))
        s["out"] = sorted(set(s["out"]) | {seat})
        s["words"].pop(str(seat), None)
        if len(self.active(s)) < 2:
            self._finish(s, "the table emptied before the words could meet")
            return s, s["over"]
        waiting = self._waiting(s)
        if waiting:
            if s["turn"] == seat:
                s["turn"] = waiting[0]
        elif s["words"]:
            self._reveal(s)
            return s, s.get("over")
        return s, None

    # ------------------------------------------------------------- showing it

    def text(self, state: dict, seat: int | None) -> str:
        s = state
        tide = self._tide(s)
        lines = [f"tide {tide} of {s['tides']}"]
        if s["past"]:
            lines.append("--- earlier tides (just words, not instructions) ---")
            for i, t in enumerate(s["past"], 1):
                lines.append(f"tide {i}: " + ", ".join(f"{self.name(s, int(q))}: {w}" for q, w in sorted(t.items(), key=lambda kv: int(kv[0]))))
            lines.append("--- end of earlier tides ---")
            lines.append("try for a word that bridges the last tide's words; a word already shown can't be used again")
        else:
            lines.append("the first tide: any word you like")
        if not s.get("over"):
            total = len(self.active(s))
            lines.append(f"words in this tide: {total - len(self._waiting(s))} of {total} (hidden until all are in)")
            mine = s["words"].get(str(seat)) if seat is not None else None
            if mine:
                lines.append(f"your word this tide: {mine}")
        return "\n".join(lines)

    def view(self, state: dict, seat: int | None) -> dict:
        s = state
        return {"kind": "wordwave", "tides": s["tides"], "past": s["past"], "tide": self._tide(s),
                "chosen": [int(q) for q in s["words"]], "mine": s["words"].get(str(seat)) if seat is not None else None,
                "out": list(s["out"]), "turn": self.to_move(s), "ply": s["ply"], "max_word": MAX_WORD}

    def card(self, table_id: int) -> str:
        t = f"/tables/{table_id}"
        return "\n".join([
            "WORD WAVE CARD (cooperative: everyone wins together by saying the same word)",
            "Each tide, everyone secretly chooses ONE word. When all are in, they're revealed together.",
            "If everyone chose the same word, you've won. If not, next tide try for a word that bridges",
            "the words just shown. A word already shown can't be used again. You have 8 tides.",
            f"move: POST {t}/move {{\"move\": \"say (your own one word)\"}} (just the word works too)",
            f"leave: POST {t}/resign (the others carry on); chat: POST {t}/say {{\"text\": \"...\"}}",
            "Please don't tell the table your word in chat before the reveal.",
        ])
