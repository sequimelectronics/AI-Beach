"""Tests for job 05's pieces: avatars (validation, the describe sentence, images, the
look-change cooldown), the browser's map and pages, and the BeachBlox bridge.

All against a temporary data directory with a fake clock. The core-level tests
need only the standard library; the HTTP and bridge tests need FastAPI + httpx.
"""

from __future__ import annotations

import json
import random
import shutil
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from beach import avatar, colours  # noqa: E402
from beach.core import SANDCHAT, Beach, BeachError  # noqa: E402

try:
    from fastapi.testclient import TestClient
    HAVE_FASTAPI = True
except ImportError:  # pragma: no cover
    HAVE_FASTAPI = False


class FakeClock:
    def __init__(self, t: float = 1_800_000_000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class ColourTests(unittest.TestCase):
    def test_accepts_hex_and_names(self):
        self.assertEqual(colours.parse("#2A9D8F"), ("#2a9d8f", "#2a9d8f"))
        self.assertEqual(colours.parse("#abc"), ("#aabbcc", "#aabbcc"))
        self.assertEqual(colours.parse("2a9d8f")[1], "#2a9d8f")
        self.assertEqual(colours.parse("Sea Green"), ("sea green", "#2e8b57"))
        self.assertEqual(colours.parse("seagreen")[1], "#2e8b57")
        self.assertEqual(colours.parse("sunset orange")[1], "#fd5e53")
        self.assertEqual(colours.parse("dark-slate-grey")[1], "#2f4f4f")

    def test_refuses_invented_colours_with_a_hint(self):
        for bad in ["#ggg", "#12345", "#1234567", "", "   ", "blurple", "sea grean", "rgb(1,2,3)",
                    "x" * 50, None, 12, ["teal"]]:
            with self.assertRaises(colours.ColourError, msg=repr(bad)):
                colours.parse(bad)
        with self.assertRaises(colours.ColourError) as cm:
            colours.parse("sea grean")
        self.assertIn("sea green", str(cm.exception))

    def test_hex_described_in_plain_words(self):
        self.assertEqual(colours.words("#ffbf00", "#ffbf00"), "amber")
        self.assertEqual(colours.words("#008080", "#008080"), "teal")
        self.assertEqual(colours.words("sunset orange", "#fd5e53"), "sunset orange")


class AvatarTests(unittest.TestCase):
    def setUp(self):
        self.base = avatar.default_record(1)

    def test_validate_merges_and_normalises(self):
        rec = avatar.validate({"hair": "Teal", "preset": "BUN", "accessory": "sun hat", "theme": "night tide"},
                              self.base)
        self.assertEqual(rec["hair"], "teal")
        self.assertEqual(rec["preset"], "bun")
        self.assertEqual(rec["accessory"], "sunhat")
        self.assertEqual(rec["theme"], "night-tide")
        self.assertEqual(rec["eyes"], self.base["eyes"])  # untouched fields kept

    def test_validate_refuses_bad_fields(self):
        for bad in [{"hair": "#zzz"}, {"preset": "mohawk"}, {"theme": "neon"}, {"skin": "green"},
                    {"accessory": "crown"}, {"colour": "red"}, {"eyes": None}, "teal"]:
            with self.assertRaises(avatar.AvatarError, msg=repr(bad)):
                avatar.validate(bad, self.base)

    def test_describe_is_one_short_sentence(self):
        rec = avatar.validate({"preset": "short", "hair": "teal", "eyes": "#ffbf00", "theme": "lagoon",
                               "accessory": "sunhat"}, self.base)
        self.assertEqual(avatar.describe(rec),
                         "A chibi with short teal hair, amber eyes, a teal-and-white outfit and a floppy sun hat.")
        rec = avatar.validate({"accessory": "none", "preset": "bun"}, rec)
        self.assertEqual(avatar.describe(rec), "A chibi with teal hair in a bun, amber eyes and a teal-and-white outfit.")

    def test_every_combination_draws(self):
        for i, p in enumerate(avatar.PRESETS):
            for acc in avatar.ACCESSORIES:
                rec = avatar.validate({"preset": p, "accessory": acc,
                                       "theme": list(avatar.THEMES)[i % len(avatar.THEMES)]}, self.base)
                s = avatar.svg(rec)
                self.assertTrue(s.startswith("<svg") and s.endswith("</svg>"))
                for layer in ("hair-back", "body", "outfit", "head", "eyes", "hair"):
                    self.assertIn(f'class="av-{layer}"', s)
        self.assertNotIn("<script", s)

    def test_recolour_changes_only_its_layer(self):
        a = avatar.validate({"hair": "teal"}, self.base)
        b = avatar.validate({"hair": "coral"}, self.base)
        la, lb = dict(avatar.layers(a)), dict(avatar.layers(b))
        changed = [k for k in la if la[k] != lb[k]]
        self.assertEqual(sorted(changed), ["hair", "hair-back"])

    def test_png_is_a_real_image(self):
        data = avatar.png(self.base, 64)
        self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"))
        w, h = int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
        self.assertEqual((w, h), (64, 76))
        idat = data[data.index(b"IDAT") + 4:data.index(b"IEND") - 8]
        raw = zlib.decompress(idat)
        self.assertEqual(len(raw), h * (1 + w * 4))
        self.assertTrue(any(raw[i] for i in range(4, len(raw), 4)))  # not blank

    def test_card_is_small(self):
        text = avatar.card(3600)
        self.assertIn("PUT /me/avatar", text)
        self.assertIn("once per 60 min", text)
        self.assertLess(len(text) / 4, 150)
        # With the Gemma tokenizer (AI_BEACH_TOKENIZER), the real limit: at most 150 tokens.
        from beach.tokens import make_counter
        counter = make_counter()
        if counter.method.startswith("tokenizer"):
            self.assertLessEqual(counter(text), 150)


class AvatarCoreTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="beach-front-")
        self.clock = FakeClock()
        self.beach = Beach(self.dir, clock=self.clock, rng=random.Random(3))
        self.beach.ensure_admin()
        self.coral, _ = self.beach.add_participant("Coral", "person")
        self.sandy, _ = self.beach.add_participant("Sandy", "agent")

    def tearDown(self):
        self.beach.db.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_everyone_has_a_default_look(self):
        a = self.beach.avatar(self.coral.id)
        self.assertFalse(a["chosen"])
        self.assertTrue(a["describe"].startswith("A chibi with "))
        self.assertEqual(a["next_change_in"], 0)
        self.assertEqual(self.beach.avatar_version(self.coral.id), 0)

    def test_cooldown_first_change_free_then_once_an_hour(self):
        self.assertEqual(self.beach.setting("avatar_cooldown_s"), 3600)
        self.beach.set_avatar(self.coral.id, {"hair": "teal"})
        with self.assertRaises(BeachError) as cm:
            self.beach.set_avatar(self.coral.id, {"hair": "coral"})
        self.assertEqual(cm.exception.code, "cooldown")
        self.assertAlmostEqual(cm.exception.retry_after, 3600, delta=1)
        self.assertEqual(self.beach.avatar(self.coral.id)["avatar"]["hair"], "teal")
        self.clock.advance(1800)
        with self.assertRaises(BeachError):
            self.beach.set_avatar(self.coral.id, {"hair": "coral"})
        self.clock.advance(1801)
        self.assertEqual(self.beach.set_avatar(self.coral.id, {"hair": "coral"})["avatar"]["hair"], "coral")

    def test_invalid_change_is_refused_and_costs_nothing(self):
        with self.assertRaises(BeachError) as cm:
            self.beach.set_avatar(self.sandy.id, {"hair": "#ggg"})
        self.assertEqual(cm.exception.code, "invalid")
        self.assertFalse(self.beach.avatar(self.sandy.id)["chosen"])
        self.beach.set_avatar(self.sandy.id, {"hair": "sea green"})  # still the free first change

    def test_keeper_can_set_any_look_without_waiting(self):
        self.beach.set_avatar(self.coral.id, {"hair": "teal"})
        self.beach.set_avatar(self.coral.id, {"hair": "gold"}, by_admin=True)
        self.assertEqual(self.beach.avatar(self.coral.id)["avatar"]["hair"], "gold")
        # A look the keeper set doesn't hold the participant to a cooldown.
        self.beach.set_avatar(self.coral.id, {"hair": "navy"})

    def test_cooldown_setting_is_the_keepers(self):
        self.beach.update_settings({"avatar_cooldown_s": 60})
        self.beach.set_avatar(self.coral.id, {"hair": "teal"})
        self.clock.advance(61)
        self.beach.set_avatar(self.coral.id, {"hair": "gold"})
        with self.assertRaises(BeachError):
            self.beach.update_settings({"avatar_cooldown_s": -5})

    def test_names_are_settings(self):
        self.beach.update_settings({"beach_name": "  Tide   Pool "})
        self.assertEqual(self.beach.setting("beach_name"), "Tide Pool")
        with self.assertRaises(BeachError):
            self.beach.update_settings({"beach_name": ""})
        self.beach.update_zone(SANDCHAT, name="The Snack Shack")
        self.assertEqual(self.beach.setting("sandchat_name"), "The Snack Shack")

    def test_who_in_maps_game_names(self):
        self.beach.add_zone("beachblox", "BeachBlox", "game")
        self.beach.update_participant(self.coral.id, game_name="CoralPlays")
        self.beach.report_players("beachblox", ["CoralPlays", "Sandy", "Visitor9"])
        who = {w["game_name"]: w for w in self.beach.who_in("beachblox")}
        self.assertEqual(who["CoralPlays"]["name"], "Coral")
        self.assertEqual(who["Sandy"]["name"], "Sandy")          # no in-game name set: matched by Beach name
        self.assertEqual(who["Visitor9"]["kind"], "guest")
        self.assertIsNone(who["Visitor9"]["id"])
        looks = self.beach.game_looks("beachblox")
        self.assertEqual(sorted(looks), ["CoralPlays", "Sandy"])
        self.assertRegex(looks["Sandy"]["outfit"], r"^#[0-9a-f]{6}$")
        # Coral's Beach name no longer matches once an in-game name is set.
        self.beach.report_players("beachblox", ["Coral"])
        self.assertEqual(self.beach.who_in("beachblox")[0]["kind"], "guest")


