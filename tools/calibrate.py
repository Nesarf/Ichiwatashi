#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Produce a reference distribution from a directory of sprites.

`calibration.py` holds percentiles; this is what produced them, so the numbers in that file are a
result rather than a constant somebody typed. **Without this script the thresholds cannot be checked,
extended or argued with** -- a reader could only take them on faith, which is the opposite of what a
measuring tool is for.

**Any directory of images works**, which is deliberate: the sample in `calibration.py` is one game and
therefore one art direction, and the way to make the thresholds mean more is to run this over other
corpora and compare, rather than to average them together.

Usage:
    python tools/calibrate.py <directory> [--limit N] [--seed S] [--json out.json]

    # compare two corpora rather than merging them
    python tools/calibrate.py ./gba-sprites  --json gba.json
    python tools/calibrate.py ./pc98-sprites  --json pc98.json

The output is the same five percentiles per metric that `calibration.py` stores, plus the flags a run
needs to be trustworthy: how many images were eligible, how many were measured, and how many raised a
note. **If a corpus raises notes on most of its own sprites, the reference is wrong, not the corpus.**
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ichiwatashi import calibration as C          # noqa: E402
from ichiwatashi.judge import judge               # noqa: E402

METRICS = ("colours_used", "isolated_rate", "outline_variation", "bbox_fill",
           "largest_cluster_rate", "dither_pixels")

SUFFIXES = (".png", ".gif", ".bmp", ".webp")


def percentile(values, p):
    if not values:
        return None
    s = sorted(values)
    return s[min(len(s) - 1, int(len(s) * p))]


def collect(directory, *, limit=None, seed=1, min_opaque=50, suffixes=SUFFIXES):
    """Measure up to `limit` images, reproducible for a given seed.

    **The seed is set unconditionally, and it used to be set only on the sampling branch.** That looked
    harmless -- when nothing is sampled there is no `random.sample` to seed -- and it is not, because the
    global random state is then left as whatever the caller's process happened to have. One run over the
    same corpus produced a different file from three others (hashes `C5F2ED7F...` against
    `4CEE73F3...`), which is exactly the shape of unreproducibility this tool exists to avoid: a reference
    distribution that differs between runs cannot be compared with another corpus, and the comparison is
    the whole point of the `--json` output.

    Seeding unconditionally costs nothing and removes the branch.
    """
    random.seed(seed)
    files = sorted(p for p in Path(directory).rglob("*") if p.suffix.lower() in suffixes)
    eligible = len(files)
    if limit and eligible > limit:
        files = random.sample(files, limit)

    from PIL import Image

    rows, skipped = [], []
    for p in sorted(files):
        try:
            with Image.open(p) as im:
                r = judge(im)
        except Exception as e:
            skipped.append((p.name, str(e)[:60]))
            continue
        # A sprite below a few dozen opaque pixels has no silhouette to measure, and including it
        # drags every percentile toward the empty image.
        if r.opaque < min_opaque:
            skipped.append((p.name, "%d opaque pixels" % r.opaque))
            continue
        rows.append(r)
    return {"eligible": eligible, "measured": len(rows), "rows": rows, "skipped": skipped}


def distribution(rows):
    out = {}
    for m in METRICS:
        v = [getattr(r, m) for r in rows]
        out[m] = {k: percentile(v, p) for k, p in
                  (("p05", 0.05), ("p25", 0.25), ("median", 0.5), ("p75", 0.75), ("p95", 0.95))}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("directory")
    ap.add_argument("--limit", type=int, default=120,
                    help="sample size; the default matches the shipped reference")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--json", help="write the distribution here")
    ap.add_argument("--suffixes", help="comma-separated, overriding the default set")
    a = ap.parse_args()

    sfx = tuple(x.strip() if x.strip().startswith(".") else "." + x.strip()
                for x in a.suffixes.split(",")) if a.suffixes else SUFFIXES
    got = collect(a.directory, limit=a.limit, seed=a.seed, suffixes=sfx)
    if not got["rows"]:
        print("no measurable images under %s" % a.directory)
        return 2

    d = distribution(got["rows"])
    print("%s" % a.directory)
    print("  eligible %d, sampled %d, measured %d, skipped %d"
          % (got["eligible"], a.limit, got["measured"], len(got["skipped"])))
    print()
    print("  %-22s %7s %7s %7s %7s %7s" % ("metric", "p05", "p25", "median", "p75", "p95"))
    for m in METRICS:
        q = d[m]
        print("  %-22s %7.3f %7.3f %7.3f %7.3f %7.3f"
              % (m, q["p05"], q["p25"], q["median"], q["p75"], q["p95"]))

    # The check that makes the run trustworthy: a reference whose own sample is mostly flagged is not
    # describing good work, and every threshold derived from it will be wrong in the same direction.
    flagged = sum(1 for r in got["rows"] if r.notes)
    print()
    print("  %d/%d (%.0f%%) of the sample raised at least one note against the current reference"
          % (flagged, got["measured"], 100 * flagged / got["measured"]))
    if flagged / got["measured"] > 0.25:
        print("  ** that is high: this corpus may be a different art direction, which is a reason to")
        print("     keep its distribution separate rather than to change the thresholds by feel **")

    # Where this corpus sits against the shipped one, metric by metric. Separate, not merged.
    print()
    print("  against the shipped reference (median):")
    for m in METRICS:
        ref = C.REFERENCE.get(m)
        if ref is None:
            print("    %-22s (no shipped reference)" % m)
            continue
        here = d[m]["median"]
        flag = "" if ref.p05 <= here <= ref.p95 else "   <- outside the shipped p05-p95"
        print("    %-22s %8.3f  vs %8.3f%s" % (m, here, ref.median, flag))

    if a.json:
        Path(a.json).write_text(json.dumps({
            "provenance": {"source": a.directory, "sample": got["measured"],
                           "eligible": got["eligible"], "seed": a.seed,
                           "suffixes": list(sfx)},
            "distribution": d,
            "flagged": flagged,
        }, indent=2), encoding="utf-8")
        print("\nwrote %s" % a.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
