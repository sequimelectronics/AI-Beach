"""The BeachBlox bridge: tells the Beach who is playing on the sand.

A small local process. Every few seconds it reads the running beach world's
player list (Clawblox's spectator endpoint, on this machine) and reports the
names to the Beach's game zone (POST /zones/<zone>/players, with that zone's
bridge token). The Beach matches in-game names to participants, and answers
with each matched player's colours; if you give the bridge the world's
directory, it writes those to static/tints.json, which the beach renderer
reads to tint each character with its participant's look.

Both addresses must be on this machine. Proxy settings are ignored, so
nothing leaves the computer. Standard library only.

    python -m beach.bridge --world http://127.0.0.1:8100 --spectator-log server.log \\
        --beach http://127.0.0.1:8765 --zone beachblox --bridge-token-file ~/.beachblox-bridge \\
        --world-dir /path/to/running/world
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

from .hooks import _is_local

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
TIMEOUT_S = 5


def require_local(url: str, what: str) -> str:
    u = urllib.parse.urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname or not _is_local(u.hostname):
        raise SystemExit(f"{what} must be an address on this machine (127.0.0.1, ::1 or localhost): {url}")
    return url.rstrip("/")


def spectator_token_from_log(path: str) -> str | None:
    """Clawblox prints 'spectator_token=...' when it starts; take the latest one."""
    try:
        text = Path(path).read_text(errors="replace")
    except OSError:
        return None
    found = re.findall(r"spectator_token=([A-Za-z0-9_\-]+)", text)
    return found[-1] if found else None


def player_names(spectate: dict) -> list[str]:
    """In-game names from a Clawblox spectator observation."""
    out = []
    for p in spectate.get("players") or []:
        n = p.get("name") if isinstance(p, dict) else None
        if isinstance(n, str) and n.strip():
            out.append(n.strip())
    return sorted(set(out))


def _http(method: str, url: str, headers: dict, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        **headers, **({"Content-Type": "application/json"} if data else {})})
    with _OPENER.open(req, timeout=TIMEOUT_S) as r:
        return json.loads(r.read() or b"{}")


class Bridge:
    """One step = read the world, report to the Beach, write tints. Transports are injectable for tests."""

    def __init__(self, world: str, beach: str, zone: str, bridge_token: str,
                 spectator_token: Callable[[], str | None], world_dir: str | None = None,
                 http: Callable[..., dict] = _http, log: Callable[[str], None] = print):
        self.world = world
        self.beach = beach
        self.zone = zone
        self.bridge_token = bridge_token
        self.spectator_token = spectator_token
        self.tints_path = Path(world_dir) / "static" / "tints.json" if world_dir else None
        self.http = http
        self.log = log
        self.last_report: list[str] | None = None
        self.last_tints: dict | None = None
        self.world_ok = True

    def read_world(self) -> list[str] | None:
        tok = self.spectator_token() or ""
        try:
            obs = self.http("GET", f"{self.world}/spectate", {"X-Spectator-Token": tok})
        except (urllib.error.URLError, OSError, ValueError) as e:
            if self.world_ok:
                self.log(f"world not reachable ({e}); reporting nobody until it's back")
            self.world_ok = False
            return None
        if not self.world_ok:
            self.log("world is back")
        self.world_ok = True
        return player_names(obs)

    def step(self) -> dict | None:
        names = self.read_world()
        report = names if names is not None else []
        try:
            res = self.http("POST", f"{self.beach}/zones/{self.zone}/players",
                            {"Authorization": f"Bearer {self.bridge_token}"}, {"players": report})
        except (urllib.error.URLError, OSError, ValueError) as e:
            self.log(f"Beach not reachable ({e}); will retry")
            return None
        if report != self.last_report:
            self.log(f"playing: {', '.join(report) if report else 'nobody'}")
            self.last_report = report
        self.write_tints(res.get("looks") or {})
        return res

    def write_tints(self, looks: dict) -> None:
        if not self.tints_path or looks == self.last_tints:
            return
        self.tints_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.tints_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"players": looks}, indent=0, sort_keys=True))
        os.replace(tmp, self.tints_path)
        self.last_tints = looks


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m beach.bridge", description=__doc__.split("\n\n")[0])
    ap.add_argument("--world", default="http://127.0.0.1:8100", help="the running Clawblox world (this machine)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--spectator-token", help="Clawblox's spectator token")
    g.add_argument("--spectator-log", help="Clawblox's server log; the token is read from it (re-read on restarts)")
    ap.add_argument("--beach", default="http://127.0.0.1:8765", help="the Beach (this machine)")
    ap.add_argument("--zone", default="beachblox", help="the Beach game zone id")
    ap.add_argument("--bridge-token-file", help="file holding the zone's bridge token (or set BEACH_BRIDGE_TOKEN)")
    ap.add_argument("--world-dir", help="the running world's directory, to write static/tints.json")
    ap.add_argument("--every", type=float, default=10.0, help="seconds between reports (default 10)")
    ap.add_argument("--once", action="store_true", help="report once and exit")
    a = ap.parse_args(argv)

    world = require_local(a.world, "--world")
    beach = require_local(a.beach, "--beach")
    token = os.environ.get("BEACH_BRIDGE_TOKEN")
    if a.bridge_token_file:
        token = Path(a.bridge_token_file).expanduser().read_text().strip()
    if not token:
        print("needs the zone's bridge token: --bridge-token-file or BEACH_BRIDGE_TOKEN", file=sys.stderr)
        return 2
    if a.spectator_log:
        spect = lambda: spectator_token_from_log(a.spectator_log)  # noqa: E731
    else:
        spect = lambda: a.spectator_token or os.environ.get("CLAWBLOX_SPECTATOR_TOKEN")  # noqa: E731
    b = Bridge(world, beach, a.zone, token, spect, a.world_dir,
               log=lambda m: print(time.strftime("%H:%M:%S"), m, flush=True))
    while True:
        b.step()
        if a.once:
            return 0
        time.sleep(max(2.0, a.every))


if __name__ == "__main__":
    sys.exit(main())
