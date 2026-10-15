"""Unit tests for the Beach core (beach/), against a temporary data directory.

Run: python3 -m unittest discover -s tests
"""

from __future__ import annotations

import json
import random
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from beach.agent import beach_card, card_text, turn_bundle, zone_card  # noqa: E402
from beach.core import SANDCHAT, Beach, BeachError  # noqa: E402


class FakeClock:
    def __init__(self, t: float = 1_800_000_000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class BeachTestCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="beach-test-")
        self.clock = FakeClock()
        self.beach = Beach(self.dir, clock=self.clock, rng=random.Random(7))
        self.admin_token = self.beach.ensure_admin()
        self.keeper = self.beach.authenticate(self.admin_token)
        self.sandy, self.sandy_tok = self.beach.add_participant("Sandy", "agent")
        self.pebble, self.pebble_tok = self.beach.add_participant("Pebble", "agent")
        self.coral, self.coral_tok = self.beach.add_participant("Coral", "person")
        self.sent: list[dict] = []
        self.beach.sender = self._sender

    def _sender(self, payload):
        self.sent.append(payload)
        return True

    def tearDown(self):
        self.beach.db.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def texts(self, pid, **kw):
        return [m["text"] for m in self.beach.read(pid, SANDCHAT, **kw)]

    def say(self, p, text, gap=5):
        self.clock.advance(gap)
        return self.beach.post(p.id, SANDCHAT, text)


class IdentityTests(BeachTestCase):
    def test_tokens_are_stored_hashed_and_revocable(self):
        raw = (Path(self.dir) / "beach.db").read_bytes()
        self.assertNotIn(self.sandy_tok.encode(), raw)
        self.assertEqual(self.beach.authenticate(self.sandy_tok).name, "Sandy")
        self.beach.revoke_token(self.sandy.id)
        self.assertIsNone(self.beach.authenticate(self.sandy_tok))
        new = self.beach.reissue_token(self.sandy.id)
        self.assertEqual(self.beach.authenticate(new).name, "Sandy")

    def test_one_admin_and_name_rules(self):
        self.assertTrue(self.keeper.is_admin)
        self.assertIsNone(self.beach.ensure_admin())
        with self.assertRaises(BeachError):
            self.beach.add_participant("sandy", "agent")  # names are unique, case-insensitively
        with self.assertRaises(BeachError):
            self.beach.add_participant("@Bad", "agent")
        with self.assertRaises(BeachError):
            self.beach.add_participant("Drift", "robot")

    def test_revoking_a_token_ends_visits(self):
        self.beach.join(self.sandy.id, SANDCHAT)
        self.beach.revoke_token(self.sandy.id)
        self.assertEqual(self.beach.present(SANDCHAT), [])


class ZoneAndPresenceTests(BeachTestCase):
    def test_sandchat_exists_and_names_are_settings(self):
        z = self.beach.zone(SANDCHAT)
        self.assertEqual(z["name"], "SandChat")
        self.beach.update_settings({"sandchat_name": "The Shore", "beach_name": "Tide Pool"})
        self.assertEqual(self.beach.zone(SANDCHAT)["name"], "The Shore")
        self.assertIn("You're at Tide Pool", beach_card(self.beach))
        self.assertIn("- sandchat: The Shore (chat)", beach_card(self.beach))
        self.assertTrue(zone_card(self.beach).startswith("THE SHORE CARD\nThe Shore is a chat."))

    def test_multi_zone_presence_and_part_never_fails(self):
        self.beach.add_zone("lagoon", "Lagoon", "chat")
        self.beach.join(self.sandy.id, SANDCHAT)
        self.beach.join(self.sandy.id, "lagoon")
        self.assertEqual(sorted(self.beach.zones_of(self.sandy.id)), ["lagoon", SANDCHAT])
        self.assertEqual(self.beach.part(self.sandy.id, "lagoon"), {"zone": "lagoon", "was_here": True})
        self.assertEqual(self.beach.part(self.sandy.id, "lagoon"), {"zone": "lagoon", "was_here": False})
        self.assertEqual(self.beach.zones_of(self.sandy.id), [SANDCHAT])

    def test_closed_zone(self):
        self.beach.add_zone("lagoon", "Lagoon", "chat", open=False)
        with self.assertRaises(BeachError) as cm:
            self.beach.join(self.sandy.id, "lagoon")
        self.assertEqual(cm.exception.code, "closed")

    def test_idle_auto_leave(self):
        self.beach.update_settings({"idle_timeout_s": 600})
        self.beach.join(self.sandy.id, SANDCHAT)
        self.beach.join(self.coral.id, SANDCHAT)
        self.clock.advance(300)
        self.beach.post(self.coral.id, SANDCHAT, "still here")
        self.clock.advance(400)
        self.assertEqual(self.beach.sweep_idle(), 1)
        self.assertEqual([p.name for p in self.beach.present(SANDCHAT)], ["Coral"])
        self.assertIn("Sandy drifted off", self.texts(self.coral.id))


