# -*- coding: utf-8 -*-
"""Perceptual colour difference, and the two things that must not be confused.

**A colour-difference metric and a palette-comparison model are different objects**, and the literature
keeps them apart: this module implements the first. (The second -- MECD, MICD, Hungarian assignment --
belongs wherever two palettes are compared, and it is where "asymmetry" actually lives; see
`corpus/REFERENCES.md` section five.)

What is here, and the reason each one is here rather than being borrowed:

- `lab_from_srgb` / `srgb_from_lab` -- because a metric has to start from the bytes in the file.
- `delta_e_2000` -- verified against the 34 pairs published by the formula's authors, which are in
  `test/data/ciede2000testdata.txt` and are the acceptance criterion this function exists to satisfy.
- `hyab` -- the distance `pixelmatch` uses, and the one the sibling project's notes reached for first.
- `oklab_from_srgb` -- a perceptual space that is a **published specification, not a standard**, and the
  documentation must say so. Ottosson's write-up is a blog with the matrices, not a CIE document.
- `oklab_distance` -- Euclidean in Oklab, which is cheap and is what a *lot* of tools actually mean.

Two properties worth stating because they are easy to get wrong in the other direction:

- **CIEDE2000 is symmetric by construction.** Every weighting function uses the mean of the reference
  and the sample, which is the symmetrisation CIE94 introduced. A tool that warns "this metric is
  asymmetric" about CIEDE2000 is warning about the wrong metric.
- **What CIEDE2000 has instead is a discontinuity at 180 degrees of hue opposition** (Sharma, Wu, Dalal
  & Celik 2004): inside 5 delta-E units the error reaches 0.274 and rises sharply beyond, which is why
  it must not be used for very large differences or as a palette-summary score.
"""
from __future__ import annotations

import math

__all__ = [
    "lab_from_srgb", "srgb_from_lab", "delta_e_2000", "hyab",
    "oklab_from_srgb", "oklab_distance", "METRICS", "distance",
    "luma", "intensity_extrema",
]


def _srgb_to_linear(c: float) -> float:
    """The sRGB transfer function, undone. Kept here so the metric starts from real bytes."""
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(c: float) -> float:
    c = max(0.0, min(1.0, c))
    v = c * 12.92 if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055
    return v * 255.0


# D65, the white point sRGB is defined against
_Xn, _Yn, _Zn = 0.95047, 1.0, 1.08883


def lab_from_srgb(colour) -> tuple:
    """CIELAB from an RGB(A) tuple. Alpha is ignored: it is not a colour."""
    r, g, b = (_srgb_to_linear(colour[i]) for i in range(3))
    x = r * 0.4124564 + g * 0.3575761 + b * 0.1804375
    y = r * 0.2126729 + g * 0.7151522 + b * 0.0721750
    z = r * 0.0193339 + g * 0.1191920 + b * 0.9503041

    def f(t):
        return t ** (1 / 3) if t > 216 / 24389 else (841 / 108) * t + 4 / 29

    fx, fy, fz = f(x / _Xn), f(y / _Yn), f(z / _Zn)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def srgb_from_lab(lab) -> tuple:
    """The inverse, so a converted palette can be written back and compared byte for byte."""
    L, a, b = lab

    def finv(t):
        return t ** 3 if t ** 3 > 216 / 24389 else (t - 4 / 29) * (108 / 841)

    fy = (L + 16) / 116
    fx = fy + a / 500
    fz = fy - b / 200
    x, y, z = finv(fx) * _Xn, finv(fy) * _Yn, finv(fz) * _Zn
    r = x * 3.2404542 + y * -1.5371385 + z * -0.4985314
    g = x * -0.9692660 + y * 1.8760108 + z * 0.0415560
    bb = x * 0.0556434 + y * -0.2040259 + z * 1.0572252
    return tuple(int(round(_linear_to_srgb(v))) for v in (r, g, bb))


