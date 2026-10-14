"""Start a game world and its bridge together, and stop them together.

    python -m beach.world --world worlds/beach --zone beachblox --port 8100 \\
        --bridge-token-file ~/.beachblox-bridge

- Runs the world with Clawblox (`clawblox run`) from a fresh COPY of the world folder (Clawblox
  writes build output and its DataStore into the folder it runs; the repo stays clean). Use
  --in-place for a folder that is already a runnable copy (e.g. the one scripts/clawblox_world.py
  assembles for ClawBlox).
- Gives the world a fresh random join key each run (CLAWBLOX_JOIN_KEY): with
  patches/clawblox-join-key.patch, the world then refuses every join that doesn't come through
  the Beach. The bridge hands the key to the Beach, which makes joins on participants' behalf.
- Runs the bridge (python -m beach.bridge) in this same process.
- Ctrl+C (or SIGTERM) stops both; if the world stops on its own, the bridge stops too, and the
  Beach is told nobody is playing.
"""

from __future__ import annotations

import argparse
import os
import secrets
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from .bridge import Bridge, require_local, run_loop, spectator_token_from_log

ROOT = Path(__file__).resolve().parents[1]
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def default_run_dir(zone: str) -> Path:
    data = os.environ.get("AI_BEACH_DATA")
    base = Path(data).expanduser() if data else Path.home() / ".local" / "share" / "ai-beach"
    return base / "worlds" / zone


def prepare(world: Path, run_dir: Path, in_place: bool) -> Path:
    """The folder Clawblox will run: the world itself (--in-place) or a fresh copy of it."""
    world = world.expanduser().resolve()
    if not (world / "world.toml").is_file():
        raise SystemExit(f"no world.toml in {world}")
    if in_place:
        if ROOT in world.parents and (ROOT / "_local") not in world.parents:
            raise SystemExit("that's the repository's own world folder: run a copy (leave out --in-place)")
        return world
    run_dir = run_dir.expanduser().resolve()
    if ROOT in run_dir.parents and (ROOT / "_local") not in run_dir.parents:
        raise SystemExit("put the run folder outside the repository (or under _local/)")
    if run_dir.exists():
        if not (run_dir / ".ai-beach-run").exists():
            raise SystemExit(f"{run_dir} exists and wasn't made by this command; choose another --run-dir")
        shutil.rmtree(run_dir)
    shutil.copytree(world, run_dir, ignore=shutil.ignore_patterns("dist", ".build.lock", ".clawblox", "tints.json"))
    (run_dir / ".ai-beach-run").write_text("A running copy made by `python -m beach.world`; safe to delete.\n")
    return run_dir


def wait_up(url: str, proc: subprocess.Popen, timeout: float) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if proc.poll() is not None:
            return False
        try:
            with _OPENER.open(f"{url}/api.md", timeout=2):
                return True
        except OSError:
            time.sleep(1)
    return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m beach.world", description=__doc__.split("\n\n")[0])
    ap.add_argument("--world", required=True, help="the world folder (e.g. worlds/beach)")
    ap.add_argument("--zone", required=True, help="the Beach game zone it is (e.g. beachblox)")
    ap.add_argument("--port", type=int, default=8100)
    ap.add_argument("--bridge-token-file", help="the zone's bridge token (or set BEACH_BRIDGE_TOKEN)")
    ap.add_argument("--beach", default="http://127.0.0.1:8765", help="the Beach (this machine)")
    ap.add_argument("--clawblox", default=os.environ.get("CLAWBLOX_BIN", "clawblox"),
                    help="the clawblox program (default: clawblox on PATH, or CLAWBLOX_BIN)")
    ap.add_argument("--run-dir", help="where the running copy goes (default: $AI_BEACH_DATA/worlds/<zone>)")
    ap.add_argument("--in-place", action="store_true", help="run --world itself (it's already a copy)")
    ap.add_argument("--no-join-key", action="store_true",
                    help="don't give the world a join key (for a Clawblox without patches/clawblox-join-key.patch)")
    ap.add_argument("--no-tints", action="store_true", help="the world's renderer doesn't use tints (ClawBlox)")
    ap.add_argument("--every", type=float, default=10.0, help="seconds between presence reports")
    a = ap.parse_args(argv)

    beach = require_local(a.beach, "--beach")
    token = os.environ.get("BEACH_BRIDGE_TOKEN")
    if a.bridge_token_file:
        token = Path(a.bridge_token_file).expanduser().read_text().strip()
    if not token:
        print("needs the zone's bridge token: --bridge-token-file or BEACH_BRIDGE_TOKEN", file=sys.stderr)
        return 2
    run_dir = prepare(Path(a.world), Path(a.run_dir) if a.run_dir else default_run_dir(a.zone), a.in_place)
    log_path = run_dir / ".ai-beach-world.log"
    join_key = None if a.no_join_key else secrets.token_urlsafe(24)
    env = dict(os.environ)
    env.pop("CLAWBLOX_JOIN_KEY", None)
    if join_key:
        env["CLAWBLOX_JOIN_KEY"] = join_key
    say = lambda m: print(time.strftime("%H:%M:%S"), m, flush=True)  # noqa: E731
    url = f"http://127.0.0.1:{a.port}"
    with open(log_path, "w") as log:
        proc = subprocess.Popen([a.clawblox, "run", str(run_dir), "--port", str(a.port)], stdout=log,
                                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env,
                                start_new_session=True)
    say(f"world starting: {run_dir} on port {a.port} (log: {log_path})")
    stopping = {"now": False}

    def stop(*_):
        stopping["now"] = True
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    bridge = None
    try:
        if not wait_up(url, proc, 180):
            say(f"the world didn't start (exit {proc.poll()}); see {log_path}")
            return 1
        say("world is up" + ("; it accepts joins only through the Beach (join key set)" if join_key else ""))
        bridge = Bridge(url, beach, a.zone, token, lambda: spectator_token_from_log(str(log_path)), str(run_dir),
                        tints=not a.no_tints, join_key=join_key, log=say)
        run_loop(bridge, a.every, keep_going=lambda: not stopping["now"] and proc.poll() is None)
        if proc.poll() is not None:
            say(f"the world stopped (exit {proc.returncode}); stopping the bridge too")
            return 1
        say("stopping the world and its bridge")
        return 0
    finally:
        if bridge:
            bridge.leaving()
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=10)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass


if __name__ == "__main__":
    sys.exit(main())
