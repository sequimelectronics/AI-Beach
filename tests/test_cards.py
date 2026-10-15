"""Card games at the Boardwalk: Crazy Eights and Go Fish rules, hidden hands, and scripted games.

The rules tests drive the games directly. The table tests go through the Beach (and its HTTP API)
the way players do, and check that nobody's hand ever reaches anyone else: not another player,
not a watcher, not table chat, SandChat or the move history, and not another participant's token.
"""

from __future__ import annotations

import json
import random
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from beach.agent import table_bundle, zone_card  # noqa: E402
from beach.core import BOARDWALK, SANDCHAT, Beach, BeachError  # noqa: E402
from beach.games import GAMES, IllegalMove  # noqa: E402
from beach.games.cards import deck, parse_card, parse_rank  # noqa: E402
from beach.games.crazy8 import CrazyEights  # noqa: E402
from beach.games.gofish import GoFish  # noqa: E402

try:
    from fastapi.testclient import TestClient
    HAVE_FASTAPI = True
except ImportError:  # pragma: no cover
    HAVE_FASTAPI = False

C8, GF = CrazyEights(), GoFish()
CARD_RE = re.compile(r"\b(?:10|[2-9AJQK])[SHDC]\b")


def c8(hands, pile, stock=(), suit=None, turn=0, names=("Sandy", "Pebble", "Coral")):
    n = len(hands)
    return {"players": n, "hands": [list(h) for h in hands], "stock": list(stock), "pile": list(pile),
            "suit": suit or pile[-1][-1], "turn": turn, "drawn": None, "ply": 0, "seed": 7, "shuffles": 0,
            "out": [], "passes": 0, "over": None, "names": list(names[:n])}


def gf(hands, stock=(), books=None, turn=0, names=("Sandy", "Pebble", "Coral")):
    n = len(hands)
    return {"players": n, "hands": [list(h) for h in hands], "stock": list(stock),
            "books": books or [[] for _ in range(n)], "turn": turn, "ply": 0, "seed": 7, "shuffles": 0,
            "out": [], "over": None, "names": list(names[:n])}


def cards_in(text: str) -> set[str]:
    """The cards named in some text, leaving out the game cards' own examples ("play 7H")."""
    for gid in ("crazy8", "gofish"):
        for tid in range(1, 20):
            for line in GAMES[gid].card(tid).splitlines():
                text = text.replace(json.dumps(line)[1:-1], "").replace(line, "")
    return set(CARD_RE.findall(text))


class NotationTests(unittest.TestCase):
    def test_deck_and_parsing(self):
        d = deck()
        self.assertEqual(len(d), 52)
        self.assertEqual(len(set(d)), 52)
        self.assertEqual([parse_card(x) for x in ("7h", "10 d", "qs", "1d", "11h", "zz")],
                         ["7H", "10D", "QS", None, None, None])
        self.assertEqual([parse_rank(x) for x in ("7s", "7", "Aces", "queens", "10s", "jack", "1s")],
                         ["7", "7", "A", "Q", "10", "J", None])

    def test_registered_with_cards_short_enough(self):
        from beach.agent import make_counter
        count = make_counter()
        for gid in ("crazy8", "gofish"):
            self.assertIn(gid, GAMES)
            self.assertLessEqual(count(GAMES[gid].card(12)), 250, gid)


