#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Can `highlight` be measured, or is every sharper criterion still describing a gradient?

`roles()` assigns `outline` and `fill` and **deliberately does not assign `highlight`**, because the obvious
criterion -- "most of its neighbours are darker than it" -- put **224 colours into that role across 20
sprites**, four to seventeen per sprite. That is what a gradient looks like at every step, not a role.

**I do not know how many highlights a real sprite has**, so this probe cannot report a correct answer. What it
can do is measure several sharper criteria and show the distribution each produces, which is the honest
position: a criterion is only usable if it lands on a plausible number for art whose author drew a highlight
on purpose, and if it does not degenerate into "most colours".

Criteria tried, from loose to sharp:

    most_darker        the loose one, for reference
    all_brighter       brighter than **every** opaque neighbour, not most
    all_brighter+int   ... and not touching transparency, so it is inside the drawing
    +area < 5%         ... and covering under 5% of the drawn pixels
    +area < 2%         ... and under 2%

    python tools/probe_highlight.py [--limit N]
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import importlib

P = importlib.import_module("ichiwatashi.palette")
from PIL import Image

CORPUS = r"E:\DaShaoHuo\downloads\ichiwatashi-corpus"


def luma(c):
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


def facts(im):
    """Per colour: pixel count, whether it ever touches clear, and its neighbour-luma comparisons."""
    im = im.convert("RGBA")
    box = im.getbbox()
    if box:
        im = im.crop(box)
    px = im.load()
    w, h = im.size
    count = Counter()
    touch = Counter()
    brighter_than_all = Counter()   # occurrences where every opaque neighbour is darker
    neighbour_pairs = Counter()
    single_kind = Counter()         # occurrences whose opaque neighbours are all ONE darker colour
    two_kind = Counter()            # ... at most two
    kind_counts = []
    for y in range(h):
        for x in range(w):
            c = px[x, y]
            if c[3] == 0:
                continue
            key = c[:3]
            count[key] += 1
            neigh = []
            clear_side = False
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                a, b = x + dx, y + dy
                if not (0 <= a < w and 0 <= b < h) or px[a, b][3] == 0:
                    clear_side = True
                elif px[a, b][:3] != key:
                    neigh.append(px[a, b][:3])
            if clear_side:
                touch[key] += 1
            if neigh:
                neighbour_pairs[key] += 1
                mine = luma(key)
                if all(luma(n) < mine for n in neigh):
                    brighter_than_all[key] += 1
                    # **the discriminator**: a highlight sits inside one flat field, so every neighbour is
                    # the same darker colour. A step of a gradient touches two different levels instead.
                    if len(set(neigh)) == 1:
                        single_kind[key] += 1
                    if len(set(neigh)) <= 2:
                        two_kind[key] += 1
    drawn = sum(count.values())
    out = {}
    for c, n in count.items():
        out[c] = {
            "pixels": n,
            "share": n / drawn,
            "touch_share": touch[c] / n,
            "all_brighter_share": brighter_than_all[c] / max(1, neighbour_pairs[c]),
            "single_kind_share": single_kind[c] / max(1, neighbour_pairs[c]),
            "two_kind_share": two_kind[c] / max(1, neighbour_pairs[c]),
        }
    return out


def classify(f, *, criterion):
    if criterion == "most_darker":
        return f["all_brighter_share"] >= 0.5
    if criterion == "all_brighter":
        return f["all_brighter_share"] >= 1.0
    if criterion == "all_brighter+int":
        return f["all_brighter_share"] >= 1.0 and f["touch_share"] == 0.0
    if criterion == "+area < 5%":
        return f["all_brighter_share"] >= 1.0 and f["touch_share"] == 0.0 and f["share"] < 0.05
    if criterion == "+area < 2%":
        return f["all_brighter_share"] >= 1.0 and f["touch_share"] == 0.0 and f["share"] < 0.02
    if criterion == "+one field":
        return f["all_brighter_share"] >= 1.0 and f["single_kind_share"] >= 1.0
    if criterion == "+one field+int":
        return (f["all_brighter_share"] >= 1.0 and f["single_kind_share"] >= 1.0
                and f["touch_share"] == 0.0)
    if criterion == "+two fields":
        return f["all_brighter_share"] >= 1.0 and f["two_kind_share"] >= 1.0
    if criterion == "+one field+2%":
        return (f["all_brighter_share"] >= 1.0 and f["single_kind_share"] >= 1.0
                and f["touch_share"] == 0.0 and f["share"] < 0.02)
    raise ValueError(criterion)


CRITERIA = ("most_darker", "all_brighter", "all_brighter+int", "+area < 2%",
            "+one field", "+one field+int", "+two fields", "+one field+2%")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=20)
    a = ap.parse_args()
    files = sorted(Path(CORPUS).rglob("*.png"))[: a.limit]
    if not files:
        print("no corpus samples at %s" % CORPUS)
        return 1

    tally = {c: [] for c in CRITERIA}
    for f in files:
        board = P.sample(Image.open(f), n=64)
        fs = facts(Image.open(f))
        for crit in CRITERIA:
            n = sum(1 for c in board if tuple(c) in fs and classify(fs[tuple(c)], criterion=crit))
            tally[crit].append(n)

    print("  %d sprites; per sprite count of colours meeting each criterion" % len(files))
    print()
    print("  %-16s %6s %6s %6s %6s %10s" % ("criterion", "min", "median", "max", "total", "per sprite"))
    for crit in CRITERIA:
        v = sorted(tally[crit])
        med = v[len(v) // 2]
        print("  %-16s %6d %6d %6d %6d %10.1f"
              % (crit, v[0], med, v[-1], sum(v), sum(v) / len(v)))
    print()
    print("  reading: `most_darker` is the loose criterion that was rejected. A usable one should name a")
    print("  couple of colours per sprite rather than a tenth of the palette, and should not be at zero for")
    print("  most sprites -- both failure directions are visible in the columns above.")
    print()
    print("  **And the middle ground is not evidence.** `+two fields` lands on 3 per sprite, which looks")
    print("  plausible -- but there is no ground truth to check it against. `outline` can be believed because")
    print("  `outline_predictability` independently measures the same relation and reads ~1.0 on real art;")
    print("  a `highlight` role would have no such cross-check, so a plausible number is all it would be.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
