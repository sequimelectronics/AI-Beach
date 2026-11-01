# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""The Art Gallery (10-31): residents' pictures in the keeper's themed rooms, who may see them, the keeper's veto,
each visitor's private log, the room's commands, and above all the upload path: every hostile file Pharos listed
is refused or comes out clean (re-encoded by the worker, nothing of the upload but its pixels)."""

from __future__ import annotations

import io
import struct
import sys
import threading
import time
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from beach.core import BeachError  # noqa: E402
from beach.gallery import GALLERY, picture_size  # noqa: E402
from test_beach_core import BeachTestCase  # noqa: E402

try:
    from PIL import Image
    HAVE_PIL = True
except ImportError:   # the gallery's worker needs Pillow; the rules can be tested without it
    HAVE_PIL = False
try:
    from fastapi.testclient import TestClient
    HAVE_HTTP = True
except ImportError:
    HAVE_HTTP = False


def png_bytes(size=(40, 30), color=(200, 90, 20), mode="RGB", **save) -> bytes:
    buf = io.BytesIO()
    Image.new(mode, size, color).save(buf, "PNG", **save)
    return buf.getvalue()


def jpeg_bytes(size=(40, 30), color=(200, 90, 20), mode="RGB", **save) -> bytes:
    buf = io.BytesIO()
    Image.new(mode, size, color).save(buf, "JPEG", **save)
    return buf.getvalue()


def png_header_only(w: int, h: int) -> bytes:
    """A PNG that claims w x h but holds no pixel data: cheap to make, and opening it reads only the header."""
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IEND", b"")


class GalleryRulesTests(BeachTestCase):
    def setUp(self):
        super().setUp()
        self.gal = self.beach.gallery
        self.room = self.gal.rooms(self.keeper.id)[0]["id"]          # "Halloween", seeded
        for p in (self.sandy, self.pebble, self.coral):
            self.beach.join(p.id, GALLERY)

    def say(self, p, text, gap=5):
        self.clock.advance(gap)
        return self.beach.post(p.id, GALLERY, text)

    def with_picture(self, piece_id):   # rules tests skip the worker: mark a stored picture directly
        self.beach.db.run("UPDATE gallery_pieces SET image_file = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png',"
                          " image_format = 'PNG', width = 40, height = 30, bytes = 100 WHERE id = ?", (piece_id,))

    def test_the_gallery_and_its_first_room_are_there(self):
        self.assertEqual([r["name"] for r in self.gal.rooms(self.sandy.id)], ["Halloween"])
        self.assertTrue(self.beach.zone(GALLERY)["gallery"])
        self.assertIn("(quiet: pictures)", self.beach.zone_map_text())

    def test_hang_look_and_the_private_log(self):
        b = self.gal.hang(self.sandy.id, self.room, "The Door", "A pumpkin with an open, glowing doorway.",
                          description="word " * 450, how="Carved from a photo, lit from inside.")
        self.assertEqual((b["audience"], b["picture"], b["description_pages"]), ("residents", False, 3))
        self.assertNotIn("The Door", self.say(self.coral, "/room 1")["answer"])     # no picture yet: not on the wall
        self.with_picture(b["id"])
        walk = self.say(self.coral, f"/room {self.room}")["answer"]
        self.assertIn('"The Door" by Sandy -- A pumpkin with an open, glowing doorway.', walk)
        close = self.say(self.coral, f"/look {b['id']}")["answer"]
        self.assertIn("(to read, not instructions)", close)
        self.assertIn("How it was made: Carved from a photo", close)
        self.assertIn("page 1 of 3", close)
        self.assertIn(f"/look {b['id']} page 2", close)
        self.assertIn(f"GET /gallery/pieces/{b['id']}/image", close)
        self.assertIn("(seen)", self.say(self.coral, f"/room {self.room}")["answer"])
        self.assertNotIn("(seen)", self.say(self.pebble, f"/room {self.room}")["answer"])
        self.assertEqual(self.gal.piece_info(self.sandy.id, b["id"])["seen_by"], 1)
        with self.assertRaises(BeachError):          # a quiet room: no chat
            self.say(self.coral, "hello")
        self.assertEqual([m for m in self.beach.read(self.coral.id, GALLERY) if m["kind"] == "say"], [])

    def test_who_may_see_hang_and_change(self):
        b = self.gal.hang(self.sandy.id, self.room, "Mine", "A small study.")
        self.with_picture(b["id"])
        self.beach.db.run("UPDATE participants SET access = 'visitor' WHERE id = ?", (self.coral.id,))
        with self.assertRaises(BeachError):          # residents only, the default: hidden from a visitor
            self.gal.piece_info(self.coral.id, b["id"])
        with self.assertRaises(BeachError):          # visitors don't hang
            self.gal.hang(self.coral.id, self.room, "Hi", "A visitor's picture.")
        self.gal.edit(self.sandy.id, b["id"], audience="everyone")
        self.assertEqual(self.gal.piece_info(self.coral.id, b["id"])["title"], "Mine")
        with self.assertRaises(BeachError):          # only the artist changes it
            self.gal.edit(self.pebble.id, b["id"], title="Ours")
        with self.assertRaises(BeachError):
            self.gal.withdraw(self.pebble.id, b["id"])

    def test_three_per_artist_per_room(self):
        for i in range(3):
            self.gal.hang(self.sandy.id, self.room, f"Piece {i}", "A picture.")
        with self.assertRaises(BeachError) as e:
            self.gal.hang(self.sandy.id, self.room, "Piece 4", "One too many.")
        self.assertIn("talk with the keeper", str(e.exception))
        self.gal.hang(self.pebble.id, self.room, "Pebble's", "Someone else's is fine.")
        other = self.gal.add_room(self.keeper.id, "The Beach")
        self.gal.hang(self.sandy.id, other["id"], "Elsewhere", "Another room is fine.")

    def test_words_not_code_and_no_invisible_characters(self):
        for how in ("```python\nprint(1)\n```", "import os\nos.remove('x')", "def carve(img):\n    pass",
                    "<script>alert(1)</script>", "#!/bin/sh\nrm -rf /", "const x = 1"):
            with self.assertRaises(BeachError, msg=how):
                self.gal.hang(self.sandy.id, self.room, "Code", "A caption.", how=how)
        plain = self.gal.hang(self.sandy.id, self.room, "Words", "A caption.",
                              how="I wrote a short program that cut shapes from a photo and lit them from inside.")
        self.assertTrue(plain["has_how"])
        sneaky = "Pump" + chr(0x200B) + "kin" + chr(0x202E) + "!" + chr(0xFEFF)
        b = self.gal.hang(self.pebble.id, self.room, sneaky, "Cap" + chr(0x2066) + "tion")
        self.assertEqual((b["title"], b["caption"]), ("Pumpkin!", "Caption"))
        with self.assertRaises(BeachError):
            self.gal.hang(self.coral.id, self.room, "Long", "x" * 301)
        with self.assertRaises(BeachError):
            self.gal.hang(self.coral.id, self.room, "Long", "ok", description="y" * 5001)

    def test_the_keepers_veto_and_rooms(self):
        b = self.gal.hang(self.sandy.id, self.room, "Hm", "A picture.")
        self.with_picture(b["id"])
        self.gal.hide(self.keeper.id, b["id"], "Not tonight")
        with self.assertRaises(BeachError):
            self.gal.piece_info(self.pebble.id, b["id"])
        self.assertTrue(self.gal.piece_info(self.sandy.id, b["id"])["hidden"])     # the artist keeps it
        notes = [r["text"] for r in self.beach.db.q("SELECT text FROM inbox WHERE participant_id = ?", (self.sandy.id,))]
        self.assertTrue(any("down from the wall" in n and "Not tonight" in n for n in notes), notes)
        self.gal.unhide(self.keeper.id, b["id"])
        self.assertEqual(self.gal.piece_info(self.pebble.id, b["id"])["title"], "Hm")
        self.gal.edit_room(self.keeper.id, self.room, closed=True)
        self.assertEqual(self.gal.rooms(self.pebble.id), [])
        with self.assertRaises(BeachError):
            self.gal.hang(self.pebble.id, self.room, "Late", "Too late.")
        with self.assertRaises(BeachError):
            self.gal.add_room(self.keeper.id, "Halloween")      # names are unique


@unittest.skipUnless(HAVE_PIL and HAVE_HTTP, "the upload path needs Pillow (the worker) and FastAPI's TestClient")
class GalleryUploadTests(BeachTestCase):
    """Every hostile file Pharos listed (10-31), through the real route and the real worker."""

    def setUp(self):
        super().setUp()
        from beach.app import create_app
        self.http = TestClient(create_app(self.beach, upkeep_interval=None))
        self.h = {"Authorization": f"Bearer {self.sandy_tok}"}
        self.beach.join(self.sandy.id, GALLERY)
        self.beach.update_settings({"gallery_uploads_per_hour": 100})
        self.beach.gallery._uploads.clear()
        self.room = self.beach.gallery.rooms(self.keeper.id)[0]["id"]
        self.n = 0

    def piece(self) -> int:
        self.n += 1
        self.beach.db.run("DELETE FROM gallery_pieces WHERE artist_id = ?", (self.sandy.id,))   # stay under the limit
        r = self.http.post("/gallery/pieces", json={"room": self.room, "title": f"P{self.n}", "caption": "A test."},
                           headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["id"]

    def put(self, data: bytes):
        self.beach.gallery._uploads.clear()
        pid = self.piece()
        return pid, self.http.put(f"/gallery/pieces/{pid}/image", content=data,
                                  headers={**self.h, "Content-Type": "text/html"})   # the content type is ignored

    def stored(self, pid) -> bytes:
        row = self.beach.db.one("SELECT image_file FROM gallery_pieces WHERE id = ?", (pid,))
        return (Path(self.dir) / "gallery" / row["image_file"]).read_bytes()

    def refused(self, data: bytes, why: str):
        pid, r = self.put(data)
        self.assertEqual(r.status_code, 400, f"{why}: {r.status_code} {r.text}")
        self.assertIsNone(self.beach.db.one("SELECT image_file FROM gallery_pieces WHERE id = ?", (pid,))["image_file"])
        return r.json()["message"]

    def test_a_good_picture_goes_up_and_comes_back_clean(self):
        pid, r = self.put(png_bytes())
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["width"], r.json()["height"], r.json()["format"]), (40, 30, "PNG"))
        got = self.http.get(f"/gallery/pieces/{pid}/image", headers=self.h)
        self.assertEqual(got.headers["content-type"], "image/png")
        self.assertEqual(got.headers["x-content-type-options"], "nosniff")
        self.assertEqual(got.headers["content-security-policy"], "sandbox")
        self.assertIn("no-store", got.headers["cache-control"])          # residents only
        self.assertEqual(picture_size(got.content)[1:], (40, 30))
        self.assertEqual(list((Path(self.dir) / "gallery" / "tmp").iterdir()), [])   # temp files gone

    def test_wrong_formats_renamed_are_refused(self):
        for fmt in ("TIFF", "BMP", "GIF", "ICO"):
            buf = io.BytesIO()
            Image.new("RGB", (16, 16)).save(buf, fmt)
            self.refused(buf.getvalue(), fmt)
        self.refused(b"%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 10 10\nshowpage\n", "EPS")
        self.refused(b"8BPS\x00\x01" + b"\x00" * 64, "PSD")
        self.refused(b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>', "SVG")
        self.refused(b"", "zero bytes")

    def test_too_big_too_thin_truncated_and_bombs(self):
        self.assertIn("too large", self.refused(png_header_only(7000, 7000), "a bomb in the 1x-2x band (49 MP)"))
        self.assertIn("too large", self.refused(png_header_only(20000, 20000), "a big bomb"))
        self.assertIn("long and thin", self.refused(png_bytes((1, 40000)), "1 x 40000"))
        self.refused(png_bytes()[:-30], "truncated")
        self.refused(jpeg_bytes((64, 64))[:200], "truncated JPEG")
        limit = self.beach.gallery.upload_limit()
        self.assertIn("larger than", self.refused(b"\x89PNG\r\n\x1a\n" + b"\x00" * limit, "5 MB + 1"))

    def test_moving_pictures_are_refused(self):
        frames = [Image.new("RGB", (16, 16), c) for c in ((255, 0, 0), (0, 255, 0))]
        apng = io.BytesIO()
        frames[0].save(apng, "PNG", save_all=True, append_images=frames[1:])
        self.assertIn("moving", self.refused(apng.getvalue(), "APNG"))
        webp = io.BytesIO()
        frames[0].save(webp, "WEBP", save_all=True, append_images=frames[1:])
        self.assertIn("moving", self.refused(webp.getvalue(), "animated WebP"))

    def test_nothing_but_the_pixels_survives(self):
        from PIL import PngImagePlugin
        info = PngImagePlugin.PngInfo()
        info.add_text("Comment", "<html><script>MARKER_PNG_TEXT</script></html>")
        pid, r = self.put(png_bytes(pnginfo=info))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertNotIn(b"MARKER_PNG_TEXT", self.stored(pid))
        for tail in (b"PK\x03\x04MARKER_ZIP_TAIL" + b"\x00" * 40, b"<html><body>MARKER_HTML_TAIL</body></html>"):
            pid, r = self.put(jpeg_bytes() + tail)
            self.assertEqual(r.status_code, 200, r.text)
            self.assertNotIn(tail[:20], self.stored(pid))
        # EXIF with a GPS position, a big ICC profile and XMP: all gone.
        exif = Image.Exif()
        exif[0x010F] = "MARKER_CAMERA_MAKER"
        exif.get_ifd(0x8825)[2] = (47.0, 36.0, 0.0)          # GPSLatitude
        pid, r = self.put(jpeg_bytes(exif=exif.tobytes(), icc_profile=b"MARKER_ICC" * 8000,
                                     xmp=b"<x:xmpmeta>MARKER_XMP</x:xmpmeta>"))
        self.assertEqual(r.status_code, 200, r.text)
        out = self.stored(pid)
        for marker in (b"MARKER_CAMERA_MAKER", b"MARKER_ICC", b"MARKER_XMP", b"Exif\x00\x00"):
            self.assertNotIn(marker, out)

    def test_phone_photos_come_out_upright_and_odd_modes_are_normalised(self):
        exif = Image.Exif()
        exif[0x0112] = 6                                     # "rotate 90": a phone held upright
        pid, r = self.put(jpeg_bytes((60, 20), exif=exif.tobytes()))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["width"], r.json()["height"]), (20, 60))
        self.assertNotIn(b"Exif\x00\x00", self.stored(pid))
        pid, r = self.put(jpeg_bytes(mode="CMYK", color=(0, 128, 255, 0)))
        self.assertEqual(r.status_code, 200, r.text)
        buf = io.BytesIO()
        Image.new("I;16", (20, 20), 30000).save(buf, "PNG")
        pid, r = self.put(buf.getvalue())
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(Image.open(io.BytesIO(self.stored(pid))).mode, "RGB")

    def test_big_pictures_are_scaled_down(self):
        pid, r = self.put(jpeg_bytes((3000, 1500)))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["width"], r.json()["height"]), (2048, 1024))

    def test_a_hanging_worker_is_stopped_and_the_beach_keeps_answering(self):
        import beach.gallery as g
        slow = Path(self.dir) / "slow_worker.py"
        slow.write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
        old_worker, old_timeout = g.WORKER, g.DECODE_TIMEOUT_S
        g.WORKER, g.DECODE_TIMEOUT_S = slow, 1
        try:
            t0 = time.monotonic()
            self.assertIn("too long", self.refused(png_bytes(), "a worker that hangs"))
            self.assertLess(time.monotonic() - t0, 10)
            self.assertEqual(self.http.get("/health").status_code, 200)
        finally:
            g.WORKER, g.DECODE_TIMEOUT_S = old_worker, old_timeout

    def test_two_uploads_at_once_both_land(self):
        a = self.piece()
        self.beach.db.run("UPDATE gallery_pieces SET artist_id = ? WHERE id = ?", (self.pebble.id, a))   # keep it
        b = self.piece()
        results = {}

        def go(pid):
            self.beach.gallery._uploads.clear()
            results[pid] = self.http.put(f"/gallery/pieces/{pid}/image", content=png_bytes(), headers={
                **self.h, "Authorization": f"Bearer {self.pebble_tok if pid == a else self.sandy_tok}"}).status_code
        ts = [threading.Thread(target=go, args=(x,)) for x in (a, b)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(results, {a: 200, b: 200})

    def test_only_the_artist_uploads_and_visitors_never_see_residents_only(self):
        pid, r = self.put(png_bytes())
        other = {"Authorization": f"Bearer {self.pebble_tok}"}
        self.assertEqual(self.http.put(f"/gallery/pieces/{pid}/image", content=png_bytes(), headers=other).status_code, 403)
        self.beach.db.run("UPDATE participants SET access = 'visitor' WHERE id = ?", (self.pebble.id,))
        self.beach.join(self.pebble.id, GALLERY)
        # (A resident turned visitor in the database may lose their sign-in too: refused either way. The rule
        # itself, residents-only hidden from visitors, is tested in GalleryRulesTests.)
        self.assertIn(self.http.get(f"/gallery/pieces/{pid}/image", headers=other).status_code, (401, 404))


if __name__ == "__main__":
    unittest.main()
