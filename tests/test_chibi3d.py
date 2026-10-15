"""Job 09, part B: each participant's chibi in 3D (BeachBlox) and Beach colors on the claw
characters (ClawBlox).

The look travels Beach -> bridge -> the world's static/tints.json -> the renderer. The 3D chibi is
built by worlds/beach/renderer/src/chibi.js; when Node.js is installed, these tests build every
hairstyle and accessory with it (no browser needed) and check the colors, the hairstyles'
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

from beach import avatar, colors  # noqa: E402
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

    def test_game_look_has_style_and_colors(self):
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


class FaceDrawingTests(unittest.TestCase):
    """The 3D face is the 2D face: one drawing (beach/avatar.py face_layers), worn by both."""

    def setUp(self):
        self.rec = avatar.validate({"preset": "bun", "theme": "coral-reef", "hair": "black", "eyes": "sea green",
                                    "skin": "peach", "accessory": "starfish"}, avatar.default_record(1))

    def test_face_svg_is_the_2d_avatars_own_face(self):
        import re
        full, face = avatar.svg(self.rec), avatar.face_svg(self.rec)
        for layer in ("eyes", "cheeks", "mouth", "hair"):
            group = re.search(r'<g class="av-%s".*?</g>' % layer, full).group(0)
            self.assertIn(group, face)                       # the very same shapes, not a copy that could drift
        for layer in ("body", "outfit", "hair-back", "accessory", "shadow"):
            self.assertNotIn(f'class="av-{layer}"', face)
        x, y, w, h = avatar.FACE_BOX
        self.assertIn(f'viewBox="{x} {y} {w} {h}"', face)
        self.assertIn("#2e8b57", face)                         # sea green eyes
        self.assertNotIn("<script", face)

    def test_the_cheerful_touches(self):
        # After Kellan N.'s sketch: one big shine on the same side of both eyes, cheeks lifted into the
        # eyes' lower outer edge, an open smile.
        eyes, cheeks, mouth = (dict(avatar.layers(self.rec))[k] for k in ("eyes", "cheeks", "mouth"))
        shines = [geo for kind, geo, fill, line, a in eyes if kind == "e" and fill == "#ffffff" and geo[2] > 2]
        self.assertEqual(len(shines), 2)
        self.assertEqual({round(cx - center, 1) for (cx, *_), center in zip(shines, (39, 61))}, {-1.6})
        lowest_eye = max(y for kind, geo, fill, *_ in eyes if kind == "p" for _, y in geo)
        self.assertLess(min(cy - ry for kind, (cx, cy, rx, ry), *_ in cheeks), lowest_eye)   # cheeks reach the eyes
        self.assertEqual(len(mouth), 2)                                                     # an open smile, with tongue

    def test_guests_get_a_face_without_a_fringe(self):
        face = avatar.guest_face_svg()
        self.assertIn('class="av-eyes"', face)
        self.assertNotIn('class="av-hair"', face)

    def test_the_look_carries_the_face(self):
        self.assertEqual(avatar.game_look(self.rec)["face"], avatar.face_svg(self.rec))


@unittest.skipUnless(NODE, "Node.js not installed")
class ChibiBuildTests(unittest.TestCase):
    """Build chibis with the real chibi.js under Node (three.js works without a browser for this).
    The face texture comes from a stand-in that records which drawing it was given."""

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
        (cls.tmp / "looks.json").write_text(json.dumps(looks))
        rng = random.Random(4)
        shades = [("#%06x" % rng.randrange(1 << 24), rng.choice([0.6, 0.8, 1.2])) for _ in range(40)]
        (cls.tmp / "shades.json").write_text(json.dumps(shades))
        (cls.tmp / "run.mjs").write_text("""
