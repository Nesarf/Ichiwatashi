# -*- coding: utf-8 -*-
"""Parametric sprite construction: describe a silhouette with shapes, then outline it automatically.

**Why this exists rather than just a grid editor.** Authoring a grid by hand requires already having a
finished silhouette in your head, which is the skill being learned. Writing one attempt at 32x32 that
way produced a block that was not recognisable, twice. Describing the same sprite as a cone, two
discs and a trapezoid produced something readable on the second attempt, because **getting a proportion
wrong becomes editing three numbers instead of re-placing hundreds of pixels** -- and iterating is what
actually converges.

That is not a claim that shapes beat hands. It is a claim about who is drawing: a person placing pixels
deliberately will beat this. An author who cannot yet do that will not, and this gets them to something
that communicates while they learn.

**The outline pass is not decoration.** Without it a silhouette dissolves into the background at small
sizes. It is automatic here for the same reason: it is a rule, not a decision.
"""
from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Canvas"]

TRANSPARENT = None


@dataclass
class Canvas:
    """A pixel grid you can draw shapes onto.

    `bg` is the key for transparent. Everything takes `key` names rather than colours so the same
    drawing can be re-rendered against a different palette without touching the shapes.
    """

    width: int
    height: int
    bg: str = "."
    _cells: list = None

    def __post_init__(self):
        self._cells = [self.bg] * (self.width * self.height)

    # -- primitives ------------------------------------------------------- #
    def get(self, x, y) -> str:
        if 0 <= x < self.width and 0 <= y < self.height:
            return self._cells[y * self.width + x]
        return self.bg

    def put(self, x, y, key: str) -> "Canvas":
        if 0 <= x < self.width and 0 <= y < self.height:
            self._cells[y * self.width + x] = key
        return self

    def rect(self, x0, y0, x1, y1, key: str) -> "Canvas":
        """Filled rectangle, inclusive of both corners."""
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                self.put(x, y, key)
        return self

    def disc(self, cx, cy, r, key: str) -> "Canvas":
        """Filled circle. `cx`/`cy` may be fractional so a sprite can sit on a half-pixel centre."""
        rr = r * r
        for y in range(self.height):
            for x in range(self.width):
                if (x - cx) ** 2 + (y - cy) ** 2 <= rr:
                    self.put(x, y, key)
        return self

    def _taper(self, y0, y1, w0, w1, key, cx):
        for y in range(y0, y1 + 1):
            t = 0.0 if y1 == y0 else (y - y0) / (y1 - y0)
            half = (w0 + (w1 - w0) * t) / 2
            for x in range(int(cx - half + 0.5), int(cx + half - 0.5) + 1):
                self.put(x, y, key)
        return self

    def trap(self, y0, y1, w0, w1, key: str, cx=None) -> "Canvas":
        """Trapezoid: a skirt, a sleeve, anything that widens or narrows as it descends."""
        return self._taper(y0, y1, w0, w1, key, cx if cx is not None else (self.width - 1) / 2)

    def cone(self, y0, y1, w0, w1, key: str, cx=None) -> "Canvas":
        """Same shape, named for readability when it is a hat."""
        return self._taper(y0, y1, w0, w1, key, cx if cx is not None else (self.width - 1) / 2)

    def line(self, x0, y0, x1, y1, key: str) -> "Canvas":
        """Bresenham, because a hand-rolled interpolation would produce gaps at some angles."""
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        while True:
            self.put(x0, y0, key)
            if x0 == x1 and y0 == y1:
                return self
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    # -- derived passes ---------------------------------------------------- #
    def recolor(self, mapping: dict) -> "Canvas":
        """Swap keys, e.g. to move a highlight after a shape has changed."""
        self._cells = [mapping.get(c, c) for c in self._cells]
        return self

    def shade(self, light: str, dark: str, *, depth: int = 2) -> "Canvas":
        """Split each shape key into a lit and a shadow key, using the shape's own extent.

        **This is the second version, and the first one is the reason it is written this way.** A rule
        of the form `(x + y) % 7 == 0` -- or `(x + y) < (width + height) / 2`, which is the same thing
        with the period taken out -- drew a diagonal sash across a skirt that nobody asked for. It was
        visible in the output and invisible in the intent, and a test caught it coming back after the
        comment had already been changed to say it was fixed.

        So this measures the shape instead of the coordinates: for each column of the region, the top
        `depth` pixels are lit and the bottom `depth` are shadowed. A rectangle comes back as two flat
        bands. **The rule is about the form; the form is what a highlight is supposed to describe.**
        """
        for key, lit in light.items():
            cols = {}
            for y in range(self.height):
                for x in range(self.width):
                    if self.get(x, y) == key:
                        cols.setdefault(x, []).append(y)
            for x, ys in cols.items():
                top, bottom = min(ys), max(ys)
                for y in ys:
                    if y < top + depth:
                        self.put(x, y, lit)
                    elif key in dark and y > bottom - depth:
                        self.put(x, y, dark[key])
        return self

    def outline(self, key: str, *, diagonal: bool = False) -> "Canvas":
        """Draw `key` in every empty cell that touches a filled one.

        `diagonal=False` is four-neighbour and gives a cleaner corner at small sizes; eight-neighbour
        closes diagonal gaps but fattens the silhouette. Four is the default for that reason.
        """
        offsets = ((1, 0), (-1, 0), (0, 1), (0, -1))
        if diagonal:
            offsets += ((1, 1), (1, -1), (-1, 1), (-1, -1))
        add = []
        for y in range(self.height):
            for x in range(self.width):
                if self.get(x, y) != self.bg:
                    continue
                for dx, dy in offsets:
                    if self.get(x + dx, y + dy) != self.bg:
                        add.append((x, y))
                        break
        for x, y in add:
            self.put(x, y, key)
        return self

    # -- output ------------------------------------------------------------ #
    def rows(self):
        return ["".join(self._cells[y * self.width:(y + 1) * self.width])
                for y in range(self.height)]

    def to_grid(self, palette: dict) -> dict:
        """The `{width, height, palette, pixels}` form, which is also the interchange format."""
        return {
            "width": self.width,
            "height": self.height,
            "palette": {k: ("transparent" if v is TRANSPARENT else
                            ("#%02X%02X%02X" % tuple(v) if not isinstance(v, str) else v))
                        for k, v in palette.items()},
            "pixels": self.rows(),
        }

    def to_image(self, palette: dict):
        """Rasterise to RGBA. Every cell is written individually -- this is the pixel output."""
        from PIL import Image

        im = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
        px = im.load()
        for y in range(self.height):
            for x in range(self.width):
                value = palette.get(self.get(x, y))
                # `to_grid` writes the *string* "transparent", so a round trip through the interchange
                # format puts a word where a colour is expected -- and `int("ra", 16)` comes out of
                # `"transparent"[1:3]`, which reads as a parsing bug rather than a missing case.
                if value is TRANSPARENT or value is None or (
                        isinstance(value, str) and value.lower() in ("transparent", "none", "")):
                    continue
                if isinstance(value, str):
                    value = tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))
                px[x, y] = (value[0], value[1], value[2], 255)
        return im

    def preview(self, scale: int = 8, palette: dict | None = None, bg=(255, 255, 255)):
        """Nearest-neighbour enlargement, for looking at. Never for output -- the sprite is the grid."""
        from PIL import Image

        im = self.to_image(palette or {self.bg: TRANSPARENT})
        big = Image.new("RGBA", (self.width * scale, self.height * scale), bg + (255,) if bg else None)
        big.alpha_composite(im.resize((self.width * scale, self.height * scale), Image.NEAREST))
        return big


def from_rows(rows, bg: str = ".") -> Canvas:
    """Build a canvas from literal rows. Raises on a ragged grid rather than padding it.

    A sprite that is silently the wrong shape shows up as a rendering bug somewhere far from the data
    that caused it, so a mismatch is refused at the point where it can still be named.
    """
    if not rows:
        raise ValueError("no rows")
    w = len(rows[0])
    for i, r in enumerate(rows):
        if len(r) != w:
            raise ValueError("row %d is %d wide, row 0 is %d" % (i, len(r), w))
    c = Canvas(w, len(rows), bg)
    c._cells = list("".join(rows))
    return c