class CrazyEightsRules(unittest.TestCase):
    def test_deal(self):
        for n, per in ((2, 7), (3, 5), (5, 5)):
            s = C8.new({"players": n, "seed": n})
            self.assertEqual([len(h) for h in s["hands"]], [per] * n)
            self.assertEqual(len(s["stock"]) + len(s["pile"]) + n * per, 52)
            self.assertNotEqual(s["pile"][-1][:-1], "8")       # never starts on an eight
        self.assertEqual(C8.new({"players": 9})["players"], 5)
        self.assertEqual(C8.new({"players": 1})["players"], 2)

    def test_match_suit_or_rank_eights_wild(self):
        s = c8([["7H", "9S", "8C", "KD"], ["2S"], ["3S"]], ["7S"])
        legal = C8.legal_moves(s)
        self.assertIn("play 7H", legal)                          # rank
        self.assertIn("play 9S", legal)                          # suit
        self.assertNotIn("play KD", legal)
        self.assertEqual([m for m in legal if m.startswith("play 8C")],
                         ["play 8C name spades", "play 8C name hearts", "play 8C name diamonds",
                          "play 8C name clubs"])
        self.assertNotIn("draw", legal)                           # can play, so can't draw

    def test_eight_names_the_suit(self):
        s = c8([["8C", "KD"], ["2D", "2S"], ["3S"]], ["7S"])
        s, info = C8.play(s, "play 8c hearts")
        self.assertEqual((s["suit"], s["turn"], info["move"]), ("H", 1, "play 8C name hearts"))
        self.assertEqual(info["text"], "Sandy played 8C and named hearts (one card left)")
        self.assertEqual(C8.legal_moves(s), ["draw"])            # Pebble has no heart and no eight
        with self.assertRaises(IllegalMove) as e:
            C8.play(c8([["8C", "KD"], ["2D"], ["3S"]], ["7S"]), "play 8C")
        self.assertIn("name the next suit", e.exception.reason)

    def test_illegal_plays_say_why(self):
        s = c8([["7H", "KD"], ["2S"], ["3S"]], ["7S"], stock=["4C"])
        for move, why in (("play KD", "doesn't match"), ("play QS", "isn't in your hand"),
                          ("draw", "can't draw"), ("pass", "only pass"), ("hello", "write a move")):
            with self.assertRaises(IllegalMove) as e:
                C8.play(s, move)
            self.assertIn(why, e.exception.reason, move)

    def test_draw_then_play_it_or_pass(self):
        s = c8([["KD", "2C"], ["2S"], ["3S"]], ["7S"], stock=["4C", "9S"])
        s, info = C8.play(s, "draw")
        self.assertEqual((info["move"], info["private"], s["turn"]), ("draw", {"drew": "9S"}, 0))
        self.assertNotIn("9S", json.dumps({k: v for k, v in info.items() if k != "private"}))
        self.assertEqual(C8.legal_moves(s), ["play 9S", "pass"])
        with self.assertRaises(IllegalMove):
            C8.play(s, "draw")
        s2, _ = C8.play(s, "pass")
        self.assertEqual((s2["turn"], s2["drawn"], len(s2["hands"][0])), (1, None, 3))
        s3, _ = C8.play(s, "play 9s")
        self.assertEqual((s3["pile"][-1], s3["turn"]), ("9S", 1))

    def test_unplayable_draw_only_pass(self):
        s = c8([["KD"], ["2S"], ["3S"]], ["7S"], stock=["4C"])
        s, _ = C8.play(s, "draw")
        self.assertEqual(C8.legal_moves(s), ["pass"])

    def test_empty_stock_reshuffles_the_pile(self):
        s = c8([["KD"], ["2S"], ["3S"]], ["4C", "5C", "6H", "7S"])
        s, info = C8.play(s, "draw")
        self.assertTrue(info["reshuffled"])
        self.assertEqual(s["pile"], ["7S"])
        self.assertEqual(len(s["stock"]) + len(s["hands"][0]), 4)

    def test_blocked_game_fewest_cards_wins(self):
        s = c8([["KD", "QD"], ["2D"], ["3D", "4D"]], ["7S"])
        self.assertEqual(C8.legal_moves(s), ["pass"])
        for _ in range(3):
            s, _ = C8.play(s, "pass")
        self.assertEqual(C8.outcome(s)["winner"], 1)
        self.assertEqual(C8.outcome(s)["reason"], "blocked: nobody could play or draw; fewest cards wins")

    def test_first_to_empty_their_hand_wins(self):
        s = c8([["7H"], ["2S"], ["3S"]], ["7S"])
        s, _ = C8.play(s, "play 7H")
        self.assertEqual(C8.outcome(s), {"winner": 0, "winners": [0], "reason": "first to empty their hand"})
        self.assertIsNone(C8.to_move(s))
        self.assertEqual(C8.legal_moves(s), [])

    def test_resign_drops_a_player_and_the_rest_play_on(self):
        s = c8([["7H", "2D"], ["2S", "3C"], ["3S"]], ["7S"], stock=["4C"])
        s, out = C8.resign(s, 0)
        self.assertIsNone(out)
        self.assertEqual((s["out"], s["turn"], s["hands"][0]), ([0], 1, []))
        self.assertEqual(s["stock"][:2], ["7H", "2D"])            # their cards go under the stock
        s, _ = C8.play(s, "play 2S")
        self.assertEqual(s["turn"], 2)                            # seat 0 is skipped from now on
        s, _ = C8.play(s, "play 3S")
        self.assertEqual(C8.outcome(s)["winner"], 2)
        s = c8([["7H"], ["2S"]], ["7S"], names=("Sandy", "Pebble"))
        s, out = C8.resign(s, 1)
        self.assertEqual(out["winner"], 0)

    def test_text_and_view_show_only_your_hand(self):
        s = c8([["7H", "KD"], ["2S", "QC"], ["3S"]], ["7S"], stock=["4C", "9D"])
        mine = C8.text(s, 0)
        self.assertIn("your hand: 7H KD", mine)
        self.assertIn("hands: Sandy (you) 2 cards, Pebble 2 cards, Coral 1 card", mine)
        self.assertEqual(cards_in(mine), {"7H", "KD", "7S"})
        self.assertEqual(cards_in(C8.text(s, None)), {"7S"})
        v = C8.view(s, 1)
        self.assertEqual((v["hand"], v["counts"]), (["2S", "QC"], [2, 2, 1]))
        self.assertIsNone(C8.view(s, None)["hand"])
        self.assertEqual(cards_in(json.dumps(C8.view(s, None))), {"7S"})


