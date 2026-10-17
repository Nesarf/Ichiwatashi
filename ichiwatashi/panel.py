# -*- coding: utf-8 -*-
"""A panel: the frame, title bar and content well that a window is made of.

**Why this exists before any window does.** NTVI asks all four tools for a graphical window with a matching
set of pixel-art assets, and assigns **Ichiwatashi** to *produce* the shared pixel layer -- font, palette,
panel layout -- which the other tools **embed**. Something that is going to be embedded by three other
projects has to be **verifiable by itself**, or every embedding is a separate act of faith.

So this module is deliberately not a GUI. It is three things in the shape the font already has:

    a data description    `PanelSpec` -- border thickness, title height, padding, bevel
    a renderer            `draw()` -- drawn on a `builder.Canvas`, using `figures.draw_text` for glyphs
    a pixel check         `check()` -- re-reads a rendered panel and reports every disagreement

**`draw` and `check` share one definition and that was a correction.** The first version had `draw` paint the
frame as "a dark rectangle, then a light face inside it" while `check` derived the expected role from a
diagonal lit/shaded split. Two renderers agreeing with each other verifies nothing -- they can both be wrong
in the same way, or right in different ways. `_role_at` is now the only definition: `draw` walks it and paints,
`check` walks it and compares. What the check then verifies is **the pixels against the layout**, which is what
it was needed for.

**The check is the point.** `figures.palette_board` taught this repository twice that a wrong frame still
renders: a pitch one pad short made every swatch eat its neighbour whole, and a near-black fill derived a
near-black ring so one swatch had no edge -- and both figures saved successfully. A frame is exactly the kind
of thing that can be off by one pixel and still look fine.

**Keys, not colours.** `builder.Canvas` takes key names so the same drawing can be re-rendered against another
palette without touching the shapes, and `figures` makes that a rule: every colour in a figure comes from the
figure's own key table. A panel is the most likely thing in this repository to be recoloured by someone else,
so it holds to the same rule.
"""
from __future__ import annotations

from dataclasses import dataclass

__all__ = ["PanelSpec", "PANEL_ROLES", "PANEL_KEYS", "PANEL_PALETTE", "TIERS", "tier",
           "layout", "draw", "render", "check", "title_room", "close_pixels"]


#: Which job each colour does in a panel. **Named rather than positional**, because the whole reason the
#: shared layer is produced once is that four tools must not each invent their own four jobs.
#: **A panel becomes a window when its title bar can show whether it is the active one.** Two title roles
#: rather than a tint applied at render time, because the difference has to be a *role* for `check` to verify
#: it -- a tint would be a rendering detail that no test could see.
PANEL_ROLES = ("frame_dark", "frame_light", "title", "title_inactive", "title_text",
               "close_mark", "well", "content")

#: One key per role. **Unique even where two roles share a colour**, because `check` compares keys: a shared
#: key would let a pixel in the title bar satisfy the frame's expectation, and the check would pass on a panel
#: with its parts in the wrong places.
PANEL_KEYS = {"frame_dark": "fd", "frame_light": "fl", "title": "ta", "title_inactive": "ti",
              "title_text": "tx", "close_mark": "cm", "well": "wl", "content": "ct"}

#: The size tiers, as `(width, height)` in logical pixels. **One layout at three sizes, not three layouts** --
#: which is only true if every tier passes the same check, and a test asserts that. The narrowest tier is sized
#: so the default title bar can hold a five-character title; anything longer is refused with both numbers, at
#: whatever tier it was asked for.
TIERS = {
    "compact": (72, 30),
    "normal": (96, 40),
    "wide": (160, 48),
}


def tier(name):
    """`(PanelSpec(), width, height)` for a named size, refused by name if it is not one."""
    if name not in TIERS:
        raise ValueError("unknown tier %r; known: %s" % (name, ", ".join(sorted(TIERS))))
    w, h = TIERS[name]
    return PanelSpec(), w, h


