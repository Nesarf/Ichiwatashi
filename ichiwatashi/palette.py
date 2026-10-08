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

__all__ = ["sample", "saturate", "separation", "best_accents"]

DEFAULT_MERGE = 24


def _chebyshev(a, b):
    return max(abs(x - y) for x, y in zip(a, b))


def sample(image, n: int = 20, *, merge_distance: int = DEFAULT_MERGE, budget: int = 1 << 18):
    """The `n` colours an image actually uses, near-duplicates merged first.

    Above `budget` pixels the image is strided down. A colour's *share* is what the result reports, and
    sampling every nth pixel of a large image estimates every share far more closely than the merge
    threshold cares about -- while building a dict of every distinct colour in a large crop raised
    MemoryError, and a large image is not a malformed input.
    """
    from PIL import Image

    src = image.convert("RGB") if not hasattr(image, "convert") else image.convert("RGB")
    if src.width * src.height > budget:
        step = int((src.width * src.height / budget) ** 0.5) + 1
        src = src.resize((max(1, src.width // step), max(1, src.height // step)), Image.NEAREST)

    counts = src.getcolors(maxcolors=1 << 24) or []
    counts.sort(reverse=True)          # most frequent first, so each group's winner is modal

    groups = []
    for count, colour in counts:
        for i, (winner, total) in enumerate(groups):
            if _chebyshev(colour, winner) <= merge_distance:
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
    and hand-picking fixed one while breaking the other, twice. Enumerating and ranking is what makes
    the closest pair visible, because the closest pair is exactly what a person choosing cannot see.
    """
    pool = sorted(set(tuple(c) for c in pool))
    if len(pool) < count:
        raise ValueError("pool has %d colours, need %d" % (len(pool), count))

    def sat(c):
        return colorsys.rgb_to_hsv(*[v / 255 for v in c[:3]])[1]

    best = None
    for combo in itertools.combinations(pool, count):
        if sum(sat(c) for c in combo) / count < min_saturation:
            continue
        mind = min(math.dist(_lab(x), _lab(y))
                   for x, y in itertools.product(combo, other_board))
        if best is None or mind > best[0]:
            best = (mind, combo)
    if best is None:
        raise ValueError("no combination met the saturation floor, or the pool is too small")
    return best[1]
