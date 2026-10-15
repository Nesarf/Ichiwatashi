#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""Draw every report figure once, write the PNGs, and print what each one measures.

**This probe exists to be looked at.** A figure that parses, renders and saves can still be wrong in a
way no assertion in the suite would catch -- a glyph read upside down, a ring drawn over its own fill, a
label one letter short -- so the output goes to `E:\DaShaoHuo\cache\tmp\figures\` and the point of running
this is that somebody opens them.

It also does the job the TODO entry asked for, in the order the entry asked for it: the figures are drawn
with `builder` and `font`, and a verb that cannot draw its figure is reported as a gap in the tool.

    python tools/probe_figures.py [--scale N] [--out DIR]
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import importlib

F = importlib.import_module("ichiwatashi.figures")
P = importlib.import_module("ichiwatashi.palette")
J = importlib.import_module("ichiwatashi.judge")
from PIL import Image

CORPUS = r"E:\DaShaoHuo\downloads\ichiwatashi-corpus"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", type=int, default=6)
    ap.add_argument("--out", default=r"E:\DaShaoHuo\cache\tmp\figures")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    files = sorted(glob.glob(CORPUS + r"\**\*.png", recursive=True))
    if not files:
        print("no corpus samples; run with the corpus present")
        return 1
    sample = Image.open(files[0]).convert("RGBA")
    clear = sample.getbbox()
    if clear:
        sample = sample.crop(clear)

    written = []

    # 1. the palette board: what the sampler found, and that a ring derives from its fill
    board = P.sample(sample, n=18)
    canvas, keys = F.palette_board(board, per_row=9, title="PALETTE %d" % len(board))
    p = out / "palette-board.png"
    F.render(canvas, keys, a.scale).convert("RGB").save(p)
    written.append((p, "%d swatches, each ringed by its own darker step" % len(board)))

    # 2. the outline study: as drawn against a flat ring
    canvas, keys = F.outline_study(sample, title="OUTLINE", glyphs=F._glyphs())
    p = out / "outline-study.png"
    F.render(canvas, keys, max(2, a.scale // 3)).convert("RGB").save(p)
    written.append((p, "left: the sprite; right: its outermost pixels only"))

    # 3. the silhouette
    canvas, keys = F.silhouette_map(sample, title="SILHOUETTE")
    p = out / "silhouette.png"
    F.render(canvas, keys, max(2, a.scale // 3)).convert("RGB").save(p)
    written.append((p, "every drawn pixel as one flat colour"))

    # 4. a distribution: five metrics of the real corpus against the shipped reference
    rows = []
    for f in files[:24]:
        im = Image.open(f).convert("RGBA")
        r = J.judge(im)
        rows.append((r.colours_used, r.isolated_rate, r.bbox_fill))
    labels = ["colour", "isolated", "fill"]
    values = [sum(v[i] for v in rows) / len(rows) for i in range(3)]
    # each row inside its own reference band, and the shipped reference marked on each row. A shared
    # scale was tried first and is unreadable: 43.0 against 0.115 and 0.41 collapses two rows to nothing.
    spans = ((9.0, 60.0), (0.0236, 0.1816), (0.284, 0.775))
    refs = (26.0, 0.116, 0.538)
    canvas, keys = F.distribution_bars(labels, values, title="MEAN OF 24", span=spans, reference=refs)
    p = out / "distribution.png"
    F.render(canvas, keys, max(3, a.scale // 2)).convert("RGB").save(p)
    written.append((p, "corpus means, with the shipped reference as a vertical rule"))

    for p, what in written:
        im = Image.open(p)
        print("  %-24s %5d x %-5d %s" % (p.name, im.width, im.height, what))
    print()
    print("  output directory: %s" % out)
    print("  ** open them ** -- this probe is for looking, not for asserting")
    return 0


if __name__ == "__main__":
    sys.exit(main())
