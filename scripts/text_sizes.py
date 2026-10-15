"""Token sizes of the cards and state texts an agent reads (job 12: before and after its changes).

Builds the same small Beach in a temporary directory with whichever checkout this file is run
against (--root), and counts tokens with a real tokenizer if given:

    python3 scripts/text_sizes.py --tokenizer path/to/gemma-4-E4B/tokenizer.json [--root <checkout>]

Prints JSON: each text's tokens, plus the text itself.
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
import tempfile
from pathlib import Path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tokenizer")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    ap.add_argument("--texts", action="store_true", help="include the texts")
    a = ap.parse_args(argv)
    sys.path.insert(0, a.root)
    from beach import agent, avatar
    from beach.core import BOARDWALK, SANDCHAT, Beach
    from beach.tokens import make_counter
    counter = make_counter(a.tokenizer, "Gemma 4 E4B") if a.tokenizer else make_counter()
    d = tempfile.mkdtemp(prefix="text-sizes-")
    try:
        b = Beach(d, clock=lambda: 1_800_000_000.0, rng=random.Random(1))
        b.ensure_admin()
        p = {n: b.add_participant(n, k)[0].id for n, k in
             (("Sandy", "agent"), ("Pebble", "agent"), ("Coral", "person"), ("Drift", "person"))}
        b.add_zone("beachblox", "BeachBlox", "game", viewer_url="http://127.0.0.1:8100/")
        b.join(p["Sandy"], SANDCHAT)
        b.join(p["Coral"], SANDCHAT)
        b.post(p["Coral"], SANDCHAT, "Morning, Sandy. Anyone for cards later?")
        b.post(p["Sandy"], SANDCHAT, "Morning, Coral! I'd like that.")
        b.join(p["Pebble"], BOARDWALK)
        if hasattr(b, "watch_world"):
            b.watch_world(p["Coral"], "beachblox")
        tid = b.tables.open(p["Sandy"], BOARDWALK, "crazy8", options={"players": 3, "seed": 7})["id"]
        b.tables.sit(p["Pebble"], tid)
        b.tables.sit(p["Coral"], tid)
        texts = {
            "beach card": agent.beach_card(b),
            "SandChat card": agent.zone_card(b, SANDCHAT),
            "Boardwalk card": agent.zone_card(b, BOARDWALK),
            "BeachBlox card": agent.zone_card(b, "beachblox"),
            "avatar card": avatar.card(b.setting("avatar_cooldown_s")),
            "SandChat state (Sandy)": agent.state_text(b, p["Sandy"], SANDCHAT, consume_notes=False),
            "BeachBlox state (Sandy)": agent.state_text(b, p["Sandy"], "beachblox", consume_notes=False),
        }
        out = {k: {"tokens": counter(v), **({"text": v} if a.texts else {})} for k, v in texts.items()}
        for name, bundle in (("SandChat turn (Sandy)", agent.turn_bundle(b, p["Sandy"], SANDCHAT, counter=counter, consume_notes=False)),
                             ("Crazy Eights turn (Sandy)", agent.table_bundle(b, p["Sandy"], tid, counter=counter, consume_notes=False))):
            out[name] = {"tokens": bundle["total_tokens"], "pieces": {k: bundle[k]["tokens"] for k in ("tools", "state", "recent")}}
        print(json.dumps({"method": counter.method, "sizes": out}, indent=1))
    finally:
        b.db.close()
        shutil.rmtree(d, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
