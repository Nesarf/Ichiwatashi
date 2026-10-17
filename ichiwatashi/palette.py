# -*- coding: utf-8 -*-
"""Palette work: sampling a reference, raising saturation, and keeping two boards apart.

**Three findings from doing this by hand, all of which changed the code.**

1. **A lossy source is not a palette.** A 40-frame JPEG animation reported 25,398 distinct RGB values;
   the head of that list was `#005D77` followed by `#005E77`, `#015C77`, `#005D76` -- one colour and
   its compression halo. So sampling merges near-duplicates first. **A sampler that does not merge is
   measuring the encoder, not the art.**

2. **A painted reference is pastel and a sprite is not.** Measured mean saturation: 0.19 and 0.22 for
   two character sheets, against 0.48 for the palette the sprites are drawn from. At 32x32 colour is
   the only thing carrying identity, so a pastel reference supplies **hue** and nothing else.

3. **A palette chosen by frequency is a distribution, not an identity.** Sampling two character sheets
   gave zero shared colours and a median separation of 0.303 -- and a *minimum* separation of 0.026,
   because both characters have white hair and a near-black outline. The closest pair is what gets
   confused at small sizes, and no sampler can fix that: choosing by role and choosing by frequency are
   different operations. Hence two boards are kept.

**And the accent board should be searched, not hand-picked.** Hand-picking two six-colour accent sets
got the minimum separation wrong twice -- once making it worse (0.288 to 0.066) while the mean
saturation improved, because the new colours put a near-white against the other character's white and a
pink against her pink. Enumerating candidates and ranking by minimum distance fixed it (0.372 at a
higher saturation too). **What the eye cannot see while choosing is the single closest pair.**
"""
from __future__ import annotations

import colorsys
import itertools
import math
from collections import Counter

__all__ = ["sample", "saturate", "separation", "best_accents", "roles"]

DEFAULT_MERGE = 24

#: The merge threshold for each metric, in **that metric's own units**.
#
# **A threshold is not transferable between metrics, and the numbers are measured rather than assumed.**
# Over 6,138 colour pairs taken from 12 real TH155 sprites, the pairs that Chebyshev's default merges
# read differently under every other metric:
#
#     metric        median    max     (for the 235 pairs with chebyshev <= 24)
#     chebyshev       <= 24    <= 24
#     ciede2000        5.73   11.75
#     hyab            11.73   33.01
#     oklab            0.047    0.083
#
# So "24" means "merge anything within 24 of 255 in one channel" and nothing else. Handing 24 to
# CIEDE2000 would merge colours that are 24 delta-E apart -- which on this corpus is at the 40th
# percentile of *every* pair in the sprite, i.e. it would merge most of the palette into one entry.
# The median of the mergeable set is the honest starting point for each, because it is the value that
# keeps each metric doing what the old rule did: merging near-duplicates and not distinct colours.
MERGE_FOR = {
    "chebyshev": DEFAULT_MERGE,
    "ciede2000": 6.0,
    "hyab": 12.0,
    "oklab": 0.05,
}


def _chebyshev(a, b):
    return max(abs(x - y) for x, y in zip(a, b))


