# -*- coding: utf-8 -*-
"""Does the intensity-slope sign test work on pixel art? Measured, not assumed.

The question this probe answers is not "is Vyšniauskas 2009 correct" -- it is correct for what it was
built for, natural images with interpolated edges. The question is whether it survives contact with
**hand-drawn pixel art**, where this repository has already recorded a hard-won lesson:

    `probe_aa_rule.py` (ABANDONED) -- "a per-pixel rule cannot separate an outline from a smoothing
    layer, and no fixture can rescue it." What replaced it measures the **outer edge as a whole**
    (how many colours it uses, what share the most common one holds), because a per-pixel predicate
    never looks at the edge, only at pixels.

The sign test is a per-pixel predicate. So the interesting outcome is not "it detects AA" but **what
it does to the 160 sprites that have none**, and whether it makes the same outline-versus-smoothing
mistake the abandoned rule made.

The rule, from the paper (Elektronika ir Elektrotechnika 95(7):107-110, DOI 10.5755/j02.eie.10058):
take the 3x3 neighbourhood, compare the centre's intensity with each of the eight neighbours, and
require that the differences contain **both signs** and **no more than two zeros**. The count of zeros
also separates a ramp boundary from a slope.

Two sides are measured for every sprite:

    the sprite as the artist drew it      the number must be small, or the detector is firing on outlines
    the same sprite bilinearly resampled  the number must rise, or the detector is not detecting

`tools/probe_silhouette.py` is run alongside because it is the working measurement, and the pair is
what says whether the new one adds anything.

    python tools/probe_aa_sign.py [--limit N]
"""
from __future__ import annotations

import argparse
import glob
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image

CORPUS = r"E:\DaShaoHuo\downloads\ichiwatashi-corpus"


def _i(px) -> float:
    """Rec.601 luma. The paper works on intensity, and this is what an intensity is for a byte image.

    A different luma (Rec.709, or CIELAB L*) would change which pixels trip the sign test, so the choice
    is recorded rather than left implicit -- and the probe reports the count under both so the reader can
    see whether the answer depends on it.
    """
    r, g, b = px[0], px[1], px[2]
    return 0.299 * r + 0.587 * g + 0.114 * b


def _i709(px) -> float:
    r, g, b = px[0], px[1], px[2]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def sign_test(im, luma=_i, max_zeros: int = 2):
    """Every opaque pixel whose 3x3 neighbourhood spans both signs with at most `max_zeros` flat steps.

    Transparent neighbours are skipped entirely rather than treated as a value: a background is not a
    brightness, and treating it as one would make every edge pixel an "anti-aliased" one -- which is
    precisely the outline-versus-smoothing confusion this probe exists to test for.
    """
    px = im.load()
    w, h = im.size
    marked = set()
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            c = px[x, y]
            if c[3] == 0:
                continue
            ci = luma(c)
            pos = neg = zero = 0
            touching_clear = False
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    n = px[x + dx, y + dy]
                    if n[3] == 0:
                        touching_clear = True
                        continue
                    d = luma(n) - ci
                    if d > 0:
                        pos += 1
                    elif d < 0:
                        neg += 1
                    else:
                        zero += 1
            # the paper's condition
            if pos and neg and zero <= max_zeros:
                marked.add((x, y))
    return marked


def silhouette_colours(im):
    """The measurement that replaced the abandoned rule: colours on the outermost opaque pixels."""
    px = im.load()
    w, h = im.size
    band = Counter()
    for y in range(h):
        for x in range(w):
            if px[x, y][3] == 0:
                continue
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if not (0 <= nx < w and 0 <= ny < h) or px[nx, ny][3] == 0:
                    band[px[x, y]] += 1
                    break
    if not band:
        return 0, 0.0, 0
    top = band.most_common(1)[0][1]
    return len(band), top / sum(band.values()), sum(band.values())


def anti_aliased(im):
    """A bilinear resample of the sprite, which is what smoothing an edge actually does."""
    return im.resize((im.width, im.height), Image.BILINEAR) if False else im.resize(
        (im.width * 2, im.height * 2), Image.BILINEAR).resize(
        (im.width, im.height), Image.BILINEAR)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=40)
    a = ap.parse_args()

    files = sorted(glob.glob(CORPUS + r"\**\*.png", recursive=True))[: a.limit]
    if not files:
        print("no corpus samples found at %s" % CORPUS)
        return 1

    rows = []
    for f in files:
        im = Image.open(f).convert("RGBA")
        clear = im.getbbox()
        if clear:
            im = im.crop(clear)
        orig = sign_test(im)
        aa = sign_test(anti_aliased(im))
        orig709 = sign_test(im, luma=_i709)
        ncol, share, nedge = silhouette_colours(im)
        opaque = sum(1 for p in im.getdata() if p[3] > 0)
        rows.append((Path(f).name, opaque, len(orig), len(orig709), len(aa), ncol, share, nedge))

    print("%-26s %7s %7s %7s %7s %6s %7s" %
          ("sprite", "opaque", "sign", "sign709", "onAA", "silN", "silShare"))
    for name, opaque, s1, s2, aa, ncol, share, _ in rows[:18]:
        print("%-26s %7d %7d %7d %7d %6d %6.2f%%" %
              (name[:26], opaque, s1, s2, aa, ncol, 100 * share))
    print()

    def rate(idx, denom=1):
        return [r[idx] / max(1, r[denom]) for r in rows]

    sr = rate(2, 1)
    ar = rate(4, 1)
    print("  the sign test on the sprite AS DRAWN")
    print("      median %.4f   mean %.4f   max %.4f" % (statistics.median(sr), statistics.mean(sr), max(sr)))
    print("  the sign test on the SAME sprite bilinearly resampled")
    print("      median %.4f   mean %.4f   max %.4f" % (statistics.median(ar), statistics.mean(ar), max(ar)))
    print("  ratio of medians (should be well above 1 if it detects smoothing): %.2f"
          % (statistics.median(ar) / max(1e-9, statistics.median(sr))))
    print()

    # **The decisive comparison.** The abandoned rule failed because every outline pixel is "outermost
    # and differs from what it wraps". The sign test is a different predicate, so the question is
    # whether it also fires on a conventional flat outline that has no smoothing at all.
    multi = [r for r in rows if r[5] > 1]
    single = [r for r in rows if r[5] == 1]
    print("  split by what the OUTER EDGE looks like (the working measurement)")
    for label, group in (("one edge colour (flat outline, no AA)", single),
                         ("several edge colours (candidate AA / blemish)", multi)):
        if not group:
            print("      %-46s (none)" % label)
            continue
        print("      %-46s n=%2d   sign-test median %.4f"
              % (label, len(group), statistics.median([g[2] / max(1, g[1]) for g in group])))
    print()
    print("  the two lumas disagree on how many pixels: median difference %.4f of opaque"
          % statistics.median([abs(r[2] - r[3]) / max(1, r[1]) for r in rows]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