class GoFishRules(unittest.TestCase):
    def test_deal(self):
        for n, per in ((2, 7), (3, 7), (4, 5), (5, 5)):
            s = GF.new({"players": n, "seed": 3})
            total = sum(len(h) for h in s["hands"]) + 4 * sum(len(b) for b in s["books"])
            self.assertEqual(total, n * per)
            self.assertEqual(len(s["stock"]), 52 - n * per)

    def test_legal_asks_name_players_and_held_ranks(self):
        s = gf([["7H", "7S", "KD"], ["2S"], ["3S"]], stock=["4C"])
        self.assertEqual(GF.legal_moves(s), ["ask Pebble 7s", "ask Pebble Ks", "ask Coral 7s", "ask Coral Ks"])

    def test_got_them_and_go_again_with_a_book(self):
        s = gf([["7H", "7S", "KD"], ["7D", "7C", "2S"], ["3S"]], stock=["4C"])
        s, info = GF.play(s, "Ask pebble for 7s")
        self.assertEqual(info["move"], "ask Pebble 7s")
        self.assertEqual(info["text"], "Sandy asked Pebble for 7s and got two; a book of 7s for Sandy")
        self.assertEqual((s["books"][0], s["hands"][0], s["hands"][1], s["turn"]), (["7"], ["KD"], ["2S"], 0))

    def test_go_fish(self):
        s = gf([["7H", "KD"], ["2S"], ["3S"]], stock=["4C", "QH"])
        s, info = GF.play(s, "ask Coral 7s")
        self.assertEqual(info["text"], "Sandy asked Coral for 7s: go fish!")
        self.assertEqual(info["private"], {"drew": "QH"})
        self.assertNotIn("QH", info["text"])
        self.assertEqual((s["turn"], len(s["hands"][0])), (1, 3))

    def test_fishing_the_rank_you_asked_for_goes_again(self):
        s = gf([["7H", "KD"], ["2S"], ["3S"]], stock=["4C", "7C"])
        s, info = GF.play(s, "ask coral sevens")
        self.assertEqual(info["fished"], "7")
        self.assertIn("fished a 7 and goes again", info["text"])
        self.assertEqual(s["turn"], 0)

    def test_illegal_asks_say_why(self):
        s = gf([["7H", "KD"], ["2S"], []], stock=["4C"])
        for move, why in (("ask Pebble 9s", "you have no 9s"), ("ask Sandy 7s", "yourself"),
                          ("ask Coral 7s", "has no cards"), ("ask Kelp 7s", "nobody here is called Kelp"),
                          ("draw", "only draw"), ("fish", "write a move")):
            with self.assertRaises(IllegalMove) as e:
                GF.play(s, move)
            self.assertIn(why, e.exception.reason, move)

    def test_empty_hand_draws_first(self):
        s = gf([[], ["2S"], ["3S"]], stock=["4C", "9D"])
        self.assertEqual(GF.legal_moves(s), ["draw"])
        s, info = GF.play(s, "draw")
        self.assertEqual((info["private"], s["turn"]), ({"drew": "9D"}, 0))
        self.assertEqual(GF.legal_moves(s), ["ask Pebble 9s", "ask Coral 9s"])

    def test_empty_hand_and_stock_sits_out(self):
        s = gf([["2H"], ["2S", "2D", "2C"], ["3S"]], turn=0, books=[["K"], [], []])
        s, info = GF.play(s, "ask Coral 2s")             # go fish with an empty stock
        self.assertEqual(s["turn"], 1)
        s, info = GF.play(s, "ask Sandy 2s")
        self.assertEqual(s["books"][1], ["2"])
        self.assertEqual(s["hands"][0], [])
        self.assertEqual(s["turn"], 2)                   # Pebble's hand is empty too: on to Coral, then Coral again
        self.assertEqual(GF.legal_moves(s), [])
        # (Only possible in a hand-made position: in a real game the other 3s are somewhere.)

    def test_most_books_wins_and_ties_share(self):
        ranks = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q"]
        s = gf([["KH", "KS"], ["KD", "KC"], []], books=[ranks[:6], ranks[6:], []])
        s, info = GF.play(s, "ask Pebble Ks")
        self.assertEqual(GF.outcome(s), {"winner": 0, "winners": [0], "reason": "most books: 7"})
        s = gf([["KH", "KS"], ["KD", "KC"], []], books=[ranks[:5], ranks[5:11], ["Q"]])
        s, _ = GF.play(s, "ask Pebble Ks")
        self.assertEqual(GF.outcome(s), {"winner": None, "winners": [0, 1], "reason": "tied on 6 books"})

    def test_text_shows_only_your_hand(self):
        s = gf([["7H", "KD"], ["2S", "QC"], ["3S"]], stock=["4C", "9D"], books=[["5"], [], []])
        self.assertEqual(cards_in(GF.text(s, 0)), {"7H", "KD"})
        self.assertIn("books: Sandy 5s; Pebble none; Coral none", GF.text(s, 0))
        self.assertEqual(cards_in(GF.text(s, None)), set())
        self.assertEqual(cards_in(json.dumps(GF.view(s, None))), set())
        self.assertIsNone(GF.view(s, None)["hand"])


