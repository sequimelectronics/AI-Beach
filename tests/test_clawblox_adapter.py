"""Unit tests for adapters/clawblox on recorded raw observations (no server needed).

Run: python3 -m unittest discover -s tests   (or: python3 -m pytest tests)
"""

from __future__ import annotations

import copy
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from adapters.clawblox import ClawbloxAdapter, approx_counter  # noqa: E402
from adapters.clawblox.compact import (  # noqa: E402
    compact_view, map_card_text, players_in_radius, summarize_rest, view_json, view_text,
)
from adapters.clawblox.world import (  # noqa: E402
    compass, direction_to, fmt_vec, held_object, parse_observation, r1, resting_on, standing_on,
)

FIX = ROOT / "tests" / "fixtures" / "clawblox"


def load(name: str) -> dict:
    return json.loads((FIX / name).read_text())


def snap(name: str):
    return parse_observation(load(name))


class FakeTransport:
    """Replays canned responses. `observe` is a list of raw observations
    returned in turn (the last one repeats); `on_input(body)` builds the
    /input response."""

    def __init__(self, observe, on_input=None, chat=None):
        self.observe = list(observe)
        self.on_input = on_input
        self.chat = chat
        self.inputs: list[dict] = []

    def request(self, method, path, body=None, session=None):
        if path.startswith("/join"):
            return 200, json.dumps({"session": "s", "agent_id": "a"})
        if path == "/observe":
            raw = self.observe.pop(0) if len(self.observe) > 1 else self.observe[0]
            return 200, json.dumps(raw)
        if path == "/input":
            self.inputs.append(body)
            raw = self.on_input(body) if self.on_input else self.observe[0]
            return 200, json.dumps(raw)
        if path.startswith("/chat/messages"):
            return 200, json.dumps(self.chat or {"messages": []})
        if path == "/chat":
            return 200, json.dumps({"id": "local_999", "created_at": "x"})
        return 404, "not found"


def adapter_for(transport) -> ClawbloxAdapter:
    return ClawbloxAdapter(transport=transport, name="Alice", sleep=lambda s: None,
                           counter=approx_counter(), session="s")


def with_result(raw: dict, code: str, **player) -> dict:
    out = copy.deepcopy(raw)
    out["tick"] = raw["tick"] + 1
    out["player"]["attributes"]["LastActionResult"] = code
    out["player"].update(player)
    return out


class DirectionTests(unittest.TestCase):
    def test_compass_points(self):
        self.assertEqual(compass(0, 1), "N")
        self.assertEqual(compass(1, 0), "E")
        self.assertEqual(compass(0, -1), "S")
        self.assertEqual(compass(-1, 0), "W")
        self.assertEqual(compass(1, 1), "NE")
        self.assertEqual(compass(-1, -1), "SW")
        self.assertEqual(compass(0.3, 1), "N")  # 17 degrees still north
        self.assertEqual(compass(0, 0), "here")

    def test_direction_uses_x_east_z_north(self):
        self.assertEqual(direction_to((0, 0, 0), (-31.4, 3, 26.9)), "NW")

    def test_rounding(self):
        self.assertEqual(r1(-0.04), 0.0)
        self.assertEqual(str(r1(-0.04)), "0.0")
        self.assertEqual(fmt_vec((14.04, 0.37, -2.18)), "(14,0.4,-2.2)")


class MapCardTests(unittest.TestCase):
    def setUp(self):
        self.s = snap("spawn.json")
        self.card = map_card_text(self.s)

    def test_static_scenery_is_described(self):
        self.assertIn("invisible walls at x=-80/80, z=-80/80", self.card)
        self.assertIn("ocean", self.card)
        for name in ("SmallPlateau", "LargeMesa", "Spire", "Peak", "Ridge"):
            self.assertIn(name, self.card)
        self.assertIn("SmallPlateau: -30,28; 10*8; top 2", self.card)

    def test_landmarks(self):
        self.assertRegex(self.card, r"a pile of 12 blocks near 1[45]")
        self.assertIn("Rock_1 (rock) on SmallPlateau", self.card)
        self.assertIn("Ring_1 (ring)", self.card)


