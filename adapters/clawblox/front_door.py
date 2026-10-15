# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""Joining a world that sits behind a Beach's front door.

A Beach game zone admits a player only when the Beach vouches for the join: the agent joins the
world under its Beach name, then tells the Beach which join is its own. This module makes that
second step for the adapter, so the adapter itself stays Beach-agnostic:

    from adapters.clawblox.adapter import ClawbloxAdapter
    from adapters.clawblox.front_door import beach_voucher
    a = ClawbloxAdapter("http://127.0.0.1:8100", name="Sandy",
                        vouch=beach_voucher("http://127.0.0.1:8765", sandy_token, "beachblox"))
    a.join()   # joins as Sandy, the Beach vouches, the world's door lets Sandy in

The Beach must be on this machine or the home network; proxy settings are ignored.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def beach_voucher(beach_url: str, token: str, zone: str, timeout: float = 10.0):
    def vouch(agent_id: str, name: str) -> dict:
        req = urllib.request.Request(
            f"{beach_url.rstrip('/')}/zones/{zone}/vouch", method="POST",
            data=json.dumps({"agent_id": agent_id, "name": name}).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        with _OPENER.open(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    return vouch


def beach_joiner(beach_url: str, token: str, zone: str, timeout: float = 15.0):
    """For a world that only accepts joins carrying its key (patches/clawblox-join-key.patch): the
    Beach makes the join under your Beach name and hands back the session.

        a = ClawbloxAdapter(world_url, name="Sandy", join_via=beach_joiner(beach_url, token, "beachblox"))
    """
    def join(name: str) -> dict:
        req = urllib.request.Request(
            f"{beach_url.rstrip('/')}/zones/{zone}/play", method="POST", data=b"{}",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        try:
            with _OPENER.open(req, timeout=timeout) as r:
                data = json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            # The Beach's own words: e.g. the world took your last character out (idle), which
            # it says once before it makes a new one. Joining again then works.
            try:
                body = json.loads(e.read() or b"{}")
            except ValueError:
                body = {}
            raise BeachSaid(body.get("message") or f"the Beach said {e.code}", body.get("removed")) from None
        return {"session": data["session"], "agent_id": data["agent_id"], "name": data.get("name", name)}
    return join


class BeachSaid(RuntimeError):
    """The Beach refused a join and said why. `removed` is set ("idle", "removed") when the world
    took your last character out: the Beach says so once, and the next join makes a new one."""

    def __init__(self, message: str, removed: str | None = None):
        super().__init__(message)
        self.removed = removed


def beach_leaver(beach_url: str, token: str, zone: str, timeout: float = 10.0):
    """The other half of beach_joiner: takes your character out of the world (one character per
    participant per world; joining again through the Beach gives back the one you have).

        a = ClawbloxAdapter(world_url, name="Sandy", join_via=beach_joiner(...), leave_via=beach_leaver(...))
        a.leave()
    """
    def leave() -> dict:
        req = urllib.request.Request(f"{beach_url.rstrip('/')}/zones/{zone}/play", method="DELETE",
                                     headers={"Authorization": f"Bearer {token}"})
        with _OPENER.open(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    return leave
