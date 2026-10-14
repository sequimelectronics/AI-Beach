"""Colour names and validation for avatars.

Accepts '#rgb', '#rrggbb', CSS colour names ('seagreen', 'sea green'), and a few
beach names ('sunset orange', 'seafoam'). Anything else is refused with a
helpful suggestion: small models invent colour codes, so nothing is guessed.
"""

from __future__ import annotations

import difflib
import re

# The CSS named colours (CSS Color Module Level 4), plus a few beach names.
CSS = {
    "aliceblue": "f0f8ff", "antiquewhite": "faebd7", "aqua": "00ffff", "aquamarine": "7fffd4",
    "azure": "f0ffff", "beige": "f5f5dc", "bisque": "ffe4c4", "black": "000000",
    "blanchedalmond": "ffebcd", "blue": "0000ff", "blueviolet": "8a2be2", "brown": "a52a2a",
    "burlywood": "deb887", "cadetblue": "5f9ea0", "chartreuse": "7fff00", "chocolate": "d2691e",
    "coral": "ff7f50", "cornflowerblue": "6495ed", "cornsilk": "fff8dc", "crimson": "dc143c",
    "cyan": "00ffff", "darkblue": "00008b", "darkcyan": "008b8b", "darkgoldenrod": "b8860b",
    "darkgray": "a9a9a9", "darkgreen": "006400", "darkgrey": "a9a9a9", "darkkhaki": "bdb76b",
    "darkmagenta": "8b008b", "darkolivegreen": "556b2f", "darkorange": "ff8c00", "darkorchid": "9932cc",
    "darkred": "8b0000", "darksalmon": "e9967a", "darkseagreen": "8fbc8f", "darkslateblue": "483d8b",
    "darkslategray": "2f4f4f", "darkslategrey": "2f4f4f", "darkturquoise": "00ced1", "darkviolet": "9400d3",
    "deeppink": "ff1493", "deepskyblue": "00bfff", "dimgray": "696969", "dimgrey": "696969",
    "dodgerblue": "1e90ff", "firebrick": "b22222", "floralwhite": "fffaf0", "forestgreen": "228b22",
    "fuchsia": "ff00ff", "gainsboro": "dcdcdc", "ghostwhite": "f8f8ff", "gold": "ffd700",
    "goldenrod": "daa520", "gray": "808080", "green": "008000", "greenyellow": "adff2f",
    "grey": "808080", "honeydew": "f0fff0", "hotpink": "ff69b4", "indianred": "cd5c5c",
    "indigo": "4b0082", "ivory": "fffff0", "khaki": "f0e68c", "lavender": "e6e6fa",
    "lavenderblush": "fff0f5", "lawngreen": "7cfc00", "lemonchiffon": "fffacd", "lightblue": "add8e6",
    "lightcoral": "f08080", "lightcyan": "e0ffff", "lightgoldenrodyellow": "fafad2", "lightgray": "d3d3d3",
    "lightgreen": "90ee90", "lightgrey": "d3d3d3", "lightpink": "ffb6c1", "lightsalmon": "ffa07a",
    "lightseagreen": "20b2aa", "lightskyblue": "87cefa", "lightslategray": "778899",
    "lightslategrey": "778899", "lightsteelblue": "b0c4de", "lightyellow": "ffffe0", "lime": "00ff00",
    "limegreen": "32cd32", "linen": "faf0e6", "magenta": "ff00ff", "maroon": "800000",
    "mediumaquamarine": "66cdaa", "mediumblue": "0000cd", "mediumorchid": "ba55d3", "mediumpurple": "9370db",
    "mediumseagreen": "3cb371", "mediumslateblue": "7b68ee", "mediumspringgreen": "00fa9a",
    "mediumturquoise": "48d1cc", "mediumvioletred": "c71585", "midnightblue": "191970",
    "mintcream": "f5fffa", "mistyrose": "ffe4e1", "moccasin": "ffe4b5", "navajowhite": "ffdead",
    "navy": "000080", "oldlace": "fdf5e6", "olive": "808000", "olivedrab": "6b8e23",
    "orange": "ffa500", "orangered": "ff4500", "orchid": "da70d6", "palegoldenrod": "eee8aa",
    "palegreen": "98fb98", "paleturquoise": "afeeee", "palevioletred": "db7093", "papayawhip": "ffefd5",
    "peachpuff": "ffdab9", "peru": "cd853f", "pink": "ffc0cb", "plum": "dda0dd",
    "powderblue": "b0e0e6", "purple": "800080", "rebeccapurple": "663399", "red": "ff0000",
    "rosybrown": "bc8f8f", "royalblue": "4169e1", "saddlebrown": "8b4513", "salmon": "fa8072",
    "sandybrown": "f4a460", "seagreen": "2e8b57", "seashell": "fff5ee", "sienna": "a0522d",
    "silver": "c0c0c0", "skyblue": "87ceeb", "slateblue": "6a5acd", "slategray": "708090",
    "slategrey": "708090", "snow": "fffafa", "springgreen": "00ff7f", "steelblue": "4682b4",
    "tan": "d2b48c", "teal": "008080", "thistle": "d8bfd8", "tomato": "ff6347",
    "turquoise": "40e0d0", "violet": "ee82ee", "wheat": "f5deb3", "white": "ffffff",
    "whitesmoke": "f5f5f5", "yellow": "ffff00", "yellowgreen": "9acd32",
}

