"""The silhouette-colour measurement: what replaces "isolated pixels" as the AA question.

Why the old framing could not work. `isolated_rate` counts a pixel whose opaque neighbours are all a
different colour, and that description covers two unrelated populations. Measured over 40 real TH155
sprites: **14930 of those pixels sit inside the drawing and 3409 on its silhouette.** The interior
ones are single-pixel highlights and cloth texture -- `README.md` already records that they *are* the
detail. So 81% of the signal was never about edges at all.

What the silhouette itself says. The outermost opaque pixels are where a smoothing layer would live,
and their colour count is a direct question with a direct answer:

    one colour, covering everything   nothing was placed between the body and the background
    several colours, in a thin band   something was

Measured here over the same 40 sprites, the median is **1 colour at 100% share**, and 9 of 40 have
more. TH155 draws a flat outline and no anti-aliasing, which is what a 2017 sprite in this style
does; the 9 are the ones worth looking at individually.

The limitation is measured rather than asserted: a stray pixel ON the silhouette is a second colour
in that band, exactly like one AA pixel, so the count cannot by itself say which it is. What it can
say is that the edge is uniform or not -- and "uniform" is the strong claim, because a per-pixel
condition cannot produce a uniform edge by accident.
"""
from __future__ import annotations

import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ichiwatashi.judge import _opaque  # noqa: E402
from PIL import Image  # noqa: E402

SPRITES = Path(r"E:\DaShaoHuo\downloads\ichiwatashi-corpus\th155")
BODY = (90, 130, 200, 255)
LINE = (20, 20, 40, 255)
MID = (55, 75, 120, 255)
SPECK = (250, 240, 90, 255)


def silhouette(im):
    """(outline pixels, distinct colours among them, share of the most common one)."""
    px = im.load()
    w, h = im.size
    cols = Counter()
    n = 0
    for x, y in _opaque(im):
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if not (0 <= nx < w and 0 <= ny < h) or px[nx, ny][3] == 0:
                cols[px[x, y][:3]] += 1
                n += 1
                break
    if not n:
        return 0, 0, 0.0
    return n, len(cols), cols.most_common(1)[0][1] / n


def block(ring=True, aa_corners=False, specks=False, stray=False, band=False):
    im = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    px = im.load()
    for y in range(8, 24):
        for x in range(8, 24):
            px[x, y] = BODY
    if ring:
        for y in range(8, 24):
            for x in range(8, 24):
                if x in (8, 23) or y in (8, 23):
                    px[x, y] = LINE
    if aa_corners:
        for cx, cy in ((9, 9), (22, 9), (9, 22), (22, 22)):
            px[cx, cy] = MID
    if specks:
        for y in range(12, 20):
            for x in range(12, 20):
                if (x * 3 + y * 5) % 4 == 0:
                    px[x, y] = SPECK
    if band:
        # a mid-tone replacing part of the outline itself: this is what a smoothing layer looks
        # like from the outside, and it is the case the measurement must react to
        for y in range(8, 16):
            px[23, y] = MID
    if stray:
        px[8, 16] = (255, 0, 255, 255)
    return im


print("=== synthetic cases, answer known by construction ===")
print("%-36s %9s %10s %12s" % ("case", "outline", "colours", "top share"))
for label, im in (
    ("solid block, no outline", block(ring=False)),
    ("flat 1px outline (no AA)", block()),
    ("same + 4 interior pixels (NOT AA)", block(aa_corners=True)),
    ("same + interior speckles", block(specks=True)),
    ("same + interior pixels + speckles", block(aa_corners=True, specks=True)),
    ("same + a mid-tone band ON the edge", block(band=True)),
    ("same + 1 stray pixel ON the edge", block(stray=True)),
):
    n, c, share = silhouette(im)
    print("%-36s %9d %10d %12.3f" % (label, n, c, share))

print()
print("=== the same measurement over 40 real TH155 sprites ===")
rows = []
for p in sorted(SPRITES.glob("*.png"))[:40]:
    with Image.open(p) as im:
        rows.append((p.name,) + silhouette(im.convert("RGBA")))
print("median outline pixels: %.0f   median colours: %.0f   median top share: %.3f"
      % (statistics.median(r[1] for r in rows),
         statistics.median(r[2] for r in rows),
         statistics.median(r[3] for r in rows)))
multi = [r for r in rows if r[2] > 1]
print("sprites whose outline uses more than one colour: %d / %d" % (len(multi), len(rows)))
for r in multi[:6]:
    print("   %-22s %4d px, %2d colours, top %.3f" % r)

print()
print("Reading:")
print("  * interior speckles do not move the measurement at all -- that separation is the whole")
print("    point, and it is what `isolated_rate` could not do because it pooled both populations")
print("  * AA pixels and a stray edge pixel both add a colour, so this says 'the edge is not")
print("    uniform', not 'the edge was smoothed'. Recorded as the limit of the measurement.")
print("  * 'top share is 1.000' is the strong direction: a per-pixel condition cannot produce a")
print("    uniform edge by accident, so a uniform outline is real evidence and a non-uniform one")
print("    is a thing to look at rather than a verdict.")
