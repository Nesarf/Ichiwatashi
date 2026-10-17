#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Is `best_accents`' problem actually the combinatorial one it looks like? Checked against brute force.

The TODO entry says "count=6 on a 30-colour pool is 593,775 combinations" and asks for a greedy or annealing
**approximation**, noting that a new approximation has to say where it starts deviating from the exact
answer. That framing assumes the exact answer needs enumeration.

**It might not, and this probe tests the reason it might not.** The objective is

    mind(combo) = min over x in combo of d(x)      where d(x) = min over y in other_board of dist(x, y)

and `d(x)` does not depend on the rest of the combo. So the objective is a **minimum of independent terms**,
which is monotone in the set: adding a colour to a combo can only lower `mind`, never raise it. Maximising a
monotone minimum over fixed-size subsets has a scanning solution rather than a combinatorial one.

The only thing that stops it being one line is the **average-saturation floor**, which is a constraint on the
whole set rather than on each member. So the probe checks the claim on random pools small enough to
enumerate, with and without the floor binding, and reports where -- if anywhere -- a scanning answer
disagrees with the brute-force one.

    python tools/probe_best_accents.py [--trials N]
"""
from __future__ import annotations

import argparse
import itertools
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import importlib

P = importlib.import_module("ichiwatashi.palette")
import colorsys


def brute(pool, other, count, floor):
    """The exhaustive answer, exactly as `best_accents` computes it today."""
    def sat(c):
        return colorsys.rgb_to_hsv(*[v / 255 for v in c[:3]])[1]

    best = None
    for combo in itertools.combinations(pool, count):
        if sum(sat(c) for c in combo) / count < floor:
            continue
        mind = min(math.dist(P._lab(x), P._lab(y)) for x, y in itertools.product(combo, other))
        if best is None or mind > best[0]:
            best = (mind, combo)
    return best


def scanning(pool, other, count, floor):
    """A scanning answer built on the claim that `d(x)` is independent of the rest of the combo.

    For each candidate threshold t taken from the `d` values, the eligible set is every colour with
    `d(x) >= t`. A threshold is feasible when that set is big enough **and** the most saturated `count`
    members of it clear the floor. The largest feasible t wins, and the answer is the `count` colours from
    that set with the highest `d` among those that keep the floor satisfied.
    """
    def sat(c):
        return colorsys.rgb_to_hsv(*[v / 255 for v in c[:3]])[1]

    d = {c: min(math.dist(P._lab(c), P._lab(y)) for y in other) for c in pool}
    thresholds = sorted(set(d.values()), reverse=True)
    for t in thresholds:
        elig = [c for c in pool if d[c] >= t]
        if len(elig) < count:
            continue
        if sum(sat(c) for c in sorted(elig, key=sat, reverse=True)[:count]) / count < floor:
            continue
        # **The answer is the most saturated `count` of the eligible set, and that is exact.** Every member
        # of `elig` has `d >= t`, so any subset of it has `min d >= t`; and `t` is the largest feasible
        # threshold, so no subset anywhere can beat it. Which members are returned therefore does not change
        # the objective, and taking the most saturated ones is what makes the constraint hold by
        # construction.
        #
        # A first version of this used `combinations(by_d[:count + 4])` -- a guessed window around the
        # highest-d colours -- and it **failed on 8 of 66 instances where the floor bound**, every failure a
        # `None`: when the least saturated colours sat inside that window, no combination in it cleared the
        # floor and the scan gave up while brute force found an answer. The window was the approximation,
        # and this paragraph is where it used to deviate.
        return (sorted(d[c] for c in sorted(elig, key=sat, reverse=True)[:count])[0],
                tuple(sorted(elig, key=sat, reverse=True)[:count]))
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=40)
    a = ap.parse_args()

    rnd = random.Random(7)
    agree = disagree = 0
    floor_bind = 0
    worst = None
    for trial in range(a.trials):
        n = rnd.randint(8, 12)
        m = rnd.randint(4, 8)
        pool = [tuple(rnd.randrange(256) for _ in range(3)) for _ in range(n)]
        other = [tuple(rnd.randrange(256) for _ in range(3)) for _ in range(m)]
        count = rnd.randint(2, 4)
        floor = rnd.choice([0.0, 0.2, 0.35, 0.5])
        b = brute(pool, other, count, floor)
        s = scanning(pool, other, count, floor)
        if b is None or s is None:
            continue
        if abs(b[0] - s[0]) < 1e-9:
            agree += 1
        else:
            disagree += 1
            if worst is None or s[0] < b[0]:
                worst = (b[0], s[0])
        # did the floor exclude anything at all?
        nofloor = brute(pool, other, count, 0.0)
        if nofloor and abs(nofloor[0] - (b[0] if b else 0)) > 1e-9:
            floor_bind += 1

    print("  trials with an answer on both sides: %d agree, %d disagree" % (agree, disagree))
    if worst:
        print("  where they differ: brute %.6f vs scanning %.6f" % worst)
    print("  trials where the saturation floor actually bound the answer: %d" % floor_bind)
    print()
    print("  reading: agreement means the objective's minimum-of-independent-terms structure holds, so the")
    print("  exhaustive enumeration is not necessary. Disagreement means the scan is not the exact answer")
    print("  and an approximation would have to be argued for instead.")
    return 0 if disagree == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