BEACH = {
    "sunsetorange": "fd5e53", "seafoam": "93e9be", "sand": "e2c48f", "driftwood": "a48466",
    "kelp": "4a6b3a", "lagoon": "1f9e98", "oceanblue": "1f5f9e", "shellpink": "f4c2c2",
    "tidepool": "3f8f8a", "coconut": "965a3e", "mango": "ffb347", "flamingo": "fc8eac",
    "starfish": "f08a4b", "pebblegrey": "9a9a96", "pebblegray": "9a9a96", "sunflower": "ffc512",
    "seaglass": "a7d7c5", "deepsea": "123a5c", "jellyfish": "c8a2e8", "auburn": "a52a2a",
    "copper": "b87333", "platinum": "e5e4e2", "amber": "ffbf00", "mint": "98ff98",
}

NAMED = {**CSS, **BEACH}

# Plain names used to describe a hex colour in words (nearest match).
DESCRIBE = {
    "black": "1b1b1b", "charcoal": "3a3a3a", "grey": "8a8a8a", "silver": "c4c4c4", "white": "f6f6f6",
    "red": "d62828", "crimson": "a4161a", "coral": "ff7f50", "salmon": "fa8072", "orange": "f77f00",
    "amber": "ffbf00", "gold": "e0b000", "yellow": "f5e000", "olive": "808000", "lime green": "7ed321",
    "green": "2a9d3a", "forest green": "1f5f2a", "sea green": "2e8b57", "mint": "98e8c1",
    "teal": "008080", "turquoise": "40e0d0", "aqua": "4fd8f0", "sky blue": "87ceeb", "blue": "2563eb",
    "navy": "1b2a6b", "indigo": "4b2a99", "violet": "8a4fd8", "purple": "7a1f8a", "lavender": "c7b6ef",
    "magenta": "d6249f", "pink": "f6a6c1", "rose": "e0607e", "brown": "6f4326", "chestnut": "954535",
    "auburn": "922724", "copper": "b87333", "tan": "d2b48c", "sandy blonde": "e6c78f",
    "platinum blonde": "efe6cf",
}

HEX_RE = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


class ColourError(ValueError):
    pass


def _key(name: str) -> str:
    return re.sub(r"[\s_\-]+", "", name.strip().lower())


def parse(value) -> tuple[str, str]:
    """Return (display, '#rrggbb') for a colour, or raise ColourError with a suggestion.

    Hex needs its '#' only when it could be mistaken for a word; 'abc' is a
    name lookup, '#abc' is hex.
    """
    if not isinstance(value, str) or not value.strip():
        raise ColourError("a colour is a hex code like '#2a9d8f' or a name like 'sea green'")
    raw = value.strip()
    if len(raw) > 40:
        raise ColourError("that colour is too long; use a hex code like '#2a9d8f' or a name like 'sea green'")
    if raw.startswith("#"):
        m = HEX_RE.match(raw)
        if not m:
            raise ColourError(f"'{raw}' isn't a colour code: use # and 3 or 6 hex digits (0-9, a-f), "
                              "like '#2a9d8f', or a name like 'sea green'")
        h = m.group(1).lower()
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return "#" + h, "#" + h
    if re.fullmatch(r"[0-9a-fA-F]{6}", raw) and _key(raw) not in NAMED:
        return "#" + raw.lower(), "#" + raw.lower()
    k = _key(raw)
    if k in NAMED:
        return " ".join(raw.lower().split()), "#" + NAMED[k]
    close = difflib.get_close_matches(k, list(NAMED), n=2, cutoff=0.75)
    hint = f" Did you mean {' or '.join(repr(_spaced(c)) for c in close)}?" if close else ""
    raise ColourError(f"'{raw}' isn't a colour I know.{hint} Use a hex code like '#2a9d8f' "
                      "or a name like 'sea green' or 'sunset orange'")


def _spaced(key: str) -> str:
    for word in ("orange", "blue", "green", "pink", "grey", "gray", "red", "white", "purple", "yellow",
                 "brown", "violet", "turquoise", "salmon", "cyan", "sea", "slate", "pool", "glass"):
        if key.endswith(word) and key != word:
            return key[: -len(word)] + " " + word
    return key


def rgb(hex6: str) -> tuple[int, int, int]:
    h = hex6.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def words(display: str, hex6: str) -> str:
    """A colour in plain words: the name given, or the nearest plain name for a hex code."""
    if not display.startswith("#"):
        return display
    r, g, b = rgb(hex6)

    def dist(h):
        r2, g2, b2 = rgb(h)
        rm = (r + r2) / 2  # "redmean" weighting, close enough to perception for naming
        return (2 + rm / 256) * (r - r2) ** 2 + 4 * (g - g2) ** 2 + (2 + (255 - rm) / 256) * (b - b2) ** 2

    return min(DESCRIBE, key=lambda n: dist(DESCRIBE[n]))


def shade(hex6: str, f: float) -> str:
    """Darken (f < 1) or lighten (f > 1) a colour."""
    r, g, b = rgb(hex6)
    if f <= 1:
        r, g, b = (int(c * f) for c in (r, g, b))
    else:
        t = f - 1
        r, g, b = (int(c + (255 - c) * t) for c in (r, g, b))
    return "#%02x%02x%02x" % (r, g, b)
