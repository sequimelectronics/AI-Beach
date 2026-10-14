"""Unit tests for the adapter's beach support, on recorded beach observations.

Run: python3 -m unittest discover -s tests
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
sys.path.insert(0, str(ROOT / "tests"))

from adapters.clawblox import ClawbloxAdapter, approx_counter  # noqa: E402
from adapters.clawblox.compact import (  # noqa: E402
    beach_map_card_text, castle_text, compact_view, players_in_radius, view_json, view_text,
)
from adapters.clawblox.world import (  # noqa: E402
    BEACH_RULES, MESA_RULES, announcements, beach_layout, detect_rules, held_object, parse_observation,
)
from test_clawblox_adapter import FakeTransport, with_result  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "beach"
MESA = ROOT / "tests" / "fixtures" / "clawblox"


def load(name: str) -> dict:
    return json.loads((FIX / name).read_text())


def snap(name: str):
    return parse_observation(load(name))


def beach_adapter(transport) -> ClawbloxAdapter:
    return ClawbloxAdapter(transport=transport, name="Sandy", sleep=lambda s: None,
                           counter=approx_counter(), session="s")


class RulesTests(unittest.TestCase):
    def test_world_is_detected(self):
        self.assertIs(detect_rules(snap("spawn.json")), BEACH_RULES)
        self.assertIs(detect_rules(parse_observation(json.loads((MESA / "spawn.json").read_text()))), MESA_RULES)

    def test_beach_rules_carry_the_beach_numbers(self):
        self.assertIn("Kick", BEACH_RULES.actions)
        self.assertIn("Mold", BEACH_RULES.actions)
        self.assertNotIn("Kick", MESA_RULES.actions)
        self.assertEqual(BEACH_RULES.kick_reach, 3.0)
        self.assertEqual(BEACH_RULES.piece_shapes, ("block", "tower", "wall", "flag"))

    def test_adapter_picks_rules_and_play_card(self):
        a = beach_adapter(FakeTransport([load("spawn.json")]))
        tools = a.tools_text()
        self.assertEqual(a.rules.world, "beach")
        self.assertIn("PLAY CARD - Beach", tools)
        self.assertIn("Kick|Mold", tools)

    def test_play_card_size_budget(self):
        # Exact count with the Gemma 4 E4B tokenizer is 400 (see BEACH_WORLD_REPORT.md);
        # this guards against growth without needing the tokenizer here.
        text = (ROOT / "adapters" / "clawblox" / "beach" / "PLAY_CARD.md").read_text().strip()
        self.assertLess(len(text), 1350)


class SceneryTests(unittest.TestCase):
    def test_scenery_is_hidden_and_folders_are_not_objects(self):
        s = snap("spawn.json")
        self.assertEqual(s.statics, [])  # everything is tagged Static by the world
        names = {e.name for e in s.objects}
        self.assertEqual(names, {"SoccerBall", "Volleyball", "BeachBall"})
        self.assertIn("BeachMap", s.folders)

    def test_map_card_from_published_layout(self):
        s = snap("spawn.json")
        card = beach_map_card_text(s, beach_layout(s), BEACH_RULES)
        self.assertIn("east of x=14 is shallow water", card)
        self.assertIn("north goal line z=28 between posts x=-3..3", card)
        self.assertIn("1 at -9.5,-18; 2 at -9.5,-6; 3 at -9.5,6; 4 at -9.5,18", card)
        self.assertIn("spawn points", card)
        self.assertIn("soccer ball (0,0.6,0)", card)

    def test_ball_kinds_come_from_the_world(self):
        kinds = sorted(e.kind for e in snap("spawn.json").objects)
        self.assertEqual(kinds, ["beach ball", "soccer ball", "volleyball"])


class CastleTests(unittest.TestCase):
    def test_far_castles_are_one_line_each(self):
        s = snap("castles_far.json")
        v = compact_view(s, s.statics, {}, BEACH_RULES)
        text = view_text(v)
        self.assertNotRegex(text, r"Block_\d")  # pieces not listed from far away
        self.assertRegex(text, r"sandcastle in plot 1 \(-9\.5,0,-18\) [\d.]+ SW: 4 pieces, 3 high, with a flag, standing")
        self.assertRegex(text, r"sandcastle in plot 4 .*: 2 pieces, 2 high, standing, has fallen 1 time")
        # a loose piece outside every plot is still an object
        self.assertIn("Tower_5 tower piece", text)

    def test_pieces_listed_when_within_reach(self):
        s = snap("castle_near.json")
        v = compact_view(s, s.statics, {}, BEACH_RULES)
        text = view_text(v)
        for name in ("Block_1", "Block_2", "Block_3", "Flag_4"):
            self.assertRegex(text, rf"{name} \w+ piece .* in plot 1\n")
        self.assertIn("sandcastle in plot 1", text)

    def test_castle_line_is_much_smaller_than_its_pieces(self):
        s = snap("castle_near.json")
        v = compact_view(s, s.statics, {}, BEACH_RULES)
        line = castle_text(next(c for c in v["castles"] if c["plot"] == 1))
        pieces = [ln for ln in view_text(v).splitlines() if "in plot 1" in ln and "sandcastle" not in ln]
        self.assertEqual(len(pieces), 4)
        self.assertLess(len(line), len("\n".join(pieces)) / 2)

    def test_json_encoding_carries_castles(self):
        s = snap("castles_far.json")
        j = json.loads(view_json(compact_view(s, s.statics, {}, BEACH_RULES)))
        self.assertEqual([c[0] for c in j["castles"]], [1, 4])


class BallAndPlayerTests(unittest.TestCase):
    def test_ball_in_the_sea_is_marked(self):
        s = snap("ball_in_sea.json")
        text = view_text(compact_view(s, s.statics, {}, BEACH_RULES))
        self.assertRegex(text, r"Volleyball volleyball \(22\.5,0\.6,-10\) [\d.]+ E in the sea")

    def test_score_line(self):
        s = snap("spawn.json")
        self.assertIn("score: north 0, south 0", view_text(compact_view(s, s.statics, {}, BEACH_RULES)))

    def test_player_behind_is_named_from_the_world_label(self):
        s = snap("two_players_behind.json")
        self.assertEqual(s.named_players, [])  # the engine's view-cone list is empty
        players = players_in_radius(s, {})
        self.assertEqual([(p.name, p.in_view) for p in players], [("Pebble", False)])

    def test_held_piece(self):
        s = snap("holding_piece.json")
        self.assertEqual(held_object(s, BEACH_RULES).name, "Tower_5")


class AnnouncementTests(unittest.TestCase):
    def test_announcements_parsed(self):
        self.assertEqual(announcements(snap("castles_far.json")),
                         [(1, "The sandcastle in plot 4 fell down!")])

    def test_old_announcements_skipped_new_ones_heard_once(self):
        old = load("castles_far.json")
        new = copy.deepcopy(old)
        new["recent_events"].append({"id": 2, "tick": 9999, "server_time_ms": 1, "name": "Announce",
                                     "reliable": True, "payload": {"text": "Goal at the north end!"}})
        t = FakeTransport([old, new])
        a = beach_adapter(t)
        a.look()  # first observation: the old fall happened before we arrived
        a.look()  # second: the goal is new
        self.assertEqual(a.hear(), "World: Goal at the north end!")
        self.assertEqual(a.hear(), "(no new chat)")

    def test_turn_bundle_does_not_eat_what_hear_returns(self):
        old = load("castles_far.json")
        new = copy.deepcopy(old)
        new["recent_events"].append({"id": 2, "tick": 9999, "server_time_ms": 1, "name": "Announce",
                                     "reliable": True, "payload": {"text": "Goal at the south end!"}})
        a = beach_adapter(FakeTransport([old, new], chat=load_chat()))
        a.look()
        b = a.turn_bundle(n_chat=10)
        self.assertIn("World: Goal at the south end!", b["recent"]["text"])
        heard = a.hear()
        self.assertIn("World: Goal at the south end!", heard)
        self.assertIn("Drift: drift message 0", heard)


def load_chat() -> dict:
    return json.loads((MESA / "chat_messages.json").read_text())


class BeachActTests(unittest.TestCase):
    def test_kick_out_of_reach_names_nearest_ball(self):
        raw = load("spawn.json")
        t = FakeTransport([raw], on_input=lambda b: with_result(raw, "KickFailed:NoBallInReach"))
        res = beach_adapter(t).act("Kick", {"direction": [0, 0, 1], "power": 1})
        self.assertRegex(res, r"^Kick failed: no ball within 3 of you; nearest is the volleyball [\d.]+ \w+ "
                              r"at \(6,0\.6,-10\) - walk up to it first$")

    def test_kick_success_reports_goal(self):
        raw = load("spawn.json")
        goal = copy.deepcopy(raw)
        goal["recent_events"] = [{"id": 7, "tick": 1, "server_time_ms": 1, "name": "Announce",
                                  "reliable": True, "payload": {"text": "Goal at the north end! (soccer ball)"}}]

        def on_input(body):
            out = with_result(raw, "KickSuccess")
            out["player"]["attributes"]["LastKicked"] = "SoccerBall"
            return out
        t = FakeTransport([raw, raw, goal], on_input=on_input)
        res = beach_adapter(t).act("Kick", {"direction": [0, 0, 1], "power": 1})
        self.assertTrue(res.startswith("Kicked the soccer ball N (power 1)"), res)
        self.assertIn("Goal at the north end!", res)
        self.assertEqual(t.inputs[-1], {"type": "Kick", "data": {"direction": [0.0, 0.0, 1.0], "power": 1.0}})

    def test_kick_validation(self):
        t = FakeTransport([load("spawn.json")])
        a = beach_adapter(t)
        self.assertIn("rejected", a.act("Kick", {"direction": [0, 1, 0]}))
        self.assertEqual(t.inputs, [])

    def test_mold_results(self):
        raw = load("spawn.json")
        for code, expect in (("MoldSuccess", "Molded a block piece"),
                             ("MoldFailed:TooManyPieces", "already has 40 sand pieces"),
                             ("MoldFailed:HandsFull", "already holding")):
            t = FakeTransport([raw], on_input=lambda b, c=code: with_result(raw, c))
            self.assertIn(expect, beach_adapter(t).act("Mold", {"shape": "block"}))
        t = FakeTransport([raw])
        self.assertIn("must be one of block, tower, wall, flag", beach_adapter(t).act("Mold", {"shape": "moat"}))

    def test_mesa_rejects_beach_actions(self):
        t = FakeTransport([json.loads((MESA / "spawn.json").read_text())])
        a = beach_adapter(t)
        self.assertIn("unknown action 'Kick'", a.act("Kick", {"direction": [1, 0, 0]}))

    def test_pickup_no_object_on_the_beach(self):
        raw = load("spawn.json")
        t = FakeTransport([raw], on_input=lambda b: with_result(raw, "PickupFailed:NoObject"))
        res = beach_adapter(t).act("Pickup", {"position": [3, 0.6, 3]})
        self.assertRegex(res, r"nothing within 1\.5 of \(3,0\.6,3\); nearest is SoccerBall")


class WorldScriptTests(unittest.TestCase):
    """Static checks on worlds/beach that the brief asks for."""

    def setUp(self):
        self.lua = (ROOT / "worlds" / "beach" / "main.lua").read_text()
        self.toml = (ROOT / "worlds" / "beach" / "world.toml").read_text()

    def test_plots_config_table_is_at_the_top(self):
        first = self.lua.index("local PLOTS = {")
        self.assertLess(first, self.lua.index("local CONFIG = {"))
        self.assertIn("enabled = true", self.lua[first:first + 200])

    def test_config(self):
        self.assertRegex(self.toml, r"max_players = ([6-9]|\d\d)")
        self.assertRegex(self.toml, r"afk_timeout = [1-9]\d*")

    def test_attribution_present(self):
        r = ROOT / "worlds" / "beach" / "renderer"
        self.assertIn("MIT License", (r / "LICENSE.clawblox").read_text())
        self.assertIn("Derived from Clawblox", (r / "src" / "index.js").read_text())
        self.assertTrue((ROOT / "worlds" / "beach" / "NOTICE.md").exists())

    def test_no_real_names_in_test_players(self):
        for f in (ROOT / "scripts").glob("beach_*.py"):
            for name in re.findall(r'ClawbloxAdapter\([^,]+, "([^"]+)"', f.read_text()):
                self.assertIn(name, ("Sandy", "Pebble", "Chatter", "ItBot"))


if __name__ == "__main__":
    unittest.main()