class FakeClock:
    def __init__(self, t: float = 1_800_000_000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, s: float) -> None:
        self.t += s


class CardTableCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="cards-")
        self.clock = FakeClock()
        self.beach = Beach(self.dir, clock=self.clock, rng=random.Random(5))
        self.beach.ensure_admin()
        self.p = {}
        for name, kind in (("Sandy", "agent"), ("Pebble", "agent"), ("Coral", "person"), ("Drift", "person")):
            self.p[name], _ = self.beach.add_participant(name, kind)
        self.bw = self.beach.tables
        self.hook = []
        self.beach.sender = lambda payload: self.hook.append(payload) or True

    def tearDown(self):
        self.beach.db.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def table(self, game="crazy8", players=("Sandy", "Pebble", "Coral"), seed=811_000_011) -> int:
        tid = self.bw.open(self.p[players[0]].id, BOARDWALK, game, options={"players": len(players), "seed": seed})["id"]
        for name in players[1:]:
            self.bw.sit(self.p[name].id, tid)
        return tid

    def raw(self, tid):
        return json.loads(self.bw.table(tid)["state"])


class CardTableTests(CardTableCase):
    def test_three_seats_start_and_names_in_turn_order(self):
        tid = self.bw.open(self.p["Sandy"].id, BOARDWALK, "crazy8", options={"players": 3})["id"]
        self.bw.sit(self.p["Pebble"].id, tid)
        self.assertEqual(self.bw.view(self.p["Pebble"].id, tid)["status"], "waiting")
        v = self.bw.sit(self.p["Coral"].id, tid)
        self.assertEqual((v["status"], len(v["seats"]), v["draws"]), ("playing", 3, False))
        with self.assertRaises(BeachError):
            self.bw.sit(self.p["Drift"].id, tid)
        text = table_bundle(self.beach, self.p["Pebble"].id, tid)["state"]["text"]
        self.assertIn("players in turn order: Sandy, Pebble (you), Coral", text)
        notes = [m["text"] for m in self.bw.chat(self.p["Sandy"].id, tid)]
        self.assertIn("Pebble sat down (2 of 3)", notes)

    def test_no_draw_offers_in_card_games(self):
        tid = self.table(players=("Sandy", "Pebble"))
        with self.assertRaises(BeachError) as e:
            self.bw.draw(self.p["Sandy"].id, tid, "offer")
        self.assertIn("no draw offers", str(e.exception))

    def test_illegal_play_gives_one_line_reason_and_the_list(self):
        tid = self.table()
        with self.assertRaises(BeachError) as e:
            self.bw.move(self.p["Sandy"].id, tid, "play 2Z")
        self.assertEqual(e.exception.data["legal"], self.bw.view(self.p["Sandy"].id, tid)["legal"])
        self.assertNotIn("\n", e.exception.data["reason"])

    def test_resign_in_a_three_player_game_plays_on(self):
        tid = self.table()
        self.bw.resign(self.p["Pebble"].id, tid)
        v = self.bw.view(self.p["Sandy"].id, tid)
        self.assertEqual((v["status"], v["position"]["out"]), ("playing", [1]))
        self.assertIn("Pebble left the game; the others play on", [m["text"] for m in self.bw.chat(self.p["Sandy"].id, tid)])
        self.bw.resign(self.p["Coral"].id, tid)
        v = self.bw.view(self.p["Sandy"].id, tid)
        self.assertEqual((v["status"], v["result_text"]), ("finished", "Sandy won (Coral resigned)"))
        self.assertIn("Sandy, Pebble and Coral finished a game of crazy eights on The Boardwalk: "
                      "Sandy won (Coral resigned).",
                      [r["text"] for r in self.beach.db.q("SELECT text FROM messages WHERE zone_id = ?", (SANDCHAT,))])

    def test_rename_mid_game_and_asks_still_work(self):
        tid = self.table("gofish")
        self.beach.rename(self.p["Pebble"].id, "Kelp")
        legal = self.bw.view(self.p["Sandy"].id, tid)["legal"]
        self.assertTrue(legal and all(m.startswith(("ask Kelp", "ask Coral")) for m in legal), legal)
        self.bw.move(self.p["Sandy"].id, tid, legal[0])

    def test_one_your_move_notice_per_turn_and_abandon(self):
        tid = self.table()
        self.bw.move(self.p["Sandy"].id, tid, self.bw.view(self.p["Sandy"].id, tid)["legal"][0])
        self.beach.part(self.p["Pebble"].id, BOARDWALK)
        for _ in range(3):
            self.clock.advance(self.beach.setting("turn_notify_after_s") + 1)
            self.beach.tick()
        mine = [h for h in self.hook if h["invitee"] == "Pebble"]
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0]["game"], "crazy eights")
        self.clock.advance(self.beach.setting("table_abandon_s") + 1)
        self.beach.tick()
        self.assertEqual(self.bw.view(self.p["Sandy"].id, tid)["status"], "abandoned")


