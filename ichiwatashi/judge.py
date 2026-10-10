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

from collections import Counter, defaultdict
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


@dataclass(frozen=True)
class RunStats:
    """What the horizontal runs say about the drawing's unit size.

    **The GCD alone cannot carry this, and both reasons are measured.**

    First, it degrades silently. One miscoloured pixel in an integer upscale splits runs, and the
    GCD is taken over every run, so the reading can collapse -- but only sometimes:

        n=2,3     gcd unchanged      (runs of 1 are filtered out of the GCD, so a split
        n=4,6,8   gcd -> 2            inside a 3-wide block leaves nothing for it to see)
        n=5,7     gcd -> 1

    On real sprites, 16 of 18 clean upscales dropped to 1 after a single touched-up pixel. So a
    `pixel_scale` of 1 means "no factor detected", never "unit scale confirmed", and it cannot be
    printed as if the two were the same.

    Second, "every run is a multiple of n" is satisfied by *any* drawing whose runs are all equal --
    which is what a cropped single-colour mask is. Measured over 300 real TH155 sprites, that
    detector flagged 59 as upscaled and **all 59 were single-colour**, while all 241 real
    multi-colour sprites had a modal run length of exactly 1. Hence two rules, both required:

        the drawing must use more than one colour (otherwise it is a mask, not a drawing)
        the modal run length must exceed 1        (measured: 1 for all 241 real sprites)

    With both, `upscale` reads the true factor on clean upscales (1.00 of runs) and still reads it
    after 20 touched-up pixels (0.997), while naming the disagreement instead of hiding it.
    """

    gcd: int
    longest: int
    modal: int
    runs: int
    upscale: int
    upscale_fraction: float
    not_multiple: int
    colours: int
    opaque: int
    pixels: int

    def hint(self):
        """A sentence about unit size, or None when the runs say nothing worth reporting.

        The count of runs that are *not* multiples is carried rather than derived from the fraction:
        at 6600 runs one straggler rounds to 100%, so a fraction-only sentence reported "100% of the
        runs" for an image with a bad pixel in it -- the sentence overstated its own evidence.
        """
        # **A run-count floor, because a unit-size claim needs runs to average over.**
        # Measured over 300 real TH155 sprites: the fewest runs any of them produced was 192
        # (median 3145). A 32x32 synthetic sprite yields 20-56. Below that floor "every run is a
        # multiple of n" is a statement about a handful of runs and will fire on small blocky
        # drawings that are simply small, so nothing is reported.
        if self.runs < 100 or self.upscale <= 1 or self.upscale_fraction < 0.95:
            return None
        if self.modal <= 1:
            return None
        if self.colours <= 1:
            return ("every run is the same length and the drawing uses one colour, so this is a flat "
                    "mask rather than art -- unit size is not measurable on it")
        pct = 100.0 * self.upscale_fraction
        detail = ("all %d runs" % self.runs if not self.not_multiple else
                  "%d of %d runs (%.1f%%)" % (self.runs - self.not_multiple, self.runs, pct))
        if self.upscale == self.gcd:
            return ("every run is a multiple of %d -- this reads as an integer upscale of that "
                    "factor, not hand-authored art" % self.upscale)
        return ("%s are multiples of %d, so this is an integer upscale of that factor, but the runs "
                "do not all share a common multiple (%d) -- %d run(s) break it, which is what a "
                "touched-up pixel in a scaled image looks like"
                % (detail, self.upscale, self.gcd, self.not_multiple))


