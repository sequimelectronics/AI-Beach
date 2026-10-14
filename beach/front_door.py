"""The Beach as the front door to game worlds: joining a world for a person.

Agents join a world themselves (under their Beach name) and then vouch for the join (the
adapter's front_door.beach_voucher). People use a browser, which can't easily do both steps
across two sites, so the Beach does them: it joins the world under the person's Beach name and
vouches for that join, then hands back the session for the viewer's chat panel.

The only network call the Beach makes here goes to the world's own address on THIS machine
(the bridge reports it), never anywhere else, and proxy settings are ignored.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

from .hooks import _is_local

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def local_world_url(url: str | None) -> str | None:
    """The world's address if it is on this machine, else None."""
    if not url:
        return None
    u = urllib.parse.urlparse(str(url))
    if u.scheme in ("http", "https") and u.hostname and _is_local(u.hostname):
        return f"{u.scheme}://{u.netloc}"
    return None


def join_world(world_url: str, name: str, timeout: float = 5.0) -> dict:
    """POST <world>/join?name=<name> on this machine. Returns {"session", "agent_id"}."""
    base = local_world_url(world_url)
    if not base:
        raise ValueError("the world must be on this machine")
    req = urllib.request.Request(f"{base}/join?" + urllib.parse.urlencode({"name": name}), method="POST",
                                 data=b"")
    with _OPENER.open(req, timeout=timeout) as r:
        data = json.loads(r.read() or b"{}")
    return {"session": data["session"], "agent_id": data["agent_id"]}


def viewer_link(viewer_url: str, spectator_token: str | None, session: str, player: str) -> str:
    base = viewer_url.split("?")[0]
    q = {"session": session, "player": player}
    if spectator_token:
        q["spectator_token"] = spectator_token
    return base + ("" if base.endswith("/") else "/") + "?" + urllib.parse.urlencode(q)
