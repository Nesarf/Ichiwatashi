#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the counterexample `pixel_scale` has never had.

`calibration.REFERENCE` has no `pixel_scale` row, and the reason recorded in the
TODO is that it reads 1 on all 120 TH123 sprites and on 640 TH155 sprite/palette
combinations -- there is no distribution to store. But "always 1" is exactly the
state in which a metric cannot be trusted, because nothing has ever shown it
*failing*. The TODO asks for one:

    "pixel_scale 没进参照表 —— 因为在这 120 张上它恒为 1，没有分布可言。
     而"恒为 1"本身是信息：真像素画的游程 GCD 就是像素尺寸。要有一个反例
     （一张被人工放大的图）进参照，才能说明这个指标能失败。"

A metric can fail in two ways, and the counterexample has to pin both:

    upscaled     run lengths really are multiples of n  -> must read n, not 1
    noisy        something that only looks scaled      -> must NOT read n

The second is the one that matters. If `pixel_scale` returns n for anything with
long runs, it is not measuring scale, it is measuring "long runs somewhere" -- and
the TODO already suspects this ("一个被人工加噪的放大图会把 GCD 拉回 1 而看起来没问题").
So this measures a ladder: clean upscales, the same upscales with one stray pixel,
and the same upscales with single-pixel-quantised noise.

Note the direction. `_run_gcd`'s docstring says a *downscaled* drawing keeps runs
in multiples of the scale; the property it actually tests holds for *upscaled*
images (one source pixel -> an n x n block). That is recorded here rather than
silently corrected in the docstring, because which way it points decides what the
metric can ever detect.

    python make_pixel_scale_counterexample.py <out-dir> [--sprites N]
