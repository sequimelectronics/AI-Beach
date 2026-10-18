#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""Scripted Beach scenario: two agents (Sandy, Pebble) and a person-shaped client (Coral).

Everything goes through the HTTP door (in-process FastAPI TestClient) against a
temporary data directory, with a fake clock so cooldowns and bell waits run
instantly. Each step is checked; the script exits non-zero if any check fails.
It also measures turn_bundle() sizes.

    python3 scripts/beach_core_scenario.py [--tokenizer gemma-4-E4B-it/tokenizer.json] [--out run.json]
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from beach.agent import card_text, turn_bundle  # noqa: E402
from beach.app import create_app  # noqa: E402
from beach.core import Beach  # noqa: E402
from beach.tokens import make_counter  # noqa: E402


class FakeClock:
    def __init__(self, t: float = 1_800_000_000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, s: float) -> None:
        self.t += s


class Client:
    """A participant's view of the door."""

    def __init__(self, http: TestClient, name: str, token: str, clock: FakeClock):
        self.http, self.name, self.clock = http, name, clock
        self.h = {"Authorization": f"Bearer {token}"}

    def _r(self, method, path, body=None):
        r = self.http.request(method, path, json=body, headers=self.h)
        return r.status_code, r.json()

    def join(self, zone="sandchat"):
        return self._r("POST", f"/zones/{zone}/join")[1]

    def part(self, zone="sandchat"):
        return self._r("POST", f"/zones/{zone}/part")[1]

    def say(self, text, zone="sandchat", gap=5.0):
        self.clock.advance(gap)
        return self._r("POST", f"/zones/{zone}/say", {"text": text})

    def lines(self, zone="sandchat", **q):
        qs = "&".join(f"{k}={v}" for k, v in q.items())
        return [m["line"] for m in self._r("GET", f"/zones/{zone}/messages?{qs}")[1]["messages"]]

    def sky(self, sky, zone="sandchat"):
        return self._r("POST", f"/zones/{zone}/sky", {"sky": sky})

    def me(self):
        return self._r("GET", "/me")[1]

    def events(self):
        return self._r("GET", "/me/events")[1]["events"]

    def optout(self, body):
        return self._r("PUT", "/me/optout", body)[1]

    def ring(self):
        return self._r("POST", "/bell/ring")

    def respond(self, bid, answer):
        return self._r("POST", f"/bell/{bid}/respond", {"answer": answer})[1]

    def zones(self):
        return self._r("GET", "/zones")[1]

    def turn(self):
        return self._r("GET", "/agent/turn")[1]


CHATTER = [
    "morning everyone, the tide is way out today",
    "I found a whole line of shells down by the rocks",
    "did anyone try the new sandcastle plots yet?",
    "Pebble built one three high with a flag on top",
    "it fell over twice before it stood, though",
    "that's the trick, wide pieces at the bottom",
    "I keep putting the tower first and it tips",
    "the beach ball keeps drifting north, is that the wind?",
    "it's a breeze, it floats a bit longer than the others",
    "who wants to play soccer later? we need two more",
    "I'm in, but after lunch",
    "same, I can be goalkeeper",
    "the sky looked amazing at sunset yesterday",
    "somebody set it to night right after, it was so dark",
    "ha, that was me, sorry",
    "no worries, it was fun to see the stars",
]


