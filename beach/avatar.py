"""Chibi avatars: a small record each participant owns, drawn from layered parts.

The record is six choices: preset (the hairstyle and silhouette), theme (the
outfit's colors), hair and eye colors (hex or a name), skin tone, accessory.
Every part is a list of simple shapes (ellipses and polygons) in one 100x120
box, so a color change is only a recolor of a layer. The same shapes are
written out as SVG (for browsers) or rasterised to PNG (for agents that look
at images); no image libraries are needed.
"""

from __future__ import annotations

import math
import struct
import zlib
from functools import lru_cache

from . import colors

PRESETS = {  # id -> how the hair is described
    "short": "short {c} hair",
    "bob": "{c} hair in a bob",
    "long": "long {c} hair",
    "bun": "{c} hair in a bun",
    "spiky": "spiky {c} hair",
    "curly": "curly {c} hair",
}

THEMES = {  # id -> (outfit color, trim color, words)
    "lagoon": ("#2a9d8f", "#e9f5f2", "teal-and-white"),
    "sunset": ("#f4845f", "#ffd166", "orange-and-gold"),
    "driftwood": ("#a47551", "#f1e3c8", "brown-and-cream"),
    "seafoam": ("#5fbf9a", "#ffffff", "mint-and-white"),
    "night-tide": ("#2b3a67", "#e9c46a", "navy-and-gold"),
    "coral-reef": ("#ef476f", "#ffd6a5", "pink-and-peach"),
    "sailor": ("#1d4e89", "#f1faee", "blue-and-white"),
}

SKINS = {
    "porcelain": "#fbe0cf", "peach": "#f2c6a0", "sand": "#e0ac7e",
    "honey": "#c68b59", "bronze": "#9b6a43", "umber": "#6b4429",
}

ACCESSORIES = {
    "none": "",
    "sunhat": "a floppy sun hat",
    "flower": "a flower in their hair",
    "headphones": "headphones",
    "bow": "a bow",
    "sunglasses": "sunglasses pushed up on their head",
    "starfish": "a starfish hair clip",
    "bandana": "a bandana",
}

FIELDS = ("preset", "theme", "hair", "eyes", "skin", "accessory")
_DEFAULT_HAIR = ("saddle brown", "black", "goldenrod", "sienna", "dark slate gray", "chocolate", "coral")
_DEFAULT_EYES = ("saddle brown", "teal", "royal blue", "sea green", "amber", "dim gray")

# The builder's one-tap colors (any name or hex works too).
QUICK = {
    "hair": ["black", "saddle brown", "chocolate", "goldenrod", "sand", "sunset orange", "coral", "sea green",
             "teal", "midnight blue", "orchid", "silver"],
    "eyes": ["saddle brown", "amber", "sea green", "teal", "royal blue", "slate gray", "olive", "violet"],
}

INK = "#3d2b2b"
STROKE = 1.8


class AvatarError(ValueError):
    pass


# ---------------------------------------------------------------- the record

def default_record(seed: int) -> dict:
    """Everyone has a look from the start, picked from their id; changing it is optional."""
    keys = list(PRESETS), list(THEMES), list(SKINS)
    return {"preset": keys[0][seed % len(keys[0])],
            "theme": keys[1][(seed * 3) % len(keys[1])],
            "hair": _DEFAULT_HAIR[(seed * 5) % len(_DEFAULT_HAIR)],
            "eyes": _DEFAULT_EYES[(seed * 7) % len(_DEFAULT_EYES)],
            "skin": keys[2][(seed * 11) % len(keys[2])],
            "accessory": "none"}


def _choice(field: str, value, options) -> str:
    v = str(value).strip().lower().replace(" ", "-").replace("_", "-") if isinstance(value, str) else None
    if field == "accessory" and v in ("sun-hat",):
        v = "sunhat"
    if v not in options:
        raise AvatarError(f"{field} must be one of: {', '.join(options)}")
    return v