class HiddenHandTests(CardTableCase):
    """Nobody's hand reaches anyone else, by any route."""

    def others_cards(self, tid, seat) -> set[str]:
        st = self.raw(tid)
        public = set(st.get("pile", []))
        for h in self.bw.history(tid):
            public |= cards_in(h["info"].get("text", "")) | {h["info"].get("card")} - {None}
        hidden = set(st["stock"])
        for s, hand in enumerate(st["hands"]):
            if s != seat:
                hidden |= set(hand)
        return hidden - public

    def everything_visible_to(self, pid, tid) -> str:
        """Every way this participant can read the table: the view, the agent bundle, table chat,
        SandChat, their private events, and the tables list."""
        seen = [json.dumps(self.bw.view(pid, tid)),
                json.dumps(table_bundle(self.beach, pid, tid, consume_notes=False)),
                json.dumps(self.bw.chat(pid, tid)),
                json.dumps(self.bw.list(BOARDWALK)),
                zone_card(self.beach, BOARDWALK)]
        if self.beach._visit(pid, SANDCHAT):
            seen.append(json.dumps(self.beach.read(pid, SANDCHAT)))
        seen.append(json.dumps(self.beach.inbox(pid, consume=False)))
        return "\n".join(seen)

    def check_no_leak(self, tid):
        st = self.raw(tid)
        names = ["Sandy", "Pebble", "Coral"]
        for seat, name in enumerate(names):
            seen = self.everything_visible_to(self.p[name].id, tid)
            leaked = cards_in(seen) & self.others_cards(tid, seat)
            self.assertEqual(leaked, set(), f"{name} can see {leaked}")
            self.assertNotIn(str(st["seed"]), seen)
            self.assertTrue(set(st["hands"][seat]) <= cards_in(seen) or seat in st["out"])
        watcher = self.p["Drift"].id
        self.bw.watch(watcher, tid)
        seen = self.everything_visible_to(watcher, tid)
        all_hidden = set(st["stock"]).union(*map(set, st["hands"]))
        public = set(st.get("pile", []))
        for h in self.bw.history(tid):
            public |= cards_in(h["info"].get("text", ""))
        self.assertEqual(cards_in(seen) & (all_hidden - public), set())
        self.assertIsNone(self.bw.view(watcher, tid)["position"]["hand"])

    def test_crazy_eights_hands_stay_hidden_all_game(self):
        tid = self.table(seed=921_000_021)
        names = {0: "Sandy", 1: "Pebble", 2: "Coral"}
        self.beach.join(self.p["Pebble"].id, SANDCHAT)
        self.bw.say(self.p["Coral"].id, tid, "good luck")
        for _ in range(200):
            v = self.bw.view(self.p["Sandy"].id, tid)
            if v["status"] != "playing":
                break
            mover = names[v["to_move"]]
            legal = self.bw.view(self.p[mover].id, tid)["legal"]
            self.bw.move(self.p[mover].id, tid, legal[0])
            if v["position"]["ply"] % 7 == 0:
                self.check_no_leak(tid)
        self.assertEqual(self.bw.view(self.p["Sandy"].id, tid)["status"], "finished")
        self.check_no_leak(tid)

    def test_go_fish_hands_stay_hidden_all_game(self):
        tid = self.table("gofish", seed=704_000_004)
        names = {0: "Sandy", 1: "Pebble", 2: "Coral"}
        for i in range(400):
            v = self.bw.view(self.p["Sandy"].id, tid)
            if v["status"] != "playing":
                break
            mover = names[v["to_move"]]
            legal = self.bw.view(self.p[mover].id, tid)["legal"]
            self.bw.move(self.p[mover].id, tid, legal[i % len(legal)])
            if i % 9 == 0:
                self.check_no_leak(tid)
        self.assertEqual(self.bw.view(self.p["Sandy"].id, tid)["status"], "finished")
        self.check_no_leak(tid)

    def test_drawn_card_goes_only_to_the_drawer(self):
        tid = self.table(seed=921_000_021)
        st = self.raw(tid)
        # Find a position where the mover must draw: play until someone has to.
        names = {0: "Sandy", 1: "Pebble", 2: "Coral"}
        for _ in range(100):
            v = self.bw.view(self.p["Sandy"].id, tid)
            mover = names[v["to_move"]]
            legal = self.bw.view(self.p[mover].id, tid)["legal"]
            r = self.bw.move(self.p[mover].id, tid, legal[0])
            if r["moved"] == "draw":
                drew = r["private"]["drew"]
                st = self.raw(tid)
                self.assertIn(drew, st["hands"][st["turn"]])
                hist = self.bw.history(tid)[-1]
                self.assertNotIn(drew, json.dumps(hist))
                self.assertNotIn("private", hist["info"])
                for other in names.values():
                    if other != mover:
                        self.assertNotIn(drew, self.everything_visible_to(self.p[other].id, tid))
                return
        self.fail("nobody drew in 100 moves")


