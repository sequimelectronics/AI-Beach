# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""The world's join key, live (job 08, item 2), plus the renamed player in the world (item 3).

Needs, on this machine: the Beach, and a world started with `python -m beach.world` (so it has a
fresh join key, and its bridge has handed that key to the Beach) using a Clawblox built with
patches/clawblox-join-key.patch. Participants Sandy and Pebble (agents) and Coral (a person)
must exist; pass their tokens. Run it against a world whose max_players is 3: then "no slot used"
shows up as all three Beach joins still fitting after five refused direct ones.

What happens:
  1. Direct joins that skip the Beach: no key, a wrong key, and the name of a real participant.
     Each is refused at once (403), and the world has no player and no used slot afterwards.
  2. Coral joins the person way (POST /zones/<zone>/play: the Beach joins with the key) and
     Sandy joins the agent way (the adapter's join_via=beach_joiner). Both are admitted, and are
     still there after the BeachDoor script's 15-second wait (the second layer agrees).
  3. Sandy renames. The world's player list carries the new name (BeachName), and Pebble's
     adapter, joined through the Beach too, sees and hears Sandy under it.

    python3 scripts/join_key_live.py --tokens tokens.json --spectator-log <run>/.ai-beach-world.log
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from adapters.clawblox.adapter import ClawbloxAdapter  # noqa: E402
from adapters.clawblox.front_door import beach_joiner  # noqa: E402
from beach.bridge import spectator_token_from_log  # noqa: E402

_OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def call(method, url, body=None, token=None, headers=None):
    h = dict(headers or {})
    if token:
        h["Authorization"] = f"Bearer {token}"
    if body is not None:
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, method=method, headers=h,
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with _OP.open(req, timeout=15) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--beach", default="http://127.0.0.1:8765")
    ap.add_argument("--world", default="http://127.0.0.1:8100")
    ap.add_argument("--zone", default="beachblox")
    ap.add_argument("--tokens", required=True, help="JSON {name: token} for Sandy, Pebble, Coral")
    ap.add_argument("--spectator-log", required=True, help="the world's log (for its spectator token)")
    ap.add_argument("--door-wait", type=float, default=17.0, help="how long the BeachDoor script waits (+2)")
    ap.add_argument("--new-name", default="Sandcastle Sam")
    a = ap.parse_args(argv)
    T = json.loads(Path(a.tokens).read_text())
    W, BE, Z = a.world, a.beach, a.zone
    checks: dict[str, bool] = {}

    def spectate():
        tok = spectator_token_from_log(a.spectator_log)
        return call("GET", f"{W}/spectate", headers={"X-Spectator-Token": tok})[1]

    def world_players():
        return sorted((p["name"], (p.get("attributes") or {}).get("BeachName")) for p in spectate()["players"])

    info = call("GET", f"{BE}/zones/{Z}/world", token=T["Coral"])[1]
    print(f"0. The Beach says joining {Z} needs its key: {info.get('join_key_required')}; steps: {info.get('steps')}")
    checks["beach_knows_the_key"] = info.get("join_key_required") is True

    print("1. Direct joins, skipping the Beach")
    refused = []
    for label, name, hdr in (("no key", "Intruder", {}), ("a wrong key", "Intruder", {"X-Join-Key": "guess"}),
                             ("no key, a real participant's name", "Sandy", {}),
                             ("no key", "Intruder2", {}), ("no key", "Intruder3", {})):
        t0 = time.monotonic()
        st, body = call("POST", f"{W}/join?name={name}", headers=hdr)
        ms = (time.monotonic() - t0) * 1000
        print(f"   {name} with {label}: {st} in {ms:.0f} ms ({str(body)[:60]})")
        refused.append(st == 403 and ms < 1000)
    now = world_players()
    print(f"   players in the world right after: {now}")
    checks["direct_joins_refused_at_once"] = all(refused)
    checks["no_player_no_slot"] = now == []

    print("2. Joins through the Beach")
    t0 = time.monotonic()
    st, coral = call("POST", f"{BE}/zones/{Z}/play", token=T["Coral"])
    print(f"   Coral (person, POST /zones/{Z}/play): {st} in {(time.monotonic() - t0) * 1000:.0f} ms; "
          f"session in the link's fragment: {'#session=' in str(coral.get('viewer', '')) if st == 200 else coral}")
    checks["person_admitted"] = st == 200 and "#session=" in coral["viewer"]
    t0 = time.monotonic()
    sandy = ClawbloxAdapter(W, name="Sandy", join_via=beach_joiner(BE, T["Sandy"], Z))
    sandy.join()
    print(f"   Sandy (agent, join_via=beach_joiner): in, door says ok, after {time.monotonic() - t0:.1f}s")
    pebble = ClawbloxAdapter(W, name="Pebble", join_via=beach_joiner(BE, T["Pebble"], Z))
    pebble.join()
    print(f"   Pebble (agent) too. Players: {world_players()}")
    print(f"   waiting {a.door_wait:.0f}s (past the BeachDoor script's 15 s)...")
    time.sleep(a.door_wait)
    after = world_players()
    print(f"   players: {after}")
    checks["beach_joins_admitted_and_kept"] = [n for n, _ in after] == ["Coral", "Pebble", "Sandy"]

    print("3. Sandy renames; the world shows the new name")
    st, r = call("PUT", f"{BE}/me/name", {"name": a.new_name}, token=T["Sandy"])
    print(f"   PUT /me/name {a.new_name!r}: {st}")
    shown = None
    for _ in range(30):
        shown = dict(world_players()).get("Sandy")
        if shown == a.new_name:
            break
        time.sleep(1)
    print(f"   world player list (engine name, BeachName): {world_players()}")
    sandy.say("Same me, new name.")
    time.sleep(2)
    look, hear = pebble.look(), pebble.hear()
    print("   Pebble's look:", " | ".join(l for l in look.splitlines() if a.new_name in l)[:200])
    print("   Pebble hears:", hear.replace("\n", " | ")[:200])
    checks["world_carries_new_name"] = shown == a.new_name
    checks["agent_sees_new_name"] = a.new_name in look and a.new_name in hear

    print()
    for k, v in checks.items():
        print(f"   {'PASS' if v else 'FAIL'}  {k}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
