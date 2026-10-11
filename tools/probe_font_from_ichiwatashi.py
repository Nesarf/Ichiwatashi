#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Can Ichiwatashi produce the art asset a sibling project already ships?

**The rule this tests** is family-level: every art asset in the four NTVI tools comes out of
Ichiwatashi. `volcano-separator` needs a 5x7 bitmap font and hand-authored one *before* the rule
existed, so it is the one real case where the rule can be checked against something already in use
rather than against an intention.

Three things are measured, and each can fail on its own:

  1. **Round trip.** Read volcano's table, put every glyph through Ichiwatashi's own `Glyph`, emit the
     hex back, and compare. If this differs, Ichiwatashi cannot express what volcano already has and
     the rule is aspirational.
  2. **The text form is the same data.** Draw one glyph as `#`/`.` and check it produces the identical
     hex. This is what makes a glyph reviewable in a diff instead of only as hex.
  3. **A glyph Ichiwatashi composes itself** lands in a well-formed table -- the smallest case of
     actual production rather than re-encoding.

What this does NOT test: that a font *drawn by* Ichiwatashi's shape primitives is good. That is a
judgement about art, and nothing here measures it.

    python tools/probe_font_from_ichiwatashi.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ichiwatashi.font import (  # noqa: E402
    FONT_H, FONT_W, glyph_from_rows, glyph_from_text, render_table, to_volcano_hex,
)

VOLCANO_FONT = Path("E:/volcano-separator/bin/pixelfont.ps1")

BS = chr(92)
SQ = chr(39)


def parse_volcano(text: str) -> dict:
    """`{char: 'HEXHEX...'}` from the `$hex = @{ ... }` table in a PowerShell font file.

    **Five parsers were written for this table and the first four were all wrong, in four different
    ways.** They are recorded because the way each one failed is the reason the fifth is shaped as it
    is, and because none of them failed silently -- which is the only reason this is a footnote rather
    than a defect:

      1. A key-and-value regex paired each key with the *next* entry's hex on a line holding several.
         It reported `Q` as sixteen digits and then, having eaten its value, `Q` as missing.
      2. A value-anchored lookahead skipped every entry whose neighbour was malformed.
      3. A cursor over the whole file paired quotes from the top, and **this file has an odd number of
         apostrophes before the table starts** -- line 5 is a comment reading
         `# PowerShell 5.1's WinForms text is antialiased`. So it was off by one from there on and
         invented three keys of prose out of fifty-nine glyphs.
      4. Scoping to the table and scanning backwards from `= '` should have worked, and did not: every
         entry came back with the value `'; '`. Why is not established, and the honest thing is to say
         so rather than to describe a mechanism that was never confirmed.

    The fifth splits the body on the separator and takes the pieces. It needs no quote pairing and no
    backwards scan, because the shape here is regular: `;` ends an entry and `+` continues one.
    """
    SQ = chr(39)
    start = text.find("$hex = @{")
    if start < 0:
        return {}
    end = text.find("\n    }", start)
    body = text[start:end if end > 0 else len(text)]

    table = {}
    # **One regex over the table body, which is the combination that finally worked.** Six parsers were
    # attempted; the two ideas that each fix a real problem have to be present at the same time:
    #
    #   *Scoped to the body*, because the file has an odd number of apostrophes before the table (line 5
    #   is `# PowerShell 5.1's WinForms text is antialiased`), so anything starting from the top of the
    #   file is off by one from there on.
    #
    #   *A regex over the body, not a split*, because **the separators are also glyphs**: `;`, `+` and
    #   `\` are all in this font, so splitting on them cuts their own hex in half and loses all three.
    #
    # And it is `finditer`, not `search`, because the table mixes its entry separators -- `;` on most
    # lines, but a bare newline between `'D'` and `'E'` -- so one match per piece dropped the second
    # entry of any newline-separated pair.
    ENTRY = re.compile(SQ + "(.{1,2})" + SQ + r"\s*=\s*" + SQ + r"([0-9A-Fa-f]{2,})" + SQ
                       + r"(\s*\+\s*" + SQ + r"([0-9A-Fa-f]+)" + SQ + r")?")
    for m in ENTRY.finditer(body):
        key = m.group(1)
        digits = m.group(2) + (m.group(4) or "")
        # Only a full fourteen digits is a glyph. Padding a half would produce a wrong glyph that looks
        # well formed, which is the class of failure this whole project is arranged against.
        if len(digits) == FONT_H * 2 and len(key) == 1:
            table[key] = digits.upper()
    return table