#: A default set of colours for those keys: a dark window, as a starting point rather than a house style.
#: Callers pass their own -- what this layer shares is the measurements, not one palette.
PANEL_PALETTE = {
    "fd": (24, 22, 32, 255),      # outermost ring
    "fl": (96, 88, 128, 255),     # the bevel's lit edge
    "ta": (52, 44, 72, 255),      # title bar, active
    "ti": (30, 27, 40, 255),      # title bar, inactive -- darker and desaturated, the usual cue
    "tx": (232, 228, 244, 255),   # title text
    "cm": (208, 72, 88, 255),     # the close mark: red, so it reads as the one destructive control
    "wl": (36, 32, 48, 255),      # the well's floor
    "ct": (60, 52, 84, 255),      # content area
}


@dataclass
class PanelSpec:
    """A panel's measurements, in logical pixels.

    The defaults are sized around `font5x7`'s glyphs: a title bar has to hold a 7-pixel glyph with a pixel of
    clearance above and below, so `title_h` is 9 rather than something arbitrary. **A title bar that cannot
    hold a glyph is not a title bar**, and deriving the height from the glyph keeps the two from drifting.
    """
    border: int = 2       # frame thickness; 2 gives room for a lit edge and a shaded one
    title_h: int = 9      # holds a 5x7 glyph plus one pixel above and below
    pad: int = 2          # gap between the frame and the well
    bevel: bool = True    # lit on the top and left of the frame, shaded on the bottom and right
    close: bool = True    # a mark at the right end of the title bar, because the system's is not used

    def __post_init__(self):
        if self.border < 1:
            raise ValueError("a border of %d is not a border" % self.border)
        if self.title_h < 1:
            raise ValueError("a title bar of %d is not a title bar" % self.title_h)
        if self.pad < 0:
            raise ValueError("padding cannot be negative")


def layout(spec, width, height):
    """Where each part of the panel goes, as half-open rectangles `(x0, y0, x1, y1)`.

    Returned rather than recomputed inside `draw`, because `check` has to agree with `draw` about the answer
    **and agreement is only checkable against one definition**.
    """
    if width < 2 * spec.border + 2:
        raise ValueError("width %d cannot hold border %d on both sides plus content"
                         % (width, spec.border))
    if height < 2 * spec.border + spec.title_h + 2:
        raise ValueError("height %d cannot hold border %d, a title of %d and content"
                         % (height, spec.border, spec.title_h))
    b = spec.border
    title = (b, b, width - b, b + spec.title_h)
    # **the close mark sits at the right end of the title bar and is sized from it**, so a taller bar gets a
    # proportionally larger mark rather than a gap. Square, because a mark that changes shape with the bar's
    # height would need its own layout rules.
    side = min(spec.title_h, 7)
    close = None
    if spec.close:
        cx1 = title[2]
        cx0 = cx1 - side
        # centred vertically in the bar
        cy0 = title[1] + (spec.title_h - side) // 2
        close = (cx0, cy0, cx1, cy0 + side)
    where = {
        "frame": (0, 0, width, height),
        "title": title,
        "close": close,
        "well": (b, b + spec.title_h, width - b, height - b),
        "content": (b + spec.pad, b + spec.title_h + spec.pad,
                    width - b - spec.pad, height - b - spec.pad),
    }
    # **computed once here and carried in the layout**, because `_role_at` runs per pixel and would otherwise
    # rebuild the mark's shape for every one of them
    where["_close_px"] = close_pixels(spec, where)
    return where


