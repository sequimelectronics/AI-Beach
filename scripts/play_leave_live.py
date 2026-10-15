# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""One character per person per world, live (job 10, item 2).

Needs, on this machine: the Beach, and a game world started with `python -m beach.world` (BeachDoor
script, join key, bridge). Participants Coral (a person) and Sandy (an agent) must exist; pass their
tokens. What happens:

  1. Coral presses Play twice, then from three tabs at once: one character, the same session.
  2. The map's button says Leave.
  3. Sandy, an agent, joins through its adapter twice: one character.
  4. Coral presses Leave: the map drops her at once, and the world's door removes her character
     within a few seconds; her old session no longer works. The button says Play.
  5. Coral plays again: a new character, still just one.

    python3 scripts/play_leave_live.py --tokens tokens.json --spectator-log <run>/.ai-beach-world.log
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from adapters.clawblox.adapter import ClawbloxAdapter  # noqa: E402
from adapters.clawblox.front_door import beach_joiner  # noqa: E402
from beach.bridge import spectator_token_from_log  # noqa: E402
from beach.front_door import session_alive  # noqa: E402

_OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def call(method, url, token=None, headers=None):
    h = dict(headers or {})
    if token:
        h["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, method=method, headers=h, data=b"" if method in ("POST", "DELETE") else None)
    try:
        with _OP.open(req, timeout=20) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--beach", default="http://127.0.0.1:8765")
    ap.add_argument("--world", default="http://127.0.0.1:8100")
    ap.add_argument("--zone", default="beachblox")
    ap.add_argument("--tokens", required=True)
    ap.add_argument("--spectator-log", required=True)
    a = ap.parse_args(argv)
    T = json.loads(Path(a.tokens).read_text())
    BE, W, Z = a.beach, a.world, a.zone
    checks = {}

    def in_world(name):
        tok = spectator_token_from_log(a.spectator_log)
        st, d = call("GET", f"{W}/spectate", headers={"X-Spectator-Token": tok})
        return sum(1 for p in d.get("players", []) if p.get("name") == name)

    def button():
        z = [z for z in call("GET", f"{BE}/map", T["Coral"])[1]["zones"] if z["id"] == Z][0]
        return ("Leave" if z["playing"] else "Play"), [w["name"] for w in z["who"]]

    print(f"0. The button before anything: {button()[0]}")
    print("1. Coral presses Play twice, then from three tabs at once")
    s1 = call("POST", f"{BE}/zones/{Z}/play", T["Coral"])[1]
    s2 = call("POST", f"{BE}/zones/{Z}/play", T["Coral"])[1]
    tabs = []
    ts = [threading.Thread(target=lambda: tabs.append(call("POST", f"{BE}/zones/{Z}/play", T["Coral"])[1]))
          for _ in range(3)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    sessions = {s1["session"], s2["session"], *(t["session"] for t in tabs)}
    time.sleep(2)
    n = in_world("Coral")
    print(f"   first: existing={s1['existing']}; then existing={s2['existing']}, "
          f"{[t['existing'] for t in tabs]}; distinct sessions: {len(sessions)}; Corals in the world: {n}")
    checks["one character, one session"] = len(sessions) == 1 and n == 1 and s2["existing"]

    time.sleep(1)
    b = button()
    print(f"2. The map's button: {b[0]}")
    checks["button says Leave"] = b[0] == "Leave"

    print("3. Sandy (an agent) joins through its adapter twice")
    sandy1 = ClawbloxAdapter(W, name="Sandy", join_via=beach_joiner(BE, T["Sandy"], Z))
    sandy1.join()
    sandy2 = ClawbloxAdapter(W, name="Sandy", join_via=beach_joiner(BE, T["Sandy"], Z))
    sandy2.join()
    time.sleep(1)
    n = in_world("Sandy")
    print(f"   same session: {sandy1.session == sandy2.session}; Sandys in the world: {n}")
    checks["agents too"] = sandy1.session == sandy2.session and n == 1

    print("4. Coral presses Leave")
    t0 = time.monotonic()
    st, r = call("DELETE", f"{BE}/zones/{Z}/play", T["Coral"])
    b = button()
    print(f"   DELETE: {st} {r}; at once the button says {b[0]} and the map shows {b[1]}")
    gone_after = None
    while time.monotonic() - t0 < 10:
        if in_world("Coral") == 0:
            gone_after = time.monotonic() - t0
            break
        time.sleep(0.25)
    alive = session_alive(W, s1["session"])
    print(f"   her character left the world after {gone_after and round(gone_after, 1)} s; "
          f"her old session still works: {alive}")
    checks["leave: map at once, world within seconds"] = (b[0] == "Play" and "Coral" not in b[1]
                                                         and gone_after is not None and not alive)

    print("5. Coral plays again")
    s3 = call("POST", f"{BE}/zones/{Z}/play", T["Coral"])[1]
    time.sleep(2)
    n = in_world("Coral")
    print(f"   existing={s3['existing']}; a new session: {s3['session'] != s1['session']}; Corals in the world: {n}; "
          f"button: {button()[0]}")
    checks["play again: a new character, one"] = (not s3["existing"]) and s3["session"] != s1["session"] and n == 1

    print()
    for k, v in checks.items():
        print(f"   {'PASS' if v else 'FAIL'}  {k}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