def run(counter) -> dict:
    data = Path(tempfile.mkdtemp(prefix="beach-scenario-"))
    clock = FakeClock()
    beach = Beach(data, clock=clock, rng=random.Random(3))
    sent: list[dict] = []
    beach.sender = lambda payload: (sent.append(payload) or True)
    admin_token = beach.ensure_admin()
    http = TestClient(create_app(beach, upkeep_interval=None))
    keeper = Client(http, "Beach-keeper", admin_token, clock)
    results: dict = {"checks": {}, "sizes": {}, "data_dir_inside_repo": str(data).startswith(str(Path(__file__).resolve().parents[1]))}
    checks = results["checks"]

    def add(name, kind):
        _, body = keeper._r("POST", "/admin/participants", {"name": name, "kind": kind, "one_room": False})
        token = http.post("/claim", json={"code": body["invite"]["code"]}).json()["token"]   # the invite, claimed
        return Client(http, name, token, clock)

    sandy, pebble, coral = add("Sandy", "agent"), add("Pebble", "agent"), add("Coral", "person")
    keeper._r("POST", "/admin/zones", {"id": "lagoon", "name": "Lagoon", "kind": "chat"})
    keeper._r("POST", "/admin/zones", {"id": "beachblox", "name": "BeachBlox", "kind": "game",
                                       "viewer_url": "http://127.0.0.1:8100/"})
    bridge = keeper._r("POST", "/admin/zones/beachblox/bridge-token")[1]["token"]

    # 1. join/part and multi-zone presence
    sandy.join(); pebble.join(); sandy.join("lagoon")
    checks["multi_zone"] = sorted(sandy.me()["zones"]) == ["lagoon", "sandchat"]
    checks["part_never_fails"] = sandy.part("lagoon")["was_here"] and sandy.part("lagoon") == {"zone": "lagoon", "was_here": False}

    # 2. presence-bounded reading
    sandy.say("before Coral arrives: a secret about the shells")
    pebble.say("ha, our secret")
    coral.join()
    sandy.say("hi Coral, welcome")
    seen = coral.lines()
    checks["late_arrival_cannot_read_earlier"] = (not any("secret" in s for s in seen)
                                                 and any("welcome" in s for s in seen))
    status, _ = Client(http, "x", "bad-token", clock)._r("GET", "/zones/sandchat/messages")
    checks["no_token_no_door"] = status == 401

    # 3. /me and a shorthand action
    coral.say("/me waves")
    _, toast = sandy.say("/me toast @Coral")
    checks["me_action"] = "* Coral waves" in coral.lines()
    checks["shorthand_action"] = toast.get("posted") and "Coral" in toast.get("text", "")
    results["toast_text"] = toast.get("text")

    # 4. per-visit opt-out, private note, reset on leaving
    coral.optout({"all": True})
    _, splash = pebble.say("/me splash @Coral")
    checks["optout_blocks_action"] = splash == {"posted": False, "note": "Coral isn't taking actions right now"}
    checks["optout_note_is_private"] = (not any("splash" in s or "isn't taking" in s for s in coral.lines())
                                       and [e["text"] for e in pebble.events()] == ["Coral isn't taking actions right now"])
    checks["optout_status_visible"] = coral.me()["optout"]["all"] is True
    checks["conversation_never_blocked"] = pebble.say("Coral, want to build something later?")[1]["posted"]
    coral.part(); coral.join()
    checks["optout_reset_on_leaving"] = coral.me()["optout"]["all"] is False
    checks["action_after_reset"] = pebble.say("/me lemonade @Coral", gap=30)[1]["posted"]

    # 5. sky and its zone cooldown
    pebble.sky("sunset")
    st, body = sandy.sky("night")
    checks["sky_attributed"] = "- Pebble set the sky to sunset" in coral.lines()
    checks["sky_zone_cooldown"] = st == 429 and body["error"] == "cooldown"
    clock.advance(3600)
    checks["sky_after_cooldown"] = sandy.sky("night")[0] == 200

    # 6. admin delete
    _, posted = pebble.say("something that shouldn't stay")
    keeper._r("DELETE", f"/admin/messages/{posted['id']}")
    audit = keeper._r("GET", "/admin/audit")[1]["audit"]
    checks["delete_removes_content"] = not any("shouldn't stay" in s for s in coral.lines() + sandy.lines())
    checks["delete_audit_row"] = (len(audit) == 1 and audit[0]["message_id"] == posted["id"]
                                  and "shouldn't stay" not in json.dumps(audit))
    checks["participant_cannot_delete"] = pebble._r("DELETE", f"/admin/messages/{posted['id']}")[0] == 403

    # Typical turn: Sandy, three here, a short conversation.
    results["sizes"]["typical"] = {k: v["tokens"] for k, v in turn_bundle(beach, beach.by_name("Sandy").id,
                                                                           counter=counter).items() if k in ("tools", "state", "recent")}
    results["sizes"]["typical"]["total"] = sum(results["sizes"]["typical"].values())

    # 7a. Gather Bell: Coral is away, Sandy rings, Coral comes.
    coral.part()
    st, ring = sandy.ring()
    beach.deliver_notices()
    invited = sorted(p["invitee"] for p in sent)
    checks["bell_notice_in_room"] = "- Sandy rang the Gather Bell" in pebble.lines()
    checks["bell_invites_only_those_away"] = invited == ["Coral"]
    clock.advance(40)
    came = coral.respond(ring["bell_id"], "come")
    checks["bell_person_came"] = came["status"] == "came" and "sandchat" in coral.me()["zones"]
    checks["ringer_told_who_came"] = [e["data"]["event"] for e in sandy.events()] == ["bell_answered"]

    # 7b. A ring nobody answers; a declined invite stays private; no late delivery.
    clock.advance(1800)
    sandy.part(); coral.part()
    beach.sender = None  # the host's hook is unavailable: notices wait in the outbox
    sent.clear()
    st, ring2 = pebble.ring()
    checks["second_ring_ok"] = st == 200
    sandy.respond(ring2["bell_id"], "decline")
    clock.advance(301)
    beach.sender = lambda payload: (sent.append(payload) or True)
    counts = beach.deliver_notices()
    ev = pebble.events()
    checks["nobody_free_event"] = [e["text"] for e in ev] == ["nobody's free right now"]
    checks["nobody_free_names_no_one"] = not any(n in json.dumps(ev) for n in ("Sandy", "Coral"))
    seen = pebble.lines()
    after_ring = seen[seen.index("- Pebble rang the Gather Bell"):]
    results["room_after_unanswered_ring"] = after_ring
    checks["decline_never_shown_to_room"] = not any("declin" in s.lower() or "Sandy" in s for s in after_ring)
    checks["decline_recorded_for_decliner"] = sandy.me()["invites"][0]["status"] == "declined"
    outbox = [r["status"] for r in beach.db.q("SELECT status FROM outbox WHERE bell_id = ?", (ring2["bell_id"],))]
    results["late_outbox"] = outbox
    checks["expired_notice_not_delivered_late"] = sent == [] and outbox == ["dropped", "dropped"]

    # 8. Sounds of play: SandChat empty, a game zone busy.
    pebble.part()
    http.post("/zones/beachblox/players", json={"players": ["Drift", "Shell"]},
              headers={"Authorization": f"Bearer {bridge}"})
    z = coral.zones()
    results["zone_map"] = {"text": z["text"], "arrival": z["arrival"]}
    checks["sounds_of_play"] = z["arrival"] == "The beach is quiet, but you hear sounds of play from BeachBlox."
    checks["bridge_needs_its_token"] = http.post("/zones/beachblox/players", json={"players": ["X"]},
                                                 headers=pebble.h).status_code == 403
    zone_card = z["text"] + "\n" + z["arrival"]
    results["sizes"]["zone_map_card"] = counter(zone_card)
    results["sizes"]["sandchat_card"] = counter(card_text(beach))

    # Busy turn: 6 participants, 40 recent messages.
    extra = [add(n, k) for n, k in (("Drift", "agent"), ("Shell", "person"), ("Kelp", "agent"))]
    room = [sandy, pebble, coral] + extra
    for c in room:
        c.join()
    beach.update_settings({"posts_per_minute": 60})
    i = 0
    while len(sandy.lines()) < 46:  # 40 messages plus join lines
        speaker = room[i % len(room)]
        if i % 9 == 4:
            speaker.say("/me cheer" if i % 2 else "/me applaud", gap=31)
        else:
            speaker.say(CHATTER[i % len(CHATTER)], gap=6)
        i += 1
    busy = turn_bundle(beach, beach.by_name("Sandy").id, counter=counter, cap=40)
    results["sizes"]["busy"] = {k: busy[k]["tokens"] for k in ("tools", "state", "recent")}
    results["sizes"]["busy"]["total"] = busy["total_tokens"]
    results["busy_recent_lines"] = busy["recent"]["text"].count("\n")
    results["busy_example"] = {k: busy[k]["text"] for k in ("tools", "state", "recent")}
    results["token_method"] = counter.method
    results["ok"] = all(checks.values())
    beach.db.close()
    shutil.rmtree(data, ignore_errors=True)
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tokenizer")
    ap.add_argument("--tokenizer-name")
    ap.add_argument("--out")
    args = ap.parse_args()
    res = run(make_counter(args.tokenizer, args.tokenizer_name))
    if args.out:
        Path(args.out).write_text(json.dumps(res, indent=1))
    print(json.dumps({k: res[k] for k in ("token_method", "checks", "sizes", "zone_map", "toast_text")}, indent=1))
    print("SCENARIO", "OK" if res["ok"] else "FAILED")
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