def _role_at(spec, where, x, y, *, active=True):
    """The role a pixel at `(x, y)` carries. **The single definition** that `draw` and `check` both walk.

    Order matters and is what makes a report readable: frame, then its bevel, then the title, then the well,
    then the content. A pixel is attributed to the outermost part whose rectangle contains it, which is the
    order a person reading the panel looks at it.
    """
    def inside(rect):
        x0, y0, x1, y1 = rect
        return x0 <= x < x1 and y0 <= y < y1

    if not inside(where["frame"]):
        return None
    b = spec.border
    if spec.bevel and b >= 2:
        dist = min(x, y, where["frame"][2] - 1 - x, where["frame"][3] - 1 - y)
        if dist == 0:
            return "frame_dark"
        if dist == 1:
            # **Lit on the top and left, shaded on the bottom and right.** A bevel is asymmetric by
            # definition; testing the two sides separately is clearer than an expression trying to capture
            # "closer to the light" in one comparison, which is what the first version got wrong.
            #
            # **A corner belongs to two edges, and this rule gives it to the top or the left**, because the
            # test is `or`. Measured: the bottom inner ring reads `"l" + "d" * 94` and the right one the
            # same -- one lit pixel at the corner it shares with a lit edge. That is a convention, not a
            # derivation, so it is stated here and asserted in the tests rather than left to be discovered.
            if (y - 0) == 1 or (x - 0) == 1:
                return "frame_light"
            return "frame_dark"
    if (x, y) in where.get("_close_px", ()):
        return "close_mark"
    if inside(where["content"]):
        return "content"
    if inside(where["title"]):
        # **the one place a window differs from a panel**: the title bar's colour is the visible record of
        # whether this window is the active one
        return "title" if active else "title_inactive"
    if inside(where["well"]):
        return "well"
    return "frame_dark"


def title_room(spec, where):
    """`(start_x, available_width)` for the title. **One definition**, because three places need it.

    **The mark takes room from the title, not the other way round.** Measured: without this the title's
    available width ran to the frame's inner edge and a title that fit could run underneath the close mark --
    the check would still pass, because the mark's own pixels are asserted separately, so the collision would
    be invisible in the one place it matters.
    """
    tx0, _ty0, tx1, _ty1 = where["title"]
    cx0, _cy0, _cx1, _cy1 = where["content"]
    start = max(tx0 + spec.pad, cx0)
    right = where["close"][0] if where.get("close") else tx1
    return start, max(0, right - start)


def close_pixels(spec, where):
    """The pixels the close mark occupies, as a set. **One definition**, used by `draw` and by `check`.

    The mark is the `X` glyph from the same 5x7 table every other glyph comes from, centred in the square
    `layout` reserved for it. **Centred rather than stretched**: a mark scaled to fill an arbitrary square
    would change shape with the title bar's height, and a shape that changes with a measurement is one more
    thing that can be wrong without being visible.

    Returns an empty set when the spec has no close mark.
    """
    from . import font as FONT

    rect = where.get("close")
    if not rect:
        return set()
    x0, y0, x1, y1 = rect
    side = x1 - x0
    rows = _X_ROWS(side)
    # centre the glyph: a 5-wide mark in a 7-wide square starts at column 1
    off_x = (side - len(rows[0])) // 2 if rows else 0
    off_y = (side - len(rows)) // 2 if rows else 0
    out = set()
    for dy, row in enumerate(rows):
        for dx, ch in enumerate(row):
            if ch != " ":
                out.add((x0 + off_x + dx, y0 + off_y + dy))
    return out


def _X_ROWS(side):
    """A five-wide `X` when there is room, a three-wide one when there is not."""
    if side >= 5:
        return ["#   #", " # # ", "  #  ", " # # ", "#   #"]
    if side >= 3:
        return ["# #", " # ", "# #"]
    return ["#"]


