"""Does a silhouette-only rule respond to anti-aliasing and ignore interior detail?

`isolated_rate` pools two populations that have nothing to do with each other: measured over 40 real
TH155 sprites, 14930 isolated pixels sit *inside* the drawing and 3409 on its silhouette. The
interior ones are single-pixel highlights and cloth texture -- the detail. The silhouette ones are
where a mid-tone can only be smoothing a staircase or being stray noise.

The first version of this probe scored 15 on a hard staircase, which should be 0, so the fixture was
wrong rather than the rule. These fixtures are built so the answer is known *by construction*:

    a solid block                     every silhouette pixel matches what it wraps  -> 0
    an inset 1px ring on a block      the ring differs from what it wraps everywhere -> all of it
    a ring + AA on the corners        the corner pixels differ, the straight ones do not
    a block + interior single pixels  no silhouette pixel differs                   -> 0

and the honest limitation is measured too: a stray pixel ON the silhouette is indistinguishable from
AA by a count, because both are an outermost pixel that differs from what it wraps.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ichiwatashi.judge import _opaque  # noqa: E402
from PIL import Image  # noqa: E402

BODY = (90, 130, 200, 255)
LINE = (20, 20, 40, 255)
MID = (55, 75, 120, 255)
SPECK = (250, 240, 90, 255)


def silhouette_aa(im):
    """Opaque pixels that touch transparency and differ from the neighbour one step inward.

    The inward comparison is what makes this a statement rather than a count: a flat outline's
    outermost pixels are identical to what they wrap, so a well-behaved hard outline scores zero.
    """
    px = im.load()
    w, h = im.size
    n = 0
    for x, y in _opaque(im):
        outward = None
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if not (0 <= nx < w and 0 <= ny < h) or px[nx, ny][3] == 0:
                outward = (dx, dy)
                break
        if outward is None:
            continue
        ix, iy = x - outward[0], y - outward[1]
        if 0 <= ix < w and 0 <= iy < h and px[ix, iy][3] > 0 and px[ix, iy] != px[x, y]:
            n += 1
    return n


def block(ring=False, aa_corners=False, specks=False, stray=False):
    """An 8..23 block; optionally a 1px line ring, specks inside, AA on the corners."""
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
        # the four staircase corners get a mid-tone, drawn just inside the silhouette
        for cx, cy in ((9, 9), (22, 9), (9, 22), (22, 22)):
            px[cx, cy] = MID
    if specks:
        for y in range(12, 20):
            for x in range(12, 20):
                if (x * 3 + y * 5) % 4 == 0:
                    px[x, y] = SPECK
    if stray:
        # on the silhouette, one pixel out of nowhere
        px[8, 16] = (255, 0, 255, 255)
    return im


cases = [
    ("solid block", block(), 0),
    ("block + 1px line ring", block(ring=True), "all of the ring"),
    ("ring + AA on 4 corners", block(ring=True, aa_corners=True), 4),
    ("block + interior specks", block(specks=True), 0),
    ("ring + AA + interior specks", block(ring=True, aa_corners=True, specks=True), 4),
    ("ring + 1 stray pixel ON the edge", block(ring=True, stray=True), 1),
]
print("%-36s %12s %10s" % ("case", "silhouette", "expected"))
for label, im, want in cases:
    got = silhouette_aa(im)
    ok = ""
    if want == 0:
        ok = "OK" if got == 0 else "**MISMATCH**"
    elif want == 1:
        ok = "OK" if got >= 1 else "**MISMATCH**"
    else:
        ok = "OK" if got > 0 else "**MISMATCH**"
    print("%-36s %12d %10s  %s" % (label, got, want, ok))

print()
print("Reading of the table:")
print("  * interior speckles do not move the number at all -- that is the separation `isolated_rate`")
print("    could not make, because it pooled both populations")
print("  * a stray pixel on the silhouette is counted exactly like AA, so the field cannot by")
print("    itself say 'this was smoothed' rather than 'this has a bad pixel'. Recorded as a limit.")
