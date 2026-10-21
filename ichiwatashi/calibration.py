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
colours_used             16.0    22.0     26.0    31.0    37.0
isolated_rate           0.074   0.099    0.116   0.134   0.160
outline_variation       0.578   0.658    0.726   0.801   0.855
bbox_fill               0.345   0.458    0.538   0.589   0.652
largest_cluster_rate    0.039   0.063    0.090   0.136   0.228
```

Only 1 of the 120 raised any note after the isolated-pixel rule was corrected, which is the property
worth keeping: **a report that fires on good work is a report that gets ignored.**
"""
from __future__ import annotations

__all__ = ["REFERENCE", "REFERENCE_BY_GENERATION", "GENERATIONS", "DEFAULT_GENERATION",
           "PROVENANCE", "PROVENANCE_BY_GENERATION", "Percentiles", "outside", "how_far"]

#: Which game and how many sprites, so a reader can judge whether a threshold applies to them.
PROVENANCE = {
    "source": "th123a.dat (Touhou Hisoutensoku, 2010)",
    "kind": "8bpp character frames with a palette, 24-128 px on the long side",
    "sample": 120,
    "eligible": 3853,
    "sampling": "random.sample with a fixed seed",
}


#: Where the TH155 bucket came from. Recorded separately because it is a different population and a
#: reader has to be able to tell which numbers apply to their art.
PROVENANCE_BY_GENERATION = {
    "th105/th123": PROVENANCE,
    "th155": {
        "source": "th155.pak (Touhou 15.5 AoCF, 2017), 8bpp indexed sprites",
        "kind": "character sprites with the container's own palette, tight-cropped",
        "sample": 160,
        "eligible": 160,
        "sampling": "four characters x 40 consecutive sprites, no random selection",
        "caveat": ("colours_used is not a property of these drawings: the palettes are "
                   "interchangeable within a character and 92.5% of sprites change colour count "
                   "when decoded with another member of the set"),
    },
}


def _sample_of(generation: str):
    prov = PROVENANCE_BY_GENERATION.get(generation)
    return prov["sample"] if prov else "?"


class Percentiles:
    """Five points of one measured distribution."""

    def __init__(self, p05, p25, median, p75, p95):
        self.p05, self.p25, self.median, self.p75, self.p95 = p05, p25, median, p75, p95

    def as_dict(self):
        return {"p05": self.p05, "p25": self.p25, "median": self.median,
                "p75": self.p75, "p95": self.p95}

    def __repr__(self):
        return "Percentiles(p05=%s, median=%s, p95=%s)" % (self.p05, self.median, self.p95)


#: Which generation a reference belongs to. **Two tiers, not three**, and that is measured:
#: TH105 and TH123 agree on every metric to three decimals across four characters and twelve
#: comparisons, so they are one population. TH155 is a second one.
GENERATIONS = ("th105/th123", "th155")

#: Two references, not one. This is the correction the module above describes the need for: a single
#: table was used to judge a second generation of correct work and flagged all of it.
#: `tools/calibrate.py` and `tools/measure_generation_bucket.py` produce these.
REFERENCE_BY_GENERATION = {
    "th105/th123": {
        "colours_used": Percentiles(16.0, 22.0, 26.0, 31.0, 37.0),
        # The rule this replaces fired above 5%. Real sprites live between 7.4% and 16%, so the old
        # threshold was below the fifth percentile of good work.
        "isolated_rate": Percentiles(0.074, 0.099, 0.116, 0.134, 0.160),
        "bbox_fill": Percentiles(0.345, 0.458, 0.538, 0.589, 0.652),
        "largest_cluster_rate": Percentiles(0.039, 0.063, 0.090, 0.136, 0.228),
        # Kept for continuity. It is NOT consulted by `judge()` any more: the outline style is
        # reported as a style (see `judge.outline_style`) rather than graded, because the two
        # generations sit at 0.726 and 0.004 and both are correct work.
        "outline_variation": Percentiles(0.578, 0.658, 0.726, 0.801, 0.855),
    },
    "th155": {
        # **`colours_used` is deliberately absent, and it is absent because it is not a property of
        # the drawing on this generation.** TH155 sprites are palette indices; each character ships
        # a set of interchangeable palettes, and decoding one sprite with a different member of its
        # own set changes the measured colour count for 92.5% of sprites with a median spread of 27
        # on a median of 44.5. The corpus recorded one palette per sprite, so any threshold derived
        # here would be a threshold derived from an arbitrary choice among sixteen. A missing
        # metric yields no note, which is the honest outcome; a wrong one does not.
        "isolated_rate": Percentiles(0.028, 0.071, 0.126, 0.153, 0.179),
        "bbox_fill": Percentiles(0.281, 0.344, 0.396, 0.449, 0.755),
        "largest_cluster_rate": Percentiles(0.023, 0.033, 0.042, 0.075, 0.248),
        # The two generations differ here by a wide margin too, so it is bucketed rather than
        # global: TH155 measures 0.997 median, which is the "cel-out" convention of outlining a
        # body with a darkened copy of its own colour.
        "outline_predictability": Percentiles(0.868, 0.954, 0.997, 1.000, 1.000),
    },
}

#: The reference consulted when a caller does not say which generation it is measuring.
#:
#: **This default is a known weakness and is named rather than hidden.** Judging a TH155 sprite
#: without saying so applies TH123's `colours_used` band of 16-37 and, at a median of 43, most
#: TH155 sprites fall outside it. Pass `generation="th155"` to `judge()` to get the right table.
DEFAULT_GENERATION = "th105/th123"

#: Backwards-compatible alias for the default bucket. Prefer `REFERENCE_BY_GENERATION`.
REFERENCE = REFERENCE_BY_GENERATION[DEFAULT_GENERATION]


def outside(metric: str, value: float, *, margin: float = 0.5,
            generation: str = DEFAULT_GENERATION):
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
    bucket = REFERENCE_BY_GENERATION.get(generation)
    if bucket is None:
        # An unknown generation is not the default generation. Saying nothing is right; silently
        # applying another era's thresholds is what produced the false-positive generation.
        return None
    ref = bucket.get(metric)
    if ref is None:
        return None
    spread = max(1e-9, ref.p95 - ref.p05)
    lo = ref.p05 - margin * spread
    hi = ref.p95 + margin * spread
    if value < lo:
        return ("%s is %.3f, well below the reference range %.3f-%.3f (generation %s, n=%s)"
                % (metric, value, ref.p05, ref.p95, generation, _sample_of(generation)))
    if value > hi:
        return ("%s is %.3f, well above the reference range %.3f-%.3f (generation %s, n=%s)"
                % (metric, value, ref.p05, ref.p95, generation, _sample_of(generation)))
    return None


def how_far(metric: str, value: float, *,
            generation: str = DEFAULT_GENERATION):
    """How many band widths a value sits outside its range. **A magnitude, not a signed distance.**

    The docstring here said "signed" for a while and the code never was: both branches return a
    positive number. Nothing noticed because the only caller (`judge`) uses it for ordering, where the
    sign does not matter -- it was found when a caller wanted to say which side a value fell on and
    would have reported "far below" and "far above" as the same thing. Which side is readable from the
    value and the range; this function answers "by how much".
    """
    bucket = REFERENCE_BY_GENERATION.get(generation)
    if bucket is None or metric not in bucket:
        return 0.0
    ref = bucket[metric]
    spread = max(1e-9, ref.p95 - ref.p05)
    if value < ref.p05:
        return (ref.p05 - value) / spread
    if value > ref.p95:
        return (value - ref.p95) / spread
    return 0.0
