# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""Hearts, 3-5 players, with the common rules:

- A standard deck; with 3 players the 2 of diamonds is set aside, with 5 the 2s of diamonds and
  spades, so everyone gets the same number of cards.
- Each hand starts with a pass: everyone picks three cards to pass (to the left, then the right,
  then across with 4 players, then no pass, and round again). Passes are chosen in turn, kept
  secret, and swapped once everyone has chosen.
- Whoever holds the 2 of clubs leads it. Follow the suit led if you can; if you can't, play
  anything (but on the first trick, no hearts and not the queen of spades unless that's all you
  have). The highest card of the suit led takes the trick and leads the next one.
- Hearts can't be led until one has been played (unless you hold only hearts).
- Each heart taken is 1 point; the queen of spades is 13. Take all of them ("shooting the moon")
  and everyone else gets 26 instead of you.
- Hands are dealt until someone reaches the target (50 by default); then the lowest score wins.

Moves: "pass 2C 7H QS" during the pass, then "play QS". What everyone would see at a real table is
public (cards played, who took each trick, points so far); the cards you pass and are passed
are yours alone.
"""

from __future__ import annotations

import json

from . import IllegalMove
from .cards import (RANKS, SUITS, CardGame, deck, new_seed, parse_card, players_option, rank, shuffled,
                    sort_hand, suit)

ORDER = ("2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A")   # aces high
QUEEN = "QS"
TARGET = 50


def points(cards: list[str]) -> int:
    return sum(1 for c in cards if suit(c) == "H") + (13 if QUEEN in cards else 0)


def by_suit_rank(cards: list[str]) -> list[str]:
    """Clubs, diamonds, spades, hearts, low to high: easy to read in Hearts."""
    order = ("C", "D", "S", "H")
    return sorted(cards, key=lambda c: (order.index(suit(c)), ORDER.index(rank(c))))


class Hearts(CardGame):
    id = "hearts"
    title = "hearts"
    min_seats = 3

    # ------------------------------------------------------------- state

    def new(self, options: dict | None = None) -> dict:
        options = options or {}
        n = players_option(options, 3, 5)
        target = options.get("target", TARGET)
        s = {"players": n, "seed": new_seed(options), "deal": 0, "scores": [0] * n, "target": int(target),
             "out": [], "over": None, "names": [], "ply": 0}
        self._deal(s)
        return s

    def _directions(self, n: int) -> tuple[str, ...]:
        return ("left", "right", "across", "hold") if n == 4 else ("left", "right", "hold")

    def _deal(self, s: dict) -> None:
        n = s["players"]
        cards = deck()
        if n == 3:
            cards.remove("2D")
        elif n == 5:
            cards.remove("2D")
            cards.remove("2S")
        cards = shuffled(cards, s["seed"], s["deal"])
        per = len(cards) // n
        s["hands"] = [by_suit_rank(cards[i * per:(i + 1) * per]) for i in range(n)]
        s["direction"] = self._directions(n)[s["deal"] % len(self._directions(n))]
        s["passes"] = {}
        s["taken"] = [[] for _ in range(n)]
        s["trick"] = []
        s["broken"] = False
        s["tricks"] = 0
        s["deal"] += 1
        if s["direction"] == "hold":
            self._start_play(s)
        else:
            s["phase"] = "pass"
            s["turn"] = 0

    def _start_play(self, s: dict) -> None:
        s["phase"] = "play"
        s["turn"] = next(q for q in range(s["players"]) if "2C" in s["hands"][q])
        s["leader"] = s["turn"]

    def drop(self, state: dict, seat: int) -> dict:
        return state

    def _target_of(self, s: dict, seat: int) -> int:
        n = s["players"]
        step = {"left": 1, "right": n - 1, "across": 2}[s["direction"]]
        return (seat + step) % n

    # ------------------------------------------------------------- rules

    def _playable(self, s: dict, seat: int) -> list[str]:
        hand = s["hands"][seat]
        first = s["tricks"] == 0
        if not s["trick"]:                                  # leading
            if first:
                return ["2C"] if "2C" in hand else hand
            if s["broken"]:
                return list(hand)
            safe = [c for c in hand if suit(c) != "H"]
            return safe or list(hand)
        led = suit(s["trick"][0][1])
        follow = [c for c in hand if suit(c) == led]
        if follow:
            return follow
        if first:
            calm = [c for c in hand if suit(c) != "H" and c != QUEEN]
            return calm or list(hand)
        return list(hand)

    def legal_moves(self, state: dict) -> list[str]:
        if state.get("over"):
            return []
        if state["phase"] == "pass":
            return ["pass <any three of your cards>"]
        return [f"play {c}" for c in self._playable(state, state["turn"])]

    def play(self, state: dict, move: str) -> tuple[dict, dict]:
        if state.get("over"):
            raise IllegalMove("the game is over")
        seat = state["turn"]
        words = (move or "").replace(",", " ").split()
        if not words:
            raise IllegalMove('write "play QS" (or, at the start of a hand, "pass 2C 7H QS")')
        verb = words[0].lower()
        s = json.loads(json.dumps(state))
        me = self.name(s, seat)
        if s["phase"] == "pass":
            if verb != "pass":
                raise IllegalMove('it\'s time to pass: choose three cards, like "pass 2C 7H QS"')
            cards = [parse_card(w) for w in words[1:]]
            if len(cards) != 3 or None in cards or len(set(cards)) != 3:
                raise IllegalMove('pass exactly three different cards, like "pass 2C 7H QS"')
            if any(c not in s["hands"][seat] for c in cards):
                raise IllegalMove("you can only pass cards you hold")
            s["ply"] += 1
            s["passes"][str(seat)] = cards
            to = self.name(s, self._target_of(s, seat))
            info = {"move": "pass", "seat": seat, "text": f"{me} chose three cards to pass {s['direction']}",
                    "private": {"passed": cards, "to": to}}
            waiting = [q for q in range(s["players"]) if str(q) not in s["passes"]]
            if waiting:
                s["turn"] = waiting[0]
                return s, info
            for q in range(s["players"]):                     # everyone has chosen: swap
                give = s["passes"][str(q)]
                s["hands"][q] = [c for c in s["hands"][q] if c not in give]
            for q in range(s["players"]):
                s["hands"][self._target_of(s, q)] += s["passes"][str(q)]
            s["hands"] = [by_suit_rank(h) for h in s["hands"]]
            info["text"] += "; the passes are swapped"
            self._start_play(s)
            info["text"] += f", and {self.name(s, s['turn'])} leads the 2 of clubs"
            return s, info
        if verb != "play" or len(words) != 2:
            raise IllegalMove('write "play QS" (one card)')
        card = parse_card(words[1])
        if card is None or card not in s["hands"][seat]:
            raise IllegalMove("you can only play a card you hold")
        allowed = self._playable(s, seat)
        if card not in allowed:
            if not s["trick"] and s["tricks"] == 0:
                why = "the 2 of clubs leads the first trick"
            elif s["trick"] and any(suit(c) == suit(s["trick"][0][1]) for c in s["hands"][seat]):
                why = f"follow the suit led ({ {'S': 'spades', 'H': 'hearts', 'D': 'diamonds', 'C': 'clubs'}[suit(s['trick'][0][1])] }) while you can"
            elif s["tricks"] == 0:
                why = "no hearts or queen of spades on the first trick"
            else:
                why = "hearts can't be led until one has been played"
            raise IllegalMove(why)
        s["ply"] += 1
        s["hands"][seat].remove(card)
        s["trick"].append([seat, card])
        if suit(card) == "H":
            s["broken"] = True
        info = {"move": f"play {card}", "seat": seat, "card": card, "text": f"{me} played {card}"}
        if len(s["trick"]) < len(self.active(s)):
            s["turn"] = self._after(s, seat)
            return s, info
        led = suit(s["trick"][0][1])
        winner = max((p for p in s["trick"] if suit(p[1]) == led), key=lambda p: ORDER.index(rank(p[1])))[0]
        got = [c for _, c in s["trick"]]
        s["taken"][winner] += got
        s["tricks"] += 1
        pts = points(got)
        info["trick"] = got
        info["text"] += (f"; {self.name(s, winner)} takes the trick"
                         + (f" ({pts} point{'s' if pts != 1 else ''})" if pts else ""))
        s["trick"] = []
        if any(s["hands"][q] for q in self.active(s)):
            s["turn"] = s["leader"] = winner
            return s, info
        # The hand is over: score it.
        gained = [points(t) for t in s["taken"]]
        moon = [q for q in range(s["players"]) if gained[q] == 26]
        if moon:
            gained = [0 if q == moon[0] else 26 for q in range(s["players"])]
            info["text"] += f". {self.name(s, moon[0])} shot the moon! Everyone else takes 26"
        for q in range(s["players"]):
            s["scores"][q] += gained[q]
        info["text"] += ". Hand over: " + ", ".join(f"{self.name(s, q)} {s['scores'][q]}"
                                                   for q in self.active(s))
        if max(s["scores"][q] for q in self.active(s)) >= s["target"]:
            s["over"] = self._result(s)
            return s, info
        self._deal(s)
        info["text"] += ("; a new hand is dealt" + (f": pass {s['direction']}" if s["phase"] == "pass"
                                                     else f" (no pass this time; {self.name(s, s['turn'])} leads)"))
        return s, info

    def _result(self, s: dict, why: str = "") -> dict:
        playing = self.active(s)
        low = min(s["scores"][q] for q in playing)
        best = [q for q in playing if s["scores"][q] == low]
        scores = ", ".join(f"{self.name(s, q)} {s['scores'][q]}" for q in playing)
        reason = (why + "; " if why else "") + f"lowest score: {scores}"
        if len(best) == 1:
            return {"winner": best[0], "winners": best, "reason": reason}
        return {"winner": None, "winners": best, "reason": reason}

    def resign(self, state: dict, seat: int) -> tuple[dict, dict | None]:
        # Hearts needs everyone's cards in play: one player leaving ends the game, scored as it stands.
        s = json.loads(json.dumps(state))
        s["out"] = sorted(set(s["out"]) | {seat})
        s["over"] = self._result(s, f"{self.name(s, seat)} left")
        return s, s["over"]

    # ------------------------------------------------------------- showing it

    def text(self, state: dict, seat: int | None) -> str:
        s = state
        lines = ["scores: " + ", ".join(f"{self.name(s, q)}{' (you)' if q == seat else ''} {s['scores'][q]}"
                                        for q in range(s["players"])) + f" (game to {s['target']}; lowest wins)",
                 "points taken this hand: " + ", ".join(f"{self.name(s, q)} {points(s['taken'][q])}"
                                                       for q in range(s["players"]))]
        if s["phase"] == "pass":
            lines.append(f"passing {s['direction']}: everyone chooses three cards in turn "
                         f"({len(s['passes'])} of {s['players']} chosen)")
            if seat is not None and str(seat) in s["passes"]:
                lines.append("you're passing: " + " ".join(s["passes"][str(seat)]))
        else:
            lines.append("trick: " + (", ".join(f"{self.name(s, q)} {c}" for q, c in s["trick"]) or
                                      f"{self.name(s, s['turn'])} to lead") + (f" (hearts broken)" if s["broken"] else ""))
        if seat is not None and seat < s["players"]:
            lines.append("your hand: " + (" ".join(by_suit_rank(s["hands"][seat])) or "empty"))
        return "\n".join(lines)

    def view(self, state: dict, seat: int | None) -> dict:
        s = state
        mine = seat is not None and seat < s["players"]
        return {"kind": "hearts", "phase": s["phase"], "direction": s["direction"], "scores": list(s["scores"]),
                "target": s["target"], "points": [points(t) for t in s["taken"]], "counts": [len(h) for h in s["hands"]],
                "trick": [[q, c] for q, c in s["trick"]], "broken": s["broken"],
                "chosen": [q for q in range(s["players"]) if str(q) in s["passes"]],
                "passing": list(s["passes"].get(str(seat), [])) if mine else [],
                "out": list(s["out"]), "turn": self.to_move(s), "ply": s["ply"],
                "hand": by_suit_rank(s["hands"][seat]) if mine else None}

    def card(self, table_id: int) -> str:
        t = f"/tables/{table_id}"
        return "\n".join([
            "HEARTS CARD (lowest score wins)",
            "Avoid taking hearts (1 point each) and the queen of spades (13). Take ALL of them and everyone",
            "else gets 26 instead (shooting the moon). Game to 50, then the lowest score wins.",
            "Each hand starts with a pass: on your turn send three cards, \"pass 2C 7H QS\" (kept secret).",
            "Then tricks: the 2 of clubs leads first. Follow the suit led if you can; the highest card of",
            "that suit takes the trick and leads next. Hearts can't be led until one has been played.",
            "On your turn, state lists the cards you may play. Send one exactly:",
            f"move: POST {t}/move {{\"move\": \"play QS\"}}",
            "You see only your own hand.",
            f"leave: POST {t}/resign (it ends the game for everyone, scored as it stands)",
            f"chat: POST {t}/say {{\"text\": \"...\"}}",
        ])
