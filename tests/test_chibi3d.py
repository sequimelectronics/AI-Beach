"""Job 09, part B: each participant's chibi in 3D (BeachBlox) and Beach colours on the claw
characters (ClawBlox).

The look travels Beach -> bridge -> the world's static/tints.json -> the renderer. The 3D chibi is
built by worlds/beach/renderer/src/chibi.js; when Node.js is installed, these tests build every
hairstyle and accessory with it (no browser needed) and check the colours, the hairstyles'
shapes and the triangle budget.
"""

from __future__ import annotations

import json
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from beach import avatar, colours  # noqa: E402
from beach.bridge import Bridge  # noqa: E402
from beach.core import Beach  # noqa: E402

NODE = shutil.which("node")
THREE = ROOT / "worlds" / "beach" / "static" / "vendor" / "three" / "build" / "three.module.min.js"
CHIBI = ROOT / "worlds" / "beach" / "renderer" / "src" / "chibi.js"


class LookRouteTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="chibi-")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_game_look_has_style_and_colours(self):
        rec = avatar.validate({"preset": "bun", "theme": "night-tide", "hair": "sea green", "eyes": "amber",
                               "skin": "umber", "accessory": "flower"}, avatar.default_record(1))
        look = avatar.game_look(rec)
        self.assertEqual(look["preset"], "bun")
        self.assertEqual(look["accessory"], "flower")
        self.assertEqual(look["hair"], "#2e8b57")
        self.assertEqual(look["eyes"], "#ffbf00")
        self.assertEqual(look["skin"], avatar.SKINS["umber"])
        self.assertEqual((look["outfit"], look["trim"]), avatar.THEMES["night-tide"][:2])

    def test_the_beach_hands_it_to_the_bridge_and_the_bridge_to_the_renderer(self):
        b = Beach(self.dir)
        b.ensure_admin()
        p, _ = b.add_participant("Coral", "person")
        b.set_avatar(p.id, {"preset": "curly", "theme": "coral-reef", "hair": "black", "eyes": "teal",
                            "skin": "peach", "accessory": "sunhat"})
        b.add_zone("beachblox", "BeachBlox", "game")
        tok = b.bridge_token("beachblox")
        looks = {"Coral": avatar.game_look(b.avatar_record(p.id))}
        world = Path(self.dir) / "world"
        br = Bridge("http://127.0.0.1:1", "http://127.0.0.1:2", "beachblox", tok, lambda: None, str(world))
        br.write_tints(looks)
        written = json.loads((world / "static" / "tints.json").read_text())["players"]["Coral"]
        self.assertEqual(written["preset"], "curly")
        self.assertEqual(written["accessory"], "sunhat")
        self.assertEqual(written["outfit"], avatar.THEMES["coral-reef"][0])
        b.db.close()


class RendererWiringTests(unittest.TestCase):
    def test_beach_renderer_draws_chibis_not_capsules(self):
        src = (ROOT / "worlds" / "beach" / "renderer" / "src" / "index.js").read_text()
        self.assertIn("import { buildChibi, disposeChibi, guestLook } from './chibi.js'", src)
        self.assertNotIn("CapsuleGeometry(0.9", src)                    # the old capsule body is gone
        self.assertIn("syncPlayer(obj, String(entity.attributes.PlayerName)", src)   # renames and new looks, live

    def test_clawblox_renderer_tints_the_claw_model(self):
        src = (ROOT / "worlds" / "clawblox" / "renderer" / "src" / "index.js").read_text()
        self.assertIn("import { startTints, tintModel } from './beach-tint.js'", src)
        self.assertIn("tintModel(obj, nameByRootPartId.get(entity.id)", src)
        tint = (ROOT / "worlds" / "clawblox" / "renderer" / "src" / "beach-tint.js").read_text()
        self.assertIn("customProgramCacheKey", tint)       # one shader program shared by every player
        self.assertIn("material.clone()", tint)            # each player's own copy of the material
        notice = (ROOT / "worlds" / "clawblox" / "NOTICE.md").read_text()
        self.assertIn("beach-tint.js", notice)
        self.assertIn("MIT", notice)

    def test_no_model_file_and_nothing_from_elsewhere(self):
        for d in ("worlds/beach/renderer/src", "worlds/clawblox/renderer/src"):
            for f in (ROOT / d).iterdir():
                self.assertNotIn(f.suffix, (".glb", ".gltf", ".fbx", ".obj"))
                text = f.read_text()
                self.assertNotIn("http://", text.replace("http://127.0.0.1", ""))
                self.assertNotIn("https://", text)