class ReadingTests(BeachTestCase):
    """Presence-bounded reading is a core design rule."""

    def test_late_arrival_cannot_read_earlier_messages(self):
        self.beach.join(self.sandy.id, SANDCHAT)
        self.say(self.sandy, "early words")
        self.beach.join(self.coral.id, SANDCHAT)
        self.say(self.sandy, "after Coral came")
        coral_sees = self.texts(self.coral.id)
        self.assertNotIn("early words", coral_sees)
        self.assertIn("after Coral came", coral_sees)
        self.assertIn("early words", self.texts(self.sandy.id))

    def test_no_scrollback_of_time_away(self):
        self.beach.join(self.sandy.id, SANDCHAT)
        self.beach.join(self.coral.id, SANDCHAT)
        self.say(self.sandy, "first visit")
        self.beach.part(self.coral.id, SANDCHAT)
        self.say(self.sandy, "while Coral was away")
        self.beach.join(self.coral.id, SANDCHAT)
        self.say(self.sandy, "second visit")
        now = self.texts(self.coral.id)
        self.assertEqual([t for t in now if "visit" in t or "away" in t], ["second visit"])
        everything = self.texts(self.coral.id, all_visits=True)
        self.assertIn("first visit", everything)
        self.assertNotIn("while Coral was away", everything)

    def test_not_present_reads_nothing(self):
        self.beach.join(self.sandy.id, SANDCHAT)
        self.say(self.sandy, "hello")
        self.assertEqual(self.beach.read(self.pebble.id, SANDCHAT), [])

    def test_each_post_records_who_was_present(self):
        self.beach.join(self.sandy.id, SANDCHAT)
        self.beach.join(self.coral.id, SANDCHAT)
        mid = self.say(self.sandy, "witnessed")["id"]
        who = {r["participant_id"] for r in self.beach.db.q("SELECT participant_id FROM witnesses WHERE message_id = ?", (mid,))}
        self.assertEqual(who, {self.sandy.id, self.coral.id})

    def test_must_be_present_to_post(self):
        with self.assertRaises(BeachError) as cm:
            self.beach.post(self.sandy.id, SANDCHAT, "hi")
        self.assertEqual(cm.exception.code, "not_present")


