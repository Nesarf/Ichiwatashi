"""What the judge is for, stated as a check rather than a paragraph.

**Why this exists.** A metric applied to something that does not have the property being measured
returns *not applicable*, and there is nothing in the arithmetic that says so. Two documented cases
where that went unnoticed:

  * `silhouette_share` on a single-colour form is 1.000, which reads as "a uniform edge" and means
    nothing -- every pixel of the edge is the same colour by construction. That one is recorded in the
    metric's own docstring.
  * The whole metric set on a 5x7 bitmap font: `colours_used` is 1 against a band of 16-37 and
    `isolated_rate` is 0.000 against 0.074-0.160, so all 58 glyphs of `volcano-separator`'s pixel font
    were flagged as unlike any reference generation. Measured over one corpus, a font and a fighting
    sprite are not the same kind of object, and `tools/probe_font_glyphs.py` is that measurement.

Both are the same failure: **the instrument has a subject and nothing said so.** This module says so.

**The rule is dimensional, and the threshold is measured rather than chosen.** The 160-sprite
reference corpus has a smallest short side of **62 px** (p05 91, median 123); a 5x7 font glyph is
**7 px**. Nothing in the corpus sits anywhere near the gap, so `MIN_SHORT_SIDE = 24` separates them
with room on both sides and does not clip any real drawing in the pool.

**What this deliberately does not do.** It does not attempt to recognise "a font panel" or any other
non-sprite subject. A screenshot of text is large and passes the gate while still not being a sprite,
and claiming otherwise would be the kind of overreach this project spends its time removing. A gate
can catch the shapes it has measurements for; anything subtler is a stated limit, not a silent pass.
"""
from __future__ import annotations

__all__ = ["OutOfScopeError", "MIN_SHORT_SIDE", "MIN_FRAMES_FOR_SPREAD", "require_in_scope"]

#: The smallest short side the judge will measure. Grounded in the reference corpus: its minimum is
#: 62 px and its fifth percentile is 91, so this cuts nothing real and still refuses a font glyph
#: (7 px) by a factor of three.
MIN_SHORT_SIDE = 24

#: Fewer frames than this and a spread is a statement about two numbers. A motion needs a sequence.
MIN_FRAMES_FOR_SPREAD = 6


class OutOfScopeError(ValueError):
    """Raised when the input is not the kind of thing the reference describes.

    A named type rather than a bare `ValueError` because callers act on it differently: the CLI turns
    it into an explanation and a non-zero exit, while `compare` propagates it so a caller cannot
    accidentally treat "not applicable" as "no problem".
    """


def require_in_scope(image, *, what: str = "image") -> None:
    """Refuse an input the judge has no reference for, and say which measurement refuses it.

    Raises `OutOfScopeError`. The message carries the numbers, because a refusal that does not say how
    close the input came is a refusal the caller cannot act on -- and the whole reason this is a hard
    error rather than a note is that a note would be printed next to a full set of numbers that look
    like findings.
    """
    size = getattr(image, "size", None)
    if not size or len(size) != 2:
        raise OutOfScopeError("the %s has no measurable size" % what)
    w, h = size
    short = min(w, h)
    if short < MIN_SHORT_SIDE:
        raise OutOfScopeError(
            "the %s is %dx%d, whose short side is %d px. This judge measures character sprites and its "
            "reference corpus has a smallest short side of 62 px (p05 91, median 123). Below %d px the "
            "metrics are not applying a weak version of themselves -- they are measuring a property the "
            "input does not have, which reads as a clean result. A 5x7 font glyph is 7 px and every one "
            "of its glyphs is flagged by every band.\n"
            "If you know what you are measuring, pass --anyway and the numbers are printed as "
            "uncalibrated: they are then yours to interpret, not the reference's."
            % (what, w, h, short, MIN_SHORT_SIDE)
        )


def require_sequence(frames, *, what: str = "frames") -> None:
    """Refuse a sequence too short for a spread to mean anything."""
    n = len(list(frames))
    if n < MIN_FRAMES_FOR_SPREAD:
        raise OutOfScopeError(
            "the %s number %d; a spread needs at least %d to be a statement about motion rather than "
            "about two numbers" % (what, n, MIN_FRAMES_FOR_SPREAD)
        )
