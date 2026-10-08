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


def outside(metric: str, value: float, *, margin: float = 0.5):
    """Return a sentence naming which side of the reference range a value fell, or None.

    **The range is not p05-p95, and that is the correction this function carries.** With four metrics
    each flagged about one time in ten, a sprite that is outside on *any* of them is flagged
    `1 - 0.9**4`, about a third of the time -- and running the calibration script over 120 real
    sprites measured exactly that: 42 of them, 35%. **A third of good work raising a note is the same
    failure as the 5% isolated-pixel rule, just distributed.** So the note now needs the value to be
    `margin` of a full range *beyond* p05 or p95, which makes each metric fire on a small percent and
    keeps "flagged" meaning something when it appears.

    `margin=0.5` is a judgement and not a measurement -- what is measured is the false-positive rate
    it produces, which `tools/calibrate.py` reports. Change the margin and re-run that.
    """
    ref = REFERENCE.get(metric)
    if ref is None:
        return None
    spread = max(1e-9, ref.p95 - ref.p05)
    lo = ref.p05 - margin * spread
    hi = ref.p95 + margin * spread
    if value < lo:
        return ("%s is %.3f, well below the reference range %.3f-%.3f (%s, n=%d)"
                % (metric, value, ref.p05, ref.p95,
                   PROVENANCE["source"].split(" (")[0], PROVENANCE["sample"]))
    if value > hi:
        return ("%s is %.3f, well above the reference range %.3f-%.3f (%s, n=%d)"
                % (metric, value, ref.p05, ref.p95,
                   PROVENANCE["source"].split(" (")[0], PROVENANCE["sample"]))
    return None


def how_far(metric: str, value: float):
    """How many reference ranges a value sits outside its range, signed. Used only for ordering."""
    ref = REFERENCE.get(metric)
    if ref is None:
        return 0.0
    spread = max(1e-9, ref.p95 - ref.p05)
    if value < ref.p05:
        return (ref.p05 - value) / spread
    if value > ref.p95:
        return (value - ref.p95) / spread
    return 0.0
