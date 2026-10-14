#!/usr/bin/env python3
"""Minimal plain-HTTP probe client for a locally running Clawblox world.

Research tool for AI-Beach: can a small local model play in a Clawblox world
using only HTTP calls as tools? This script plays the part of that model's
tool layer. It uses only the Python standard library.

It joins, reads observations, performs each of the six mesa-island actions
(MoveTo, Jump, Stop, Pickup, Place, Throw), sends and reads chat, and records
the byte size and an approximate token count of every /observe and /input
response.

Token counts are APPROXIMATE: characters / 4, the usual rule of thumb for
English-ish text with BPE tokenizers. JSON full of numbers usually tokenizes
worse than that (digits, minus signs and punctuation often become their own
tokens), so treat chars/4 as an optimistic lower-ish estimate, not a
measurement for any particular model.

Usage (server started separately with `clawblox run <world> --port 8080`):

    python3 clawblox_probe.py session --base http://127.0.0.1:8080 --out run.json
    python3 clawblox_probe.py multi   --base http://127.0.0.1:8081 --out multi.json

Never point this at a server you do not run yourself.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ACTION_TYPES = ("MoveTo", "Jump", "Stop", "Pickup", "Place", "Throw")


def approx_tokens(n_chars: int) -> int:
    """Approximate token count: chars / 4 (see module docstring)."""
    return math.ceil(n_chars / 4)


class Client:
    """One player session. Every response body is measured."""

    def __init__(self, base: str, name: str, timeout: float = 15.0):
        self.base = base.rstrip("/")
        self.name = name
        self.timeout = timeout
        self.session: str | None = None
        self.agent_id: str | None = None
        self.log: list[dict] = []

    def _request(self, method: str, path: str, body: dict | None = None,
                 kind: str | None = None, note: str = ""):
        url = self.base + path
        data = None
        headers = {}
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if self.session:
            headers["X-Session"] = self.session
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        started = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                status = resp.status
        except urllib.error.HTTPError as err:
            raw = err.read()
            status = err.code
        elapsed_ms = round((time.monotonic() - started) * 1000, 1)
        text = raw.decode("utf-8", errors="replace")
        entry = {
            "kind": kind or path.split("?")[0],
            "method": method,
            "path": path,
            "status": status,
            "bytes": len(raw),
            "chars": len(text),
            "approx_tokens": approx_tokens(len(text)),
            "ms": elapsed_ms,
            "note": note,
        }
        parsed = None
        try:
            parsed = json.loads(text) if text else None
        except json.JSONDecodeError:
            pass
        if isinstance(parsed, dict):
            entry["entity_count"] = len(parsed.get("world", {}).get("entities", []) or [])
            entry["tick"] = parsed.get("tick")
            attrs = (parsed.get("player") or {}).get("attributes") or {}
            if "LastActionResult" in attrs:
                entry["last_action_result"] = attrs["LastActionResult"]
        self.log.append(entry)
        if status >= 400:
            print(f"[{self.name}] {method} {path} -> {status}: {text[:200]}", file=sys.stderr)
        return status, parsed, text

    # --- the whole agent-facing protocol -------------------------------------

    def api_md(self) -> str:
        _, _, text = self._request("GET", "/api.md", kind="api.md")
        return text

    def join(self) -> dict:
        q = urllib.parse.urlencode({"name": self.name})
        status, body, text = self._request("POST", f"/join?{q}", kind="join")
        if status != 200 or not body:
            raise RuntimeError(f"join failed: {status} {text[:200]}")
        self.session = body["session"]
        self.agent_id = body["agent_id"]
        return body

    def observe(self, note: str = "") -> dict:
        _, body, _ = self._request("GET", "/observe", kind="observe", note=note)
        return body or {}

    def act(self, action: str, data: dict | None = None, note: str = "") -> dict:
        _, body, _ = self._request("POST", "/input", {"type": action, "data": data or {}},
                                   kind="input", note=note or action)
        return body or {}

    def chat(self, content: str) -> dict:
        _, body, _ = self._request("POST", "/chat", {"content": content}, kind="chat")
        return body or {}

    def chat_messages(self, after: str | None = None, limit: int = 20) -> list[dict]:
        params = {"limit": limit}
        if after:
            params["after"] = after
        q = urllib.parse.urlencode(params)
        _, body, _ = self._request("GET", f"/chat/messages?{q}", kind="chat_messages")
        return (body or {}).get("messages", [])


# --- helpers an agent harness would need ------------------------------------

def my_pos(obs: dict) -> list[float]:
    return (obs.get("player") or {}).get("position") or [0.0, 0.0, 0.0]


def dist(a, b) -> float:
    return math.dist(a, b)


def pickups(obs: dict) -> list[dict]:
    ents = (obs.get("world") or {}).get("entities") or []
    return [e for e in ents if (e.get("attributes") or {}).get("IsPickupObject")]


def nearest_pickup(obs: dict, kind: str | None = None) -> dict | None:
    me = my_pos(obs)
    cands = [e for e in pickups(obs)
             if kind is None or (e.get("attributes") or {}).get("RenderRole") == kind]
    return min(cands, key=lambda e: dist(me, e["position"]), default=None)


def walk_to(c: Client, target, tolerance=2.5, max_polls=12, poll_s=0.5) -> dict:
    """MoveTo, then poll /observe until close (horizontal) or out of polls."""
    obs = c.act("MoveTo", {"position": list(target)}, note="MoveTo")
    for _ in range(max_polls):
        p = my_pos(obs)
        if math.hypot(p[0] - target[0], p[2] - target[2]) <= tolerance:
            break
        time.sleep(poll_s)
        obs = c.observe(note="poll during MoveTo")
    return obs


# --- scripted session ---------------------------------------------------------

def run_session(c: Client, steps_target: int = 50) -> dict:
    results: dict = {"action_results": {}}
    api = c.api_md()
    results["api_md_bytes"] = len(api.encode())
    c.join()
    obs = c.observe(note="first observation")
    results["first_observation"] = obs

    # Pickup / Place / Throw on a block from the pile.
    block = nearest_pickup(obs, "PickupObject")
    if block:
        obs = walk_to(c, block["position"], tolerance=2.0)
        block = nearest_pickup(obs, "PickupObject") or block
        obs = c.act("Pickup", {"position": block["position"]})
        results["action_results"]["Pickup"] = obs.get("player", {}).get("attributes", {}).get("LastActionResult")
        p = my_pos(obs)
        place_at = [p[0] + 3.0, p[1], p[2]]
        obs = c.act("Place", {"position": place_at})
        results["action_results"]["Place"] = obs.get("player", {}).get("attributes", {}).get("LastActionResult")
        time.sleep(0.6)
        obs = c.observe(note="after Place")
        block = nearest_pickup(obs, "PickupObject")
        if block:
            obs = walk_to(c, block["position"], tolerance=2.0)
            block = nearest_pickup(obs, "PickupObject") or block
            obs = c.act("Pickup", {"position": block["position"]}, note="Pickup (2)")
        obs = c.act("Throw", {"direction": [1, 0.3, 0], "speed": 10})
        results["action_results"]["Throw"] = obs.get("player", {}).get("attributes", {}).get("LastActionResult")

    obs = c.act("Jump")
    results["action_results"]["Jump"] = "no LastActionResult change (movement action)"
    obs = c.act("MoveTo", {"position": [-20, 2, 20]}, note="MoveTo then Stop")
    time.sleep(0.4)
    before = my_pos(c.observe(note="before Stop"))
    obs = c.act("Stop")
    time.sleep(0.6)
    after = my_pos(c.observe(note="after Stop"))
    results["action_results"]["Stop"] = {"moved_after_stop": round(dist(before, after), 2)}
    results["action_results"]["MoveTo"] = {"position_after": my_pos(obs)}

    # The rock: pick it up and throw it hard enough to spawn cubes.
    obs = c.observe(note="look for rock")
    rock = nearest_pickup(obs, "Rock")
    if rock:
        obs = walk_to(c, rock["position"], tolerance=2.5)
        rock = nearest_pickup(obs, "Rock") or rock
        obs = c.act("Pickup", {"position": rock["position"]}, note="Pickup rock")
        results["action_results"]["PickupRock"] = obs.get("player", {}).get("attributes", {}).get("LastActionResult")
        before_n = len(pickups(obs))
        obs = c.act("Throw", {"direction": [0, -0.2, -1], "speed": 10}, note="Throw rock")
        results["action_results"]["ThrowRock"] = obs.get("player", {}).get("attributes", {}).get("LastActionResult")
        time.sleep(2.0)
        obs = c.observe(note="after rock throw")
        results["pickups_before_after_rock_throw"] = [before_n, len(pickups(obs))]

    # Chat round trip.
    sent = c.chat(f"hello from {c.name}")
    msgs = c.chat_messages()
    results["chat_sent"] = sent
    results["chat_read_back"] = [m.get("content") for m in msgs]

    # Pad out to ~steps_target observe/input calls with a wander loop.
    waypoints = [[0, 2, 0], [10, 2, -10], [-10, 2, -5], [5, 2, 10]]
    i = 0
    while sum(1 for e in c.log if e["kind"] in ("observe", "input")) < steps_target:
        wp = waypoints[i % len(waypoints)]
        c.act("MoveTo", {"position": wp}, note="wander")
        time.sleep(0.3)
        c.observe(note="wander")
        i += 1
    return results


def summarize(log: list[dict], kinds=("observe", "input")) -> dict:
    out = {}
    for kind in kinds:
        rows = [e for e in log if e["kind"] == kind and e["status"] == 200]
        if not rows:
            continue
        b = [e["bytes"] for e in rows]
        t = [e["approx_tokens"] for e in rows]
        n = [e.get("entity_count", 0) for e in rows]
        out[kind] = {
            "n": len(rows),
            "bytes": {"min": min(b), "median": statistics.median(b), "max": max(b)},
            "approx_tokens_chars_div_4": {"min": min(t), "median": statistics.median(t), "max": max(t)},
            "entities": {"min": min(n), "median": statistics.median(n), "max": max(n)},
        }
    return out


def run_multi(base: str) -> dict:
    a, b = Client(base, "Alice"), Client(base, "Bob")
    a.join()
    b.join()
    time.sleep(0.5)
    oa, ob = a.observe(), b.observe()

    def others(o):
        return [{"name": p.get("name"), "id": p.get("id"), "distance": p.get("distance")}
                for p in o.get("other_players", [])]

    res = {
        "alice_id": a.agent_id, "bob_id": b.agent_id,
        "alice_sees": others(oa), "bob_sees": others(ob),
        # Does each character also show up as a world entity?
        "alice_entity_names": sorted({e["name"] for e in oa.get("world", {}).get("entities", [])}),
    }
    a.chat("hi Bob, it's Alice")
    b.chat("hi Alice, Bob here")
    res["alice_reads"] = [(m["agent_name"], m["content"]) for m in a.chat_messages()]
    res["bob_reads"] = [(m["agent_name"], m["content"]) for m in b.chat_messages()]

    # Polling with `after`: created_at has 1-second resolution and the filter is
    # strictly-greater, so a cursor taken from the last message can hide a
    # message sent later in the same second.
    first = a.chat("cursor test 1")
    cursor = first.get("created_at")
    b.chat("cursor test 2 (same second?)")
    seen = [m["content"] for m in a.chat_messages(after=cursor)]
    res["after_cursor_test"] = {"cursor": cursor, "messages_after_cursor": seen,
                                "missed_same_second_message": "cursor test 2 (same second?)" not in seen}
    res["chat_message_example"] = a.chat_messages(limit=1)
    res["sizes"] = summarize(a.log + b.log, kinds=("observe", "chat_messages"))
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("mode", choices=["session", "multi", "observe-once"])
    ap.add_argument("--base", default="http://127.0.0.1:8080")
    ap.add_argument("--name", default="Probe")
    ap.add_argument("--steps", type=int, default=50)
    ap.add_argument("--out", help="write JSON results here")
    args = ap.parse_args()

    if args.mode == "session":
        c = Client(args.base, args.name)
        res = run_session(c, args.steps)
        res["summary"] = summarize(c.log)
        res["log"] = c.log
    elif args.mode == "multi":
        res = run_multi(args.base)
    else:
        c = Client(args.base, args.name)
        c.join()
        time.sleep(0.3)
        obs = c.observe()
        res = {"observation": obs, "log": c.log}

    text = json.dumps(res, indent=2)
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(text)
    summary = res.get("summary") or res.get("sizes") or res.get("log")
    print(json.dumps(summary, indent=2)[:4000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