import * as THREE from './three.mjs'
import { buildChibi, triangles, shade, INK } from './chibi.mjs'
import { readFileSync } from 'fs'
const looks = JSON.parse(readFileSync(new URL('./looks.json', import.meta.url)))
const shades = JSON.parse(readFileSync(new URL('./shades.json', import.meta.url)))
const faceTexture = (svg) => { const t = new THREE.Texture(); t.userData.svg = svg; return t }
const out = looks.map((L) => {
  const g = buildChibi(L, { faceTexture })
  const colors = new Set(), shapes = []
  let face = null, outline = 0, lit = 0, toneMapped = 0, earFront = 0
  g.traverse((m) => {
    if (!m.isMesh) return
    if (!m.material.isMeshBasicMaterial) lit++
    if (m.material.toneMapped) toneMapped++
    if (m.userData.face) {
      const p = m.geometry.attributes.position, uv = m.geometry.attributes.uv
      let center = null, right = null
      for (let i = 0; i < p.count; i++) {
        const x = p.getX(i), y = p.getY(i), z = p.getZ(i)
        if (!center || Math.hypot(x, y) < Math.hypot(center.x, center.y)) center = { x, y, z, u: uv.getX(i), v: uv.getY(i) }
        if (!right || x > right.x) right = { x, u: uv.getX(i) }
      }
      face = { svg: m.material.map.userData.svg, center, right, transparent: m.material.transparent }
      return
    }
    if (m.material.side === THREE.BackSide) { outline++; colors.add('outline:#' + m.material.color.getHexString()); return }
    colors.add('#' + m.material.color.getHexString())
    if ('#' + m.material.color.getHexString() === L.hair.toLowerCase()) {
      // Hair beside the face at ear height, in front of the ear (the ears sit at x = +-1.17, z = 0).
      const p = m.geometry.attributes.position, v = new THREE.Vector3()
      m.updateMatrixWorld(true)
      for (let i = 0; i < p.count; i++) {
        v.fromBufferAttribute(p, i).applyMatrix4(m.matrixWorld)
        if (Math.abs(v.x) > 0.95 && v.y > 1.25 - 0.35 && v.y < 1.25 + 0.1 && v.z < -0.08) earFront++
      }
    }
    m.geometry.computeBoundingBox()
    const bb = m.geometry.boundingBox
    shapes.push(m.material.color.getHexString() + ':' + m.geometry.attributes.position.count + ':' +
                [...bb.min.toArray(), ...bb.max.toArray()].map(v => v.toFixed(2)).join(','))
  })
  let meshes = 0; g.traverse((m) => { if (m.isMesh) meshes++ })
  return { preset: L.preset, accessory: L.accessory, triangles: triangles(g), meshes, colors: [...colors],
           shapes: shapes.sort().join('|'), face, outline, lit, toneMapped, earFront }
})
const guest = buildChibi({ hair: '#336699', outfit: '#3366cc' }, { faceTexture })
let guestFace = 0; guest.traverse((m) => { if (m.isMesh && m.userData.face) guestFace++ })
console.log(JSON.stringify({ out, ink: INK, guestFace, shades: shades.map(([h, f]) => shade(h, f)) }))
""")
        r = subprocess.run([NODE, str(cls.tmp / "run.mjs")], stdin=subprocess.DEVNULL, capture_output=True,
                           text=True, timeout=120)
        if r.returncode:
            raise RuntimeError(r.stderr)
        cls.result = json.loads(r.stdout)
        cls.looks, cls.shades = looks, shades

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_every_look_builds_in_its_colors(self):
        for look, got in zip(self.looks, self.result["out"]):
            for part in ("hair", "skin", "outfit", "trim"):
                self.assertIn(look[part], got["colors"], f"{part} missing for {look['preset']}/{look['accessory']}")
            if look["preset"] in ("short", "bob", "long", "curly"):      # these have the 2D's darker back hair
                self.assertIn(colors.shade(look["hair"], 0.8), got["colors"])

    def test_the_face_is_the_2d_face_painted_on(self):
        for look, got in zip(self.looks, self.result["out"]):
            face = got["face"]
            self.assertIsNotNone(face)
            self.assertEqual(face["svg"], look["face"])              # exactly the 2D drawing
            self.assertTrue(face["transparent"])
            self.assertLess(face["center"]["z"], 0)                   # on the front of the head (-Z)
            self.assertAlmostEqual(face["center"]["u"], 0.5, places=1)  # the face box's middle at the front
            self.assertAlmostEqual(face["center"]["v"], 0.5, places=1)
            self.assertLess(face["right"]["u"], 0.1)                  # mirrored: the head's +x is the drawing's left

    def test_flat_cartoon_shading_with_an_outline(self):
        for got in self.result["out"]:
            self.assertEqual(got["lit"], 0)                 # no lit (glossy) materials
            self.assertEqual(got["toneMapped"], 0)          # colors exactly as in 2D
            self.assertEqual(got["outline"], 1)             # one outline mesh per character
            self.assertIn("outline:" + self.result["ink"], got["colors"])
        self.assertEqual(self.result["ink"], avatar.INK)    # the 2D avatar's ink color

    def test_no_strip_of_hair_in_front_of_an_ear(self):
        # Job 10's spiky hair (and bun) showed a strip of hair color by the ear from a turned angle:
        # the side hair hung down in front of the ear. Now it stops above the ears beside the face.
        # (Bob and long hair have locks in front of the ears on purpose; curly is a cloud all round.)
        for got in self.result["out"]:
            if got["accessory"] == "none" and got["preset"] in ("spiky", "bun", "short"):
                self.assertEqual(got["earFront"], 0, got["preset"])

    def test_guests_without_a_face_drawing_still_build(self):
        self.assertEqual(self.result["guestFace"], 0)

    def test_the_six_hairstyles_are_different_shapes(self):
        plain = {r["preset"]: r["shapes"] for r in self.result["out"] if r["accessory"] == "none"}
        self.assertEqual(len(plain), 6)
        self.assertEqual(len(set(plain.values())), 6)

    def test_accessories_change_the_shape(self):
        shapes = {r["accessory"]: r["shapes"] for r in self.result["out"] if r["preset"] == "short"}
        self.assertEqual(len(set(shapes.values())), len(avatar.ACCESSORIES))

    def test_few_draw_calls(self):
        # Parts merged into one mesh per color, plus the face and one outline: about a dozen.
        self.assertLessEqual(max(r["meshes"] for r in self.result["out"]), 16)

    def test_triangle_budget(self):
        # The claw character is ~35,900 triangles; a chibi, outline and face included, stays far lighter.
        tris = [r["triangles"] for r in self.result["out"]]
        self.assertLess(max(tris), 15000)

    def test_shading_matches_the_2d_avatar(self):
        for (hexcode, f), got in zip(self.shades, self.result["shades"]):
            self.assertEqual(got, colors.shade(hexcode, f))


if __name__ == "__main__":
    unittest.main()
