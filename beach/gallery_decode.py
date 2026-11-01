# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""The Art Gallery's image worker: the ONLY code that opens an uploaded picture.

The Beach never imports Pillow. It runs this script in its own short-lived process (python -I), with a time limit,
one at a time, so a hostile file or a decoder bug can at worst crash this worker, never the Beach (Pharos, 10-31).

    python -I gallery_decode.py <upload file> <output path without extension>

It reads only PNG, JPEG and WebP (Pillow is told so: no other format's code ever runs), refuses a picture that is too
big, too thin, animated or truncated, turns a phone photo upright, and saves a fresh file from the pixels alone, so
nothing else in the upload survives: no EXIF (a phone's GPS location), no XMP, no color profile, no comments, nothing
appended. It prints one line of JSON: {"ok": true, "format", "ext", "width", "height"} or {"ok": false, "error"}.
"""

import json
import sys
import warnings

MAX_PIXELS = 40_000_000      # refused before decoding (Pillow alone only raises at twice its own limit)
EDGE = 2048                  # the longest side kept
MAX_ASPECT = 20              # wider or taller than 20:1 is refused (a 2048 downscale would leave a 0-pixel side)
MAGIC = {"PNG": (b"\x89PNG\r\n\x1a\n",), "JPEG": (b"\xff\xd8\xff",), "WEBP": (b"RIFF",)}
EXT = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp"}


def fail(msg: str) -> int:
    print(json.dumps({"ok": False, "error": msg}))
    return 1


def sniff(head: bytes) -> str | None:
    if head.startswith(MAGIC["PNG"][0]):
        return "PNG"
    if head.startswith(MAGIC["JPEG"][0]):
        return "JPEG"
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return "WEBP"
    return None


def main(src: str, dst_base: str) -> int:
    try:
        from PIL import Image, ImageFile, ImageOps
    except ImportError:
        return fail("the gallery needs Pillow on this Beach (requirements-gallery.txt)")
    ImageFile.LOAD_TRUNCATED_IMAGES = False
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    warnings.simplefilter("error", Image.DecompressionBombWarning)   # the 1x-2x band is a refusal too

    with open(src, "rb") as f:
        head = f.read(16)
    kind = sniff(head)
    if kind is None:
        return fail("only PNG, JPEG or WebP pictures can hang here")
    try:
        with Image.open(src, formats=["PNG", "JPEG", "WEBP"]) as im:
            if im.format != kind:
                return fail("the picture isn't what its first bytes say it is")
            w, h = im.size
            if w < 1 or h < 1 or w * h > MAX_PIXELS:
                return fail(f"the picture is too large to open (at most {MAX_PIXELS // 1_000_000} million pixels)")
            if max(w, h) > MAX_ASPECT * min(w, h):
                return fail(f"the picture is too long and thin (at most {MAX_ASPECT}:1)")
            if getattr(im, "n_frames", 1) > 1 or getattr(im, "is_animated", False):
                return fail("moving pictures (animated PNG or WebP) can't hang here, only still ones")
            im = ImageOps.exif_transpose(im)        # upright first: the orientation lives in the EXIF we drop
            alpha = im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info)
            im = im.convert("RGBA" if alpha and kind != "JPEG" else "RGB")
            im.thumbnail((EDGE, EDGE))
            fresh = Image.new(im.mode, im.size)     # the pixels alone, into a brand-new picture
            fresh.paste(im)
            out = f"{dst_base}.{EXT[kind]}"
            if kind == "JPEG":
                fresh.save(out, "JPEG", quality=88, optimize=True)
            elif kind == "PNG":
                fresh.save(out, "PNG", optimize=True)
            else:
                fresh.save(out, "WEBP", quality=90, method=4)
            print(json.dumps({"ok": True, "format": kind, "ext": EXT[kind], "width": fresh.width,
                              "height": fresh.height}))
            return 0
    except (Image.DecompressionBombWarning, Image.DecompressionBombError):
        return fail(f"the picture is too large to open (at most {MAX_PIXELS // 1_000_000} million pixels)")
    except Exception as e:   # anything the decoder dislikes: truncated, corrupt, unsupported inside
        return fail(f"the picture couldn't be read ({type(e).__name__})")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(fail("usage: gallery_decode.py <upload> <output path without extension>"))
    sys.exit(main(sys.argv[1], sys.argv[2]))
