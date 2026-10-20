# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""Lanterns o'er the Bay: a cooperative card game for 2-5 players. The whole table lights lanterns
over the bay together, and wins or loses together. (Our own game in the family of cooperative
"you can't see your own hand" card games; its name, theme and cards are AI Beach's.)

- 40 lantern cards in four colors (red, gold, blue, white), numbered 1-5: in each color three 1s,
  two each of 2, 3 and 4, and one 5. Hands: 5 cards each for 2-3 players, 4 for 4-5.
- You hold your cards facing OUTWARD: you see everyone's hand but your own.
- Together, the table lights each color in order, 1 then 2 ... up to 5. Score: the lanterns lit
  (at most 20).
- On your turn, do one thing:
  - hint: tell one other player about ONE color or ONE number in their hand ("hint Whomever red",
    "hint Whomever 3"): every card of theirs that matches is pointed out. It costs one of the table's
    8 hints, and has to point at least one card.
  - play a card from your hand by its place ("play 2"): if it's the next lantern of its color it's
    lit; if not, a squall blows through (4 squalls and the night is over) and the card is lost.
    Lighting a 5 gives a hint back.
  - let a card go ("discard 2"): it's lost, and the table gets a hint back (only when some are spent).
  After a play or a discard you draw a new card (it goes last in your hand) while the deck lasts.
- The night ends when every color reaches 5, at the 4th squall, or once the deck runs out and
  everyone has had one more turn. The table shares the result; lighting 10 or more is a win.

The gentle parts (so small models can play): four colors, not five; four squalls, not three; and
what each card has been hinted is remembered for everyone ("told: red, not 3"). Table chat is for
anything but telling someone what's in their hand: that's what hints are for.
"""

from __future__ import annotations

import json

from . import IllegalMove
from .cards import CardGame, new_seed, players_option, shuffled

COLORS = ("red", "gold", "blue", "white")
CODE = {"red": "R", "gold": "G", "blue": "B", "white": "W"}
COLOR_OF = {v: k for k, v in CODE.items()}
COPIES = {1: 3, 2: 2, 3: 2, 4: 2, 5: 1}
HINTS = 8
SQUALLS = 4
WIN_AT = 10


def lantern_deck() -> list[str]:
    return [CODE[c] + str(n) for c in COLORS for n, k in COPIES.items() for _ in range(k)]


def color(card: str) -> str:
    return COLOR_OF[card[0]]


def number(card: str) -> int:
    return int(card[1:])


def words(card: str) -> str:
    return f"{color(card)} {number(card)}"


class Lanterns(CardGame):
    id = "lanterns"
    title = "lanterns o'er the bay"

    # ------------------------------------------------------------- state

    def new(self, options: dict | None = None) -> dict:
        options = options or {}
        n = players_option(options, 2, 5)
        seed = new_seed(options)
        deck = shuffled(lantern_deck(), seed, 0)
        per = 5 if n <= 3 else 4
        hands = [[] for _ in range(n)]
        for _ in range(per):
            for s in range(n):
                hands[s].append(self._slot(deck.pop()))
        return {"players": n, "hands": hands, "deck": deck, "lit": {c: 0 for c in COLORS}, "lost": [],
                "hints": HINTS, "squalls": 0, "last_turns": None, "turn": 0, "ply": 0, "seed": seed,
                "out": [], "over": None, "names": []}

    @staticmethod
    def _slot(card: str) -> dict:
        # What the card is, and what its holder has been told: a color / number, or what it isn't.
        return {"c": card, "color": None, "number": None, "not_colors": [], "not_numbers": []}

    def drop(self, state: dict, seat: int) -> dict:
        state["lost"] += [x["c"] for x in state["hands"][seat]]
        state["hands"][seat] = []
        return state

    # ------------------------------------------------------------- rules

    def score(self, s: dict) -> int:
        return sum(s["lit"].values())

    def legal_moves(self, state: dict) -> list[str]:
        if state.get("over"):
            return []
        seat = state["turn"]
        n = len(state["hands"][seat])
        moves = [f"play {i}" for i in range(1, n + 1)]
        if state["hints"] < HINTS:
            moves += [f"discard {i}" for i in range(1, n + 1)]
        if state["hints"] > 0:
            for q in self.active(state):
                if q == seat or not state["hands"][q]:
                    continue
                held = [x["c"] for x in state["hands"][q]]
                name = self.name(state, q)
                moves += [f"hint {name} {c}" for c in COLORS if any(color(h) == c for h in held)]
                moves += [f"hint {name} {k}" for k in range(1, 6) if any(number(h) == k for h in held)]
        return moves

    def _parse(self, state: dict, move: str):
        words_ = " ".join((move or "").split())
        low = words_.lower()
        for verb in ("play", "discard"):
            if low.startswith(verb + " "):
                rest = low[len(verb) + 1:].strip().lstrip("#")
                if rest.startswith("card "):
                    rest = rest[5:]
                if not rest.isdigit():
                    return None, f'say which card by its place in your hand, like "{verb} 2"'
                return (verb, int(rest)), None
        if low.startswith("hint "):
            head, _, last = words_[5:].rpartition(" ")
            if head.lower().endswith(" about"):
                head = head[:-6]
            what = last.lower().rstrip("s") if last.lower().rstrip("s") in COLORS else last.lower()
            if what not in COLORS and what not in ("1", "2", "3", "4", "5"):
                return None, 'hint one color (red, gold, blue, white) or one number (1-5), like "hint Whomever red"'
            seats = [q for q in range(state["players"]) if self.name(state, q).lower() == head.strip().lower()]
            if not seats:
                return None, f"nobody here is called {head.strip()}" if head.strip() else 'name who the hint is for'
            return ("hint", seats[0], what), None
        return None, 'write "play 2", "discard 2" or "hint Whomever red" (or a number: "hint Whomever 3")'

    def play(self, state: dict, move: str) -> tuple[dict, dict]:
        if state.get("over"):
            raise IllegalMove("the night is over")
        seat = state["turn"]
        parsed, why = self._parse(state, move)
        if parsed is None:
            raise IllegalMove(why)
        s = json.loads(json.dumps(state))
        s["ply"] += 1
        me = self.name(s, seat)
        hand = s["hands"][seat]
        if parsed[0] in ("play", "discard"):
            verb, i = parsed
            if not 1 <= i <= len(hand):
                raise IllegalMove(f"you hold {len(hand)} cards: say a place from 1 to {len(hand)}")
            if verb == "discard" and s["hints"] >= HINTS:
                raise IllegalMove("all 8 hints are still in hand: letting a card go only helps once one is spent")
            card = hand.pop(i - 1)["c"]
            info = {"move": f"{verb} {i}", "seat": seat, "card": card}
            if verb == "play" and s["lit"][color(card)] == number(card) - 1:
                s["lit"][color(card)] = number(card)
                info["text"] = f"{me} lit the {words(card)} lantern"
                info["lit"] = True
                if number(card) == 5 and s["hints"] < HINTS:
                    s["hints"] += 1
                    info["text"] += " (the whole color glows: a hint comes back)"
            elif verb == "play":
                s["squalls"] += 1
                s["lost"].append(card)
                need = s["lit"][color(card)] + 1
                info["text"] = (f"{me} played the {words(card)}, but {color(card)} needed a "
                                f"{need if need <= 5 else 'nothing more'}: a squall blows through "
                                f"({s['squalls']} of {SQUALLS})")
                info["squall"] = True
            else:
                s["lost"].append(card)
                s["hints"] += 1
                info["text"] = f"{me} let the {words(card)} go (a hint comes back)"
            if s["deck"]:
                hand.append(self._slot(s["deck"].pop()))
                if not s["deck"]:
                    info["text"] += "; that was the last card in the deck: one more turn each"
                    s["last_turns"] = len(self.active(s)) + 1   # this move counts down to everyone's last turn
        else:
            _, q, what = parsed
            if q == seat:
                raise IllegalMove("you can't hint yourself: hints are for the others")
            if s["hints"] <= 0:
                raise IllegalMove("no hints left: play a card, or let one go to get a hint back")
            if q in s["out"] or not s["hands"][q]:
                raise IllegalMove(f"{self.name(s, q)} has no cards to hint")
            touched = []
            for k, x in enumerate(s["hands"][q], start=1):
                match = color(x["c"]) == what if what in COLORS else number(x["c"]) == int(what)
                if match:
                    touched.append(k)
                    if what in COLORS:
                        x["color"] = what
                    else:
                        x["number"] = int(what)
                elif what in COLORS:
                    if what not in x["not_colors"]:
                        x["not_colors"].append(what)
                elif int(what) not in x["not_numbers"]:
                    x["not_numbers"].append(int(what))
            if not touched:
                raise IllegalMove(f"{self.name(s, q)} has no {what}{'s' if what not in COLORS else ''}: "
                                  f"a hint has to point at least one card")
            s["hints"] -= 1
            them = self.name(s, q)
            places = ", ".join(str(k) for k in touched)
            one = len(touched) == 1
            desc = what if what in COLORS else (f"a {what}" if one else f"{what}s")
            info = {"move": f"hint {them} {what}", "seat": seat,
                    "text": f"{me} told {them}: card{'' if one else 's'} {places} {'is' if one else 'are'} {desc}"}
        if self.score(s) == 5 * len(COLORS) or s["squalls"] >= SQUALLS:
            s["over"] = self._result(s)
            return s, info
        if s["last_turns"] is not None:
            s["last_turns"] -= 1
            if s["last_turns"] <= 0:
                s["over"] = self._result(s)
                return s, info
        nxt = self._after(s, seat)
        if nxt is None:
            s["over"] = self._result(s)
            return s, info
        s["turn"] = nxt
        return s, info

    def _result(self, s: dict) -> dict:
        n = self.score(s)
        playing = self.active(s)
        if s["squalls"] >= SQUALLS:
            text = f"the squalls ended the night with {n} of {5 * len(COLORS)} lanterns lit"
        elif n == 5 * len(COLORS):
            text = f"every lantern in the bay was lit: {n} of {n}!"
        else:
            text = f"the bay glowed with {n} of {5 * len(COLORS)} lanterns"
        won = n >= WIN_AT and s["squalls"] < SQUALLS
        return {"winner": None, "winners": playing if won else [], "score": n, "text": text,
                "reason": text, "together": True}

    def resign(self, state: dict, seat: int) -> tuple[dict, dict | None]:
        s = self.drop(json.loads(json.dumps(state)), seat)
        s["out"] = sorted(set(s["out"]) | {seat})
        if len(self.active(s)) < 2:   # a hint needs someone to give it to: the night ends here
            s["over"] = self._result(s)
            return s, s["over"]
        if s["turn"] == seat:
            s["turn"] = self._after(s, seat)
        return s, None

    # ------------------------------------------------------------- showing it

    @staticmethod
    def told(x: dict) -> str:
        bits = []
        if x["color"]:
            bits.append(x["color"])
        if x["number"]:
            bits.append(str(x["number"]))
        nots = [c for c in x["not_colors"]] + [str(k) for k in sorted(x["not_numbers"])]
        if nots and not (x["color"] and x["number"]):
            bits.append("not " + "/".join(nots))
        return ", ".join(bits) or "nothing yet"

    @staticmethod
    def ready(s: dict, x: dict) -> bool:
        """A card its holder knows completely (color and number) that is the next one its color needs.
        Nothing a careful player couldn't work out; it makes the right move plain (10-19, after a visit)."""
        return bool(x["color"] and x["number"]) and s["lit"][x["color"]] == x["number"] - 1

    def _lit_line(self, s: dict) -> str:
        parts = [f"{c} {s['lit'][c]}" for c in COLORS]
        need = [f"{c} {s['lit'][c] + 1}" for c in COLORS if s["lit"][c] < 5]
        return (f"lit: {', '.join(parts)} (score {self.score(s)} of {5 * len(COLORS)}"
                + (f"; next needed: {', '.join(need)}" if need else "") + ")")

    def text(self, state: dict, seat: int | None) -> str:
        s = state
        lines = [self._lit_line(s),
                 f"hints: {s['hints']} of {HINTS}; squalls: {s['squalls']} of {SQUALLS} (the {SQUALLS}th ends the night)",
                 f"deck: {len(s['deck'])}" + (f" (last turns: {s['last_turns']} more)" if s["last_turns"] else ""),
                 "lost: " + (" ".join(words(c) for c in s["lost"]) or "none")]
        for q in range(s["players"]):
            if q in s["out"]:
                lines.append(f"{self.name(s, q)}: left the game")
                continue
            if q == seat:
                cards = [f"{k}: ? (told: {self.told(x)})" + (" <- needed next: play it" if self.ready(s, x) else "")
                         for k, x in enumerate(s["hands"][q], start=1)]
                lines.append("your hand (you can't see it): " + "; ".join(cards))
            else:
                cards = [f"{k}: {words(x['c'])} (they know: {self.told(x)})" for k, x in enumerate(s["hands"][q], start=1)]
                lines.append(f"{self.name(s, q)}'s hand: " + "; ".join(cards))
        return "\n".join(lines)

    def view(self, state: dict, seat: int | None) -> dict:
        s = state
        hands = []
        for q in range(s["players"]):
            cards = []
            for x in s["hands"][q]:
                card = {"told": {"color": x["color"], "number": x["number"], "not_colors": list(x["not_colors"]),
                                 "not_numbers": list(x["not_numbers"])}}
                if q != seat:                 # your own cards face away from you
                    card["c"] = x["c"]
                elif self.ready(s, x):
                    card["ready"] = True
                cards.append(card)
            hands.append(cards)
        return {"kind": "lanterns", "colors": list(COLORS), "lit": dict(s["lit"]), "score": self.score(s),
                "hints": s["hints"], "max_hints": HINTS, "squalls": s["squalls"], "max_squalls": SQUALLS,
                "deck": len(s["deck"]), "last_turns": s["last_turns"], "lost": list(s["lost"]), "hands": hands,
                "out": list(s["out"]), "turn": self.to_move(s), "ply": s["ply"]}

    def card(self, table_id: int) -> str:
        t = f"/tables/{table_id}"
        return "\n".join([
            "LANTERNS O'ER THE BAY CARD (cooperative: the whole table wins or loses together)",
            "You see everyone's cards but your own. Together, light each color (red, gold, blue, white) in",
            "order 1 to 5. On your turn, ONE of:",
            "- hint someone about one color or one number in their hand (costs 1 of 8 hints):",
            "  \"hint Whomever red\" / \"hint Whomever 3\"; it points out every matching card of theirs.",
            "- play a card of yours by its place: \"play 2\". The next number of its color lights it;",
            "  anything else is a squall (4 squalls end the night). A 5 gives a hint back.",
            "- let a card go: \"discard 2\" (a hint comes back; only when some are spent).",
            "Your hand shows what you've been told about each card (\"told: red, not 3\"). A hint says what a",
            "card is, not that it's safe to play: play when you know its color AND number and that's the one",
            "needed next (your hand says \"needed next: play it\"). Otherwise hint, or let go of a card nobody needs.",
            "Card places shift after a play or a let-go: read your hand again before each move.",
            "Lighting 10 of 20 is a win. Don't tell anyone their cards in chat: that's what hints are for.",
            f"move: POST {t}/move {{\"move\": \"hint Whomever red\"}}; state lists every legal move.",
            f"leave the game: POST {t}/resign; chat: POST {t}/say {{\"text\": \"...\"}}",
        ])
