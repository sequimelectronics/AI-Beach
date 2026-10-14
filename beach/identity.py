"""One name, everywhere: the rules for participant names.

A participant's Beach name is their name in every zone, at every table and in every game
world. Names are checked so that no two participants can be confused:

- the shape: 1-24 characters, letters, digits, spaces, '.', '_' or '-', starting with a letter
  (ASCII only, which already rules out look-alike letters from other alphabets);
- the "skeleton": a name is refused when, ignoring case, spaces and punctuation, and reading
  look-alike characters as the same (0/o, 1/l/i, 5/s, rn/m, vv/w ...), it matches another
  participant's name, or a name someone gave up recently (still shown as "(was ...)").
"""

from __future__ import annotations

import re
import unicodedata

NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 _.-]{0,23}$")
NAME_RULE = "names are 1-24 letters, digits, spaces, '.', '_' or '-', starting with a letter"

# Characters that read alike in common fonts, folded to one representative.
_FOLD = str.maketrans({"0": "o", "1": "l", "i": "l", "j": "l", "|": "l", "5": "s", "$": "s", "2": "z",
                       "3": "e", "4": "a", "6": "b", "8": "b", "9": "g", "7": "t", "q": "g"})
_PAIRS = (("rn", "m"), ("cl", "d"))


def skeleton(name: str) -> str:
    """A name reduced to what it looks like: two names with the same skeleton are look-alikes."""
    s = unicodedata.normalize("NFKC", name or "").casefold()
    s = re.sub(r"[\s_.\-]+", "", s).replace("vv", "w")
    s = s.translate(_FOLD)
    s = re.sub(r"(.)\1+", r"\1", s)     # "Saandy" ~ "Sandy"
    for a, b in _PAIRS:
        s = s.replace(a, b)
    return s


def shape_ok(name: str) -> bool:
    return bool(NAME_RE.match(name or ""))