def validate(changes: dict, current: dict) -> dict:
    """Merge a partial change into the current record, validating every field."""
    if not isinstance(changes, dict):
        raise AvatarError("send an object like {\"hair\": \"sea green\"}")
    unknown = [k for k in changes if k not in FIELDS]
    if unknown:
        raise AvatarError(f"unknown field {unknown[0]!r}; the fields are {', '.join(FIELDS)}")
    rec = dict(current)
    for k, v in changes.items():
        if k == "preset":
            rec[k] = _choice(k, v, PRESETS)
        elif k == "theme":
            rec[k] = _choice(k, v, THEMES)
        elif k == "skin":
            rec[k] = _choice(k, v, SKINS)
        elif k == "accessory":
            rec[k] = _choice(k, v, ACCESSORIES)
        else:
            try:
                rec[k] = colors.parse(v)[0]
            except colors.ColorError as e:
                raise AvatarError(f"{k}: {e}") from None
    return rec


def hexes(rec: dict) -> dict:
    """The record's colors as '#rrggbb' (what a game uses to tint a character)."""
    outfit, trim, _ = THEMES[rec["theme"]]
    return {"hair": colors.parse(rec["hair"])[1], "eyes": colors.parse(rec["eyes"])[1],
            "skin": SKINS[rec["skin"]], "outfit": outfit, "trim": trim}


def guest_face_svg() -> str:
    """The face for a game-world player who isn't a Beach participant: the same face, plain brown
    eyes, no fringe (their hair color is picked by the world from their name)."""
    return face_svg({**default_record(0), "eyes": "#5c4a42"}, hair=False)


def game_look(rec: dict) -> dict:
    """What a game world needs to draw the chibi in 3D: the colors, the hairstyle, the accessory,
    and the face itself, as the 2D avatar draws it (an SVG the renderer paints onto the head)."""
    return {**hexes(rec), "preset": rec["preset"], "accessory": rec["accessory"], "face": face_svg(rec)}


def _a(phrase: str) -> str:
    return ("an " if phrase[0] in "aeiou" else "a ") + phrase


def describe(rec: dict) -> str:
    """The record as one short plain-language sentence."""
    h = colors.parse(rec["hair"])
    e = colors.parse(rec["eyes"])
    parts = [PRESETS[rec["preset"]].format(c=colors.words(*h)),
             f"{colors.words(*e)} eyes",
             _a(f"{THEMES[rec['theme']][2]} outfit")]
    acc = ACCESSORIES[rec["accessory"]]
    if acc:
        parts.append(acc)
    return "A chibi with " + ", ".join(parts[:-1]) + " and " + parts[-1] + "."


