# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""Assemble a runnable ClawBlox world (Clawblox's mesa-island) that works without the internet.

mesa-island's world script and its player model belong to Clawblox and are not in this
repository. This copies them from YOUR Clawblox checkout into a folder outside the repo, then
lays our pieces over the copy:

- worlds/clawblox/renderer/  mesa-island's renderer, adapted (three.js from the vendored copy)
- static/vendor/             three.js and lucide, from worlds/beach/static/vendor/
- scripts/ServerScriptService/BeachDoor.lua   the Beach's front door (from worlds/beach/), so only
                             participants the Beach vouches for can play, under their Beach names
- scripts/ServerScriptService/LostAndFound.lua (from worlds/clawblox/): the boulder and the ring come
                             back beside the spawn if they fall off the island

    python3 scripts/clawblox_world.py --clawblox ~/src/clawblox --out ~/beach-worlds/clawblox
    clawblox run ~/beach-worlds/clawblox --port 8200

Run it again after updating Clawblox; it replaces the folder it made (and only a folder it made).
With --max-players N it raises mesa-island's player limit (1 by default) in the copy.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARK = ".ai-beach-clawblox"


def assemble(clawblox: Path, out: Path, max_players: int | None = None) -> Path:
    mesa = clawblox / "worlds" / "mesa-island"
    if not (mesa / "world.toml").is_file():
        raise SystemExit(f"no mesa-island world in {clawblox} (expected {mesa}/world.toml)")
    out = out.expanduser().resolve()
    if ROOT in out.parents or out == ROOT:
        if (ROOT / "_local") not in out.parents:
            raise SystemExit("put the world outside the repository (or under _local/, which git ignores)")
    if out.exists():
        if not (out / MARK).exists():
            raise SystemExit(f"{out} exists and wasn't made by this script; choose another --out")
        shutil.rmtree(out)
    # mesa-island from the Clawblox checkout (not ours, never committed): script, settings, assets.
    shutil.copytree(mesa, out, ignore=shutil.ignore_patterns("renderer", "dist", ".clawblox", ".build.lock"))
    # Our renderer and the vendored libraries.
    shutil.copytree(ROOT / "worlds" / "clawblox" / "renderer", out / "renderer",
                    ignore=shutil.ignore_patterns("dist", ".build.lock"))
    shutil.copytree(ROOT / "worlds" / "beach" / "static" / "vendor", out / "static" / "vendor")
    # The front door: the same script the beach world runs, in a script tree.
    door_src = ROOT / "worlds" / "beach" / "scripts" / "ServerScriptService" / "BeachDoor.lua"
    (out / "scripts" / "ServerScriptService").mkdir(parents=True, exist_ok=True)
    shutil.copy2(door_src, out / "scripts" / "ServerScriptService" / "BeachDoor.lua")
    # Ours for this world: the lost and found (the boulder and ring come back by the spawn if they fall off).
    for f in (ROOT / "worlds" / "clawblox" / "scripts" / "ServerScriptService").glob("*.lua"):
        shutil.copy2(f, out / "scripts" / "ServerScriptService" / f.name)
    toml = out / "world.toml"
    text = toml.read_text()
    if re.search(r"(?m)^tree\s*=", text):
        raise SystemExit("mesa-island already has a script tree; merge BeachDoor.lua into it by hand")
    text, n = re.subn(r"(?m)^(\[scripts\]\s*\n)", r'\1tree = "scripts"\n', text)
    if n != 1:
        raise SystemExit("couldn't find [scripts] in mesa-island's world.toml")
    toml.write_text(text)
    if max_players:
        text, n = re.subn(r"(?m)^max_players\s*=\s*\d+", f"max_players = {int(max_players)}", toml.read_text())
        if n != 1:
            raise SystemExit("couldn't find max_players in mesa-island's world.toml")
        toml.write_text(text)
    (out / MARK).write_text("Assembled by AI Beach's scripts/clawblox_world.py; safe to delete.\n")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--clawblox", required=True, type=Path, help="your Clawblox checkout")
    ap.add_argument("--out", required=True, type=Path, help="where to put the world (outside this repo)")
    ap.add_argument("--max-players", type=int, help="raise mesa-island's player limit in the copy")
    a = ap.parse_args(argv)
    out = assemble(a.clawblox.expanduser(), a.out, a.max_players)
    print(f"ClawBlox world ready: {out}\nrun it with: clawblox run {out} --port 8200")
    return 0


if __name__ == "__main__":
    sys.exit(main())
