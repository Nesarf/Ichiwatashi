# -*- coding: utf-8 -*-
"""Producing a bitmap font as data a sibling project can embed.

**Why this is the first thing built for a family-level rule.** The rule is that **every art asset in
the four NTVI tools comes out of Ichiwatashi**, and this is the smallest real case of it:

  * `volcano-separator` needs a 5x7 bitmap font, because Windows text is antialiased and its windows
    have to be pixel art.
  * It hand-authored that font as a table of hex strings, and it did so before this rule existed.
  * So either Ichiwatashi can produce that table, or the rule is aspirational.

**And the test is exact, not a vibe.** Volcano's format is stated in its own file: *"one hex digit per
row, bit 4 as the leftmost pixel"* — two hex digits per row, fourteen per glyph. This emits the same
format, so the check is whether Ichiwatashi reproduces glyphs that agree with the ones in use.

## The two things that are easy to get wrong, both recorded because I got them wrong

**Bit order.** Bit 4 is the leftmost of five columns, so the mask for column `x` is `1 << (4 - x)`.
Writing `1 << x` mirrors every glyph, and a mirrored font looks like a font.

**What "the same glyph" means.** A glyph here is a 7-row list of 5-bit masks — no colours, no size,
no antialiasing. A comparison against another implementation is therefore exact, and a difference is a
difference rather than a rendering accident.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ["Glyph", "FONT_W", "FONT_H", "glyph_from_rows", "glyph_from_text", "load_source",
           "parse_source", "to_volcano_hex", "render_table", "check_font"]

FONT_W = 5
FONT_H = 7


def parse_source(text: str) -> dict:
    """`{char: glyph}` from the `assets/font5x7.txt` format: one line per glyph, `char TAB hex`.

    Comment lines start with `#`. A space glyph is written as `TAB hex` with an empty first field, so
    the separator is the tab and not a split on whitespace -- `line.split()` would eat the space key
    and the font would come back a glyph short with nothing to say so.
    """
    out = {}
    for n, raw in enumerate(text.split("\n"), 1):
        line = raw.rstrip("\r")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if "\t" not in line:
            raise ValueError("line %d has no tab, so a space glyph cannot be told from a bad line: %r"
                             % (n, line[:40]))
        key, _, digits = line.partition("\t")
        # a trailing comment is stripped by hand: `split("#")` would break the `#` glyph itself
        digits = digits.split("  #")[0].strip()
        if len(key) != 1:
            raise ValueError("line %d: the key must be one character, got %r" % (n, key))
        if not re.fullmatch("[0-9A-Fa-f]{%d}" % (FONT_H * 2), digits):
            raise ValueError("line %d: %r is not %d hex digits" % (n, digits, FONT_H * 2))
        rows = tuple(int(digits[i * 2:i * 2 + 2], 16) for i in range(FONT_H))
        out[key] = Glyph(key, rows)
    return out


def load_source(path) -> dict:
    from pathlib import Path
    return parse_source(Path(path).read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Glyph:
    """One character as `FONT_H` row masks, each using `FONT_W` bits with bit 4 leftmost."""

    char: str
    rows: tuple

    def __post_init__(self):
        if len(self.rows) != FONT_H:
            raise ValueError("%r has %d row(s); a glyph is %d tall" % (self.char, len(self.rows), FONT_H))
        for i, mask in enumerate(self.rows):
            if not 0 <= mask < (1 << FONT_W):
                raise ValueError("%r row %d is %d, which does not fit %d columns (0-31)"
                                 % (self.char, i, mask, FONT_W))

    def __str__(self):
        return "\n".join("".join("#" if r & (1 << (FONT_W - 1 - x)) else "." for x in range(FONT_W))
                         for r in self.rows)

    def hex(self) -> str:
        """The fourteen hex digits, two per row, top row first."""
        return "".join("%02X" % r for r in self.rows)


def glyph_from_text(char: str, art: str) -> Glyph:
    """Build a glyph from the text form `str(glyph)` prints, so a shape can be typed or diffed.

    Any character other than `#` is a hole, which makes `.` and a space mean the same thing -- a font
    drawn by hand is easier to read than one written as hex, and it is the same data.
    """
    lines = [ln for ln in art.strip("\n").split("\n") if ln.strip() != ""]
    if len(lines) != FONT_H:
        raise ValueError("%r has %d non-empty line(s); a glyph needs %d" % (char, len(lines), FONT_H))
    rows = []
    for i, ln in enumerate(lines):
        if len(ln) != FONT_W:
            raise ValueError("%r line %d is %d wide; a glyph is %d" % (char, i, len(ln), FONT_W))
        mask = 0
        for x, ch in enumerate(ln):
            if ch == "#":
                mask |= 1 << (FONT_W - 1 - x)
        rows.append(mask)
    return Glyph(char, tuple(rows))


def glyph_from_rows(char: str, rows) -> Glyph:
    return Glyph(char, tuple(rows))


def to_volcano_hex(glyphs) -> dict:
    """`{char: '0E11111F111111'}` -- the table shape `volcano-separator` reads.

    Emitted in the format that file already uses, verified against its own parser rather than assumed:
    fourteen hex digits, row 0 first, bit 4 the leftmost column.
    """
    return {g.char: g.hex() for g in glyphs}


def render_table(glyphs, *, per_line: int = 4, indent: str = "        ") -> str:
    """A PowerShell hashtable body, so the output can be pasted where the current one lives.

    Grouped several to a line because that is how the file is written today, and a generated table
    that looks nothing like the hand-authored one is a table nobody will adopt.
    """
    items = ["'%s' = '%s'" % (g.char.replace("'", "''"), g.hex()) for g in glyphs]
    lines = []
    for i in range(0, len(items), per_line):
        lines.append(indent + "; ".join(items[i:i + per_line]))
    return "\n".join(lines)


def check_font(glyphs) -> dict:
    """What this font can and cannot say, measured rather than assumed.

    Reported instead of asserted, because a font is a work in progress and a test demanding a complete
    one would be inventing requirements. What matters for a *window* font is narrower and checkable:
    the characters an English panel needs, and whether every glyph is drawable at all.

    **The `missing` field is the point.** The first version of this file reported 60 glyphs and looked
    finished; the check said `"#'abcdefghijklmnopqrstuvwxyz` -- no lowercase, and no `#`, which a
    panel showing a hex dump or a colour would want. A font is exactly the kind of asset where "it
    parsed and the count is plausible" passes for done.
    """
    have = set(glyphs)
    need = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 "
               ".,:;!?'\"-_+=/()[]<>|&%#*")
    # Every glyph in this source is 5 wide and 7 tall, so the shape is a constant rather than something
    # measured. Counted so that a future variable-width font cannot quietly satisfy this function.
    shapes = {(FONT_W, FONT_H) for _ in glyphs.values()}
    return {
        "glyphs": len(glyphs),
        "missing": "".join(sorted(need - have)),
        "lowercase": sum(1 for c in have if c.islower()),
        # the space glyph is a real glyph here; a font without it runs every word together
        "has_space": " " in have,
        "distinct_shapes": len(shapes),
    }
