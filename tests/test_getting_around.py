"""Job 12: getting around, leaving, and watching a world.

- the bar (GET /map) lists every zone, with "you" where you are: here (a chat), playing or
  watching (a world);
- Leave table, and leaving the Boardwalk;
- idle auto-leave says so (and the keeper sets how long);
- the target box: an action with no target takes none (the page grays it out; the API ignores it);
- renaming away from the default "Beach-keeper" shows no "(was ...)";
- no Boardwalk-wide chat: POST /zones/boardwalk/say is refused, table chat isn't;
- the map's quiet line counts the Boardwalk; a world's facts count the people in the world;
- watching a world: no character, never idled out, visible to the world (the door lists watchers);
- a character the world removed: its participant is told, and the next Play says so first.

Against a temporary data directory with a fake clock, and a stand-in world (test_play_leave.py).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from beach import agent  # noqa: E402
from beach.core import BOARDWALK, SANDCHAT, WATCH_TTL_S, Beach, BeachError  # noqa: E402
from test_play_leave import HAVE_FASTAPI, Case  # noqa: E402

if HAVE_FASTAPI:
    from fastapi.testclient import TestClient
    from beach.app import create_app


class ApiCase(Case):
    def setUp(self):
        super().setUp()
        if not HAVE_FASTAPI:
            self.skipTest("needs fastapi")
        self.http = TestClient(create_app(self.beach, upkeep_interval=None))

    def h(self, tok):
        return {"Authorization": f"Bearer {tok}"}

    def zones(self, tok):
        return {z["id"]: z for z in self.http.get("/map", headers=self.h(tok)).json()["zones"]}


class BarTests(ApiCase):
    def test_every_zone_is_listed_with_a_pin_where_you_are(self):
        b = self.beach
        b.add_zone("tidepool", "Tide Pool", "chat")
        z = self.zones(self.coral_tok)
        self.assertEqual(set(z), {"sandchat", "boardwalk", "beachblox", "tidepool"})   # games too
        self.assertEqual({k: v["you"] for k, v in z.items()}, dict.fromkeys(z))       # nowhere yet
        b.join(self.coral.id, SANDCHAT)
        b.join(self.coral.id, BOARDWALK)
        self.play(self.coral)
        b.watch_world(self.sandy.id, "beachblox")
        z = self.zones(self.coral_tok)
        self.assertEqual(z["sandchat"]["you"], "here")
        self.assertEqual(z["boardwalk"]["you"], "here")
        self.assertEqual(z["beachblox"]["you"], "playing")
        self.assertIsNone(z["tidepool"]["you"])
        self.assertEqual(self.zones(self.sandy_tok)["beachblox"]["you"], "watching")
        # Leaving takes the pin away.
        b.part(self.coral.id, BOARDWALK)
        b.leave_world(self.coral.id, "beachblox")
        z = self.zones(self.coral_tok)
        self.assertIsNone(z["boardwalk"]["you"])
        self.assertIsNone(z["beachblox"]["you"])

    def test_pages_carry_the_bar_and_the_world_page_frames_only_its_world(self):
        for page in ("/", "/chat", "/boardwalk", "/avatar", "/keeper", "/world?zone=beachblox"):
            r = self.http.get(page, headers={"Accept": "text/html"})
            self.assertEqual(r.status_code, 200, page)
            self.assertIn('src="/web/common.js"', r.text)       # common.js draws the bar on every page
            self.assertIn('src="/web/words.js"', r.text)
        csp = self.http.get("/world?zone=beachblox").headers["content-security-policy"]
        self.assertIn("frame-src http://127.0.0.1:8100", csp)
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertIn("frame-src 'none'", self.http.get("/world?zone=sandchat").headers["content-security-policy"])
        self.assertNotIn("frame-src", self.http.get("/chat").headers["content-security-policy"])

    def test_the_bar_menu_holds_my_look_and_sign_out(self):
        js = (ROOT / "beach/web/common.js").read_text(encoding="utf-8")
        menu = js[js.index("function meMenu"):js.index("function onEvent")]
        self.assertIn("T.t('my_look')", menu)
        self.assertIn("T.t('sign_out')", menu)
        bar = js[js.index("function drawBar"):js.index("async function refreshBar")]
        self.assertNotIn("my_look", bar)                  # not in the main bar any more
        self.assertNotIn("sign_out", bar)
        self.assertIn("for (const z of zoneOrder(map.zones))", bar)   # every zone, unfiltered


class LeaveTests(ApiCase):
    def test_leave_a_finished_table(self):
        bw = self.beach.tables
        tid = bw.open(self.coral.id, BOARDWALK, "crazy8", options={"players": 2})["id"]
        bw.sit(self.sandy.id, tid)
        bw.watch(self.beach.add_participant("Drift", "person")[0].id, tid)
        bw.resign(self.sandy.id, tid)
        r = self.http.post(f"/tables/{tid}/leave", headers=self.h(self.coral_tok))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["left"])
        drift = self.beach.by_name("Drift")
        bw.leave(drift.id, tid)
        self.assertFalse(bw.view(drift.id, tid)["watching"])

    def test_leave_a_table_before_it_starts_and_not_in_the_middle(self):
        bw = self.beach.tables
        tid = bw.open(self.coral.id, BOARDWALK, "checkers")["id"]
        self.assertEqual(bw.leave(self.coral.id, tid)["status"], "closed")        # stood up
        tid = bw.open(self.coral.id, BOARDWALK, "checkers")["id"]
        bw.sit(self.sandy.id, tid)
        with self.assertRaises(BeachError) as e:
            bw.leave(self.coral.id, tid)
        self.assertIn("resign", e.exception.message)                            # the game waits

    def test_leave_the_boardwalk(self):
        tid = self.beach.tables.open(self.coral.id, BOARDWALK, "checkers")["id"]
        self.assertEqual(self.zones(self.coral_tok)["boardwalk"]["you"], "here")   # sitting is being there
        self.http.post("/zones/boardwalk/part", headers=self.h(self.coral_tok))
        self.assertIsNone(self.zones(self.coral_tok)["boardwalk"]["you"])
        self.assertEqual(self.beach.tables.seat_of(tid, self.coral.id), 0)        # leaving never forfeits
        page = (ROOT / "beach/web/boardwalk.js").read_text(encoding="utf-8")
        self.assertIn("leaveZoneButton()", page[page.index("function renderLobby"):])
        self.assertIn("T.t('leave_table')", page)


class IdleTests(ApiCase):
    def test_idle_auto_leave_says_so(self):
        b = self.beach
        b.join(self.coral.id, BOARDWALK)
        b.join(self.sandy.id, SANDCHAT)
        self.clock.advance(b.setting("idle_timeout_s") + 1)
        b.tick()
        self.assertIsNone(self.zones(self.coral_tok)["boardwalk"]["you"])     # the pin follows
        ev = self.http.get("/me/events", headers=self.h(self.coral_tok)).json()["events"]
        self.assertEqual([e["text"] for e in ev], ["You were away 30 minutes and left The Boardwalk."])
        self.assertEqual(ev[0]["data"], {"event": "idle_left", "zone": "boardwalk"})
        st = agent.state_text(b, self.sandy.id, SANDCHAT)
        self.assertIn("private: You were away 30 minutes and left SandChat.", st)

    def test_the_keeper_sets_the_idle_time(self):
        b = self.beach
        r = self.http.patch("/admin/settings", json={"idle_timeout_s": 600}, headers=self.h(self.admin_tok))
        self.assertEqual(r.json()["idle_timeout_s"], 600)
        b.join(self.coral.id, SANDCHAT)
        self.clock.advance(601)
        b.tick()
        self.assertEqual([e["text"] for e in b.inbox(self.coral.id)], ["You were away 10 minutes and left SandChat."])
        self.assertIn("10 minutes idle in a zone and you leave it (you're told)", agent.beach_card(b))

    def test_nothing_says_you_stay_until_you_leave(self):
        card = agent.beach_card(self.beach)
        self.assertIn("30 minutes idle in a zone and you leave it (you're told)", card)


class ChatTests(ApiCase):
    def test_no_boardwalk_wide_chat(self):
        h = self.h(self.coral_tok)
        self.http.post("/zones/boardwalk/join", headers=h)
        for text in ("hello everyone", "/me waves"):
            r = self.http.post("/zones/boardwalk/say", json={"text": text}, headers=h)
            self.assertEqual(r.status_code, 400)
            self.assertIn("no zone-wide chat", r.json()["message"])
        tid = self.http.post("/zones/boardwalk/tables", json={"game": "checkers"}, headers=h).json()["id"]
        self.assertEqual(self.http.post(f"/tables/{tid}/say", json={"text": "hi"}, headers=h).status_code, 200)
        self.assertNotIn("POST /zones/boardwalk/say", agent.zone_card(self.beach, BOARDWALK))
        self.assertEqual(self.http.post("/zones/sandchat/join", headers=h).status_code, 200)
        self.assertEqual(self.http.post("/zones/sandchat/say", json={"text": "hi"}, headers=h).status_code, 200)

    def test_untargeted_actions_grey_out_the_target_box(self):
        # The page grays the box out for an action that takes no target (wave, shrug)...
        js = (ROOT / "beach/web/chat.js").read_text(encoding="utf-8")
        sync = js[js.index("function syncTarget"):js.index("function aimAt")]
        self.assertIn("ui.target.disabled = !present || !aimed", sync)
        self.assertIn("onchange: () => syncTarget()", js)
        # ...and the actions list says which are which.
        acts = {a["name"]: a["targeted"] for a in self.http.get("/actions", headers=self.h(self.coral_tok)).json()["actions"]}
        self.assertFalse(acts["wave"])
        self.assertFalse(acts["shrug"])
        self.assertTrue(acts["greet"])


class RenameTests(ApiCase):
    def test_no_was_after_renaming_from_the_default(self):
        b = self.beach
        keeper = b.participant(next(p["id"] for p in b.participants() if p["admin"]))
        self.assertEqual(keeper.name, "Beach-keeper")
        r = self.http.put("/me/name", json={"name": "Tide"}, headers=self.h(self.admin_tok)).json()
        self.assertEqual(r["name"], "Tide")
        self.assertIsNone(b.was_name(keeper.id))
        self.assertEqual(b.label(keeper.id), "Tide")
        self.assertIsNone(self.http.get("/me", headers=self.h(self.admin_tok)).json()["was"])
        self.assertIsNone(next(p for p in b.participants() if p["id"] == keeper.id)["was"])
        b.add_participant("Beach-keeper", "person")             # the default name isn't held back
        # A real rename later still shows "(was ...)" for a while.
        self.clock.advance(b.setting("rename_cooldown_s") + 1)
        b.rename(keeper.id, "Kelp")
        self.assertEqual(b.label(keeper.id), "Kelp (was Tide)")

    def test_an_ordinary_first_rename_still_shows_was(self):
        self.beach.rename(self.coral.id, "Shell")
        self.assertEqual(self.beach.label(self.coral.id), "Shell (was Coral)")


class QuietTests(ApiCase):
    def test_the_quiet_line_counts_the_boardwalk(self):
        b = self.beach
        self.assertEqual(b.arrival_line(self.coral.id), "The beach is quiet.")
        b.join(self.sandy.id, BOARDWALK)
        self.assertEqual(b.arrival_line(self.coral.id),
                         "The beach is quiet, but you hear sounds of play from The Boardwalk.")
        b.join(self.coral.id, BOARDWALK)                       # you, on your own, don't count
        b.part(self.sandy.id, BOARDWALK)
        self.assertEqual(b.arrival_line(self.coral.id), "The beach is quiet.")

    def test_world_facts_count_people_in_the_world(self):
        b = self.beach
        self.assertIn("no people have been here yet", b.ambient_facts("beachblox"))
        self.play(self.coral)
        self.report("Coral")
        self.assertFalse([f for f in b.ambient_facts("beachblox") if f.startswith("no people")])
        b.leave_world(self.coral.id, "beachblox")
        self.report()
        self.clock.advance(600)
        self.assertIn("no people have been here for 10 minutes", b.ambient_facts("beachblox"))
        # Watching counts too: a person on the lifeguard chair is a person in the world.
        b.watch_world(self.coral.id, "beachblox")
        self.assertFalse([f for f in b.ambient_facts("beachblox") if f.startswith("no people")])


class WatchTests(ApiCase):
    def test_watch_is_seen_and_has_no_character(self):
        b = self.beach
        r = self.http.post("/zones/beachblox/watch", headers=self.h(self.coral_tok)).json()
        self.assertTrue(r["watching"])
        self.assertTrue(r["viewer"].endswith("#watch=1"))
        self.assertNotIn("session", r["viewer"])
        self.assertEqual(self.world.joins, [])                               # no character
        self.assertEqual(b.door("beachblox")["watchers"], ["Coral"])          # the world shows the name
        who = b.who_in("beachblox")
        self.assertEqual([(w["name"], w.get("watching")) for w in who], [("Coral", True)])
        self.assertNotIn("Coral", b.game_looks("beachblox"))                  # no body to draw
        z = b.zone_map()
        self.assertEqual([(x["here"], x["watching"]) for x in z if x["id"] == "beachblox"], [(0, 1)])
        self.assertIn("BeachBlox (game): 0 playing, 1 watching", b.zone_map_text())

    def test_watchers_are_never_idled_out(self):
        b = self.beach
        b.watch_world(self.coral.id, "beachblox")
        b.report_players("beachblox", [], world_up=True, run="run-1", afk_timeout_s=300)
        for _ in range(12):                                   # an hour of the world's reports
            self.clock.advance(300)
            b.report_players("beachblox", [], world_up=True, run="run-1", afk_timeout_s=300)
            b.watch_world(self.coral.id, "beachblox")         # the open page keeps the watch up
            b.tick()
        self.assertTrue(b.watching(self.coral.id, "beachblox"))
        self.assertEqual(b.inbox(self.coral.id), [])           # nobody told them anything happened

    def test_a_watch_fades_when_its_page_is_gone(self):
        b = self.beach
        b.watch_world(self.coral.id, "beachblox")
        self.clock.advance(WATCH_TTL_S + 1)
        self.assertFalse(b.watching(self.coral.id, "beachblox"))
        self.assertEqual(b.door("beachblox")["watchers"], [])

    def test_play_or_watch(self):
        b = self.beach
        b.watch_world(self.coral.id, "beachblox")
        self.play(self.coral)                                 # Play ends watching
        self.assertFalse(b.watching(self.coral.id, "beachblox"))
        b.watch_world(self.coral.id, "beachblox")              # Watch takes the character out
        self.assertFalse(b.playing(self.coral.id, "beachblox"))
        self.assertTrue(b.watching(self.coral.id, "beachblox"))
        self.http.delete("/zones/beachblox/watch", headers=self.h(self.coral_tok))
        self.assertFalse(b.watching(self.coral.id, "beachblox"))

    def test_an_agent_sees_who_is_watching(self):
        b = self.beach
        b.watch_world(self.coral.id, "beachblox")
        st = agent.state_text(b, self.sandy.id, "beachblox")
        self.assertIn("watching: Coral (person)", st)


class RemovedTests(ApiCase):
    def setUp(self):
        super().setUp()
        self.b = self.beach
        self.first = self.play(self.sandy)
        self.clock.advance(30)
        self.reported(["Sandy"])

    def reported(self, players, run="run-1"):
        from beach.core import Beach as B
        entries = [{"user_id": B.user_id_for(j["agent_id"]), "joined_as": n}
                   for n, j in self.world.joins if n in players and j["session"] in self.world.live]
        self.b.report_players("beachblox", entries, world_up=True, run=run, afk_timeout_s=300)

    def test_a_kicked_agent_is_told(self):
        self.world.live.discard(self.first["session"])        # the world's idle limit took Sandy out
        self.reported([])
        notes = self.b.inbox(self.sandy.id, consume=False)
        self.assertEqual([n["text"] for n in notes],
                         ["You were idle 5 minutes in BeachBlox, so the world took your character out "
                          "(its idle limit). Play again any time."])
        self.assertIn("private: You were idle 5 minutes in BeachBlox", agent.state_text(self.b, self.sandy.id, SANDCHAT))
        self.assertFalse(self.b.playing(self.sandy.id, "beachblox"))

    def test_the_next_play_says_what_happened_instead_of_a_silent_new_character(self):
        self.world.live.discard(self.first["session"])
        self.reported([])
        r = self.http.post("/zones/beachblox/play", headers=self.h(self.sandy_tok))
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["removed"], "idle")
        self.assertIn("Play again to come back as a new character", r.json()["message"])
        self.assertEqual(len(self.world.joins), 1)               # nothing was created
        second = self.play(self.sandy)                            # asked again: a new one
        self.assertFalse(second["existing"])
        live = [c for g in self.b.door("beachblox")["grants"] for c in g["claims"] if not c["left"]]
        self.assertEqual(len(live), 1)                            # still one character

    def test_even_before_the_bridge_reports_it(self):
        self.world.live.discard(self.first["session"])           # gone; no report yet
        with self.assertRaises(BeachError) as e:
            self.play(self.sandy)
        self.assertIn("no longer in BeachBlox", e.exception.message)
        self.assertEqual(len(self.world.joins), 1)

    def test_leaving_yourself_or_a_world_restart_is_not_a_kick(self):
        self.b.leave_world(self.sandy.id, "beachblox")
        self.reported([])
        self.assertEqual(self.b.inbox(self.sandy.id), [])
        self.assertTrue(self.play(self.sandy)["session"])            # no hold-up after your own Leave
        self.clock.advance(30)
        self.reported(["Sandy"])
        self.world.restart()
        self.reported([], run="run-2")                                 # a new run: not a kick
        self.assertEqual(self.b.inbox(self.sandy.id), [])

    def test_a_world_that_is_down_kicks_nobody(self):
        self.b.report_players("beachblox", [], world_up=False, run=None)
        self.assertEqual(self.b.inbox(self.sandy.id), [])


if __name__ == "__main__":
    unittest.main()
