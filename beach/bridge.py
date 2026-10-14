"""The game bridge: the Beach's local helper for one running Clawblox world.

Run one per world (BeachBlox, ClawBlox). It does two jobs, both on this machine only:

1. The front door. Every second it fetches from the Beach who it has vouched for (GET
   /zones/<zone>/door) and writes those claims into the world's own DataStore (the SQLite file
   Clawblox keeps in <world>/.clawblox/local-<port>.db). The world's BeachDoor script reads them
   there: it admits a join only when the Beach vouched for it under the name it joined with,
   labels the player with their current Beach name, and kicks everyone else (or, if the keeper
   allows guests, labels them "Guest N").
2. Presence. Every 10 s it reads the world's players (Clawblox's spectator endpoint) and reports
   them: vouched-for players by their join (the Beach knows whose it is), guests as guests.
   The Beach answers with each player's colours; the bridge writes them to static/tints.json
   for the beach renderer.

Both addresses must be on this machine. Proxy settings are ignored, so nothing leaves the
computer. Standard library only.

    python -m beach.bridge --world http://127.0.0.1:8100 --spectator-log server.log \\
        --beach http://127.0.0.1:8765 --zone beachblox --bridge-token-file ~/.beachblox-bridge \\
        --world-dir /path/to/running/world
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
from contextlib import closing
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
    """The names players joined a world under (from a Clawblox spectator observation)."""
    out = []
    for p in spectate.get("players") or []:
        n = p.get("name") if isinstance(p, dict) else None
        if isinstance(n, str) and n.strip():
            out.append(n.strip())
    return sorted(set(out))


def user_id_for(agent_id: str) -> int:
    """The UserId Clawblox gives a join: the low 53 bits of its agent_id (never 0)."""
    import uuid
    return (uuid.UUID(str(agent_id)).int & ((1 << 53) - 1)) or 1


def door_report(spectate: dict) -> list[dict]:
    """Who to report: players the world's door admitted (by their join), and guests. Players still
    waiting at the door, or refused, aren't reported."""
    out = []
    for p in spectate.get("players") or []:
        if not isinstance(p, dict):
            continue
        attrs = p.get("attributes") or {}
        state = attrs.get("BeachDoor")
        if state == "ok" and p.get("id"):
            out.append({"user_id": user_id_for(p["id"]), "joined_as": p.get("name", "")})
        elif state == "guest":
            out.append({"guest": str(attrs.get("BeachGuest") or "Guest")})
    return out


class WorldStore:
    """The world's own DataStore (Clawblox's local SQLite file), where the door reads claims."""

    STORE = "BeachDoor"

    def __init__(self, path: Path):
        self.path = Path(path)

    def _conn(self):
        return sqlite3.connect(str(self.path), timeout=5)

    def game_id(self) -> str | None:
        """This run's game id: the BeachDoor script writes a "world" row when the world starts."""
        if not self.path.exists():
            return None
        with closing(self._conn()) as c, c:
            row = c.execute("SELECT game_id FROM data_stores WHERE store_name = ? AND key = 'world'"
                            " ORDER BY updated_at DESC, rowid DESC LIMIT 1", (self.STORE,)).fetchone()
        return row[0] if row else None

    def write(self, game_id: str, items: dict[str, object]) -> None:
        with closing(self._conn()) as c, c:
            for key, value in items.items():
                c.execute("INSERT INTO data_stores (game_id, store_name, key, value) VALUES (?, ?, ?, ?)"
                          " ON CONFLICT (game_id, store_name, key) DO UPDATE SET value = excluded.value,"
                          " updated_at = datetime('now')",
                          (game_id, self.STORE, key, json.dumps(value, separators=(",", ":"))))

    def read(self, game_id: str, key: str):
        with closing(self._conn()) as c, c:
            row = c.execute("SELECT value FROM data_stores WHERE game_id = ? AND store_name = ? AND key = ?",
                            (game_id, self.STORE, key)).fetchone()
        return json.loads(row[0]) if row else None


