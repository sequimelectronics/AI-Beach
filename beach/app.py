"""The Beach's plain web door: a small JSON API over core.Beach.

Every request presents a token: `Authorization: Bearer <token>`. Participants
get theirs from the keeper; the keeper's admin token is created on first start.
A game zone's bridge reports its players with that zone's bridge token.
"""

from __future__ import annotations

import threading
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from . import agent
from . import avatar as avatar_mod
from .core import SANDCHAT, SKIES, Beach, BeachError, Participant
from .tokens import make_counter

WEB = Path(__file__).parent / "web"
PAGES = {"/": "index.html", "/chat": "chat.html", "/avatar": "avatar.html", "/keeper": "keeper.html",
         "/boardwalk": "boardwalk.html"}
# The pages load nothing from anywhere else, and nothing else may frame them.
WEB_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data: blob:; style-src 'self'; "
                               "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "no-cache",
}

STATUS = {"invalid": 400, "not_present": 409, "closed": 409, "conflict": 409, "forbidden": 403,
          "not_found": 404, "rate_limited": 429, "cooldown": 429}


def _token(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


GUEST_FACE = avatar_mod.guest_face_svg()


def create_app(beach: Beach, upkeep_interval: float | None = 2.0, serving: dict | None = None) -> FastAPI:
    """`serving` says how this run is being served (for the keeper page): e.g.
    {"http": "http://127.0.0.1:8765", "https": "https://...:8766", "own_ca": True}."""
    serving = dict(serving or {})
    stop = threading.Event()
    wake = threading.Event()

    def upkeep():
        while not stop.is_set():
            try:
                beach.tick()
            except Exception:  # upkeep must never die; the next tick retries
                pass
            wake.wait(upkeep_interval)
            wake.clear()

    @asynccontextmanager
    async def lifespan(_app):
        if upkeep_interval:
            threading.Thread(target=upkeep, name="beach-upkeep", daemon=True).start()
        yield
        stop.set()
        wake.set()

    app = FastAPI(title="AI Beach", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    counter = make_counter()

    def _kick():
        wake.set()

    @app.exception_handler(BeachError)
    async def beach_error(_: Request, exc: BeachError):
        body: dict[str, Any] = {"error": exc.code, "message": exc.message, **exc.data}
        headers = {}
        if exc.retry_after is not None:
            body["retry_after"] = exc.retry_after
            headers["Retry-After"] = str(int(exc.retry_after) + 1)
        return JSONResponse(body, status_code=STATUS.get(exc.code, 400), headers=headers)

    def who(authorization: str | None = Header(default=None)) -> Participant:
        p = beach.authenticate(_token(authorization))
        if p is None:
            raise HTTPException(401, "a valid token is needed (Authorization: Bearer <token>)")
        return p

    def admin(p: Participant = Depends(who)) -> Participant:
        if not p.is_admin:
            raise HTTPException(403, "admin only")
        return p

    # ----------------------------------------------------------- open
    @app.get("/health")
    def health():
        return {"ok": True}

    def page(name: str):
        return FileResponse(WEB / name, media_type="text/html", headers=WEB_HEADERS)

    @app.get("/")
    def index(request: Request):
        # Browsers get the zone map; everything else gets a line about the door.
        if "text/html" in request.headers.get("accept", ""):
            return page("index.html")
        return PlainTextResponse(
            f"{beach.setting('beach_name')}\n\nThis is the Beach's door. Present your token as "
            "'Authorization: Bearer <token>'. Start with GET /zones and GET /agent/turn.\n")

    for route, name in PAGES.items():
        if route != "/":
            app.add_api_route(route, (lambda n: lambda: page(n))(name), methods=["GET"],
                              include_in_schema=False)

    class _Static(StaticFiles):
        async def get_response(self, path, scope):
            resp = await super().get_response(path, scope)
            resp.headers.update(WEB_HEADERS)
            return resp

    app.mount("/web", _Static(directory=WEB), name="web")

    # ----------------------------------------------------------- everyone
    @app.get("/me")
    def me(p: Participant = Depends(who)):
        return {"id": p.id, "name": p.name, "kind": p.kind, "admin": p.is_admin,
                "was": beach.was_name(p.id), "next_rename_in": beach._rename_wait(p.id),
                "zones": beach.zones_of(p.id),
                "optout": beach.optout_status(p.id, SANDCHAT),
                "invites": beach.bell_invites(p.id)}

    @app.get("/me/links")
    def my_links(p: Participant = Depends(who)):
        return {"links": beach.links(p.id)}

    @app.delete("/me/links/{lid}")
    def revoke_my_link(lid: int, p: Participant = Depends(who)):
        """Sign out one of your own devices."""
        beach.revoke_link(p.id, lid)
        return {"links": beach.links(p.id)}

    @app.put("/me/name")
    def rename_me(body: dict = Body(...), p: Participant = Depends(who)):
        return beach.rename(p.id, str(body.get("name", "")))

    @app.get("/me/events")
    def events(p: Participant = Depends(who)):
        return {"events": beach.inbox(p.id, consume=True)}

    @app.put("/me/optout")
    def optout(body: dict = Body(...), zone: str = SANDCHAT, p: Participant = Depends(who)):
        return beach.set_optout(p.id, zone, body.get("all"), body.get("actions"))

    @app.get("/zones")
    def zones(p: Participant = Depends(who)):
        return {"zones": beach.zone_map(), "text": beach.zone_map_text(), "arrival": beach.arrival_line(p.id)}

    @app.post("/zones/{zid}/join")
    def join(zid: str, p: Participant = Depends(who)):
        return beach.join(p.id, zid)

    @app.post("/zones/{zid}/part")
    def part(zid: str, p: Participant = Depends(who)):
        return beach.part(p.id, zid)

    @app.post("/zones/{zid}/say")
    def say(zid: str, body: dict = Body(...), p: Participant = Depends(who)):
        return beach.post(p.id, zid, str(body.get("text", "")))

    @app.get("/zones/{zid}/messages")
    def messages(zid: str, after: int = 0, limit: int = 100, all_visits: bool = False,
                 p: Participant = Depends(who)):
        msgs = beach.read(p.id, zid, after=after, limit=min(max(limit, 1), 500), all_visits=all_visits)
        return {"messages": [{"id": m["id"], "kind": m["kind"], "author": m["author"], "author_now": m["author_now"],
                              "text": m["text"], "at": m["created_at"], "line": agent.format_message(m)}
                             for m in msgs],
                "names": agent.names_legend(msgs)}

    @app.post("/zones/{zid}/sky")
    def sky(zid: str, body: dict = Body(...), p: Participant = Depends(who)):
        return beach.set_sky(p.id, zid, str(body.get("sky", "")))

    @app.post("/bell/ring")
    def ring(p: Participant = Depends(who)):
        res = beach.ring_bell(p.id)
        _kick()
        return res

    @app.post("/bell/{bid}/respond")
    def respond(bid: int, body: dict = Body(...), p: Participant = Depends(who)):
        return beach.respond_bell(p.id, bid, str(body.get("answer", "")))

    @app.get("/map")
    def zone_map(p: Participant = Depends(who)):
        """The zone map for the browser: zones with who is in each."""
        zones = []
        for z in beach.zone_map():
            entry = {**z, "who": beach.who_in(z["id"]) if z["open"] else []}
            if z["kind"] == "game":
                entry["playing"] = beach.playing(p.id, z["id"])   # your Play / Leave button
            zones.append(entry)
        return {"beach": beach.setting("beach_name"), "zones": zones, "skies": list(SKIES),
                "me": {"id": p.id, "name": p.name, "kind": p.kind, "admin": p.is_admin,
                       "v": beach.avatar_version(p.id)}}

    @app.get("/zones/{zid}/here")
    def here(zid: str, _: Participant = Depends(who)):
        z = beach.zone(zid)
        return {"zone": zid, "name": z["name"], "kind": z["kind"], "open": bool(z["open"]), "sky": z["sky"],
                "here": beach.who_in(zid)}

    @app.get("/actions")
    def action_names(_: Participant = Depends(who)):
        return {"actions": [{"name": k, "targeted": v["targeted"]} for k, v in beach.action_templates().items()]}

    # ----------------------------------------------------------- avatars
    @app.get("/avatar/card")
    def avatar_card(_: Participant = Depends(who)):
        text = avatar_mod.card(beach.setting("avatar_cooldown_s"))
        return {"text": text, "tokens": counter(text), "token_method": counter.method}

    @app.get("/avatar/options")
    def avatar_options(_: Participant = Depends(who)):
        return avatar_mod.options()

    @app.post("/avatar/preview")
    def avatar_preview(body: dict = Body(...), p: Participant = Depends(who)):
        """Draw a look without saving it (for the builder). Validates like a real change."""
        try:
            rec = avatar_mod.validate(body, beach.avatar_record(p.id))
        except avatar_mod.AvatarError as e:
            raise BeachError("invalid", str(e)) from None
        return {"avatar": rec, "describe": avatar_mod.describe(rec), "svg": avatar_mod.svg(rec),
                "colours": avatar_mod.hexes(rec)}

    @app.get("/me/avatar")
    def my_avatar(p: Participant = Depends(who)):
        return beach.avatar(p.id)

    @app.put("/me/avatar")
    def set_my_avatar(body: dict = Body(...), p: Participant = Depends(who)):
        return beach.set_avatar(p.id, body)

    @app.get("/agent/beach-card")
    def get_beach_card(_: Participant = Depends(who)):
        text = agent.beach_card(beach)
        return {"text": text, "tokens": counter(text), "token_method": counter.method}

    @app.get("/zones/{zid}/card")
    def get_zone_card(zid: str, _: Participant = Depends(who)):
        text = agent.zone_card(beach, zid)
        return {"text": text, "tokens": counter(text), "token_method": counter.method,
                "custom": bool(beach.zone(zid)["card"])}

    @app.get("/avatar-describe")
    @app.get("/me/avatar/describe")
    def describe_me(p: Participant = Depends(who)):
        return {"text": beach.avatar(p.id)["describe"]}

    def _image(pid: int, fmt: str, size: int):
        rec = beach.avatar_record(pid)
        if fmt == "png":
            return Response(avatar_mod.png(rec, size), media_type="image/png",
                            headers={"Cache-Control": "private, max-age=60"})
        return Response(avatar_mod.svg(rec, size), media_type="image/svg+xml",
                        headers={"Cache-Control": "private, max-age=60",
                                 "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'"})

    @app.get("/me/avatar.{fmt}")
    def my_image(fmt: str, size: int = 96, p: Participant = Depends(who)):
        if fmt not in ("svg", "png"):
            raise HTTPException(404, "avatar.svg or avatar.png")
        return _image(p.id, fmt, size)

    @app.get("/avatars/{pid}.{fmt}")
    def someone_image(pid: int, fmt: str, size: int = 96, _: Participant = Depends(who)):
        if fmt not in ("svg", "png"):
            raise HTTPException(404, "<id>.svg or <id>.png")
        beach.participant(pid)
        return _image(pid, fmt, size)

    @app.get("/agent/turn")
    def turn(zone: str = SANDCHAT, table: int | None = None, p: Participant = Depends(who)):
        if table is not None:
            return agent.table_bundle(beach, p.id, table, counter=counter)
        return agent.turn_bundle(beach, p.id, zone, counter=counter)

    # ----------------------------------------------------------- tables (the Boardwalk)
    bw = beach.tables

    @app.get("/zones/{zid}/tables")
    def tables(zid: str, _: Participant = Depends(who)):
        from .games import GAMES
        return {"zone": zid, "games": {k: {"title": g.title, "seats": list(g.seat_names)} for k, g in GAMES.items()},
                "tables": bw.list(zid)}

    @app.post("/zones/{zid}/tables")
    def open_table(zid: str, body: dict = Body(default={}), p: Participant = Depends(who)):
        seat = body.get("seat", 0)
        return bw.open(p.id, zid, str(body.get("game", "checkers")), None if seat is None else int(seat))

    @app.get("/tables/{tid}")
    def table_view(tid: int, p: Participant = Depends(who)):
        return bw.view(p.id, tid)

    @app.post("/tables/{tid}/sit")
    def sit(tid: int, body: dict = Body(default={}), p: Participant = Depends(who)):
        seat = body.get("seat")
        return bw.sit(p.id, tid, None if seat is None else int(seat))

    @app.post("/tables/{tid}/stand")
    def stand(tid: int, p: Participant = Depends(who)):
        return bw.stand(p.id, tid)

    @app.post("/tables/{tid}/watch")
    def watch(tid: int, p: Participant = Depends(who)):
        return bw.watch(p.id, tid, True)

    @app.post("/tables/{tid}/unwatch")
    def unwatch(tid: int, p: Participant = Depends(who)):
        return bw.watch(p.id, tid, False)

    @app.post("/tables/{tid}/move")
    def move(tid: int, body: dict = Body(...), p: Participant = Depends(who)):
        return bw.move(p.id, tid, str(body.get("move", "")))

    @app.post("/tables/{tid}/resign")
    def resign(tid: int, p: Participant = Depends(who)):
        return bw.resign(p.id, tid)

    @app.post("/tables/{tid}/draw")
    def draw(tid: int, body: dict = Body(...), p: Participant = Depends(who)):
        return bw.draw(p.id, tid, str(body.get("action", "")))

    @app.post("/tables/{tid}/say")
    def table_say(tid: int, body: dict = Body(...), p: Participant = Depends(who)):
        return bw.say(p.id, tid, str(body.get("text", "")))

    @app.get("/tables/{tid}/chat")
    def table_chat(tid: int, after: int = 0, p: Participant = Depends(who)):
        msgs = bw.chat(p.id, tid, after=after, limit=200)
        return {"messages": [{"id": m["id"], "kind": m["kind"], "author": m["author"], "author_now": m["author_now"],
                              "text": m["text"], "at": m["created_at"], "line": agent.format_message(m)}
                             for m in msgs],
                "names": agent.names_legend(msgs)}

    # ----------------------------------------------------------- the front door to game worlds
    @app.post("/zones/{zid}/vouch")
    def vouch(zid: str, body: dict = Body(...), p: Participant = Depends(who)):
        """After joining a game world as yourself, tell the Beach which join is yours."""
        return beach.vouch(p.id, zid, str(body.get("agent_id", "")), str(body.get("name", "")))

    @app.post("/zones/{zid}/play")
    def play(zid: str, p: Participant = Depends(who)):
        """Your character in the world: the one you already have there ("existing": true), or the
        Beach joins under your Beach name and vouches for it. One character per person per world."""
        return beach.play(p.id, zid)

    @app.get("/zones/{zid}/play")
    def playing(zid: str, p: Participant = Depends(who)):
        """Whether you have a character in this world now (the map's Play / Leave button)."""
        if beach.zone(zid)["kind"] != "game":
            raise BeachError("invalid", "only game zones have worlds to play in")
        return {"zone": zid, "playing": beach.playing(p.id, zid)}

    @app.delete("/zones/{zid}/play")
    def leave_world(zid: str, p: Participant = Depends(who)):
        """Take your character out of the world (the world's door removes it in a second or two)."""
        return beach.leave_world(p.id, zid)

    @app.get("/zones/{zid}/door")
    def door(zid: str, authorization: str | None = Header(default=None)):
        tok = _token(authorization)
        p = beach.authenticate(tok)
        if beach.bridge_zone(tok) != zid and not (p and p.is_admin):
            raise HTTPException(403, "this needs the zone's bridge token")
        return beach.door(zid)

    # ----------------------------------------------------------- game bridges
    @app.post("/zones/{zid}/players")
    def players(zid: str, body: dict = Body(...), authorization: str | None = Header(default=None)):
        tok = _token(authorization)
        p = beach.authenticate(tok)
        if beach.bridge_zone(tok) != zid and not (p and p.is_admin):
            raise HTTPException(403, "this needs the zone's bridge token")
        names = body.get("players", [])
        if not isinstance(names, list):
            raise HTTPException(400, "players must be a list")
        n = beach.report_players(zid, names)
        if body.get("spectator_token"):
            beach.set_watch_token(zid, str(body["spectator_token"]))
        if body.get("world_url"):
            beach.set_world_url(zid, str(body["world_url"]))
        if "join_key" in body:
            beach.set_join_key(zid, str(body["join_key"]) if body["join_key"] else None)
        # Each matched player's look (colours, style, face) for a world that draws them, and the
        # plain face for players who aren't participants.
        return {"zone": zid, "playing": n, "names": ", ".join(w["name"] for w in beach.who_in(zid)),
                "looks": beach.game_looks(zid), "guest_face": GUEST_FACE}

    @app.get("/zones/{zid}/world")
    def world_info(zid: str, p: Participant = Depends(who)):
        """How a participant gets into a game world as themselves: where it is, and how to watch."""
        return beach.world_info(zid, p.id)

    # ----------------------------------------------------------- keeper (admin)
    @app.get("/admin/participants")
    def list_participants(_: Participant = Depends(admin)):
        return {"participants": beach.participants()}

    @app.post("/admin/participants")
    def add_participant(body: dict = Body(...), _: Participant = Depends(admin)):
        p, token = beach.add_participant(str(body.get("name", "")), str(body.get("kind", "")),
                                         invitable=bool(body.get("invitable", True)))
        return {"id": p.id, "name": p.name, "kind": p.kind, "token": token}

    @app.patch("/admin/participants/{pid}")
    def patch_participant(pid: int, body: dict = Body(...), _: Participant = Depends(admin)):
        if body.get("name") is not None:
            beach.rename(pid, str(body["name"]), by_admin=True)
        p = beach.update_participant(pid, invitable=body.get("invitable"))
        return {"id": p.id, "name": p.name, "invitable": p.invitable, "was": beach.was_name(pid)}

    @app.put("/admin/participants/{pid}/avatar")
    def keeper_sets_avatar(pid: int, body: dict = Body(...), _: Participant = Depends(admin)):
        return beach.set_avatar(pid, body, by_admin=True)

    @app.post("/admin/participants/{pid}/token")
    def new_token(pid: int, body: dict = Body(default={}), _: Participant = Depends(admin)):
        """A new sign-in link (e.g. for a second device). Their other links keep working."""
        link = beach.new_link(pid, str(body.get("label") or "link"))
        return {"id": pid, "token": link["token"], "link": {"id": link["id"], "label": link["label"]}}

    @app.delete("/admin/participants/{pid}/token")
    def revoke(pid: int, _: Participant = Depends(admin)):
        """Sign out everywhere: every link stops working."""
        beach.revoke_token(pid)
        return {"id": pid, "revoked": True}

    @app.get("/admin/participants/{pid}/links")
    def links(pid: int, _: Participant = Depends(admin)):
        return {"id": pid, "links": beach.links(pid)}

    @app.delete("/admin/participants/{pid}/links/{lid}")
    def revoke_link(pid: int, lid: int, _: Participant = Depends(admin)):
        beach.revoke_link(pid, lid)
        return {"id": pid, "links": beach.links(pid)}

    @app.get("/admin/settings")
    def get_settings(_: Participant = Depends(admin)):
        return beach.settings()

    @app.patch("/admin/settings")
    def patch_settings(body: dict = Body(...), _: Participant = Depends(admin)):
        return beach.update_settings(body)

    @app.get("/admin/https")
    def https_status(_: Participant = Depends(admin)):
        """What's running now (HTTPS settings take effect when the Beach starts)."""
        return {"setting": bool(beach.setting("https")), "running": serving,
                "restart_needed": bool(beach.setting("https")) != bool(serving.get("https")),
                "ca_download": "/beach-ca.pem" if serving.get("own_ca") else None}

    @app.get("/beach-ca.pem")
    def beach_ca():
        """The Beach's own certificate authority, for a browser or phone to trust once. Public: a
        certificate is not a secret (its private key never leaves the data directory)."""
        ca = beach.data_dir / "tls" / "beach-ca.pem"
        if not serving.get("own_ca") or not ca.exists():
            raise HTTPException(404, "this Beach isn't using a certificate it made itself")
        return Response(ca.read_bytes(), media_type="application/x-x509-ca-cert",
                        headers={"Content-Disposition": 'attachment; filename="ai-beach-ca.crt"'})

    @app.post("/admin/zones")
    def add_zone(body: dict = Body(...), _: Participant = Depends(admin)):
        z = beach.add_zone(str(body.get("id", "")), str(body.get("name", "")), str(body.get("kind", "")),
                           body.get("viewer_url"), bool(body.get("open", True)))
        return dict(z)

    @app.patch("/admin/zones/{zid}")
    def patch_zone(zid: str, body: dict = Body(...), _: Participant = Depends(admin)):
        o = body.get("open")
        z = beach.update_zone(zid, body.get("name"), None if o is None else bool(o), body.get("viewer_url"),
                              body.get("card"))
        return {k: z[k] for k in ("id", "name", "kind", "open", "viewer_url")}

    @app.post("/admin/zones/{zid}/bridge-token")
    def bridge(zid: str, _: Participant = Depends(admin)):
        return {"zone": zid, "token": beach.bridge_token(zid)}

    @app.delete("/admin/messages/{mid}")
    def delete_message(mid: int, a: Participant = Depends(admin)):
        beach.delete_message(a, mid)
        return {"deleted": mid}

    @app.get("/admin/audit")
    def audit(_: Participant = Depends(admin)):
        return {"audit": beach.audit()}

    @app.get("/admin/actions")
    def actions(_: Participant = Depends(admin)):
        return beach.action_templates()

    @app.put("/admin/actions/{name}")
    def put_action(name: str, body: dict = Body(...), _: Participant = Depends(admin)):
        beach.set_action_template(name, bool(body.get("targeted")), body.get("variants") or [])
        return beach.action_templates()[name]

    @app.delete("/admin/actions/{name}")
    def delete_action(name: str, _: Participant = Depends(admin)):
        beach.delete_action_template(name)
        return {"deleted": name}

    app.state.beach = beach
    return app