class CompactViewTests(unittest.TestCase):
    def test_static_scenery_omitted_and_near_list_capped(self):
        s = snap("spawn.json")
        v = compact_view(s, s.statics, {})
        text = view_text(v)
        for static in ("Ocean", "GroundCenter", "BoundaryNorth", "LargeMesa ", "HumanoidRootPart"):
            self.assertNotIn(static, text)
        self.assertEqual(len(v["near"]), 8)
        self.assertEqual(v["rest_count"], 6)
        self.assertIn("objects (nearest 8 of 14", text)

    def test_rows_sorted_with_distance_and_direction(self):
        s = snap("at_pile.json")
        v = compact_view(s, s.statics, {})
        dists = [r["dist"] for r in v["near"]]
        self.assertEqual(dists, sorted(dists))
        for r in v["near"]:
            self.assertIn(r["dir"], ("N", "NE", "E", "SE", "S", "SW", "W", "NW", "here"))

    def test_summary_names_single_landmarks_with_position(self):
        s = snap("spawn.json")
        v = compact_view(s, s.statics, {})
        self.assertRegex(v["rest"], r"Rock_1 rock \(-31\.4,3(\.\d)?,26\.9\) on SmallPlateau [\d.]+ NW")
        self.assertRegex(v["rest"], r"Ring_1 ring \(40,0\.3,-42\) [\d.]+ SE")

    def test_summarize_groups_by_direction(self):
        rows = [{"name": f"B{i}", "kind": "block", "dist": d, "dir": "N", "on": None, "pos": [0, 0, 0]}
                for i, d in enumerate((15.2, 18.9, 29.6))]
        rows.append({"name": "B9", "kind": "block", "dist": 40.0, "dir": "E", "on": None, "pos": [0, 0, 0]})
        self.assertEqual(summarize_rest(rows), "4 blocks (3 N 15-30, 1 E 40)")

    def test_text_and_json_carry_the_same_names(self):
        s = snap("after_rock_throw.json")
        v = compact_view(s, s.statics, {})
        t, j = view_text(v), view_json(v)
        for r in v["near"]:
            self.assertIn(r["name"], t)
            self.assertIn(r["name"], j)

    def test_after_rock_throw_counts_new_blocks(self):
        s = snap("after_rock_throw.json")
        names = {e.name for e in s.objects}
        self.assertTrue(any(n.startswith("ImpactBlock_") for n in names))
        self.assertGreater(len(s.objects), 14)


class HeldStateTests(unittest.TestCase):
    def test_held_block_inferred_and_hidden_from_object_list(self):
        s = snap("holding_block.json")
        held = held_object(s)
        self.assertIsNotNone(held)
        v = compact_view(s, s.statics, {})
        self.assertEqual(v["holding"], held.name)
        self.assertNotIn(held.name, [r["name"] for r in v["near"]])
        self.assertIn(f"holding {held.name}", view_text(v))

    def test_hands_empty_when_nothing_overhead(self):
        for name in ("spawn.json", "at_pile.json"):
            self.assertIsNone(held_object(snap(name)), name)
            self.assertIn("hands empty", view_text(compact_view(snap(name), [], {})))


class PlatformTests(unittest.TestCase):
    def test_standing_on_plateau(self):
        s = snap("on_plateau.json")
        on = standing_on(s, s.statics)
        self.assertIsNotNone(on)
        self.assertEqual(on.name, "SmallPlateau")

    def test_rock_rests_on_plateau_at_start(self):
        s = snap("spawn.json")
        rock = next(e for e in s.objects if e.kind == "rock")
        self.assertEqual(resting_on(rock, s.statics).name, "SmallPlateau")


class PlayerTests(unittest.TestCase):
    def test_player_in_view_is_named(self):
        s = snap("two_players_in_view.json")
        players = players_in_radius(s, {})
        self.assertEqual([(p.name, p.in_view) for p in players], [("Bob", True)])

    def test_player_behind_is_still_listed(self):
        names: dict[int, str] = {}
        players_in_radius(snap("two_players_in_view.json"), names)  # learn Bob's entity id
        s = snap("two_players_behind.json")
        self.assertEqual(s.named_players, [])  # the server's list is empty here
        players = players_in_radius(s, names)
        self.assertEqual([(p.name, p.in_view) for p in players], [("Bob", False)])
        self.assertIn("Bob 11.7 W (not in view)", view_text(compact_view(s, s.statics, names)))

    def test_never_seen_player_is_unknown(self):
        players = players_in_radius(snap("two_players_behind.json"), {})
        self.assertEqual([p.name for p in players], ["unknown player"])

    def test_self_is_not_listed(self):
        self.assertEqual(players_in_radius(snap("spawn.json"), {}), [])


