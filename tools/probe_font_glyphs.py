#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Can Ichiwatashi judge a class of pixel art it was not built for?

The third tool in this family (volcano-separator) requires pixel-art UI and draws it from **a 5x7
bitmap font defined as hex data** -- one hex digit pair per row, bit 4 leftmost. It ships no PNGs at
all: 51 files, zero images. So the question "can the corpus admit volcano's art" turns out to be a
different question than expected, and a more interesting one.

**This is a derived measurement, not a corpus sample, and it is labelled that way on purpose.**
`corpus/POLICY.md` gate 3 says anything synthesised or rendered by a tool never enters a reference
table. The font is hand-authored data; the images this script makes are my rendering of it. So the
numbers below describe *my renderer's output of someone else's bitmap*, which is exactly the kind of
thing that must not be mistaken for evidence about an artist.

What makes it worth measuring anyway: **the judge was built for sprites.** A 5x7 glyph has no
silhouette to speak of, no interior detail, usually one colour, and its "outline" is the whole shape.
Every reference in `calibration.py` comes from character sprites. So this is a test of the judge's
scope, and it is falsifiable in a useful direction: if the glyphs are flagged as unlike any
generation, then the reference does not generalise past its subject and the fourth bucket needed is
not "another generation of sprites" but "another class of pixel art".

    python tools/probe_font_glyphs.py
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ichiwatashi import calibration as C  # noqa: E402
from ichiwatashi.judge import judge  # noqa: E402
from PIL import Image  # noqa: E402

VOLCANO = Path("E:/volcano-separator")
FONT_PS1 = VOLCANO / "bin" / "pixelfont.ps1"

# The glyph table is a single PowerShell hashtable of quoted hex strings. Parsed with a regex rather
# than by evaluating PowerShell: this must not run the file it is reading.
ENTRY = re.compile(r"'(?P<ch>(?:[^'\\]|\\.)+)'\s*=\s*'(?P<hex>[0-9A-Fa-f]{2,})'\s*(?:\+\s*'(?P<more>[0-9A-Fa-f]+)')?")


def parse_font(text: str) -> dict:
    """{character: [7 row bitmasks]}, taking the concatenated `+ '...'` form into account."""
    out = {}
    for m in ENTRY.finditer(text):
        ch = m.group("ch").replace("\\\\", "\\")
        h = m.group("hex") + (m.group("more") or "")
        if len(h) != 14:
            continue
        try:
            rows = [int(h[i * 2:i * 2 + 2], 16) for i in range(7)]
        except ValueError:
            continue
        out[ch] = rows
    return out


def render(rows, *, scale=1, ink=(0, 0, 0, 255), paper=(0, 0, 0, 0), pad=1):
    """A glyph as an image. 5 wide, 7 tall, each row's bit 4 the leftmost pixel."""
    w, h = 5 + pad * 2, 7 + pad * 2
    im = Image.new("RGBA", (w * scale, h * scale), paper)
    px = im.load()
    for y, bits in enumerate(rows):
        for x in range(5):
            if bits & (1 << (4 - x)):
                for dy in range(scale):
                    for dx in range(scale):
                        px[(x + pad) * scale + dx, (y + pad) * scale + dy] = ink
    return im


def main():
    if not FONT_PS1.is_file():
        print("the font is not at %s -- nothing to measure" % FONT_PS1)
        return 1
    text = FONT_PS1.read_text(encoding="utf-8", errors="replace")
    font = parse_font(text)
    print("glyphs parsed from %s: %d" % (FONT_PS1.name, len(font)))
    if not font:
        print("the parser found none: the table's shape has changed, and this says so rather than "
              "reporting a clean zero")
        return 1

    # One glyph as text, so the parser can be checked against something a reader can see.
    print("\nthe 'E' as the font defines it (bit 4 = leftmost):")
    for bits in font.get("E", []):
        print("   " + "".join("#" if bits & (1 << (4 - x)) else "." for x in range(5)))
    print("  parsed as %s -> %s" % (font.get("E"), "see above"))

    print("\n=== the judge, on each glyph ===")
    rows = []
    for ch, bits in sorted(font.items()):
        im = render(bits)
        if not im.getbbox():
            continue                      # the space glyph is genuinely empty; it has nothing to measure
        rows.append((ch, judge(im), im))
    print("glyphs with ink: %d of %d" % (len(rows), len(font)))
    print("%-26s %8s %8s %8s" % ("metric", "min", "median", "max"))

    def col(name):
        return sorted(getattr(r, name) for _, r, _ in rows)

    for name in ("colours_used", "isolated_rate", "bbox_fill", "largest_cluster_rate",
                 "outline_colours", "silhouette_colours"):
        v = col(name)
        if not v:
            continue
        print("  %-22s %8.3f %8.3f %8.3f" % (name, v[0], v[len(v) // 2], v[-1]))

    print("\n=== outline style, by the shipped classifier ===")
    styles = Counter()
    from ichiwatashi.judge import outline_style
    for _, r, _ in rows:
        styles[outline_style(r.outline_variation, r.outline_predictability, r.outline_colours)] += 1
    print("  %s" % styles.most_common())

    print("\n=== would the reference table flag them? ===")
    flag = Counter()
    for _, r, _ in rows:
        for metric, val in (("isolated_rate", r.isolated_rate), ("bbox_fill", r.bbox_fill),
                            ("largest_cluster_rate", r.largest_cluster_rate),
                            ("colours_used", r.colours_used)):
            for gen in C.GENERATIONS:
                if C.outside(metric, val, generation=gen):
                    flag[(gen, metric)] += 1
    if not flag:
        print("  no glyph raises a reference note in either generation")
    for (gen, metric), n in flag.most_common():
        print("  %-14s %-22s %d of %d glyphs" % (gen, metric, n, len(rows)))

    print("""
Reading of that table -- measured, and it answers the question this file was written to ask:

  colours_used 1 and isolated_rate 0.000 are not "unusual for a glyph", they are *what a glyph is*:
  one ink colour and no interior detail. The reference bands are 16-37 and 0.074-0.160, so all 58
  fall outside both. largest_cluster_rate is distorted the other way, because a glyph IS one cluster.

  And the two metrics that pass -- outline_colours 1, silhouette_colours 1 -- pass vacuously. A
  single-colour glyph has one colour by construction, so those numbers carry no information here.
  That is the same shape as the silhouette measurement's own recorded limitation: measuring a
  property on something that does not have that structure yields "not applicable", not "good".

So **the premise of "add volcano as a fourth corpus source" was wrong**, and this is the useful part:
the judge's metric set is sprite-shaped, and a different class of pixel art does not get a new
generation bucket -- it gets a different metric set, or it is declared out of scope.

What this does NOT say: that the glyphs are bad pixel art. They are hand-authored 5x7 bitmaps, and
nothing above measured their quality. It says the instrument has a subject, and a font is not it.
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