@unittest.skipUnless(HAVE_FASTAPI, "needs fastapi")
class CardApiTests(unittest.TestCase):
    """Through HTTP, with each participant's own token, and with another's."""

    def setUp(self):
        from beach.app import create_app
        self.dir = tempfile.mkdtemp(prefix="cards-api-")
        self.beach = Beach(self.dir, clock=FakeClock(), rng=random.Random(1))
        self.admin = {"Authorization": f"Bearer {self.beach.ensure_admin()}"}
        self.http = TestClient(create_app(self.beach, upkeep_interval=None))
        self.h = {}
        for name, kind in (("Sandy", "agent"), ("Pebble", "agent"), ("Coral", "person"), ("Drift", "person")):
            tok = self.http.post("/admin/participants", json={"name": name, "kind": kind},
                                 headers=self.admin).json()["token"]
            self.h[name] = {"Authorization": f"Bearer {tok}"}

    def tearDown(self):
        self.beach.db.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def open3(self, game="crazy8", body=None):
        r = self.http.post("/zones/boardwalk/tables", json={"game": game, "players": 3, **(body or {})},
                           headers=self.h["Sandy"])
        self.assertEqual(r.status_code, 200, r.text)
        tid = r.json()["id"]
        self.http.post(f"/tables/{tid}/sit", headers=self.h["Pebble"])
        self.assertEqual(self.http.post(f"/tables/{tid}/sit", headers=self.h["Coral"]).json()["status"], "playing")
        return tid

    def test_each_token_sees_only_its_own_hand(self):
        tid = self.open3()
        st = json.loads(self.beach.tables.table(tid)["state"])
        top = st["pile"][-1]
        for seat, name in enumerate(("Sandy", "Pebble", "Coral")):
            v = self.http.get(f"/tables/{tid}", headers=self.h[name]).json()
            b = self.http.get(f"/agent/turn?table={tid}", headers=self.h[name]).json()
            self.assertEqual(v["position"]["hand"], st["hands"][seat])
            seen = cards_in(json.dumps(v) + json.dumps(b))
            self.assertEqual(seen, set(st["hands"][seat]) | {top}, name)
        for name in ("Drift",):                                  # a watcher, and a stranger to the table
            self.http.post(f"/tables/{tid}/watch", headers=self.h[name])
            v = self.http.get(f"/tables/{tid}", headers=self.h[name]).json()
            b = self.http.get(f"/agent/turn?table={tid}", headers=self.h[name]).json()
            self.assertIsNone(v["position"]["hand"])
            self.assertEqual(v["position"]["counts"], [5, 5, 5])
            self.assertEqual(cards_in(json.dumps(v) + json.dumps(b)), {top})
        lst = self.http.get("/zones/boardwalk/tables", headers=self.h["Drift"]).json()
        self.assertEqual(cards_in(json.dumps(lst)), set())

    def test_another_players_token_cannot_move_or_see_for_them(self):
        tid = self.open3()
        sandy_legal = self.http.get(f"/tables/{tid}", headers=self.h["Sandy"]).json()["legal"]
        r = self.http.post(f"/tables/{tid}/move", json={"move": sandy_legal[0]}, headers=self.h["Pebble"])
        self.assertEqual(r.status_code, 409)
        self.assertEqual(cards_in(r.text), set())                  # the refusal doesn't echo Sandy's options
        self.assertEqual(self.http.get(f"/tables/{tid}", headers=self.h["Pebble"]).json()["legal"], [])

    def test_seed_and_options_from_outside_are_ignored(self):
        a = self.open3(body={"seed": 1})
        b = self.open3(body={"seed": 1})
        sa = json.loads(self.beach.tables.table(a)["state"])
        sb = json.loads(self.beach.tables.table(b)["state"])
        self.assertNotEqual(sa["hands"], sb["hands"])

    def test_illegal_play_over_http(self):
        tid = self.open3()
        r = self.http.post(f"/tables/{tid}/move", json={"move": "play QZ"}, headers=self.h["Sandy"])
        self.assertEqual(r.status_code, 400)
        self.assertIn("legal", r.json())
        self.assertEqual(len(r.json()["reason"].splitlines()), 1)

    def test_move_reply_carries_private_draw_only_to_the_drawer(self):
        tid = self.open3()
        names = ("Sandy", "Pebble", "Coral")
        for _ in range(150):
            v = self.http.get(f"/tables/{tid}", headers=self.h["Sandy"]).json()
            if v["status"] != "playing":
                break
            mover = names[v["to_move"]]
            legal = self.http.get(f"/tables/{tid}", headers=self.h[mover]).json()["legal"]
            r = self.http.post(f"/tables/{tid}/move", json={"move": legal[0]}, headers=self.h[mover]).json()
            if r["moved"] == "draw":
                card = r["private"]["drew"]
                for other in names:
                    if other != mover:
                        self.assertNotIn(card, self.http.get(f"/tables/{tid}", headers=self.h[other]).text)
                        self.assertNotIn(card, self.http.get(f"/tables/{tid}/chat", headers=self.h[other]).text)
                return
        self.fail("nobody drew")


@unittest.skipUnless(HAVE_FASTAPI, "needs fastapi")
class ScriptedGames(unittest.TestCase):
    """Three players, two agent-shaped (they read only their turn bundle) and one person-shaped
    (it reads only the browser's table view), play each game to the end, choosing among the moves
    they're shown."""

    def test_mixed_clients_play_to_the_end(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import cards_scripted
        d = tempfile.mkdtemp(prefix="cards-scripted-")
        try:
            beach, http, heads = cards_scripted.setup(d)
            for game in ("crazy8", "gofish"):
                for seed in (1, 2):
                    g = cards_scripted.play_game(http, heads, game, seed=seed)
                    self.assertEqual(g["status"], "finished", (game, seed, g["transcript"][-5:]))
                    self.assertTrue(g["result"])
            beach.db.close()
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
