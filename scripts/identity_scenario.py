# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""One name everywhere, scripted against a REAL running Beach and BeachBlox world (job 07).

Needs the stack running on this machine: the Beach, the beach world (Clawblox) with its
BeachDoor script, and the world's bridge (python -m beach.bridge ... --world-dir <world>).
Participants Sandy and Pebble (agents) and Coral (a person) must exist; pass their tokens.

What happens:
  1. Sandy and Pebble join BeachBlox the agent way: the adapter joins under their Beach name and
     the Beach vouches. Coral joins the person way: the Beach joins for Coral (POST
     /zones/beachblox/play, what the map's button does) and Coral chats in the world with the
     session it got back.
  2. Sandy and Pebble start a checkers game at the Boardwalk.
  3. Impostors join the world directly, skipping the Beach: "Sandy" and "SahndyRULZ". The door
     waits for a vouch that never comes, then kicks them; the map never shows them.
  4. Mid-session, Sandy (still in BeachBlox) renames to "Sandcastle Sam". The /nick line appears in
     SandChat, the label over Sandy's character changes live, and Pebble still finds Sandy: in
     the world (by the label), in Pebble's Beach state ("Sandcastle Sam (was Sandy)") and at the
     Boardwalk table.
  5. An impostor tries the new name too. Refused the same way.

    python3 scripts/identity_scenario.py --tokens tokens.json --spectator-log server.log
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
from adapters.clawblox.front_door import beach_voucher  # noqa: E402
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
    ap.add_argument("--spectator-log", required=True)
    ap.add_argument("--door-wait", type=float, default=16.0, help="how long the world's door waits (+1)")
    a = ap.parse_args(argv)
    T = json.loads(Path(a.tokens).read_text())
    W, BE, Z = a.world, a.beach, a.zone
    checks: dict[str, bool] = {}

    def spectate():
        tok = spectator_token_from_log(a.spectator_log)
        return call("GET", f"{W}/spectate", headers={"X-Spectator-Token": tok})[1]

    def world_players():
        return [(p["name"], (p.get("attributes") or {}).get("BeachDoor"), (p.get("attributes") or {}).get("BeachName"))
                for p in spectate()["players"]]

    def labels():
        return sorted((e.get("attributes") or {}).get("PlayerName") for e in spectate().get("entities", [])
                      if (e.get("attributes") or {}).get("PlayerName"))

    def on_map(zid):
        z = [z for z in call("GET", f"{BE}/map", token=T["Coral"])[1]["zones"] if z["id"] == zid][0]
        return sorted(w["name"] for w in z["who"])

    print("1. Joining BeachBlox through the Beach")
    t0 = time.time()
    sandy = ClawbloxAdapter(W, name="Sandy", vouch=beach_voucher(BE, T["Sandy"], Z))
    sandy.join()
    pebble = ClawbloxAdapter(W, name="Pebble", vouch=beach_voucher(BE, T["Pebble"], Z))
    pebble.join()
    print(f"   Sandy and Pebble admitted in {time.time() - t0:.1f}s")
    st, coral = call("POST", f"{BE}/zones/{Z}/play", token=T["Coral"])
    print(f"   Coral (person): the Beach joined for Coral -> {st}; viewer link has session: {'session=' in str(coral)}")
    checks["person_joined_by_the_beach"] = st == 200 and "session=" in coral["viewer"]
    time.sleep(3)
    s, _ = call("POST", f"{W}/chat", {"content": "Hi from the sand, everyone."},
                headers={"X-Session": coral["session"]})
    msgs = call("GET", f"{W}/chat/messages?limit=20", headers={"X-Session": coral["session"]})[1]
    senders = [m.get("agent_name") or m.get("name") or m.get("sender") for m in (msgs.get("messages") or [])]
    print(f"   Coral chats in the world with the Beach's session: {s}; world chat senders {senders}")
    checks["person_chats_under_their_name"] = s == 200 and "Coral" in senders
    for _ in range(12):
        if on_map(Z) == ["Coral", "Pebble", "Sandy"]:
            break
        time.sleep(1)
    print(f"   map, BeachBlox: {on_map(Z)}")
    checks["all_three_on_the_map"] = on_map(Z) == ["Coral", "Pebble", "Sandy"]

    print("2. A game at the Boardwalk")
    tid = call("POST", f"{BE}/zones/boardwalk/tables", {"game": "checkers"}, token=T["Sandy"])[1]["id"]
    call("POST", f"{BE}/tables/{tid}/sit", {}, token=T["Pebble"])
    call("POST", f"{BE}/tables/{tid}/move", {"move": "c3-d4"}, token=T["Sandy"])
    call("POST", f"{BE}/tables/{tid}/move", {"move": "f6-g5"}, token=T["Pebble"])
    call("POST", f"{BE}/zones/sandchat/join", token=T["Pebble"])
    call("POST", f"{BE}/zones/sandchat/join", token=T["Coral"])
    print(f"   table {tid}: Sandy (Black) vs Pebble (White), 2 moves played")

    print("3. Impostors skip the Beach and join the world directly")
    for name in ("Sandy", "SahndyRULZ"):
        print(f"   POST {W}/join?name={name} -> {call('POST', f'{W}/join?name={name}')[0]}")
    time.sleep(1)
    print(f"   at once: {world_players()}")
    time.sleep(a.door_wait)
    after = world_players()
    print(f"   {a.door_wait:.0f}s later: {after}; labels {labels()}; map {on_map(Z)}")
    checks["impostor_and_unlisted_refused"] = (sorted(n for n, *_ in after) == ["Coral", "Pebble", "Sandy"]
                                              and on_map(Z) == ["Coral", "Pebble", "Sandy"])

    print("4. Sandy renames mid-session, while in BeachBlox")
    st, r = call("PUT", f"{BE}/me/name", {"name": "Sandcastle Sam"}, token=T["Sandy"])
    print(f"   PUT /me/name -> {st} {r}")
    time.sleep(4)
    lab = labels()
    print(f"   labels in the world now: {lab}; map {on_map(Z)}")
    checks["label_changes_live"] = "Sandcastle Sam" in lab and "Sandy" not in lab
    checks["map_shows_the_new_name"] = "Sandcastle Sam" in on_map(Z)
    nick = [m["line"] for m in call("GET", f"{BE}/zones/sandchat/messages", token=T["Coral"])[1]["messages"]
            if "now known as" in m["line"]]
    print(f"   SandChat: {nick}")
    checks["nick_line_in_sandchat"] = nick == ["- Sandy is now known as Sandcastle Sam"]
    seen = pebble.look()
    print(f"   Pebble looks around in the world: {'Sandcastle Sam' in seen}")
    checks["pebble_finds_them_in_the_world"] = "Sandcastle Sam" in seen
    stt = call("GET", f"{BE}/agent/turn?zone=sandchat", token=T["Pebble"])[1]["state"]["text"]
    here = [ln for ln in stt.splitlines() if ln.startswith("zones:")]
    tb = call("GET", f"{BE}/agent/turn?table={tid}", token=T["Pebble"])[1]
    seat = [ln for ln in tb["state"]["text"].splitlines() if ln.startswith("you are")][0]
    print(f"   Pebble's Boardwalk table state: {seat}")
    checks["table_shows_the_new_name_with_was"] = "Sandcastle Sam (was Sandy) is Black" in seat
    tables = call("GET", f"{BE}/zones/boardwalk/tables", token=T["Pebble"])[1]["tables"]
    checks["boardwalk_listing_new_name"] = any(s["player"] and s["player"]["name"] == "Sandcastle Sam"
                                               for t in tables if t["id"] == tid for s in t["seats"])
    del here

    print("5. An impostor tries the new name")
    print(f"   POST {W}/join?name=Sandcastle Sam -> {call('POST', f'{W}/join?name=Sandcastle%20Sam')[0]}")
    time.sleep(a.door_wait)
    after = world_players()
    print(f"   {a.door_wait:.0f}s later: {after}")
    checks["new_name_cannot_be_taken"] = sum(1 for n, *_ in after if n == "Sandcastle Sam") == 0 and len(after) == 3

    card = call("GET", f"{BE}/agent/beach-card", token=T["Pebble"])[1]
    print(f"\nBeach card: {card['tokens']} tokens ({card['token_method']})")
    for k, v in checks.items():
        print(f"  [{'x' if v else ' '}] {k}")
    print(f"{sum(checks.values())} of {len(checks)} checks passed")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