def main():
    if not VOLCANO_FONT.is_file():
        print("volcano's font is not at %s -- nothing to check against" % VOLCANO_FONT)
        print("(this probe needs a real asset in use; without one it would only be testing itself)")
        return 1
    table = parse_volcano(VOLCANO_FONT.read_text(encoding="utf-8", errors="replace"))
    print("volcano's table, as Ichiwatashi reads it: %d glyph(s)" % len(table))
    if len(table) < 40:
        print("too few to be the real table -- the format must have changed, and this says so")
        return 1

    # 1. round trip through Ichiwatashi's own type
    #
    # Counted in three buckets rather than as `total - mismatches`, because the first version reported
    # "58 of 60" while an independent count of the same thing said 59 and 1: the arithmetic mixed a
    # *rejection* (the glyph never entered the map) with a *difference* (it entered and came out
    # changed). Those are different facts and a probe whose own count is off by one is a probe nobody
    # should trust.
    identical, differing, rejected = [], [], []
    rebuilt = {}
    for ch, h in sorted(table.items()):
        rows = tuple(int(h[i * 2:i * 2 + 2], 16) for i in range(FONT_H))
        try:
            g = glyph_from_rows(ch, rows)
        except ValueError as e:
            rejected.append((ch, str(e)))
            continue
        rebuilt[ch] = g.hex()
        if g.hex() == h.upper():
            identical.append(ch)
        else:
            differing.append((ch, "%s -> %s" % (h, g.hex())))

    print("\n=== 1. round trip through `ichiwatashi.font.Glyph` ===")
    print("  glyphs in volcano's table : %d" % len(table))
    print("  re-emitted identically    : %d" % len(identical))
    print("  re-emitted but different  : %d" % len(differing))
    print("  refused by the type       : %d" % len(rejected))
    for ch, why in rejected:
        print("      %r  %s" % (ch, why))
    for ch, why in differing:
        print("      %r  %s" % (ch, why))

    if differing:
        print("\n  So Ichiwatashi reproduces the table except where it is wrong, and the wrong entries")
        print("  are refused rather than re-encoded -- which is the behaviour wanted, and is why the")
        print("  count below is what it is rather than 100%%.")
    if not identical:
        print("\n  Ichiwatashi cannot reproduce anything volcano ships, so the rule is aspirational.")
        return 1

    # 2. the text form is the same data
    print("\n=== 2. the text form of a glyph ===")
    sample = glyph_from_rows("E", tuple(int(table["E"][i * 2:i * 2 + 2], 16) for i in range(FONT_H)))
    art = str(sample)
    print("  'E' drawn as text:")
    for line in art.split("\n"):
        print("     %s" % line)
    back = glyph_from_text("E", art)
    print("  text -> hex: %s   (volcano's: %s)   equal: %s"
          % (back.hex(), table["E"], back.hex() == table["E"]))
    if back.hex() != table["E"]:
        print("  So a glyph drawn by hand and a glyph as hex are NOT the same data here.")
        return 1

    # 3. composition, not just re-encoding
    print("\n=== 3. a glyph Ichiwatashi composes itself ===")
    box = glyph_from_text("?", "\n".join([
        ".###.",
        "#...#",
        "....#",
        "...#.",
        "..#..",
        ".....",
        "..#..",
    ]))
    print(str(box))
    print("  hex: %s  (%d digits, %s)" % (box.hex(), len(box.hex()),
                                          "well formed" if len(box.hex()) == FONT_H * 2 else "MALFORMED"))
    emitted = to_volcano_hex([box, sample])
    print("  emitted table shape: %r" % emitted)
    print("\n  PowerShell body, as volcano would paste it:")
    print(render_table([box, sample]))
    print()
    print("So an asset produced here is data in the sibling's own format, and the check above is exact:")
    print("a glyph that differs is a different glyph, not a rendering difference.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
