# -*- coding: utf-8 -*-
"""What is the sign test firing on in drawings that were never smoothed? Measured, in isolation.

`probe_aa_sign.py` established two things on real sprites: the sign test's rate rises 8.6x when a sprite
is bilinearly resampled (so it detects smoothing), and the rate is the same whether the outer edge uses
one colour or several (so it does **not** make the outline-versus-smoothing mistake that killed
`probe_aa_rule.py`).

That leaves the number it reports on untouched art -- a median of 8.1% of opaque pixels -- which should
not exist if a hand-drawn pixel-art region is a flat field. This probe separates the candidates:

    a 1-step stair            a genuine one-unit slope, which IS what AA looks like at its faintest
    a flat field with +-1      quantisation residue: neighbouring pixels differ by rounding, not by intent
    a flat field with +-8      visible banding, still not a slope
    a real gradient            many steps over many pixels

If the sign test fires on the +-1 field as hard as on the stair, then on this corpus it is partly a
quantisation-residue detector, and the rate it reports on real art cannot be read as "8% anti-aliased".
That distinction is worth having before the number goes into a report.

    python tools/probe_aa_sign_isolate.py
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from PIL import Image

from probe_aa_sign import sign_test


def field(w=64, h=64, background=(40, 60, 80, 255), jitter=0, seed=7):
    """A flat drawing with a flat interior, optionally carrying +-jitter of rounding residue."""
    rnd = random.Random(seed)
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px = im.load()
    for y in range(h):
        for x in range(w):
            if 8 <= x < w - 8 and 8 <= y < h - 8:
                d = rnd.randint(-jitter, jitter) if jitter else 0
                px[x, y] = (background[0] + d, background[1] + d, background[2] + d, 255)
    return im


def stair(w=64, h=64, step=1, period=8, base=40):
    """Flat bands one unit apart: the faintest thing a smoothing pass can leave behind."""
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px = im.load()
    for y in range(h):
        for x in range(w):
            if 8 <= x < w - 8 and 8 <= y < h - 8:
                d = ((x - 8) // period) * step
                px[x, y] = (base + d, base + d, base + d, 255)
    return im


def gradient(w=64, h=64):
    """A real ramp: many steps across the field."""
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px = im.load()
    for y in range(h):
        for x in range(w):
            if 8 <= x < w - 8 and 8 <= y < h - 8:
                d = (x - 8) * 2
                px[x, y] = (40 + d, 40 + d, 40 + d, 255)
    return im


def report(name, im):
    marked = sign_test(im)
    opaque = sum(1 for p in im.getdata() if p[3] > 0)
    print("  %-34s marked %5d of %5d opaque   %6.2f%%"
          % (name, len(marked), opaque, 100.0 * len(marked) / max(1, opaque)))
    return len(marked) / max(1, opaque)


def main() -> int:
    print("=== isolated fields, same geometry, only the interior differs ===")
    flat = report("flat interior (one colour)", field(jitter=0))
    r1 = report("flat interior, +-1 residue", field(jitter=1))
    r2 = report("flat interior, +-2 residue", field(jitter=2))
    r8 = report("flat interior, +-8 banding", field(jitter=8))
    print()
    s1 = report("1-unit stair (period 8)", stair(step=1, period=8))
    s2 = report("2-unit stair (period 8)", stair(step=2, period=8))
    print()
    g = report("real gradient (2 per pixel)", gradient())
    print()
    print("=== the reading that matters ===")
    print("  the stair and the residue have the same size, so compare them directly:")
    print("      +-1 residue / flat        %8.3f   <- firing with no slope present?"
          % (r1 / max(1e-9, flat)))
    print("      1-unit stair / flat       %8.3f" % (s1 / max(1e-9, flat)))
    print("      stair / residue           %8.3f   <- if near 1.0, it cannot tell a slope from rounding"
          % (s1 / max(1e-9, r1)))
    print()
    print("  and how a bigger residue compares, for scale:")
    print("      +-8 banding               %8.3f of opaque" % r8)
    print("      real gradient             %8.3f of opaque" % g)
    return 0


if __name__ == "__main__":
    sys.exit(main())
