# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""Solitaire: a table for one, in three variants chosen before the first move (the keeper, 11-09).

- Klondike, drawing one card or three: seven columns, the first card of each face up; build down in alternating
  colors; only a king (or a run headed by one) goes into an empty column; turning the stock over is unlimited.
- FreeCell: all 52 cards face up in eight columns, four free cells that hold one card each; build down in alternating
  colors; a run can move as a whole when there's room to shuffle it through the free cells and empty columns.

Every variant builds the foundations up by suit, ace to king, and is won when all 52 cards are home. A game with no
move left ends on its own; otherwise you can stop whenever you like (resign).

Moves, written short: "draw"; "w>f" (waste to foundation), "w>3" (waste to column 3); "2>f", "2>5" (column to column,
the run that fits); FreeCell: "4>c" (to a free cell), "c1>f", "c1>6". Words work too: "column 2 to foundation".
"""

from __future__ import annotations

import json
import re

from . import IllegalMove, TableGame
from .cards import RANKS, SUITS, deck, new_seed, rank, shuffled, suit

VARIANTS = {"klondike": "Klondike, draw one", "klondike3": "Klondike, draw three", "freecell": "FreeCell"}
RED = ("H", "D")


def _rank(c: str) -> int:
    return RANKS.index(rank(c))


def _stacks(card: str, on: str) -> bool:
    """card may go on `on` in a column: one rank lower, the other color."""
    return _rank(card) == _rank(on) - 1 and (suit(card) in RED) != (suit(on) in RED)


class Solitaire(TableGame):
    id = "solitaire"
    title = "solitaire"
    seats = 1
    seat_names = ("Player",)
    draws = False

    def new(self, options: dict | None = None) -> dict:
        options = options or {}
        variant = options.get("variant") if options.get("variant") in VARIANTS else "klondike"
        return self._deal(variant, new_seed(options))

    def _deal(self, variant: str, seed: int) -> dict:
        cards = shuffled(deck(), seed, 0)
        if variant == "freecell":
            tab = [[] for _ in range(8)]
            for i, c in enumerate(cards):
                tab[i % 8].append({"c": c, "up": True})
            stock = []
        else:
            tab, k = [], 0
            for col in range(7):
                tab.append([{"c": c, "up": i == col} for i, c in enumerate(cards[k:k + col + 1])])
                k += col + 1
            stock = cards[k:]
        return {"variant": variant, "seed": seed, "tab": tab, "stock": stock, "waste": [],
                "found": {s: 0 for s in SUITS}, "cells": [None] * 4 if variant == "freecell" else [],
                "ply": 0, "over": None}

    def to_move(self, state: dict) -> int | None:
        return None if state.get("over") else 0

    def outcome(self, state: dict) -> dict | None:
        return state.get("over")

    def rematch_options(self, state: dict) -> dict:
        return {"variant": state["variant"]}

    # ------------------------------------------------------------- rules

    def _home(self, s: dict) -> int:
        return sum(s["found"].values())

    def _can_found(self, s: dict, c: str) -> bool:
        return s["found"][suit(c)] == _rank(c)

    def _run_start(self, s: dict, i: int) -> int:
        """Where the movable run at the bottom of column i begins (face up, alternating, descending)."""
        col = s["tab"][i]
        k = len(col) - 1
        while k > 0 and col[k - 1]["up"] and _stacks(col[k]["c"], col[k - 1]["c"]):
            k -= 1
        return k

    def _capacity(self, s: dict, dest: int) -> int:
        free = sum(1 for c in s["cells"] if c is None)
        empty = sum(1 for j, col in enumerate(s["tab"]) if not col and j != dest)
        return (free + 1) * (2 ** empty)

    def _run_to(self, s: dict, i: int, j: int) -> int | None:
        """The index in column i of the run that can move onto column j, or None."""
        src, dest = s["tab"][i], s["tab"][j]
        if i == j or not src:
            return None
        start = self._run_start(s, i)
        cands = range(start, len(src))
        if s["variant"] == "freecell":
            cap = self._capacity(s, j)
            cands = [k for k in cands if len(src) - k <= cap]
        if not dest:
            if s["variant"] == "freecell":
                ok = [k for k in cands if k > 0]        # moving a whole column into an empty one gains nothing
                return min(ok) if ok else None          # the longest run that fits through the free spaces
            ks = [k for k in cands if rank(src[k]["c"]) == "K" and k > 0]
            return ks[0] if ks else None                 # a king already at the top of its column gains nothing
        top = dest[-1]["c"]
        for k in cands:
            if _stacks(src[k]["c"], top):
                return k
        return None

    def legal_moves(self, state: dict) -> list[str]:
        s = state
        if s.get("over"):
            return []
        out = []
        if s["ply"] == 0:
            out += [f"variant {v}" for v in VARIANTS if v != s["variant"]]
        if s["variant"] != "freecell":
            if s["stock"] or s["waste"]:
                out.append("draw")
            if s["waste"]:
                w = s["waste"][-1]
                if self._can_found(s, w):
                    out.append("w>f")
                for j, col in enumerate(s["tab"]):
                    if (not col and rank(w) == "K") or (col and _stacks(w, col[-1]["c"])):
                        out.append(f"w>{j + 1}")
        for i, col in enumerate(s["tab"]):
            if col and self._can_found(s, col[-1]["c"]):
                out.append(f"{i + 1}>f")
            for j in range(len(s["tab"])):
                if self._run_to(s, i, j) is not None:
                    out.append(f"{i + 1}>{j + 1}")
            if col and None in s["cells"]:
                out.append(f"{i + 1}>c")
        for n, c in enumerate(s["cells"]):
            if c is None:
                continue
            if self._can_found(s, c):
                out.append(f"c{n + 1}>f")
            for j, col in enumerate(s["tab"]):
                if not col or _stacks(c, col[-1]["c"]):
                    out.append(f"c{n + 1}>{j + 1}")
        return out

    def _normalize(self, move: str) -> str:
        t = " ".join((move or "").lower().split())
        if t.startswith(("variant", "draw")):
            return t                                     # before the cell words below ("freecell" is a variant here)
        t = re.sub(r"\b(free ?cell|cell)\s*(\d)", r"c\2", t)
        t = re.sub(r"\b(free ?cell|cell)\b", "c", t)
        t = re.sub(r"\b(foundations?|home)\b", "f", t)
        t = re.sub(r"\bwaste\b", "w", t)
        t = re.sub(r"\b(columns?|col|pile)\s*", "", t)
        t = re.sub(r"\s*(?:\bto\b|->|>|\bonto\b|\bon\b)\s*", ">", t)
        return t.replace(" ", "")

    def play(self, state: dict, move: str) -> tuple[dict, dict]:
        if state.get("over"):
            raise IllegalMove("the game is over")
        m = self._normalize(move)
        legal = self.legal_moves(state)
        if m.startswith("variant"):
            v = m.split(" ", 1)[1].strip() if " " in m else ""
            v = {"draw one": "klondike", "draw three": "klondike3", "klondike1": "klondike"}.get(v, v)
            if state["ply"]:
                raise IllegalMove("the variant is chosen before the first move; start a new game to change it")
            if v not in VARIANTS:
                raise IllegalMove("the variants are: " + ", ".join(VARIANTS))
            s = self._deal(v, state["seed"] + 1)
            return s, {"move": f"variant {v}", "seat": 0, "text": f"A fresh deal of {VARIANTS[v]}"}
        if m not in legal:
            raise IllegalMove(f'"{move}" isn\'t a legal move right now')
        s = json.loads(json.dumps(state))
        s["ply"] += 1
        text = ""
        src, dst = (m.split(">") + [""])[:2] if ">" in m else (m, "")
        if m == "draw":
            if s["stock"]:
                n = 3 if s["variant"] == "klondike3" else 1
                for _ in range(min(n, len(s["stock"]))):
                    s["waste"].append(s["stock"].pop())
                text = "Drew from the stock"
            else:
                s["stock"] = list(reversed(s["waste"]))
                s["waste"] = []
                text = "Turned the waste back over into the stock"
        else:
            if src == "w":
                cards = [s["waste"].pop()]
            elif src.startswith("c"):
                n = int(src[1:]) - 1
                cards, s["cells"][n] = [s["cells"][n]], None
            else:
                i = int(src) - 1
                if dst in ("f", "c"):
                    k = len(s["tab"][i]) - 1
                else:
                    k = self._run_to(state, i, int(dst) - 1)
                cards = [x["c"] for x in s["tab"][i][k:]]
                del s["tab"][i][k:]
                if s["tab"][i] and not s["tab"][i][-1]["up"]:
                    s["tab"][i][-1]["up"] = True         # turn over the card underneath
            if dst == "f":
                s["found"][suit(cards[0])] += 1
                text = f"Moved {cards[0]} home"
            elif dst == "c":
                s["cells"][s["cells"].index(None)] = cards[0]
                text = f"Moved {cards[0]} to a free cell"
            else:
                s["tab"][int(dst) - 1].extend({"c": c, "up": True} for c in cards)
                text = f"Moved {cards[0]}" + (f" and {len(cards) - 1} more" if len(cards) > 1 else "") + f" to column {dst}"
        home = self._home(s)
        if home == 52:
            s["over"] = {"winner": 0, "reason": f"all 52 cards are home ({VARIANTS[s['variant']]})"}
            text += ". All 52 cards are home!"
        elif not [x for x in self.legal_moves(s) if not x.startswith("variant")]:
            s["over"] = {"winner": None, "reason": f"no moves left, with {home} of 52 cards home"}
            text += ". No moves left."
        return s, {"move": m, "seat": 0, "text": text}

    def resign(self, state: dict, seat: int) -> tuple[dict, dict | None]:
        s = json.loads(json.dumps(state))
        s["over"] = {"winner": None, "reason": f"stopped with {self._home(s)} of 52 cards home"}
        return s, s["over"]

    # ------------------------------------------------------------- showing it

    def text(self, state: dict, seat: int | None) -> str:
        s = state
        f = "  ".join(f"{x}: {RANKS[n - 1] + x if n else '-'}" for x, n in s["found"].items())
        lines = [f"{VARIANTS[s['variant']]}. Foundations (next card goes on top): {f}. Home: {self._home(s)} of 52."]
        if s["variant"] == "freecell":
            lines.append("Free cells: " + "  ".join(f"c{n + 1}: {c or '-'}" for n, c in enumerate(s["cells"])))
        else:
            top = s["waste"][-3:] if s["variant"] == "klondike3" else s["waste"][-1:]
            lines.append(f"Stock: {len(s['stock'])} cards. Waste: {' '.join(top) or '-'}"
                         + (" (the last one is the one you can play)" if len(top) > 1 else ""))
        lines.append("Columns, left to right (## is face down; the LAST card of each column is the one on top):")
        for i, col in enumerate(s["tab"]):
            lines.append(f"{i + 1}: " + (" ".join(x["c"] if x["up"] else "##" for x in col) or "(empty)"))
        if s["ply"] == 0:
            lines.append("Before your first move you may switch variant: " + ", ".join(f"variant {v}" for v in VARIANTS))
        return "\n".join(lines)

    def view(self, state: dict, seat: int | None) -> dict:
        s = state
        return {"kind": "solitaire", "variant": s["variant"], "variants": VARIANTS, "ply": s["ply"],
                "tab": [[x["c"] if x["up"] else None for x in col] for col in s["tab"]],
                "stock": len(s["stock"]), "waste": s["waste"][-3:] if s["variant"] == "klondike3" else s["waste"][-1:],
                "waste_n": len(s["waste"]), "found": {x: (RANKS[n - 1] + x if n else None) for x, n in s["found"].items()},
                "cells": s["cells"], "home": self._home(s), "can_change": s["ply"] == 0 and not s.get("over"), "out": []}

    def card(self, table_id: int) -> str:
        t = f"/tables/{table_id}"
        return "\n".join([
            "SOLITAIRE CARD (a table for one: no one else's turn to wait for)",
            "Build the four foundations up by suit, ace to king. In the columns, build down in alternating colors",
            "(a red 6 on a black 7). Win by getting all 52 cards home. Your state lists every legal move.",
            "Moves: draw (turn cards from the stock), w>f (waste to foundation), w>3 (waste to column 3),",
            "2>f (column 2's top card home), 2>5 (move the run that fits from column 2 to column 5).",
            "FreeCell adds 4>c (column 4's top card to a free cell), c1>f and c1>6. Words work too: \"column 2 to 5\".",
            f"move: POST {t}/move {{\"move\": \"draw\"}}. Before the first move: \"variant klondike3\" or \"variant freecell\".",
            f"stop: POST {t}/resign",
        ])