@unittest.skipUnless(NODE, "Node.js not installed")
class ChibiBuildTests(unittest.TestCase):
    """Build chibis with the real chibi.js under Node (three.js works without a browser for this)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="chibi-node-"))
        shutil.copy(THREE, cls.tmp / "three.mjs")
        src = CHIBI.read_text().replace("'../../static/vendor/three/build/three.module.min.js'", "'./three.mjs'")
        (cls.tmp / "chibi.mjs").write_text(src)
        looks = []
        for preset in avatar.PRESETS:
            for acc in avatar.ACCESSORIES:
                rec = avatar.validate({"preset": preset, "accessory": acc, "theme": "sunset", "hair": "sea green",
                                       "eyes": "amber", "skin": "honey"}, avatar.default_record(0))
                looks.append(avatar.game_look(rec))
        rng = random.Random(4)
        shades = [("#%06x" % rng.randrange(1 << 24), rng.choice([0.6, 0.8, 1.2])) for _ in range(40)]
        (cls.tmp / "run.mjs").write_text("""
import { buildChibi, triangles, shade } from './chibi.mjs'
const looks = %s, shades = %s
const out = looks.map((L) => {
  const g = buildChibi(L)
  const colours = new Set(), shapes = []
  g.traverse((m) => {
    if (!m.isMesh) return
    colours.add('#' + m.material.color.getHexString())
    m.geometry.computeBoundingBox()
    const bb = m.geometry.boundingBox
    shapes.push(m.material.color.getHexString() + ':' + m.geometry.attributes.position.count + ':' +
                [...bb.min.toArray(), ...bb.max.toArray()].map(v => v.toFixed(2)).join(','))
  })
  return { preset: L.preset, accessory: L.accessory, triangles: triangles(g), meshes: shapes.length, colours: [...colours], shapes: shapes.sort().join('|') }
})
console.log(JSON.stringify({ out, shades: shades.map(([h, f]) => shade(h, f)) }))
""" % (json.dumps(looks), json.dumps(shades)))
        r = subprocess.run([NODE, str(cls.tmp / "run.mjs")], capture_output=True, text=True, timeout=120)
        if r.returncode:
            raise RuntimeError(r.stderr)
        cls.result = json.loads(r.stdout)
        cls.looks, cls.shades = looks, shades

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_every_look_builds_in_its_colours(self):
        for look, got in zip(self.looks, self.result["out"]):
            for part in ("hair", "eyes", "skin", "outfit", "trim"):
                self.assertIn(look[part], got["colours"], f"{part} missing for {look['preset']}/{look['accessory']}")
            if look["preset"] in ("short", "bob", "long", "curly"):      # these have the 2D's darker back hair
                self.assertIn(colours.shade(look["hair"], 0.8), got["colours"])

    def test_the_six_hairstyles_are_different_shapes(self):
        plain = {r["preset"]: r["shapes"] for r in self.result["out"] if r["accessory"] == "none"}
        self.assertEqual(len(plain), 6)
        self.assertEqual(len(set(plain.values())), 6)

    def test_accessories_change_the_shape(self):
        shapes = {r["accessory"]: r["shapes"] for r in self.result["out"] if r["preset"] == "short"}
        self.assertEqual(len(set(shapes.values())), len(avatar.ACCESSORIES))

    def test_few_draw_calls(self):
        # Parts are merged into one mesh per colour: about a dozen draw calls per character.
        self.assertLessEqual(max(r["meshes"] for r in self.result["out"]), 16)

    def test_triangle_budget(self):
        # The claw character is ~35,900 triangles; a chibi should be far lighter.
        tris = [r["triangles"] for r in self.result["out"]]
        self.assertLess(max(tris), 9000)

    def test_shading_matches_the_2d_avatar(self):
        for (hexcode, f), got in zip(self.shades, self.result["shades"]):
            self.assertEqual(got, colours.shade(hexcode, f))


if __name__ == "__main__":
    unittest.main()