def _run_stats(im, coords):
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
        opaque_run = 1 if px[0, y][3] > 0 else 0
        for x in range(1, w):
            if px[x, y] == px[x - 1, y]:
                run += 1
                if px[x, y][3] > 0:
                    opaque_run += 1
            else:
                # Only runs made of drawn pixels count. A transparent margin contributes one huge
                # run per row, which would make every sprite with a margin look scaled.
                if opaque_run:
                    runs.append(opaque_run)
                run = 1
                opaque_run = 1 if px[x, y][3] > 0 else 0
        if opaque_run:
            runs.append(opaque_run)
    if not runs:
        return RunStats(0, 0, 0, 0, 0, 0.0, 0, 0, 0, 0)
    longest = max(runs)
    modal = Counter(runs).most_common(1)[0][0]
    # The largest factor that accounts for nearly every run. Taking the *largest* rather than the
    # best-scoring one matters: 2 always scores at least as high as any even number, so a
    # best-score rule would report 2 for a clean x4.
    upscale, frac = 0, 0.0
    if len(runs) >= 8:
        for n in range(2, 65):
            f = sum(1 for r in runs if r % n == 0) / len(runs)
            if f >= 0.95 and n > upscale:
                upscale, frac = n, f
    notm = sum(1 for r in runs if upscale and r % upscale) if upscale else 0
    # `colours` is measured from the same pixels the runs come from, so the two rules cannot
    # disagree about what was drawn.
    ncol = len({px[x, y] for x, y in coords}) if coords else 0
    return RunStats(reduce(gcd, [r for r in runs if r > 1], 0), longest, modal, len(runs),
                    upscale, frac, notm, ncol, len(coords), w * h)


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
    """Two separate things about the outline, because one number could not carry both.

    **The history here is a correction on top of a correction.** The first version returned the share
    of border pixels differing from the most common border colour, and read it as discipline: flat
    outline good, varied outline sloppy. Pointed at known-good art that was inverted -- commercial
    sprites vary their outline with the local colour. So it was flipped to "higher is more work".
    That reading is still wrong, and this is the measurement that shows it.

    Pointed at 161 real TH155 sprites the median of that number is 0.003, and broken out per
    character it is 0.000 / 0.055 / 0.000 / 0.041 with the count above 0.30 running 3 / 15 / 0 / 1.
    Same generation, same pipeline, same artists. **So it is not measuring a drawing convention at
    all -- it is measuring how many colours that character's palette contains.** Futo has several
    costume colours and scores high; Hijiri is dressed in white and scores exactly 0. A flat outline
    is not a beginner's move in TH155, it is what the palette does.

    And the number cannot do the job it was given, because two different drawings produce the same
    value: a drawing whose outline follows the local colour, and a drawing whose outline pixels are
    random. Measured on the same sprites with the outline rewritten three ways:

        outline style        colours   variation   predictability
        one flat colour            1       0.000            1.000
        varies with the fill      30       0.816            1.000
        random, 6-colour pool      6       0.806            0.256
        random, any colour       880       0.999            0.035

    So this returns both: `variation` (how much the outline changes) and `predictability` (how much
    the fill colour predicts the outline colour). Only the pair distinguishes the three cases, and
    neither is a score -- which one is desirable depends on the art direction, not on the metric.
    """
    px = im.load()
    w, h = im.size
    border = []          # (fill colour, outline colour), for the note
    ocol = []            # outline colours only
    for x, y in coords:
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            a, b = x + dx, y + dy
            if not (0 <= a < w and 0 <= b < h) or px[a, b][3] == 0:
                ocol.append(px[x, y][:3])
                # the inward neighbour is the fill this outline pixel wraps; an outline on the
                # outer edge of a one-pixel shape has none, and contributes variation only
                i, j = x - dx, y - dy
                if 0 <= i < w and 0 <= j < h and px[i, j][3] > 0:
                    border.append((px[i, j][:3], px[x, y][:3]))
                break
    if not ocol:
        return 0.0, None, 0, 0.0, 0
    counts = Counter(ocol)
    most, n_most = counts.most_common(1)[0]
    variation = round(1 - n_most / len(ocol), 3)
    if not border:
        return variation, most, len(ocol), 0.0, 0
    by_fill = defaultdict(Counter)
    for fill, out in border:
        by_fill[fill][out] += 1
    hit = sum(c.most_common(1)[0][1] for c in by_fill.values())
    total = sum(sum(c.values()) for c in by_fill.values())
    return (variation, most, len(ocol), round(hit / total, 3), len(counts))


