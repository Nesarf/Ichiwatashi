#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""Does `aligned_shift` see what `drift` cannot? Measured against animations whose answer is known.

The TODO entry claims `drift` reads 0 when a shape moves inside while its silhouette stays put. That claim
is worth checking rather than repeating, and so is its replacement -- so this probe builds three
animations that differ only in what moves, and prints both measures.

    a whole-shape translation     both measures should see it
    an interior-only movement      `drift` should read 0 and `aligned_shift` should not
    a rotation                     `aligned_shift` should report a high residual, i.e. refuse to call it
                                   a translation

    python tools/probe_drift_measures.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import importlib

F = importlib.import_module("ichiwatashi.frames")
from PIL import Image

INK = (30, 30, 40, 255)
BODY = (220, 140, 170, 255)
ACCENT = (90, 60, 150, 255)
N = 6


def _base(interior_dx=0, whole_dx=0, rotate=False):
    """A 40x28 sprite: a fixed silhouette, and an interior mark that may move inside it."""
    im = Image.new("RGBA", (40, 28), (0, 0, 0, 0))
    px = im.load()
    x0, x1 = 8 + whole_dx, 31 + whole_dx
    y0, y1 = 6, 22
    for y in range(y0, y1):
        for x in range(x0, x1):
            px[x, y] = INK
    for y in range(y0 + 2, y1 - 2):
        for x in range(x0 + 2, x1 - 2):
            px[x, y] = BODY
    # the interior mark: a small block that can slide inside the silhouette without touching its edge
    mx = 14 + whole_dx + interior_dx
    if rotate:
        mx = 14 + whole_dx
    for y in range(12, 16):
        for x in range(mx, mx + 4):
            px[x, y] = ACCENT
    if rotate:
        # a diagonal mark instead: the same pixel count, a different orientation
        for i in range(6):
            px[14 + whole_dx + i, 12 + i] = ACCENT
    return im


def build(kind):
    tl = F.Timeline(width=44, height=30)
    for i in range(N):
        if kind == "translation":
            im = _base(whole_dx=i)
        elif kind == "interior":
            im = _base(interior_dx=i)
        else:
            im = _base(rotate=(i % 2 == 0))
        tl.add(im, pivot=(20, 26), duration_ms=100)
    return tl


def main() -> int:
    print("%-13s %-10s %-20s %-9s %-11s %s"
          % ("case", "drift", "per-pair shifts", "spread", "hit edge", "residual"))
    for kind, why in (("translation", "the whole shape moves"),
                      ("interior", "only the inside moves"),
                      ("rotate", "a mark changes orientation, not position")):
        tl = build(kind)
        dx, dy = tl.drift()
        adx, ady, per, scores, bounds, exact = tl.aligned_shift(reach=6)
        wdx, wdy, _wper, _ws, _wb, exact = tl.aligned_shift(reach=6, changed_only=False)
        print("%-13s %-10s %-20s %-9s %-11s %s"
              % (kind, "(%d,%d)" % (dx, dy), str(per[:3]), "(%d,%d)" % (adx, ady),
                 "Y" if any(bounds) else "n", max(scores) if scores else "-"))
        print("               %s" % why)
    print()
    print("  reading, in the order the columns appear:")
    print("    drift          a bounding-box measure: 0 for the interior case, because the silhouette is")
    print("                   fixed. That is the gap this measure exists to fill.")
    print("    per-pair       the offset each frame needs to sit on the previous one -- the useful reading.")
    print("                   Translation and interior motion both show a steady one pixel per frame, which")
    print("                   is exactly right: in both cases something moved one pixel.")
    print("    spread         max minus min of those. **0 for both moving cases**, and that is not a")
    print("                   failure: a whole animation translating one pixel per frame has no stutter. The")
    print("                   spread answers 'did the motion jump', not 'did it move'.")
    print("    hit edge       the column that carries the refusal. A rotation is not a translation, so the")
    print("                   fit runs to the edge of the search window and this says so instead of reporting")
    print("                   the window as an answer.")
    print("    residual       in changed-only mode this is 0 by construction -- it counts disagreement only")
    print("                   among pixels that already differ, and a perfect translation of that set leaves")
    print("                   none. It discriminates in whole-frame mode; do not read it here.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
