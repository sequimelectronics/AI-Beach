"""Watching a world, live (job 12, section 2).

Needs, on this machine: the Beach, and BeachBlox started with `python -m beach.world` (patched
Clawblox; for part 2 a copy of worlds/beach whose world.toml sets a short afk_timeout, e.g. 40, run
with --in-place). Participants Coral and Drift (people) and Sandy (an agent) must exist.

  1. ghosts: Drift and Sandy play, then leave, while a stream follower reads the world's live
     updates as a viewer does. With patches/clawblox-live-removals.patch their bodies go when they
     leave; without it the Players list empties but both bodies stay.
  2. idle: Coral watches (and keeps the watch up, as the page does); Sandy (adapter) and Drift
     play and do nothing. The world's idle limit removes both players; each is told; Sandy's next
     action says its character is gone, the next join says why, the one after makes one new
     character. Coral, who has no character, is never idled out and is told nothing.

    python3 scripts/watch_live.py --tokens tokens.json --world-log <run>/.ai-beach-world.log ghosts
    python3 scripts/watch_live.py --tokens tokens.json --world-log <run>/.ai-beach-world.log idle --wait 75
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from adapters.clawblox.adapter import CharacterGone, ClawbloxAdapter  # noqa: E402
from adapters.clawblox.front_door import BeachSaid, beach_joiner, beach_leaver  # noqa: E402

BEACH = "http://127.0.0.1:8765"
WORLD = "http://127.0.0.1:8100"
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def call(tok: str, method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(BEACH + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    try:
        with _OPENER.open(req, timeout=30) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return {"status": e.code, **json.loads(e.read() or b"{}")}


def ghosts(T: dict, log: str, seconds: int = 40) -> dict:
    tok = re.findall(r"spectator_token=([A-Za-z0-9_\-]+)", Path(log).read_text(encoding="utf-8", errors="replace"))[-1]
    follower = subprocess.Popen(["node", str(ROOT / "scripts" / "viewer_stream.cjs"),
                                 f"ws://127.0.0.1:8100/spectate/ws?spectator_token={tok}", str(seconds)],
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    time.sleep(2)
    for n in ("Drift", "Sandy"):
        call(T[n], "POST", "/zones/beachblox/play", {"again": True})
    time.sleep(12)
    for n in ("Drift", "Sandy"):
        call(T[n], "DELETE", "/zones/beachblox/play")
    out, _ = follower.communicate()
    seen = [json.loads(line) for line in out.splitlines() if line.startswith("{")]
    for s in seen:
        if s["t"] % 5 == 0 or s is seen[-1]:
            print(s)
    last = seen[-1]
    return {"players_at_end": last["players"], "bodies_at_end": last["bodies"], "ghosts": bool(last["bodies"])}


def idle(T: dict, log: str, wait: float) -> dict:
    stop = threading.Event()

    def keep_watching():
        while not stop.is_set():
            call(T["Coral"], "POST", "/zones/beachblox/watch")
            stop.wait(30)
    threading.Thread(target=keep_watching, daemon=True).start()
    call(T["Drift"], "POST", "/zones/beachblox/play", {"again": True})
    a = ClawbloxAdapter(WORLD, name="Sandy", join_via=beach_joiner(BEACH, T["Sandy"], "beachblox"),
                        leave_via=beach_leaver(BEACH, T["Sandy"], "beachblox"))
    try:
        a.look()
    except BeachSaid as e:       # an earlier run's removal, said once
        print("first join said:", e)
        a.look()
    print(f"Sandy and Drift are in the world; Coral is watching. Waiting {wait:.0f} s...")
    time.sleep(wait)
    out: dict = {}
    out["sandy_turn_private"] = [ln for ln in call(T["Sandy"], "GET", "/agent/turn?zone=sandchat")["state"]["text"].splitlines()
                                 if ln.startswith("private:")]
    out["drift_events"] = [e["text"] for e in call(T["Drift"], "GET", "/me/events")["events"]]
    try:
        a.look()
        out["sandy_next_action"] = "worked (not removed?)"
    except CharacterGone as e:
        out["sandy_next_action"] = str(e)
    try:
        a.look()
        out["sandy_next_join"] = "made a new character without a word"
    except BeachSaid as e:
        out["sandy_next_join"] = f"{e} (removed={e.removed})"
    out["sandy_after"] = a.look().splitlines()[0]
    out["coral"] = call(T["Coral"], "GET", "/zones/beachblox/play")
    out["coral_events"] = call(T["Coral"], "GET", "/me/events")["events"]
    out["world_log"] = [ln for ln in Path(log).read_text(encoding="utf-8", errors="replace").splitlines() if "[AFK]" in ln or "watching from" in ln][-6:]
    stop.set()
    a.leave()
    call(T["Coral"], "DELETE", "/zones/beachblox/watch")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tokens", required=True)
    ap.add_argument("--world-log", required=True)
    ap.add_argument("what", choices=("ghosts", "idle"))
    ap.add_argument("--wait", type=float, default=75, help="idle: seconds to wait (the world's idle limit + ~30)")
    a = ap.parse_args(argv)
    T = json.loads(Path(a.tokens).read_text(encoding="utf-8"))
    res = ghosts(T, a.world_log) if a.what == "ghosts" else idle(T, a.world_log, a.wait)
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
