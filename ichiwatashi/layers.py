# -*- coding: utf-8 -*-
"""The same canvas, drawn in passes.

**What a layer is here, and what it is not.** It is an ordered stack of grids that a drawing is split
across: a draft and its ink, or a body and the parts placed on it. It is not transparency, blending or
opacity -- a pixel sprite lands on one colour, and a stack that could fade would be exporting something
the format cannot carry. `flatten` composes the passes in order and the result is what gets written.

**Why the wrapper rather than a per-cell layer index.** The alternative was an extra column in the grid
every verb writes through, and every verb in `builder` -- `rect`, `disc`, `outline`, `blit`, the history
snapshots -- would have had to learn about it. A wrapper that forwards the drawing verbs to one of several
plain canvases keeps `builder` single-layer, which is what makes the two testable apart from each other.

**Undo is per layer, and the current layer is explicit.** Each pass keeps its own history, and a script
names the layer it is drawing on; an `undo` with no layer named steps back the layer that was current. The
alternative -- one history across the stack -- would have to record which pass each snapshot came from,
and would make "step back one operation" depend on a stack the caller cannot see.
"""
from __future__ import annotations

from . import builder as B

__all__ = ["Layers"]

#: The drawing verbs a layer owns. Everything in this list is forwarded to the current layer; everything
#: else (`to_image`, `to_grid`, `preview`, `flatten`, `history`) composes or reports the stack, because
#: those are what a reader looks at and a reader looks at the whole drawing. `history` is in the second
#: group on purpose: one layer's history answers "what did I do last" for that pass only.
FORWARDED = (
    "get", "put", "rect", "disc", "trap", "cone", "line", "recolor", "shade", "outline", "mirror", "blit",
    "crop", "stamp", "flip", "undo", "redo", "clear_history", "rows",
)


class Layers:
    """An ordered stack of `builder.Canvas`, bottom first, with one of them current."""

    def __init__(self, width, height, names=None, bg="."):
        names = list(names) if names else ["base"]
        if not names:
            raise ValueError("a drawing needs at least one layer")
        if len(set(names)) != len(names):
            duplicate = next(n for n in names if names.count(n) > 1)
            raise ValueError("duplicate layer %r" % duplicate)
        if any(not isinstance(n, str) or not n for n in names):
            raise ValueError("layer names must be non-empty strings")
        self.width = width
        self.height = height
        self.bg = bg
        self.names = names
        self.current = names[0]
        self._layers = {n: B.Canvas(width, height, bg) for n in names}

    # -- addressing ------------------------------------------------------- #
    def layer(self, name):
        """One layer by name, refused by name if it does not exist."""
        try:
            return self._layers[name]
        except KeyError:
            raise ValueError("unknown layer %r; known: %s"
                             % (name, ", ".join(self.names))) from None

    def use(self, name):
        """Make `name` the layer the drawing verbs write to. Refused by name if it does not exist."""
        self.layer(name)
        self.current = name
        return self

    def current_canvas(self):
        return self._layers[self.current]

    # -- composing -------------------------------------------------------- #
    def flatten(self, *, hide=()):
        """The stack as one canvas, bottom first. `hide` omits passes by name.

        Hidden layers are omitted from the *rendering*, not deleted: a draft pass is exactly the layer a
        caller wants to keep in the file and out of the picture.
        """
        hidden = set(hide)
        unknown = hidden - set(self.names)
        if unknown:
            raise ValueError("unknown layer(s) to hide: %s" % ", ".join(sorted(unknown)))
        out = B.Canvas(self.width, self.height, self.bg)
        for name in self.names:
            if name in hidden:
                continue
            # `blit` copies non-background pixels only, which is the composition rule this whole family
            # already uses: a pass that drew nothing must not blank the pass underneath it.
            out.blit(self._layers[name], 0, 0)
        return out

    def state(self):
        """Every layer's state, so a test can compare the whole stack rather than the visible one."""
        return tuple(self._layers[n].state() for n in self.names)

    def history(self):
        return tuple((n, self._layers[n].history()) for n in self.names)

    # -- everything a reader looks at composes first ----------------------- #
    def to_image(self, palette):
        return self.flatten().to_image(palette)

    def to_grid(self, palette):
        return self.flatten().to_grid(palette)

    def preview(self, scale=8, palette=None, bg=(255, 255, 255)):
        return self.flatten().preview(scale=scale, palette=palette, bg=bg)

    # -- and the drawing verbs go to the current layer --------------------- #
    def __getattr__(self, name):
        if name in FORWARDED:
            return getattr(self.current_canvas(), name)
        raise AttributeError(name)