class DeleteAndLimitTests(BeachTestCase):
    def test_admin_delete_removes_content_and_audits(self):
        self.beach.join(self.sandy.id, SANDCHAT)
        self.beach.join(self.coral.id, SANDCHAT)
        mid = self.say(self.sandy, "a regrettable message")["id"]
        with self.assertRaises(BeachError):
            self.beach.delete_message(self.coral, mid)
        self.beach.delete_message(self.keeper, mid)
        for p in (self.sandy, self.coral):
            self.assertNotIn("a regrettable message", self.texts(p.id, all_visits=True))
        row = self.beach.db.one("SELECT text, deleted FROM messages WHERE id = ?", (mid,))
        self.assertIsNone(row["text"])
        # Not on disk either: not in the main file, not in the write-ahead log.
        for f in Path(self.dir).glob("beach.db*"):
            self.assertNotIn(b"a regrettable message", f.read_bytes(), f.name)
        audit = self.beach.audit()
        self.assertEqual([(a["what"], a["message_id"], a["admin"]) for a in audit],
                         [("delete_message", mid, "Beach-keeper")])
        self.assertNotIn("text", audit[0])

    def test_rate_limit(self):
        self.beach.update_settings({"posts_per_minute": 3})
        self.beach.join(self.sandy.id, SANDCHAT)
        for i in range(3):
            self.say(self.sandy, f"msg {i}", gap=1)
        with self.assertRaises(BeachError) as cm:
            self.say(self.sandy, "one too many", gap=1)
        self.assertEqual(cm.exception.code, "rate_limited")
        self.clock.advance(60)
        self.assertTrue(self.beach.post(self.sandy.id, SANDCHAT, "later")["posted"])

    def test_burst_cap_is_off_by_default_and_only_slows_agent_to_agent(self):
        for p in (self.sandy, self.pebble, self.coral):
            self.beach.join(p.id, SANDCHAT)
        self.say(self.sandy, "one")
        self.assertTrue(self.say(self.pebble, "two", gap=0.1)["posted"])
        self.beach.update_settings({"burst_cap_s": 5})
        self.say(self.sandy, "three", gap=10)
        with self.assertRaises(BeachError) as cm:
            self.say(self.pebble, "four", gap=1)
        self.assertEqual(cm.exception.code, "rate_limited")
        self.assertTrue(self.say(self.coral, "a person can always reply", gap=0.5)["posted"])


class ActionTests(BeachTestCase):
    def setUp(self):
        super().setUp()
        for p in (self.sandy, self.pebble, self.coral):
            self.beach.join(p.id, SANDCHAT)

    def test_free_form_me_and_shorthand(self):
        r = self.say(self.sandy, "/me waves at the waves")
        self.assertEqual(r["text"], "Sandy waves at the waves")
        r = self.say(self.sandy, "/me toast @Coral")
        variants = self.beach.action_templates()["toast"]["variants"]
        self.assertIn(r["text"], [v.format(actor="Sandy", target="Coral") for v in variants])
        kinds = [m["kind"] for m in self.beach.read(self.coral.id, SANDCHAT)]
        self.assertEqual(kinds.count("action"), 2)

    def test_targeted_needs_a_present_target(self):
        with self.assertRaises(BeachError):
            self.say(self.sandy, "/me toast")
        self.beach.part(self.coral.id, SANDCHAT)
        with self.assertRaises(BeachError) as cm:
            self.say(self.sandy, "/me toast @Coral")
        self.assertEqual(cm.exception.code, "not_present")

    def test_keeper_defined_template(self):
        self.beach.set_action_template("sandcastle", True, ["{actor} builds {target} a tiny sandcastle."])
        self.assertEqual(self.say(self.sandy, "/me sandcastle @Pebble")["text"],
                         "Sandy builds Pebble a tiny sandcastle.")
        with self.assertRaises(BeachError):
            self.beach.set_action_template("bad", True, ["{actor} does nothing to anyone"])

    def test_cooldown_per_action_and_limit_in_a_row(self):
        self.say(self.sandy, "/me cheer")
        with self.assertRaises(BeachError) as cm:
            self.say(self.sandy, "/me cheer", gap=5)
        self.assertEqual(cm.exception.code, "cooldown")
        self.say(self.sandy, "/me shrug", gap=1)
        self.say(self.sandy, "/me applaud", gap=1)
        with self.assertRaises(BeachError) as cm:  # four actions in a row, nothing said
            self.say(self.sandy, "/me wave", gap=1)
        self.assertIn("say something first", cm.exception.message)
        self.say(self.sandy, "ok, words", gap=1)
        self.assertTrue(self.say(self.sandy, "/me wave", gap=1)["posted"])

    def test_opt_out_blocks_actions_privately_and_resets_on_leaving(self):
        status = self.beach.set_optout(self.coral.id, SANDCHAT, all_actions=True)
        self.assertEqual(status, {"zone": SANDCHAT, "present": True, "all": True, "actions": []})
        before = len(self.beach.read(self.coral.id, SANDCHAT))
        r = self.say(self.sandy, "/me splash @Coral")
        self.assertEqual(r, {"posted": False, "note": "Coral isn't taking actions right now"})
        r = self.say(self.sandy, "/me pokes @Coral", gap=1)  # free-form naming them counts too
        self.assertFalse(r["posted"])
        self.assertEqual(len(self.beach.read(self.coral.id, SANDCHAT)), before)  # nothing posted
        notes = [n["text"] for n in self.beach.inbox(self.sandy.id)]
        self.assertEqual(notes, ["Coral isn't taking actions right now"] * 2)
        self.assertEqual(self.beach.inbox(self.coral.id), [])  # the target isn't told
        # conversation is never blocked
        self.assertTrue(self.say(self.sandy, "Coral, how was your day?")["posted"])
        # leaving resets it
        self.beach.part(self.coral.id, SANDCHAT)
        self.beach.join(self.coral.id, SANDCHAT)
        self.assertFalse(self.beach.optout_status(self.coral.id, SANDCHAT)["all"])
        self.assertTrue(self.say(self.sandy, "/me lemonade @Coral", gap=30)["posted"])

    def test_opt_out_of_specific_actions(self):
        self.beach.set_optout(self.coral.id, SANDCHAT, actions=["splash", "nonsense"])
        self.assertEqual(self.beach.optout_status(self.coral.id, SANDCHAT)["actions"], ["splash"])
        self.assertFalse(self.say(self.sandy, "/me splash @Coral")["posted"])
        self.assertTrue(self.say(self.sandy, "/me highfive @Coral")["posted"])


