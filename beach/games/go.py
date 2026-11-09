# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""Go on a 9x9 board: Black (x, seat 0) and White (o, seat 1) take turns placing a stone or passing.

- A group of connected stones with no empty point next to it is captured.
- A move may not leave its own group with no empty point next to it (after any captures it makes), and may not
  recreate a whole-board position from earlier in the game (this covers ko).
- Two passes in a row end the game, and so does the move limit. Scoring is by area: your stones plus the empty regions
  that touch only your stones, with komi for White (6.5 unless the table chose otherwise). Every stone on the board at
  the end counts as alive, so a player who thinks a group is dead captures it before passing.

Points are named as on most Go boards: columns A-H then J (there's no I), rows 1-9 from the bottom.
"""

from __future__ import annotations

import hashlib
import json

from . import IllegalMove, TableGame

SIZE = 9
COLS = "ABCDEFGHJ"
EMPTY = "."
STONES = ("x", "o")
NAMES = ("Black", "White")
MAX_PLY = 240


def point(i: int) -> str:
    return COLS[i % SIZE] + str(i // SIZE + 1)


def neighbors(i: int) -> list[int]:
    r, f = divmod(i, SIZE)
    return [r2 * SIZE + f2 for r2, f2 in ((r - 1, f), (r + 1, f), (r, f - 1), (r, f + 1))
            if 0 <= r2 < SIZE and 0 <= f2 < SIZE]


def group(board: str, i: int) -> tuple[set[int], set[int]]:
    """The connected stones at i, and the empty points next to them (their liberties)."""
    stone, stack, seen, libs = board[i], [i], {i}, set()
    while stack:
        for n in neighbors(stack.pop()):
            if board[n] == EMPTY:
                libs.add(n)
            elif board[n] == stone and n not in seen:
                seen.add(n)
                stack.append(n)
    return seen, libs


def groups(board: str, stone: str) -> list[tuple[set[int], set[int]]]:
    out, done = [], set()
    for i, c in enumerate(board):
        if c == stone and i not in done:
            g = group(board, i)
            done |= g[0]
            out.append(g)
    return out


def _key(board: str) -> str:
    return hashlib.sha256(board.encode("ascii")).hexdigest()[:16]


class Go(TableGame):
    id = "go"
    title = "go (9x9)"
    seats = 2
    seat_names = NAMES
    draws = False

    def new(self, options: dict | None = None) -> dict:
        options = options or {}
        board = EMPTY * (SIZE * SIZE)
        return {"board": board, "turn": 0, "ply": 0, "passes": 0, "captures": [0, 0], "last": None,
                "seen": [_key(board)], "komi": float(options.get("komi", 6.5)), "over": None}

    def to_move(self, state: dict) -> int | None:
        return None if state.get("over") else state["turn"]

    def outcome(self, state: dict) -> dict | None:
        return state.get("over")

    # ------------------------------------------------------------- rules

    def _place(self, s: dict, i: int) -> tuple[str, int]:
        """The board after placing at i, and how many stones it captured. Raises IllegalMove if it can't be played."""
        me, foe = STONES[s["turn"]], STONES[1 - s["turn"]]
        if s["board"][i] != EMPTY:
            raise IllegalMove(f"{point(i)} already has a stone on it")
        cells = list(s["board"])
        cells[i] = me
        taken = 0
        for n in neighbors(i):
            if cells[n] == foe:
                stones, libs = group("".join(cells), n)
                if not libs:
                    for q in stones:
                        cells[q] = EMPTY
                    taken += len(stones)
        board = "".join(cells)
        if not group(board, i)[1]:
            raise IllegalMove(f"{point(i)} would leave your own stones with no empty point next to them")
        if _key(board) in s["seen"]:
            raise IllegalMove(f"{point(i)} would repeat an earlier position of the whole board (the ko rule): play somewhere else first")
        return board, taken

    def legal_moves(self, state: dict) -> list[str]:
        if state.get("over"):
            return []
        out = []
        for i, c in enumerate(state["board"]):
            if c == EMPTY:
                try:
                    self._place(state, i)
                except IllegalMove:
                    continue
                out.append(point(i))
        return out + ["pass"]

    def _parse(self, move: str) -> int | None:
        """A point index, or None for a pass."""
        text = (move or "").strip().upper().rstrip(".")
        if text.startswith("PLAY "):
            text = text[5:].strip()
        if text == "PASS":
            return None
        if len(text) in (2, 3) and text[0] == "I" and text[1:].isdigit():
            raise IllegalMove("a Go board has no I column: the columns go A-H, then J")
        if len(text) == 2 and text[0] in COLS and text[1] in "123456789":
            return (int(text[1]) - 1) * SIZE + COLS.index(text[0])
        raise IllegalMove('name a point such as D4, or say "pass"')

    def score(self, s: dict) -> dict:
        """Area scoring: stones on the board plus empty regions that touch only one color."""
        b, area, done = s["board"], [b_count(s["board"], 0), b_count(s["board"], 1)], set()
        for i, c in enumerate(b):
            if c != EMPTY or i in done:
                continue
            region, stack, touch = {i}, [i], set()
            while stack:
                for n in neighbors(stack.pop()):
                    if b[n] == EMPTY and n not in region:
                        region.add(n)
                        stack.append(n)
                    elif b[n] != EMPTY:
                        touch.add(b[n])
            done |= region
            if len(touch) == 1:
                area[STONES.index(touch.pop())] += len(region)
        return {"black": area[0], "white": area[1] + s["komi"], "komi": s["komi"]}

    def _end(self, s: dict, why: str) -> None:
        t = self.score(s)
        if t["black"] == t["white"]:
            s["over"] = {"winner": None, "reason": f"a tie, {t['black']:g} each ({why})", "score": t}
            return
        win = 0 if t["black"] > t["white"] else 1
        s["over"] = {"winner": win, "score": t, "reason": f"{NAMES[win]} wins by {abs(t['black'] - t['white']):g}: Black {t['black']:g}, "
                                                          f"White {t['white']:g} with {t['komi']:g} komi ({why})"}

    def play(self, state: dict, move: str) -> tuple[dict, dict]:
        if state.get("over"):
            raise IllegalMove("the game is over")
        i = self._parse(move)
        s = json.loads(json.dumps(state))
        who = NAMES[s["turn"]]
        s["ply"] += 1
        if i is None:
            s["passes"] += 1
            s["last"] = "pass"
            info = {"move": "pass", "seat": state["turn"], "text": f"{who} passes"}
        else:
            s["board"], taken = self._place(state, i)
            s["captures"][s["turn"]] += taken
            s["seen"].append(_key(s["board"]))
            s["passes"] = 0
            s["last"] = point(i)
            info = {"move": point(i), "seat": state["turn"],
                    "text": f"{who} plays {point(i)}" + (f", capturing {taken}" if taken else "")}
        s["turn"] = 1 - s["turn"]
        if s["passes"] >= 2:
            self._end(s, "both players passed")
        elif s["ply"] >= MAX_PLY:
            self._end(s, "the move limit")
        return s, info

    # ------------------------------------------------------------- showing it

    def _dangers(self, s: dict, seat: int) -> list[str]:
        """Plain help for the player to move: their stones one move from capture, and captures they can make."""
        out = []
        for stones, libs in groups(s["board"], STONES[seat]):
            if len(libs) == 1:
                out.append(f"your stones at {','.join(point(q) for q in sorted(stones))} have one liberty left, at {point(next(iter(libs)))}")
        legal = set(self.legal_moves(s))
        for stones, libs in groups(s["board"], STONES[1 - seat]):
            if len(libs) == 1 and point(next(iter(libs))) in legal:
                out.append(f"you can capture {len(stones)} stone{'s' if len(stones) != 1 else ''} by playing {point(next(iter(libs)))}")
        return out

    def text(self, state: dict, seat: int | None) -> str:
        s = state
        b = s["board"]
        head = "    " + " ".join(COLS)
        rows = [f"{r + 1:>2}  " + " ".join(b[r * SIZE:(r + 1) * SIZE]) + f"  {r + 1}" for r in range(SIZE - 1, -1, -1)]
        lines = [head, *rows, head,
                 f"x = Black, o = White. Captured so far: Black {s['captures'][0]}, White {s['captures'][1]}. "
                 f"White gets {s['komi']:g} komi."]
        if seat is not None:
            lines.append(f"You are {NAMES[seat]} ({STONES[seat]}).")
        if s["last"]:
            lines.append(f"Last move: {NAMES[1 - s['turn']] if not s.get('over') else 'the game ended on'} {s['last']}")
        if s["passes"] == 1 and not s.get("over"):
            lines.append("The other player just passed: if you pass too, the game ends and is scored.")
        if seat is not None and seat == self.to_move(s):
            lines.extend(self._dangers(s, seat))
        if s.get("over") and s["over"].get("score"):
            lines.append(s["over"]["reason"])
        return "\n".join(lines)

    def view(self, state: dict, seat: int | None) -> dict:
        s = state
        return {"kind": "go", "board": s["board"], "size": SIZE, "cols": COLS, "turn": self.to_move(s), "ply": s["ply"],
                "last": s["last"], "captures": s["captures"], "komi": s["komi"], "passes": s["passes"], "out": [],
                "score": (s.get("over") or {}).get("score")}

    def card(self, table_id: int) -> str:
        t = f"/tables/{table_id}"
        return "\n".join([
            "GO CARD (9x9)",
            "Black (x) moves first, then you take turns placing a stone on an empty point, or passing.",
            "Points are a column and a row: columns A-H then J (there is no I), rows 1-9.",
            "A group of connected stones with no empty point next to it is captured and taken off.",
            "You can't play where your own group would have no empty point next to it (unless the move captures",
            "first), or recreate an earlier position of the whole board. Your state lists every legal point.",
            f"move: POST {t}/move {{\"move\": \"D4\"}} or {{\"move\": \"pass\"}}",
            "Two passes in a row end the game. Score: your stones plus the empty areas only you surround; White",
            "gets 6.5 for moving second. Every stone left on the board counts as alive, so capture what's dead",
            "before you pass.",
            f"resign: POST {t}/resign; chat: POST {t}/say {{\"text\": \"...\"}}",
            "The game waits for you; leaving never forfeits.",
        ])


def b_count(board: str, seat: int) -> int:
    return board.count(STONES[seat])
