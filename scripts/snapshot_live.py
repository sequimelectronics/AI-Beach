# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""A world's snapshot is for its operator only (job 09, part A, item 1), live.

Needs a running world on this machine with a player in it (e.g. one person joined through the
Beach), started with WORLD_OPERATOR_TOKEN set in its environment if you want to see the operator
path still working. Run it against an unpatched Clawblox to see the problem, and against one with
patches/clawblox-snapshot-operator-only.patch to see it fixed:

    python3 scripts/snapshot_live.py --world http://127.0.0.1:8100 --spectator-log <run>/.ai-beach-world.log \\
        [--operator-token <the world's WORLD_OPERATOR_TOKEN>] [--session <a player's session, to look for>]

What it checks:
  1. GET /snapshot with only the spectator token (as a header, and as ?spectator_token=, the way a
     viewer link carries it): refused, and no session token in the reply.
  2. GET /snapshot with nothing: refused.
  3. GET /snapshot with the operator token: allowed (the save/load protocol still works).
  4. GET /spectate with the spectator token: still works, and carries no session token.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from beach.bridge import spectator_token_from_log  # noqa: E402

_OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def get(url, headers=None):
    try:
        with _OP.open(urllib.request.Request(url, headers=headers or {}), timeout=15) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--world", default="http://127.0.0.1:8100")
    ap.add_argument("--spectator-log", required=True)
    ap.add_argument("--operator-token")
    ap.add_argument("--session", help="a joined player's session token, to look for in the replies")
    a = ap.parse_args(argv)
    W, spec = a.world, spectator_token_from_log(a.spectator_log)
    checks = {}

    def leaks(body: str) -> bool:
        if a.session:
            return a.session in body
        try:
            return bool(json.loads(body).get("sessions"))
        except (ValueError, AttributeError):
            return False

    for label, url, hdr in (("spectator token (header)", f"{W}/snapshot", {"X-Spectator-Token": spec}),
                            ("spectator token (?spectator_token=, as in a viewer link)",
                             f"{W}/snapshot?spectator_token={spec}", {}),
                            ("no token", f"{W}/snapshot", {})):
        st, body = get(url, hdr)
        print(f"GET /snapshot with {label}: {st}; session tokens in the reply: {leaks(body)}"
              + (f" ({body[:70]})" if st >= 400 else ""))
        checks[f"refused: {label}"] = st in (401, 403) and not leaks(body)
    if a.operator_token:
        st, body = get(f"{W}/snapshot", {"X-Operator-Token": a.operator_token})
        print(f"GET /snapshot with the operator token: {st}; has sessions: {leaks(body)}")
        checks["operator still allowed"] = st == 200
    st, body = get(f"{W}/spectate", {"X-Spectator-Token": spec})
    players = [p.get("name") for p in json.loads(body).get("players", [])] if st == 200 else []
    print(f"GET /spectate with the spectator token: {st}; players {players}; session tokens in it: {leaks(body)}")
    checks["watching still works, without sessions"] = st == 200 and not leaks(body)
    print()
    for k, v in checks.items():
        print(f"   {'PASS' if v else 'FAIL'}  {k}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
