#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""Count tokens in saved Clawblox observations with real small-model tokenizers.

Companion to clawblox_probe.py. Needs `pip install tokenizers` and local copies
of tokenizer.json files (e.g. Qwen/Qwen3-4B and a Gemma-3-4B tokenizer from
Hugging Face). Prints, per file: bytes, chars/4 estimate, real token counts,
and the size of a "compact" re-encoding that keeps only name, position, size
and RenderRole per entity (what a thin adapter could send instead).

    python3 clawblox_token_count.py --tok qwen3-4b=path/tokenizer.json obs-*.json
"""

import argparse
import json

from tokenizers import Tokenizer


def compact(obs: dict) -> dict:
    """Drop derived geometry (rotation, aabb, obb corners, color) and round to 0.1."""
    def r(v):
        return [round(x, 1) for x in v]
    ents = []
    for e in obs["world"]["entities"]:
        attrs = e.get("attributes") or {}
        ent = {"n": e["name"], "p": r(e["position"]), "s": r(e["size"])}
        if "RenderRole" in attrs:
            ent["role"] = attrs["RenderRole"]
        ents.append(ent)
    return {
        "tick": obs["tick"],
        "me": r(obs["player"]["position"]),
        "last": obs["player"]["attributes"].get("LastActionResult"),
        "others": [{"n": p.get("name"), "p": r(p["position"])} for p in obs["other_players"]],
        "ents": ents,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tok", action="append", required=True, help="name=path/to/tokenizer.json")
    ap.add_argument("files", nargs="+")
    args = ap.parse_args()
    toks = {k: Tokenizer.from_file(v) for k, v in (t.split("=", 1) for t in args.tok)}
    for f in args.files:
        text = open(f).read()
        row = {"file": f, "bytes": len(text.encode()), "chars/4": -(-len(text) // 4)}
        row.update({k: len(t.encode(text).ids) for k, t in toks.items()})
        if f.endswith(".json"):
            obs = json.loads(text)
            row["entities"] = len(obs["world"]["entities"])
            c = json.dumps(compact(obs), separators=(",", ":"))
            row["compact_bytes"] = len(c)
            row.update({f"compact_{k}": len(t.encode(c).ids) for k, t in toks.items()})
        print(json.dumps(row))


if __name__ == "__main__":
    main()