def _http(method: str, url: str, headers: dict, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        **headers, **({"Content-Type": "application/json"} if data else {})})
    with _OPENER.open(req, timeout=TIMEOUT_S) as r:
        return json.loads(r.read() or b"{}")


class Bridge:
    """sync_door() = Beach claims into the world; step() = presence report. Transports are injectable."""

    def __init__(self, world: str, beach: str, zone: str, bridge_token: str,
                 spectator_token: Callable[[], str | None], world_dir: str | None = None,
                 http: Callable[..., dict] = _http, log: Callable[[str], None] = print,
                 store: "WorldStore | None" = None, tints: bool = True):
        self.world = world
        self.beach = beach
        self.zone = zone
        self.bridge_token = bridge_token
        self.spectator_token = spectator_token
        self.tints_path = Path(world_dir) / "static" / "tints.json" if (world_dir and tints) else None
        if store is None and world_dir:
            port = urllib.parse.urlparse(world).port or 80
            store = WorldStore(Path(world_dir) / ".clawblox" / f"local-{port}.db")
        self.store = store
        self.http = http
        self.log = log
        self.last_report: list | None = None
        self.last_tints: dict | None = None
        self.last_door: str | None = None
        self.world_ok = True

    def _auth(self) -> dict:
        return {"Authorization": f"Bearer {self.bridge_token}"}

    def sync_door(self) -> int | None:
        """Copy the Beach's claims into the world's DataStore. Returns how many joins it covers."""
        if not self.store:
            return None
        game_id = self.store.game_id()
        if not game_id:
            return None   # the world hasn't started its door yet
        try:
            door = self.http("GET", f"{self.beach}/zones/{self.zone}/door", self._auth())
        except (urllib.error.URLError, OSError, ValueError) as e:
            self.log(f"Beach not reachable for the door ({e}); the world keeps what it has")
            return None
        items: dict[str, object] = {"policy": {"guests": bool(door.get("guests"))}}
        for g in door.get("grants", []):
            items[f"grant:{int(g['user_id'])}"] = {"claims": [
                {"name": c["name"], "joined_as": c["joined_as"], "revoked": bool(c.get("revoked"))}
                for c in g.get("claims", [])]}
        sig = json.dumps([game_id, items], sort_keys=True)
        if sig != self.last_door:
            self.store.write(game_id, items)
            self.last_door = sig
        return len(items) - 1

    def read_world(self) -> dict | None:
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
        return obs

    def step(self) -> dict | None:
        obs = self.read_world()
        report = door_report(obs) if obs is not None else []
        body: dict = {"players": report, "world_url": self.world}
        tok = self.spectator_token()
        if tok and obs is not None:
            body["spectator_token"] = tok   # so the Beach can hand participants a working viewer link
        try:
            res = self.http("POST", f"{self.beach}/zones/{self.zone}/players", self._auth(), body)
        except (urllib.error.URLError, OSError, ValueError) as e:
            self.log(f"Beach not reachable ({e}); will retry")
            return None
        if report != self.last_report:
            self.log(f"playing: {res.get('names') or 'nobody'}")
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
    ap.add_argument("--world-dir", required=True,
                    help="the running world's directory (its DataStore holds the door's claims)")
    ap.add_argument("--no-tints", action="store_true", help="don't write static/tints.json (worlds that don't use it)")
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
    b = Bridge(world, beach, a.zone, token, spect, a.world_dir, tints=not a.no_tints,
               log=lambda m: print(time.strftime("%H:%M:%S"), m, flush=True))
    last_report = 0.0
    while True:
        b.sync_door()   # every second: joins wait on this
        if time.monotonic() - last_report >= max(2.0, a.every):
            b.step()
            last_report = time.monotonic()
        if a.once:
            return 0
        time.sleep(1.0)


if __name__ == "__main__":
    sys.exit(main())