def delta_e_2000(lab1, lab2, kL: float = 1.0, kC: float = 1.0, kH: float = 1.0) -> float:
    """CIEDE2000. Verified against the authors' 34 published pairs, not against a memory of the formula.

    The three-argument form is deliberate: the parametric weights kL, kC, kH belong to the *textile*
    variant (kL=2) and leaving them at 1 is the reference form. Passing them is allowed; changing the
    default would silently answer a different question.
    """
    L1, a1, b1 = lab1
    L2, a2, b2 = lab2
    C1 = math.hypot(a1, b1)
    C2 = math.hypot(a2, b2)
    Cbar = (C1 + C2) / 2.0
    Cbar7 = Cbar ** 7
    G = 0.5 * (1 - math.sqrt(Cbar7 / (Cbar7 + 25 ** 7)))
    a1p = (1 + G) * a1
    a2p = (1 + G) * a2
    C1p = math.hypot(a1p, b1)
    C2p = math.hypot(a2p, b2)

    def hp(ap, bp):
        if ap == 0 and bp == 0:
            return 0.0
        h = math.degrees(math.atan2(bp, ap))
        return h + 360 if h < 0 else h

    h1p, h2p = hp(a1p, b1), hp(a2p, b2)
    dLp = L2 - L1
    dCp = C2p - C1p
    if C1p * C2p == 0:
        dhp = 0.0
    else:
        dhp = h2p - h1p
        if dhp > 180:
            dhp -= 360
        elif dhp < -180:
            dhp += 360
    dHp = 2 * math.sqrt(C1p * C2p) * math.sin(math.radians(dhp) / 2)

    Lbarp = (L1 + L2) / 2
    Cbarp = (C1p + C2p) / 2
    if C1p * C2p == 0:
        hbarp = h1p + h2p
    else:
        hbarp = (h1p + h2p) / 2
        if abs(h1p - h2p) > 180:
            hbarp += 180 if h1p + h2p < 360 else -180

    T = (1 - 0.17 * math.cos(math.radians(hbarp - 30))
         + 0.24 * math.cos(math.radians(2 * hbarp))
         + 0.32 * math.cos(math.radians(3 * hbarp + 6))
         - 0.20 * math.cos(math.radians(4 * hbarp - 63)))
    dtheta = 30 * math.exp(-(((hbarp - 275) / 25) ** 2))
    Cbarp7 = Cbarp ** 7
    RC = 2 * math.sqrt(Cbarp7 / (Cbarp7 + 25 ** 7))
    SL = 1 + (0.015 * (Lbarp - 50) ** 2) / math.sqrt(20 + (Lbarp - 50) ** 2)
    SC = 1 + 0.045 * Cbarp
    SH = 1 + 0.015 * Cbarp * T
    RT = -math.sin(math.radians(2 * dtheta)) * RC
    return math.sqrt((dLp / (kL * SL)) ** 2
                     + (dCp / (kC * SC)) ** 2
                     + (dHp / (kH * SH)) ** 2
                     + RT * (dCp / (kC * SC)) * (dHp / (kH * SH)))


def hyab(lab1, lab2) -> float:
    """HyAB: Euclidean across hue and chroma, **city-block for lightness**.

    That asymmetry in the formula is the whole point of it -- lightness differences of a given size are
    judged larger than the same distance spent in chroma -- and it is the distance `pixelmatch` uses.
    Recording the shape matters because "Euclidean in Lab" is a different metric and would be a
    different answer under the same name.
    """
    dL = abs(lab1[0] - lab2[0])
    da = lab1[1] - lab2[1]
    db = lab1[2] - lab2[2]
    return dL + math.hypot(da, db)


# Oklab's matrices, from Ottosson's published specification. Written out rather than derived, because
# the specification *is* these numbers and any rederivation is a different space.
_OKL_M1 = (
    (0.4122214708, 0.5363325363, 0.0514459929),
    (0.2119034982, 0.6806995451, 0.1073969566),
    (0.0883024619, 0.2817188376, 0.6299787005),
)
_OKL_M2 = (
    (0.2104542553, 0.7936177850, -0.0040720468),
    (1.9779984951, -2.4285922050, 0.4505937099),
    (0.0259040371, 0.7827717662, -0.8086757660),
)


def oklab_from_srgb(colour) -> tuple:
    """Oklab. **A published specification, not a standard** -- say so wherever it is cited."""
    r, g, b = (_srgb_to_linear(colour[i]) for i in range(3))
    lms = [m[0] * r + m[1] * g + m[2] * b for m in _OKL_M1]
    lms = [v ** (1 / 3) if v >= 0 else -((-v) ** (1 / 3)) for v in lms]
    return tuple(m[0] * lms[0] + m[1] * lms[1] + m[2] * lms[2] for m in _OKL_M2)


