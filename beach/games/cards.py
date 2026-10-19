# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""Shared pieces for card games: a standard 52-card deck, card notation, and fair shuffles.

Notation: rank then suit, upper case: "7H", "10D", "QS", "AC". Ranks A 2-10 J Q K; suits S (spades),
H (hearts), D (diamonds), C (clubs). Parsing is forgiving about case and spaces ("10 d", "qs").

Shuffles come from a random seed kept in the game's state, so a table's deck order is decided
by the Beach alone (never by a player) and a test can replay a game exactly.
"""

from __future__ import annotations

import json
import random
import secrets

from . import TableGame

RANKS = ("A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K")
SUITS = ("S", "H", "D", "C")
SUIT_NAMES = {"S": "spades", "H": "hearts", "D": "diamonds", "C": "clubs"}
SUIT_BY_NAME = {v: k for k, v in SUIT_NAMES.items()} | {v[:-1]: k for k, v in SUIT_NAMES.items()}
RANK_WORDS = {"A": "ace", "J": "jack", "Q": "queen", "K": "king"}
_WORDS = dict(RANK_WORDS, **{str(n): w for n, w in zip(range(2, 11), ("two", "three", "four", "five", "six",
                                                                       "seven", "eight", "nine", "ten"))})
RANK_BY_WORD = {w: r for r, w in _WORDS.items()} | {w + "s": r for r, w in _WORDS.items()} | {"sixes": "6"}


def deck() -> list[str]:
    return [r + s for s in SUITS for r in RANKS]


def rank(card: str) -> str:
    return card[:-1]


def suit(card: str) -> str:
    return card[-1]


def parse_card(text: str) -> str | None:
    """'7h', '10 D', 'qs' -> '7H', '10D', 'QS'; None if it isn't a card."""
    t = (text or "").replace(" ", "").upper()
    if len(t) < 2:
        return None
    r, s = t[:-1], t[-1]
    if r == "1":                    # "1" alone isn't a rank; "10" is
        return None
    return r + s if r in RANKS and s in SUITS else None


def parse_rank(text: str) -> str | None:
    """'7s', '7', 'sevens', 'Aces', 'queens', '10s' -> '7', '7', '7', 'A', 'Q', '10'."""
    t = (text or "").strip().lower()
    if t in RANK_BY_WORD:
        return RANK_BY_WORD[t]
    if t.endswith("s") and t[:-1].upper() in RANKS:
        t = t[:-1]
    return t.upper() if t.upper() in RANKS else None


def plural(r: str) -> str:
    """How a rank is written in moves: '7s', '10s', 'As', 'Js'."""
    return r + "s"


def sort_hand(cards: list[str]) -> list[str]:
    """By suit, then rank: for games played by suit (Crazy Eights)."""
    return sorted(cards, key=lambda c: (SUITS.index(suit(c)), RANKS.index(rank(c))))


def sort_by_rank(cards: list[str]) -> list[str]:
    """By rank, then suit: for games played in sets (Go Fish), so a pair or three sit together (10-18)."""
    return sorted(cards, key=lambda c: (RANKS.index(rank(c)), SUITS.index(suit(c))))


def shuffled(cards: list[str], seed: int, n: int) -> list[str]:
    """The cards in a fair random order: shuffle number `n` of the table with this seed."""
    out = list(cards)
    random.Random(f"{seed}:{n}").shuffle(out)
    return out


def new_seed(options: dict) -> int:
    seed = options.get("seed")
    return int(seed) if seed is not None else secrets.randbits(48)


def players_option(options: dict, low: int, high: int) -> int:
    n = options.get("players", 2)
    try:
        n = int(n)
    except (TypeError, ValueError):
        n = 2
    return max(low, min(high, n))


def number_word(n: int) -> str:
    return ("no", "one", "two", "three", "four")[n] if 0 <= n <= 4 else str(n)


class CardGame(TableGame):
    """What the card games share: 2-5 seats chosen when the table opens, players named in turn
    order (the Boardwalk keeps `state["names"]` current), players who resign drop out while the
    rest play on, and no draw offers.

    Hidden hands: the state holds every hand, the stock order and the shuffle seed, and is never
    shown. `text()` and `view()` give a seat its own hand and everyone's counts; a watcher
    (seat None) sees counts only. Move info (which goes into the table's public history) holds
    only what everyone at a real table would see; what only the mover sees goes under "private".
    """

    seats = 5                      # the most a table can have; each table's own count is in its state
    min_seats = 2
    seat_names: tuple[str, ...] = ()
    draws = False

    def seat_count(self, state: dict) -> int:
        return state["players"]

    def seat_label(self, state: dict, s: int) -> str:
        return f"seat {s + 1}"

    def name(self, state: dict, s: int) -> str:
        names = state.get("names") or []
        return names[s] if s < len(names) and names[s] else f"seat {s + 1}"

    def active(self, state: dict) -> list[int]:
        return [s for s in range(state["players"]) if s not in state["out"]]

    def to_move(self, state: dict) -> int | None:
        return None if state.get("over") else state["turn"]

    def outcome(self, state: dict) -> dict | None:
        return state.get("over")

    def _after(self, state: dict, seat: int, ok=lambda s: True) -> int | None:
        """The next seat after `seat`, in turn order, still playing and for whom `ok(s)`."""
        n = state["players"]
        for k in range(1, n + 1):
            s = (seat + k) % n
            if s not in state["out"] and ok(s):
                return s
        return None

    def _counts_line(self, state: dict, seat: int | None) -> str:
        parts = []
        for s in range(state["players"]):
            who = self.name(state, s) + (" (you)" if s == seat else "")
            n = len(state["hands"][s])
            parts.append(f"{who} {'left the game' if s in state['out'] else str(n) + (' card' if n == 1 else ' cards')}")
        return "hands: " + ", ".join(parts)

    def drop(self, state: dict, seat: int) -> dict:
        """What happens to a resigning player's cards (the game's own rule)."""
        raise NotImplementedError

    def resign(self, state: dict, seat: int) -> tuple[dict, dict | None]:
        """The player leaves; the others play on. The last one left wins."""
        state = self.drop(json.loads(json.dumps(state)), seat)
        state["out"] = sorted(set(state["out"]) | {seat})
        left = self.active(state)
        if len(left) == 1:
            state["over"] = {"winner": left[0], "winners": left}   # the table adds who resigned
            return state, state["over"]
        if state["turn"] == seat:
            state["turn"] = self._next_turn(state, seat)
            state.pop("drawn", None)
        return state, None

    def _next_turn(self, state: dict, seat: int) -> int:
        return self._after(state, seat)
