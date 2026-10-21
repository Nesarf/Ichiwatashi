# -*- coding: utf-8 -*-
"""Where a sprite sits among the measured generations. A position, not a verdict.

**Why this is not a model.** A learned judgement would need labels, and the only labels this project
can defend are "these came from known-good work" -- which is exactly what the two reference buckets
already are. So the first version of this answers the question a caller actually asks ("which era does
this look like?") by placing the four numbers the judge already measures against the two bands it
already carries. Nothing is trained, and every distance can be opened up into the numbers it was
computed from.

**What the distance means, concretely.** For each metric, `calibration.how_far` reports how many band
widths a value sits outside its p05-p95 range -- zero when inside, and always a magnitude -- and this
module records the **direction** beside it (`below` / `above` / `none`), because "fewer colours than any
reference generation" and "more" are different findings and a magnitude cannot tell them apart. The
distance is the length of that vector, so `1.0` means "one band width outside, on one metric" and
`0.707` means two metrics half a width out each. It is a position, not a probability.

**Why not a standard deviation.** The reference records five percentiles, not a mean and a spread.
Converting them into sigma would invent two parameters nobody measured, and the module that carries
them (`calibration.py`) exists because a guessed parameter was wrong by a factor of two once already.

**A metric absent from a generation is not compared, and the count says so.** TH155 has no
`colours_used` band, because its palettes are interchangeable and 92.5% of its sprites change colour
count when decoded with another member of the same set. Comparing three metrics against one generation
and four against another is a real asymmetry, so `compared` travels with every row.
"""
from __future__ import annotations

from . import calibration

__all__ = ["METRICS", "GENERATIONS", "position", "nearest", "describe"]

#: The metrics a position is computed from: the ones the judge measures on every sprite and the
#: reference carries a band for. Deliberately not `outline_variation` or `outline_predictability` --
#: those two are the convention that differs most between generations, and they are reported as a
#: style rather than graded, so folding them into a distance would turn "this is TH155-shaped" into
#: "this is wrong".
METRICS = ("colours_used", "isolated_rate", "bbox_fill", "largest_cluster_rate")

#: Which generations can be compared against, in the order they are reported.
GENERATIONS = tuple(calibration.REFERENCE_BY_GENERATION)


def _value(report, metric):
    """One metric off a `Report`, or off a mapping with the same keys."""
    if isinstance(report, dict):
        return report.get(metric)
    return getattr(report, metric, None)


def position(report, generation):
    """One generation's row: the distance, the metrics compared, and every metric's own row.

    A generation with no band for one of `METRICS` simply does not compare it; `compared` is the number
    that did, so a row computed from three metrics cannot be read as one computed from four.
    """
    bucket = calibration.REFERENCE_BY_GENERATION.get(generation)
    if bucket is None:
        raise ValueError("unknown generation %r; known: %s"
                         % (generation, ", ".join(sorted(calibration.REFERENCE_BY_GENERATION))))

    rows = []
    offset_squares = 0.0
    for metric in METRICS:
        ref = bucket.get(metric)
        value = _value(report, metric)
        if ref is None or value is None:
            continue
        offset = calibration.how_far(metric, float(value), generation=generation)
        offset_squares += offset * offset
        if offset == 0.0:
            direction = "none"
        else:
            # `how_far` returns a magnitude, so the side has to be read off the value itself. Reading
            # it as a sign would have reported "below the band" and "above the band" identically, and
            # those are not the same finding.
            direction = "below" if float(value) < ref.p05 else "above"
        rows.append({
            "metric": metric,
            "value": value,
            "p05": ref.p05,
            "median": ref.median,
            "p95": ref.p95,
            "offset": round(offset, 4),
            "direction": direction,
            "inside": offset == 0.0,
        })
    # sqrt of the squared offsets, not a sum: two metrics each one width out is the same displacement
    # in two directions, and a sum would call that twice as far without saying so.
    distance = offset_squares ** 0.5
    return {
        "generation": generation,
        "distance": round(distance, 4),
        "compared": len(rows),
        "inside": sum(1 for r in rows if r["inside"]),
        "rows": rows,
    }


def nearest(report, *, generations=None):
    """Every generation's row, sorted by distance, plus whether they can be told apart at all.

    **`separated` is the honest half.** When both generations are inside every band they compare, the
    two distances are both zero and the sprite does not carry evidence for either. Reporting the
    closer one as an answer would be a coin flip with a decimal point.
    """
    wanted = tuple(generations or GENERATIONS)
    rows = [position(report, g) for g in wanted]
    rows.sort(key=lambda r: (r["distance"], -r["inside"]))
    best = rows[0]
    runner_up = rows[1] if len(rows) > 1 else None
    separated = bool(runner_up and runner_up["distance"] > best["distance"])
    return {
        "placed": best,
        "all": rows,
        "separated": separated,
        "runner_up": runner_up,
    }


def describe(result, name=None):
    """The report, as lines. Kept next to the numbers so the two cannot describe different things."""
    best = result["placed"]
    loser = result["runner_up"]
    out = []
    if name:
        out.append(name)
    head = "  nearest      %s  distance %.2f  compared %d metric(s), %d inside" % (
        best["generation"], best["distance"], best["compared"], best["inside"])
    out.append(head)
    if loser is not None:
        if result["separated"]:
            # The runner-up is reported even when the answer is clear: "closer to one era" is only
            # useful beside how far the other one was, and a reader who wants to disagree needs both.
            out.append("  next         %s  distance %.2f  compared %d metric(s), %d inside"
                       % (loser["generation"], loser["distance"], loser["compared"], loser["inside"]))
        else:
            # Two generations at the same distance is a result, and the useful thing to say is that the
            # sprite does not distinguish them -- not which one sorted first.
            out.append("  the two generations are not separated: %s also sits at distance %.2f on %d metric(s)"
                       % (loser["generation"], loser["distance"], loser["compared"]))
    for row in best["rows"]:
        state = ("inside" if row["inside"]
                 else "%.2f band(s) %s the range" % (row["offset"], row["direction"]))
        out.append("    %-20s %8.3f   p05 %.3f  median %.3f  p95 %.3f   %s"
                   % (row["metric"], row["value"], row["p05"], row["median"], row["p95"], state))
    return "\n".join(out)
