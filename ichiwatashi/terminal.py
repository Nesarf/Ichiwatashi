# -*- coding: utf-8 -*-
"""A panel as text: one character per logical pixel, so the interface can be asserted as a string.

**Why text and not a toolkit window, given that `tkinter` is present.** The panel layer's whole purpose is to
be verifiable by itself, and a toolkit window is not: what a test can check about it is whatever the toolkit
exposes, which is not the pixels. A character grid, on the other hand, **is** the rendering -- dump it and
compare it. So this is the smallest renderer that keeps the same guarantee, and it means "keyboard-operable"
can be tested rather than demonstrated.

Measured before choosing anything: `tkinter` present, `msvcrt` present (Windows key reads), `curses` and
`termios` absent, terminal 80x24. **A real window is reachable from here** -- this layer is where the
decisions get settled first, and a toolkit renderer can be added later against the same `panel` rows.

**One character is one logical pixel.** That keeps the pixel-art rule intact in an environment that has no
pixels: the border is one character thick because it is one pixel thick, and `TIERS` still mean what they mean.
"""
from __future__ import annotations

from . import panel as Pn

__all__ = ["CHARS", "rows", "status_line", "frame"]


#: One character per role. **Chosen so a dump reads as the thing it is**: `#` for the frame, a rule for the
#: title bar, blanks for the well. The two title bars differ, because their difference is the point.
CHARS = {
    "frame_dark": "#",
    "frame_light": "+",
    # **A horizontal rule for the bar and a heavy mark for the text**, so the two are distinguishable in one
    # glance. The first version used `=` for the bar and `#` for the glyphs, which at 5x7 reads as noise --
    # the glyphs sit *in* the bar and have to be the darker mark of the two.
    "title": "-",
    "title_inactive": ".",
    "title_text": None,     # the glyphs are drawn as themselves, not as one character
    "close_mark": "x",      # the same mark the window draws, so the text version shows it too
    "well": " ",
    "content": " ",
}


def rows(spec, width, height, *, title=None, active=True, glyphs=None):
    """The panel as one string per row, using `panel.layout` for every position.

    **The geometry comes from `panel.layout`, not from here.** Two independent ideas of where a border goes is
    the defect this repository has already fixed once (a renderer and a checker each doing their own
    arithmetic); repeating it in a second renderer would be the same mistake with more places to make it.
    """
    from . import figures as FIG

    where = Pn.layout(spec, width, height)
    grid = [[" "] * width for _ in range(height)]
    for y in range(height):
        for x in range(width):
            role = Pn._role_at(spec, where, x, y, active=active)
            if role is None:
                continue
            ch = CHARS.get(role)
            if ch is not None:
                grid[y][x] = ch
    if title:
        # the same overlap rule `panel.draw` uses: refuse a title that does not fit rather than clip it
        tx0, ty0, tx1, _ty1 = where["title"]
        cx0, _cy0, cx1, _cy1 = where["content"]
        start = max(tx0 + spec.pad, cx0)
        if start + FIG.text_width(title) > tx1:
            raise ValueError("title %r needs %d columns but the title bar has %d"
                             % (title, FIG.text_width(title), tx1 - start))
        # the glyphs are written into the grid as themselves, one column per pixel column of the glyph
        text_rows = _text_grid(title, glyphs=glyphs)
        for dy, text_row in enumerate(text_rows):
            for dx, ch in enumerate(text_row):
                if ch != " ":
                    px, py = start + dx, ty0 + 1 + dy
                    if py < height and px < cx1:
                        grid[py][px] = ch
    return ["".join(r) for r in grid]


def _text_grid(s: str, *, glyphs=None):
    """The title as rows of `#` and spaces, using the same 5x7 table the image renderer uses."""
    from . import figures as FIG
    from . import font as FONT

    if glyphs is None:
        glyphs = FONT.load_source(FIG.FONT_PATH)
    out = [[" "] * (FIG.text_width(s)) for _ in range(FONT.FONT_H)]
    cursor = 0
    for ch in s:
        g = glyphs.get(ch)
        if g is None:
            cursor += 6
            continue
        for row_i, bits in enumerate(g.rows):
            # **bit 4 is the leftmost of five columns**, the convention `font.Glyph` documents; reading it the
            # other way mirrors every glyph, which is the kind of error that looks like a font defect
            for col in range(5):
                if bits & (1 << (4 - col)):
                    if row_i < len(out) and cursor + col < len(out[row_i]):
                        out[row_i][cursor + col] = "#"
        cursor += 6
    return ["".join(r) for r in out]


def status_line(*, focus=None, active=True, hint=None):
    """One line under the panel: what holds the focus, whether the window is active, and what keys do.

    **A status line rather than nothing**, because the focus ring is invisible otherwise -- and a keyboard
    interface whose current target cannot be seen is not operable, it is guessable.
    """
    parts = []
    parts.append("active" if active else "inactive")
    if focus is not None:
        if focus.count:
            parts.append("focus %d/%d" % (focus.index + 1, focus.count))
        else:
            parts.append("no control focused")
    if hint:
        parts.append(hint)
    return "  ".join(parts)


def frame(spec, width, height, *, title=None, active=True, focus=None, hint=None, glyphs=None):
    """The panel rows plus a status line, as one block of text ready to print or compare."""
    body = rows(spec, width, height, title=title, active=active, glyphs=glyphs)
    return body + [status_line(focus=focus, active=active, hint=hint)]