class ChatTests(unittest.TestCase):
    def test_hear_dedupes_by_id_and_keeps_same_second_messages(self):
        chat = load("chat_messages.json")
        a = adapter_for(FakeTransport([load("spawn.json")], chat=chat))
        first = a.hear().splitlines()
        self.assertEqual(len(first), 6)  # all six share one created_at second
        self.assertEqual(first[0], "Alice: alice message 0")
        self.assertEqual(first[1], "Bob: bob message 0")
        self.assertEqual(a.hear(), "(no new chat)")

    def test_hear_orders_by_numeric_id(self):
        chat = load("chat_messages.json")
        chat["messages"] = list(reversed(chat["messages"]))
        a = adapter_for(FakeTransport([load("spawn.json")], chat=chat))
        self.assertTrue(a.hear().startswith("Alice: alice message 0"))

    def test_say_validates_length(self):
        a = adapter_for(FakeTransport([load("spawn.json")]))
        self.assertIn("limit is 500", a.say("x" * 501))
        self.assertEqual(a.say("hi"), "said: hi")
        self.assertEqual(a.hear(), "(no new chat)")


class ActTests(unittest.TestCase):
    def test_pickup_success_reports_held_object(self):
        holding = load("holding_block.json")
        held = held_object(parse_observation(holding)).name
        t = FakeTransport([load("at_pile.json")],
                          on_input=lambda b: with_result(holding, "PickupSuccess"))
        res = adapter_for(t).act("Pickup", {"position": [15.2, 0.4, -1.2]})
        self.assertEqual(res, f"Picked up {held} (now holding it)")

    def test_pickup_out_of_range_gives_distance_and_reach(self):
        raw = load("spawn.json")
        rock = next(e for e in parse_observation(raw).objects if e.kind == "rock")
        t = FakeTransport([raw], on_input=lambda b: with_result(raw, "PickupFailed:OutOfRange"))
        res = adapter_for(t).act("Pickup", {"position": list(rock.pos)})
        self.assertRegex(res, r"^Pickup failed: Rock_1 is 41(\.\d)? away, reach is 6 - move closer$")

    def test_pickup_no_block_names_the_nearest(self):
        raw = load("at_pile.json")
        t = FakeTransport([raw], on_input=lambda b: with_result(raw, "PickupFailed:NoBlock"))
        res = adapter_for(t).act("Pickup", {"position": [11, 0.4, 3]})
        self.assertRegex(res, r"nothing within 1\.5 of \(11,0\.4,3\); nearest is \w+ at ")

    def test_already_holding(self):
        raw = load("holding_block.json")
        held = held_object(parse_observation(raw)).name
        t = FakeTransport([raw], on_input=lambda b: with_result(raw, "PickupFailed:AlreadyHolding"))
        res = adapter_for(t).act("Pickup", {"position": [15, 0.4, -1]})
        self.assertEqual(res, f"Pickup failed: already holding {held} - Place or Throw it first")

    def test_sticky_last_action_result_is_not_misread(self):
        # LastActionResult still says PickupSuccess from an older action; MoveTo
        # must report arrival from positions, not that string.
        raw = with_result(load("at_pile.json"), "PickupSuccess")
        me = raw["player"]["position"]
        t = FakeTransport([raw], on_input=lambda b: raw)
        res = adapter_for(t).act("MoveTo", {"position": me})
        self.assertTrue(res.startswith("MoveTo: arrived at"), res)
        self.assertNotIn("Pickup", res)

    def test_result_without_matching_code_is_flagged(self):
        raw = with_result(load("at_pile.json"), "PlaceSuccess")
        t = FakeTransport([raw], on_input=lambda b: raw)
        res = adapter_for(t).act("Pickup", {"position": [15, 0.4, -1]})
        self.assertIn("reported no result", res)

    def test_moveto_stuck_at_ledge_suggests_jump(self):
        raw = load("spawn.json")
        raw["player"]["position"] = [-23.95, 2.55, 26.9]
        t = FakeTransport([raw], on_input=lambda b: raw)
        res = adapter_for(t).act("MoveTo", {"position": [-31, 3, 27]})
        self.assertIn("stuck at a ledge 2 high (SmallPlateau, top 2)", res)
        self.assertIn('"jump": true', res)

    def test_moveto_blocked_by_invisible_wall(self):
        raw = load("spawn.json")
        raw["player"]["position"] = [78.9, 2.55, 0]
        t = FakeTransport([raw], on_input=lambda b: raw)
        res = adapter_for(t).act("MoveTo", {"position": [95, 2, 0]})
        self.assertIn("invisible wall", res)

    def test_place_failures(self):
        raw = load("holding_block.json")
        a_raw = copy.deepcopy(raw)
        for code, expect in (("PlaceFailed:Occupied", "y = surface top + 0.6"),
                             ("PlaceFailed:OutOfRange", "reach is 7"),
                             ("PlaceFailed:EmptyHands", "not holding anything")):
            t = FakeTransport([a_raw], on_input=lambda b, c=code: with_result(raw, c))
            self.assertIn(expect, adapter_for(t).act("Place", {"position": [20, 0.6, 0]}))

    def test_throw_speed_cap_is_reported(self):
        raw = load("holding_block.json")
        t = FakeTransport([raw], on_input=lambda b: with_result(raw, "ThrowSuccess"))
        res = adapter_for(t).act("Throw", {"direction": [1, 0, 0], "speed": 25})
        self.assertIn("speed is capped at 10", res)
        self.assertEqual(t.inputs[-1]["type"], "Throw")

    def test_validation_happens_before_sending(self):
        t = FakeTransport([load("spawn.json")])
        a = adapter_for(t)
        self.assertIn("rejected", a.act("MoveTo", {"position": [1, "x", 3]}))
        self.assertIn("rejected", a.act("Throw", {"direction": [0, 0, 0]}))
        self.assertIn("unknown action", a.act("Fly", {}))
        self.assertEqual(t.inputs, [])

    def test_history_is_one_line_per_action(self):
        t = FakeTransport([load("spawn.json")])
        a = adapter_for(t)
        a.act("Fly", {})
        a.act("MoveTo", {"position": [1, "x", 3]})
        lines = a.history().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0].startswith("Fly -> unknown action"))


