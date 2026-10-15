"""American English in everything people or agents read (job 12): pages, cards, play cards,
messages, docs, the README, and the code that produces them.

The check reads every text file the repository tracks, except vendored code, recorded fixtures,
license texts, and the upstream code inside patch files (only a patch's own description is ours).
A line that keeps a British spelling on purpose (an old API name that still works, the British
spelling of a CSS color people may type) says so with "spelling: kept".
"""

from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# British spelling -> American. Whole words, any case. ("towards" is fine in both.)
BRITISH = {
    "colour": "color", "colours": "colors", "coloured": "colored", "colouring": "coloring", "colourful": "colorful",
    "recolour": "recolor", "centre": "center", "centres": "centers", "centred": "centered",
    "grey": "gray", "greyed": "grayed", "greys": "grays", "labelled": "labeled", "labelling": "labeling",
    "behaviour": "behavior", "behaviours": "behaviors", "licence": "license", "honour": "honor",
    "honours": "honors", "honoured": "honored", "defence": "defense", "offence": "offense",
    "favourite": "favorite", "favour": "favor", "neighbour": "neighbor", "neighbours": "neighbors",
    "harbour": "harbor", "armour": "armor", "humour": "humor", "flavour": "flavor", "endeavour": "endeavor",
    "rumour": "rumor", "vapour": "vapor", "parlour": "parlor", "odour": "odor", "labour": "labor",
    "normalise": "normalize", "normalises": "normalizes", "normalised": "normalized",
    "initialise": "initialize", "initialised": "initialized", "recognise": "recognize", "recognised": "recognized",
    "organise": "organize", "organised": "organized", "realise": "realize", "realised": "realized",
    "summarise": "summarize", "summarised": "summarized", "minimise": "minimize", "maximise": "maximize",
    "optimise": "optimize", "optimised": "optimized", "prioritise": "prioritize", "customise": "customize",
    "utilise": "utilize", "emphasise": "emphasize", "apologise": "apologize", "synchronise": "synchronize",
    "generalise": "generalize", "generalised": "generalized", "visualise": "visualize", "finalise": "finalize",
    "serialise": "serialize", "serialised": "serialized", "authorise": "authorize", "authorised": "authorized",
    "categorise": "categorize", "memorise": "memorize", "standardise": "standardize", "specialise": "specialize",
    "analyse": "analyze", "analysed": "analyzed", "paralyse": "paralyze", "catalogue": "catalog",
    "travelled": "traveled", "travelling": "traveling", "cancelled": "canceled", "cancelling": "canceling",
    "modelling": "modeling", "modelled": "modeled", "signalled": "signaled", "signalling": "signaling",
    "fuelled": "fueled", "levelled": "leveled", "marvellous": "marvelous", "jewellery": "jewelry",
    "metre": "meter", "metres": "meters", "litre": "liter", "theatre": "theater", "fibre": "fiber",
    "whilst": "while", "amongst": "among", "learnt": "learned", "spelt": "spelled", "dreamt": "dreamed",
    "judgement": "judgment", "artefact": "artifact", "artefacts": "artifacts", "mould": "mold",
    "moulded": "molded", "practise": "practice", "tyre": "tire", "kerb": "curb", "cheque": "check",
    "aluminium": "aluminum", "sceptical": "skeptical", "plough": "plow", "programme": "program",
    "enrol": "enroll", "fulfil": "fulfill", "manoeuvre": "maneuver", "aeroplane": "airplane",
    "storey": "story", "draught": "draft", "gaol": "jail", "pyjamas": "pajamas",
}
WORD = re.compile(r"\b(" + "|".join(sorted(BRITISH, key=len, reverse=True)) + r")\b", re.I)
TEXT = (".py", ".js", ".cjs", ".lua", ".md", ".html", ".css", ".toml", ".txt", ".patch", ".json")
SKIP = ("tests/fixtures/", "worlds/beach/static/vendor/", "tests/test_spelling.py")


def british_lines(text: str, patch: bool = False):
    if patch:   # only the patch's description is ours; the diff below it is upstream code
        text = text.split("\ndiff --git", 1)[0]
    for n, line in enumerate(text.splitlines(), 1):
        if "spelling: kept" in line:
            continue
        for m in WORD.finditer(line):
            yield n, m.group(1), line.strip()


class SpellingTests(unittest.TestCase):
    def test_no_british_spellings(self):
        files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True,
                               stdin=subprocess.DEVNULL).stdout.split()
        if not files:
            self.skipTest("not a git checkout")
        found = []
        for f in files:
            if f.startswith(SKIP) or "LICENSE" in f or not f.endswith(TEXT):
                continue
            path = ROOT / f
            if not path.exists():
                continue
            for n, word, line in british_lines(path.read_text(errors="replace"), patch=f.endswith(".patch")):
                found.append(f"{f}:{n}: {word} -> {BRITISH[word.lower()]}: {line[:100]}")
        self.assertEqual(found, [], "British spellings:\n" + "\n".join(found[:60]))

    def test_the_check_catches_them(self):
        # The check itself: a British spelling is found, an American one isn't, a kept one is allowed.
        sample = "Pick a colour.\nThe center.\nOld name: colours  # spelling: kept\nA gray sky, grey sea."
        self.assertEqual([w for _, w, _ in british_lines(sample)], ["colour", "grey"])
        patch = "Why: the colour.\n\ndiff --git a/x b/x\n-  centre\n+  centre"
        self.assertEqual([w for _, w, _ in british_lines(patch, patch=True)], ["colour"])

    def test_old_names_still_work(self):
        # Renamed for the spelling; the old names keep working.
        from beach import colors, colours
        self.assertIs(colours.ColourError, colors.ColorError)
        self.assertEqual(colors.parse("dark slate grey")[1], colors.parse("dark slate gray")[1])
        app = (ROOT / "beach" / "app.py").read_text()
        self.assertIn('"colours": avatar_mod.hexes(rec)', app)
        lua = (ROOT / "worlds" / "beach" / "main.lua").read_text()
        self.assertIn("centre = { CONFIG.center.X, CONFIG.center.Z }", lua)


if __name__ == "__main__":
    unittest.main()