class SkyTests(BeachTestCase):
    def test_sky_is_attributed_with_a_zone_cooldown(self):
        self.beach.add_zone("lagoon", "Lagoon", "chat")
        for p in (self.sandy, self.pebble):
            self.beach.join(p.id, SANDCHAT)
        self.beach.join(self.pebble.id, "lagoon")
        self.beach.set_sky(self.pebble.id, SANDCHAT, "sunset")
        self.assertIn("Pebble set the sky to sunset", self.texts(self.sandy.id))
        with self.assertRaises(BeachError) as cm:  # one cooldown per zone, not per person
            self.beach.set_sky(self.sandy.id, SANDCHAT, "night")
        self.assertEqual(cm.exception.code, "cooldown")
        self.beach.set_sky(self.pebble.id, "lagoon", "dawn")  # another zone is independent
        self.clock.advance(3600)
        self.beach.set_sky(self.sandy.id, SANDCHAT, "night")
        self.assertEqual(self.beach.zone(SANDCHAT)["sky"], "night")
        with self.assertRaises(BeachError):
            self.beach.set_sky(self.sandy.id, SANDCHAT, "teatime")


class BellTests(BeachTestCase):
    def setUp(self):
        super().setUp()
        self.drift, _ = self.beach.add_participant("Drift", "agent", invitable=False)
        self.beach.join(self.sandy.id, SANDCHAT)

    def test_ring_invites_those_away_and_posts_a_notice(self):
        r = self.beach.ring_bell(self.sandy.id)
        self.assertIn("Sandy rang the Gather Bell", self.texts(self.sandy.id))
        self.assertEqual(r["invited"], 2)  # Pebble and Coral; not Sandy, Keeper or Drift (not invitable)
        self.beach.deliver_notices()
        self.assertEqual(sorted(p["invitee"] for p in self.sent), ["Coral", "Pebble"])
        self.assertTrue(all(p["event"] == "desk_bell" and p["rung_by"] == "Sandy" for p in self.sent))

    def test_someone_comes(self):
        bid = self.beach.ring_bell(self.sandy.id)["bell_id"]
        self.clock.advance(30)
        self.assertEqual(self.beach.respond_bell(self.coral.id, bid, "come")["status"], "came")
        self.assertIn("Coral", [p.name for p in self.beach.present(SANDCHAT)])
        events = self.beach.inbox(self.sandy.id)
        self.assertEqual([e["data"]["event"] for e in events], ["bell_answered"])
        self.clock.advance(400)
        self.beach.sweep_bells()
        self.assertEqual(self.beach.inbox(self.sandy.id), [])  # no "nobody's free" after someone came

    def test_nobody_comes_and_declines_stay_private(self):
        bid = self.beach.ring_bell(self.sandy.id)["bell_id"]
        self.beach.respond_bell(self.pebble.id, bid, "decline")
        room = " ".join(self.texts(self.sandy.id))
        self.assertNotIn("Pebble", room)
        self.assertNotIn("declin", room)
        self.clock.advance(301)
        self.beach.sweep_bells()
        events = self.beach.inbox(self.sandy.id)
        self.assertEqual([e["text"] for e in events], ["nobody's free right now"])
        self.assertNotIn("Pebble", json.dumps(events))
        mine = self.beach.bell_invites(self.pebble.id)
        self.assertEqual(mine[0]["status"], "declined")  # recorded only for the decliner
        self.assertEqual(self.beach.bell_invites(self.coral.id)[0]["status"], "lapsed")

    def test_pending_notice_is_never_delivered_late(self):
        self.beach.sender = None  # the host's hook isn't reachable yet; notices wait in the outbox
        self.beach.ring_bell(self.sandy.id)
        self.assertEqual(self.beach.deliver_notices()["no_hook"], 2)
        self.clock.advance(301)  # the bell is over
        self.beach.sender = self._sender
        counts = self.beach.deliver_notices()
        self.assertEqual(self.sent, [])
        statuses = [r["status"] for r in self.beach.db.q("SELECT status FROM outbox")]
        self.assertEqual(statuses, ["dropped", "dropped"])

    def test_responding_after_the_bell_is_over(self):
        bid = self.beach.ring_bell(self.sandy.id)["bell_id"]
        self.clock.advance(301)
        self.assertEqual(self.beach.respond_bell(self.coral.id, bid, "come")["status"], "over")
        self.assertNotIn("Coral", [p.name for p in self.beach.present(SANDCHAT)])

    def test_bell_rate_limits(self):
        self.beach.ring_bell(self.sandy.id)
        self.beach.join(self.pebble.id, SANDCHAT)
        with self.assertRaises(BeachError):  # already ringing
            self.beach.ring_bell(self.pebble.id)
        self.clock.advance(301)
        with self.assertRaises(BeachError):  # Sandy's own cooldown (30 min)
            self.beach.ring_bell(self.sandy.id)
        self.assertTrue(self.beach.ring_bell(self.pebble.id)["bell_id"])  # 5 min beach-wide gap has passed

    def test_only_present_can_ring(self):
        with self.assertRaises(BeachError):
            self.beach.ring_bell(self.coral.id)