@unittest.skipUnless(HAVE_FASTAPI, "fastapi/httpx not installed")
class FrontApiTests(unittest.TestCase):
    def setUp(self):
        from beach.app import create_app
        self.dir = tempfile.mkdtemp(prefix="beach-front-api-")
        self.clock = FakeClock()
        self.beach = Beach(self.dir, clock=self.clock, rng=random.Random(1))
        self.admin = {"Authorization": f"Bearer {self.beach.ensure_admin()}"}
        self.http = TestClient(create_app(self.beach, upkeep_interval=None))
        tok = self.http.post("/admin/participants", json={"name": "Sandy", "kind": "agent"},
                             headers=self.admin).json()["token"]
        self.sandy = {"Authorization": f"Bearer {tok}"}
        self.sandy_id = self.beach.by_name("Sandy").id

    def tearDown(self):
        self.beach.db.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_agent_sets_avatar_in_one_call(self):
        r = self.http.put("/me/avatar", headers=self.sandy, json={
            "preset": "spiky", "theme": "sunset", "hair": "sea green", "eyes": "amber",
            "skin": "honey", "accessory": "headphones"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["describe"],
                         "A chibi with spiky sea green hair, amber eyes, an orange-and-gold outfit and headphones.")
        self.assertEqual(self.http.get("/me/avatar/describe", headers=self.sandy).json()["text"],
                         r.json()["describe"])
        again = self.http.put("/me/avatar", headers=self.sandy, json={"hair": "teal"})
        self.assertEqual(again.status_code, 429)
        self.assertIn("Retry-After", again.headers)
        bad = self.http.put("/me/avatar", headers=self.sandy, json={"eyes": "#12g"})
        self.assertEqual(bad.status_code, 400)
        self.assertIn("isn't a colour code", bad.json()["message"])

    def test_images_on_request(self):
        svg = self.http.get("/me/avatar.svg", headers=self.sandy)
        self.assertEqual(svg.headers["content-type"], "image/svg+xml")
        self.assertTrue(svg.text.startswith("<svg"))
        png = self.http.get("/me/avatar.png?size=64", headers=self.sandy)
        self.assertEqual(png.headers["content-type"], "image/png")
        self.assertTrue(png.content.startswith(b"\x89PNG"))
        other = self.http.get(f"/avatars/{self.sandy_id}.svg", headers=self.admin)
        self.assertEqual(other.status_code, 200)
        self.assertEqual(self.http.get("/me/avatar.svg").status_code, 401)
        self.assertEqual(self.http.get("/avatars/999.svg", headers=self.admin).status_code, 404)

    def test_preview_does_not_save(self):
        r = self.http.post("/avatar/preview", headers=self.sandy, json={"hair": "gold"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("gold hair", r.json()["describe"])
        self.assertFalse(self.http.get("/me/avatar", headers=self.sandy).json()["chosen"])

    def test_card_offered_on_request_not_in_sandchat_card(self):
        card = self.http.get("/avatar/card", headers=self.sandy).json()
        self.assertIn("AVATAR CARD", card["text"])
        turn = self.http.get("/agent/turn", headers=self.sandy).json()
        self.assertNotIn("avatar", turn["tools"]["text"].lower())

    def test_map_and_pages(self):
        self.http.post("/zones/sandchat/join", headers=self.sandy)
        m = self.http.get("/map", headers=self.sandy).json()
        self.assertEqual(m["beach"], "AI Beach")
        sc = [z for z in m["zones"] if z["id"] == "sandchat"][0]
        self.assertEqual([w["name"] for w in sc["who"]], ["Sandy"])
        page = self.http.get("/", headers={"Accept": "text/html"})
        self.assertEqual(page.headers["content-type"].split(";")[0], "text/html")
        self.assertIn("default-src 'self'", page.headers["content-security-policy"])
        self.assertTrue(self.http.get("/").text.startswith("AI Beach"))  # agents still get the door line
        for path in ("/chat", "/avatar", "/keeper", "/web/beach.css", "/web/common.js"):
            self.assertEqual(self.http.get(path).status_code, 200, path)

    def test_front_end_loads_nothing_from_elsewhere(self):
        import re
        loads = re.compile(r"""(src|href)\s*=\s*["']?(https?:)?//|import[^;\n]*["'](https?:)?//|"""
                           r"""url\(\s*["']?(https?:)?//|fetch\(\s*["'](https?:)?//|@import|esm\.sh|cdn|googleapis""")
        files = list((ROOT / "beach" / "web").rglob("*")) + list((ROOT / "worlds" / "beach" / "renderer" / "src").rglob("*"))
        checked = 0
        for f in files:
            if f.suffix in (".html", ".js", ".css", ".svg"):
                checked += 1
                for line in f.read_text().splitlines():
                    self.assertIsNone(loads.search(line), f"{f.name} loads from elsewhere: {line.strip()[:100]}")
        self.assertGreater(checked, 8)

    def test_keeper_page_tasks(self):
        r = self.http.patch("/admin/zones/sandchat", headers=self.admin, json={"name": "Shell Shack", "open": False})
        self.assertEqual(r.json()["name"], "Shell Shack")
        self.assertFalse(r.json()["open"])
        self.assertEqual(self.http.post("/zones/sandchat/join", headers=self.sandy).status_code, 409)
        r = self.http.patch(f"/admin/participants/{self.sandy_id}", headers=self.admin, json={"game_name": "SandyB"})
        self.assertEqual(r.status_code, 200)
        r = self.http.put(f"/admin/participants/{self.sandy_id}/avatar", headers=self.admin, json={"hair": "teal"})
        self.assertEqual(r.json()["avatar"]["hair"], "teal")
        self.assertEqual(self.http.patch("/admin/settings", headers=self.sandy, json={"beach_name": "X"}).status_code, 403)
        r = self.http.patch("/admin/settings", headers=self.admin, json={"link_base": "http://192.168.1.20:8765/"})
        self.assertEqual(r.json()["link_base"], "http://192.168.1.20:8765")
        self.assertEqual(self.http.patch("/admin/settings", headers=self.admin,
                                         json={"link_base": "javascript:alert(1)"}).status_code, 400)


@unittest.skipUnless(HAVE_FASTAPI, "fastapi/httpx not installed")
class BridgeTests(unittest.TestCase):
    """The bridge, with the world faked and the Beach real (through its HTTP door)."""

    def setUp(self):
        from beach.app import create_app
        self.dir = tempfile.mkdtemp(prefix="beach-bridge-")
        self.clock = FakeClock()
        self.beach = Beach(self.dir, clock=self.clock, rng=random.Random(1))
        self.admin = {"Authorization": f"Bearer {self.beach.ensure_admin()}"}
        self.http = TestClient(create_app(self.beach, upkeep_interval=None))
        self.beach.add_zone("beachblox", "BeachBlox", "game", viewer_url="http://127.0.0.1:8100/")
        self.bridge_token = self.http.post("/admin/zones/beachblox/bridge-token", headers=self.admin).json()["token"]
        coral, _ = self.beach.add_participant("Coral", "person")
        self.beach.add_participant("Sandy", "agent")
        self.beach.update_participant(coral.id, game_name="CoralPlays")
        self.beach.set_avatar(coral.id, {"theme": "sunset", "hair": "teal"})
        self.world_players = []
        self.world_up = True
        self.calls = []
        self.logs = []

    def tearDown(self):
        self.beach.db.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def fake_http(self, method, url, headers, body=None):
        import urllib.error
        self.calls.append((method, url, dict(headers)))
        if url.startswith("http://127.0.0.1:8100"):
            if not self.world_up:
                raise urllib.error.URLError("connection refused")
            assert headers.get("X-Spectator-Token") == "spec-tok"
            return {"players": [{"name": n, "position": [0, 3, 0]} for n in self.world_players]}
        path = url.split("http://127.0.0.1:8765", 1)[1]
        r = self.http.request(method, path, headers=headers, json=body)
        r.raise_for_status()
        return r.json()

    def make(self, world_dir=None):
        from beach.bridge import Bridge
        return Bridge("http://127.0.0.1:8100", "http://127.0.0.1:8765", "beachblox", self.bridge_token,
                      lambda: "spec-tok", world_dir, http=self.fake_http, log=self.logs.append)

    def zone(self):
        return [z for z in self.http.get("/map", headers=self.admin).json()["zones"] if z["id"] == "beachblox"][0]

    def test_reports_who_is_playing(self):
        b = self.make()
        self.world_players = ["CoralPlays", "Sandy", "Visitor9"]
        res = b.step()
        self.assertEqual(res["playing"], 3)
        z = self.zone()
        self.assertEqual(z["here"], 3)
        self.assertEqual(sorted(w["name"] for w in z["who"]), ["Coral", "Sandy", "Visitor9"])
        self.assertEqual(self.beach.arrival_line(None),
                         "The beach is quiet, but you hear sounds of play from BeachBlox.")
        self.world_players = ["Sandy"]
        b.step()
        self.assertEqual([w["name"] for w in self.zone()["who"]], ["Sandy"])

    def test_world_down_reports_nobody(self):
        b = self.make()
        self.world_players = ["Sandy"]
        b.step()
        self.world_up = False
        b.step()
        self.assertEqual(self.zone()["here"], 0)
        self.assertTrue(any("not reachable" in m for m in self.logs))

    def test_reports_expire_if_the_bridge_stops(self):
        b = self.make()
        self.world_players = ["Sandy"]
        b.step()
        self.clock.advance(self.beach.setting("game_report_ttl_s") + 1)
        self.assertEqual(self.zone()["here"], 0)

    def test_writes_tints_for_the_renderer(self):
        world = Path(self.dir) / "world"
        b = self.make(str(world))
        self.world_players = ["CoralPlays", "Visitor9"]
        b.step()
        tints = json.loads((world / "static" / "tints.json").read_text())["players"]
        self.assertEqual(list(tints), ["CoralPlays"])  # guests keep the game's own colours
        self.assertEqual(tints["CoralPlays"]["outfit"], avatar.THEMES["sunset"][0])
        self.assertEqual(tints["CoralPlays"]["hair"], "#008080")

    def test_only_the_zones_bridge_token_reports(self):
        tok = self.http.post("/admin/participants", json={"name": "Pebble", "kind": "agent"},
                             headers=self.admin).json()["token"]
        r = self.http.post("/zones/beachblox/players", headers={"Authorization": f"Bearer {tok}"},
                           json={"players": ["x"]})
        self.assertEqual(r.status_code, 403)

    def test_addresses_must_be_local(self):
        from beach.bridge import require_local, spectator_token_from_log
        self.assertEqual(require_local("http://127.0.0.1:8100/", "w"), "http://127.0.0.1:8100")
        require_local("http://localhost:8765", "b")
        for bad in ("http://192.168.1.5:8100", "http://example.com", "file:///etc/passwd"):
            with self.assertRaises(SystemExit):
                require_local(bad, "w")
        log = Path(self.dir) / "server.log"
        log.write_text("start\nspectator_token=old\nrestart\nspectator_token=abc-123_x\n")
        self.assertEqual(spectator_token_from_log(str(log)), "abc-123_x")


if __name__ == "__main__":
    unittest.main()