"""
from __future__ import annotations

import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ichiwatashi.judge import judge  # noqa: E402
from PIL import Image  # noqa: E402

sys.path.insert(0, r"E:\~Sayori~Sleeping~\research\touhou-fighting-sprites\tools\tfpk-ref")
from tfpk import Reader  # noqa: E402
import tfbm as T  # noqa: E402

PAK = r"D:\th155\th155.pak"
CONTAINERS = [(238, "doremy", 293, range(309, 546)),
              (804, "futo", 849, range(865, 1009)),
              (1375, "hijiri", 1412, range(1428, 1645)),
              (2044, "ichirin", 1465, range(2096, 2274)),
              (3376, "kasen", 2750, range(2857, 3051))]


def harvest(want):
    """Return [(name, PIL Image)] of tight-cropped 8bpp sprites."""
    a = Reader(PAK)
    dirs, names, entries = a.load()
    out = []
    for cont, ch, pal, run in CONTAINERS:
        if len(out) >= want:
            break
        blob = a.read_file(entries[pal])
        if blob[:4] != b"TFPA":
            continue
        for i in run:
            if len(out) >= want:
                break
            e = entries[i]
            if e["size"] < 22 or a.peek_file(e, 4) != b"TFBM":
                continue
            b = a.read_file(e)
            bpp, w, h, pw, comp = T.header(b)
            if bpp != 8 or w > 400 or h > 400:
                continue
            im = T.to_image(b, blob)
            box = im.getchannel("A").getbbox()
            if not box:
                continue
            crop = im.crop(box)
            if crop.width < 24 or crop.height < 24:
                continue
            out.append(("%s_%04d.png" % (ch, i), crop))
    return out


def noisy(im, factor, seed, stray, quant):
    """Upscale by `factor`, then break the property in a controlled way."""
    up = im.resize((im.width * factor, im.height * factor), Image.NEAREST)
    rng = random.Random(seed)
    px = up.load()
    if stray:
        for _ in range(stray):
            x = rng.randrange(up.width)
            y = rng.randrange(up.height)
            r, g, b, a = px[x, y]
            if a == 0:
                continue
            px[x, y] = ((r + 64) & 0xFF, (g + 64) & 0xFF, (b + 64) & 0xFF, a)
    if quant:
        for y in range(up.height):
            for x in range(up.width):
                r, g, b, a = px[x, y]
                if a == 0:
                    continue
                px[x, y] = ((r // quant) * quant, (g // quant) * quant,
                            (b // quant) * quant, a)
    return up


def main():
    outdir = Path(sys.argv[1])
    (outdir / "clean").mkdir(parents=True, exist_ok=True)
    (outdir / "stray").mkdir(parents=True, exist_ok=True)
    (outdir / "noisy").mkdir(parents=True, exist_ok=True)
    want = 6
    if "--sprites" in sys.argv:
        want = int(sys.argv[sys.argv.index("--sprites") + 1])

    sprites = harvest(want)
    print("harvested %d sprites" % len(sprites))
    if not sprites:
        print("nothing harvested")
        return

    factors = (2, 3, 4)
    rows = []
    print("\n%-22s %5s %-9s %-9s %-9s" %
          ("sprite", "src", "clean", "1 stray", "quantised"))
    for name, im in sprites:
        base = judge(im).pixel_scale
        row = {"sprite": name, "src_size": list(im.size), "src_pixel_scale": base, "cases": []}
        cells = []
        for f in factors:
            c = noisy(im, f, 0, 0, 0)
            s = noisy(im, f, 7, 1, 0)
            q = noisy(im, f, 0, 0, 8)
            r = {"factor": f,
                 "clean": judge(c).pixel_scale,
                 "stray": judge(s).pixel_scale,
                 "quantised": judge(q).pixel_scale}
            row["cases"].append(r)
            c.save(outdir / "clean" / ("x%d_%s" % (f, name)))
            s.save(outdir / "stray" / ("x%d_%s" % (f, name)))
            q.save(outdir / "noisy" / ("x%d_%s" % (f, name)))
            cells.append("x%d %d/%d/%d" % (f, r["clean"], r["stray"], r["quantised"]))
        rows.append(row)
        print("%-22s %5s  %s" % (name, "%dx%d" % tuple(im.size), "  ".join(cells)))

    # --- verdict, computed not asserted ---
    clean_ok = sum(1 for r in rows for c in r["cases"] if c["clean"] == c["factor"])
    clean_n = sum(len(r["cases"]) for r in rows)
    stray_broken = sum(1 for r in rows for c in r["cases"] if c["stray"] == 1)
    quant_broken = sum(1 for r in rows for c in r["cases"] if c["quantised"] == 1)
    src_one = sum(1 for r in rows if r["src_pixel_scale"] == 1)

    print("\n--- results ---")
    print("source sprites reading 1                : %d / %d" % (src_one, len(rows)))
    print("clean upscales reading their factor     : %d / %d" % (clean_ok, clean_n))
    print("...with one stray pixel reading 1       : %d / %d" % (stray_broken, clean_n))
    print("...with 8-level quantisation reading 1  : %d / %d" % (quant_broken, clean_n))
    print()
    if clean_ok == clean_n:
        print("=> pixel_scale DOES detect an integer upscale. It is not a constant.")
    else:
        print("=> pixel_scale FAILS to detect some clean upscales (see the ladder).")
    if stray_broken or quant_broken:
        print("=> and it can fail, which is what a reference row needs in order to mean anything.")
    else:
        print("=> but nothing here made it fail: a stray pixel and a quantised ramp both")
        print("   left it at the factor, so the metric is not measuring 'cleanliness'.")

    (outdir / "manifest.json").write_text(
        json.dumps({"derived_from": "th155.pak 8bpp sprites with the container's own TFPA",
                    "note": "synthesised, not game data: nearest-neighbour integer upscales",
                    "factors": list(factors), "rows": rows}, indent=1, ensure_ascii=False),
        encoding="utf-8")
    print("\nwrote manifest.json and %d PNGs to %s"
          % (3 * clean_n, outdir))


if __name__ == "__main__":
    main()
