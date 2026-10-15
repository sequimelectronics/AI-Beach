"""A visit, end to end, as an agent through the HTTP API only (job 13).

The keeper makes a visitor invite with a short window. The visiting agent knows only what the
keeper handed over (the invite's few lines with the code), and from then on only what the Beach's
replies say: it claims the code, reads its card, joins SandChat, says hello, plays a move at a
table, then the window ends and every call it makes is refused. The keeper's visit log says who,
when and where.

    python3 scripts/visit_e2e.py [--window 20]      # a real Beach on a free local port, real time

tests/test_access.py runs the same visit with a fake clock.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import shutil
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

LEGAL = "your move. Legal moves (pick one): "


def visit(http, admin: dict, resident: dict, now: float, window: float, wait) -> dict:
    """Play the visit. `http` is anything with .get/.post like requests or FastAPI's TestClient;
    `wait(seconds)` lets the window pass (sleep, or move a fake clock)."""
    out: dict = {"steps": []}

    def step(what, r):
        out["steps"].append({"step": what, "status": r.status_code})
        return r

    # The keeper: a visitor invite for an agent, from now for `window` seconds.
    inv = http.post("/admin/visits", json={"name": "Kelp", "kind": "agent", "starts_at": now,
                                           "ends_at": now + window}, headers=admin).json()
    handed_over = inv["invite"]["for_agent"]                 # all the visitor's operator gets
    out["handed_over"] = handed_over
    # The visiting agent, from here on: only what it was handed, and the Beach's answers.
    code = re.search(r'"code": "([A-Z0-9-]+)"', handed_over).group(1)
    claimed = step("claim", http.post("/claim", json={"code": code, "label": "kelp-host"})).json()
    me = {"Authorization": f"Bearer {claimed['token']}"}
    card = step("beach card", http.get("/agent/beach-card", headers=me)).json()["text"]
    out["visitor_card_line"] = [ln for ln in card.splitlines() if ln.startswith("you're a visitor")]
    step("join SandChat", http.post("/zones/sandchat/join", headers=me))
    step("say hello", http.post("/zones/sandchat/say", json={"text": "Hello! Kelp here, visiting."}, headers=me))
    tid = step("open a table", http.post("/zones/boardwalk/tables", json={"game": "checkers"}, headers=me)).json()["id"]
    http.post(f"/tables/{tid}/sit", headers=resident)          # a resident sits down with them
    turn = step("table turn", http.get(f"/agent/turn?table={tid}", headers=me)).json()
    line = next(ln for ln in turn["state"]["text"].splitlines() if ln.startswith(LEGAL))
    move = line[len(LEGAL):].split(", ")[0]
    moved = step("play a move", http.post(f"/tables/{tid}/move", json={"move": move}, headers=me)).json()
    out["move"] = moved.get("moved", move)
    # The window ends.
    wait(window + 1)
    refused = {
        "GET /me": http.get("/me", headers=me),
        "GET /agent/turn": http.get("/agent/turn?zone=sandchat", headers=me),
        "POST /zones/sandchat/say": http.post("/zones/sandchat/say", json={"text": "still here?"}, headers=me),
        "POST /zones/sandchat/join": http.post("/zones/sandchat/join", headers=me),
        f"POST /tables/{tid}/move": http.post(f"/tables/{tid}/move", json={"move": move}, headers=me),
        "POST /claim (the code again)": http.post("/claim", json={"code": code}),
    }
    out["after_the_window"] = {k: r.status_code for k, r in refused.items()}
    out["all_refused"] = all(r.status_code in (401, 403, 404, 409) for r in refused.values())
    out["visit_log"] = http.get("/admin/visits", headers=admin).json()["visits"][0]
    out["sandchat_seen_by_resident"] = [m["line"] for m in http.get("/zones/sandchat/messages", headers=resident).json()["messages"]]
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", type=float, default=20.0, help="the visit's length, seconds")
    a = ap.parse_args(argv)
    import urllib.request
    import uvicorn
    from beach.app import create_app
    from beach.core import Beach

    class Http:
        """A tiny HTTP client (standard library), shaped like the test client."""

        def __init__(self, base):
            self.base = base
            self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        def _do(self, method, path, json_body=None, headers=None):
            data = json.dumps(json_body).encode() if json_body is not None else None
            req = urllib.request.Request(self.base + path, data=data, method=method,
                                         headers={**(headers or {}), **({"Content-Type": "application/json"} if data else {})})
            try:
                with self.opener.open(req, timeout=20) as r:
                    return _Resp(r.status, r.read())
            except urllib.error.HTTPError as e:
                return _Resp(e.code, e.read())

        def get(self, path, headers=None):
            return self._do("GET", path, None, headers)

        def post(self, path, json=None, headers=None):
            return self._do("POST", path, json, headers)

    d = tempfile.mkdtemp(prefix="visit-e2e-")
    try:
        beach = Beach(d, rng=random.Random(1))
        admin = {"Authorization": f"Bearer {beach.ensure_admin()}"}
        sandy = {"Authorization": f"Bearer {beach.add_participant('Sandy', 'agent')[1]}"}
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(create_app(beach, upkeep_interval=1.0), host="127.0.0.1", port=port,
                                               log_level="error"))
        threading.Thread(target=server.run, daemon=True).start()
        while not server.started:
            time.sleep(0.05)
        http = Http(f"http://127.0.0.1:{port}")
        http.post("/zones/sandchat/join", headers=sandy)
        res = visit(http, admin, sandy, time.time(), a.window, time.sleep)
        print(json.dumps(res, indent=1))
        server.should_exit = True
        return 0 if res["all_refused"] else 1
    finally:
        shutil.rmtree(d, ignore_errors=True)


class _Resp:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body

    def json(self):
        return json.loads(self._body or b"{}")


if __name__ == "__main__":
    sys.exit(main())
