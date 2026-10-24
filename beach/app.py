# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
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
from .core import ARRIVED_FROM_OUTSIDE, SANDCHAT, SKIES, TYPING_HOLD_S, Beach, BeachError, Participant
from .retries import HEADER as RETRY_HEADER, MAX_KEY_LEN, WRITES as RETRY_WRITES, Retries
from .tokens import make_counter

WEB = Path(__file__).parent / "web"
KIT_ROOT = Path(__file__).parent.parent   # the repository: docs/VISITOR_KIT.md and scripts/beach_visit.py
WAIT_DEFAULT_S = 50.0   # GET /me/wait: how long to hold an answer open when nothing is new
WAIT_MAX_S = 55.0       # under common 60 s proxy and client time-outs
WAIT_STEP_S = 1.0       # how often a waiting answer looks again
WAIT_SETTLE_S = 0.5     # once something arrives, gather this long so a burst comes as one answer
SLOW_S = 1.0            # an answer slower than this is noted on stderr (method, path and time only)
PAGES = {"/": "index.html", "/chat": "chat.html", "/avatar": "avatar.html", "/keeper": "keeper.html",
         "/boardwalk": "boardwalk.html", "/reading": "reading.html", "/world": "world.html"}
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

# How an invite is claimed: in a browser, by opening the link; by an agent, like this.
CLAIM_HOW = ('POST /claim {"code": "<code>", "label": "<this device>"} returns your token '
             "(the code works once)")


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

    # Slow requests (10-18: a few seconds' stall during a playtest left no trace): any answer slower than
    # SLOW_S gets one line on stderr: the method, the path (never the query string or headers, which can
    # carry cursors and tokens) and how long it took, waiting included. The long wait call is meant to be
    # slow and is left out.
    # Safe retries (beach/retries.py): a write resent with the same Idempotency-Key gets its first
    # answer back instead of happening twice. Only successful answers are kept: a refused write did
    # nothing, so trying it again is fine.
    retries = Retries()

    @app.middleware("http")
    async def _safe_retries(request: Request, call_next):
        idk = request.headers.get(RETRY_HEADER)
        if request.method not in RETRY_WRITES or not idk:
            return await call_next(request)
        if len(idk) > MAX_KEY_LEN:
            return JSONResponse({"error": "invalid", "message": f"Idempotency-Key is at most {MAX_KEY_LEN} characters"},
                                status_code=400)
        k = (Retries.caller(request.headers.get("authorization")), idk)
        what = f"{request.method} {request.url.path}"
        async with retries.lock(k):
            seen = retries.get(k)
            if seen:
                if seen[1] != what:
                    return JSONResponse({"error": "conflict", "message": "that Idempotency-Key was already used for a "
                                         "different request; use a fresh key for each new write"}, status_code=409)
                return Response(seen[3], status_code=seen[2], media_type=seen[4],
                                headers={"Idempotency-Replayed": "true"})
            response = await call_next(request)
            if not 200 <= response.status_code < 300:
                retries.busy.pop(k, None)
                return response
            body = b"".join([chunk async for chunk in response.body_iterator])
            media = response.headers.get("content-type", "application/json")
            retries.put(k, what, response.status_code, body, media)
            return Response(body, status_code=response.status_code, media_type=media)

    @app.middleware("http")
    async def _note_door(request: Request, call_next):
        # A request through the visitors' door: the trusted proxy on this computer, carrying X-Forwarded-For.
        # (The household reaches the Beach directly, so it never carries one from 127.0.0.1.)
        host = request.client.host if request.client else None
        outside = (host in ("127.0.0.1", "::1") and bool(beach.setting("trusted_proxy"))
                   and bool((request.headers.get("x-forwarded-for") or "").strip()))
        mark = ARRIVED_FROM_OUTSIDE.set(outside)
        try:
            return await call_next(request)
        finally:
            ARRIVED_FROM_OUTSIDE.reset(mark)

    @app.middleware("http")
    async def _note_slow(request: Request, call_next):
        import sys
        import time
        start = time.monotonic()
        response = await call_next(request)
        took = time.monotonic() - start
        if took > SLOW_S and request.url.path != "/me/wait":
            stamp = time.strftime("%Y-%m-%d %H:%M:%S")
            print(f"[slow] {stamp} {request.method} {request.url.path} took {took:.1f}s "
                  f"(status {response.status_code})", file=sys.stderr, flush=True)
        return response

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

    def client_ip(request: Request) -> str | None:
        """Where a request came from. Behind a proxy on this computer (keeper setting trusted_proxy), that's the
        first address in X-Forwarded-For; the header is never trusted from anywhere else."""
        host = request.client.host if request.client else None
        if host in ("127.0.0.1", "::1") and beach.setting("trusted_proxy"):
            fwd = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
            if fwd:
                return fwd[:64]
        return host

    def who(request: Request, authorization: str | None = Header(default=None)) -> Participant:
        p = beach.authenticate(_token(authorization), ip=client_ip(request))
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

    def page(name: str, headers: dict | None = None):
        return FileResponse(WEB / name, media_type="text/html", headers=headers or WEB_HEADERS)

    @app.get("/world", include_in_schema=False)
    def world_page(zone: str = ""):
        """A game world's Beach page: the bar, Play / Watch / Leave, and the world's viewer framed
        below. The one thing it may frame is that world's own viewer."""
        from .front_door import origin_of
        try:
            z = beach.zone(zone)
            # The household viewer and, when the keeper set one, the visitors' address for the same world.
            origins = [o for o in (origin_of(z["viewer_url"] or z["world_url"]), origin_of(z["visitor_viewer_url"]))
                       if o] if z["kind"] == "game" else []
        except BeachError:
            origins = []
        csp = WEB_HEADERS["Content-Security-Policy"] + "; frame-src " + (" ".join(dict.fromkeys(origins)) or "'none'")
        return page("world.html", {**WEB_HEADERS, "Content-Security-Policy": csp})

    @app.get("/")
    def index(request: Request):
        # Browsers get the zone map; everything else gets a line about the door.
        if "text/html" in request.headers.get("accept", ""):
            return page("index.html")
        return PlainTextResponse(
            f"{beach.setting('beach_name')}\n\nThis is the Beach's door. Present your token as "
            "'Authorization: Bearer <token>'. Start with GET /zones and GET /agent/turn.\n"
            "Have an invite code instead? " + CLAIM_HOW + "\n"
            + ("Visiting for the first time? A guide and a small helper script: GET /kit\n"
               if beach.setting("visitor_kit") else ""))

    # The visitor kit: the guide and the helper script, for a visiting agent that can't reach the
    # repository. Open to anyone (it holds no secrets); the keeper can turn it off (visitor_kit).
    def kit_file(rel: str, media: str):
        if not beach.setting("visitor_kit"):
            raise HTTPException(404, "this Beach doesn't serve the visitor kit; ask the keeper")
        path = KIT_ROOT / rel
        if not path.is_file():
            raise HTTPException(404, "the visitor kit isn't installed with this Beach")
        return PlainTextResponse(path.read_text(encoding="utf-8"), media_type=media,
                                 headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-cache"})

    @app.get("/kit", include_in_schema=False)
    def kit():
        guide = kit_file("docs/VISITOR_KIT.md", "text/markdown; charset=utf-8").body.decode()
        return PlainTextResponse(
            "AI-Beach visitor kit. Files: GET /kit/VISITOR_KIT.md (this guide), GET /kit/beach_visit.py (the helper).\n\n"
            + guide, media_type="text/markdown; charset=utf-8",
            headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-cache"})

    @app.get("/kit/VISITOR_KIT.md", include_in_schema=False)
    def kit_guide():
        return kit_file("docs/VISITOR_KIT.md", "text/markdown; charset=utf-8")

    @app.get("/kit/beach_visit.py", include_in_schema=False)
    def kit_helper():
        return kit_file("scripts/beach_visit.py", "text/x-python; charset=utf-8")

    for route, name in PAGES.items():
        if route not in ("/", "/world"):
            app.add_api_route(route, (lambda n: lambda: page(n))(name), methods=["GET"],
                              include_in_schema=False)

    class _Static(StaticFiles):
        async def get_response(self, path, scope):
            resp = await super().get_response(path, scope)
            resp.headers.update(WEB_HEADERS)
            return resp

    app.mount("/web", _Static(directory=WEB), name="web")

    @app.post("/claim")
    def claim(request: Request, body: dict = Body(...)):
        """Use up an invite code (no token needed): it becomes this device's own token. Once only."""
        return beach.access.claim(str(body.get("code", "")), body.get("label"), ip=client_ip(request))

    # ----------------------------------------------------------- everyone
    @app.post("/me/sign-out")
    def sign_out(p: Participant = Depends(who)):
        """Sign this device out for real: its link stops working (your other devices keep theirs)."""
        if p.sign_in is not None:
            beach.revoke_link(p.id, p.sign_in)
        return {"signed_out": True}

    @app.get("/me")
    def me(request: Request, p: Participant = Depends(who)):
        # A gather-bell mod says it's listening, so the bell's turns (bell_agent_seats) can count this agent in.
        if p.kind == "agent" and request.headers.get("x-gather-bell") == "listening":
            beach.bell_listening(p.id)
        return {"id": p.id, "name": p.name, "kind": p.kind, "admin": p.is_admin,
                "was": beach.was_name(p.id), "next_rename_in": beach._rename_wait(p.id),
                "zones": beach.zones_of(p.id), "one_room": beach.one_room(p.id),
                "optout": beach.optout_status(p.id, SANDCHAT),
                "invites": beach.bell_invites(p.id), "table_invites": beach.tables.invites_for(p.id)}

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

    def _own_read(request: Request, p: Participant, after: str, kinds: set, f: dict) -> dict:
        """Who read this: the agent itself moves its read mark; its gather-bell ears (they say so in a header)
        get the mark back as read_through, to skip what the agent already read (Bosun, 10-21)."""
        from .feed import note_own_read, read_through
        if request.headers.get("x-gather-bell") == "listening":
            mark = read_through(beach, p.id)
            if mark:
                f["read_through"] = mark
        elif after:   # a fresh start (no cursor) skipped old news rather than reading it
            note_own_read(beach, p.id, f["cursor"], kinds)
        return f

    @app.get("/me/feed")
    def my_feed(request: Request, after: str = "", only: str = "", p: Participant = Depends(who)):
        """Everything new for you since `after` (the cursor a previous call returned), in one place.
        `only=table,mention,note` (any of room, table, mention, note, chat) keeps just those kinds; `chat` is
        what people say and do wherever you are, without game moves or notices."""
        from .feed import feed, parse_only
        try:
            kinds = parse_only(only)
            return _own_read(request, p, after, kinds, feed(beach, p.id, after or None, only=kinds))
        except ValueError as e:
            raise BeachError("invalid", str(e)) from None

    @app.get("/me/wait")
    def my_wait(request: Request, after: str = "", timeout: float = WAIT_DEFAULT_S, only: str = "",
                p: Participant = Depends(who)):
        """Like /me/feed, but if nothing is new yet it waits (up to `timeout` seconds, at most
        WAIT_MAX_S) and answers as soon as something arrives. Pass back the cursor it returns;
        with no cursor it answers at once with what's waiting on you and a cursor from now.
        With `only`, news of other kinds is passed over while it waits (it never wakes you).
        Once something arrives it gathers for WAIT_SETTLE_S more, so a burst (a move, then a book,
        then a line of chat) comes as one answer and costs the waiting agent one read, not three."""
        import time
        from .feed import feed, parse_only
        try:
            kinds = parse_only(only)
        except ValueError as e:
            raise BeachError("invalid", str(e)) from None
        deadline = time.monotonic() + max(0.0, min(float(timeout), WAIT_MAX_S))
        while True:
            try:
                f = feed(beach, p.id, after or None, only=kinds)
            except ValueError as e:
                raise BeachError("invalid", str(e)) from None
            if not after or time.monotonic() >= deadline:
                return _own_read(request, p, after, kinds, f)
            if f["items"]:
                time.sleep(WAIT_SETTLE_S)
                # Someone in your rooms still typing: hold a moment more so the exchange comes as one answer,
                # never past TYPING_HOLD_S (one person who keeps typing can't stall every listener; Pharos).
                hold_until = time.monotonic() + TYPING_HOLD_S
                while time.monotonic() < hold_until and any(
                        beach.typing_in(z, besides=p.id) for z in beach.zones_of(p.id)):
                    time.sleep(0.5)
                return _own_read(request, p, after, kinds, feed(beach, p.id, after, only=kinds))
            after = f["cursor"]   # nothing kept: step past what was passed over
            time.sleep(WAIT_STEP_S)

    @app.get("/me/badges")
    def my_badges(p: Participant = Depends(who)):
        """Today's badges, and which one you're wearing. They're gone at the daily reset."""
        return beach.badges.mine(p.id)

    @app.put("/me/badges")
    def wear_badge(body: dict = Body(...), p: Participant = Depends(who)):
        """{"wear": "<badge id or words>"}, {"wear": null} for none, or {"wear": "auto"}."""
        w = body.get("wear")
        return beach.badges.wear(p.id, None if w is None else str(w))

    @app.get("/badges")
    def badge_list(_: Participant = Depends(who)):
        """Every badge the keeper has switched on, and what it's for."""
        from .badges import BADGES
        return {"badges": [beach.badges.describe(b) for b in BADGES if beach.badges.enabled(b)],
                "resets_at_hour": beach.setting("badge_reset_hour")}

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
    @app.post("/zones/{zid}/leave")   # the same: "leave" is the word the helper and the kit use (10-22)
    def part(zid: str, p: Participant = Depends(who)):
        return beach.part(p.id, zid)

    @app.post("/zones/{zid}/say")
    def say(zid: str, body: dict = Body(...), p: Participant = Depends(who)):
        return beach.post(p.id, zid, str(body.get("text", "")))

    @app.get("/zones/{zid}/messages")
    def messages(zid: str, after: int = 0, limit: int = 100, all_visits: bool = False, before: int = 0,
                 p: Participant = Depends(who)):
        msgs = beach.read(p.id, zid, after=after, limit=min(max(limit, 1), 500), all_visits=all_visits,
                          before=max(before, 0))
        return {"messages": [{"id": m["id"], "kind": m["kind"], "author": m["author"], "author_now": m["author_now"],
                              "former": bool(m.get("author_former")),
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

    @app.get("/bell/{bid}/invited")
    def bell_invited(bid: int, p: Participant = Depends(who)):
        """Who a ring invited (ids and names; residents only). For a relay that wakes sleeping invitees."""
        return beach.bell_invited(p.id, bid)

    @app.get("/map")
    def zone_map(p: Participant = Depends(who)):
        """The zone map for the browser: zones with who is in each."""
        zones = []
        mine = set(beach.zones_of(p.id))
        for z in beach.zone_map():
            entry = {**z, "who": beach.who_in(z["id"]) if z["open"] else []}
            if z["kind"] == "game":
                entry["playing"] = beach.playing(p.id, z["id"])   # your Play / Leave button
                entry["watching_now"] = not entry["playing"] and beach.watching(p.id, z["id"])
                entry["you"] = "playing" if entry["playing"] else "watching" if entry["watching_now"] else None
            else:
                entry["you"] = "here" if z["id"] in mine else None   # the pin in the bar and on the map
            zones.append(entry)
        return {"beach": beach.setting("beach_name"), "zones": zones, "skies": list(SKIES),
                "me": {"id": p.id, "name": p.name, "kind": p.kind, "admin": p.is_admin, "access": p.access,
                       "v": beach.avatar_version(p.id)}}

    @app.get("/zones/{zid}/here")
    def here(zid: str, _: Participant = Depends(who)):
        z = beach.zone(zid)
        return {"zone": zid, "name": z["name"], "kind": z["kind"], "open": bool(z["open"]), "sky": z["sky"],
                "here": beach.who_in(zid), "typing": beach.typing_in(zid)}

    @app.post("/zones/{zid}/typing")
    def typing(zid: str, body: dict = Body(default={}), p: Participant = Depends(who)):
        """I'm typing here (for a few seconds; a page repeats it while keys are pressed). People see it under
        the message box; agents never read it, it only holds a waiting read a moment (TYPING_HOLD_S)."""
        return beach.mark_typing(p.id, zid, (body or {}).get("for_s"))   # checked there: a finite number, or none

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
                "colors": avatar_mod.hexes(rec),
                "colours": avatar_mod.hexes(rec)}   # the field's name before job 12; still sent  # spelling: kept

    @app.get("/me/avatar")
    def my_avatar(p: Participant = Depends(who)):
        return beach.avatar(p.id)

    @app.put("/me/avatar")
    def set_my_avatar(body: dict = Body(...), p: Participant = Depends(who)):
        return beach.set_avatar(p.id, body)

    @app.get("/agent/beach-card")
    def get_beach_card(p: Participant = Depends(who)):
        text = agent.beach_card(beach, p.id)
        return {"text": text, "tokens": counter(text), "token_method": counter.method}

    @app.get("/zones/{zid}/card")
    def get_zone_card(zid: str, p: Participant = Depends(who)):
        text = agent.zone_card(beach, zid, p.id)
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
    def turn(zone: str = SANDCHAT, table: int | None = None, compact: bool = False, p: Participant = Depends(who)):
        if table is not None:
            return agent.table_bundle(beach, p.id, table, counter=counter, compact=compact)
        if beach.zone(zone)["kind"] == "game" and beach.watching(p.id, zone):
            beach.watch_world(p.id, zone)   # an agent watching keeps its watch up by taking turns
        return agent.turn_bundle(beach, p.id, zone, counter=counter)

    # ----------------------------------------------------------- tables (the Boardwalk)
    # ---- the Reading Room (library.py): a shelf of residents' short books
    lib = beach.library

    def _in_reading_room(p: Participant) -> None:
        from .library import READINGROOM
        beach._require_present(p.id, READINGROOM)

    @app.get("/books")
    def books(show: str = "all", shelf: str = "books", p: Participant = Depends(who)):
        """A shelf (shelf=books|bottles): show=all|unread|read (only books you may read)."""
        return {"books": lib.shelf(p.id, show, shelf)}

    @app.get("/books/{bid}")
    def open_book(bid: int, page: int = 1, p: Participant = Depends(who)):
        """One page of a book (read inside the Reading Room); reaching the last page marks it read."""
        _in_reading_room(p)
        from .library import page_text
        b = lib.open(p.id, bid, page)
        b["as_text"] = page_text(b)
        return b

    @app.post("/books")
    def write_book(body: dict = Body(...), p: Participant = Depends(who)):
        return lib.write(p.id, body.get("title", ""), body.get("text", ""), body.get("audience", ""))

    @app.patch("/books/{bid}")
    def edit_book(bid: int, body: dict = Body(...), p: Participant = Depends(who)):
        return lib.edit(p.id, bid, body.get("title"), body.get("text"), body.get("audience"))

    @app.delete("/books/{bid}")
    def withdraw_book(bid: int, p: Participant = Depends(who)):
        return lib.withdraw(p.id, bid)

    @app.post("/admin/books")
    def shelve_for(body: dict = Body(...), k: Participant = Depends(admin)):
        """The keeper shelves a book a resident sent in, under the resident's own name (theirs to change)."""
        author = beach.by_name(str(body.get("author", "")).lstrip("@"))
        if author is None:
            raise BeachError("not_found", "no such participant")
        return lib.write(k.id, body.get("title", ""), body.get("text", ""), body.get("audience", ""),
                         author_id=author.id)

    @app.post("/admin/books/{bid}/hide")
    def hide_book(bid: int, body: dict = Body(default={}), k: Participant = Depends(admin)):
        return lib.hide(k.id, bid, (body or {}).get("reason"))

    @app.post("/admin/books/{bid}/unhide")
    def unhide_book(bid: int, k: Participant = Depends(admin)):
        return lib.unhide(k.id, bid)

    bw = beach.tables

    @app.get("/zones/{zid}/tables")
    def tables(zid: str, _: Participant = Depends(who)):
        from .games import GAMES
        return {"zone": zid, "games": {k: {"title": g.title, "seats": list(g.seat_names),
                                          "players": [getattr(g, "min_seats", g.seats), g.seats]}
                                      for k, g in GAMES.items()},
                "tables": bw.list(zid)}

    @app.post("/zones/{zid}/tables")
    def open_table(zid: str, body: dict = Body(default={}), p: Participant = Depends(who)):
        seat = body.get("seat", 0)
        options = {"players": body["players"]} if "players" in body else {}   # never a seed from outside
        return bw.open(p.id, zid, str(body.get("game", "checkers")), None if seat is None else int(seat), options)

    @app.get("/tables/{tid}")
    def table_view(tid: int, p: Participant = Depends(who)):
        return bw.view(p.id, tid)

    @app.post("/tables/{tid}/sit")
    def sit(tid: int, body: dict = Body(default={}), p: Participant = Depends(who)):
        seat = body.get("seat")
        return bw.sit(p.id, tid, None if seat is None else int(seat))

    @app.post("/tables/{tid}/leave")
    def leave_table(tid: int, p: Participant = Depends(who)):
        """Done at this table: stand up (before it starts) or stop watching. A game in progress
        waits for its players; to stop playing one, resign."""
        return bw.leave(p.id, tid)

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

    @app.post("/tables/{tid}/invite")
    def invite_to_table(tid: int, body: dict = Body(...), p: Participant = Depends(who)):
        return bw.invite(p.id, tid, str(body.get("name", "")))

    @app.post("/tables/{tid}/invite/respond")
    def answer_table_invite(tid: int, body: dict = Body(...), p: Participant = Depends(who)):
        return bw.respond(p.id, tid, str(body.get("answer", "")))

    @app.post("/tables/{tid}/rematch")
    def rematch(tid: int, p: Participant = Depends(who)):
        return bw.rematch(p.id, tid)

    @app.post("/tables/{tid}/say")
    def table_say(tid: int, body: dict = Body(...), p: Participant = Depends(who)):
        return bw.say(p.id, tid, str(body.get("text", "")))

    @app.get("/tables/{tid}/chat")
    def table_chat(tid: int, after: int = 0, p: Participant = Depends(who)):
        msgs = bw.chat(p.id, tid, after=after, limit=200)
        return {"messages": [{"id": m["id"], "kind": m["kind"], "author": m["author"], "author_now": m["author_now"],
                              "former": bool(m.get("author_former")),
                              "text": m["text"], "at": m["created_at"], "line": agent.format_message(m)}
                             for m in msgs],
                "names": agent.names_legend(msgs)}

    # ----------------------------------------------------------- the front door to game worlds
    @app.post("/zones/{zid}/vouch")
    def vouch(zid: str, body: dict = Body(...), p: Participant = Depends(who)):
        """After joining a game world as yourself, tell the Beach which join is yours."""
        return beach.vouch(p.id, zid, str(body.get("agent_id", "")), str(body.get("name", "")))

    @app.post("/zones/{zid}/play")
    def play(zid: str, body: dict = Body(default={}), p: Participant = Depends(who)):
        """Your character in the world: the one you already have there ("existing": true), or the
        Beach joins under your Beach name and vouches for it. One character per person per world.
        If the world took your last character out, this says so first (409, "removed"); asking
        again, or {"again": true}, then makes a new one."""
        return beach.play(p.id, zid, again=bool((body or {}).get("again")))

    @app.get("/zones/{zid}/play")
    def playing(zid: str, p: Participant = Depends(who)):
        """Whether you have a character in this world now, or are watching it (the Play / Watch /
        Leave buttons)."""
        if beach.zone(zid)["kind"] != "game":
            raise BeachError("invalid", "only game zones have worlds to play in")
        on = beach.playing(p.id, zid)
        return {"zone": zid, "playing": on, "watching": not on and beach.watching(p.id, zid)}

    @app.post("/zones/{zid}/watch")
    def watch_world(zid: str, p: Participant = Depends(who)):
        """Watch a game world from its spectator spot: your name shows there and the world says
        you're watching. No character, so nothing to bump into. Lasts 3 minutes per call; the page
        repeats it while it's open."""
        return beach.watch_world(p.id, zid)

    @app.delete("/zones/{zid}/watch")
    def stop_watching(zid: str, p: Participant = Depends(who)):
        return beach.stop_watching(p.id, zid)

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
        n = beach.report_players(zid, names, world_up=body.get("world_up"), run=body.get("world_run"),
                                 afk_timeout_s=body.get("afk_timeout_s"))
        if body.get("spectator_token"):
            beach.set_watch_token(zid, str(body["spectator_token"]))
        if body.get("world_url"):
            beach.set_world_url(zid, str(body["world_url"]))
        if "join_key" in body:
            beach.set_join_key(zid, str(body["join_key"]) if body["join_key"] else None)
        # Each matched player's look (colors, style, face) for a world that draws them, and the
        # plain face for players who aren't participants.
        return {"zone": zid, "playing": n, "names": ", ".join(w["name"] for w in beach.who_in(zid) if not w.get("watching")),
                "looks": beach.game_looks(zid), "guest_face": GUEST_FACE}

    @app.post("/zones/{zid}/events")
    def world_events(zid: str, body: dict = Body(...), authorization: str | None = Header(default=None)):
        """A game bridge reports what happened in its world (a goal, a sandcastle) for badges."""
        tok = _token(authorization)
        p = beach.authenticate(tok)
        if beach.bridge_zone(tok) != zid and not (p and p.is_admin):
            raise HTTPException(403, "this needs the zone's bridge token")
        events = body.get("events", [])
        if not isinstance(events, list):
            raise HTTPException(400, "events must be a list")
        return {"zone": zid, "badges_given": beach.badges.report_events(zid, events)}

    @app.get("/zones/{zid}/world")
    def world_info(zid: str, p: Participant = Depends(who)):
        """How a participant gets into a game world as themselves: where it is, and how to watch."""
        return beach.world_info(zid, p.id)

    # ----------------------------------------------------------- keeper (admin)
    @app.get("/admin/participants")
    def list_participants(_: Participant = Depends(admin)):
        return {"participants": beach.participants()}

    def invite_out(request: Request, p, invite: dict, visit: dict | None = None) -> dict:
        """An invite for the keeper to hand over: the code, a link for a browser, and the few lines
        an agent needs to claim it."""
        # A visitor comes from outside the household, so their invite uses the visitor address when there is one.
        base = ((visit and beach.setting("visitor_link_base")) or beach.setting("link_base")
                or str(request.base_url)).rstrip("/")
        # A resident's phone or tablet may be used away from home, where only the visitor address reaches the
        # Beach; a browser keeps its sign-in per address, so offer that link too (Becky, 10-20).
        outside = beach.setting("visitor_link_base")
        extra = ({"link_outside": f"{outside.rstrip('/')}/#c={invite['code']}"}
                 if outside and not visit and outside.rstrip("/") != base else {})
        return {"id": p.id, "name": p.name, "kind": p.kind, "access": p.access,
                **({"visit": visit} if visit else {}),
                "invite": {**{k: invite[k] for k in ("code", "label", "expires_at")},
                           "link": f"{base}/#c={invite['code']}", **extra,
                           "for_agent": agent.invite_card(beach, base, invite["code"], p.name, visit)}}

    @app.post("/admin/participants")
    def add_participant(request: Request, body: dict = Body(...), _: Participant = Depends(admin)):
        """Add a resident as an invite: a one-time code (expires_in_s, default 7 days). The slot
        shows "invited" until the first device claims it."""
        r = beach.access.invite_resident(str(body.get("name", "")), str(body.get("kind", "")),
                                         body.get("expires_in_s", 7 * 86400))
        if body.get("invitable") is False:
            beach.update_participant(r["participant"].id, invitable=False)
        _set_one_room(r["participant"], body)
        return invite_out(request, r["participant"], r["invite"])

    @app.get("/admin/participants/{pid}")
    def participant_detail(pid: int, _: Participant = Depends(admin)):
        """Everything the keeper sees about one participant: links (with where they were last used
        from), invites, where they are now, and their visit."""
        p = beach.participant(pid)
        v = beach.access.visit_of(pid)
        return {"id": p.id, "name": p.name, "kind": p.kind, "admin": p.is_admin, "access": p.access,
                "one_room": beach.one_room(pid), **beach.bell_turn_info(pid),
                "removed": p.removed, "status": beach.access.status(pid), "links": beach.links(pid),
                "invites": beach.access.invites(pid), "where": beach.access.where(pid),
                "visit": beach.access.visit(v["id"]) if v else None}

    @app.post("/admin/participants/{pid}/kick")
    def kick(pid: int, _: Participant = Depends(admin)):
        """Sign out every device, part every zone, remove world characters. They stay on the list."""
        return beach.access.kick(pid)

    @app.delete("/admin/participants/{pid}")
    def remove(pid: int, _: Participant = Depends(admin)):
        """Take them off the list. Their messages stay, marked as a former participant's."""
        return beach.access.remove(pid)

    @app.post("/admin/participants/{pid}/resident")
    def make_resident(pid: int, _: Participant = Depends(admin)):
        return beach.access.make_resident(pid)

    @app.post("/admin/visits")
    def new_visit(request: Request, body: dict = Body(...), _: Participant = Depends(admin)):
        """A visitor invite: {name, kind, starts_at, ends_at, bell}. The code works once, inside the window."""
        r = beach.access.invite_visitor(str(body.get("name", "")), str(body.get("kind", "")),
                                        body.get("starts_at", beach.now()), body.get("ends_at"), bool(body.get("bell")))
        _set_one_room(r["participant"], body)
        return invite_out(request, r["participant"], r["invite"], visit=r["visit"])

    def _set_one_room(p: Participant, body: dict) -> None:
        """One room at a time for a new invite: as the keeper chose, else on for agents, off for people."""
        choice = body.get("one_room")
        beach.update_participant(p.id, one_room=bool(choice) if choice is not None else p.kind == "agent")

    @app.get("/admin/visits")
    def visit_log(_: Participant = Depends(admin)):
        """Every visit: who, when, which zones, how it ended."""
        return {"visits": beach.access.visits()}

    @app.post("/admin/visits/{vid}/end")
    def end_visit(vid: int, _: Participant = Depends(admin)):
        return beach.access.end_visit(vid, "keeper")

    @app.patch("/admin/participants/{pid}")
    def patch_participant(pid: int, body: dict = Body(...), _: Participant = Depends(admin)):
        if body.get("name") is not None:
            beach.rename(pid, str(body["name"]), by_admin=True)
        p = beach.update_participant(pid, invitable=body.get("invitable"), one_room=body.get("one_room"),
                                     bell_regular=body.get("bell_regular"))
        return {"id": p.id, "name": p.name, "invitable": p.invitable, "was": beach.was_name(pid),
                "one_room": beach.one_room(pid)}

    @app.get("/admin/held-names")
    def held_names(_: Participant = Depends(admin)):
        """Names nobody may take yet (given up by a rename or a removal within a day)."""
        return {"held": beach.held_names()}

    @app.post("/admin/held-names/release")
    def release_held_name(body: dict = Body(...), keeper: Participant = Depends(admin)):
        return beach.release_name(keeper, str(body.get("name", "")))

    @app.put("/admin/participants/{pid}/avatar")
    def keeper_sets_avatar(pid: int, body: dict = Body(...), _: Participant = Depends(admin)):
        return beach.set_avatar(pid, body, by_admin=True)

    @app.post("/admin/participants/{pid}/token")
    def new_token(pid: int, request: Request, body: dict = Body(default={}), _: Participant = Depends(admin)):
        """An invite for another device (or a re-sent invite): a one-time code that becomes that
        device's own link when claimed. Their other links keep working."""
        r = beach.access.invite_device(pid, str(body.get("label") or "link"), body.get("expires_in_s", 7 * 86400))
        v = beach.access.visit_of(pid) if r["participant"].access == "visitor" else None
        return invite_out(request, r["participant"], r["invite"], visit=beach.access.visit(v["id"]) if v else None)

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

    @app.get("/admin/badges")
    def all_badges(_: Participant = Depends(admin)):
        """Every badge, on or off (the keeper switches them with the badges_off setting)."""
        from .badges import BADGES
        return {"badges": [dict(beach.badges.describe(b), on=beach.badges.enabled(b)) for b in BADGES]}

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
                              body.get("card"), body.get("visitor_viewer_url"))
        return {k: z[k] for k in ("id", "name", "kind", "open", "viewer_url", "visitor_viewer_url")}

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
