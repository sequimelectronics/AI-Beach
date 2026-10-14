"""The Beach as the front door to game worlds: joining a world on a participant's behalf.

The Beach joins the world under the participant's Beach name and vouches for that join, then
hands back the session: to a person's viewer (in the link's #fragment) or to an agent's adapter.
A world started with a join key (patches/clawblox-join-key.patch, `python -m beach.world`)
accepts joins only from whoever holds the key, which is the Beach; then this is the only way in.
(Worlds without the key also accept the job 07 way: the agent joins, then vouches.)

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


def join_world(world_url: str, name: str, join_key: str | None = None, timeout: float = 5.0) -> dict:
    """POST <world>/join?name=<name> on this machine (with the world's join key, if it has one).
    Returns {"session", "agent_id"}."""
    base = local_world_url(world_url)
    if not base:
        raise ValueError("the world must be on this machine")
    headers = {"X-Join-Key": join_key} if join_key else {}
    req = urllib.request.Request(f"{base}/join?" + urllib.parse.urlencode({"name": name}), method="POST",
                                 data=b"", headers=headers)
    with _OPENER.open(req, timeout=timeout) as r:
        data = json.loads(r.read() or b"{}")
    return {"session": data["session"], "agent_id": data["agent_id"]}


def viewer_link(viewer_url: str, spectator_token: str | None, session: str, player: str) -> str:
    """The viewer, with the game session after '#': it never reaches a server, its logs or the
    Referer header, and the patched viewer removes it from the address bar once read
    (patches/clawblox-viewer-session.patch)."""
    base = viewer_url.split("?")[0].split("#")[0]
    link = base + ("" if base.endswith("/") else "/")
    if spectator_token:
        link += "?" + urllib.parse.urlencode({"spectator_token": spectator_token})
    return link + "#" + urllib.parse.urlencode({"session": session, "player": player})