def outline_style(variation: float, predictability: float, colours: int) -> str:
    """Name the outline's style, or say the evidence is too thin. Thresholds are measured.

    From rewriting the outline of 164 real TH155 sprites three ways and reading both numbers:

        one flat colour           colours  1    variation 0.000   predictability 1.000
        varies with the fill      colours 30    variation 0.820   predictability 0.886
        random 6-colour pool      colours  6    variation 0.806   predictability 0.266

    A flat outline is `variation ~ 0`; "systematic" and "noisy" both sit high on variation and are
    told apart by predictability, 0.886 against 0.266. So the pair separates all three, and neither
    number alone does.

    **This is deliberately not a grade.** Which style is right depends on the art direction: all 161
    real TH155 sprites measured sit at variation ~0 (flat) with predictability ~1.0, and the
    reference generation sits above 0.5. Calling either one better is what made the earlier version
    report a whole generation of correct work as defective.
    """
    if colours < 2:
        return "flat"
    if variation < 0.30:
        return "flat"
    if predictability >= 0.80:
        return "systematic"
    if predictability <= 0.50:
        return "noisy"
    return "mixed"


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
    run_longest: int
    run_modal: int
    upscale: int
    upscale_fraction: float
    isolated: int
    isolated_rate: float
    clusters: int
    largest_cluster: int
    largest_cluster_rate: float
    median_cluster: float
    outline_variation: float
    outline_predictability: float
    outline_colours: int
    outline_color: tuple | None
    border_pixels: int
    dither_pixels: int
    bbox: tuple
    bbox_fill: float
    notes: list = field(default_factory=list)


def judge(image, *, generation: str | None = None) -> Report:
    """Measure one image. Deterministic: the same bytes always give the same report."""
    im = load_rgba(image)
    w, h = im.size
    coords = _opaque(im)
    px = im.load()

    colours = Counter(px[x, y][:3] for x, y in coords)
    sizes = _clusters(im, coords)
    iso = _isolated(im, coords)
    var, ocol, nborder, pred, ncols = _outline(im, coords)
    dith = _dither(im, coords, w, h)
    runs = _run_stats(im, coords)

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

    rh = runs.hint()
    if rh:
        notes.append(rh)
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
        # **Which generation is being measured decides which reference applies.** TH105 and TH123
        # are one population (they agree to three decimals across four characters); TH155 is another,
        # and the same sprite scores 16-37 on palette_size in one and 43 median in the other. Judging
        # the second with the first is what flagged an entire generation of correct work.
        gen = generation or calibration.DEFAULT_GENERATION
        found = []
        for metric, value in (("isolated_rate", iso / n),
                              ("bbox_fill", fill),
                              ("largest_cluster_rate", (sizes[0] if sizes else 0) / n),
                              ("palette_size", len(colours))):
            msg = calibration.outside(metric, value, generation=gen)
            if msg:
                found.append((calibration.how_far(metric, value, generation=gen), msg))
        found.sort(reverse=True)
        notes.extend(m for _, m in found[:2])

        # Two rules that are not percentile-based, because the reference sample cannot express them:
        # a flat outline is a shape of the distribution rather than an outlying value, and the
        # combination of a high isolated rate with large clusters is what noise looks like -- detail
        # has the same rate but comes with many small clusters.
        # **This note used to say the flat outline was a fault, and it fired on 161 of 161 real
        # TH155 sprites.** It read "known-good sprites vary it with the local colour" against a
        # reference median of 0.73 from TH123. Measuring the two generations with the same pipeline:
        # TH123 sits above 0.5, TH155 sits at 0.003 and is entirely flat, and both are correct work.
        # So the note now names the style and prints the evidence instead of grading it -- which is
        # what a measurement is allowed to do when the convention is a property of the era.
        if var >= 0.30 and nborder > 20:
            style = outline_style(var, pred, ncols)
            if style == "noisy":
                notes.append("the outline uses %d colours at %.3f variation, but the fill predicts "
                             "its colour only %.0f%% of the time -- that is close to one outline "
                             "colour per pixel rather than a palette"
                             % (ncols, var, 100 * pred))
        if iso and iso / n > 0.05 and median_cluster > 4:
            notes.append("isolated pixels are %.1f%% and the colour clusters are large (median %d "
                         "pixels) -- that combination is stray single pixels or a procedural pattern "
                         "rather than detail" % (100 * iso / n, median_cluster))

    return Report(
        width=w, height=h, opaque=len(coords),
        palette_size=len(colours),
        pixel_scale=runs.gcd,
        run_longest=runs.longest,
        run_modal=runs.modal,
        upscale=runs.upscale,
        upscale_fraction=runs.upscale_fraction,
        isolated=iso, isolated_rate=round(iso / n, 4),
        clusters=len(sizes), largest_cluster=sizes[0] if sizes else 0,
        largest_cluster_rate=round((sizes[0] if sizes else 0) / n, 4),
        median_cluster=median_cluster,
        outline_variation=var, outline_predictability=pred,
        outline_colours=ncols, outline_color=ocol, border_pixels=nborder,
        dither_pixels=dith,
        bbox=bbox, bbox_fill=fill,
        notes=notes,
    )
