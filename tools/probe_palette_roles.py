#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Can a palette colour's *role* be measured, or only guessed from what it depicts?

The TODO entry asks for role slots: "按用途分槽（皮肤/头发/服装/描边/高光）会比按色相分更有用". Four of
those five need semantics -- nothing in a pixel grid says which region is skin. **Two do not**, and this
probe measures those two:

    outline     the colour sits on the outer edge, touching transparency
    highlight   the colour sits inside, on top of pixels that are uniformly darker than it
    mid         everything else

The test is whether those two separate cleanly on real sprites, and in particular whether **every sprite has
exactly one outline role** -- which is what `outline_predictability` measuring ~1.0 implies but does not
say. If a sprite comes out with several outline colours, the criterion is too loose; if none, too tight.

    python tools/probe_palette_roles.py [--limit N]
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


def measure(im, *, edge_share=0.5, dark_delta=8.0):
    """Each colour on the board, with the two position facts that decide its role.

    For every occurrence of a colour:
      touches_clear   one of its four neighbours is transparent -- the outer edge
      darker_around   the mean luma of its opaque four-neighbours is at least `dark_delta` below its own
                      (a highlight sits on a darker body; a body does not sit on a darker body uniformly)
    """
    im = im.convert("RGBA")
    clear = im.getbbox()
    if clear:
        im = im.crop(clear)
    px = im.load()
    w, h = im.size
    occ = Counter()
    touch = Counter()
    darker = Counter()
    for y in range(h):
        for x in range(w):
            c = px[x, y]
            if c[3] == 0:
                continue
            key = c[:3]
            occ[key] += 1
            neigh, clear_side = [], False
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                a, b = x + dx, y + dy
                if not (0 <= a < w and 0 <= b < h) or px[a, b][3] == 0:
                    clear_side = True
                elif px[a, b][:3] != key:
                    neigh.append(px[a, b][:3])
            if clear_side:
                touch[key] += 1
            if neigh:
                mean_other = sum(luma(n) for n in neigh) / len(neigh)
                if mean_other < luma(key) - dark_delta:
                    darker[key] += 1
    out = {}
    for c, n in occ.items():
        out[c] = {
            "pixels": n,
            "edge_share": touch[c] / n,
            "darker_around_share": darker[c] / n,
        }
    return out


def role(facts, *, edge_share=0.5, darker_share=0.5):
    if facts["edge_share"] >= edge_share:
        return "outline"
    if facts["darker_around_share"] >= darker_share:
        return "highlight"
    return "mid"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=24)
    a = ap.parse_args()
    files = sorted(Path(CORPUS).rglob("*.png"))[: a.limit]
    if not files:
        print("no corpus samples at %s" % CORPUS)
        return 1

    print("%-26s %6s %8s %10s %10s %10s" %
          ("sprite", "colours", "outline", "highlight", "mid", "unseen?"))
    tot = Counter()
    outlines = Counter()
    for f in files:
        board = P.sample(Image.open(f).convert("RGBA"), n=64)
        facts = measure(Image.open(f), )
        by_role = Counter()
        for c in board:
            t = tuple(c)
            if t not in facts:
                by_role["absent"] += 1
                continue
            by_role[role(facts[t])] += 1
        outlines[by_role["outline"]] += 1
        tot.update(by_role)
        print("%-26s %6d %8d %10d %10d %10d"
              % (Path(f).name[:26], len(board), by_role["outline"], by_role["highlight"],
                 by_role["mid"], by_role["absent"]))
    print()
    print("  totals: %s" % dict(tot))
    print("  how many OUTLINE colours per sprite: %s" % dict(sorted(outlines.items())))
    print()
    print("  reading: exactly one outline colour per sprite is the clean answer, and it is what")
    print("  `outline_predictability` ~1.0 implies. More than one means the criterion is loose.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
