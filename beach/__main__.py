"""Run the Beach:  python -m beach
Print the keeper's sign-in link for a browser:  python -m beach keeper-link

Settings come from the environment:
  AI_BEACH_DATA   data directory (database, admin token). Required; keep it outside the repo.
                  For development, `_local/beach-data` is gitignored.
  AI_BEACH_HOST   listening address (default 127.0.0.1 = this computer only)
  AI_BEACH_PORT   port (default 8765)

HTTPS is a keeper setting (`https`, off by default; see the README): when it's on, browsers use
HTTPS on `https_port` at AI_BEACH_HOST, and plain HTTP stays available on this computer only
(127.0.0.1:AI_BEACH_PORT) for the bridge, local agents and hooks.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import sys
from pathlib import Path

import uvicorn

from .app import create_app
from .core import Beach
from .hooks import install


def main() -> int:
    data = os.environ.get("AI_BEACH_DATA")
    if not data:
        print("Set AI_BEACH_DATA to a data directory outside the repository, e.g.\n"
              "  AI_BEACH_DATA=~/.local/share/ai-beach python -m beach", file=sys.stderr)
        return 2
    data_dir = Path(data).expanduser()
    host = os.environ.get("AI_BEACH_HOST", "127.0.0.1")
    port = int(os.environ.get("AI_BEACH_PORT", "8765"))

    if sys.argv[1:] == ["keeper-link"]:
        token_file = data_dir / "admin_token"
        if not token_file.exists():
            print("No admin token yet: start the Beach once first.", file=sys.stderr)
            return 1
        b = Beach(data_dir)
        base = b.setting("link_base") or f"http://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{port}"
        b.db.close()
        print(f"{base}/#t={token_file.read_text().strip()}")
        print("Open it in your browser. It signs you in as the keeper; don't share it.", file=sys.stderr)
        return 0

    beach = Beach(data_dir)
    install(beach)
    token = beach.ensure_admin()
    if token:
        token_file = data_dir / "admin_token"
        token_file.write_text(token + "\n")
        os.chmod(token_file, 0o600)
        print(f"First start: the keeper's admin token is in {token_file} (readable only by you).")

    local = host in ("127.0.0.1", "localhost", "::1")
    if not beach.setting("https"):
        print(f"{beach.setting('beach_name')} is listening on http://{host}:{port}")
        print("Keeper: `python -m beach keeper-link` prints your sign-in link for a browser.")
        if not local:
            print("Note: listening beyond this computer. Anyone on that network can reach the door; "
                  "tokens are still required.")
        uvicorn.run(create_app(beach, serving={"http": f"http://{host}:{port}"}), host=host, port=port,
                    log_level="warning", access_log=False)
        return 0
    return serve_https(beach, data_dir, host, port)


class _Server(uvicorn.Server):
    """Two servers share one process here, so signals are handled once, below, for both."""

    @contextlib.contextmanager
    def capture_signals(self):
        yield


def serve_https(beach: Beach, data_dir: Path, host: str, port: int) -> int:
    from . import tls
    https_port = int(beach.setting("https_port"))
    if https_port == port:
        print(f"https_port ({https_port}) must differ from AI_BEACH_PORT ({port}).", file=sys.stderr)
        return 2
    cert, key = beach.setting("https_cert"), beach.setting("https_key")
    own_ca = not (cert and key)
    if own_ca:
        cert, key, ca = tls.ensure(data_dir, tls.wanted_names(beach.setting("link_base"), beach.setting("https_names")))
    else:
        cert, key = Path(cert).expanduser(), Path(key).expanduser()
    shown = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    serving = {"http": f"http://127.0.0.1:{port}", "https": f"https://{shown}:{https_port}", "own_ca": own_ca}
    app = create_app(beach, serving=serving)
    servers = [
        # Plain HTTP for programs on this computer only: never reachable from the network.
        _Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)),
        # HTTPS for browsers, at the chosen address. The app's start-up runs once, in the first.
        _Server(uvicorn.Config(app, host=host, port=https_port, log_level="warning", access_log=False,
                               lifespan="off", ssl_certfile=str(cert), ssl_keyfile=str(key))),
    ]
    print(f"{beach.setting('beach_name')} is listening on https://{shown}:{https_port} (browsers), "
          f"and on http://127.0.0.1:{port} for programs on this computer.")
    if own_ca:
        print(f"Devices trust this Beach once: install {ca} (also at /beach-ca.pem); see the README, \"HTTPS\".")
    print("Keeper: `python -m beach keeper-link` prints your sign-in link for a browser.")

    def stop(*_):
        for s in servers:
            s.should_exit = True
    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), stop)

    async def both():
        await asyncio.gather(*(s.serve() for s in servers))
    asyncio.run(both())
    return 0


if __name__ == "__main__":
    sys.exit(main())
