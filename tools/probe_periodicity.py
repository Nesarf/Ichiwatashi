#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Probe the periodicity classifier and the grid phase against drawings whose answer is known.

**Why this is synthetic and why that is not circular.** The corpus is 160 real hand-authored sprites
and all 160 read `upscale=0`, `periodic_class=none` -- which is the right answer for hand drawing, but
it exercises none of the branches. A classifier whose branch is never entered is not verified, and
`POLICY.md` gate 3 already says synthetic samples may be used to *verify* a metric as long as they
never enter the reference table. That is exactly the role they play here.

Each case is a drawing built to hit one branch, and the expected class is stated before the run.

    python tools/probe_periodicity.py
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image

J = importlib.import_module("ichiwatashi.judge")


def draw(w, h, blocks):
    """blocks: (x, y, x2, y2, colour) in *source* pixels, then scaled by the caller."""
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px = im.load()
    for x0, y0, x1, y1, c in blocks:
        for y in range(y0, y1):
            for x in range(x0, x1):
                px[x, y] = c
    return im


def upscale(im, n):
    return im.resize((im.width * n, im.height * n), Image.NEAREST)


def hand_drawn_like(n=64, colours=4):
    """Many runs of many different lengths, which is what hand-authored art measures as."""
    cols = [(200, 60, 60, 255), (60, 120, 200, 255), (240, 220, 90, 255), (30, 30, 40, 255)]
    im = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    px = im.load()
    for y in range(4, n - 4):
        for x in range(4, n - 4):
            # a pattern with irregular run lengths: different widths per row
            px[x, y] = cols[(x // 3 + y // 5) % colours] if (x * 7 + y * 5) % 9 else cols[(y) % colours]
    return im


CASES = []


def case(name, im, expect_class, expect_factor=None, expect_candidates=None, expect_phase=None):
    CASES.append((name, im, expect_class, expect_factor, expect_candidates, expect_phase))


# **The feature widths decide whether the factor is identifiable at all**, so both kinds are built on
# purpose. This is the finding the first version of this probe produced by accident: with even-width
# features the run lengths are 2s, 3s and 4s times the scale, so 2, 4 and 8 all explain them and no
# single factor is the right answer. With mixed widths the GCD of the runs is the scale itself.

# 1. features of mixed width (1, 3, 5 source pixels), so the scale is unambiguous
mixed = draw(32, 32, [(4, 4, 5, 12, (200, 60, 60, 255)),
                      (7, 6, 10, 16, (60, 120, 200, 255)),
                      (5, 14, 10, 20, (240, 220, 90, 255))])
case("mixed-width features x4", upscale(mixed, 4), "upscale", 4, None, 0)
case("mixed-width features x3", upscale(mixed, 3), "upscale", 3, None, 0)

# 2. the same drawing with even-width features only, which is genuinely ambiguous
even = draw(24, 24, [(4, 4, 10, 12, (200, 60, 60, 255)),
                     (12, 6, 18, 16, (60, 120, 200, 255)),
                     (6, 14, 14, 20, (240, 220, 90, 255))])
case("even-width features x4 (ambiguous)", upscale(even, 4), "upscale", None, (2, 4, 8), None)

# 3. the same upscale, cropped so the grid no longer starts at the origin
big = upscale(mixed, 4)
case("x4 upscale cropped by 2", big.crop((2, 0, big.width, big.height)), "upscale", None, None, 2)

# 4. one colour with runs of differing lengths: the branch 59 of 300 real sprites hit.
mask = Image.new("RGBA", (48, 48), (0, 0, 0, 0))
px = mask.load()
for y in range(48):
    half = (y * 40 // 48) // 2                       # a varying width, so runs differ
    for x in range(24 - half, 24 + half):
        px[x, y] = (255, 255, 255, 255)
case("single-colour mask (varying runs)", mask, "mask")

# 5. every run the same length: a solid block, which also satisfied "multiple of n" before
case("solid block (constant runs)", draw(40, 40, [(5, 5, 35, 35, (10, 200, 10, 255))]), "constant")

# 6. hand-authored-like art, which must NOT be called periodic
case("hand-drawn-like art", hand_drawn_like(), "none", 0, (), None)

# 7. a clean upscale with one touched-up pixel -- the documented degradation path
touched = upscale(mixed, 4)
touched.putpixel((touched.width // 2 + 1, touched.height // 2), (255, 0, 255, 255))
case("x4 upscale with one bad pixel", touched, "upscale", None, None, None)

# 8. the structure the literature warns about: a regular grid that is NOT resampling. This case exists
#    so the tool's wording stays honest -- it names the structure it measured and does not claim to
#    know the image's provenance. Two colours, because a one-colour version of this is a mask (and the
#    probe caught that too: the first version of this case was one colour and read `mask`, correctly).
grid8 = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
px = grid8.load()
for y in range(64):
    for x in range(64):
        px[x, y] = (90, 90, 90, 255) if (x % 8 < 4) != (y % 8 < 4) else (200, 60, 60, 255)
case("8-pixel regular grid", grid8, "upscale", None, None, None)


def main() -> int:
    bad = 0
    print("%-36s %-9s %-9s %-7s %-6s %-7s %s"
          % ("case", "class", "expected", "factor", "phase", "agree", "candidates"))
    for name, im, ecls, efac, ecand, ephase in CASES:
        r = J.judge(im)
        why = []
        if r.periodic_class != ecls:
            why.append("class")
        if efac is not None and r.upscale != efac:
            why.append("factor")
        if ecand is not None and tuple(r.upscale_candidates) != tuple(ecand):
            why.append("candidates")
        if ephase is not None and r.phase != ephase:
            why.append("phase")
        if why:
            bad += 1
        print("%-36s %-9s %-9s %-7s %-6s %-7.2f %-16s %s"
              % (name, r.periodic_class, ecls, r.upscale, r.phase, r.phase_agree,
                 str(tuple(r.upscale_candidates)), "ok" if not why else "MISMATCH: " + ",".join(why)))
    print()
    print("%d of %d cases match" % (len(CASES) - bad, len(CASES)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
