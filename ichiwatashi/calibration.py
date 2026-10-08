# -*- coding: utf-8 -*-
"""Measured reference distributions, so thresholds are derived from evidence rather than chosen.

**Why this module exists.** The first version of the judge used thresholds that felt reasonable and one
of them was wrong by a factor of two: "isolated pixels above 5% is noise" was written before any real
sprite had been measured, and real sprites sit at **11.6% median**. Pointed at 120 of them it fired on
almost all of them -- a false positive on known-good art, which is the failure this project is least
allowed to have.

So the numbers below are measurements, and each carries the sample they came from. A threshold is now a
statement about a population rather than an opinion, and the way to change one is to point a script at
more sprites.

## The sample

120 frames from `th123a.dat` (Touhou Hisoutensoku, 2010), all 8bpp character sprites with a palette,
sizes 24 to 128 pixels on the long side, chosen by a seeded `random.sample` so the run is reproducible.
3853 frames were eligible. This is *one* game, and its art direction is one point in the space of pixel
art -- so these are a reference for "hand-authored 2000s commercial sprite", not for pixel art in
general. `TODO.md` records the intent to widen it.

```
metric                    p05     p25   median     p75     p95
palette_size             16.0    22.0     26.0    31.0    37.0
isolated_rate           0.074   0.099    0.116   0.134   0.160
outline_variation       0.578   0.658    0.726   0.801   0.855
bbox_fill               0.345   0.458    0.538   0.589   0.652
largest_cluster_rate    0.039   0.063    0.090   0.136   0.228
```

Only 1 of the 120 raised any note after the isolated-pixel rule was corrected, which is the property
worth keeping: **a report that fires on good work is a report that gets ignored.**
"""
from __future__ import annotations

__all__ = ["REFERENCE", "Percentiles", "outside"]

#: Which game and how many sprites, so a reader can judge whether a threshold applies to them.
PROVENANCE = {
    "source": "th123a.dat (Touhou Hisoutensoku, 2010)",
    "kind": "8bpp character frames with a palette, 24-128 px on the long side",
    "sample": 120,
    "eligible": 3853,
    "sampling": "random.sample with a fixed seed",
}


class Percentiles:
    """Five points of one measured distribution."""

    def __init__(self, p05, p25, median, p75, p95):
        self.p05, self.p25, self.median, self.p75, self.p95 = p05, p25, median, p75, p95

    def as_dict(self):
        return {"p05": self.p05, "p25": self.p25, "median": self.median,
                "p75": self.p75, "p95": self.p95}

    def __repr__(self):
        return "Percentiles(p05=%s, median=%s, p95=%s)" % (self.p05, self.median, self.p95)


REFERENCE = {
    "palette_size": Percentiles(16.0, 22.0, 26.0, 31.0, 37.0),
    # The rule this replaces fired above 5%. Real sprites live between 7.4% and 16%, so the old
    # threshold was below the fifth percentile of good work.
    "isolated_rate": Percentiles(0.074, 0.099, 0.116, 0.134, 0.160),
    "outline_variation": Percentiles(0.578, 0.658, 0.726, 0.801, 0.855),
    "bbox_fill": Percentiles(0.345, 0.458, 0.538, 0.589, 0.652),
    "largest_cluster_rate": Percentiles(0.039, 0.063, 0.090, 0.136, 0.228),
}


def outside(metric: str, value: float, *, low: bool = True, high: bool = True):
    """Return a sentence naming which side of the reference range a value fell, or None.

    The range used is p05 to p95, so by construction about one sprite in ten of the reference sample
    would sit outside it. That is deliberate: **a note should mean "this is unlike the reference" and
    not "this is wrong"**, and roughly one in ten is the rate at which the former stays useful.
    """
    ref = REFERENCE.get(metric)
    if ref is None:
        return None
    if low and value < ref.p05:
        return "%s is %.3f, below the reference range %.3f-%.3f (%s, n=%d)" % (
            metric, value, ref.p05, ref.p95, PROVENANCE["source"].split(" (")[0],
            PROVENANCE["sample"])
    if high and value > ref.p95:
        return "%s is %.3f, above the reference range %.3f-%.3f" % (
            metric, value, ref.p05, ref.p95)
    return None