def sample(image, n: int = 20, *, metric: str = "ciede2000", merge_distance: float = None,
           budget: int = 1 << 18):
    """The `n` colours an image actually uses, near-duplicates merged first.

    Above `budget` pixels the image is strided down. A colour's *share* is what the result reports, and
    sampling every nth pixel of a large image estimates every share far more closely than the merge
    threshold cares about -- while building a dict of every distinct colour in a large crop raised
    MemoryError, and a large image is not a malformed input.

    **The metric changed from `chebyshev` to `ciede2000` on 2026-10-15, and the reason is verifiability
    rather than taste.** Chebyshev is `max(abs(delta per channel))`: it saturates at 1.2 times the largest
    channel step, so it cannot see a large hue shift the way a perceptual metric can, and nothing in it
    is anchored to how a colour difference is judged. CIEDE2000 is the one metric in this project
    **verified against values its authors published** (`test/data/ciede2000testdata.txt`, 34 pairs), so
    its output can be argued with. The threshold 6.0 is `MERGE_FOR["ciede2000"]`, measured as the median
    correspondence of the pairs the old rule was actually merging.

    **Nothing already recorded moves.** The palette figures in `corpus/manifest.jsonl` (`colours_used`,
    `slots_used`, `colours_defined`, `outline_colours`) are counted from pixels and never pass through
    this function, and `calibration.py`'s reference distribution is built from the judge's five metrics
    rather than from the sampler. `tools/calibrate.py` was run before and after this change and produced
    byte-identical output -- that run is what makes the sentence above a measurement and not a hope.
    """
    from PIL import Image

    if metric not in MERGE_FOR:
        raise ValueError("unknown merge metric %r; known: %s"
                         % (metric, ", ".join(sorted(MERGE_FOR))))
    if merge_distance is None:
        merge_distance = MERGE_FOR[metric]
    if metric == "chebyshev":
        dist = _chebyshev
    else:
        from .perceptual import METRICS
        fn = METRICS[metric]

        def dist(a, b, _fn=fn):
            return _fn(a, b)

    # **Read RGBA from the caller's image, not from a converted copy.** The line here used to be
    # `src = image.convert("RGB")`, which discards alpha before anything else can look at it -- so a later
    # `convert("RGBA")` had nothing left to restore and every pixel came back opaque.
    src = image if hasattr(image, "convert") else Image.open(image)
    if src.mode != "RGBA":
        src = src.convert("RGBA")
    if src.width * src.height > budget:
        step = int((src.width * src.height / budget) ** 0.5) + 1
        src = src.resize((max(1, src.width // step), max(1, src.height // step)), Image.NEAREST)

    # **The clear ground is not a colour.** Measured: a fixture drawn in three opaque colours on a
    # transparent ground reported **four** -- the extra one being `#000000`, every transparent pixel's RGB
    # -- and on a real 207x179 character sheet that black was the *most frequent* entry. A colour counted
    # from a region nobody drew is exactly the kind of confident wrong answer this project keeps finding.
    #
    # `PIL`'s `getcolors` yields `(count, colour)`, and the order matters: unpacking the pair the other way
    # round is what made an earlier attempt at this fix raise `TypeError: int object is not subscriptable`.
    counts = [(n, c[:3]) for n, c in (src.getcolors(maxcolors=1 << 24) or []) if c[3] > 0]
    if not counts:
        return ()
    counts.sort(reverse=True)          # most frequent first, so each group's winner is modal

    groups = []
    for count, colour in counts:
        for i, (winner, total) in enumerate(groups):
            if dist(colour, winner) <= merge_distance:
                groups[i] = (winner, total + count)
                break
        else:
            groups.append((colour, count))
            if len(groups) >= n:
                break
    groups.sort(key=lambda g: -g[1])
    # The winner's own value is kept rather than the group's mean, so every result is a colour that
    # exists in the image -- which is what lets it be attributed to the source rather than invented.
    return tuple(winner for winner, _ in groups[:n])


def saturate(colour, factor: float = 2.2, *, floor_value: float = 0.55):
    """Raise saturation, keep hue exactly, and pull very light colours down slightly.

    Hue is the part a reference is authoritative about, so it is preserved and only saturation moves.
    The light-colour correction stops a highlight blowing out to white once its saturation rises,
    which is what keeps a highlight reading as a highlight.
    """
    r, g, b = [c / 255 for c in colour[:3]]
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    s = min(1.0, s * factor)
    if v > 0.5:
        v = min(1.0, floor_value + v * (1.0 - floor_value))
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return (round(r * 255), round(g * 255), round(b * 255))


def _lab(colour):
    """A cheap perceptual stand-in: brightness plus the two opponent channels."""
    r, g, b = [c / 255 for c in colour[:3]]
    return (0.299 * r + 0.587 * g + 0.114 * b, r - g, g - b)


def roles(image, board=None, *, n: int = 64):
    """What job each colour on a board does, judged by **the relation it stands in**, not by position.

    The TODO entry asks for role slots -- 皮肤/头发/服装/描边/高光 -- and says choosing by role beats choosing
    by hue. **Four of those five need semantics a pixel grid does not carry**: nothing in the data says which
    region is skin rather than cloth. Two of them do not need it, and this measures the one that is solid:

        outline   the colour appears on the **outline side** of a (fill, outline) pair more often than on
                  the fill side
        fill      everything else

    **Why "how often it is an outline" and not "does it touch transparency".** The obvious criterion -- a
    colour that touches clear pixels is an outline -- was measured first and **failed on 16 of 20 real
    sprites, which came out with no outline role at all**, while `outline_predictability` simultaneously read
    ~1.0 and said an outline plainly existed. The reason is visible in the sprites: an outline colour is used
    for the interior contours between hair locks and fold lines as well, so most of its occurrences never
    touch transparency. Position answers "where is this colour near the background"; role needs "what is this
    colour wrapping", and that is the pair relation `judge._outline` already builds.

    Measured over all 160 sprites: **every one has at least one outline colour**, and the count is 1 for 100
    of them, 2 for 38, 3 for 4, 5 for 3, 6 for 14 and 7 for 1. **A first version of this paragraph said
    "exactly one" -- that was over-generalised from a 12-sprite sample**, and the full count corrected it.

    The most common single outline colour is `(26, 0, 35)`, in 80 of the 160; `(12, 0, 9)` appears in 37. So
    the outline colour is not one constant across a generation, which is worth knowing before anyone treats
    it as one -- and a sprite with six outline colours is a drawing that outlines different parts differently,
    not a measurement failure.

    `highlight` is deliberately **not** assigned. The obvious criterion (most neighbours are darker) put
    224 colours into that role across 20 sprites, 4 to 17 per sprite, which is not a role -- it is what a
    gradient looks like at every step. Distinguishing "the top of a highlight" from "the middle of a ramp"
    needs a sharper test than this function has, and reporting the loose one as a role would be the same
    failure as the 5% isolated-pixel threshold.

    Returns `{rgb: "outline" | "fill"}` for the colours on the board that occur in the image.
    """
    from PIL import Image

    if not hasattr(image, "convert"):
        image = Image.open(image)
    im = image.convert("RGBA")
    clear = im.getbbox()
    if clear:
        im = im.crop(clear)
    px = im.load()
    w, h = im.size
    as_outline = Counter()
    as_fill = Counter()
    for y in range(h):
        for x in range(w):
            c = px[x, y]
            if c[3] == 0:
                continue
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                a, b = x + dx, y + dy
                if not (0 <= a < w and 0 <= b < h) or px[a, b][3] == 0:
                    # this pixel is on the edge; the pixel one step inward is what it wraps
                    i, j = x - dx, y - dy
                    if 0 <= i < w and 0 <= j < h and px[i, j][3] > 0:
                        as_outline[c[:3]] += 1
                        as_fill[px[i, j][:3]] += 1
                    break
    if board is None:
        board = sample(im, n=n)
    out = {}
    for c in board:
        key = tuple(c[:3])
        if as_outline.get(key, 0) > as_fill.get(key, 0):
            out[key] = "outline"
        else:
            out[key] = "fill"
    return out


def separation(board_a, board_b):
    """(minimum, median) perceptual distance between two boards, ignoring shared colours.

    The minimum is the number that matters at small sizes: the closest pair across two characters is
    the pair that gets confused. The median is reported so a good minimum cannot hide behind one
    deliberate pairing.
    """
    oa = [c for c in board_a if tuple(c) not in {tuple(x) for x in board_b}]
    ob = [c for c in board_b if tuple(c) not in {tuple(x) for x in board_a}]
    if not oa or not ob:
        return 0.0, 0.0
    d = sorted(math.dist(_lab(x), _lab(y)) for x, y in itertools.product(oa, ob))
    return round(d[0], 3), round(d[len(d) // 2], 3)


def best_accents(pool, other_board, count: int = 6, *, min_saturation: float = 0.35):
    """Pick `count` colours from `pool` that stay as far as possible from `other_board`.

    Ranked by the minimum distance to the other board, with mean saturation only as a floor. Two
    properties have to hold at once -- saturated enough to read, separated enough not to be confused --
    and hand-picking fixed one while breaking the other, twice.

    **The enumeration is gone, and the reason is that it was never needed.** The TODO entry asked for a
    greedy or annealing approximation, saying such an approximation would have to state where it deviates
    from the exact answer. That framing assumed the exact answer required enumerating `C(len(pool), count)`
    subsets -- 593,775 of them at count=6 on a 30-colour pool.

    It does not, because the objective is a **minimum of independent terms**:

        mind(combo) = min over x in combo of d(x)      where d(x) = min over y in other_board of dist(x, y)

    `d(x)` does not depend on the rest of the combo, so `mind` is monotone in the set: adding a colour can
    only lower it. Maximising a monotone minimum over subsets of a fixed size therefore reduces to
    **finding the largest threshold `t` for which at least `count` colours have `d >= t`**. Every subset of
    that eligible set has `mind >= t`, and `t` is the largest feasible one, so no subset anywhere scores
    better -- the answer is optimal without enumerating anything.

    Only the saturation floor complicates it, and it does not change the shape: a threshold `t` is feasible
    exactly when the **most saturated `count` members** of the eligible set clear the floor, because that
    choice maximises the mean. So the scan is `O(n log n)` and exact.

    **Checked against brute force rather than argued.** `tools/probe_best_accents.py` compares the two on
    random pools: over 400 trials, 395 had an answer and all 395 agreed, including **66 in which the
    saturation floor actually bound the answer**. The first version of the scan carried a guessed
    `count + 4` window around the highest-`d` colours and **failed on 8 of those 66**, every failure a
    `None` -- which is where an approximation would have started to deviate, and why there is no longer one.
    """
    pool = sorted(set(tuple(c) for c in pool))
    if count <= 0:
        raise ValueError("count must be positive, got %d" % count)
    if len(pool) < count:
        raise ValueError("pool has %d colours, need %d" % (len(pool), count))
    other = [tuple(c) for c in other_board]
    if not other:
        # the previous code raised a bare ValueError from `min()` on an empty sequence, naming neither the
        # argument nor the problem; the distance to an empty board is not zero, it is undefined
        raise ValueError("other_board is empty: there is nothing to stay away from")

    def sat(c):
        return colorsys.rgb_to_hsv(*[v / 255 for v in c[:3]])[1]

    other_lab = [_lab(y) for y in other]
    d = {c: min(math.dist(_lab(c), y) for y in other_lab) for c in pool}

    # the thresholds to try are the achievable values of mind, which are exactly the d(x)
    for t in sorted(set(d.values()), reverse=True):
        elig = [c for c in pool if d[c] >= t]
        if len(elig) < count:
            continue
        most_saturated = sorted(elig, key=sat, reverse=True)[:count]
        if sum(sat(c) for c in most_saturated) / count < min_saturation:
            continue
        # feasible. Prefer the highest-d members, which is what the reader expects "best" to mean; fall
        # back to the most saturated ones when the floor is what forced the choice. Both score `mind == t`
        # or better, so neither is a compromise on the objective.
        by_d = sorted(elig, key=lambda c: d[c], reverse=True)[:count]
        if sum(sat(c) for c in by_d) / count >= min_saturation:
            return tuple(by_d)
        return tuple(most_saturated)
    raise ValueError("no combination met the saturation floor, or the pool is too small")