def oklab_distance(c1, c2) -> float:
    """Euclidean in Oklab, taking RGB(A) tuples directly -- the convenience form."""
    a, b = oklab_from_srgb(c1), oklab_from_srgb(c2)
    return math.dist(a, b)


#: The named metrics, so a caller can select one and the report can say which was used. A metric that
#: is not named in the output is a metric the reader has to guess at, and guessing is what this project
#: keeps having to undo.
METRICS = {
    "ciede2000": lambda c1, c2: delta_e_2000(lab_from_srgb(c1), lab_from_srgb(c2)),
    "hyab": lambda c1, c2: hyab(lab_from_srgb(c1), lab_from_srgb(c2)),
    "oklab": oklab_distance,
    "cie76": lambda c1, c2: math.dist(lab_from_srgb(c1), lab_from_srgb(c2)),
}


def distance(c1, c2, metric: str = "ciede2000") -> float:
    """A colour difference by name. Raising on an unknown name is deliberate: a silent fallback would
    make two runs disagree about what they measured under the same label."""
    try:
        fn = METRICS[metric]
    except KeyError:
        raise ValueError("unknown colour metric %r; known: %s"
                         % (metric, ", ".join(sorted(METRICS)))) from None
    return fn(c1, c2)


def luma(colour) -> float:
    """Rec.601 intensity. Named because the choice changes which pixels a slope test selects."""
    return 0.299 * colour[0] + 0.587 * colour[1] + 0.114 * colour[2]


def intensity_extrema(im, *, max_zeros: int = 2, alpha: bool = True):
    """The intensity-slope **sign test** of Vysniauskas 2009 -- which does NOT measure anti-aliasing.

    **The name says what it measures, and the name was changed after measuring.** The published rule is:
    for each pixel, compare its intensity with the eight neighbours in a 3x3 block; the pixel qualifies
    when those differences contain both signs and no more than `max_zeros` of them are zero. The paper
    presents it as an anti-aliased-pixel detector, and on pixel art **that is not what it detects**.

    Four measurements, each isolating one claim (`tools/probe_aa_sign.py`, `probe_aa_sign_isolate.py`):

        pure flat field                         0.00% of opaque pixels marked
        flat field + rounding residue of 1     15.80%    <- fires hard with no slope present
        1-unit stair, period 8                  0.00%    <- and ignores a real faint slope entirely
        2-unit stair, period 8                  0.00%
        a real 2-per-pixel gradient            95.83%

    So it responds to **local extrema** -- peaks and dips in the brightness terrain -- and not to slopes.
    A one-unit stair is monotone along its run, so the pixel at a step is neither a peak nor a dip and the
    rule stays silent; and an anti-aliased edge is exactly that kind of monotone slope. What it does fire
    on is the intermediate values a resampler inserts, because those create reversals: bilinearly
    resampling twelve real sprites raises the rate from a median of 1.8% to 70.2%, a factor of 8.6.

    **That rise is real information and this function keeps it** -- "was this resampled" is a question
    worth asking, and `judge.py` already answers a related one under `periodic_class`. What it must not be
    used for is the label it arrived with. And the failure is not the one the abandoned probe hit:
    per-pixel or not, this rule does **not** confuse an outline with a smoothing layer -- splitting the
    corpus by how many colours the outer edge uses gives a median rate of 0.0813 against 0.0814, the same
    number on both sides.

    Transparent neighbours are skipped rather than treated as zero intensity, because a background is not
    a brightness; counting it would make every silhouette pixel a slope pixel by construction.
    """
    px = im.load()
    w, h = im.size
    marked = set()
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            c = px[x, y]
            if alpha and c[3] == 0:
                continue
            ci = luma(c)
            pos = neg = zero = 0
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    n = px[x + dx, y + dy]
                    if alpha and n[3] == 0:
                        continue
                    d = luma(n) - ci
                    if d > 0:
                        pos += 1
                    elif d < 0:
                        neg += 1
                    else:
                        zero += 1
            if pos and neg and zero <= max_zeros:
                marked.add((x, y))
    return marked
