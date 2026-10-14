"""Run the Beach:  python -m beach
Print the keeper's sign-in link for a browser:  python -m beach keeper-link

Settings come from the environment:
  AI_BEACH_DATA   data directory (database, admin token). Required; keep it outside the repo.
                  For development, `_local/beach-data` is gitignored.
  AI_BEACH_HOST   listening address (default 127.0.0.1 = this computer only)
  AI_BEACH_PORT   port (default 8765)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

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

    import uvicorn
    print(f"{beach.setting('beach_name')} is listening on http://{host}:{port}")
    print("Keeper: `python -m beach keeper-link` prints your sign-in link for a browser.")
    if host not in ("127.0.0.1", "localhost", "::1"):
        print("Note: listening beyond this computer. Anyone on that network can reach the door; "
              "tokens are still required.")
    uvicorn.run(create_app(beach), host=host, port=port, log_level="warning", access_log=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
