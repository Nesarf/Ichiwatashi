"""Probe: can anti-aliasing be told apart from interior detail by where the pixel sits?

`isolated_rate` counts opaque pixels whose opaque neighbours are all a different colour. That
description covers two unrelated things, which `README.md` already records as a hazard:

    a single-pixel eye highlight, a cloth texture speck   -> interior, and it is the detail
    a mid-tone pixel on a staircase corner of the outline -> at the silhouette, and it is AA

The published convention (Pixnote, "輪郭線とアンチエイリアス", see corpus/AESTHETICS.md) is specific
about where AA belongs: only on long diagonals and curves, one pixel wide, inside the silhouette,
and never on small sprites. So position is the discriminator that `isolated_rate` throws away.

This measures the candidate split before anything is wired into the judge:

    interior   opaque, not touching transparency
    silhouette opaque, touching transparency

and within the silhouette, whether the pixel is a corner step (AA's home) or a straight edge.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ichiwatashi.judge import _opaque  # noqa: E402
from PIL import Image  # noqa: E402

SPRITES = Path(r"E:\DaShaoHuo\downloads\ichiwatashi-corpus\th155")


def classify(im):
    """Return counts: interior, silhouette, and silhouette-on-a-corner."""
    px = im.load()
    w, h = im.size
    inside, sil, corner = 0, 0, 0
    for x, y in _opaque(im):
        touches_empty = False
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if not (0 <= nx < w and 0 <= ny < h) or px[nx, ny][3] == 0:
                touches_empty = True
                break
        if not touches_empty:
            inside += 1
            continue
        sil += 1
        # a corner step: transparency is reachable diagonally but not straight ahead, or both an
        # orthogonal and a diagonal neighbour are empty. That is where a staircase looks like steps.
        orth = [px[x + dx, y + dy][3] == 0 for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                if 0 <= x + dx < w and 0 <= y + dy < h]
        diag = 0
        for dx, dy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
            nx, ny = x + dx, y + dy
            if not (0 <= nx < w and 0 <= ny < h) or px[nx, ny][3] == 0:
                diag += 1
        if diag and sum(orth) < 2:
            corner += 1
    return inside, sil, corner


def isolated_split(im):
    """`_isolated`'s predicate, split by where it fires."""
    px = im.load()
    w, h = im.size
    inside = sil = 0
    for x, y in _opaque(im):
        c = px[x, y]
        seen = same = False
        touches_empty = False
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if not (0 <= nx < w and 0 <= ny < h):
                continue
            if px[nx, ny][3] == 0:
                touches_empty = True
                continue
            seen = True
            if px[nx, ny] == c:
                same = True
                break
        if seen and not same:
            if touches_empty:
                sil += 1
            else:
                inside += 1
    return inside, sil


files = sorted(SPRITES.glob("*.png"))[:40]
rows = []
for p in files:
    with Image.open(p) as im:
        im = im.convert("RGBA")
        ins, sil, cor = classify(im)
        iso_in, iso_sil = isolated_split(im)
        n = ins + sil
        rows.append((p.name, n, ins, sil, cor, iso_in, iso_sil))

print("%-22s %7s %8s %8s %8s %8s %8s" %
      ("sprite", "opaque", "interior", "silhou.", "corner", "iso-int", "iso-sil"))
for r in rows[:8]:
    print("%-22s %7d %8d %8d %8d %8d %8d" % r)

import statistics
def med(i):
    return statistics.median([r[i] for r in rows])
print()
print("medians over %d sprites:" % len(rows))
print("  interior share of opaque        : %.3f" % (med(2) / med(1)))
print("  silhouette share                : %.3f" % (med(3) / med(1)))
print("  corner share                    : %.4f" % (med(4) / med(1)))
print("  isolated pixels that sit inside : %.1f" % med(5))
print("  isolated pixels at the silhouette: %.1f" % med(6))
print()
tot_in = sum(r[5] for r in rows)
tot_sil = sum(r[6] for r in rows)
print("pooled isolated pixels: %d interior vs %d at the silhouette" % (tot_in, tot_sil))
print("=> the silhouette share is the part an AA rule could look at; the interior part is detail.")