def draw(spec, width, height, *, keys, title=None, body=None, glyphs=None, active=True):
    """Render a panel onto a fresh canvas at one pixel per pixel.

    `keys` maps every `PANEL_ROLES` entry to a `builder` key. **Nothing is defaulted**, because a default
    colour is a decision four tools would inherit silently -- the palette is the caller's; what the shared
    layer shares is the *measurements*.

    `title` is drawn inside the title bar with `figures.draw_text`, one row below its top so the glyph clears
    the frame. `body` is an optional list of rows of role names, placed at the content rectangle and clipped
    to it.
    """
    from . import builder as B
    from . import figures as FIG

    missing = [r for r in PANEL_ROLES if r not in keys]
    if missing:
        raise ValueError("keys is missing %s; every role is required" % ", ".join(missing))
    where = layout(spec, width, height)
    cv = B.Canvas(width, height)
    for y in range(height):
        for x in range(width):
            role = _role_at(spec, where, x, y, active=active)
            if role is not None:
                cv.put(x, y, keys[role])
    cx0, cy0, cx1, cy1 = where["content"]
    if body is not None:
        for row_i, row in enumerate(body):
            for col_i, role in enumerate(row):
                if role is None:
                    continue
                px, py = cx0 + col_i, cy0 + row_i
                if px < cx1 and py < cy1:
                    cv.put(px, py, keys[role])
    if title:
        ty0 = where["title"][1]
        start, room = title_room(spec, where)
        # **A title that does not fit is refused, not clipped.** Measured: a 64-pixel panel with the default
        # spec has 58 pixels of room, and "Ichiwatashi" is 66 wide at 6 per character -- so the first version
        # drew "Ichi wa.ta.sk", a word that is not the one the caller passed. A panel title that silently
        # becomes a different word is the same failure as a figure whose label ran off its canvas: the image
        # still saved, and nothing said so.
        need = FIG.text_width(title)
        if need > room:
            raise ValueError("title %r needs %d px but the title bar has %d; widen the panel or shorten the "
                             "title" % (title, need, room))
        FIG.draw_text(cv, start, ty0 + 1, title, keys["title_text"], glyphs=glyphs)
    return cv


def render(spec, width, height, *, keys, palette, title=None, body=None, glyphs=None, scale: int = 1,
           active=True):
    """A panel as an image, at one pixel per pixel then an **integer** nearest-neighbour upscale.

    The upscale is integer and `NEAREST` because that is this project's rule everywhere: a fractional resize
    is no longer the art that was drawn, and a smooth filter would invent colours that are not in the palette.
    `scale` is refused rather than coerced, so a caller asking for 1.5 is told no instead of being given 2.
    """
    if not isinstance(scale, int) or scale < 1:
        raise ValueError("scale must be a positive whole number, got %r" % (scale,))
    cv = draw(spec, width, height, keys=keys, title=title, body=body, glyphs=glyphs, active=active)
    im = cv.to_image(palette)
    if scale != 1:
        from PIL import Image

        im = im.resize((im.width * scale, im.height * scale), Image.NEAREST)
    return im


def check(spec, canvas, *, keys, title=None, active=True):
    """Re-read a rendered panel and report every pixel that disagrees with `layout`.

    Returns a list of `(x, y, expected_role, found_key)`, **empty when the panel is what `layout` says**.
    The expected role comes from `_role_at` -- the same function `draw` painted from -- so this checks **the
    pixels against the panel's definition**, not one renderer against another.

    **`title` is excluded rather than ignored.** The first version reported 90 problems on a correct panel,
    every one of them a `title_text` pixel sitting where `title` was expected: the glyphs are drawn *over*
    the title bar, so those pixels are legitimately not the bar's colour. Passing `title` here lets the check
    step over **exactly the rectangle the text occupies** -- computed from the same `draw_text` metrics `draw`
    used -- so the rest of the bar is still verified. Skipping the whole bar would lose that.
    """
    from . import figures as FIG

    where = layout(spec, canvas.width, canvas.height)
    skip = None
    if title:
        start, room = title_room(spec, where)
        if FIG.text_width(title) > room:
            # a reported problem with no pixel coordinates: it is about the layout, not about a pixel
            return [(-1, -1, "title_fits", "%r is %d px, %d available"
                     % (title, FIG.text_width(title), room))]
        tx0, ty0, _tx1, _ty1 = where["title"]
        cx0, _cy0, _cx1, _cy1 = where["content"]
        start = max(tx0 + spec.pad, cx0)
        # the glyph box: `draw` places the title at `ty0 + 1`, and a glyph is FONT_H rows tall
        skip = (start, ty0 + 1, start + FIG.text_width(title), ty0 + 1 + 7)
    problems = []
    for y in range(canvas.height):
        for x in range(canvas.width):
            role = _role_at(spec, where, x, y, active=active)
            if role is None:
                continue
            if skip and skip[0] <= x < skip[2] and skip[1] <= y < skip[3]:
                continue
            found = canvas.get(x, y)
            if found != keys[role]:
                problems.append((x, y, role, found))
    return problems