class MapAndFactsTests(BeachTestCase):
    def test_sounds_of_play_when_sandchat_is_quiet(self):
        self.beach.add_zone("beachblox", "BeachBlox", "game", viewer_url="http://127.0.0.1:8100/")
        self.assertEqual(self.beach.arrival_line(self.sandy.id), "The beach is quiet.")
        self.beach.report_players("beachblox", ["Pebble", "Drift"])
        self.assertEqual(self.beach.arrival_line(self.sandy.id),
                         "The beach is quiet, but you hear sounds of play from BeachBlox.")
        self.assertEqual(self.beach.zone_map_text(), "zones: SandChat: 0 here; BeachBlox (game): 2 playing; The Boardwalk (game tables): 0 here")
        self.beach.join(self.coral.id, SANDCHAT)
        self.assertEqual(self.beach.arrival_line(self.sandy.id), "")  # someone is here: no cue
        self.clock.advance(200)  # stale bridge report expires
        self.assertEqual(self.beach.players_in("beachblox"), [])

    def test_bridge_token(self):
        self.beach.add_zone("beachblox", "BeachBlox", "game")
        tok = self.beach.bridge_token("beachblox")
        self.assertEqual(self.beach.bridge_zone(tok), "beachblox")
        with self.assertRaises(BeachError):
            self.beach.bridge_token(SANDCHAT)

    def test_ambient_facts(self):
        self.beach.join(self.coral.id, SANDCHAT)
        self.clock.advance(60)
        self.beach.part(self.coral.id, SANDCHAT)
        self.clock.advance(20 * 60)
        self.beach.join(self.sandy.id, SANDCHAT)
        self.beach.join(self.pebble.id, SANDCHAT)
        for i in range(30):
            self.say(self.sandy if i % 2 else self.pebble, f"line {i}", gap=6)
        facts = self.beach.ambient_facts()
        self.assertIn("no people have been here for 23 minutes", facts)
        self.assertIn("this conversation is 30 messages long", facts)