def card(cooldown_s: int) -> str:
    mins = max(1, int(cooldown_s // 60)) if cooldown_s else 0
    pace = f"once per {mins} min" if mins else "any time"
    return "\n".join([
        "AVATAR CARD",
        "Your look here: a chibi shown beside your name.",
        "set: PUT /me/avatar {preset, theme, hair, eyes, skin, accessory} (any; one word from each list)",
        "see: GET /me/avatar (with a sentence) or /me/avatar.png",
        f"preset (hair style): {' '.join(PRESETS)}",
        f"theme (clothing): {' '.join(THEMES)}",
        f"skin: {' '.join(SKINS)}",
        f"accessory: {' '.join(ACCESSORIES)}",
        "hair, eyes: #rrggbb or a color name (sea green)",
        f"changes: {pace}; the first is free",
    ])


# ---------------------------------------------------------------- the parts

def _E(cx, cy, rx, ry, fill, line=True, alpha=1.0):
    return ("e", (cx, cy, rx, ry), fill, line, alpha)


def _P(points, fill, line=True, alpha=1.0):
    return ("p", tuple(points), fill, line, alpha)


def _arc(cx, cy, rx, ry, a0, a1, n=16, wobble=None):
    pts = []
    for i in range(n + 1):
        a = math.radians(a0 + (a1 - a0) * i / n)
        r = 1.0 if wobble is None else wobble(i)
        pts.append((cx + rx * r * math.cos(a), cy + ry * r * math.sin(a)))
    return pts


def _quad(p0, p1, p2, n=6):
    return [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
             (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1])
            for t in (i / n for i in range(n + 1))]


def _star(cx, cy, r1, r2, n=5):
    pts = []
    for i in range(n * 2):
        a = math.radians(-90 + i * 180 / n)
        r = r1 if i % 2 == 0 else r2
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def _happy_eye(cx, cy, rx, ry, fill, line=True, flat=0.62):
    """An eye whose lower edge is pushed up and flattened a little, as if by a smiling cheek."""
    pts = _arc(cx, cy, rx, ry, 0, 360, 28)
    return _P([(x, min(y, cy + ry * flat)) for x, y in pts], fill, line)


def _fringe(preset: str, zig: list) -> list:
    """The lower edge of the front hair, right to left. Not everyone's bangs are spiky (a note from
    Kellan N.): short hair keeps the zigzag, a bob has a straight blunt fringe, long hair a curved
    fringe swept to one side, and a bun soft rounded scallops."""
    if preset == "bob":
        return [(79.5, 46), (77.5, 40.5), (72, 39), (28, 39), (22.5, 40.5), (20.5, 46)]
    if preset == "long":
        return ([(79.5, 46)] + _quad((77, 36), (66, 30.5), (55, 35.5), 6)
                + _quad((55, 35.5), (40, 42.5), (20.5, 46), 8)[1:])
    if preset == "bun":
        pts = [(79.5, 46)]
        for x0, x1 in ((79.5, 64.5), (64.5, 50), (50, 35.5), (35.5, 20.5)):
            pts += _quad((x0, 43 if x0 in (79.5, 20.5) else 40), ((x0 + x1) / 2, 32.5),
                         (x1, 43 if x1 in (79.5, 20.5) else 40), 5)[1:]
        return pts + [(20.5, 46)]
    return zig


def face_layers(c: dict) -> list[tuple[str, list]]:
    """The face: eyes, cheeks and mouth. The 2D avatar draws these, and the 3D chibi in BeachBlox
    wears the very same drawing (face_svg), so the two faces can't drift apart.

    The cheerful touches follow Kellan N.'s reference sketch (docs/art/cheerful-face-sketch.png):
    one big round shine on the same side of both eyes, the lower edge of each eye lifted by its
    cheek, blush that overlaps the eye's lower outer edge, and an open smile. Toned down from the
    sketch, which is deliberately extra cheerful."""
    eyes = []
    for x in (39, 61):
        eyes += [_happy_eye(x, 52.4, 5.4, 7.3, "#2b2233", False, 0.74),
                 _happy_eye(x, 53.4, 4.2, 5.9, c["eyes"], False, 0.66),
                 _happy_eye(x, 54.6, 2.3, 3.2, "#1a1420", False, 0.6),
                 _E(x - 1.6, 50.2, 2.3, 2.4, "#ffffff", False), _E(x + 1.8, 55.0, 0.75, 0.75, "#ffffff", False)]
    cheeks = [_E(31.5, 59.6, 5.2, 2.9, "#ff6f7f", False, 0.42), _E(68.5, 59.6, 5.2, 2.9, "#ff6f7f", False, 0.42)]
    # An open smile: nearly flat on top with the corners curling up, rounded underneath.
    top = _quad((45, 61.8), (50, 63.1), (55, 61.8), 8)
    bottom = _quad((55, 61.8), (54.2, 67.6), (50, 67.4), 6)[1:] + _quad((50, 67.4), (45.8, 67.6), (45, 61.8), 6)[1:-1]
    mouth = [_P(top + bottom, "#7a3333"), _E(50, 65.9, 2.4, 1.2, "#ff8a8a", False)]
    return [("eyes", eyes), ("cheeks", cheeks), ("mouth", mouth)]


FACE_BOX = (21, 21, 58, 54)   # the head's front in the 100 x 120 drawing: x, y, width, height


def face_svg(rec: dict, hair: bool = True) -> str:
    """The front of the head as drawn in 2D (front hair, eyes, cheeks, mouth) on a transparent
    background, cropped to FACE_BOX: what the 3D chibi's head wears, so its face is the 2D face.
    `hair=False` leaves out the fringe (the plain face guests wear)."""
    keep = {"hair", "eyes", "cheeks", "mouth"} if hair else {"eyes", "cheeks", "mouth"}
    x, y, w, h = FACE_BOX
    full = svg(rec, only=keep)
    return full.replace('viewBox="0 0 100 120"', f'viewBox="{x} {y} {w} {h}" width="512" height="{round(512 * h / w)}"', 1)


def layers(rec: dict) -> list[tuple[str, list]]:
    """The avatar as named layers of shapes, back to front."""
    c = hexes(rec)
    hair, skin, outfit, trim = c["hair"], c["skin"], c["outfit"], c["trim"]
    hair_dark = colors.shade(hair, 0.8)
    preset = rec["preset"]
    out = []

    out.append(("shadow", [_E(50, 113.5, 22, 3.5, "#000000", False, 0.15)]))

    back = []
    if preset == "long":
        back += [_E(50, 44, 33, 31, hair_dark),
                 _P([(18, 44), (17, 72), (22, 94), (36, 89), (50, 93), (64, 89), (78, 94), (83, 72), (82, 44)],
                    hair_dark)]
    elif preset == "bob":
        back += [_E(50, 46, 34, 30, hair_dark),
                 _P([(16.5, 46), (17.5, 68), (31, 71), (69, 71), (82.5, 68), (83.5, 46)], hair_dark)]
    elif preset == "bun":
        back += [_E(50, 13, 11, 10, hair), _E(50, 45, 32, 30, hair_dark)]
    elif preset == "curly":
        for a in range(0, 360, 30):
            r = math.radians(a)
            back.append(_E(50 + 30 * math.cos(r), 46 + 28 * math.sin(r), 9, 9, hair_dark))
    else:  # short, spiky
        back.append(_E(50, 44, 32, 29, hair_dark))
    out.append(("hair-back", back))

    out.append(("body", [
        _E(43, 107, 4.5, 6.5, skin), _E(57, 107, 4.5, 6.5, skin),
        _E(42, 113, 6, 3, colors.shade(outfit, 0.6)), _E(58, 113, 6, 3, colors.shade(outfit, 0.6)),
        _E(30.5, 89, 5, 10, skin), _E(69.5, 89, 5, 10, skin),
    ]))
    out.append(("outfit", [
        _E(33, 80, 6.5, 6.5, outfit), _E(67, 80, 6.5, 6.5, outfit),
        _P([(38, 73), (62, 73), (68.5, 104)] + _quad((68.5, 104), (50, 108), (31.5, 104))[1:], outfit),
        _P([(35.2, 93), (64.8, 93), (66.5, 99), (33.5, 99)], trim),
        _P([(43, 73), (57, 73), (50, 81)], trim),
    ]))
    out.append(("head", [
        _E(21, 53, 4, 5.5, skin), _E(79, 53, 4, 5.5, skin),
        _E(50, 48, 29, 27, skin),
    ]))
    out += face_layers(c)

    front = []
    zig = [(79.5, 46), (73, 35), (67, 42), (59, 32), (50, 40), (41, 32), (33, 42), (27, 35), (20.5, 46)]
    if preset == "spiky":
        top = _arc(50, 47, 30, 31, 180, 360, 12, wobble=lambda i: 1.22 if i % 2 else 1.0)
        front.append(_P(top + zig, hair))
    elif preset == "curly":
        for a in range(195, 350, 22):
            r = math.radians(a)
            front.append(_E(50 + 25 * math.cos(r), 40 + 20 * math.sin(r), 8.5, 8, hair))
    else:
        front.append(_P(_arc(50, 47, 30, 30, 180, 360, 16) + _fringe(preset, zig), hair))
        if preset == "long":
            front += [_P([(21, 44), (18, 72), (24, 76), (28, 50)], hair),
                      _P([(79, 44), (82, 72), (76, 76), (72, 50)], hair)]
        if preset == "bob":
            front += [_P([(21, 44), (19, 66), (27, 66), (27, 48)], hair),
                      _P([(79, 44), (81, 66), (73, 66), (73, 48)], hair)]
    out.append(("hair", front))

    acc = rec["accessory"]
    a = []
    if acc == "sunhat":
        a = [_E(50, 23, 41, 8.5, trim),
             _P(_arc(50, 23, 17, 16, 180, 360, 10), trim),
             _P([(33.4, 18), (66.6, 18), (67, 22.5), (33, 22.5)], outfit)]
    elif acc == "flower":
        for k in range(5):
            r = math.radians(k * 72 - 90)
            a.append(_E(73 + 5 * math.cos(r), 28 + 5 * math.sin(r), 3.8, 3.8, "#ff6f91"))
        a.append(_E(73, 28, 2.8, 2.8, "#ffd166"))
    elif acc == "headphones":
        outer = _arc(50, 48, 33, 34, 185, 355, 14)
        inner = _arc(50, 48, 29, 30, 355, 185, 14)
        a = [_P(outer + inner, "#3a4256"), _E(19.5, 52, 5, 8, outfit), _E(80.5, 52, 5, 8, outfit)]
    elif acc == "bow":
        a = [_P([(70, 26), (60, 19), (60, 33)], outfit), _P([(70, 26), (80, 19), (80, 33)], outfit),
             _E(70, 26, 2.8, 2.8, trim)]
    elif acc == "sunglasses":
        a = [_P([(44, 27), (56, 27), (56, 29.5), (44, 29.5)], "#222222"),
             _E(38, 28, 7, 5, "#222222"), _E(62, 28, 7, 5, "#222222"),
             _E(36, 26.6, 2, 1.2, "#ffffff", False, 0.6), _E(60, 26.6, 2, 1.2, "#ffffff", False, 0.6)]
    elif acc == "starfish":
        a = [_P(_star(72, 29, 7.5, 3.2), "#f08a4b")]
    elif acc == "bandana":
        band = _arc(50, 47, 30.5, 30, 190, 350, 12) + _arc(50, 47, 27, 23, 350, 190, 12)
        a = [_P(band, outfit), _P([(77, 38), (86, 34), (85, 43)], outfit)]
    if a:
        out.append(("accessory", a))
    return out


# ---------------------------------------------------------------- output: SVG

def _n(v: float) -> str:
    s = f"{v:.1f}"
    return s[:-2] if s.endswith(".0") else s


def svg(rec: dict, size: int | None = None, title: str | None = None, only: set | None = None) -> str:
    """Layered SVG. Each layer is a <g> so a recolor touches one group. `only`: just those layers."""
    dims = f' width="{size}" height="{int(size * 1.2)}"' if size else ""
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 120"{dims} role="img">']
    if title:
        esc = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        parts.append(f"<title>{esc}</title>")
    for name, shapes in layers(rec):
        if only is not None and name not in only:
            continue
        parts.append(f'<g class="av-{name}" stroke="{INK}" stroke-width="{STROKE}" stroke-linejoin="round">')
        for kind, geo, fill, line, alpha in shapes:
            extra = "" if line else ' stroke="none"'
            if alpha < 1:
                extra += f' fill-opacity="{alpha}"'
            if kind == "e":
                cx, cy, rx, ry = geo
                parts.append(f'<ellipse cx="{_n(cx)}" cy="{_n(cy)}" rx="{_n(rx)}" ry="{_n(ry)}" fill="{fill}"{extra}/>')
            else:
                d = "M" + " L".join(f"{_n(x)} {_n(y)}" for x, y in geo) + "Z"
                parts.append(f'<path d="{d}" fill="{fill}"{extra}/>')
        parts.append("</g>")
    parts.append("</svg>")
    return "".join(parts)


# ---------------------------------------------------------------- output: PNG

def _spans_ellipse(geo, y):
    cx, cy, rx, ry = geo
    t = (y - cy) / ry
    if abs(t) >= 1:
        return []
    dx = rx * math.sqrt(1 - t * t)
    return [(cx - dx, cx + dx)]


def _spans_poly(pts, y):
    xs = []
    n = len(pts)
    for i in range(n):
        (x0, y0), (x1, y1) = pts[i], pts[(i + 1) % n]
        if (y0 <= y < y1) or (y1 <= y < y0):
            xs.append(x0 + (y - y0) * (x1 - x0) / (y1 - y0))
    xs.sort()
    return [(xs[i], xs[i + 1]) for i in range(0, len(xs) - 1, 2)]


def _fill(buf, W, H, k, kind, geo, rgba, alpha):
    if kind == "e":
        cx, cy, rx, ry = geo
        y0, y1 = cy - ry, cy + ry
        spans = _spans_ellipse
    else:
        ys = [p[1] for p in geo]
        y0, y1 = min(ys), max(ys)
        spans = _spans_poly
    r, g, b = rgba
    px = bytes((r, g, b, 255))
    for row in range(max(0, int(y0 * k)), min(H, int(y1 * k) + 1)):
        y = (row + 0.5) / k
        for xa, xb in spans(geo, y):
            a0 = max(0, int(xa * k + 0.5))
            a1 = min(W, int(xb * k + 0.5))
            if a1 <= a0:
                continue
            off = (row * W + a0) * 4
            if alpha >= 1:
                buf[off:off + (a1 - a0) * 4] = px * (a1 - a0)
            else:
                for o in range(off, off + (a1 - a0) * 4, 4):
                    da = buf[o + 3] / 255
                    oa = alpha + da * (1 - alpha)
                    for j, cval in enumerate((r, g, b)):
                        buf[o + j] = int((cval * alpha + buf[o + j] * da * (1 - alpha)) / oa) if oa else 0
                    buf[o + 3] = int(oa * 255)


def _dilate(kind, geo, w):
    if kind == "e":
        cx, cy, rx, ry = geo
        return [("e", (cx, cy, rx + w, ry + w))]
    out = [("p", geo)]
    for a in range(0, 360, 45):
        dx, dy = w * math.cos(math.radians(a)), w * math.sin(math.radians(a))
        out.append(("p", tuple((x + dx, y + dy) for x, y in geo)))
    return out


@lru_cache(maxsize=256)
def _png_cached(key: tuple, size: int) -> bytes:
    rec = dict(key)
    S = 3
    W, H = size * S, int(size * 1.2) * S
    k = W / 100
    buf = bytearray(W * H * 4)
    ink = colors.rgb(INK)
    for _, shapes in layers(rec):
        for kind, geo, fill, line, alpha in shapes:
            if line:
                for dk, dg in _dilate(kind, geo, STROKE / 2):
                    _fill(buf, W, H, k, dk, dg, ink, alpha)
            _fill(buf, W, H, k, kind, geo, colors.rgb(fill), alpha)
    # Downsample SxS (premultiplied) for smooth edges.
    w, h = W // S, H // S
    raw = bytearray()
    n = S * S
    for y in range(h):
        raw.append(0)
        for x in range(w):
            tr = tg = tb = ta = 0
            for sy in range(S):
                o = ((y * S + sy) * W + x * S) * 4
                for sx in range(S):
                    a = buf[o + 3]
                    tr += buf[o] * a
                    tg += buf[o + 1] * a
                    tb += buf[o + 2] * a
                    ta += a
                    o += 4
            if ta:
                raw += bytes((tr // ta, tg // ta, tb // ta, ta // n))
            else:
                raw += b"\0\0\0\0"

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))


def png(rec: dict, size: int = 96) -> bytes:
    size = max(32, min(int(size), 256))
    return _png_cached(tuple(sorted(rec.items())), size)


def options() -> dict:
    """What the builder offers."""
    return {"presets": list(PRESETS), "themes": {k: {"outfit": v[0], "trim": v[1], "words": v[2]}
                                                 for k, v in THEMES.items()},
            "skins": SKINS, "accessories": list(ACCESSORIES),
            "quick": {f: [[n, colors.parse(n)[1]] for n in names] for f, names in QUICK.items()}}
