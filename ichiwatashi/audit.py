# -*- coding: utf-8 -*-
"""Things worth saying while a drawing is being built, rather than after it is measured.

**Why this is not a score.** `judge` answers "is this value outside the reference band" for art that was
already made; that is a measurement of an outcome. What a construction script can say about itself is
different in kind: which palette entries it declares and never uses, whether it shaded a form without
outlining it, whether a declared pass stayed empty. Those are **inconsistencies between what the script
says and what it draws**, and they can be checked without a reference corpus at all.

**So nothing here compares a sprite with real art.** A construction script of three colours is not wrong
for being three colours -- it is a different kind of drawing from a 26-colour fighting-game frame, and
telling it so on every build would make the whole report ignorable. Each hint below is either a
contradiction inside the script or a convention whose absence has a named cost.
"""
from __future__ import annotations

__all__ = ["hints", "PALETTE_SOFT_CAP"]

#: Above this many entries the palette stops being a palette and starts being a texture. The reference
#: corpus sits at 16-37 with a median of 26, so this is a note rather than a refusal -- and it only fires
#: where a script names that many entries itself.
PALETTE_SOFT_CAP = 32


def _used_keys(plan):
    """Every palette key the plan itself reaches, so "unused" can be checked."""
    used = set()
    for kind, step in plan:
        if kind in ("rect", "line", "disc", "trap", "cone", "outline"):
            used.add(step.get("key"))
        elif kind == "shade":
            # Both sides of each mapping are used: the source key is what gets shaded, and the target key is
            # the band's own colour. Counting only the sources reported every band colour as unused.
            used.update(step.get("light", {}))
            used.update(step.get("light", {}).values())
            used.update(step.get("dark", {}).values())
        # `mirror`, `flip`, `copy`, `mask`, `unmask`, `undo`, `redo`, `part` reach no key of their own:
        # a part's keys belong to its own file and a region verb moves what is already placed.
    used.discard(None)
    return used


def hints(spec, plan):
    """Inconsistencies between what the script declares and what it draws. Ordered, deduplicated."""
    out = []
    palette = spec.get("palette") or {}
    keys = set(palette)
    used = _used_keys(plan)
    kinds = [kind for kind, _step in plan]

    # 1. A palette entry nothing draws with. Cheap to say, and it usually means a shape was deleted while
    #    its colour stayed -- the next person then wonders which entry is live.
    #
    #    **The background is not one of them.** It is a key the canvas fills itself with and no step ever
    #    names, so counting it reported every script as having an unused entry -- a hint that is always on
    #    is a hint nobody reads.
    #
    #    **And a script that places parts cannot answer this at all.** A part draws with the host's keys
    #    from its own file, so a drawing made only of parts has no key of its own to count -- reported on
    #    first release as three unused entries in a script that used all three through a part. A check that
    #    cannot see the usage must not report the absence.
    bg = spec.get("bg", ".")
    has_parts = any(kind == "part" for kind, _step in plan)
    if not has_parts:
        unused = sorted(k for k in keys if k not in used and k != bg)
        if unused:
            out.append("palette entries no step uses: %s" % ", ".join(repr(k) for k in unused))

    # 2. Shaded but not outlined. The cost is stated rather than implied: at small sizes an unoutlined
    #    silhouette dissolves into whatever it sits on, which is why `outline` exists at all.
    shaded = "shade" in kinds
    outlined = "outline" in kinds
    if shaded and not outlined:
        out.append("this drawing is shaded and not outlined; at small sizes the silhouette has no edge of "
                   "its own, so it dissolves into whatever it sits on")

    # 3. An outline drawn in the same key as a shading band -- two jobs, one colour, and the shape loses
    #    its edge exactly where the light falls.
    if outlined:
        outline_keys = {step.get("key") for kind, step in plan if kind == "outline"}
        shade_keys = set()
        for kind, step in plan:
            if kind == "shade":
                shade_keys.update(step.get("light", {}))
                shade_keys.update(step.get("dark", {}).values())
        shared = sorted(k for k in outline_keys & shade_keys if k)
        if shared:
            out.append("the outline and a shading band share %s; the form loses its edge where the light "
                       "falls" % ", ".join(repr(k) for k in shared))

    # 4. A declared pass that never received a step. Layers are declared before they are named, so this is
    #    how a rename goes wrong: the old name stays behind as an empty pass and nobody notices.
    names = spec.get("layers")
    if isinstance(names, list) and names:
        touched = {step.get("layer") for kind, step in plan if step.get("layer")}
        for name in names:
            if name not in touched:
                out.append("layer %r is declared and no step draws on it" % name)

    # 5. A canvas that is not a whole number of units. The grid a person places on then disagrees with the
    #    canvas edge, so the last row or column cannot be snapped to.
    unit = spec.get("unit", 1)
    if isinstance(unit, int) and unit > 1:
        for label, size in (("width", spec.get("width")), ("height", spec.get("height"))):
            if isinstance(size, int) and size % unit:
                out.append("%s is %d, which is not a multiple of the unit %d; the edge cannot be snapped to"
                           % (label, size, unit))

    # 6. A palette large enough to stop being one. Stated with the reference median so the reader can
    #    disagree with the number instead of with the tool.
    if len(keys) > PALETTE_SOFT_CAP:
        out.append("the palette declares %d entries; the reference corpus sits at 16-37 with a median of "
                   "26, so this is a texture rather than a palette unless it is deliberate" % len(keys))

    return out
