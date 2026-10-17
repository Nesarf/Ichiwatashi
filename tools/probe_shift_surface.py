#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Does a wrong fit look different from a right one, in the residual surface itself?

`aligned_shift` decides "is this fit trustworthy" by whether the best offset landed on the edge of the search
window. Measured on a rotation fixture at three window sizes: at `reach=3` it hits the edge five times, at
`reach=6` and `9` it settles on `(-4, -4)` and flags nothing. So the edge flag catches a search that ran out
of room and cannot catch a fit that settled on a wrong answer.

**The obvious next idea is also an edge test** -- "is the offset close to the edge" -- and that is a threshold
on a symptom. The question underneath is whether the search found a *valley* or a *slope*: a genuine
translation makes one offset markedly better than its neighbours, while a rotation fits many offsets about
equally and the argmin is whichever tie the loop reached first.

So this measures the surface rather than the argmin:

    best         the lowest disagreement found
    median       the median disagreement over the whole window
    contrast     median / best -- how much worse a typical offset is than the best one
    basin        how many offsets score within 5% of the best

A real translation should give a high contrast and a small basin. If a rotation gives contrast near 1 and a
basin covering much of the window, then **contrast is the signal to report**, and the edge flag becomes a
secondary note.

    python tools/probe_shift_surface.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import importlib

F = importlib.import_module("ichiwatashi.frames")
from PIL import Image

W = H = 40


def sprite(i=0, mark_dx=0):
    """An asymmetric body with a mark that can move; asymmetry matters for the rotation case."""
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    px = im.load()
    for y in range(8, 34):
        for x in range(8, 30):
            px[x, y] = (200, 60, 60, 255)
    # an asymmetric notch so a rotation is distinguishable from a translation
    for y in range(8, 16):
        for x in range(28, 30):
            px[x, y] = (0, 0, 0, 0)
    for y in range(16, 20):
        for x in range(12 + mark_dx, 18 + mark_dx):
            px[x, y] = (90, 60, 150, 255)
    return im


def rotate90(im):
    return im.rotate(90)


def surface(a, b, reach):
    """The whole disagreement surface, over the changed pixels only -- the same rule aligned_shift uses."""
    pa, pb = a.load(), b.load()
    seta = {(x, y) for y in range(H) for x in range(W) if pa[x, y] != pb[x, y]}
    if not seta:
        return None
    vals = []
    for dy in range(-reach, reach + 1):
        for dx in range(-reach, reach + 1):
            diff = 0
            for (x, y) in seta:
                nx, ny = x + dx, y + dy
                ca = pa[x, y]
                cb = pb[nx, ny] if (0 <= nx < W and 0 <= ny < H) else (0, 0, 0, 0)
                if ca != cb:
                    diff += 1
            vals.append((diff, dx, dy))
    return sorted(vals)


def describe(name, a, b, reach):
    s = surface(a, b, reach)
    if s is None:
        print("  %-26s (identical frames)" % name)
        return
    best = s[0]
    n = len(s)
    med = s[n // 2][0]
    basin = sum(1 for v in s if v[0] <= best[0] * 1.05)
    contrast = (med / best[0]) if best[0] else float("inf")
    near = [v for v in s if v[0] <= best[0] * 1.05][:4]
    print("  %-26s reach=%-2d best=%-5d %-11s median=%-5d contrast=%5.2f basin=%d/%d %s"
          % (name, reach, best[0], "(%d,%d)" % (best[1], best[2]), med, contrast, basin, n,
             "" if contrast > 2 else "  <-- flat"))


def main() -> int:
    base = sprite()
    print("=== a genuine one-pixel translation ===")
    for reach in (3, 4, 6, 9):
        describe("translate +1,+0", base, sprite(mark_dx=1), reach)

    print()
    print("=== a real four-pixel translation ===")
    for reach in (4, 6):
        shifted = sprite()
        px = shifted.load()
        moved = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        m = moved.load()
        for y in range(H):
            for x in range(W):
                if px[x, y][3]:
                    m[x + 4, y] = px[x, y]
        describe("translate +4,+0", base, moved, reach)

    print()
    print("=== a rotation, which is not a translation ===")
    for reach in (3, 4, 6, 9):
        describe("rotate 90", base, rotate90(base), reach)

    print()
    print("  reading: contrast is median/best over the search window. A translation should show a deep")
    print("  valley (high contrast, small basin); a rotation should show a flat surface (contrast near 1,")
    print("  basin covering much of the window). If that holds, contrast is the signal worth reporting and")
    print("  the boundary flag becomes secondary.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