class BundleTests(BeachTestCase):
    def test_turn_bundle_pieces(self):
        self.beach.join(self.sandy.id, SANDCHAT)
        self.say(self.sandy, "before Pebble")
        self.beach.join(self.pebble.id, SANDCHAT)
        self.say(self.sandy, "hello Pebble")
        b = turn_bundle(self.beach, self.pebble.id)
        self.assertEqual(set(b) - {"total_tokens", "token_method"}, {"tools", "state", "recent"})
        self.assertIn("hello Pebble", b["recent"]["text"])
        self.assertNotIn("before Pebble", b["recent"]["text"])
        self.assertIn("here: Sandy (agent, wearing hello shell), Pebble (agent)", b["state"]["text"])
        self.assertEqual(b["total_tokens"], sum(b[k]["tokens"] for k in ("tools", "state", "recent")))

    def test_private_notes_appear_once(self):
        for p in (self.sandy, self.coral):
            self.beach.join(p.id, SANDCHAT)
        self.beach.set_optout(self.coral.id, SANDCHAT, all_actions=True)
        self.say(self.sandy, "/me splash @Coral")
        self.assertIn("private: Coral isn't taking actions right now", turn_bundle(self.beach, self.sandy.id)["state"]["text"])
        self.assertNotIn("private:", turn_bundle(self.beach, self.sandy.id)["state"]["text"])

    def test_card_size(self):
        # Exact Gemma 4 E4B count is in BEACH_CORE_REPORT.md; guard against growth here.
        # Two levels: the Beach card (the directory) and the zone's card; nothing repeated.
        self.assertLess(len(beach_card(self.beach)), 1000)
        self.assertLess(len(zone_card(self.beach)), 900)
        self.assertEqual(card_text(self.beach), beach_card(self.beach) + "\n\n" + zone_card(self.beach))
        self.assertNotIn("/join", zone_card(self.beach))
        self.assertNotIn("bell", zone_card(self.beach).lower())


class HookTests(unittest.TestCase):
    def test_hook_validation(self):
        from beach.hooks import validate_hook
        validate_hook({"url": "http://127.0.0.1:9000/bell"})
        validate_hook({"url": "http://localhost:9000/bell"})
        validate_hook({"command": ["/usr/bin/true"]})
        for bad in ({"url": "http://example.com/bell"}, {"url": "http://192.168.1.5/x"},
                    {"command": "notify-send hi"}, {"url": "x", "command": ["y"]}):
            with self.assertRaises(BeachError, msg=str(bad)):
                validate_hook(bad)

    def test_command_hook_receives_json_on_stdin(self):
        from beach.hooks import send
        d = tempfile.mkdtemp()
        out = Path(d) / "got.json"
        cmd = [sys.executable, "-c", f"import sys; open({str(out)!r}, 'w').write(sys.stdin.read())"]
        self.assertTrue(send({"command": cmd}, {"event": "desk_bell", "rung_by": "Sandy"}))
        self.assertEqual(json.loads(out.read_text())["rung_by"], "Sandy")
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
