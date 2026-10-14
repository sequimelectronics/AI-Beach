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
        with _OPENER.open(req, timeout=timeout) as r:
            data = json.loads(r.read() or b"{}")
        return {"session": data["session"], "agent_id": data["agent_id"], "name": data.get("name", name)}
    return join