class TurnBundleTests(unittest.TestCase):
    def test_three_pieces_with_sizes_and_map_only_first(self):
        a = adapter_for(FakeTransport([load("spawn.json")], chat=load("chat_messages.json")))
        b1 = a.turn_bundle()
        self.assertEqual(set(b1) - {"total_tokens", "token_method"}, {"tools", "state", "recent"})
        for k in ("tools", "state", "recent"):
            self.assertGreater(b1[k]["tokens"], 0)
        self.assertEqual(b1["total_tokens"], sum(b1[k]["tokens"] for k in ("tools", "state", "recent")))
        self.assertIn("MAP (", b1["state"]["text"])
        self.assertIn("RECENT CHAT", b1["recent"]["text"])
        b2 = a.turn_bundle()
        self.assertNotIn("MAP (", b2["state"]["text"])
        self.assertIn("NOW\nyou ", b2["state"]["text"])

    def test_bundle_stays_small_on_the_largest_fixture(self):
        a = adapter_for(FakeTransport([load("after_rock_throw.json")], chat=load("chat_messages.json")))
        b = a.turn_bundle()
        self.assertLess(b["total_tokens"], 8000)

    def test_play_card_and_tools_text(self):
        a = adapter_for(FakeTransport([load("spawn.json")]))
        tools = a.tools_text()
        self.assertIn("PLAY CARD", tools)
        self.assertIn('"name":"act"', tools)
        for fact in ("within 6", "within 7", "within 1.5", "capped at 10", '"jump": true', "rock"):
            self.assertIn(fact, tools)


class RepoHygieneTests(unittest.TestCase):
    def test_fixtures_hold_no_session_tokens(self):
        for f in FIX.glob("*.json"):
            self.assertNotRegex(f.read_text(), r'"(session|token)"\s*:', f.name)


if __name__ == "__main__":
    unittest.main()
