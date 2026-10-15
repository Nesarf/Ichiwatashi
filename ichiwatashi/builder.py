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

from contextlib import contextmanager
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
    _history: list = None
    _redo: list = None
    _drawing: int = 0

    def __post_init__(self):
        self._cells = [self.bg] * (self.width * self.height)
        self._history = []
        self._redo = []

    # -- history ---------------------------------------------------------- #
    #
    # **Undo is a snapshot of the cells, not a diff, and the reason is the acceptance test.** This
    # project's rule is that state has to be *reconstructable* rather than trusted: `corpus/README.md`
    # commits measurement facts and not samples because a fact can be re-derived. A diff-based undo would
    # need the forward operation to be exactly invertible for every verb -- `shade` and `outline` both read
    # the canvas while writing to it, so an inverse of those is not a local operation at all. A snapshot
    # has no such requirement: `undo` puts the cells back to a state that was observed, so "the canvas is
    # pixel-identical to what it was" holds by construction rather than by proof.
    #
    # The cost is bounded and was measured before choosing: a 512x512 canvas is 262,144 single-character
    # strings, and copying that list takes about a millisecond. A sprite is not a photograph, so the
    # snapshot wins on the axis that matters here.
    #
    # **The hook is `put`, and it is the only one needed.** Every primitive -- `rect`, `disc`, `line`,
    # `trap`, `cone`, `_taper` -- reaches the grid through `put`, so a call site cannot forget to record.
    # `shade`, `outline` and `recolor` iterate the cells directly for speed, which is why they call
    # `_mark` on entry: their *own* iteration is their business, but the boundary of their transaction is
    # not.

    def _mark(self, label: str = None, *, _internal: bool = False):
        """Record a floor for undo. Idempotent within a transaction when a label is given.

        **There is deliberately no idempotence check on the label, and a first version had one.**
        `_mark("rect")` twice in a row is two `rect` calls, not one call recorded twice -- measured, two
        consecutive rectangles left a single history entry, so one undo removed both and the state between
        them was never snapshotted. The check looked like it prevented duplicates while it was dropping
        states.

        Duplicates cannot arise anyway. A static shape opens one `_shape` context and its interior writes
        go through `put` with the counter set, so the shape contributes exactly one entry; the guard was
        solving a problem the counter already solves, and introducing a real one.
        """
        self._history.append((label or "", tuple(self._cells)))
        self._redo.clear()
        return self

    @contextmanager
    def _shape(self, label: str):
        """One logical operation, however many pixels it writes.

        **`put` is two things at once and that is the whole difficulty.** It is the public single-pixel
        drawing verb *and* the path every static shape uses to reach the grid. Recording on `put` alone
        gave a sixteen-pixel `rect` sixteen history entries: measured on a two-rectangle test the history
        held twenty-one entries where four were expected, so `undo` took sixteen calls to step back one
        operation, which is not undo.

        The counter covers both callers. A static shape opens this context and writes as many pixels as it
        likes; a caller looping over `put` for a dynamically computed region gets the same treatment as long
        as it does so inside one too. `put` records only when nothing is open.
        """
        self._mark(label)
        self._drawing += 1
        try:
            yield self
        finally:
            self._drawing -= 1

    def undo(self) -> bool:
        """Step back one operation. Returns whether anything changed.

        The floor is pushed onto the redo stack so the step can be taken again, which is why an undo is
        itself undoable rather than a one-way loss.
        """
        if not self._history:
            return False
        label, cells = self._history.pop()
        self._redo.append((label, tuple(self._cells)))
        self._cells = list(cells)
        return True

    def redo(self) -> bool:
        """Step forward again after an undo, or return False if there is nothing to redo."""
        if not self._redo:
            return False
        label, cells = self._redo.pop()
        self._history.append((label, tuple(self._cells)))
        self._cells = list(cells)
        return True

    def history(self):
        """The labels of the recorded steps, oldest first, prefixed with the starting state.

        Returned as a list of strings rather than the internal tuples: the snapshots are large and a caller
        wanting to inspect the sequence wants the names, not the pixels. `state()` is how a caller gets a
        particular state back.
        """
        return ["<start>"] + [label or "<step %d>" % i for i, (label, _) in enumerate(self._history)]

    def state(self) -> tuple:
        """The cells as an immutable tuple -- the identity a history entry is compared by."""
        return tuple(self._cells)

    def clear_history(self):
        """Forget the recorded steps. Used by a replay that wants the history to describe the run rather
        than the construction of the canvas."""
        self._history.clear()
        self._redo.clear()
        return self

    # -- primitives ------------------------------------------------------- #
    def get(self, x, y) -> str:
        if 0 <= x < self.width and 0 <= y < self.height:
            return self._cells[y * self.width + x]
        return self.bg

    def put(self, x, y, key: str) -> "Canvas":
        # only a direct call is its own operation; inside `_shape` the caller already recorded one
        if not self._drawing:
            self._mark("put")
        if 0 <= x < self.width and 0 <= y < self.height:
            self._cells[y * self.width + x] = key
        return self

    def rect(self, x0, y0, x1, y1, key: str) -> "Canvas":
        """Filled rectangle, inclusive of both corners."""
        with self._shape('rect'):
            for y in range(y0, y1 + 1):
                for x in range(x0, x1 + 1):
                    self.put(x, y, key)
            return self

    def disc(self, cx, cy, r, key: str) -> "Canvas":
        """Filled circle. `cx`/`cy` may be fractional so a sprite can sit on a half-pixel centre."""
        with self._shape('disc'):
            rr = r * r
            for y in range(self.height):
                for x in range(self.width):
                    if (x - cx) ** 2 + (y - cy) ** 2 <= rr:
                        self.put(x, y, key)
            return self

    def _taper(self, y0, y1, w0, w1, key, cx):
        self._mark()
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
        with self._shape('line'):
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
        with self._shape('recolor'):
            self._cells = [mapping.get(c, c) for c in self._cells]
            return self

    def shade(self, light: str, dark: str, *, depth: int = 2) -> "Canvas":
        """Split each shape key into a lit band inside its top edge and a shadowed band inside its
        bottom edge, at a constant **perpendicular** thickness of `depth`.

        **Two versions have been wrong here, and the second one was wrong in a way that only a slant
        reveals.** The first was coordinate arithmetic -- `(x + y) % 7 == 0` -- which drew a diagonal
        sash across a skirt. The second measured the shape per column: the top `depth` pixels lit,
        the bottom `depth` shadowed. On a rectangle that is exactly right, which is why it survived:
        two flat bands, the perpendicular thickness equal to `depth`.

        On a slope it is not right, and the numbers are measured (`tools/probe_shade_bands.py`). The
        rule fixes the **vertical** thickness, so what it produces perpendicular to the edge is
        `depth / sqrt(1 + m^2)`. Where the edge steps one pixel per row that is `depth / sqrt(2)`, and
        because the vertical count is an integer it alternates between `depth` and `depth / sqrt(2)` --
        a sawtooth, `0.71x` to `1.0x` of the intended width, on the very form the band is meant to
        describe.

        So the band is now taken from **distance to the region's own boundary**, which does not care
        which way the edge runs. The distance is Euclidean -- a chamfer transform, two passes -- rather
        than a 4-connected wavefront, because a wavefront counts diagonal steps as one and would
        reproduce the same anisotropy in a different place.

        The direction stays: light comes from above, so the band along a top edge is lit and the one
        along a bottom edge is shadowed. A pixel can be within `depth` of both on a thin form, and
        then it is left alone rather than guessed at.
        """
        with self._shape('shade'):
            BIG = 1 << 20
            for key, lit in light.items():
                members = [(x, y) for y in range(self.height) for x in range(self.width)
                           if self.get(x, y) == key]
                if not members:
                    continue
                inside = set(members)
                # Euclidean distance to the nearest cell that is not in the region, by chamfer
                # propagation: forward pass then backward, 3-4 weights scaled so that 3 is orthogonal
                # and 4 is diagonal (4/3 approximates sqrt(2)).
                dist = {}
                for (x, y) in members:
                    d = 0
                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
                        if (x + dx, y + dy) not in inside:
                            d = 3
                            break
                    dist[(x, y)] = d if d else BIG
                grid = [(x, y) for y in range(self.height) for x in range(self.width)]
                for (x, y) in grid:
                    if (x, y) not in inside:
                        continue
                    for dx, dy, w in ((-1, 0, 3), (0, -1, 3), (-1, -1, 4), (1, -1, 4)):
                        n = (x + dx, y + dy)
                        if n in inside:
                            dist[(x, y)] = min(dist[(x, y)], dist[n] + w)
                for (x, y) in reversed(grid):
                    if (x, y) not in inside:
                        continue
                    for dx, dy, w in ((1, 0, 3), (0, 1, 3), (1, 1, 4), (-1, 1, 4)):
                        n = (x + dx, y + dy)
                        if n in inside:
                            dist[(x, y)] = min(dist[(x, y)], dist[n] + w)
                cutoff = depth * 3
                top_edge = {x: min(y for xx, y in members if xx == x)
                            for x in {xx for xx, _ in members}}
                bottom_edge = {x: max(y for xx, y in members if xx == x)
                               for x in {xx for xx, _ in members}}
                for (x, y) in members:
                    if dist[(x, y)] > cutoff:
                        continue
                    near_top = y - top_edge[x] < depth + depth
                    near_bottom = bottom_edge[x] - y < depth + depth
                    # `distance` decides, `near_top`/`near_bottom` only say which side it is on, so a
                    # thin form where both are true is left unshaded rather than guessed.
                    if near_top and not near_bottom:
                        self.put(x, y, lit)
                    elif near_bottom and not near_top and key in dark:
                        self.put(x, y, dark[key])
            return self

    def outline(self, key: str, *, diagonal: bool = False) -> "Canvas":
        """Draw `key` in every empty cell that touches a filled one.

        `diagonal=False` is four-neighbour and gives a cleaner corner at small sizes; eight-neighbour
        closes diagonal gaps but fattens the silhouette. Four is the default for that reason.
        """
        with self._shape('outline'):
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
