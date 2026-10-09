# -*- coding: utf-8 -*-
"""Deterministic measurements of a pixel-art image.

**What this module is for.** It is the half of a generate-judge-refine loop that does not need a model.
Most of what makes pixel art read as pixel art is countable from the pixels themselves, and a countable
answer is faster, explainable and does not drift. Only judgements like "is this face appealing" need a
learned model, and that is a small part of the whole.

**Every metric here was checked against a sprite that is known to be good** -- a frame from a 2008
commercial fighting game, decoded from its own archive. Two of the metrics that seemed obvious had to
be inverted once that was done, and both corrections are recorded next to the code that carries them,
because a measurement that has never been pointed at a known-good sample is a guess with a number
attached.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from math import gcd
from functools import reduce

from . import calibration

__all__ = ["Report", "judge", "load_rgba"]


def load_rgba(image):
    """Accept a path or an already-open image, and always return RGBA."""
    from PIL import Image

    if isinstance(image, (str, bytes)):
        image = Image.open(image)
    return image.convert("RGBA")


def _opaque(im):
    px = im.load()
    w, h = im.size
    return [(x, y) for y in range(h) for x in range(w) if px[x, y][3] > 0]


def _run_gcd(im, coords):
    """The largest n such that every horizontal run of one colour is a multiple of n.

    **The direction in the sentence that used to be here was backwards**, and it matters: an
    *upscaled* image keeps run lengths in multiples of the scale (one source pixel becomes an n x n
    block), while a *downscaled* one has its blocks broken up and does not. Measured, 18/18 clean
    integer upscales of real sprites read their factor.

    **But 1 does not mean "unit scale confirmed".** Runs of 1 are filtered out below, so a drawing
    made entirely of single pixels has no GCD to take and returns 0; real hand-authored art has runs
    of many different lengths and returns 1. And one miscoloured pixel anywhere in an upscale drops
    it back to 1 -- 16 of 18 measured cases. So:

        clean upscale              -> n
        upscale with one bad pixel -> 1      (indistinguishable from hand-authored art)
        all-single-pixel drawing   -> 0

    A value that is not a divisor of a clean scale is a signal, not a score; but a 1 is not proof of
    anything, and `cli.py`'s parenthetical must not be read as if it were.
    """
    px = im.load()
    w, h = im.size
    runs = []
    for y in range(h):
        run = 1
        for x in range(1, w):
            if px[x, y] == px[x - 1, y]:
                run += 1
            else:
                runs.append(run)
                run = 1
        runs.append(run)
    return reduce(gcd, [r for r in runs if r > 1], 0)


def _isolated(im, coords):
    """Opaque pixels whose opaque four-neighbours are all a different colour.

    **This was the first metric to be corrected.** The absolute count is misleading: a good 72x113
    sprite had 260 of them against 47 in a 32x32 attempt, which reads as the good sprite being worse.
    Scaled to a rate it is 3.2% against 10% -- the good sprite is three times cleaner. So the report
    carries `isolated_rate` and treats the raw count as diagnostic only.
    """
    px = im.load()
    w, h = im.size
    n = 0
    for x, y in coords:
        c = px[x, y]
        seen = False
        same = False
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            a, b = x + dx, y + dy
            if not (0 <= a < w and 0 <= b < h):
                continue
            if px[a, b][3] == 0:
                continue
            seen = True
            if px[a, b] == c:
                same = True
                break
        if seen and not same:
            n += 1
    return n


def _clusters(im, coords):
    """Connected components of equal colour, largest first."""
    px = im.load()
    w, h = im.size
    seen = set()
    sizes = []
    for x, y in coords:
        if (x, y) in seen:
            continue
        c = px[x, y]
        stack = [(x, y)]
        seen.add((x, y))
        n = 0
        while stack:
            a, b = stack.pop()
            n += 1
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                p = (a + dx, b + dy)
                if p in seen or not (0 <= p[0] < w and 0 <= p[1] < h):
                    continue
                if px[p[0], p[1]] == c:
                    seen.add(p)
                    stack.append(p)
        sizes.append(n)
    sizes.sort(reverse=True)
    return sizes


def _outline(im, coords):
    """How much the outline changes with what it borders.

    **This was the second metric to be corrected, and it was inverted.** The obvious reading is
    "an outline of one consistent colour is disciplined". Pointed at a known-good sprite it returned
    0.338 against 0.991 for a hand attempt -- and the good sprite is right. Commercial pixel art
    varies its outline with the local colour, so hair gets a cool outline and cloth a warm one; a
    single flat outline is the beginner's move.

    So this returns the *variation*: the share of border pixels whose colour differs from the most
    common border colour. Higher means the outline is doing more work. A flat outline scores near 0.
    """
    px = im.load()
    w, h = im.size
    border = []
    for x, y in coords:
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            a, b = x + dx, y + dy
            if not (0 <= a < w and 0 <= b < h) or px[a, b][3] == 0:
                border.append(px[x, y][:3])
                break
    if not border:
        return 0.0, None, 0
    counts = Counter(border)
    most, n_most = counts.most_common(1)[0]
    return round(1 - n_most / len(border), 3), most, len(border)


def _dither(im, coords, w, h):
    """Share of pixels that sit in a checkerboard-ish alternation with a neighbour.

    Dithering is a legitimate technique, so this is reported rather than scored. What it is useful for
    is telling "deliberate dithering" apart from "a smooth gradient that survived the quantiser".
    """
    px = im.load()
    n = 0
    for x, y in coords:
        right = px[x + 1, y] if x + 1 < w else None
        down = px[x, y + 1] if y + 1 < h else None
        c = px[x, y]
        for other in (right, down):
            if other is None or other[3] == 0:
                continue
            if other == c:
                continue
            # A dither neighbour differs but stays close in luminance; a gradient step does too, so
            # the checkerboard condition is the alternation, checked by looking one further along.
            far = px[x + 2, y] if (other is right and x + 2 < w) else (
                px[x, y + 2] if (other is down and y + 2 < h) else None)
            if far is not None and far[3] > 0 and far == c:
                n += 1
                break
    return n


@dataclass
class Report:
    """The measurements, with the size they were taken at so rates can be checked."""

    width: int
    height: int
    opaque: int
    palette_size: int
    pixel_scale: int
    isolated: int
    isolated_rate: float
    clusters: int
    largest_cluster: int
    largest_cluster_rate: float
    median_cluster: float
    outline_variation: float
    outline_color: tuple | None
    border_pixels: int
    dither_pixels: int
    bbox: tuple
    bbox_fill: float
    notes: list = field(default_factory=list)


def judge(image) -> Report:
    """Measure one image. Deterministic: the same bytes always give the same report."""
    im = load_rgba(image)
    w, h = im.size
    coords = _opaque(im)
    px = im.load()

    colours = Counter(px[x, y][:3] for x, y in coords)
    sizes = _clusters(im, coords)
    iso = _isolated(im, coords)
    var, ocol, nborder = _outline(im, coords)
    dith = _dither(im, coords, w, h)

    if coords:
        l = min(p[0] for p in coords)
        r = max(p[0] for p in coords)
        t = min(p[1] for p in coords)
        b = max(p[1] for p in coords)
        bbox = (r - l + 1, b - t + 1)
        fill = round(len(coords) / (bbox[0] * bbox[1]), 3)
    else:
        bbox, fill = (0, 0), 0.0

    n = max(1, len(coords))
    median_cluster = sorted(sizes)[len(sizes) // 2] if sizes else 0
    notes = []

    # **Is this a sprite at all?** The metrics assume a subject on transparency, cropped to itself.
    # Pointed at a full-canvas opaque image -- a frame exported from an animation, a screenshot -- they
    # do not measure the art, they measure the convention: bounding-box fill reads 1.000 and outline
    # variation reads 0.000 whatever is drawn. Both then raise notes that are simply false.
    #
    # Measured on 40 frames of a pixel-art animation: raw, the two metrics gave exactly those values
    # and 40 of 40 frames were flagged. After the background was made transparent and each frame
    # cropped to its subject, the same frames measured 0.642 and 0.564 -- inside the reference range,
    # and the two corpora became comparable at all. **The notes had been about the export.**
    rendered_frame = bool(coords) and len(coords) == w * h and fill > 0.98 and var == 0.0

    if not coords:
        notes.append("the image is fully transparent")
    elif rendered_frame:
        notes.append(
            "every pixel is opaque and one colour fills the frame, so this reads as a rendered frame "
            "rather than a sprite; bounding-box fill and outline variation cannot be measured on it, "
            "and any note they would raise is about the export rather than the drawing. Make the "
            "background transparent and crop to the subject, then measure again.")
    else:
        # Thresholds come from `calibration`, which holds measured percentiles from 120 real sprites.
        # They used to be chosen by feel, and one of them was wrong by a factor of two: "isolated
        # pixels above 5%" sat *below the fifth percentile* of known-good art and fired on nearly
        # every real sprite. **A report that fires on good work is a report that gets ignored.**
        # At most the two furthest-out metrics. Even with the margin, listing every qualifying one
        # turns the report into a wall of text that gets skimmed, and the point of the margin was to
        # make a note mean something.
        found = []
        for metric, value in (("isolated_rate", iso / n),
                              ("bbox_fill", fill),
                              ("largest_cluster_rate", (sizes[0] if sizes else 0) / n),
                              ("palette_size", len(colours))):
            msg = calibration.outside(metric, value)
            if msg:
                found.append((calibration.how_far(metric, value), msg))
        found.sort(reverse=True)
        notes.extend(m for _, m in found[:2])

        # Two rules that are not percentile-based, because the reference sample cannot express them:
        # a flat outline is a shape of the distribution rather than an outlying value, and the
        # combination of a high isolated rate with large clusters is what noise looks like -- detail
        # has the same rate but comes with many small clusters.
        if var < 0.3 and nborder > 20:
            notes.append("the outline is nearly one flat colour (variation %.2f against a reference "
                         "median of %.2f); known-good sprites vary it with the local colour"
                         % (var, calibration.REFERENCE["outline_variation"].median))
        if iso and iso / n > 0.05 and median_cluster > 4:
            notes.append("isolated pixels are %.1f%% and the colour clusters are large (median %d "
                         "pixels) -- that combination is stray single pixels or a procedural pattern "
                         "rather than detail" % (100 * iso / n, median_cluster))

    return Report(
        width=w, height=h, opaque=len(coords),
        palette_size=len(colours),
        pixel_scale=_run_gcd(im, coords),
        isolated=iso, isolated_rate=round(iso / n, 4),
        clusters=len(sizes), largest_cluster=sizes[0] if sizes else 0,
        largest_cluster_rate=round((sizes[0] if sizes else 0) / n, 4),
        median_cluster=median_cluster,
        outline_variation=var, outline_color=ocol, border_pixels=nborder,
        dither_pixels=dith,
        bbox=bbox, bbox_fill=fill,
        notes=notes,
    )
