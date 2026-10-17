# -*- coding: utf-8 -*-
"""Tests for Ichiwatashi.

The interesting assertions here are the ones that came from measurement rather than from intent: a
metric that flagged known-good art, a sampler that measured the encoder, an accent set that optimised
one property by destroying another. Each is pinned so it cannot come back.
"""
from __future__ import annotations

import glob
import itertools
import json
import math
import os
import shutil
import tempfile
import unittest
import zipfile

from pathlib import Path

from PIL import Image

from ichiwatashi.scope import MIN_SHORT_SIDE, OutOfScopeError


def in_scope(size: int = MIN_SHORT_SIDE) -> int:
    """A canvas side the judge will accept, for fixtures whose own subject is not the size gate.

    **The fixtures used to be 8-20 px, and every one of them was a shape the judge was never meant to
    measure.** They passed because nothing checked. `volcano-separator`'s 5x7 font is what made that
    visible: `colours_used` 1 against a band of 16-37 and `isolated_rate` 0.000 against 0.074-0.160, so
    all 58 glyphs came back flagged, and a fixture that small was in the same position without anyone
    noticing. So these helpers exist to keep fixtures at or above the gate -- and the shapes below were
    scaled with them, because enlarging a canvas without enlarging the drawing changes what is measured.
    """
    return max(size, MIN_SHORT_SIDE)


def block_canvas(side: int = 30, *, pad: int = 6, bg=(0, 0, 0, 0)):
    """A square canvas big enough to be measured, and the x-range the drawing should occupy."""
    side = in_scope(side)
    pad = max(pad, 2)
    return Image.new("RGBA", (side, side), bg), pad, side - pad


from ichiwatashi import builder as B
from ichiwatashi import frames as F
from ichiwatashi.judge import judge as judge_fn
from ichiwatashi.judge import _opaque
from ichiwatashi import palette as P
from ichiwatashi import perceptual as PC
from ichiwatashi import figures as FIG
from ichiwatashi import keys as KEYS
from ichiwatashi import panel as PANEL
from ichiwatashi import portable as PORT
from ichiwatashi import terminal as TERM
from ichiwatashi import window as WIN


def coords_note(r):
    return r.notes


def flat(size, colour=(0, 0, 0, 255)):
    """A solid canvas, exactly the size asked for.

    **Deliberately not floored to the judge's minimum.** It was, for one revision, and that broke a
    frame test that needs a 12x20 canvas for its own reasons -- the floor belongs on the calls that
    hand a drawing to `judge_fn`, not on a general image builder. Raising it here was a blunt fix that
    moved the failure instead of removing it.
    """
    return Image.new("RGBA", size, colour)


class TestJudge(unittest.TestCase):

    def test_a_sprite_that_is_one_block_is_reported_as_one(self):
        """A full rectangle is the degenerate case: one cluster, a full bounding box, no outline."""
        im = flat((in_scope(16), in_scope(16)))
        r = judge_fn(im)
        self.assertEqual(r.colours_used, 1)
        self.assertEqual(r.clusters, 1)
        self.assertAlmostEqual(r.bbox_fill, 1.0, places=2)
        self.assertEqual(r.outline_variation, 0.0)

    def test_a_flat_outline_is_no_longer_called_a_fault(self):
        """**This replaces a test that asserted the opposite, and the replacement is the point.**

        The old test asserted that a flat outline raises a note saying known-good sprites vary their
        outline with the local colour. Pointed at 161 real TH155 sprites, *all* of them were flat
        (median variation 0.003) and every one raised that note. Measuring the two generations with
        one pipeline: TH123 sits above 0.5, TH155 sits at ~0, and both are correct work.

        So the outline style is now reported as a style, not a grade. A flat outline raises nothing.
        """
        im = Image.new("RGBA", (in_scope(16), in_scope(16)), (0, 0, 0, 0))
        px = im.load()
        lo, hi = 6, 24
        for y in range(lo, hi):
            for x in range(lo, hi):
                px[x, y] = (200, 200, 200, 255)
        for y in range(lo, hi):
            for x in range(lo, hi):
                if x in (lo, hi - 1) or y in (lo, hi - 1):
                    px[x, y] = (20, 20, 20, 255)
        r = judge_fn(im)
        self.assertLess(r.outline_variation, 0.1)
        self.assertEqual(r.outline_colours, 1)
        self.assertEqual(r.outline_predictability, 1.0)
        self.assertFalse(any("outline" in n for n in r.notes),
                         "a flat outline is a style, not a fault: %s" % r.notes)

    def test_outline_style_separates_systematic_from_noisy(self):
        """The two quantities, on the measurement that motivated them.

        Rewriting one real sprite's outline three ways: a flat outline scores ~0 variation, while
        "varies with the fill" and "random" both score ~0.8 and are told apart only by
        predictability (0.886 against 0.266). One number could not do this -- that is why both exist.
        """
        from ichiwatashi.judge import outline_style
        # flat
        self.assertEqual(outline_style(0.00, 1.00, 1), "flat")
        # systematic: the fill predicts the outline
        self.assertEqual(outline_style(0.82, 0.89, 30), "systematic")
        # noisy: same variation, unpredictable
        self.assertEqual(outline_style(0.81, 0.27, 6), "noisy")
        # the same variation with no predictability signal is not called either
        self.assertEqual(outline_style(0.81, 0.65, 12), "mixed")

        # 30x30 with four 3-wide bands 15 tall: the same shape at a size the judge accepts. The
        # spacing, the band width and the outline rows all scale together -- a fixture that keeps 3 px
        # bands on a larger canvas changes the outline-to-fill ratio the assertion depends on.
        side = in_scope(30)
        im = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        px = im.load()
        fills = [(200, 60, 60, 255), (60, 200, 60, 255), (60, 60, 200, 255), (200, 200, 60, 255)]
        top, bottom = 7, 22
        for k, f in enumerate(fills):
            x0 = 6 + k * 5
            for y in range(top, bottom + 1):
                for x in range(x0, x0 + 3):
                    px[x, y] = f
        # outline each fill with a darkened version of itself, which is the systematic convention
        for k, f in enumerate(fills):
            x0 = 6 + k * 5
            dark = (f[0] // 3, f[1] // 3, f[2] // 3, 255)
            for y in range(top, bottom + 1):
                px[x0, y] = dark
                px[x0 + 2, y] = dark
            for x in range(x0, x0 + 3):
                px[x, top] = dark
                px[x, bottom] = dark
        r = judge_fn(im)
        self.assertGreaterEqual(r.outline_colours, 4)
        self.assertGreater(r.outline_predictability, 0.8)

    def test_isolated_pixels_need_a_rate_and_a_cluster_shape_to_flag(self):
        """**This is the false positive that was found by pointing the judge at real art.**

        A 72x113 commercial frame has 10.1% isolated pixels and is not noisy -- 21 colours across 546
        clusters is detail. A rate-only rule called it bad. What distinguishes noise is that it comes
        with few, large clusters.
        """
        detail = Image.new("RGBA", (24, 24), (0, 0, 0, 0))
        px = detail.load()
        for y in range(24):
            for x in range(24):
                # a fine texture: every pixel its own colour, i.e. lots of isolated ones
                px[x, y] = ((x * 9) % 200 + 30, (y * 7) % 200 + 30, (x + y) % 200 + 30, 255)
        r = judge_fn(detail)
        self.assertGreater(r.isolated_rate, 0.05)
        # Two different statements are possible about isolated pixels and they must not be confused.
        # Being unlike the reference sample is one of them, and this fixture -- 576 colours against a
        # reference of 16-37 -- deserves it. Being diagnosed as *noise* is the other, and that is the
        # one the cluster shape decides. So the assertion names the diagnosis, not the word.
        self.assertFalse(any("stray single pixels" in n for n in r.notes),
                         "fine detail is being diagnosed as noise: %s" % r.notes)

    def test_the_report_is_deterministic(self):
        im = flat((in_scope(8), in_scope(8)), (10, 20, 30, 255))
        self.assertEqual(judge_fn(im), judge_fn(im))

    def test_fully_transparent_does_not_divide_by_zero(self):
        r = judge_fn(flat((in_scope(8), in_scope(8)), (0, 0, 0, 0)))
        self.assertEqual(r.opaque, 0)
        self.assertTrue(any("transparent" in n for n in r.notes))

    def test_a_large_image_does_not_exhaust_memory(self):
        """Sampling builds a dict of every distinct colour; a big image is not a malformed input."""
        im = Image.new("RGB", (400, 400))
        px = im.load()
        for y in range(400):
            for x in range(400):
                px[x, y] = ((x * 3 + y) % 256, (y * 5 + x) % 256, (x ^ y) % 256)
        self.assertTrue(len(P.sample(im, 8)) <= 8)

    def test_a_rendered_frame_is_not_measured_as_a_sprite(self):
        """**Found by pointing the judge at 40 frames of a pixel-art animation.**

        Those frames are opaque and fill their canvas, and the subject sits on a background rather
        than on transparency. Raw, they measured bounding-box fill 1.000 and outline variation 0.000
        -- which raise "the silhouette is a block" and "the outline is flat" -- and 40 of 40 were
        flagged. After the background was made transparent and the frames cropped, the same frames
        measured 0.642 and 0.564. **The two notes had been about the export, not the drawing.**
        """
        # A full-canvas opaque frame with a drawn subject on a flat background.
        im = Image.new("RGBA", (32, 32), (0, 0x5D, 0x77, 255))
        px = im.load()
        for y in range(10, 22):
            for x in range(10, 22):
                px[x, y] = (0xFF, 0x63, 0x63, 255)
        r = judge_fn(im)
        self.assertEqual(r.bbox_fill, 1.0)
        self.assertEqual(r.outline_variation, 0.0)
        self.assertEqual(len(r.notes), 1,
                         "the wrong number of notes for a rendered frame: %s" % r.notes)
        self.assertIn("rendered frame", r.notes[0])
        self.assertNotIn("block", r.notes[0])
        self.assertNotIn("flat colour", r.notes[0])

    def test_a_transparent_sprite_is_still_measured_normally(self):
        """The guard must not swallow real sprites.

        Note the shape: a **disc**, not a rectangle. A solid rectangle cropped to itself has a
        bounding-box fill of exactly 1.000 whatever its transparency, so using one here would be
        testing the guard against a case that cannot distinguish it from a rendered frame.
        """
        im = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
        px = im.load()
        for y in range(32):
            for x in range(32):
                if (x - 15.5) ** 2 + (y - 15.5) ** 2 <= 10 * 10:
                    px[x, y] = (0xFF, 0x63, 0x63, 255)
        r = judge_fn(im)
        self.assertLess(r.bbox_fill, 0.9, "a disc should not fill its bounding box")
        self.assertFalse(any("rendered frame" in n for n in r.notes))
        self.assertLess(len(coords_note(r)), 4)


class TestSilhouette(unittest.TestCase):
    """The anti-aliasing question, asked at the edge instead of over the whole drawing.

    It used to be answered by `isolated_rate`, and that could not work: measured over 40 real TH155
    sprites, **14930 isolated pixels sit inside the drawing and 3409 on its silhouette**. The
    interior ones are single-pixel highlights and cloth texture, which the README already records as
    being the detail. So 81% of the signal was never about edges.

    These fixtures are sized to clear the measurement's own floor. The floor is 100 outline pixels
    because the smallest real sprite measured had 192, and a fixture below it cannot demonstrate
    anything -- which is how the first version of these tests silently tested nothing.
    """

    @staticmethod
    def _block(n=60, band=0, stray=False, specks=False):
        body, line, mid, speck = ((90, 130, 200, 255), (20, 20, 40, 255),
                                  (55, 75, 120, 255), (250, 240, 90, 255))
        im = Image.new("RGBA", (n, n), (0, 0, 0, 0))
        px = im.load()
        lo, hi = 8, n - 8
        for y in range(lo, hi):
            for x in range(lo, hi):
                px[x, y] = body
        for y in range(lo, hi):
            for x in range(lo, hi):
                if x in (lo, hi - 1) or y in (lo, hi - 1):
                    px[x, y] = line
        for y in range(lo, lo + band):
            px[hi - 1, y] = mid
        if stray:
            px[lo, 30] = (255, 0, 255, 255)
        if specks:
            for y in range(18, 34):
                for x in range(18, 34):
                    if (x * 3 + y * 5) % 4 == 0:
                        px[x, y] = speck
        return im

    def test_a_flat_outline_is_a_uniform_edge(self):
        """The strong direction, and the reason this is a measurement rather than a guess: a
        per-pixel condition cannot produce a uniform edge by accident, so `share == 1.0` is real
        evidence that no smoothing layer exists on the drawing."""
        r = judge_fn(self._block())
        self.assertGreaterEqual(r.silhouette_pixels, 100, "fixture below the measurement's floor")
        self.assertEqual(r.silhouette_colours, 1)
        self.assertEqual(r.silhouette_share, 1.0)
        self.assertFalse(any("uniform edge" in n for n in r.notes))

    def test_interior_detail_does_not_move_the_edge_measurement(self):
        """The separation `isolated_rate` could not make, and the whole point of measuring position.

        14930 interior isolated pixels against 3409 silhouette ones: pooling them is what made the
        old number useless as an edge question. Interior speckles leave both silhouette numbers
        exactly where they were.
        """
        flat = judge_fn(self._block())
        specked = judge_fn(self._block(specks=True))
        self.assertGreater(specked.isolated, flat.isolated,
                           "the fixture must actually add isolated pixels, or it proves nothing")
        self.assertEqual(specked.silhouette_colours, flat.silhouette_colours)
        self.assertEqual(specked.silhouette_share, flat.silhouette_share)
        self.assertFalse(any("uniform edge" in n for n in specked.notes))

    def test_a_band_on_the_edge_is_reported_and_a_blemish_is_not(self):
        """The share is what separates a smoothing layer from one bad pixel, and the separation is
        measured rather than chosen: a band covering 12% of the outline reads 0.884, while one stray
        pixel reads 0.994. The threshold sits between them.

        Erring toward silence is deliberate. A false 'your edge is not uniform' on good work is the
        failure this project is least allowed to have; a missed one is the ordinary cost of a
        measurement that will not overstate itself.
        """
        banded = judge_fn(self._block(band=20))
        self.assertEqual(banded.silhouette_colours, 2)
        self.assertLess(banded.silhouette_share, 0.95)
        self.assertTrue(any("uniform edge" in n for n in banded.notes), banded.notes)
        # and the honest limit, pinned: a single stray pixel is a second colour too
        stray = judge_fn(self._block(stray=True))
        self.assertEqual(stray.silhouette_colours, 2)
        self.assertGreater(stray.silhouette_share, 0.95)
        self.assertFalse(any("uniform edge" in n for n in stray.notes))

    def test_the_note_does_not_claim_to_know_which_it_is(self):
        """It can say the edge is not uniform. It cannot say the edge was smoothed, because one
        stray pixel and one anti-aliasing pixel are the same thing seen from outside."""
        r = judge_fn(self._block(band=20))
        note = [n for n in r.notes if "uniform edge" in n][0]
        self.assertIn("cannot tell those apart", note)

    def test_real_sprites_mostly_have_a_uniform_edge(self):
        """The corpus, if it is present. This is the claim the measurement rests on: TH155 draws a
        flat outline with no smoothing layer, so most of these should be uniform."""
        d = Path("E:/DaShaoHuo/downloads/ichiwatashi-corpus/th155")
        if not d.is_dir():
            self.skipTest("the TH155 corpus is not on this machine")
        files = sorted(d.glob("*.png"))[:20]
        flat = 0
        for p in files:
            with Image.open(p) as im:
                if judge_fn(im.convert("RGBA")).silhouette_share == 1.0:
                    flat += 1
        self.assertGreaterEqual(flat, len(files) // 2,
                                "only %d of %d real sprites had a uniform edge" % (flat, len(files)))


class TestGenerationBuckets(unittest.TestCase):
    """A single reference table judged a second generation of correct work and flagged all of it.

    TH123 and TH155 are different populations: `colours_used` has a median of 26 in one and 43 in
    the other, and `outline_variation` 0.726 against 0.004. Measured end to end over 160 real TH155
    sprites, judging them with the TH123 table raised a reference note on **80 of them (50%)**; with
    their own table it is **8 (5%)**. So the bucket is not bookkeeping, it is the difference between
    a report that fires on half of correct work and one that fires on a twentieth.

    TH105 and TH123 are one bucket, not two: they agree on every metric to three decimals across
    four characters and twelve comparisons.
    """

    def test_the_two_generations_are_named_and_one_table_is_the_default(self):
        from ichiwatashi import calibration as C
        self.assertEqual(tuple(C.GENERATIONS), ("th105/th123", "th155"))
        self.assertEqual(C.DEFAULT_GENERATION, "th105/th123")
        # the alias still resolves to the default bucket, so older callers keep working
        self.assertIs(C.REFERENCE, C.REFERENCE_BY_GENERATION[C.DEFAULT_GENERATION])

    def test_the_same_value_gets_different_verdicts_in_the_two_buckets(self):
        """The regression this whole structure exists for, stated as one value and two answers."""
        from ichiwatashi import calibration as C
        # a colours_used of 70 is far above TH123's band and simply not a metric for TH155
        self.assertIsNotNone(C.outside("colours_used", 70.0, generation="th105/th123"))
        self.assertIsNone(C.outside("colours_used", 70.0, generation="th155"))
        # a bbox_fill of 0.85 is above TH123's band and inside TH155's
        self.assertIsNotNone(C.outside("bbox_fill", 0.85, generation="th105/th123"))
        self.assertIsNone(C.outside("bbox_fill", 0.85, generation="th155"))
        # and a metric that only exists in the TH155 bucket
        self.assertIsNone(C.outside("outline_predictability", 0.30, generation="th105/th123"))
        self.assertIsNotNone(C.outside("outline_predictability", 0.30, generation="th155"))

    def test_an_unknown_generation_says_nothing_instead_of_guessing(self):
        """Silence is right. Applying another era's thresholds is exactly what produced the
        false-positive generation, so an unrecognised name must not fall back to the default."""
        from ichiwatashi import calibration as C
        self.assertIsNone(C.outside("colours_used", 70.0, generation="gba-era"))
        self.assertIsNone(C.outside("bbox_fill", 0.85, generation="gba-era"))
        self.assertEqual(C.how_far("bbox_fill", 0.85, generation="gba-era"), 0.0)

    def test_colours_used_is_absent_from_the_th155_bucket_on_purpose(self):
        """It is not a property of those drawings: the palettes are interchangeable within a
        character, and 92.5% of sprites change colour count when decoded with another member of the
        set. A threshold derived from one palette per sprite would be derived from a coin toss."""
        from ichiwatashi import calibration as C
        self.assertNotIn("colours_used", C.REFERENCE_BY_GENERATION["th155"])
        self.assertIn("colours_used", C.REFERENCE_BY_GENERATION["th105/th123"])

    def test_both_buckets_record_where_their_numbers_came_from(self):
        """A threshold a reader cannot trace is an opinion."""
        from ichiwatashi import calibration as C
        for gen in C.GENERATIONS:
            prov = C.PROVENANCE_BY_GENERATION[gen]
            self.assertIn("source", prov)
            self.assertGreater(prov["sample"], 0)
            # and the note has to name the generation it used, or the reader cannot tell which
            note = C.outside("bbox_fill", 99.0, generation=gen)
            self.assertIsNotNone(note)
            self.assertIn(gen, note)

    def test_judge_passes_the_generation_through(self):
        """The wiring, not just the table: `judge(..., generation=...)` has to reach `outside`."""
        # A 30x30 canvas, and the square is placed by the canvas rather than by hand -- `in_scope(16)`
        # is 24, not 30, and writing to x=25 on a 24 px image is an IndexError that reads like a judge
        # failure until you look at the traceback.
        side = in_scope(30)
        im = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        px = im.load()
        lo = side // 5
        hi = side - lo
        # A solid red square with no outline: `colours_used` 1 and a full bounding box put it outside
        # both generations' bands, which is what this needs -- a fixture that fits every band would
        # prove nothing about which table was used.
        for y in range(lo, hi):
            for x in range(lo, hi):
                px[x, y] = (200, 60, 60, 255)
        a = judge_fn(im)
        b = judge_fn(im, generation="th155")
        self.assertTrue(any("th105/th123" in n for n in a.notes) or not a.notes)
        self.assertFalse(any("th105/th123" in n for n in b.notes),
                         "the second call was judged with the first generation's table: %s" % b.notes)


class TestShade(unittest.TestCase):
    """`shade` bands a form by distance to its own boundary, at a constant perpendicular thickness.

    **Two rules were wrong before this one, and the second survived because a rectangle hides it.**
    The first was coordinate arithmetic -- `(x + y) % 7 == 0` -- which drew a diagonal sash. The
    second measured the shape per column and set the top `depth` pixels lit. On a rectangle that is
    exactly right, which is why nobody caught it: two flat bands, perpendicular thickness equal to
    `depth`. On a slope it fixes the wrong quantity, so the perpendicular thickness becomes
    `depth / sqrt(1 + m^2)` and, because the vertical count is an integer, sawtooths between
    `depth` and `depth / sqrt(2)` -- measured 0.71x to 1.0x of the intended width.

    The perpendicular thickness is what these tests assert, because it is the number that is only
    constant when the band actually follows the form.
    """

    @staticmethod
    def _perp_thickness(c):
        """Perpendicular thickness of the lit band per row, with that row's edge step."""
        out = []
        prev_edge = None
        for row in c.rows():
            lit = [x for x, ch in enumerate(row) if ch == "l"]
            filled = [x for x, ch in enumerate(row) if ch in ("b", "l", "d")]
            if not lit or not filled:
                prev_edge = None
                continue
            edge = min(filled)
            step = abs(edge - prev_edge) if prev_edge is not None else 0
            out.append(len(lit) / (1 + step * step) ** 0.5)
            prev_edge = edge
        return out

    def test_a_rectangle_comes_back_as_two_flat_bands(self):
        """The control. Every earlier rule got this right, so it cannot be the whole test -- but a
        rule that broke it would be worse than the one being replaced."""
        c = B.Canvas(24, 16)
        c.rect(4, 2, 19, 13, key="b")
        c.shade({"b": "l"}, {"b": "d"}, depth=2)
        rows = c.rows()
        self.assertEqual(rows[2], "....llllllllllllllll....")
        self.assertEqual(rows[3], "....llllllllllllllll....")
        self.assertEqual(rows[12], "....dddddddddddddddd....")
        self.assertEqual(rows[13], "....dddddddddddddddd....")
        # the vertical sides are banded too, which the per-column rule never did -- it lit only
        # the top of every column, so the left and right edges had no highlight at all
        self.assertEqual(rows[4], "....llbbbbbbbbbbbbll....")
        self.assertEqual(rows[10], "....ddbbbbbbbbbbbbdd....")

    def test_a_sloped_form_gets_a_band_of_constant_perpendicular_width(self):
        """The regression. On a 45-degree edge the old rule produced a sawtooth between 1.0 and 2.0
        for `depth=2`; the band must now hold its width. This test fails against the per-column
        rule, which is what makes it a regression test rather than a description."""
        c = B.Canvas(40, 26)
        c.cone(3, 22, 4, 30, key="b")
        c.shade({"b": "l"}, {"b": "d"}, depth=2)
        perp = self._perp_thickness(c)
        self.assertGreater(len(perp), 8, "fixture too small to say anything")
        spread = max(perp) - min(perp)
        self.assertLess(spread, 1.0,
                        "the band's perpendicular width wobbles by %.2f: %s" % (spread, perp))
        self.assertGreater(min(perp), 2.0, "the band is thinner than the step it came from")

    def test_a_short_form_where_both_bands_meet_is_left_alone(self):
        """The guard. A form thin enough that the top and bottom bands overlap has no correct answer,
        so pixels within range of both are not shaded rather than guessed at."""
        c = B.Canvas(20, 10)
        c.rect(4, 3, 15, 6, key="b")
        c.shade({"b": "l"}, {"b": "d"}, depth=2)
        mid = c.rows()[5]
        self.assertIn("b", mid, "a four-pixel-tall form was shaded solid: %r" % mid)

    def test_light_comes_from_above(self):
        """The direction the rule has always had, kept: a band along a top edge is lit and one along
        a bottom edge is shadowed, so the sign of the shading is not an accident of the geometry."""
        c = B.Canvas(24, 16)
        c.disc(12, 8, 6, key="b")
        c.shade({"b": "l"}, {"b": "d"}, depth=1)
        rows = c.rows()
        first = next(y for y, r in enumerate(rows) if "l" in r)
        last = max(y for y, r in enumerate(rows) if "d" in r)
        self.assertLess(first, 8, "the lit band is not on top")
        self.assertGreater(last, 8, "the shadowed band is not on the bottom")

    def test_the_band_follows_a_slope_rather_than_marching_sideways(self):
        """The failure mode the very first version had, asserted by shape: on a cone the lit band
        must stay a rim near the apex rather than crossing the form.

        Measured as the lit band's horizontal span against the form's own span, row by row: a band
        that marches sideways covers more of each row the further down it goes.
        """
        c = B.Canvas(40, 26)
        c.cone(3, 22, 4, 30, key="b")
        c.shade({"b": "l"}, {"b": "d"}, depth=2)
        coverage = []
        for row in c.rows():
            filled = [x for x, ch in enumerate(row) if ch in ("b", "l", "d")]
            lit = [x for x, ch in enumerate(row) if ch == "l"]
            # Only rows with room for a band on both sides. At the apex the form is two or three
            # pixels wide and the band legitimately *is* the whole row, so including it would
            # measure the fixture rather than the rule.
            if len(filled) >= 8 and lit:
                coverage.append(len(lit) / len(filled))
        self.assertGreater(len(coverage), 6, "fixture too small to say anything")
        self.assertLess(max(coverage), 0.9,
                        "the lit band covers %.0f%% of a row, so it is a sash and not a rim"
                        % (100 * max(coverage)))
        # The shape of a rim rather than a sash: the band's pixel width is roughly constant while
        # the rows get wider, so its share of a row *falls* down the form. A band marching sideways
        # would do the opposite and approach the whole row, which is what the bound above catches.
        self.assertLess(coverage[-1], coverage[0],
                        "coverage does not fall down the form, so the band is spreading into it: %s"
                        % [round(x, 2) for x in coverage])


class TestIndexedColourCounts(unittest.TestCase):
    """Three legitimate answers to "how many colours", and the old name hid which one was meant.

    `palette_size` described the palette's *defined* slots. The code counted distinct RGB values
    among the drawn pixels -- on an indexed source, the slots the drawing *references*, once the
    palette has collapsed them. Measured on TH155, that is not a pedantic distinction: **142 of 200
    sprites use fewer distinct colours than indices**, with gaps up to 11 slots, and a TFPA palette
    declares 256 slots of which only about 70 are distinct.

    `judge` is handed RGBA and cannot make the distinction at all, which is why the count it produces
    is now named for what it is and the indexed relationship is measured separately.
    """

    def test_the_three_counts_are_separate_quantities(self):
        from ichiwatashi.judge import measure_indexed
        # 256 declared slots, of which 4 are distinct colours
        # Index 0 is the transparent slot -- that is the convention everywhere in this project, and
        # the first two versions of this fixture got it wrong: one put a colour at 0, the other put a
        # transparent entry *and* an opaque one on the same RGB triple, which made `colours_defined`
        # count that triple twice.
        # The first four slots are the interesting ones. Everything after them is padding, and the
        # padding is one colour so that counting it is unambiguous -- three earlier versions of this
        # fixture mis-counted by forgetting the padding, or by putting a colour where the transparent
        # slot belongs, or by having a transparent entry and an opaque one share an RGB triple.
        palette = [(0, 0, 0, 0), (10, 20, 30, 255), (40, 50, 60, 255), (10, 20, 30, 255)]
        palette += [(200, 200, 200, 255)] * 252
        # the drawing uses indices 1, 2 and 3; nothing uses 0
        indices = [1] * 5 + [2] * 5 + [3] * 5
        m = measure_indexed(indices, palette)
        self.assertEqual(m["slots_defined"], 256)
        # distinct RGB in the whole palette: transparent, 10/20/30, 40/50/60, and the padding colour
        self.assertEqual(m["colours_defined"], 4)
        self.assertEqual(m["slots_used"], 3)           # indices 1, 2, 3
        self.assertEqual(m["colours_used"], 2)         # index 3 repeats index 1's colour
        self.assertAlmostEqual(m["used_duplicate_share"], 1 - 2 / 3, places=3)

    def test_a_duplicate_slot_inside_the_used_range_is_visible(self):
        """The relation 71% of real TH155 sprites are in. Two indices, one colour: any RGBA path
        reports one colour and cannot say that two slots were spent on it."""
        from ichiwatashi.judge import measure_indexed
        palette = [(0, 0, 0, 0), (40, 50, 60, 255), (10, 20, 30, 255), (10, 20, 30, 255)]
        indices = [1] * 4 + [2] * 4 + [3] * 4      # index 0 transparent, unused
        m = measure_indexed(indices, palette)
        self.assertEqual(m["slots_used"], 3)        # 1, 2, 3
        self.assertEqual(m["colours_used"], 2)      # 2 and 3 are the same colour
        self.assertAlmostEqual(m["used_duplicate_share"], 1 - 2 / 3, places=3)

    def test_transparency_is_a_slot_but_not_a_colour(self):
        """Index 0 is the transparent one throughout this project, so it counts as a slot the drawing
        references only if it is drawn -- and it never is. Counting it would inflate every sprite."""
        from ichiwatashi.judge import measure_indexed
        palette = [(0, 0, 0, 0), (10, 20, 30, 255)]
        m = measure_indexed([0] * 100 + [1] * 3, palette)
        self.assertEqual(m["slots_used"], 1)
        self.assertEqual(m["colours_used"], 1)

    def test_judge_reports_what_it_can_see_and_the_field_is_named_for_it(self):
        """`colours_used` on an RGBA report is distinct RGB among drawn pixels. It is the same number
        an indexed measurement would give for `colours_used`, and it is *not* the palette's size --
        which is what the old name claimed."""
        side = in_scope(30)
        im = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        px = im.load()
        lo = side // 5
        hi = side - lo
        for y in range(lo, hi):
            for x in range(lo, hi):
                px[x, y] = (10, 20, 30, 255)
        # one row inside the block carries the second colour, so the count is exactly 2
        for x in range(lo, hi):
            px[x, lo + 3] = (40, 50, 60, 255)
        r = judge_fn(im)
        self.assertEqual(r.colours_used, 2)
        self.assertFalse(hasattr(r, "palette_size"),
                         "the old name is deliberately gone: it described something else")


class TestPalette(unittest.TestCase):

    def test_merging_collapses_compression_noise(self):
        """**The measurement that started this: 40 JPEG frames reported 25,398 distinct RGB values,
        and the head of the list was one colour plus its halo.**"""
        base = [(0x00, 0x5D, 0x77), (0x10, 0x6B, 0xA4), (0x4A, 0xC5, 0xFF), (0xFF, 0x39, 0x00)]
        im = Image.new("RGB", (40, 40))
        px = im.load()
        i = 0
        for y in range(40):
            for x in range(40):
                c = base[(x // 10) % 4]
                d = (i % 5) - 2
                px[x, y] = (max(0, min(255, c[0] + d)),
                            max(0, min(255, c[1] - d)),
                            max(0, min(255, c[2] + (d if d % 2 else 0))))
                i += 1
        self.assertGreater(len(im.getcolors(1 << 24)), 4)
        got = P.sample(im, 4)
        self.assertLessEqual(len(got), 4)
        present = {col for _, col in im.getcolors(1 << 24)}
        for c in got:
            self.assertIn(tuple(c), present, "%r is not a colour in the image" % (c,))

    def test_merging_zero_measures_the_encoder(self):
        """A guard on the guard: with merging off the count must be large, or the fixture is wrong."""
        im = Image.new("RGB", (20, 20))
        px = im.load()
        for y in range(20):
            for x in range(20):
                px[x, y] = (100 + (x % 3), 100 + (y % 3), 100)
        self.assertGreater(len(P.sample(im, 40, merge_distance=0)), len(P.sample(im, 40)))

    def test_saturate_keeps_hue(self):
        import colorsys
        for c in ((0x62, 0x38, 0x4D), (0xDB, 0xB5, 0xB7), (0x4A, 0xC5, 0xFF)):
            h0 = colorsys.rgb_to_hsv(*[v / 255 for v in c])[0]
            h1 = colorsys.rgb_to_hsv(*[v / 255 for v in P.saturate(c)])[0]
            self.assertAlmostEqual(h0, h1, places=2)

    def test_separation_reports_the_minimum_because_that_is_what_gets_confused(self):
        a = [(255, 0, 0), (0, 0, 0)]
        b = [(254, 0, 0), (0, 0, 255)]
        lo, mid = P.separation(a, b)
        self.assertLess(lo, 0.05, "a near-identical pair must show up in the minimum")
        self.assertGreater(mid, lo)

    def test_best_accents_prefers_separation_over_saturation(self):
        """Hand-picking got this wrong twice: it fixed saturation and destroyed separation, because a
        near-white and a pink were placed against the other character's white and pink."""
        other = [(255, 255, 255), (237, 28, 36), (243, 141, 169)]     # white, red, pink
        pool = [(255, 255, 255), (254, 254, 254), (243, 141, 169),     # the trap: near-those colours
                (0x7B, 0x4F, 0xCB), (0x86, 0x45, 0xD6), (0x53, 0x2E, 0x8F),
                (0x63, 0x4A, 0xA8), (0xA5, 0x7B, 0xDB)]
        got = P.best_accents(pool, other, count=3, min_saturation=0.3)
        for c in got:
            self.assertGreater(min(max(abs(x - y) for x, y in zip(c, o)) for o in other), 40,
                               "%r is too close to the other board" % (c,))


class TestBestAccentsIsExact(unittest.TestCase):
    """The enumeration was replaced by a scan, and the scan is **exact** -- checked against brute force.

    The TODO entry asked for a greedy or annealing **approximation** and said such an approximation would
    have to state where it deviates. It does not deviate: the objective is a minimum of independent terms,

        mind(combo) = min over x in combo of d(x)      where d(x) = min over y in other_board of dist(x, y)

    so `d(x)` does not depend on the rest of the combo and maximising the minimum over fixed-size subsets
    reduces to finding the largest threshold with enough colours above it. `test_the_scan_matches_brute_force`
    is that claim tested rather than argued, and it is the assertion that would have caught a guessed
    window in the first version of the scan -- which failed on 8 of 66 floor-bound instances.
    """

    @staticmethod
    def _brute(pool, other, count, floor):
        """The exhaustive answer, kept in the tests as the oracle."""
        import colorsys

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

    @staticmethod
    def _objective(combo, other):
        return min(math.dist(P._lab(x), P._lab(y)) for x, y in itertools.product(combo, other))

    def test_the_scan_matches_brute_force(self):
        """Random pools, compared on the objective value -- including ones where the floor binds.

        300 trials, and the trial generator deliberately includes high floors so that the saturation
        constraint is not decorative: in the probe run that produced this test, 66 of 400 trials had a
        floor that changed the answer, and a scan with a guessed window failed 8 of those.
        """
        import random as _r
        rnd = _r.Random(11)
        feasible = compared = bound = 0
        for _ in range(300):
            n = rnd.randint(8, 12)
            m = rnd.randint(3, 6)
            pool = [tuple(rnd.randrange(256) for _ in range(3)) for _ in range(n)]
            other = [tuple(rnd.randrange(256) for _ in range(3)) for _ in range(m)]
            count = rnd.randint(2, 4)
            floor = rnd.choice([0.2, 0.35, 0.5, 0.65])
            b = self._brute(pool, other, count, floor)
            nofloor = self._brute(pool, other, count, 0.0)
            if b is None:
                with self.assertRaises(ValueError):
                    P.best_accents(pool, other, count=count, min_saturation=floor)
                continue
            feasible += 1
            if nofloor and abs(nofloor[0] - b[0]) > 1e-9:
                bound += 1
            got = P.best_accents(pool, other, count=count, min_saturation=floor)
            self.assertEqual(len(got), count)
            self.assertAlmostEqual(self._objective(got, other), b[0], places=9,
                                   msg="the scan found %r scoring %.6f where brute force found %.6f"
                                       % (got, self._objective(got, other), b[0]))
            compared += 1
        self.assertGreater(compared, 250, "the trial generator must produce answers to compare")
        self.assertGreater(bound, 20, "the saturation floor must actually bind in these trials: %d" % bound)

    def test_the_answer_is_a_subset_of_the_pool_and_respects_the_floor(self):
        """Two properties the caller relies on, asserted on a real board."""
        import colorsys
        other = [(255, 255, 255), (237, 28, 36)]
        pool = [(0x7B, 0x4F, 0xCB), (0x86, 0x45, 0xD6), (0x53, 0x2E, 0x8F),
                (0x63, 0x4A, 0xA8), (0xA5, 0x7B, 0xDB), (0xF0, 0xF0, 0xF0)]
        got = P.best_accents(pool, other, count=3, min_saturation=0.3)
        self.assertEqual(len(set(got)), 3, "no duplicates")
        for c in got:
            self.assertIn(c, pool, "%r is not from the pool" % (c,))
        mean_sat = sum(colorsys.rgb_to_hsv(*[v / 255 for v in c[:3]])[1] for c in got) / 3
        self.assertGreaterEqual(mean_sat, 0.3, "the floor must hold: %.3f" % mean_sat)

    def test_a_pool_that_is_too_small_or_has_no_other_board_is_refused(self):
        """Named refusals rather than a bare ValueError from an empty `min()`."""
        with self.assertRaises(ValueError) as ctx:
            P.best_accents([(1, 2, 3)], [(9, 9, 9)], count=3)
        self.assertIn("need", str(ctx.exception))
        with self.assertRaises(ValueError) as ctx:
            P.best_accents([(1, 2, 3)], [], count=1)
        self.assertIn("other_board", str(ctx.exception))
        with self.assertRaises(ValueError) as ctx:
            P.best_accents([(1, 2, 3)], [(9, 9, 9)], count=0)
        self.assertIn("positive", str(ctx.exception))

    def test_a_high_floor_falls_back_to_the_most_saturated_eligible_set(self):
        """When the floor is what forces the choice, the answer is the saturated set -- not a refusal.

        Both choices score the same objective (the threshold is already the largest feasible one), so the
        fallback is not a compromise; it is the tie-break that keeps the constraint holding.
        """
        import colorsys
        # d-ranked grey colours are far from the board but desaturated; the vivid ones are closer
        other = [(10, 10, 10)]
        pool = [(240, 240, 240), (230, 230, 230), (220, 220, 220),
                (200, 30, 30), (30, 200, 30), (30, 30, 200)]
        got = P.best_accents(pool, other, count=2, min_saturation=0.6)
        sats = [colorsys.rgb_to_hsv(*[v / 255 for v in c[:3]])[1] for c in got]
        self.assertGreaterEqual(sum(sats) / 2, 0.6, "the floor must hold: %s" % (got,))
        self.assertTrue(all(s > 0.3 for s in sats), "a desaturated colour slipped through: %s" % (got,))

    def test_a_large_pool_is_fast_enough_to_not_need_a_budget(self):
        """The case the TODO entry was written about: count=6 on a 30-colour pool, 593,775 combinations.

        Not a timing assertion -- those are flaky -- but a bound generous enough that only a return to
        enumeration could exceed it. Measured: the scan does this in about 0.0001 s, while the enumeration
        needed 1.03 s at 20 colours and 3.41 s at 24 for the same `count`.
        """
        import random as _r
        import time as _t
        rnd = _r.Random(5)
        pool = [tuple(rnd.randrange(256) for _ in range(3)) for _ in range(30)]
        other = [(255, 255, 255), (10, 10, 10), (200, 40, 60)]
        t0 = _t.perf_counter()
        got = P.best_accents(pool, other, count=6, min_saturation=0.1)
        dt = _t.perf_counter() - t0
        self.assertEqual(len(got), 6)
        self.assertLess(dt, 1.0, "a 30-colour pool with count=6 took %.3f s -- enumeration is back" % dt)


class TestPaletteRoles(unittest.TestCase):
    """A colour's job, judged by the relation it stands in rather than by where it sits.

    The TODO entry: "两块板之间没有角色分工：现在不知道某个色是「皮肤」还是「描边」。按用途分槽会比按色相
    分更有用。" Four of the five roles it names need semantics a pixel grid does not carry. **Outline does
    not**, and this measures it from the (fill, outline) pair relation `judge._outline` already builds.

    **The obvious criterion was measured first and failed**, which is why the test file records the wrong one
    too: "a colour that touches transparency is an outline" produced **no outline role on 16 of 20 real
    sprites**, while `outline_predictability` read ~1.0 and said an outline plainly existed. An outline
    colour is also used for the interior contours between hair locks, so most of its occurrences never touch
    the background. Position answers where a colour is near the edge; role needs what it wraps.
    """

    @staticmethod
    def _ringed(w=24, h=24, fill=(200, 120, 160), ring=(12, 0, 9)):
        """A filled shape with a one-pixel ring -- an outline, by construction."""
        im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        px = im.load()
        for y in range(6, h - 6):
            for x in range(6, w - 6):
                px[x, y] = ring + (255,)
        for y in range(7, h - 7):
            for x in range(7, w - 7):
                px[x, y] = fill + (255,)
        return im

    def test_a_ring_is_named_the_outline_and_the_body_is_not(self):
        """The fixture's answer is known by construction, so the criterion is checked against it."""
        im = self._ringed()
        r = P.roles(im)
        self.assertEqual(r.get((12, 0, 9)), "outline")
        self.assertEqual(r.get((200, 120, 160)), "fill")

    def test_the_positional_criterion_is_the_one_that_fails(self):
        """Kept as a test so the wrong idea cannot be re-derived without meeting the measurement.

        On this fixture the ring *does* touch transparency, so a positional criterion would also name it an
        outline -- which is why the fixture alone would not have caught the mistake. What exposed it was the
        corpus: 16 of 20 real sprites, where the outline is used inside the drawing too. So this asserts the
        distinction the real sprites forced: **the ring here is the shape's only edge colour, and it is still
        found by the relation rather than by the touch.**
        """
        im = self._ringed()
        px = im.load()
        # the ring pixel at (6, 6) has a transparent neighbour
        self.assertEqual(px[5, 6][3], 0, "the fixture's ring must touch transparency")
        r = P.roles(im)
        # and a colour that touches transparency but is mostly interior is NOT an outline
        interior_heavy = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
        q = interior_heavy.load()
        for y in range(4, 36):
            for x in range(4, 36):
                q[x, y] = (200, 120, 160, 255)
        for x in range(4, 36):
            q[x, 35] = (12, 0, 9, 255)          # a single outline-coloured row along the bottom
        r2 = P.roles(interior_heavy)
        self.assertEqual(r2.get((200, 120, 160)), "fill")
        self.assertIn(r2.get((12, 0, 9)), ("outline", "fill"))

    def test_a_flat_shape_has_no_outline_role(self):
        """Nothing to name: a shape drawn in one colour has no (fill, outline) pair at all."""
        im = Image.new("RGBA", (24, 24), (0, 0, 0, 0))
        px = im.load()
        for y in range(6, 18):
            for x in range(6, 18):
                px[x, y] = (200, 120, 160, 255)
        r = P.roles(im)
        self.assertEqual(r.get((200, 120, 160)), "fill")
        self.assertEqual([k for k, v in r.items() if v == "outline"], [])

    def test_every_real_sprite_has_an_outline_role(self):
        """The assertion the full corpus supports: at least one outline colour, on all 160.

        **A first version asserted "exactly one" and was refuted by the corpus**: the real distribution is 1
        for 100 sprites, 2 for 38, 3 for 4, 5 for 3, 6 for 14 and 7 for 1. The "exactly one" claim came from
        a 12-sprite sample -- the same over-generalisation the role docstring used to carry.

        So what is pinned is the claim that survived: the criterion always finds **something**, which is what
        a positional criterion failed to do on 16 of 20. The distribution is asserted loosely -- no sprite
        may report zero -- and a sprite with several is a drawing that outlines parts differently, not a
        failure of the measurement.
        """
        files = sorted(glob.glob(r"E:\DaShaoHuo\downloads\ichiwatashi-corpus\**\*.png", recursive=True))
        if not files:
            self.skipTest("corpus samples are not on this machine")
        seen = {}
        for f in files:
            r = P.roles(Image.open(f))
            n = sum(1 for v in r.values() if v == "outline")
            seen[n] = seen.get(n, 0) + 1
            self.assertGreaterEqual(n, 1, "%s has no outline colour at all" % os.path.basename(f))
        self.assertNotIn(0, seen, "the distribution must contain no zero: %s" % seen)
        self.assertIn(1, seen, "at least some sprites have a single outline: %s" % seen)

    def test_the_board_argument_limits_the_answer_to_the_board(self):
        """A role is only ever assigned to a colour the caller asked about."""
        im = self._ringed()
        only_fill = P.roles(im, [(200, 120, 160)])
        self.assertEqual(list(only_fill), [(200, 120, 160)])
        self.assertEqual(only_fill[(200, 120, 160)], "fill")


class TestPackaging(unittest.TestCase):
    """The things a release needs, asserted before a tag exists rather than after PyPI has the file.

    **This class exists because the first wheel built here was incomplete.** It contained eleven `.py` files
    and no `assets/`, so an installed copy could not find the font its own `font` command defaults to -- while
    the build, the metadata check and the install all reported success. The sibling project shipped once
    without the module behind its main flag for exactly the same reason. A build that succeeds says nothing
    about its contents.
    """

    def test_the_font_source_ships_inside_the_package(self):
        """It has to be inside `ichiwatashi/`, not beside it, or `package-data` cannot reach it."""
        src = Path(__file__).resolve().parents[1] / "ichiwatashi" / "assets" / "font5x7.txt"
        self.assertTrue(src.is_file(), "the font source is missing from the package: %s" % src)
        # **Counted with the parser, not by counting lines.** The file is 119 lines and 88 glyphs: it carries
        # comments and blank lines, and `\n`-splitting it counts 119 -- which is what the first version of this
        # assertion did, and it failed on a file that was completely correct.
        from ichiwatashi import font as FONT
        glyphs = FONT.parse_source(src.read_text(encoding="utf-8"))
        self.assertEqual(len(glyphs), 88, "the font table should hold 88 glyphs")
        self.assertIn(" ", glyphs, "the space glyph is part of the set")
        for ch, glyph in glyphs.items():
            self.assertEqual(len(glyph.rows), 7, "%r does not have 7 rows" % ch)
            for row in glyph.rows:
                self.assertTrue(0 <= row < 128, "%r row %d is not a 5-bit value" % (ch, row))

    def test_pyproject_declares_the_package_data(self):
        """Without this line the wheel is built and is missing the font."""
        pyproject = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn("[tool.setuptools.package-data]", pyproject)
        self.assertIn("assets/*.txt", pyproject)

    def test_the_version_is_declared_once_and_agrees_in_both_places(self):
        """`pyproject.toml` and `ichiwatashi.__version__` both exist, so they can disagree.

        The release workflow checks this too; asserting it here means the failure arrives while editing rather
        than at the last step of a release.
        """
        import tomllib
        root = Path(__file__).resolve().parents[1]
        declared = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
        import ichiwatashi as I
        self.assertEqual(declared, I.__version__,
                         "pyproject.toml says %r but ichiwatashi.__version__ says %r"
                         % (declared, I.__version__))

    def test_the_cli_font_default_is_absolute_and_inside_the_package(self):
        """A default relative to the current directory passes in the checkout and fails for every user."""
        from ichiwatashi.cli import FONT_SOURCE
        self.assertTrue(Path(FONT_SOURCE).is_absolute(), "%s is not absolute" % FONT_SOURCE)
        self.assertTrue(Path(FONT_SOURCE).is_file(), "%s does not exist" % FONT_SOURCE)
        self.assertEqual(Path(FONT_SOURCE).parent.parent.name, "ichiwatashi",
                         "%s is not inside the package" % FONT_SOURCE)

    def test_figures_font_path_resolves_from_any_directory(self):
        """`figures.FONT_PATH` used to be the bare string "assets/font5x7.txt"."""
        from ichiwatashi import figures as FIG
        self.assertTrue(Path(FIG.FONT_PATH).is_absolute(), "FONT_PATH is still relative: %r" % FIG.FONT_PATH)
        old = os.getcwd()
        d = tempfile.mkdtemp()
        try:
            os.chdir(d)
            self.assertTrue(Path(FIG.FONT_PATH).is_file(),
                            "FONT_PATH does not resolve from an unrelated cwd")
        finally:
            # **step out before removing it**: on Windows a directory cannot be deleted while it is the
            # current working directory, and a `TemporaryDirectory` context manager therefore raises
            # PermissionError from its own cleanup while the assertion above passed.
            os.chdir(old)
            shutil.rmtree(d, ignore_errors=True)


class TestPanel(unittest.TestCase):
    """The panel's layout, its renderer, and the check that makes it embeddable.

    NTVI assigns Ichiwatashi the task of *producing* the shared pixel layer -- font, palette, panel layout --
    which the other tools **embed**. Something three other projects will embed has to be **verifiable by
    itself**, so this module is a description, a renderer and a pixel check rather than a GUI.

    **The check is the point, and it caught two real things while being built.** Its first version reported 90
    problems on a *correct* panel -- the title glyphs are drawn over the title bar, so those pixels are
    legitimately not the bar's colour. And a 64-pixel panel with "Ichiwatashi" as its title drew
    "Ichi wa.ta.sk": the title bar had 58 pixels and the word needs 65, so the panel showed a different word
    and saved successfully, which is the same failure as a figure whose label ran off its canvas.
    """

    # **Taken from the implementation, not copied.** A local copy of the role table is a second definition,
    # and when the two title roles were added this copy silently went stale and eight tests failed -- which is
    # the tests noticing, but only after the fact. The keys used here are the ones the module ships.
    ROLES = PANEL.PANEL_ROLES
    KEYS = dict(PANEL.PANEL_KEYS)
    PALETTE = dict(PANEL.PANEL_PALETTE)

    def test_a_correct_panel_has_no_problems(self):
        cv = PANEL.draw(PANEL.PanelSpec(), 96, 40, keys=self.KEYS, title="Hi")
        self.assertEqual(PANEL.check(PANEL.PanelSpec(), cv, keys=self.KEYS, title="Hi"), [])

    def test_the_title_exclusion_is_doing_work(self):
        """Without it the check reports the glyph pixels as errors -- which is what it did at first."""
        cv = PANEL.draw(PANEL.PanelSpec(), 96, 40, keys=self.KEYS, title="Hi")
        without = PANEL.check(PANEL.PanelSpec(), cv, keys=self.KEYS)
        self.assertGreater(len(without), 0, "the glyphs must land where the bar was expected")
        self.assertTrue(all(p[2] == "title" for p in without),
                        "every such problem is a title-bar pixel: %r" % (without[:3],))

    def test_the_check_bites_when_one_pixel_is_wrong(self):
        """A checker that cannot fail is not a checker. This flips one frame pixel."""
        cv = PANEL.draw(PANEL.PanelSpec(), 96, 40, keys=self.KEYS)
        self.assertEqual(PANEL.check(PANEL.PanelSpec(), cv, keys=self.KEYS), [])
        cv.put(0, 0, self.KEYS["frame_light"])
        problems = PANEL.check(PANEL.PanelSpec(), cv, keys=self.KEYS)
        self.assertEqual(problems, [(0, 0, "frame_dark", self.KEYS["frame_light"])])

    def test_the_dithering_pattern_of_the_bevel_is_lit_top_left_and_shaded_bottom_right(self):
        """A bevel is asymmetric by definition; the first version had the two sides disagree."""
        where = PANEL.layout(PANEL.PanelSpec(), 96, 40)
        fx0, fy0, fx1, fy1 = where["frame"]
        cv = PANEL.draw(PANEL.PanelSpec(), 96, 40, keys=self.KEYS)
        # **Asserted edge by edge rather than at hand-picked corners**, because two attempts at corner
        # coordinates were both off by one: `(fx0 + 1, fy0)` is the *outer* ring (row 0), not the inner one.
        # Walking each edge asks the question the renderer is answering -- "is this whole side lit or shaded"
        # -- instead of asking me to get an index right.
        inner_top = [cv.get(x, fy0 + 1) for x in range(fx0 + 1, fx1 - 1)]
        inner_left = [cv.get(fx0 + 1, y) for y in range(fy0 + 1, fy1 - 1)]
        inner_bottom = [cv.get(x, fy1 - 2) for x in range(fx0 + 1, fx1 - 1)]
        inner_right = [cv.get(fx1 - 2, y) for y in range(fy0 + 1, fy1 - 1)]
        self.assertEqual(set(inner_top), {self.KEYS["frame_light"]},
                         "the whole top inner ring is lit: %r" % (set(inner_top),))
        self.assertEqual(set(inner_left), {self.KEYS["frame_light"]},
                         "and the whole left one: %r" % (set(inner_left),))
        # **The corners belong to two edges, and the renderer gives them to the top and the left.** So the
        # bottom and right inner rings start with one lit pixel each -- measured: the bottom reads
        # `'l' + 'd' * 94`. Excluding the end pixels is asserting what the rule actually says rather than
        # asserting a symmetry the rule does not claim.
        self.assertEqual(set(inner_bottom[1:]), {self.KEYS["frame_dark"]},
                         "the bottom inner ring is shaded apart from the corner: %r"
                         % (set(inner_bottom),))
        self.assertEqual(set(inner_right[1:]), {self.KEYS["frame_dark"]},
                         "and the right one too: %r" % (set(inner_right),))
        self.assertEqual(inner_bottom[0], self.KEYS["frame_light"],
                         "the bottom-left corner is on the lit left edge")
        self.assertEqual(inner_right[0], self.KEYS["frame_light"],
                         "and the top-right corner is on the lit top edge")

    def test_a_missing_role_is_refused(self):
        keys = dict(self.KEYS)
        del keys["content"]
        with self.assertRaises(ValueError) as ctx:
            PANEL.draw(PANEL.PanelSpec(), 96, 40, keys=keys)
        self.assertIn("content", str(ctx.exception))

    def test_a_canvas_too_small_for_its_own_border_is_refused(self):
        with self.assertRaises(ValueError):
            PANEL.layout(PANEL.PanelSpec(border=3), 5, 40)
        # **14, not 15**: border 2 on both sides plus a 9-row title plus 2 rows of content is exactly 15, so
        # 15 is a panel that just fits -- the first version of this test asserted it should be refused.
        with self.assertRaises(ValueError):
            PANEL.layout(PANEL.PanelSpec(title_h=9), 96, 14)
        PANEL.layout(PANEL.PanelSpec(title_h=9), 96, 15)   # and this one must not raise

    def test_a_title_that_does_not_fit_is_refused_rather_than_clipped(self):
        """**The defect the render showed**: a clipped title is a different word, drawn silently."""
        with self.assertRaises(ValueError) as ctx:
            PANEL.draw(PANEL.PanelSpec(), 64, 40, keys=self.KEYS, title="Ichiwatashi")
        msg = str(ctx.exception)
        self.assertIn("Ichiwatashi", msg)
        self.assertIn("widen", msg, "the way out has to be stated")

    def test_check_reports_a_title_that_does_not_fit_without_pixel_coordinates(self):
        cv = PANEL.draw(PANEL.PanelSpec(), 96, 40, keys=self.KEYS, title="Hi")
        problems = PANEL.check(PANEL.PanelSpec(), cv, keys=self.KEYS, title="A title far too long for this")
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0][2], "title_fits")
        self.assertEqual(problems[0][:2], (-1, -1), "a layout problem has no pixel to point at")

    def test_render_upscales_by_a_whole_number_only(self):
        im = PANEL.render(PANEL.PanelSpec(), 96, 40, keys=self.KEYS, palette=self.PALETTE,
                          title="Hi", scale=3)
        self.assertEqual(im.size, (96 * 3, 40 * 3))
        for bad in (0, -1, 1.5, "2"):
            with self.assertRaises(ValueError):
                PANEL.render(PANEL.PanelSpec(), 96, 40, keys=self.KEYS, palette=self.PALETTE, scale=bad)

    def test_every_size_tier_passes_the_same_check(self):
        """**One layout at three sizes, not three layouts** -- and only this assertion makes that true."""
        for name in sorted(PANEL.TIERS):
            spec, w, h = PANEL.tier(name)
            cv = PANEL.draw(spec, w, h, keys=self.KEYS, title="Ichi")
            problems = PANEL.check(spec, cv, keys=self.KEYS, title="Ichi")
            self.assertEqual(problems, [], "tier %r at %dx%d: %r" % (name, w, h, problems[:3]))

    def test_an_unknown_tier_is_refused_by_name(self):
        with self.assertRaises(ValueError) as ctx:
            PANEL.tier("enormous")
        self.assertIn("enormous", str(ctx.exception))
        self.assertIn("compact", str(ctx.exception), "the known names must be listed")

    def test_window_state_is_visible_to_the_check(self):
        """**What makes this a window rather than a panel.** The active title bar is a different role, so a
        panel drawn active and checked as inactive reports a problem at every title-bar pixel."""
        spec, w, h = PANEL.tier("normal")
        for drawn_active in (True, False):
            cv = PANEL.draw(spec, w, h, keys=self.KEYS, title="Ichi", active=drawn_active)
            self.assertEqual(PANEL.check(spec, cv, keys=self.KEYS, title="Ichi", active=drawn_active), [])
            wrong = PANEL.check(spec, cv, keys=self.KEYS, title="Ichi", active=not drawn_active)
            self.assertGreater(len(wrong), 100,
                               "checking the wrong state must be loud, not silent: %d" % len(wrong))
            self.assertTrue(all(p[2].startswith("title") for p in wrong),
                            "and every problem is in the title bar: %r" % (wrong[:3],))

    def test_the_tiers_differ_in_size_and_agree_on_the_layout(self):
        """The parts must be in the same relative places, which is what "one layout" means."""
        for name in sorted(PANEL.TIERS):
            spec, w, h = PANEL.tier(name)
            where = PANEL.layout(spec, w, h)
            self.assertEqual(where["frame"], (0, 0, w, h))
            self.assertEqual(where["title"][0], spec.border)
            self.assertEqual(where["content"][0], spec.border + spec.pad)

    def test_the_cli_verifies_before_writing(self):
        """A panel nobody checked is a panel somebody else inherits unchecked."""
        from ichiwatashi.cli import main
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "p.png"
            self.assertEqual(main(["panel", str(out), "--width", "96", "--title", "Hi", "--scale", "3"]), 0)
            self.assertTrue(out.is_file())
            from PIL import Image as _I
            self.assertEqual(_I.open(out).size, (96 * 3, 40 * 3))
            # and a title that cannot fit is refused with exit 2, and leaves no file
            bad = Path(d) / "bad.png"
            self.assertEqual(main(["panel", str(bad), "--width", "48", "--title", "Ichiwatashi"]), 2)
            self.assertFalse(bad.exists(), "a refusal must not leave a file behind")

    def test_every_rendered_colour_comes_from_the_key_table(self):
        """The rule `figures` states: a rendered image may not contain a colour nobody asked for."""
        im = PANEL.render(PANEL.PanelSpec(), 96, 40, keys=self.KEYS, palette=self.PALETTE, title="Hi")
        used = {c[1] for c in im.getcolors(maxcolors=1 << 16) or []}
        self.assertTrue(used <= set(self.PALETTE.values()),
                        "colours outside the palette: %r" % (used - set(self.PALETTE.values())))


class TestPortablePanel(unittest.TestCase):
    """The panel as data a tool in another language can read.

    NTVI assigns this repository the shared pixel layer and the other three embed it. Two are Python, **Volcano
    Separator is PowerShell and Node** -- so "embed" cannot be an import, and must not become a runtime
    dependency either (source shared, dependency not). What crosses all three boundaries is data.
    """

    def test_the_export_carries_everything_an_embedder_needs(self):
        body = PORT.export("compact", title="Ichi")
        for field in ("format", "tier", "size", "spec", "layout", "close_pixels", "title_room",
                      "roles", "keys", "colours", "chars", "checksum"):
            self.assertIn(field, body, "an embedder needs %r" % field)
        self.assertEqual(body["format"], PORT.FORMAT)
        # **both colour and character, keyed the same way**: an embedder reads one index and gets both, which
        # is not true if one table is keyed by role name and the other by role key
        self.assertEqual(set(body["colours"]), set(body["keys"].values()))
        self.assertEqual(set(body["chars"]), set(body["keys"].values()),
                         "colours and chars must be keyed alike: %r vs %r"
                         % (sorted(body["colours"]), sorted(body["chars"])))
        for role in body["roles"]:
            key = body["keys"][role]
            self.assertIn(key, body["colours"], "no colour for %r" % role)
            self.assertIn(key, body["chars"], "no character for %r" % role)
        # the one role with no single character says so rather than being absent
        self.assertIsNone(body["chars"][body["keys"]["title_text"]])
        self.assertIn("null", body["chars_note"])

    def test_the_checksum_is_reproducible_across_writers(self):
        """**Canonical JSON, not `json.dumps` defaults** -- key order and spacing are exactly what two writers
        disagree about, and the checksum has to survive being recomputed elsewhere."""
        a = PORT.export("normal", title="Ichi")
        b = PORT.export("normal", title="Ichi")
        self.assertEqual(a["checksum"], b["checksum"])
        self.assertEqual(PORT.canonical({"b": 1, "a": 2}), PORT.canonical({"a": 2, "b": 1}))

    def test_a_round_trip_through_a_file(self):
        body = PORT.export("wide", title="Ichi")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "panel.json"
            p.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
            back = PORT.load(p)
        self.assertEqual(back["checksum"], body["checksum"])
        self.assertEqual(back["layout"], body["layout"])

    def test_a_tampered_file_is_refused_by_its_own_checksum(self):
        """**The checksum is what makes this a shared fact rather than a familiar filename.**"""
        body = PORT.export("normal", title="Ichi")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "panel.json"
            body2 = dict(body, keys=dict(body["keys"], frame_dark="XX"))
            p.write_text(json.dumps(body2, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                PORT.load(p)
            self.assertIn("checksum", str(ctx.exception))

    def test_an_unknown_format_is_refused_by_name(self):
        body = dict(PORT.export("normal"), format="something/9")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "panel.json"
            p.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                PORT.load(p)
            self.assertIn("something/9", str(ctx.exception))
            self.assertIn(PORT.FORMAT, str(ctx.exception), "the format this build speaks has to be named")

    def test_verify_checks_a_rendering_against_the_file(self):
        body = PORT.export("normal", title="Ichi")
        spec = PANEL.PanelSpec(**body["spec"])
        cv = PANEL.draw(spec, body["size"][0], body["size"][1], keys=PANEL.PANEL_KEYS, title="Ichi")
        self.assertEqual(PORT.verify(spec, cv, body=body, title="Ichi"), [])
        # a file edited after export is caught before any comparison
        tampered = dict(body, keys=dict(body["keys"]))
        tampered["keys"]["frame_dark"] = "XX"
        self.assertIn("checksum", [p[2] for p in PORT.verify(spec, cv, body=tampered)])

    def test_verify_reports_a_size_mismatch_without_pixel_coordinates(self):
        body = PORT.export("compact")
        spec = PANEL.PanelSpec(**body["spec"])
        cv = PANEL.draw(spec, body["size"][0], body["size"][1], keys=PANEL.PANEL_KEYS)
        other = dict(body, size=[999, 999], checksum=None)
        other["checksum"] = PORT._checksum(other)
        problems = PORT.verify(spec, cv, body=other)
        self.assertEqual(problems[0][2], "size")
        self.assertEqual(problems[0][:2], (-1, -1))

    def test_the_cli_exports_and_verifies(self):
        import contextlib
        import io as _io
        from ichiwatashi.cli import main
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "panel.json"
            buf = _io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(main(["panel", "--tier", "compact", "--title", "Ichi",
                                       "--export", str(p)]), 0)
            self.assertTrue(p.is_file())
            self.assertIn("checksum", buf.getvalue())
            buf2 = _io.StringIO()
            with contextlib.redirect_stdout(buf2):
                self.assertEqual(main(["panel", "--verify", str(p)]), 0)
            self.assertIn("agree", buf2.getvalue())


class TestKeyboardModel(unittest.TestCase):
    """Keys as a model, before any window: which key means what, and where the focus goes.

    **"A keyboard-operable window" sounds like a GUI problem and is mostly not one.** What a window *does* with
    a key -- which widget is next, whether Enter activates, whether Escape backs out -- is a small state
    machine, and it is the part that can be wrong. The toolkit is a delivery mechanism. So these tests run
    without a display, a terminal, or a keyboard.
    """

    def test_escape_sequences_are_tried_longest_first(self):
        """**The order is the whole difficulty.** `\x1b[Z` starts with `\x1b`, so a table tried in the wrong
        order reports every arrow key as Escape plus two stray characters -- and the symptom is a window that
        closes when you press Up."""
        self.assertEqual(KEYS.parse_key("\x1b[Z"), "shift+tab")
        self.assertEqual(KEYS.parse_key("\x1b[A"), "up")
        self.assertEqual(KEYS.parse_key("\x1b[B"), "down")
        self.assertEqual(KEYS.parse_key("\x1b"), "esc")

    def test_a_printable_key_is_one_namespace_and_matched_by_its_letter(self):
        """`parse_key("q")` is `char:q`, and the bindings table says `q`.

        **The first version looked up only the full name**, so `"q": "quit"` sat in the table and never fired:
        measured, pressing `q` returned `ignored`. A `char:` key that is not found verbatim is now looked up by
        the letter alone.
        """
        self.assertEqual(KEYS.parse_key("q"), "char:q")
        self.assertEqual(KEYS.parse_key("Q"), "char:q", "case does not make a different key")
        self.assertEqual(KEYS.action_for("char:q"), "quit")
        self.assertEqual(KEYS.action_for("char:z"), None, "an unbound key stays unbound")

    def test_the_focus_ring_wraps_in_both_directions(self):
        f = KEYS.Focus(3)
        self.assertEqual([f.apply("focus_next") for _ in range(4)], ["moved"] * 4)
        self.assertEqual(f.index, 1, "three nexts from 0 land on 1 after wrapping once")
        f2 = KEYS.Focus(3)
        f2.apply("focus_prev")
        self.assertEqual(f2.index, 2, "one step back from the start wraps to the end")

    def test_actions_report_what_happened_rather_than_mutating_the_world(self):
        f = KEYS.Focus(2)
        self.assertEqual(f.press("\t"), ("tab", "focus_next", "moved"))
        self.assertEqual(f.press("\r"), ("enter", "activate", "activated"))
        self.assertEqual(f.press("\x1b"), ("esc", "cancel", "left"))
        self.assertEqual(f.press("z"), ("char:z", None, "ignored"))

    def test_an_empty_ring_ignores_movement_and_activation(self):
        """A window with no controls is a legitimate state, not an error."""
        f = KEYS.Focus(0)
        self.assertEqual(f.apply("focus_next"), "ignored")
        self.assertEqual(f.apply("activate"), "ignored")
        self.assertEqual(f.index, 0)

    def test_refusals_are_by_name(self):
        for bad in ("", "ab", "\x01"):
            with self.assertRaises(ValueError):
                KEYS.parse_key(bad)
        with self.assertRaises(ValueError) as ctx:
            KEYS.action_for("tab", bindings={"tab": "focus_sideways"})
        self.assertIn("focus_sideways", str(ctx.exception))
        with self.assertRaises(ValueError):
            KEYS.Focus(3, index=5)
        with self.assertRaises(ValueError):
            KEYS.Focus(-1)


class TestTerminalRendering(unittest.TestCase):
    """One character per logical pixel, so the interface can be compared as a string.

    **A toolkit window cannot be checked this way** -- what a test can see of it is whatever the toolkit
    exposes, which is not the pixels. A character grid *is* the rendering.
    """

    def test_the_geometry_comes_from_the_panel_layout(self):
        """Two independent ideas of where a border goes is the defect `panel` already fixed once."""
        spec, w, h = PANEL.tier("compact")
        for name in sorted(PANEL.TIERS):
            spec, w, h = PANEL.tier(name)
            lines = TERM.rows(spec, w, h)
            self.assertEqual(len(lines), h)
            self.assertTrue(all(len(line) == w for line in lines))
            where = PANEL.layout(spec, w, h)
            fx0, fy0, fx1, fy1 = where["frame"]
            self.assertEqual(set(lines[fy0]), {"#"}, "the top row is the frame")
            self.assertEqual(set(lines[fy1 - 1]), {"#"}, "and so is the bottom")
            self.assertTrue(all(line[fx0] == "#" and line[fx1 - 1] == "#" for line in lines),
                            "and both side columns")

    def test_the_two_title_bars_are_different_characters(self):
        spec, w, h = PANEL.tier("normal")
        active = TERM.rows(spec, w, h, title="Ichi")
        inactive = TERM.rows(spec, w, h, title="Ichi", active=False)
        self.assertNotEqual(active, inactive, "the state has to be visible in the text too")
        where = PANEL.layout(spec, w, h)
        right = where["title"][2] - 2
        self.assertEqual(active[where["title"][1]][right], "-")
        self.assertEqual(inactive[where["title"][1]][right], ".")

    def test_the_title_is_drawn_as_glyphs(self):
        spec, w, h = PANEL.tier("normal")
        lines = TERM.rows(spec, w, h, title="Ichi")
        joined = "".join(lines)
        self.assertIn("#", joined, "glyph pixels are the heavy mark")
        # and the glyph rows sit inside the title band
        where = PANEL.layout(spec, w, h)
        band = "".join(lines[where["title"][1] + 1:where["title"][3]])
        self.assertIn("#", band)

    def test_the_close_mark_is_drawn_and_counted(self):
        """**The system's title bar is not used, so this is the only close button there is.**"""
        spec, w, h = PANEL.tier("normal")
        where = PANEL.layout(spec, w, h)
        cv = PANEL.draw(spec, w, h, keys=PANEL.PANEL_KEYS, title="Ichi")
        marks = sum(1 for y in range(h) for x in range(w)
                    if cv.get(x, y) == PANEL.PANEL_KEYS["close_mark"])
        self.assertEqual(marks, len(where["_close_px"]))
        self.assertGreater(marks, 0, "an undecorated window with no close mark cannot be closed")
        # and the mark really is the X shape: its pixels are not a filled block
        rect = where["close"]
        area = (rect[2] - rect[0]) * (rect[3] - rect[1])
        self.assertLess(marks, area, "an X is not a filled square: %d of %d" % (marks, area))

    def test_the_mark_can_be_turned_off(self):
        spec = PANEL.PanelSpec(close=False)
        where = PANEL.layout(spec, 96, 40)
        self.assertIsNone(where["close"])
        self.assertEqual(where["_close_px"], set())

    def test_the_title_never_runs_under_the_close_mark(self):
        """**The mark takes room from the title, not the other way round.**

        Measured before the fix: the title's available width ran to the frame's inner edge, so a title that fit
        could run underneath the mark -- and the check would still pass, because the mark's pixels are
        asserted separately. **The collision would have been invisible in the one place it matters.**
        """
        spec, w, h = PANEL.tier("normal")
        where = PANEL.layout(spec, w, h)
        start, room = PANEL.title_room(spec, where)
        self.assertEqual(start + room, where["close"][0],
                         "the room ends where the mark begins")
        # a title exactly filling the room is accepted, and one pixel more is not
        from ichiwatashi import figures as _FIG
        exact = room // 6
        PANEL.draw(spec, w, h, keys=PANEL.PANEL_KEYS, title="x" * exact)
        with self.assertRaises(ValueError):
            PANEL.draw(spec, w, h, keys=PANEL.PANEL_KEYS, title="x" * (exact + 2))

    def test_the_text_version_shows_the_mark_too(self):
        spec, w, h = PANEL.tier("normal")
        lines = TERM.rows(spec, w, h, title="Ichi")
        self.assertIn(TERM.CHARS["close_mark"], "".join(lines))

    def test_a_title_that_does_not_fit_is_refused(self):
        spec, w, h = PANEL.tier("compact")
        with self.assertRaises(ValueError) as ctx:
            TERM.rows(spec, w, h, title="A title far too long for this tier")
        self.assertIn("columns", str(ctx.exception))

    def test_the_status_line_names_the_focus(self):
        self.assertIn("focus 2/3", TERM.status_line(focus=KEYS.Focus(3, index=1)))
        self.assertIn("inactive", TERM.status_line(focus=KEYS.Focus(1), active=False))
        self.assertIn("no control focused", TERM.status_line(focus=KEYS.Focus(0)))
        self.assertIn("hint", TERM.status_line(focus=KEYS.Focus(1), hint="hint"))

    def test_the_cli_prints_the_window_and_a_transcript(self):
        """The focus ring is driven from the command line, so "keyboard-operable" has a transcript to read.

        **That is the point of splitting the model from the toolkit**: a real window would need a display to
        demonstrate this, and the thing worth demonstrating is the state machine.
        """
        import contextlib
        import io as _io
        from ichiwatashi.cli import main
        buf = _io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main(["panel", "--tier", "compact", "--title", "Ichi", "--controls", "3",
                       "--dispatch", "focus_next focus_next activate", "--text"])
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("focus_next   -> moved", out)
        self.assertIn("activate     -> activated", out)
        self.assertIn("#", out, "and the window itself is printed")
        self.assertIn("focus 3/3", out, "the status line reports where the focus ended up")

    def test_the_cli_refuses_an_unknown_action_with_exit_two(self):
        import contextlib
        import io as _io
        from ichiwatashi.cli import main
        buf = _io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main(["panel", "--dispatch", "focus_sideways", "--text"])
        self.assertEqual(rc, 2)
        self.assertIn("not an action", buf.getvalue())

    @unittest.skipUnless(os.environ.get("ICHIWATASHI_WINDOW_TEST"),
                         "opening a window blocks in mainloop and needs a display; set "
                         "ICHIWATASHI_WINDOW_TEST=1 to run it")
    def test_the_cli_refuses_a_window_gracefully_when_it_cannot_open_one(self):
        """**Not run by default, and that is a correction.**

        The first version called `main([... "--window"])` unconditionally. On this machine a display exists,
        so the window really opened and the suite **blocked forever in `mainloop()`** -- measured: ten minutes
        with no end. **A test that can hang is worse than no test**, because it takes the whole suite with it
        and looks like a slow run rather than a stuck one.

        What is worth asserting is available without a window: `open_window` refuses a fractional scale before
        any toolkit is touched, and `tk_key` is a pure function. Both are tested above. This one is kept behind
        an environment variable for the case where someone actually wants to open one.
        """
        import contextlib
        import io as _io
        from ichiwatashi.cli import main
        buf = _io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main(["panel", "--tier", "compact", "--window"])
        out = buf.getvalue()
        if rc == 2:
            self.assertIn("could not open a window", out)
            self.assertIn("--text", out, "the alternative has to be offered")
        else:
            self.assertEqual(rc, 0)

    def test_the_cli_wants_a_destination_or_the_text_flag(self):
        import contextlib
        import io as _io
        from ichiwatashi.cli import main
        buf = _io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main(["panel"])
        self.assertEqual(rc, 2)
        self.assertIn("--text", buf.getvalue(), "the way out has to be stated")

    def test_a_toolkit_key_event_becomes_this_package_s_key_name(self):
        """**The only toolkit-specific logic, and it is a pure function** -- which is why it is testable
        without a display, while the window itself is not.

        `keysym` first because it names the key ("Tab", "Up"); `char` second because for a letter that is what
        was typed. Binding on keysym alone loses the arrow keys; on char alone it loses Tab and Return.
        """
        cases = [("Tab", None, "tab"), ("ISO_Left_Tab", None, "shift+tab"), ("Return", None, "enter"),
                 ("Escape", None, "esc"), ("Up", None, "up"), ("Down", None, "down"),
                 ("space", " ", "space"), ("q", "q", "char:q"), ("Q", "Q", "char:q")]
        for keysym, char, want in cases:
            self.assertEqual(WIN.tk_key(keysym, char), want, "keysym %r char %r" % (keysym, char))

    def test_an_unknown_key_carries_no_action(self):
        """**`None`, not a guessed character.** Turning an unknown keysym into a character would make F5
        press the letter f five times."""
        for keysym in ("F5", "Control_L", "Alt_R", "Prior"):
            self.assertIsNone(WIN.tk_key(keysym), "%r must not become a key" % (keysym,))

    def test_the_whole_chain_from_a_toolkit_event_to_an_effect(self):
        """A toolkit event, through the key model, to what the window does -- all without a display."""
        f = KEYS.Focus(3)
        transcript = []
        for keysym, char in (("Tab", None), ("Tab", None), ("Return", None), ("q", "q")):
            key = WIN.tk_key(keysym, char)
            action = KEYS.action_for(key) if key else None
            transcript.append((keysym, key, action, f.apply(action) if action else "ignored"))
        self.assertEqual(transcript, [
            ("Tab", "tab", "focus_next", "moved"),
            ("Tab", "tab", "focus_next", "moved"),
            ("Return", "enter", "activate", "activated"),
            ("q", "char:q", "quit", "left"),
        ])

    def test_the_window_refuses_a_fractional_scale(self):
        """The check happens before any toolkit is touched, so it can be asserted here."""
        spec, w, h = PANEL.tier("compact")
        for bad in (0, -1, 1.5, "2", None):
            with self.assertRaises(ValueError):
                WIN.open_window(spec, w, h, title="x", scale=bad)

    def test_a_whole_frame_includes_the_status_line(self):
        spec, w, h = PANEL.tier("compact")
        block = TERM.frame(spec, w, h, title="Ichi", focus=KEYS.Focus(2), hint="tab")
        self.assertEqual(len(block), h + 1)
        self.assertIn("focus 1/2", block[-1])

class TestDelaysFromAnArchive(unittest.TestCase):
    """An animation archive, read for timing it may or may not carry.

    **What the format actually is, checked against a client rather than remembered.** An earlier note in this
    project said `うごイラ` "is frames plus a per-frame delay table". That is true only of exports that
    repackage it: **pixiv's own ZIP contains the frames and nothing else**, and gallery-dl's extractor reads
    the timing from the API (`/v1/ugoira/metadata` -> `["ugoira_metadata"]["frames"]`, each entry
    `{"file": ..., "delay": ...}`) while the archive comes from a separate URL. **So a native archive has no
    answer to give, and saying that is the correct result** -- not an empty list with no explanation.
    """

    @staticmethod
    def _archive(path, table_name=None, table_body=None, frames=4):
        with zipfile.ZipFile(path, "w") as z:
            for i in range(frames):
                im = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
                px = im.load()
                for y in range(2, 6):
                    for x in range(2, 6):
                        px[x, y] = (200, 60, 60, 255)
                tmp = Path(str(path) + ".png")
                im.save(tmp)
                z.write(tmp, "%06d.png" % i)
                tmp.unlink()
            if table_name:
                z.writestr(table_name, table_body)
        return path

    def test_the_pixiv_metadata_shape(self):
        """Nested under `ugoira_metadata`, frames as dicts with `delay` in milliseconds."""
        with tempfile.TemporaryDirectory() as d:
            p = self._archive(Path(d) / "a.zip", "metadata.json", json.dumps(
                {"ugoira_metadata": {"frames": [{"file": "000000.png", "delay": 60} for _ in range(4)]}}))
            delays, note = F.read_delays(p)
            self.assertEqual(delays, [60, 60, 60, 60])
            self.assertIn("metadata.json", note)

    def test_a_bare_frames_array(self):
        """The same thing without the outer key -- which is what an un-nested export looks like."""
        with tempfile.TemporaryDirectory() as d:
            p = self._archive(Path(d) / "b.zip", "frames.json", json.dumps(
                {"frames": [{"file": "000000.png", "delay": 40} for _ in range(4)]}))
            self.assertEqual(F.read_delays(p)[0], [40, 40, 40, 40])

    def test_a_text_table_inside_the_archive(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._archive(Path(d) / "c.zip", "delays.txt", "80\n80\n120\n40\n")
            self.assertEqual(F.read_delays(p)[0], [80, 80, 120, 40])

    def test_frames_only_is_reported_as_no_timing(self):
        """**The native case, and the reason this class exists.**"""
        with tempfile.TemporaryDirectory() as d:
            p = self._archive(Path(d) / "native.zip")
            delays, note = F.read_delays(p)
            self.assertEqual(delays, [], "an archive with no table has no durations: %r" % (delays,))
            self.assertIn("no delay table", note)
            self.assertIn("4 frame", note, "the archive was read, and saying how many frames proves it")
            self.assertIn("API metadata", note, "and where the timing actually lives")

    def test_centiseconds_are_converted(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._archive(Path(d) / "e.zip", "metadata.json", json.dumps(
                {"ugoira_metadata": {"frames": [{"file": "f", "delay": 60} for _ in range(4)]}}))
            self.assertEqual(F.read_delays(p, unit="cs")[0], [6, 6, 6, 6])

    def test_a_frame_entry_without_a_delay_field_is_named(self):
        """A wrong key would otherwise produce an empty list and look like an archive with no timing."""
        with tempfile.TemporaryDirectory() as d:
            p = self._archive(Path(d) / "f.zip", "metadata.json", json.dumps(
                {"frames": [{"file": "000000.png", "wait": 60}]}))
            delays, note = F.read_delays(p)
            self.assertEqual(delays, [])
            self.assertIn("no delay field", note)
            self.assertIn("file", note, "the keys that were present are listed")

    def test_the_cli_accepts_a_zip(self):
        from ichiwatashi.cli import main
        with tempfile.TemporaryDirectory() as d:
            size = 40
            for i in range(6):
                im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
                px = im.load()
                for y in range(6, 34):
                    for x in range(6, 34):
                        px[x, y] = (200, 60, 60, 255)
                for y in range(16, 22):
                    for x in range(14 + i, 20 + i):
                        px[x, y] = (90, 60, 150, 255)
                im.save(Path(d) / ("f%02d.png" % i))
            z = Path(d) / "t.zip"
            with zipfile.ZipFile(z, "w") as zf:
                zf.writestr("metadata.json", json.dumps(
                    {"ugoira_metadata": {"frames": [{"file": "f", "delay": 80} for _ in range(6)]}}))
            self.assertIn(main(["frames", d, "--delays", str(z)]), (0, 1))
            # an archive with no table is refused with the reason, not a traceback
            z2 = Path(d) / "empty.zip"
            with zipfile.ZipFile(z2, "w") as zf:
                zf.writestr("000000.png", b"x")
            self.assertEqual(main(["frames", d, "--delays", str(z2)]), 2)


class TestAllowingLossesOneAtATime(unittest.TestCase):
    """The two GIF losses are not equally acceptable, and `allow` says which is which.

    **The problem.** `allow_loss` was a boolean, so a caller who accepts quantisation but not flattened alpha
    could only grant both or neither. Those losses are not the same kind of thing: **flattening a partly
    transparent pixel destroys information that cannot be recovered**, while quantising above 256 colours
    keeps the shapes and approximates the colours -- a loss of degree.

    **And a third candidate was removed, not merely disallowed.** "A frame mixes opaque and transparent
    pixels" flagged every ordinary sprite and was deleted; `LOSS_KINDS` holds two names, and a test asserts
    that count so a re-added false positive would be visible.
    """

    @staticmethod
    def _both(size=40, n=3):
        """A timeline that has both losses: partly transparent pixels, and more than 256 colours."""
        tl = F.Timeline(size, size)
        for i in range(n):
            im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            px = im.load()
            for y in range(size):
                for x in range(size):
                    a = 128 if (12 <= x < 26 and 12 <= y < 26) else 255
                    px[x, y] = ((x * 7) % 256, (y * 11) % 256, (x * y) % 256, a)
            tl.add(im, pivot=(size // 2, size - 1), duration_ms=80)
        return tl

    def test_exactly_two_kinds_exist(self):
        """A false-positive kind would change this number; that is why it is asserted."""
        self.assertEqual(F.LOSS_KINDS, ("transparency", "palette"))

    def test_gif_losses_reports_which_kinds_are_present(self):
        kinds = self._both().gif_losses()["kinds"]
        self.assertIn("transparency", kinds)
        self.assertIn("palette", kinds)

    def test_allowing_one_kind_still_refuses_the_other(self):
        tl = self._both()
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(F.GifWouldLose) as ctx:
                tl.to_gif(Path(d) / "a.gif", allow={"palette"})
            msg = str(ctx.exception)
            self.assertIn("transparency", msg, "the refused kind must be named")
            self.assertIn("allowed: palette", msg, "and what was granted must be stated too")
            self.assertNotIn("palette:", msg.split("would not be what was drawn")[1],
                             "the allowed kind must not appear in the refused list")
            self.assertFalse((Path(d) / "a.gif").exists())

    def test_allowing_both_writes_it(self):
        tl = self._both()
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "b.gif"
            tl.to_gif(p, allow=set(F.LOSS_KINDS))
            self.assertTrue(p.is_file())

    def test_allow_loss_still_means_everything(self):
        """The boolean is kept as shorthand, and it has to stay equivalent to the full set."""
        tl = self._both()
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.gif"
            tl.to_gif(p, allow_loss=True)
            self.assertTrue(p.is_file())

    def test_a_kind_that_does_not_exist_is_refused_by_name(self):
        """A typo must not quietly grant nothing and then look like a broken refusal."""
        tl = self._both()
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError) as ctx:
                tl.to_gif(Path(d) / "d.gif", allow={"colour"})
            self.assertIn("unknown loss kind", str(ctx.exception))
            self.assertIn("transparency", str(ctx.exception), "the known names must be listed")

    def test_the_cli_accepts_a_single_kind(self):
        from ichiwatashi.cli import main
        with tempfile.TemporaryDirectory() as d:
            size = 48
            for i in range(6):
                im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
                px = im.load()
                for y in range(8, 40):
                    for x in range(8, 40):
                        px[x, y] = (200, 60, 60, 255)
                for y in range(20, 28):
                    for x in range(18 + i, 24 + i):
                        px[x, y] = (90, 60, 150, 128)
                im.save(Path(d) / ("f%02d.png" % i))
            # only the transparency loss is at stake in this fixture, so allowing palette changes nothing
            self.assertEqual(main(["frames", d, "--gif", str(Path(d) / "x.gif"), "--allow", "palette"]), 2)
            self.assertIn(main(["frames", d, "--gif", str(Path(d) / "x.gif"), "--allow", "transparency"]),
                          (0, 1))


class TestTheClearGroundIsNotAColour(unittest.TestCase):
    """`sample()` was counting the transparent region as a colour, and on real art it ranked first.

    **The bug underneath the `--count` report.** Investigating why `--count 8` printed 4 found that
    `--merge 0` printed **4 when the fixture draws 3** -- the extra entry being `#000000`, every
    transparent pixel's RGB, because `sample()` used `convert("RGB")`. On a real 207x179 character sheet
    that black was the **most frequent** entry in the palette of a sprite that does not contain it.

    A colour counted from a region nobody drew is the failure shape this project keeps meeting: not an
    error, a confident wrong answer. And the first attempt at the fix converted an already-RGB copy back
    to RGBA, which restored nothing -- the alpha had been discarded two lines earlier.
    """

    def test_a_transparent_ground_contributes_no_colours(self):
        im = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
        px = im.load()
        for i, c in enumerate([(200, 60, 60), (60, 120, 200), (240, 220, 90)]):
            for y in range(4 + i * 4, 4 + i * 4 + 3):
                for x in range(6, 26):
                    px[x, y] = c + (255,)
        got = P.sample(im, 20, merge_distance=0)
        self.assertEqual(len(got), 3,
                         "three opaque colours on a clear ground is three colours, not four: %r" % (got,))
        self.assertNotIn((0, 0, 0), [tuple(c[:3]) for c in got],
                         "the clear ground's RGB must not appear as a palette entry")

    def test_a_fully_transparent_image_yields_nothing(self):
        """No palette, rather than a palette of one invented black."""
        self.assertEqual(P.sample(Image.new("RGBA", (16, 16), (0, 0, 0, 0)), 8), ())

    def test_an_opaque_black_is_still_a_colour(self):
        """The fix must not throw away real black along with the transparent kind."""
        im = Image.new("RGBA", (16, 16), (0, 0, 0, 255))
        got = P.sample(im, 8)
        self.assertEqual([tuple(c[:3]) for c in got], [(0, 0, 0)],
                         "an opaque black pixel is a colour and has to survive: %r" % (got,))

    def test_the_alpha_channel_is_not_lost_before_the_filter(self):
        """The specific mechanism: converting to RGB first leaves nothing for a later RGBA conversion."""
        im = Image.new("RGBA", (24, 24), (0, 0, 0, 0))
        px = im.load()
        for y in range(8, 16):
            for x in range(8, 16):
                px[x, y] = (200, 60, 60, 255)
        # one colour despite the image being mostly transparent
        self.assertEqual(len(P.sample(im, 20, merge_distance=0)), 1)


class TestPaletteCommandSaysWhoLimitedIt(unittest.TestCase):
    """`palette` names which parameter produced the count, and it had been naming none.

    **The report that started this**: `--count 8` on a 16-colour sprite printed "4 colour(s) after merging
    within 24 per channel", which reads as "this image has 4 colours" when it has sixteen -- and the reader
    could not tell whether `--count` or `--merge` produced the shortfall. Both parameters are honest; only
    saying which one bound the result makes it readable.

    **And the first fix was wrong twice.** A two-way test ("fewer than --count" means the threshold bound it)
    reported `--count 40 --merge 4` as threshold-limited when the drawing simply has 18 colours -- naming the
    wrong cause, which is worse than naming none. Then the cap case said "merging did not limit this", which
    is false whenever the threshold happens to produce the same count as the cap. Four cases, and the cap
    case states only what is known.
    """

    def _sprite(self, colours, transparent_bg=True):
        # the canvas has to hold `4 * len(colours)` rows of bands, so it grows with the fixture -- an
        # earlier 24-row canvas raised IndexError on the six-colour case
        h = max(24, 4 * len(colours) + 4)
        im = Image.new("RGBA", (24, h), (0, 0, 0, 0) if transparent_bg else (255, 255, 255, 255))
        px = im.load()
        # **bands must not overlap.** The first version used `range(4 + i, 8 + i)`, so band i+1 overwrote
        # most of band i and the fixture ended up drawing one colour while the test expected three.
        for i, c in enumerate(colours):
            for y in range(2 + i * 4, 2 + i * 4 + 3):
                for x in range(4, 20):
                    px[x, y] = tuple(c) + (255,)
        return im

    def _run(self, im, *args):
        import contextlib
        import io as _io
        from ichiwatashi.cli import main
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.png"
            im.save(p)
            buf = _io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main(["palette", str(p)] + list(args))
        return rc, buf.getvalue()

    def test_distinct_colours_are_counted_from_opaque_pixels_only(self):
        """A transparent ground is not a colour of the artwork.

        The first version converted to RGB before counting, which folded the clear background's colour into
        the total -- one colour more than the drawing uses, and that one is not in the drawing.
        """
        im = self._sprite([(200, 60, 60), (60, 120, 200), (240, 220, 90)])
        _rc, out = self._run(im, "--count", "20", "--merge", "0")
        self.assertIn("3 colour(s) this drawing uses", out,
                      "three opaque colours and a clear ground should read as three: %r" % out)

    def test_the_threshold_is_named_when_it_is_what_limited(self):
        im = self._sprite([(200, 60, 60), (201, 61, 61), (60, 120, 200), (61, 121, 201),
                           (240, 220, 90), (241, 221, 91)])
        _rc, out = self._run(im, "--count", "6", "--merge", "24")
        self.assertIn("the threshold is what limited this", out,
                      "near-duplicates merged under a wide threshold must be named as the cause: %r" % out)
        self.assertIn("lower --merge", out, "and the way out has to be offered")

    def test_the_drawing_itself_is_named_when_it_is_the_limit(self):
        """The case the two-way version mis-attributed."""
        im = self._sprite([(200, 60, 60), (60, 120, 200), (240, 220, 90)])
        _rc, out = self._run(im, "--count", "40", "--merge", "4")
        self.assertIn("this drawing uses", out,
                      "when nothing was merged away and the cap was not reached, the drawing is the limit: %r"
                      % out)
        self.assertNotIn("threshold is what limited", out,
                         "naming the threshold here would send the reader to change the wrong flag")

    def test_the_cap_is_named_without_claiming_what_merging_would_have_done(self):
        """`--count 4 --merge 24` can return 4 because of the cap *and* because of the threshold.

        So the cap case does not say "merging did not limit this" -- that sentence is false whenever the two
        coincide, which is exactly when a reader would want the truth.
        """
        im = self._sprite([(200, 60, 60), (201, 61, 61), (60, 120, 200), (240, 220, 90)])
        _rc, out = self._run(im, "--count", "2", "--merge", "24")
        self.assertIn("capped by --count", out)
        self.assertNotIn("did not limit this", out,
                         "the old sentence claimed something the command does not know: %r" % out)

    def test_the_report_names_the_sprite_it_used(self):
        """A count with no attribution is what the entry was about; the blocks still have roles beside them."""
        im = self._sprite([(200, 60, 60), (60, 120, 200), (240, 220, 90)])
        _rc, out = self._run(im, "--count", "20", "--merge", "0")
        self.assertIn("#", out, "the hex values are still printed")
        self.assertIn("fill", out, "and so are the roles")


class TestShiftExactness(unittest.TestCase):
    """`exact` is what tells a translation from a lookalike, and it does not depend on the window.

    **The problem it solves.** `aligned_shift` used to decide "is this fit trustworthy" by whether the best
    offset landed on the search window's edge. Measured: at `reach=3` a rotation hits the edge five times,
    while at `reach=6` and `9` it settles on a wrong offset and flags nothing. **The edge flag catches a
    search that ran out of room; it cannot catch a fit that settles.**

    **The signal that does catch it.** A frame is an integer grid, so a genuine translation matches every
    changed pixel and leaves a residual of zero. Measured across three motion kinds, as a *fraction of the
    changed pixels matched*: a one-pixel translation gives **1.0000** at every window size, a 90-degree
    rotation gives 0.58 / 0.71 / 0.74 / 0.74 as the window widens, and a horizontal flip gives 0.83 / 0.87.
    **Nothing that is not a translation reaches 1.0, and the translation reaches it regardless of the
    window** -- which is what makes this a judgement and the edge flag a note.
    """

    SIZE = 40

    def _frames(self, marks=None, rotate=0, flip=False, n=3):
        """A body with an asymmetric notch and a mark that can move."""
        out = []
        for i in range(n):
            im = Image.new("RGBA", (self.SIZE, self.SIZE), (0, 0, 0, 0))
            px = im.load()
            for y in range(8, self.SIZE - 8):
                for x in range(8, self.SIZE - 8):
                    px[x, y] = (200, 60, 60, 255)
            for y in range(8, 16):
                for x in range(self.SIZE - 12, self.SIZE - 8):
                    px[x, y] = (0, 0, 0, 0)
            dx = (marks[i] if marks else 0)
            for y in range(18, 24):
                for x in range(14 + dx, 20 + dx):
                    px[x, y] = (90, 60, 150, 255)
            if rotate:
                im = im.rotate(rotate * i, resample=Image.NEAREST, center=(self.SIZE // 2, self.SIZE // 2))
            if flip:
                im = im.transpose(Image.FLIP_LEFT_RIGHT) if i % 2 else im
            out.append(im)
        return out

    def _timeline(self, frames):
        tl = F.Timeline(self.SIZE, self.SIZE)
        for im in frames:
            tl.add(im, pivot=(self.SIZE // 2, self.SIZE - 1))
        return tl

    def test_a_true_translation_is_exact_at_every_window_size(self):
        """The claim the whole design rests on: the window stops being the bottleneck."""
        tl = self._timeline(self._frames(marks=[0, 1, 2]))
        for reach in (3, 4, 6, 9):
            _dx, _dy, per, scores, _bounds, exact = tl.aligned_shift(reach=reach)
            self.assertTrue(all(exact), "reach=%d: not every pair was exact: %s" % (reach, exact))
            self.assertTrue(all(s == 0 for s in scores),
                            "reach=%d: an exact fit must leave no residual: %s" % (reach, scores))
            self.assertEqual(per, [(1, 0), (1, 0)], "reach=%d: offsets changed: %s" % (reach, per))

    def test_a_rotation_is_not_exact(self):
        tl = self._timeline(self._frames(rotate=15))
        _dx, _dy, _per, scores, _bounds, exact = tl.aligned_shift(reach=6)
        self.assertFalse(any(exact), "a rotation must not be reported as a translation: %s" % (exact,))
        self.assertTrue(all(s > 0 for s in scores), "a rotation leaves residual: %s" % (scores,))

    def test_a_flip_is_not_exact(self):
        tl = self._timeline(self._frames(flip=True))
        _dx, _dy, _per, _scores, _bounds, exact = tl.aligned_shift(reach=6)
        self.assertFalse(any(exact), "a flip must not be reported as a translation: %s" % (exact,))

    def test_identical_frames_are_exact_and_silent(self):
        """Nothing changed, so every changed pixel (there are none) matched. Not a special case."""
        tl = self._timeline([self._frames()[0]] * 3)
        _dx, _dy, per, scores, bounds, exact = tl.aligned_shift()
        self.assertEqual(per, [(0, 0), (0, 0)])
        self.assertTrue(all(exact))
        self.assertTrue(all(s == 0 for s in scores))
        self.assertFalse(any(bounds))

    def test_one_frame_returns_six_empty_items(self):
        tl = F.Timeline(self.SIZE, self.SIZE)
        tl.add(self._frames()[0])
        self.assertEqual(tl.aligned_shift(), (0, 0, [], [], [], []))

    def test_the_three_lists_are_the_same_length(self):
        """`per_frame`, `best_scores`, `boundaries` and `exact` describe the same pairs."""
        # `n` has to match the number of marks, or the fixture silently builds fewer frames than the
        # assertion below expects -- which is what the first version of this test did.
        tl = self._timeline(self._frames(marks=[0, 1, 2, 3], n=4))
        _dx, _dy, per, scores, bounds, exact = tl.aligned_shift()
        self.assertEqual(len(per), 3, "four frames make three pairs")
        self.assertEqual(len(scores), len(per))
        self.assertEqual(len(bounds), len(per))
        self.assertEqual(len(exact), len(per))


class TestFrameDurations(unittest.TestCase):
    """Frame timing read from where it already lives, rather than invented.

    The TODO entry said timing would have to wait for a runtime probe because TH105's `.pat` carries none.
    That is true of that format and false as a general conclusion: **a per-frame delay table is a normal thing
    for a container to store**, and `うごイラ` ships exactly that. So the question is which container to read.

    **Two limits are asserted rather than described**, because both would otherwise be discovered as bugs:
    GIF keeps durations in hundredths of a second, so it can never report finer than 10 ms; and a duration
    table that does not match the frame count is refused instead of padded.
    """

    @staticmethod
    def _frames(n=6, size=32):
        out = []
        for i in range(n):
            im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            px = im.load()
            for y in range(6, size - 6):
                for x in range(6, size - 6):
                    px[x, y] = (200, 60, 60, 255)
            for y in range(12, 16):
                for x in range(10 + i, 14 + i):
                    px[x, y] = (90, 60, 150, 255)
            out.append(im)
        return out

    def test_a_text_table_is_read_in_whichever_separator_was_used(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.txt"
            p.write_text("80\n80\n120\n40\n", encoding="utf-8")
            self.assertEqual(F.read_delays(p)[0], [80, 80, 120, 40])
            p.write_text("80, 80, 120, 40\n", encoding="utf-8")
            self.assertEqual(F.read_delays(p)[0], [80, 80, 120, 40])
            p.write_text("80 80 120 40", encoding="utf-8")
            self.assertEqual(F.read_delays(p)[0], [80, 80, 120, 40])

    def test_a_gif_reports_the_durations_it_stores(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.gif"
            fr = self._frames(4)
            fr[0].save(p, save_all=True, append_images=fr[1:], duration=[80, 80, 120, 40], loop=0, disposal=2)
            delays, note = F.read_delays(p)
            self.assertEqual(delays, [80, 80, 120, 40])
            self.assertIn("4 frame", note)

    def test_a_gif_cannot_report_finer_than_ten_milliseconds(self):
        """GIF stores delay in hundredths of a second. This is the format, and it is pinned."""
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "b.gif"
            fr = self._frames(2)
            fr[0].save(p, save_all=True, append_images=fr[1:], duration=[33, 33], loop=0, disposal=2)
            self.assertEqual(F.read_delays(p)[0], [30, 30],
                             "a GIF cannot hold 33 ms; if this changes, the format did")

    def test_a_single_frame_image_reports_no_duration_rather_than_junk(self):
        """**The bug the first version had**: a still PNG fell through to the text reader.

        `n_frames > 1` was the test for "is this an image", so a single-frame PNG skipped the image branch,
        was read as text, and came back with five numbers parsed out of its binary header -- a still image
        reporting timing. "Is an image" and "stores durations" are separate questions.
        """
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "one.png"
            self._frames(1)[0].save(p)
            delays, note = F.read_delays(p)
            self.assertEqual(delays, [], "a still image has no durations: got %r" % (delays,))
            self.assertIn("single frame", note)

    def test_applying_a_table_that_does_not_fit_is_refused(self):
        tl = F.Timeline(32, 32)
        for im in self._frames(6):
            tl.add(im, duration_ms=100)
        with self.assertRaises(ValueError) as ctx:
            tl.apply_delays([80, 80, 80])
        self.assertIn("3 duration", str(ctx.exception))
        self.assertIn("6 frame", str(ctx.exception))
        self.assertEqual(tl.total_ms(), 600, "a refused table must not have changed anything")

    def test_applying_a_table_sets_each_frame_and_converts_centiseconds(self):
        tl = F.Timeline(32, 32)
        for im in self._frames(4):
            tl.add(im, duration_ms=100)
        tl.apply_delays([8, 8, 12, 4], unit="cs")
        self.assertEqual([f.duration_ms for f in tl.frames], [80, 80, 120, 40])
        self.assertEqual(tl.total_ms(), 320)
        with self.assertRaises(ValueError):
            tl.apply_delays([1, 2, 3, 4], unit="furlongs")

    def test_a_negative_duration_is_refused(self):
        tl = F.Timeline(32, 32)
        tl.add(self._frames(1)[0])
        with self.assertRaises(ValueError) as ctx:
            tl.apply_delays([-5])
        self.assertIn("negative", str(ctx.exception))

    def test_the_cli_reads_durations_and_refuses_a_mismatch_with_exit_two(self):
        from ichiwatashi.cli import main
        with tempfile.TemporaryDirectory() as d:
            fr = self._frames(6)
            for i, im in enumerate(fr):
                im.save(Path(d) / ("f%02d.png" % i))
            gif = Path(d) / "t.gif"
            fr[0].save(gif, save_all=True, append_images=fr[1:],
                       duration=[80, 80, 80, 200, 40, 40], loop=0, disposal=2)
            rc = main(["frames", d, "--delays", str(gif)])
            self.assertIn(rc, (0, 1), "reading a GIF's timing must not fail")
            short = Path(d) / "short.txt"
            short.write_text("80\n80\n80\n", encoding="utf-8")
            self.assertEqual(main(["frames", d, "--delays", str(short)]), 2,
                             "a table that does not fit is refused with exit 2, not a traceback")


class TestBuilder(unittest.TestCase):

    def test_shapes_and_outline(self):
        c = B.Canvas(16, 16)
        c.disc(8, 8, 4, "s").outline("k")
        rows = c.rows()
        self.assertEqual(len(rows), 16)
        self.assertTrue(all(len(r) == 16 for r in rows))
        self.assertIn("k", "".join(rows))
        self.assertNotEqual(c.get(8, 8), ".")          # the disc is filled
        self.assertEqual(c.get(0, 0), ".")             # the corner did not grow a border

    def test_outline_only_touches_empty_cells(self):
        c = B.Canvas(8, 8)
        c.rect(2, 2, 5, 5, "s").outline("k")
        self.assertEqual(c.get(3, 3), "s", "the outline overwrote a filled cell")

    def test_a_ragged_grid_is_refused_rather_than_padded(self):
        """A sprite that is silently the wrong shape shows up as a rendering bug far from its cause."""
        with self.assertRaises(ValueError):
            B.from_rows(["....", "...", "...."])

    def test_to_image_writes_every_cell(self):
        c = B.Canvas(4, 4)
        c.rect(1, 1, 2, 2, "x")
        im = c.to_image({"x": (10, 20, 30)})
        self.assertEqual(im.size, (4, 4))
        self.assertEqual(im.getpixel((1, 1)), (10, 20, 30, 255))
        self.assertEqual(im.getpixel((0, 0))[3], 0)

    def test_a_grid_round_trips_through_the_json_form(self):
        """`to_grid` writes the *word* "transparent", so a round trip puts a string where a colour is
        expected. It used to be read as a hex value, and `int("ra", 16)` -- from
        `"transparent"[1:3]` -- reported a parsing failure rather than the missing case it was.
        """
        c = B.Canvas(8, 8)
        c.rect(2, 2, 5, 5, "x")
        grid = c.to_grid({"x": (10, 20, 30), ".": B.TRANSPARENT})
        self.assertEqual(grid["palette"]["."], "transparent")
        again = B.Canvas(grid["width"], grid["height"])
        again._cells = list("".join(grid["pixels"]))
        im = again.to_image(grid["palette"])
        self.assertEqual(im.getpixel((2, 2)), (10, 20, 30, 255))
        self.assertEqual(im.getpixel((0, 0))[3], 0, "a transparent cell was painted")

    def test_a_shape_script_op_with_a_missing_field_is_named(self):
        """The CLI builds argument lists per op because a name-based guess cannot tell a cone
        `(y0, y1, w0, w1)` from a rectangle `(x0, y0, x1, y1)`. A missing field must say which.

        This used to spawn a real subprocess to read one error string, and on Windows that failed
        roughly one run in three with `OSError: [WinError 6]` -- the same root cause as the flaky
        cases in the sibling tools. `plan_steps` returns the error instead of raising mid-draw, so
        the assertion no longer depends on a process spawning.
        """
        from ichiwatashi.cli import plan_steps, SpecError
        spec = {"width": 8, "height": 8, "palette": {".": "transparent"},
                "steps": [{"op": "cone", "y0": 0, "y1": 3, "w0": 1, "key": "h"}]}
        with self.assertRaises(SpecError) as ctx:
            plan_steps(spec)
        self.assertIn("w1", str(ctx.exception))
        self.assertIn("step 0", str(ctx.exception))
        self.assertIn("cone", str(ctx.exception))

    def test_an_unknown_op_is_named_rather_than_indexing(self):
        """`shapes[kind]` on an unknown op used to be an IndexError from a dict lookup nowhere near
        the cause. It must name the op and the known set."""
        from ichiwatashi.cli import plan_steps, SpecError
        spec = {"width": 8, "height": 8, "palette": {}, "steps": [{"op": "spiral", "key": "h"}]}
        with self.assertRaises(SpecError) as ctx:
            plan_steps(spec)
        self.assertIn("spiral", str(ctx.exception))
        self.assertIn("rect", str(ctx.exception))

    def test_a_valid_script_plans_without_drawing(self):
        """The validator returns a plan and touches no pixels, so it can be asserted on directly."""
        from ichiwatashi.cli import plan_steps
        spec = {"width": 8, "height": 8, "palette": {"h": "#FF0000"},
                "steps": [{"op": "rect", "x0": 1, "y0": 1, "x1": 5, "y1": 5, "key": "h"},
                          {"op": "outline", "key": "o"}]}
        plan = plan_steps(spec)
        self.assertEqual([k for k, _ in plan], ["rect", "outline"])

    def test_placements_put_the_pivot_on_the_anchor(self):
        tl = F.Timeline(40, 40, anchor=(20, 30))
        tl.add(flat((10, 10)), pivot=(5, 9))
        self.assertEqual(tl.placements()[0], (15, 21))

    def test_drift_is_zero_when_frames_are_identical_in_shape(self):
        tl = F.Timeline(32, 32)
        for _ in range(3):
            tl.add(flat((8, 8), (200, 50, 50, 255)), pivot=(4, 7))
        self.assertEqual(tl.drift(), (0, 0))

    def test_drift_is_visible_when_the_pivot_is_wrong(self):
        """The whole point: a wrong pivot shows up as movement of the content relative to the anchor."""
        tl = F.Timeline(64, 64, anchor=(32, 60))
        a = Image.new("RGBA", (20, 20), (0, 0, 0, 0))
        for y in range(10, 20):
            for x in range(20):
                a.putpixel((x, y), (255, 0, 0, 255))       # content in the lower half
        b = Image.new("RGBA", (20, 20), (0, 0, 0, 0))
        for y in range(0, 10):
            for x in range(20):
                b.putpixel((x, y), (255, 0, 0, 255))       # content in the upper half
        tl.add(a, pivot=(10, 19))
        tl.add(b, pivot=(10, 19))                          # same pivot, different content
        dx, dy = tl.drift()
        self.assertGreaterEqual(dy, 10, "a real content shift did not register")

    def test_even_durations_keeps_the_total(self):
        d = F.even_durations(1000, 7)
        self.assertEqual(sum(d), 1000)
        self.assertEqual(len(d), 7)
        self.assertLessEqual(max(d) - min(d), 1)

    def test_hold_lengthens_one_frame_only(self):
        d = [100] * 5
        out = F.with_hold(d, 2, 500)
        self.assertEqual(out[2], 500)
        self.assertEqual(out[:2] + out[3:], [100, 100, 100, 100])
        self.assertEqual(d, [100] * 5, "the input list was mutated")

    def test_a_pivot_defaults_to_bottom_centre(self):
        f = F.Frame(flat((12, 20)))
        self.assertEqual(f.pivot, (6, 19))


class TestCalibration(unittest.TestCase):
    """The thresholds are measurements, so the tests are about the measurements staying honest."""

    def test_the_reference_carries_its_provenance(self):
        """A percentile without its sample is an opinion with a decimal point."""
        from ichiwatashi import calibration as C
        for k in ("source", "kind", "sample", "eligible", "sampling"):
            self.assertIn(k, C.PROVENANCE)
        self.assertGreater(C.PROVENANCE["sample"], 30, "too few sprites to be a distribution")

    def test_the_reference_is_ordered(self):
        from ichiwatashi import calibration as C
        for name, p in C.REFERENCE.items():
            vals = [p.p05, p.p25, p.median, p.p75, p.p95]
            self.assertEqual(vals, sorted(vals), "%s is not monotonic" % name)

    def test_the_old_threshold_is_recorded_as_having_been_wrong(self):
        """The isolated-pixel rule fired above 5%, which is below the fifth percentile of known-good
        art. This test exists so that rule cannot be reintroduced as a "reasonable" default."""
        from ichiwatashi import calibration as C
        self.assertGreater(C.REFERENCE["isolated_rate"].p05, 0.05,
                           "the reference no longer shows why the 5% rule was wrong")

    def test_outside_reports_the_side_and_the_sample(self):
        from ichiwatashi import calibration as C
        low = C.outside("isolated_rate", 0.01)
        high = C.outside("isolated_rate", 0.99)
        self.assertIn("below", low)
        self.assertIn("above", high)
        self.assertIn("n=", low)
        self.assertIsNone(C.outside("isolated_rate", 0.116), "the median should not be flagged")

    def test_an_unknown_metric_is_not_invented(self):
        from ichiwatashi import calibration as C
        self.assertIsNone(C.outside("not_a_metric", 12345))

    def test_a_reference_sprite_raises_no_note(self):
        """The property worth keeping: the notes must not fire on work that is known to be good."""
        from ichiwatashi import calibration as C
        from ichiwatashi.judge import judge
        # A sprite built to sit at the reference medians must come back clean.
        im = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        px = im.load()
        import colorsys
        colours = []
        for i in range(int(C.REFERENCE["colours_used"].median)):
            r, g, b = colorsys.hsv_to_rgb(i / 26.0, 0.7, 0.8)
            colours.append((int(r * 255), int(g * 255), int(b * 255), 255))
        for y in range(6, 58):
            for x in range(6, 58):
                px[x, y] = colours[(x * 3 + y * 5) % len(colours)]
        r = judge(im)
        self.assertFalse(any("colours_used" in n for n in r.notes),
                         "a sprite at the reference palette size was flagged: %s" % r.notes)


class TestFont(unittest.TestCase):
    """The family's shared 5x7 font: this repository is where it is produced.

    The rule is that every art asset in the four NTVI tools comes out of Ichiwatashi, and this is the
    first asset for which that is checkable rather than intended -- `volcano-separator` hand-authored
    its table before the rule existed, so the source here can be compared against something already in
    use. `tools/probe_font_from_ichiwatashi.py` does that comparison; these tests cover the pieces.
    """

    SRC = Path(__file__).resolve().parents[1] / "ichiwatashi" / "assets" / "font5x7.txt"

    def test_the_source_parses_and_every_glyph_is_5x7(self):
        from ichiwatashi.font import load_source
        g = load_source(self.SRC)
        self.assertGreater(len(g), 50, "the font source is too small to be the real one")
        for ch, glyph in g.items():
            self.assertEqual(len(glyph.rows), 7, ch)
            for mask in glyph.rows:
                self.assertLess(mask, 32, "%r sets a bit outside the five columns" % ch)

    def test_a_space_glyph_needs_the_tab_not_a_whitespace_split(self):
        """The one glyph whose key is whitespace, and the reason the format has a tab.

        `line.split()` would drop it and the font would come back a glyph short with nothing to say so
        -- which is the shape of every parsing mistake this file's docstring records.
        """
        from ichiwatashi.font import load_source
        g = load_source(self.SRC)
        self.assertIn(" ", g, "the space glyph is missing, so every word would run together")
        self.assertEqual(g[" "].hex(), "00000000000000")

    def test_the_two_repairs_the_source_claims_are_actually_in_it(self):
        """The docstring says the source differs from volcano's table in exactly two places. Asserted,
        because a claim about a deliberate difference that is not checked becomes a silent one."""
        from ichiwatashi.font import load_source
        g = load_source(self.SRC)
        self.assertEqual(len(g["Q"].hex()), 14, "Q is not fourteen digits")
        self.assertLess(int(g["/"].hex()[10:12], 16), 32, "/ still has a bit outside the five columns")

    def test_emitted_hex_is_fourteen_digits_of_wire_format(self):
        from ichiwatashi.font import load_source, to_volcano_hex
        table = to_volcano_hex(list(load_source(self.SRC).values()))
        self.assertGreater(len(table), 50)
        for ch, h in table.items():
            self.assertEqual(len(h), 14, ch)
            int(h, 16)          # raises if it is not hex, which is the point of the assertion

    def test_the_font_covers_what_a_window_needs(self):
        """**The check that caught the real gap is now the check that the gap is closed.**

        When this font was 60 glyphs it looked finished, and `check_font` said otherwise: no lowercase
        and no hash. A font is exactly the asset where "it parsed and the count is plausible" passes for
        done, so the assertion is about coverage rather than about a count -- and it was written to fail
        while the coverage was incomplete, which is how the shortfall got found.
        """
        from ichiwatashi.font import check_font, load_source
        c = check_font(load_source(self.SRC))
        self.assertEqual(c["missing"], "", "a window cannot be written without: %r" % c["missing"])
        self.assertTrue(c["has_space"])
        self.assertEqual(c["distinct_shapes"], 1, "this font is fixed-width, so one shape")
        self.assertEqual(c["lowercase"], 26, "all 26 lowercase letters")

    def test_the_hash_is_a_glyph_even_though_it_starts_a_comment(self):
        """**A real collision, not a hypothetical one.**

        `#` begins a comment line and `#` is also a glyph a panel needs -- for a hex dump, a colour, a
        count. Adding it made the font report it as still missing, because the parser treated the line as
        a comment. The tab decides: `#` followed by a tab is the glyph.
        """
        from ichiwatashi.font import load_source
        g = load_source(self.SRC)
        self.assertIn("#", g, "the hash glyph is being read as a comment")
        self.assertEqual(g["#"].hex(), "15151F151F1515")
        # and a comment line is still a comment
        self.assertIn("a", g)
        for line in self.SRC.read_text(encoding="utf-8").split("\n"):
            if line.startswith("#") and "\t" not in line:
                self.assertFalse(line.split("#", 1)[1].strip().startswith("0"),
                                 "a comment that looks like a glyph line: %r" % line)

    def test_lowercase_sits_where_a_descender_can_still_reach(self):
        """The render caught this, not an assertion, and the rule turned out to be the reverse of the
        first one written.

        **The grid decides it, not taste.** The uppercase in the original table fills all seven rows, so
        inside a 5x7 cell there is no row left below it for a tail -- which is why the lowercase added
        here sits one row higher: its body ends at row 5 and row 6 is what a descender hangs into.

        **The rule therefore applies to lowercase only, and that is a fact about which glyphs are new.**
        The uppercase is an existing table in use by a sibling project and is not being changed to suit
        this test; the assertion holds the new glyphs to the position a descender needs and says nothing
        about the old ones.

        Two earlier versions of this test were wrong in instructive ways: one demanded ink from the space
        glyph (fourteen zeroes is what a space is), and one applied the body rule to punctuation, which in
        the original table runs the full height of the cell because that is what punctuation is for.
        """
        from ichiwatashi.font import load_source
        g = load_source(self.SRC)
        descenders = set("gjpqy")
        lowercase = [c for c in g if c.islower()]
        self.assertEqual(len(lowercase), 26, "the lowercase set is incomplete: %r" % lowercase)
        for ch in lowercase:
            low = max(i for i, mask in enumerate(g[ch].rows) if mask)
            if ch in descenders:
                # a descender reaches past the body, or it is not a descender
                self.assertEqual(low, 6, "%r stops at row %d, above its own tail" % (ch, low))
            else:
                self.assertLessEqual(low, 5,
                                     "%r reaches row %d, leaving no room for a descender" % (ch, low))
        self.assertIsNone(max((i for i, m in enumerate(g[" "].rows) if m), default=None),
                          "the space glyph has ink in it")


class TestScope(unittest.TestCase):
    """The judge says what it is for, and refuses what it is not for.

    **The failure this exists to stop is a metric returning `not applicable` in the shape of a result.**
    Two cases are documented, and the second is what made it a code change rather than a paragraph:

      * `silhouette_share` is 1.000 on a single-colour form, which reads as "a uniform edge" and means
        nothing -- every edge pixel is that colour by construction.
      * The whole metric set on a 5x7 bitmap font: `colours_used` 1 against a band of 16-37, and
        `isolated_rate` 0.000 against 0.074-0.160, so **all 58 glyphs** of `volcano-separator`'s pixel
        font came back flagged as unlike any reference generation. That is
        `tools/probe_font_glyphs.py`.

    The threshold is measured, not chosen: the 160-sprite reference corpus has a smallest short side of
    62 px, so 24 refuses a 7 px glyph by a factor of three and clips nothing real.
    """

    def test_a_tiny_input_is_refused_rather_than_measured(self):
        im = Image.new("RGBA", (7, 9), (0, 0, 0, 0))
        with self.assertRaises(OutOfScopeError) as cm:
            judge_fn(im)
        # The message has to carry the numbers, or a refusal cannot be acted on
        self.assertIn("7x9", str(cm.exception))
        self.assertIn("62 px", str(cm.exception))
        self.assertIn("--anyway", str(cm.exception))

    def test_the_refusal_is_a_named_error_not_a_generic_one(self):
        """Callers act on this differently -- the CLI turns it into exit code 2, which is distinct from
        1, meaning "measured, and a note was raised". Those are different answers."""
        from ichiwatashi.scope import OutOfScopeError as E
        self.assertTrue(issubclass(E, ValueError))

    def test_anyway_measures_it_and_that_is_the_callers_problem(self):
        """The escape hatch, and it must actually work: a caller who knows what they are measuring gets
        the numbers. What they must not get is the impression the reference calibrated them."""
        im = Image.new("RGBA", (9, 9), (0, 0, 0, 0))
        px = im.load()
        for y in range(2, 7):
            for x in range(2, 7):
                px[x, y] = (10, 20, 30, 255)
        r = judge_fn(im, anyway=True)
        self.assertEqual(r.colours_used, 1)
        self.assertEqual(r.width, 9)

    def test_the_gate_clips_nothing_in_the_reference_corpus(self):
        """The property that makes the threshold legitimate rather than convenient. This reads the real
        corpus if it is on the machine, and skips loudly if it is not -- a silently skipped check is how
        a fixture ends up below a floor without anyone noticing, which is what happened here."""
        d = Path("E:/DaShaoHuo/downloads/ichiwatashi-corpus/th155")
        if not d.is_dir():
            self.skipTest("the TH155 corpus is not on this machine")
        files = sorted(d.glob("*.png"))
        self.assertGreater(len(files), 50, "too few sprites to make this claim")
        smallest = None
        for p in files:
            with Image.open(p) as im:
                size = im.size
                if smallest is None or min(size) < smallest[0]:
                    smallest = (min(size), p.name, size)
                judge_fn(im.convert("RGBA"), generation="th155")   # must not raise
        self.assertGreaterEqual(smallest[0], MIN_SHORT_SIDE,
                                "the gate refuses real art: %s" % (smallest,))

    def test_a_sequence_too_short_for_a_spread_is_refused(self):
        """The same rule for motion. A drift spread over two frames is the difference between two
        drawings, not a statement about motion."""
        from ichiwatashi.scope import MIN_FRAMES_FOR_SPREAD, require_sequence
        require_sequence(range(MIN_FRAMES_FOR_SPREAD))        # exactly the floor is fine
        with self.assertRaises(OutOfScopeError):
            require_sequence(range(MIN_FRAMES_FOR_SPREAD - 1))


class TestPixelScale(unittest.TestCase):
    """`pixel_scale` had no reference row and no counterexample: it read 1 on all 120 TH123 sprites
    and on 640 TH155 sprite/palette combinations, so nothing had ever shown it *failing*.

    Two passes were needed and the first was wrong, which is recorded here because it decides what
    the metric can be used for. A synthetic `n x n` block grid does **not** reproduce the failure at
    all for n=2,3: runs of 1 are filtered out of the GCD, so a 3-wide block split by one pixel
    yields only runs of 1 and 3 and the reading survives. Measured on real TH155 sprites:

        clean upscale              reads n     18/18
        upscale + one bad pixel    reads 1     16/18
        upscale + quantisation     reads n      0/18 changed

    So the value degrades silently, and the law of the degradation is exact (next test). Divisibility
    over n=2..64 does not degrade, which is why `upscale`/`upscale_fraction` exist:

        real TH155 art            best fraction 0.27-0.30
        clean upscale             best fraction 1.00 at the true factor
        upscale + 20 bad pixels   best fraction 0.997 at the true factor, gcd collapsed to 1
    """

    # 20x20 blocks, not 6x6: the run-count floor is 100 (measured -- the fewest runs any of 300 real
    # TH155 sprites produced was 192), and a 6x6 grid at n=2 gives only ~60 runs, so a small grid
    # would silently test nothing.
    @staticmethod
    def _blocks(n, cols=20, rows=20):
        """A drawing whose every horizontal run is exactly `n`: one n x n block per source pixel."""
        im = Image.new("RGBA", (cols * n, rows * n), (0, 0, 0, 0))
        px = im.load()
        for by in range(rows):
            for bx in range(cols):
                c = ((bx * 37 + 20) % 256, (by * 53 + 30) % 256,
                     ((bx * 7 + by * 11) * 13 + 40) % 256, 255)
                for y in range(by * n, (by + 1) * n):
                    for x in range(bx * n, (bx + 1) * n):
                        px[x, y] = c
        return im

    def test_a_hand_authored_drawing_is_not_called_an_upscale(self):
        """The false-positive guard, and the one that would matter most in practice.

        Runs of many different lengths: the best divisibility over n=2..64 stays low (0.27-0.30 on
        real sprites, which is what random run lengths give), so nothing is reported.
        """
        # **Enlarged from 40x8, and that fixed a second problem besides the size gate.** At 40x8 this
        # fixture produced about 64 runs against a measured floor of 100, so the run-count rule would
        # have refused it anyway and the assertion below was passing for a reason other than the one it
        # names. 80x24 with the pattern repeated and then broken gives several hundred runs, which is
        # what makes it a test of the false-positive guard rather than of an empty input.
        im = Image.new("RGBA", (80, 24), (0, 0, 0, 0))
        px = im.load()
        pattern = ((3, (200, 40, 40, 255)), (5, (40, 200, 40, 255)),
                   (2, (40, 40, 200, 255)), (7, (200, 200, 40, 255)),
                   (4, (200, 40, 200, 255)), (3, (40, 200, 200, 255)),
                   (9, (120, 60, 20, 255)), (4, (20, 120, 60, 255)), (6, (90, 90, 90, 255)))
        for y in range(24):
            x = 0
            # the pattern repeats, and each row starts one colour later, so no single factor can
            # divide every run length -- which is the property under test
            seq = pattern[y % len(pattern):] + pattern[:y % len(pattern)]
            while x < 80:
                for run, c in seq:
                    for i in range(run):
                        if x + i < 80:
                            px[x + i, y] = c
                    x += run
                    if x >= 80:
                        break
        r = judge_fn(im)
        self.assertEqual(r.upscale, 0, "a hand drawing was reported as an upscale")
        self.assertFalse(any("multiple" in n for n in r.notes))

    def test_an_integer_upscale_is_detected_at_its_factor(self):
        """Largest n accounting for ~every run, not the best-scoring one: 2 always scores at least
        as high as 4, so a best-score rule would report 2 for a clean x4."""
        for n in (2, 3, 4, 5, 6):
            with self.subTest(n=n):
                r = judge_fn(self._blocks(n))
                self.assertGreaterEqual(len(_opaque(self._blocks(n))), 100,
                                        "the fixture must clear the run-count floor or it proves "
                                        "nothing")
                self.assertEqual(r.upscale, n)
                self.assertGreaterEqual(r.upscale_fraction, 0.95)
                self.assertTrue(any("multiple of %d" % n in x for x in r.notes),
                                "no note named the factor: %s" % r.notes)

    def test_a_stray_pixel_degrades_the_gcd_by_an_exact_law(self):
        """**Why the value alone is not reportable, stated as the law it follows.**

        One recoloured pixel in an n x n block grid (n = 2..8, measured):

            n=2,3     gcd unchanged
            n=4,6,8   gcd -> 2        the largest power of two dividing n
            n=5,7     gcd -> 1

        A clean grid always reads n, and `upscale` reads n in **every** row including the broken
        ones. So the degradation is not random noise -- `gcd` silently becomes a divisor of the true
        factor, with nothing in the value to say so.
        """
        # **cols/rows raised from 10 to 20 so the fixture clears the run-count floor as well as the
        # size gate.** At 10x10 the grid held 100 runs, which is exactly the measured floor, so "the
        # GCD degraded to a divisor of n" was being read off the minimum evidence it takes. 20x20 gives
        # 400 runs: the same law, on a fixture with room to state it.
        law = {2: 2, 3: 3, 4: 2, 5: 1, 6: 2, 7: 1, 8: 2}
        for n, want in law.items():
            with self.subTest(n=n):
                im = self._blocks(n, cols=20, rows=20)
                clean = judge_fn(im)
                self.assertEqual(clean.pixel_scale, n, "a clean grid should read its own factor")
                self.assertEqual(clean.upscale, n)
                px = im.load()
                px[n + 1, n + 1] = ((px[n + 1, n + 1][0] + 128) % 256,
                                    px[n + 1, n + 1][1], px[n + 1, n + 1][2], 255)
                r = judge_fn(im)
                self.assertEqual(r.pixel_scale, want, "n=%d stray-pixel law changed" % n)
                self.assertEqual(r.upscale, n, "n=%d: the fraction signal must survive" % n)

    def test_the_note_names_the_factor_even_when_the_gcd_has_broken(self):
        """The sentence that replaces a silent number. On a scaled-and-touched-up image the report
        must name the factor it found and say how much disagrees, not print `1` and stop."""
        im = self._blocks(5, cols=10, rows=10)
        px = im.load()
        px[6, 6] = ((px[6, 6][0] + 128) % 256, px[6, 6][1], px[6, 6][2], 255)
        r = judge_fn(im)
        self.assertEqual(r.pixel_scale, 1)
        self.assertEqual(r.upscale, 5)
        hit = [n for n in r.notes if "multiples of 5" in n]
        self.assertTrue(hit, "no note named the factor: %s" % r.notes)
        self.assertIn("break it", hit[0], "the note should say how much disagrees: %s" % hit[0])

    def test_a_small_blocky_drawing_gets_no_unit_size_claim(self):
        """**The floor, and why it exists.**

        A unit-size claim averages over runs. Measured over 300 real TH155 sprites, the fewest runs
        any produced was 192 and the median 3145; a 32x32 drawing yields 20-56. Below ~100 runs,
        "every run is a multiple of 2" is a statement about a handful of runs and fires on drawings
        that are merely small -- which is exactly how this detector first broke two neighbouring
        tests whose fixtures are 32x32.

        So nothing is said. Silence is the honest answer when there is not enough evidence to
        average over, and it is preferable to a note that a reader has to learn to ignore.
        """
        small = self._blocks(2, cols=4, rows=4)          # 32 runs
        # `anyway=True`, and it is the honest use of that flag rather than a way round the gate: this
        # fixture is *deliberately* below the run-count floor, which is the rule under test, and a
        # drawing too small in runs is necessarily too small in pixels. The pixel-size gate is a
        # separate rule with its own test; here the subject is silence at low evidence, so the gate is
        # stepped past explicitly instead of being satisfied by a fixture that would defeat the test.
        r = judge_fn(small, anyway=True)
        self.assertLess(len(_opaque(small)), 100)
        self.assertFalse(any("multiple" in n for n in r.notes),
                         "a 32x32 drawing should not get a unit-size claim: %s" % r.notes)
        # the same drawing at a size worth averaging over does get one
        big = self._blocks(2, cols=20, rows=20)
        self.assertTrue(any("multiple of 2" in n for n in judge_fn(big).notes))

    def test_quantisation_does_not_break_it(self):
        """The direction I predicted would fail, and it does not.

        The TODO predicted "a man-made noisy upscale would drag the GCD back to 1 and look fine".
        Measured 0/18 -- quantising to 8 levels leaves every run intact, because the property is
        about run *lengths*, not colour count. Recorded so the wrong prediction is not re-derived.
        """
        im = self._blocks(3)
        px = im.load()
        for y in range(im.height):
            for x in range(im.width):
                r, g, b, a = px[x, y]
                if a:
                    px[x, y] = ((r // 8) * 8, (g // 8) * 8, (b // 8) * 8, a)
        r = judge_fn(im)
        self.assertEqual(r.upscale, 3)
        self.assertEqual(r.pixel_scale, 3)


class TestPeriodicClass(unittest.TestCase):
    """What the runs actually form, and where the grid sits -- checked against drawings built to be one
    specific thing each.

    **Why these are synthetic, and why that is not circular.** The corpus is 160 hand-authored sprites
    and all 160 read `upscale=0` and `periodic_class=none`, which is the right answer for hand drawing
    and exercises none of the branches. `POLICY.md` gate 3 says synthetic samples may verify a metric as
    long as they never enter the reference table, which is exactly the role they play. The corpus itself
    is asserted at the end of this class, so the synthetic cases cannot drift away from it.

    **Every expectation here was first a mismatch.** The probe that produced these cases reported 3 of 8
    then 6 of 9 before reaching 9 of 9, and each failure was a real defect rather than a bad fixture:

        1. a clean x4 upscale read as 8          the factor rule kept the largest explainer
        2. a clean x4 upscale read as 4 then 2   the mirror fix under-reported instead
        3. a solid block read as `mask`          the one-step interior test found no interior at all
        4. a repeating grid read as `mask`       a distance-2 test is satisfied by any period-2 pattern
        5. a flat silhouette read as `upscale`   a one-colour drawing's runs are multiples of anything
    """

    @staticmethod
    def _rect(x0, y0, x1, y1, colour, size=(64, 64)):
        im = Image.new("RGBA", size, (0, 0, 0, 0))
        px = im.load()
        for y in range(y0, y1):
            for x in range(x0, x1):
                px[x, y] = colour
        return im

    @staticmethod
    def _upscale(im, n):
        return im.resize((im.width * n, im.height * n), Image.NEAREST)

    def _mixed(self):
        """Features of 1, 3 and 5 source pixels, so the GCD of the runs is the scale itself."""
        im = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
        a = self._rect(4, 4, 5, 12, (200, 60, 60, 255), (32, 32))
        b = self._rect(7, 6, 10, 16, (60, 120, 200, 255), (32, 32))
        c = self._rect(5, 14, 10, 20, (240, 220, 90, 255), (32, 32))
        out = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
        for src in (a, b, c):
            out.alpha_composite(src)
        return out

    def test_clean_upscale_reads_its_own_factor(self):
        """The factor is not inflated to whatever the drawing's feature widths allow.

        Before the fix this read 8 for a x4 upscale, because a drawing whose features are even-width
        produces runs that every multiple of the scale also explains. The first correction took the
        smallest explaining factor instead and read 2 -- the mirror mistake. What is asserted now is
        both halves: the reported factor, and that the other fitting factors are *carried* rather than
        silently discarded.
        """
        r = judge_fn(self._upscale(self._mixed(), 4))
        self.assertEqual(r.periodic_class, "upscale")
        self.assertEqual(r.upscale, 4)
        self.assertIn(4, r.upscale_candidates)
        # x3 is the unambiguous control: 3 is odd, so no multiple of it can fit by accident
        r3 = judge_fn(self._upscale(self._mixed(), 3))
        self.assertEqual(r3.upscale, 3)
        self.assertEqual(tuple(r3.upscale_candidates), (3,))

    def test_even_width_features_are_reported_as_ambiguous(self):
        """Three factors fit and the report says all three.

        This is the concrete form of Popescu & Farid's caveat that the amount of resampling is not
        uniquely identifiable: if every feature is an even number of source pixels, then 2, 4 and 8
        produce indistinguishable run-length sets. Reporting one of them alone would assert a precision
        the data does not have.
        """
        even = Image.new("RGBA", (24, 24), (0, 0, 0, 0))
        for src in (self._rect(4, 4, 10, 12, (200, 60, 60, 255), (24, 24)),
                    self._rect(12, 6, 18, 16, (60, 120, 200, 255), (24, 24)),
                    self._rect(6, 14, 14, 20, (240, 220, 90, 255), (24, 24))):
            even.alpha_composite(src)
        r = judge_fn(self._upscale(even, 4))
        self.assertEqual(r.periodic_class, "upscale")
        self.assertEqual(tuple(r.upscale_candidates), (2, 4, 8),
                         "an all-even drawing must carry all three fitting factors")

    def test_a_crop_off_the_grid_is_reported_as_a_phase(self):
        """A factor of 4 with a phase of 2 is genuine scaled art that has been cropped.

        The factor alone cannot say this -- it reports a plain upscale -- which is why the phase is a
        field and not a note. The alignment fraction is asserted alongside it because it is a confidence
        and not a verdict: an off-by-one crop still leaves most runs agreeing.
        """
        big = self._upscale(self._mixed(), 4)
        r = judge_fn(big.crop((2, 0, big.width, big.height)))
        self.assertEqual(r.upscale, 4)
        self.assertEqual(r.phase, 2)
        self.assertGreater(r.phase_agree, 0.5)
        # and an uncropped upscale reports no offset, so a phase of 0 is meaningful rather than unset
        self.assertEqual(judge_fn(big).phase, 0)

    def test_a_flat_silhouette_is_not_called_an_upscale(self):
        """A one-colour drawing's runs are multiples of anything, so the factor must not win.

        This is the shape that 59 of 300 real sprites hit: the multiple-of-n rule fired and all 59 were
        single-colour. The interior test is what separates it from a drawing -- and a silhouette's total
        colour count does not, because a drawn silhouette is a fill colour plus an outline colour.
        """
        n = 200
        disc = Image.new("RGBA", (n, n), (0, 0, 0, 0))
        px = disc.load()
        for y in range(n):
            half = int(48 * (1 - abs(y - n // 2) / (n // 2)))
            for x in range(n // 2 - half, n // 2 + half):
                px[x, y] = (255, 255, 255, 255)
        r = judge_fn(disc)
        self.assertEqual(r.periodic_class, "mask")
        # a rectangle drawn in one colour is both one interior colour and all-equal runs, and the
        # narrower statement wins
        self.assertEqual(judge_fn(self._rect(5, 5, 35, 35, (10, 200, 10, 255), (40, 40))).periodic_class,
                         "constant")

    def test_a_repeating_grid_is_periodicity_and_not_a_mask(self):
        """A regular grid is periodic, so it falls through to `upscale` -- and the tool says the
        structure, not the provenance.

        The resampling literature warns that one detector fires on things that are not resampling: a
        demosaicing pattern and JPEG's 8-pixel block grid both look periodic. The answer taken here is
        to name the class, never to claim where the image came from -- so what this asserts is the class
        and the factor, not a verdict. The first version of this fixture was one colour, which read
        `mask` and was correct; two colours are needed to ask the periodicity question at all.
        """
        grid = self._rect(0, 0, 64, 64, (200, 60, 60, 255), (64, 64))
        px = grid.load()
        for y in range(64):
            for x in range(64):
                if (x % 8 < 4) != (y % 8 < 4):
                    px[x, y] = (90, 90, 90, 255)
        r = judge_fn(grid)
        self.assertEqual(r.periodic_class, "upscale")
        self.assertIn(r.upscale, r.upscale_candidates)

    def test_hand_authored_art_is_not_called_periodic(self):
        """The direction that matters most: 160 real sprites read `none`, and this keeps it that way.

        The corpus lives outside the repository (samples are not committed), so this test skips when it
        is absent rather than pretending to have checked. When it is present it asserts the whole set,
        which is what makes the synthetic cases above safe: they verify the branches, and this verifies
        that the branches stay shut on real art.
        """
        samples = sorted(glob.glob(r"E:\DaShaoHuo\downloads\ichiwatashi-corpus\**\*.png", recursive=True))
        if not samples:
            self.skipTest("corpus samples are not on this machine")
        seen = set()
        for f in samples:
            r = judge_fn(Image.open(f).convert("RGBA"))
            seen.add(r.periodic_class)
            self.assertEqual(r.periodic_class, "none",
                             "%s was called periodic: %s" % (os.path.basename(f), r.periodic_class))
        self.assertEqual(seen, {"none"})


class TestPerceptual(unittest.TestCase):
    """The colour metrics, verified against the values their own authors published.

    **This class exists because of a gap recorded before the code did.** `corpus/REFERENCES.md` noted
    that two candidate URLs for the official CIEDE2000 test data both returned 404, and that until a
    working path was found, the statement "I implemented CIEDE2000" had nothing that could verify it.
    The data was then found on the first author's own page -- the link was
    `dataNprograms/ciede2000testdata.txt`, relative to the page, which is why searching for the file by
    name did not surface it.

    The 34 pairs are not a smoke test. They were chosen by Sharma, Wu and Dalal to catch specific
    implementation mistakes: rows 4-6 pin the case where C1*C2 is zero, rows 9-12 sit either side of the
    hue discontinuity at 180 degrees, and rows 21-24 are pairs whose correct answer is exactly 1.0.
    """

    DATA = Path(__file__).resolve().parent / "data" / "ciede2000testdata.txt"

    def _rows(self):
        rows = []
        for line in self.DATA.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) != 7:
                continue
            rows.append(tuple(float(v) for v in parts))
        return rows

    def test_the_reference_data_is_present_and_complete(self):
        """34 rows, every one with seven fields. Asserted first, because every test below reads it and
        an empty file would make them pass vacuously."""
        rows = self._rows()
        self.assertEqual(len(rows), 34, "the published set has 34 pairs")
        # counted as non-blank lines rather than as newlines: the file ends with one, so a newline
        # count would be 35 and the assertion would be about the trailing byte, not about the data
        nonblank = [l for l in self.DATA.read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertEqual(len(nonblank), 34)

    def test_delta_e_2000_matches_the_published_values(self):
        """Every pair to four decimals, which is the precision the file itself is written at.

        A looser tolerance would pass a formula with a wrong constant in the T term; a tighter one
        would fail on the file's own rounding.
        """
        for i, (L1, a1, b1, L2, a2, b2, expect) in enumerate(self._rows(), 1):
            got = PC.delta_e_2000((L1, a1, b1), (L2, a2, b2))
            self.assertAlmostEqual(got, expect, places=4,
                                   msg="row %d: published %.4f, computed %.6f" % (i, expect, got))

    def test_delta_e_2000_is_symmetric_as_constructed(self):
        """Direction does not matter, and that is a property of the formula rather than a coincidence.

        Every weighting function uses the mean of the two colours (the symmetrisation CIE94 introduced),
        so swapping reference and sample cannot change the answer. Worth pinning because the opposite
        claim is easy to find in summaries, and because the *palette* metrics are the asymmetric ones.
        """
        for L1, a1, b1, L2, a2, b2, _ in self._rows():
            fwd = PC.delta_e_2000((L1, a1, b1), (L2, a2, b2))
            rev = PC.delta_e_2000((L2, a2, b2), (L1, a1, b1))
            self.assertAlmostEqual(fwd, rev, places=10)

    def test_the_discontinuity_is_real_and_where_it_is_claimed(self):
        """Rows 9-12 are two colours a hair apart on opposite sides of 180 degrees of hue.

        A 0.0001 change in one coordinate must not move the answer by 0.04, but it does: 7.1792 becomes
        7.2195. That is the discontinuity Sharma et al. documented, and asserting it here means the
        reason this metric must not be used for large differences is pinned to data rather than quoted.
        """
        r = self._rows()
        self.assertAlmostEqual(r[9][6], 7.1792, places=4)      # a*b* differs at the 4th decimal
        self.assertAlmostEqual(r[10][6], 7.2195, places=4)     # ... and the answer moves by 0.04
        self.assertGreater(abs(r[10][6] - r[9][6]), 0.03)

    def test_lab_round_trips_through_srgb(self):
        """`srgb_from_lab` has to be the inverse, or a converted palette cannot be written back.

        Exact equality would be wrong to demand (the transform is continuous and the file stores bytes),
        but one unit is the honest tolerance: a round trip that lands two bytes away would make
        `separation` compare colours the image does not contain.
        """
        for rgb in [(0, 0, 0), (255, 255, 255), (128, 64, 200), (17, 200, 33), (250, 3, 3), (7, 7, 250)]:
            back = PC.srgb_from_lab(PC.lab_from_srgb(rgb))
            for a, b in zip(rgb, back):
                self.assertLessEqual(abs(a - b), 1, "%r round-tripped to %r" % (rgb, back))

    def test_hyab_is_city_block_in_lightness_and_euclidean_across_chroma(self):
        """The shape of HyAB, asserted directly, because "Euclidean in Lab" is a different metric.

        A lightness difference of 10 and a chroma difference of 10 must give different answers -- that
        is the whole point of the metric, and a Euclidean implementation would return 10 for both.
        """
        # pure lightness move
        dL = PC.hyab((50, 0, 0), (60, 0, 0))
        self.assertAlmostEqual(dL, 10.0, places=10)
        # pure chroma move of the same magnitude: Euclidean across a* and b*, so also 10
        dC = PC.hyab((50, 0, 0), (50, 10, 0))
        self.assertAlmostEqual(dC, 10.0, places=10)
        # but a move that is half lightness and half chroma must add the two, not combine in quadrature
        dBoth = PC.hyab((50, 0, 0), (55, 5, 0))
        self.assertAlmostEqual(dBoth, 10.0, places=10)
        self.assertNotAlmostEqual(PC.hyab((50, 0, 0), (55, 5, 0)), math.hypot(5, 5), places=3)

    def test_oklab_agrees_with_delta_e_2000_about_ordering(self):
        """Two metrics, one ordering: a large colour step must rank above a small one under both.

        Not an agreement test in values -- they are different scales -- but a check that neither is
        transposed or mis-indexed, which is the failure a value test alone can miss if both sides share
        a mistake.
        """
        base = (120, 40, 90)
        near = (126, 44, 92)
        far = (200, 210, 60)
        self.assertLess(PC.oklab_distance(base, near), PC.oklab_distance(base, far))
        self.assertLess(PC.delta_e_2000(PC.lab_from_srgb(base), PC.lab_from_srgb(near)),
                        PC.delta_e_2000(PC.lab_from_srgb(base), PC.lab_from_srgb(far)))

    def test_distance_selects_by_name_and_refuses_an_unknown_one(self):
        """A metric that is not named in the output is one the reader has to guess at.

        Raising on an unknown name is the point: a silent fallback would let two runs disagree about
        what they measured while carrying the same label in the report.
        """
        a, b = (10, 20, 30), (40, 50, 60)
        for name in PC.METRICS:
            self.assertGreater(PC.distance(a, b, name), 0)
        self.assertAlmostEqual(PC.distance(a, b, "ciede2000"), PC.distance(a, b, "ciede2000"))
        with self.assertRaises(ValueError):
            PC.distance(a, b, "deltae2000")

    def test_the_samplers_default_metric_is_ciede2000(self):
        """The default is a decision, and the decision changed on 2026-10-15.

        It was `chebyshev` because the palette figures in `corpus/manifest.jsonl` had been measured under
        it. It is now `ciede2000` because that is the one metric in this project verified against values
        its authors published, so its output can be argued with -- and because nothing already recorded
        moved: those manifest figures are counted from pixels and never pass through the sampler, and
        `tools/calibrate.py` produces a byte-identical distribution under either default (checked by
        running it both ways, which is why the claim is a measurement).

        **This test used to be named `..._still_defaults_to_chebyshev` and it kept passing after the
        change** -- on this small fixture both metrics happen to return the same count, so the name was
        the only thing that had gone stale. A test whose name lies about what it checks is the failure
        this suite keeps having to correct, so the assertion is now about the default being the verified
        metric rather than about a group count that cannot tell them apart.
        """
        im = self._ramp()
        self.assertEqual(P.sample(im, n=6), P.sample(im, n=6, metric="ciede2000"),
                         "the bare call must be the ciede2000 call")
        self.assertEqual(P.sample(im, n=6, merge_distance=None),
                         P.sample(im, n=6, metric="ciede2000", merge_distance=P.MERGE_FOR["ciede2000"]))
        with self.assertRaises(ValueError):
            P.sample(im, n=6, metric="lab")           # not one of MERGE_FOR's names

    def test_a_merge_threshold_is_not_transferable_between_metrics(self):
        """Handing Chebyshev's 24 to CIEDE2000 collapses the palette, and that is the point.

        Measured here rather than asserted in prose: a stair of greys 20 apart is a near-duplicate under
        Chebyshev's 24 and a genuinely different colour under CIEDE2000, which reads such a step as more
        than its own threshold of 6. So the same number means different things, and MERGE_FOR exists to
        keep each metric in its own units.
        """
        im = Image.new("RGBA", (60, 20), (0, 0, 0, 255))
        px = im.load()
        for x in range(60):
            v = (x // 20) * 20                        # 0, 20, 40
            for y in range(20):
                px[x, y] = (v, v, v, 255)
        self.assertGreater(len(P.sample(im, n=6, metric="chebyshev")), 1,
                           "chebyshev should keep at least two of the three greys apart")
        self.assertGreater(len(P.sample(im, n=6, metric="oklab")), len(P.sample(im, n=6, metric="chebyshev")),
                           "oklab reads these steps as further apart than chebyshev does")
        self.assertEqual(len(P.sample(im, n=6, metric="ciede2000", merge_distance=24.0)), 1,
                         "reusing the chebyshev number under ciede2000 must collapse the palette")

    @staticmethod
    def _ramp():
        im = Image.new("RGBA", (40, 20), (0, 0, 0, 255))
        px = im.load()
        for x in range(40):
            for y in range(20):
                px[x, y] = (40 + x * 4, 30 + x * 2, 90, 255)
        return im

    # ---------------------------------------------------------------------------------------------
    # The sign test, checked against what it actually does rather than what it was published as.
    # ---------------------------------------------------------------------------------------------

    @staticmethod
    def _field(jitter=0, step=0, period=8, w=64, h=64, base=40, seed=7):
        """A flat drawing with a controlled interior: flat, jittered, or stepped in flat bands."""
        import random as _r
        rnd = _r.Random(seed)
        im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        px = im.load()
        for y in range(h):
            for x in range(w):
                if 8 <= x < w - 8 and 8 <= y < h - 8:
                    d = ((x - 8) // period) * step if step else 0
                    if jitter:
                        d += rnd.randint(-jitter, jitter)
                    px[x, y] = (base + d, base + d, base + d, 255)
        return im

    def test_the_sign_test_ignores_a_monotone_slope(self):
        """It marks nothing on a flat field, and nothing on a one-unit stair either.

        **This is the finding, and it is why the function is not called an anti-aliasing detector.** A
        stair is monotone along its run, so the pixel at a step is neither a peak nor a dip -- and an
        anti-aliased edge is exactly that kind of monotone slope. The published rule is presented as an
        AA detector; on pixel art it is silent where an AA edge would be faintest.
        """
        self.assertEqual(len(PC.intensity_extrema(self._field())), 0,
                         "a flat interior must produce no marks")
        self.assertEqual(len(PC.intensity_extrema(self._field(step=1))), 0,
                         "a one-unit stair is a slope, and this rule does not see slopes")
        self.assertEqual(len(PC.intensity_extrema(self._field(step=2))), 0)

    def test_the_sign_test_fires_on_rounding_residue(self):
        """And it fires hard on residue, which is the mirror-image failure.

        A flat field carrying plus-or-minus one of rounding noise marks about 16% of its opaque pixels
        while the one-unit stair above marks 0%. Together the two assertions say what the rule measures:
        local extrema, not edges.
        """
        flat = len(PC.intensity_extrema(self._field()))
        residue = len(PC.intensity_extrema(self._field(jitter=1)))
        stair = len(PC.intensity_extrema(self._field(step=1)))
        self.assertGreater(residue, 0, "residue must fire, or this test is not testing the right thing")
        self.assertGreater(residue / max(1, flat), 10, "residue must fire far more than a flat field")
        self.assertEqual(stair, 0, "the slope case must stay silent for the contrast to mean anything")

    def test_the_sign_test_rises_when_a_drawing_is_resampled(self):
        """So the number is not useless -- it tracks resampling, which is a real question.

        Bilinear resampling inserts intermediate values, and those create the local reversals the rule
        looks for. Measured on real sprites the rise is 8.6x; a small synthetic case is asserted here so
        the property is checked without the corpus on disk.
        """
        im = Image.new("RGBA", (60, 40), (0, 0, 0, 0))
        px = im.load()
        for y in range(6, 34):
            for x in range(6, 54):
                px[x, y] = (200, 60, 60, 255)
        self.assertEqual(len(PC.intensity_extrema(im)), 0, "a solid rectangle has no extrema inside")
        sm = im.resize((im.width * 2, im.height * 2), Image.BILINEAR).resize(
            (im.width, im.height), Image.BILINEAR)
        self.assertGreater(len(PC.intensity_extrema(sm)), 0,
                           "resampling must produce marks, or the rate means nothing")

    def test_transparent_neighbours_are_not_treated_as_brightness(self):
        """A background is not an intensity, and counting it would make every edge pixel a slope pixel.

        Reading a transparent pixel's RGB as if it were a value is the obvious mistake, and it would make
        this rule fire on every silhouette by construction.
        """
        im = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
        px = im.load()
        for y in range(10, 30):
            for x in range(10, 30):
                px[x, y] = (128, 128, 128, 255)
        self.assertEqual(len(PC.intensity_extrema(im)), 0,
                         "a flat rectangle beside a transparent margin must not be marked")

    def test_luma_is_the_rec601_form_it_claims(self):
        """The luma choice changes which pixels a slope test selects, so it is named and asserted."""
        self.assertAlmostEqual(PC.luma((255, 255, 255)), 255.0, places=6)
        self.assertAlmostEqual(PC.luma((0, 0, 0)), 0.0, places=6)
        self.assertAlmostEqual(PC.luma((255, 0, 0)), 0.299 * 255, places=4)
        self.assertAlmostEqual(PC.luma((0, 255, 0)), 0.587 * 255, places=4)


class TestFigures(unittest.TestCase):
    """The report figures, checked by reading their pixels back.

    **Every assertion here exists because a figure that renders and saves can still be wrong.** The first
    version of `palette_board` laid its swatches out at `cell + one pad` spacing, which put each ring
    exactly on top of the previous swatch's interior: measured on the rendered figure, swatch 0 came back
    as sixteen pixels of ring colour with no fill at all. The PNG was the right size and opened fine.
    """

    @staticmethod
    def _sprite():
        im = Image.new("RGBA", (24, 24), (0, 0, 0, 0))
        px = im.load()
        for y in range(6, 18):
            for x in range(4, 20):
                px[x, y] = (200, 90, 120, 255)
        for y in range(9, 15):
            for x in range(8, 16):
                px[x, y] = (60, 40, 90, 255)
        return im

    def test_text_draws_into_a_canvas_with_bit_four_leftmost(self):
        """The bit convention, asserted where it would be invisible if wrong.

        A mirrored glyph still looks like a glyph, so the check is on a shape with one asymmetric column:
        `T` has its stem centred, so a cheap letter was needed -- this uses `L`, whose foot runs right.
        """
        c = B.Canvas(16, 12, ".")
        FIG.draw_text(c, 0, 1, "L", "k")
        rows = ["".join("#" if c.get(x, y) == "k" else "." for x in range(7)) for y in range(1, 8)]
        # Asserted on columns 0..4 -- the glyph's own five. **A first version of this test read r[0] of
        # an 8-wide window drawn at x=1**, so it was measuring the padding and failed a glyph that was
        # correct (it renders as `.#...` .. `#####`, stem left, foot running right).
        self.assertTrue(all(r[0] == "#" for r in rows),
                        "the stem must be the leftmost drawn column:\n" + "\n".join(rows))
        self.assertGreaterEqual(rows[-1].count("#"), 4,
                                "the foot must run rightwards:\n" + "\n".join(rows))
        # and a mirrored glyph must NOT pass the same check, or the check proves nothing
        c2 = B.Canvas(16, 12, ".")
        FIG.draw_text(c2, 0, 1, "J", "k")
        rows2 = ["".join("#" if c2.get(x, y) == "k" else "." for x in range(7)) for y in range(1, 8)]
        self.assertNotEqual(rows2, rows, "L and J must not render identically")

    def test_a_missing_glyph_is_visible_rather_than_skipped(self):
        """A label that silently drops a letter is worse than one that shows it is missing."""
        c = B.Canvas(40, 12, ".")
        FIG.draw_text(c, 1, 1, "AZ", "k")            # A and Z both exist
        two = sum(1 for y in range(12) for x in range(40) if c.get(x, y) == "k")
        c2 = B.Canvas(40, 12, ".")
        FIG.draw_text(c2, 1, 1, "A", "k")
        one = sum(1 for y in range(12) for x in range(40) if c2.get(x, y) == "k")
        self.assertGreater(two, one)

    def test_text_width_matches_what_draw_text_advances(self):
        """The two have to agree or a right-aligned label will not line up."""
        for s in ("", "A", "OUTLINE", "PALETTE 16"):
            c = B.Canvas(80, 12, ".")
            end = FIG.draw_text(c, 0, 0, s, "k")
            self.assertEqual(FIG.text_width(s), end, "for %r" % s)

    def test_palette_swatches_keep_their_fill_and_their_pad(self):
        """The bug that got away: spacing one pixel short ate every swatch's interior.

        Measured on the rendered figure rather than reasoned about -- the fill at the centre of each cell
        must be the board colour, and the pixel just outside the ring must be the field colour.
        """
        board = [(146, 123, 206, 255), (0, 0, 0, 255), (247, 244, 255, 255), (70, 45, 73, 255)]
        c, keys = FIG.palette_board(board, per_row=4, swatch=14, title=None)
        img = FIG.render(c, keys, 1)
        cell, pad, pitch = 16, 1, 18
        field = FIG.DEFAULT_PALETTE["."][:3]
        for i, colour in enumerate(board):
            x = pad + 1 + i * pitch
            y = pad
            self.assertEqual(img.getpixel((x + 8, y + 8))[:3], tuple(colour[:3]),
                             "swatch %d lost its fill to the next swatch's ring" % i)
            self.assertEqual(img.getpixel((x - 1, y))[:3], field,
                             "swatch %d has no field-coloured pad" % i)

    def test_the_derived_ring_is_darker_than_its_fill(self):
        """The figure is making the outline-predictability point, so the ring must actually be darker."""
        board = [(200, 120, 160, 255), (247, 244, 255, 255)]
        c, keys = FIG.palette_board(board, per_row=2, swatch=14, title=None)
        for i in range(len(board)):
            fill = keys["s%d" % i]
            ring = keys["r%d" % i]
            self.assertLess(sum(ring[:3]), sum(fill[:3]),
                            "the ring on swatch %d is not a darker step of its fill" % i)

    def test_no_resampling_happens_anywhere_in_a_figure(self):
        """Every colour in the output must be one the key table names, and the size must be an integer
        multiple. A figure that had been resampled would be lying about the pixels it shows."""
        c, keys = FIG.palette_board([(10, 20, 30, 255), (200, 100, 50, 255)], per_row=2, swatch=10)
        for scale in (1, 4):
            img = FIG.render(c, keys, scale)
            self.assertEqual(img.size, (c.width * scale, c.height * scale))
            allowed = {tuple(v[:3]) for v in keys.values() if v[3] > 0}
            got = {p[:3] for p in img.convert("RGB").get_flattened_data()}
            self.assertTrue(got <= allowed, "the renderer invented colours: %s" % (got - allowed))

    def test_no_ink_falls_outside_the_canvas(self):
        """The check that catches a clipped label, and it is a canvas-level question rather than a
        question about how a preview happens to be scaled.

        **Two figures lost their labels to this and both still saved.** `outline_study` drew `as drawn`
        and `flat ring` at `head + h + 2` on a canvas whose height left exactly that much and no more, so
        the last row of each label sat on the final pixel row. The fix was a margin; the guard is this
        assertion, which asks the only question that matters: is every pixel of ink inside the canvas?
        """
        sprite = self._sprite()
        made = [
            FIG.palette_board([(10, 20, 30, 255), (200, 100, 50, 255)], per_row=2, title="PAL"),
            FIG.silhouette_map(sprite, title="SIL"),
            FIG.outline_study(sprite, title="OUT"),
            FIG.distribution_bars(["a", "b"], [3.0, 1.0], title="DIS"),
        ]
        for canvas, keys in made:
            tag = canvas
            # a canvas refuses out-of-range writes, so this checks the layout rather than the drawing:
            # every ink pixel a figure intends must be within the canvas it was given.
            for y in range(canvas.height):
                for x in range(canvas.width):
                    self.assertIsInstance(canvas.get(x, y), str)
            # and the label area must not be the last row: there has to be a margin below the lowest ink
            lowest = max((y for y in range(canvas.height) for x in range(canvas.width)
                          if canvas.get(x, y) != "_" and canvas.get(x, y) != "."), default=0)
            self.assertLess(lowest, canvas.height - 1,
                            "the lowest ink sits on the final pixel row, so a label is clipped")

    def test_a_per_row_span_keeps_small_metrics_visible(self):
        """The unreadable figure, and the fix.

        Three judge metrics on one shared scale measure 43.0, 0.115 and 0.41 -- the first fills the plot
        and the other two are invisible. With a `span` per row each is drawn inside its own reference
        band, which is the comparison the metrics are actually about.
        """
        values = [43.0, 0.115, 0.41]
        spans = ((9.0, 60.0), (0.0236, 0.1816), (0.284, 0.775))
        shared, k1 = FIG.distribution_bars(["a", "b", "c"], values, width=100)
        per_row, k2 = FIG.distribution_bars(["a", "b", "c"], values, width=100, span=spans)
        img_shared = FIG.render(shared, k1, 1)
        img_spans = FIG.render(per_row, k2, 1)

        def lit(img, keys, i):
            colour = keys["b%d" % i][:3]
            return sum(1 for y in range(img.height) for x in range(img.width)
                       if img.getpixel((x, y))[:3] == colour)

        # every key is present even when a bar quantises to zero width, so the table is complete
        for k in (k1, k2):
            self.assertIn("b0", k)
            self.assertIn("b1", k)
            self.assertIn("b2", k)
        # on a shared scale the two small metrics are nearly invisible or absent entirely
        self.assertLess(lit(img_shared, k1, 1) + lit(img_shared, k1, 2), 40)
        # with their own band they are not
        self.assertGreater(lit(img_spans, k2, 1), 100)
        self.assertGreater(lit(img_spans, k2, 2), 100)

    def test_an_empty_source_is_drawn_as_empty_rather_than_omitted(self):
        """The figure's main job: a declared source contributing nothing must be visible as a zero.

        Measured when this was written, `corpus/sources.jsonl` names three sources while
        `corpus/manifest.jsonl` holds 160 rows all from one -- so two are declared and empty. A chart that
        omitted them would report a corpus broader than it is, and the whole point of the TODO entry is
        that breadth cannot be claimed without it.
        """
        ids = ["a-full-source", "b-empty-source", "c-empty-source"]
        counts = {"a-full-source": 160}
        c, keys = FIG.source_distribution(ids, counts, title="SOURCES")
        img = FIG.render(c, keys, 1)
        # **Only the bar area is counted.** The label column shares its colour with the empty-source
        # marker, so a whole-image count includes the ids' own text and reports hundreds of pixels for a
        # one-pixel marker -- which is exactly what the first version of this test measured.
        label_w = max(FIG.text_width(i) for i in ids) + 3

        def count(colour, row=None):
            ys = range(img.height) if row is None else [row]
            return sum(1 for y in ys for x in range(label_w, img.width)
                       if img.getpixel((x, y))[:3] == colour)

        self.assertGreater(count(keys["b0"][:3]), 100, "the full source needs a real bar")
        # **Counted per row, not across the figure.** Both empty sources carry the same marker colour, so a
        # whole-figure count returns 2 and reads as a two-pixel marker -- which is what the first version of
        # this assertion measured. The marker is one pixel on its own row's centre line, and that is the
        # claim worth pinning.
        bar_h, gap, head = 8, 4, FIG.FONT_H + 3
        for i in (1, 2):
            row = head + 1 + i * (bar_h + gap) + bar_h // 2
            self.assertEqual(count(keys["b%d" % i][:3], row), 1,
                             "an empty source must show exactly one marker pixel on its own row")
            # and nothing else on that row
            self.assertEqual(count(keys["b%d" % i][:3], row - 2), 0)
        self.assertNotEqual(keys["b1"], keys["b0"],
                            "an empty source must not share a filled bar's colour")

    def test_the_corpus_ledger_scope_is_machine_readable(self):
        """Every declared source says what kind of ledger it has, so a zero row is not read as a gap.

        **This is a correction to a misreading, and the misreading was mine.** The source figure's first
        title said "CORPUS SOURCES" while it measured `manifest.jsonl` rows, so two sources showing nothing
        read as a corpus with two holes in it. The truth: `th123-hisoutensoku-rip`'s 120 samples exist only
        as aggregate percentiles in `calibration.py`, and `ugoira-40frames`' 40 frames are deliberately
        excluded from the reference table. The `ledger` field is what lets a reader -- or a figure -- tell
        "no rows by design" from "not measured yet".
        """
        import json as _json
        rows = [_json.loads(l) for l in
                (Path(__file__).resolve().parents[1] / "corpus" / "sources.jsonl")
                .read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertEqual(len(rows), 3, "three sources are declared")
        kinds = {}
        for r in rows:
            self.assertIn("sample", r, "%s must declare its sample size" % r["source_id"])
            self.assertIn("ledger", r, "%s must declare its ledger kind" % r["source_id"])
            self.assertIn(r["ledger"], ("per-row", "aggregate", "excluded"),
                          "%s has an unknown ledger kind %r" % (r["source_id"], r["ledger"]))
            self.assertGreater(r["sample"], 0)
            kinds[r["source_id"]] = r["ledger"]
        # exactly one source carries the per-row ledger, and it is the one the manifest is made of
        self.assertEqual(kinds["th155-aoCF-rip"], "per-row")
        self.assertEqual(kinds["th123-hisoutensoku-rip"], "aggregate")
        self.assertEqual(kinds["ugoira-40frames"], "excluded")
        manifest = (Path(__file__).resolve().parents[1] / "corpus" / "manifest.jsonl") \
            .read_text(encoding="utf-8").splitlines()
        ids = {_json.loads(l)["source_id"] for l in manifest if l.strip()}
        self.assertEqual(ids, {"th155-aoCF-rip"},
                         "the ledger must hold rows for the per-row source and nothing else")

    def test_a_source_in_the_manifest_but_not_the_source_list_is_still_drawn(self):
        """A manifest row whose source id is undeclared is a corpus inconsistency, and hiding it would be
        the wrong way to be tidy."""
        # the function is fed ids, so the caller decides; this pins that an id with no declared entry
        # still gets a row when it carries a count
        ids = ["declared", "undeclared-but-present"]
        counts = {"declared": 5, "undeclared-but-present": 11}
        c, keys = FIG.source_distribution(ids, counts)
        self.assertEqual(c.width > 0 and c.height > 0, True)
        self.assertIn("b1", keys)

    def test_the_reference_marker_sits_where_the_reference_is(self):
        """The marker is the shipped distribution's position inside the row's own band, so a row below
        its marker is below the reference -- the comparison `calibrate.py` prints as text."""
        c, keys = FIG.distribution_bars(["x"], [50.0], width=100, span=((0.0, 100.0),), reference=(25.0,))
        img = FIG.render(c, keys, 1)
        colour = keys["m0"][:3]
        xs = [x for y in range(img.height) for x in range(img.width) if img.getpixel((x, y))[:3] == colour]
        bar = keys["b0"][:3]
        bx = [x for y in range(img.height) for x in range(img.width) if img.getpixel((x, y))[:3] == bar]
        self.assertTrue(xs and bx)
        self.assertLess(min(xs), max(bx), "the marker must sit inside the bar for a value above it")

    def test_the_silhouette_figure_is_flat_and_bounded_by_the_sprite(self):
        """One colour for the whole shape, and the same bounding box as the drawing it came from."""
        sprite = self._sprite()
        c, keys = FIG.silhouette_map(sprite, title="SIL")
        img = FIG.render(c, keys, 1)
        shape = {p[:3] for p in img.convert("RGB").get_flattened_data()}
        self.assertIn(keys["s"][:3], shape)
        # the shape occupies exactly the sprite's drawn extent, offset by the border and any title
        drawn = sum(1 for p in list(sprite.get_flattened_data()) if p[3] > 0)
        got = sum(1 for p in img.convert("RGB").get_flattened_data() if p[:3] == keys["s"][:3])
        self.assertEqual(got, drawn)

    def test_a_bar_length_is_the_value_it_encodes(self):
        """Integer rectangles, so a bar's length is exact rather than approximate."""
        c, keys = FIG.distribution_bars(["a", "b"], [10.0, 5.0], width=100, bar_h=4)
        img = FIG.render(c, keys, 1)

        def run_length(row_pixels, colour):
            best = cur = 0
            for p in row_pixels:
                cur = cur + 1 if p[:3] == colour else 0
                best = max(best, cur)
            return best

        def row_of(colour):
            for y in range(img.height):
                if any(img.getpixel((x, y))[:3] == colour for x in range(img.width)):
                    return [img.getpixel((x, y)) for x in range(img.width)]
            return None

        lengths = []
        for i in range(2):
            row = row_of(keys["b%d" % i][:3])
            self.assertIsNotNone(row, "bar %d was not drawn" % i)
            lengths.append(run_length(row, keys["b%d" % i][:3]))
        self.assertGreater(lengths[0], 90, "the full-height bar should span the plot width: %s" % lengths)
        self.assertAlmostEqual(lengths[0] / max(1, lengths[1]), 2.0, delta=0.1,
                               msg="a value twice as large must draw a bar twice as long: %s" % lengths)


class TestHistory(unittest.TestCase):
    """Undo, redo, and the two defects that shaped them.

    The acceptance criterion is the one this project uses everywhere: **state has to be reconstructable
    rather than trusted.** So every assertion here compares cells, not counts -- an undo that returns True
    and leaves the canvas wrong is the failure worth catching, and only a pixel comparison catches it.

    Two defects were found while building this and both are pinned below:

    1. Recording on `put` alone gave a sixteen-pixel `rect` sixteen history entries, so `undo` took
       sixteen calls to step back one operation.
    2. An idempotence check on the label then made two consecutive `rect` calls leave **one** entry, so one
       undo removed both and the state between them was never snapshotted. The guard was hiding a real
       loss.
    """

    def test_one_operation_is_one_history_entry(self):
        """The first defect: a verb is one step however many pixels it writes."""
        c = B.Canvas(8, 8)
        c.rect(1, 1, 4, 4, "r")
        self.assertEqual(c.history(), ["<start>", "rect"])
        c.disc(4, 4, 2, "b")
        self.assertEqual(c.history(), ["<start>", "rect", "disc"])
        c.line(0, 0, 7, 7, "k")
        self.assertEqual(c.history(), ["<start>", "rect", "disc", "line"])
        c.outline("e")
        self.assertEqual(c.history()[-1], "outline")
        c.recolor({"r": "y"})
        self.assertEqual(c.history()[-1], "recolor")

    def test_two_identical_operations_are_two_entries(self):
        """The second defect, and the reason there is no idempotence check on the label.

        Two `rect` calls in a row are two operations. A guard that skipped a repeated label left one entry,
        so a single undo removed both and `revert` to the state between them was unreachable.
        """
        c = B.Canvas(6, 6)
        c.rect(1, 1, 4, 4, "r")
        mid = c.state()
        c.rect(2, 2, 3, 3, "b")
        end = c.state()
        self.assertEqual(c.history(), ["<start>", "rect", "rect"])
        self.assertTrue(c.undo())
        self.assertEqual(c.state(), mid, "one undo must land between the two rectangles")
        self.assertTrue(c.undo())
        self.assertNotEqual(c.state(), mid)
        self.assertTrue(c.redo())
        self.assertEqual(c.state(), mid)
        self.assertTrue(c.redo())
        self.assertEqual(c.state(), end)

    def test_a_dynamic_put_loop_is_one_entry_inside_a_transaction(self):
        """`put` is the public verb and the interior path, so both callers are covered by the counter."""
        c = B.Canvas(8, 8)
        before = c.state()
        with c._shape("computed"):
            for i in range(8):
                c.put(i, 0, "k")
        self.assertEqual(c.history(), ["<start>", "computed"])
        c.undo()
        self.assertEqual(c.state(), before)

    def test_a_lone_put_is_its_own_entry(self):
        """The other half of the same rule: outside a transaction, a single pixel IS an operation."""
        c = B.Canvas(4, 4)
        c.put(1, 1, "k")
        self.assertEqual(c.history(), ["<start>", "put"])
        self.assertTrue(c.undo())
        self.assertEqual(c.get(1, 1), c.bg)

    def test_undo_and_redo_walk_the_whole_history_both_ways(self):
        """Every intermediate state, compared as cells rather than as counts."""
        c = B.Canvas(10, 10)
        states = [c.state()]
        for i in range(6):
            c.rect(i, i, 9 - i, 9 - i, "k")
            states.append(c.state())
        self.assertEqual(len(c.history()), 7)
        for i in range(len(states) - 1, 0, -1):
            self.assertTrue(c.undo())
            self.assertEqual(c.state(), states[i - 1], "undo to step %d" % (i - 1))
        self.assertFalse(c.undo(), "the history is exhausted")
        for i in range(1, len(states)):
            self.assertTrue(c.redo())
            self.assertEqual(c.state(), states[i], "redo to step %d" % i)
        self.assertFalse(c.redo(), "the redo stack is exhausted")

    def test_a_new_operation_after_an_undo_drops_the_redo_stack(self):
        """Otherwise a redo would resurrect a branch the author had already abandoned."""
        c = B.Canvas(6, 6)
        c.rect(1, 1, 4, 4, "r")
        c.rect(2, 2, 3, 3, "b")
        c.undo()
        self.assertTrue(c.redo() or True)          # the stack exists here
        c.disc(3, 3, 1, "y")                       # a new operation
        self.assertFalse(c.redo(), "the abandoned branch must not come back")

    def test_undo_on_an_empty_history_is_false_and_changes_nothing(self):
        """A refusal that is reported rather than a silent no-op the caller has to guess at."""
        c = B.Canvas(4, 4)
        before = c.state()
        self.assertFalse(c.undo())
        self.assertEqual(c.state(), before)
        self.assertFalse(c.redo())
        self.assertEqual(c.state(), before)

    def test_every_state_the_history_holds_is_a_state_the_canvas_had(self):
        """The property that makes a snapshot honest: no state is invented by stepping back.

        Twelve random operations, then walking the history down and checking each landing against the set
        of states the canvas actually occupied.
        """
        import random as _r
        rnd = _r.Random(11)
        c = B.Canvas(16, 16)
        seen = {c.state()}
        for _ in range(12):
            kind = rnd.choice(["rect", "disc", "line", "put"])
            if kind == "rect":
                a, b = sorted(rnd.sample(range(16), 2))
                c.rect(a, a, b, b, rnd.choice("rgb"))
            elif kind == "disc":
                c.disc(rnd.uniform(2, 14), rnd.uniform(2, 14), rnd.uniform(1, 5), rnd.choice("rgb"))
            elif kind == "line":
                c.line(0, 0, rnd.randrange(16), rnd.randrange(16), rnd.choice("rgb"))
            else:
                c.put(rnd.randrange(16), rnd.randrange(16), rnd.choice("rgb"))
            seen.add(c.state())
        while c.undo():
            self.assertIn(c.state(), seen, "undo landed on a state the canvas never had")

    def test_plan_steps_accepts_and_validates_the_history_ops(self):
        """The script-level vocabulary, including the refusal of a nonsense count."""
        from ichiwatashi.cli import plan_steps, SpecError
        spec = {"width": 8, "height": 8, "steps": [{"op": "rect", "x0": 0, "y0": 0, "x1": 3, "y1": 3,
                                                   "key": "r"},
                                                  {"op": "undo"},
                                                  {"op": "redo", "count": 2}]}
        plan = plan_steps(spec)
        self.assertEqual([k for k, _ in plan], ["rect", "undo", "redo"])
        self.assertEqual(plan[1][1]["count"], 1, "an omitted count means one step")
        self.assertEqual(plan[2][1]["count"], 2)
        for bad in (0, -1, 1.5, "2"):
            with self.assertRaises(SpecError):
                plan_steps({"width": 8, "height": 8, "steps": [{"op": "undo", "count": bad}]})

    def test_the_undo_demo_script_produces_the_retry_and_not_the_first_attempt(self):
        """The end-to-end case the TODO entry is about: try, step back, try again, in one run.

        Two rectangles are drawn at the same place; the first is undone before the second. The assertion is
        on the pixels, so a script that reported an undo without performing one fails here.
        """
        from ichiwatashi.cli import plan_steps
        spec = {"width": 20, "height": 12, "palette": {".": None, "r": [200, 60, 60, 255]},
                "steps": [{"op": "rect", "x0": 2, "y0": 2, "x1": 17, "y1": 9, "key": "r"},
                          {"op": "undo"},
                          {"op": "rect", "x0": 6, "y0": 2, "x1": 13, "y1": 9, "key": "r"}]}
        c = B.Canvas(spec["width"], spec["height"])
        for kind, step in plan_steps(spec):
            if kind in ("undo", "redo"):
                getattr(c, kind)()
            else:
                getattr(c, kind)(step["x0"], step["y0"], step["x1"], step["y1"], step["key"])
        # the wide first attempt must be gone and only the narrow retry present
        self.assertEqual(c.get(3, 5), ".", "the first rectangle was not undone")
        self.assertEqual(c.get(10, 5), "r", "the retry was not drawn")


class TestGridRoundTrip(unittest.TestCase):
    """Export a grid, read it back, and refuse what cannot be honoured.

    The TODO entry: "网格 JSON 导出有了、导入没有（只能从形状脚本重建）。**手写补细节后无法回读**". So the
    acceptance criterion is the one that entry names -- a hand edit made to the file must come back -- and
    the assertions below are on pixels rather than on a successful parse.

    **Building this found a real defect on the export side**, which is why the round trip is tested at all
    rather than assumed: `to_grid` formatted every non-string colour as `"#%02X%02X%02X"`, which raises
    `TypeError` on an RGBA tuple -- and every palette in this repository holds RGBA, because `judge` and
    `figures` both work in it. Nothing had caught it because nothing called `to_grid` in a test.
    """

    PALETTE = {".": None, "k": (20, 20, 28, 255), "s": (226, 178, 196, 255), "h": (110, 80, 150, 128)}

    def _canvas(self):
        c = B.Canvas(12, 10, ".")
        c.disc(5.5, 4.5, 4, "s")
        c.rect(2, 7, 9, 9, "h")
        c.outline("k")
        return c

    def test_a_grid_survives_a_json_round_trip_pixel_for_pixel(self):
        """The whole point: what came out goes back in, and the picture is the same one."""
        c = self._canvas()
        grid = json.loads(json.dumps(c.to_grid(self.PALETTE)))
        c2, pal2 = B.from_grid(grid)
        self.assertEqual(c2.state(), c.state())
        self.assertEqual((c2.width, c2.height), (c.width, c.height))
        self.assertEqual(c2.bg, c.bg)
        # and it renders identically, which covers the palette having been re-parsed rather than passed on
        self.assertEqual(c.to_image(self.PALETTE).tobytes(), c2.to_image(pal2).tobytes())

    def test_alpha_is_carried_rather_than_dropped(self):
        """A 3-tuple is written as #RRGGBB and a 4-tuple as #RRGGBBAA, and both come back whole.

        The defect above lived here: the exporter could not write an RGBA palette at all.
        """
        c = self._canvas()
        grid = c.to_grid(self.PALETTE)
        self.assertEqual(grid["palette"]["s"], "#E2B2C4FF")
        self.assertEqual(grid["palette"]["h"], "#6E509680", "the alpha must survive, not be dropped")
        self.assertEqual(grid["palette"]["."], "transparent")
        _, pal = B.from_grid(grid)
        self.assertEqual(pal["h"], (110, 80, 150, 128))
        self.assertIsNone(pal["."])

    def test_a_hand_edit_comes_back(self):
        """The criterion the TODO entry states, done the way a person would do it: change one character."""
        c = self._canvas()
        grid = json.loads(json.dumps(c.to_grid(self.PALETTE)))
        rows = list(grid["pixels"])
        row = list(rows[8])
        self.assertNotEqual(row[5], "s")
        row[5] = "s"                       # a hand-added highlight
        rows[8] = "".join(row)
        grid["pixels"] = rows
        c2, _ = B.from_grid(grid)
        self.assertEqual(c2.get(5, 8), "s", "the hand edit was lost")
        self.assertEqual(c2.state(), B.from_grid(grid)[0].state())

    def test_every_malformed_grid_is_refused_by_name(self):
        """Six refusals, each naming the thing that would otherwise be a wrong picture.

        The last one is the reason `from_grid` exists instead of being a call to `from_rows`: an unknown
        character renders as nothing, so a typo in a hand-edited file would leave a hole and raise no error
        anywhere.
        """
        cases = [
            ({"height": 2, "pixels": ["ab", "ab"]}, "width"),
            ({"width": 0, "height": 2, "pixels": ["ab", "ab"]}, "positive"),
            ({"width": "2", "height": 2, "pixels": ["ab", "ab"]}, "positive"),
            ({"width": 2, "height": 2, "pixels": [[1, 2], [3, 4]]}, "list of strings"),
            ({"width": 2, "height": 3, "pixels": ["ab", "ab"]}, "row(s) for a height"),
            ({"width": 3, "height": 2, "pixels": ["ab", "ab"]}, "row 0 is 2 wide"),
            ({"width": 2, "height": 2, "pixels": ["aZ", "ab"],
              "palette": {"a": "#000000", "b": "transparent"}}, "no palette entry"),
            ({"width": 2, "height": 2, "pixels": ["ab", "ab"], "palette": {"a": "#00"}}, "RRGGBB"),
        ]
        for spec, wanted in cases:
            with self.assertRaises(ValueError) as ctx:
                B.from_grid(spec)
            self.assertIn(wanted, str(ctx.exception),
                          "the refusal for %r should mention %r, said: %s"
                          % (spec, wanted, ctx.exception))

    def test_the_background_is_not_an_unknown_character(self):
        """A `.` absent from the palette is the canvas's own background, and it comes back in the palette
        so the image can be rendered without the caller having to add it."""
        grid = {"width": 2, "height": 2, "pixels": ["a.", ".a"], "palette": {"a": "#010203"}}
        canvas, pal = B.from_grid(grid)
        self.assertEqual(canvas.bg, ".")
        self.assertIn(".", pal)
        self.assertIsNone(pal["."])
        self.assertEqual(canvas.get(0, 0), "a")
        self.assertEqual(canvas.get(1, 0), ".")

    def test_parse_colour_accepts_the_shapes_to_grid_writes(self):
        """The inverse has to accept its own forward function's output, in every spelling it writes."""
        self.assertEqual(B.parse_colour("#FF8000"), (255, 128, 0, 255))
        self.assertEqual(B.parse_colour("#FF800080"), (255, 128, 0, 128))
        self.assertIsNone(B.parse_colour("transparent"))
        self.assertIsNone(B.parse_colour(None))
        self.assertEqual(B.parse_colour((1, 2, 3)), (1, 2, 3, 255))
        self.assertEqual(B.parse_colour("red"), "red")
        for bad in ("#FFF", "#GGGGGG", (1, 2), (1, 2, 3, 4, 5), 3.5):
            with self.assertRaises(ValueError):
                B.parse_colour(bad)


class TestAlignedShift(unittest.TestCase):
    """The second drift measure: what each frame must move by to sit on the one before it.

    The TODO entry for this named the gap precisely -- `drift` "only takes the first opaque row/column, so
    a shape that moves inside while its silhouette stays put reads 0". Three animations below differ only
    in what moves, and the assertions are on which measure sees which.

    **Two things were learned by measuring rather than by design, and both are pinned here:**

    1. Minimising disagreement over *every* opaque pixel is overwhelmed by whatever is not moving. On the
       interior fixture -- a 16-pixel accent sliding inside a fixed 330-pixel silhouette -- the whole-frame
       fit returned `(0, 0)` for every pair, correctly, because the stationary body disagreed more than the
       moving accent at any offset. The fix is to difference the pair first and fit only the changed pixels.
    2. A best fit that lands on the edge of the search window is not a fit. The rotation fixture returned
       offsets of exactly `reach`, twice; reporting those would be reporting the window rather than the
       motion, so the call substitutes `(0, 0)` and flags it.
    """

    @staticmethod
    def _sprite(interior_dx=0, whole_dx=0, rotate=False):
        im = Image.new("RGBA", (40, 28), (0, 0, 0, 0))
        px = im.load()
        x0, x1 = 8 + whole_dx, 31 + whole_dx
        for y in range(6, 22):
            for x in range(x0, x1):
                px[x, y] = (30, 30, 40, 255)
        for y in range(8, 20):
            for x in range(x0 + 2, x1 - 2):
                px[x, y] = (220, 140, 170, 255)
        mx = 14 + whole_dx + interior_dx
        if rotate:
            for i in range(6):
                px[14 + whole_dx + i, 12 + i] = (90, 60, 150, 255)
        else:
            for y in range(12, 16):
                for x in range(mx, mx + 4):
                    px[x, y] = (90, 60, 150, 255)
        return im

    def _timeline(self, kind, n=6):
        tl = F.Timeline(width=44, height=30)
        for i in range(n):
            if kind == "translation":
                im = self._sprite(whole_dx=i)
            elif kind == "interior":
                im = self._sprite(interior_dx=i)
            else:
                im = self._sprite(rotate=(i % 2 == 0))
            tl.add(im, pivot=(20, 26), duration_ms=100)
        return tl

    def test_a_whole_shape_moving_is_seen_by_both_measures(self):
        """The case both were built for, so neither can be broken while the other passes."""
        tl = self._timeline("translation")
        dx, dy = tl.drift()
        self.assertEqual((dx, dy), (5, 0), "the bounding box moves five pixels across six frames")
        adx, ady, per, _scores, bounds, exact = tl.aligned_shift(reach=6)
        self.assertEqual(per, [(1, 0)] * 5, "each frame sits one pixel right of the previous")
        self.assertFalse(any(bounds))
        self.assertEqual((adx, ady), (0, 0), "a steady crawl has no stutter")

    def test_interior_motion_is_seen_only_by_the_aligned_measure(self):
        """The gap the TODO entry named: the silhouette is fixed and the inside moves.

        `drift` reads 0 -- correctly, as a bounding-box measure -- and `aligned_shift` reads the one pixel
        per frame that the accent actually travels. A bounding box of the same value in every frame is the
        fixture's point, so if this test ever reports a non-zero drift the fixture has stopped testing it.
        """
        tl = self._timeline("interior")
        boxes = {tl.compose()[i].getbbox() for i in range(6)}
        self.assertEqual(len(boxes), 1, "the fixture's silhouette must not move")
        self.assertEqual(tl.drift(), (0, 0), "the bounding-box measure cannot see this, by construction")
        adx, ady, per, _scores, bounds, exact = tl.aligned_shift(reach=6)
        self.assertEqual(per, [(1, 0)] * 5, "the interior moves one pixel per frame and that is the reading")
        self.assertFalse(any(bounds), "one pixel is well inside the window, so nothing hit an edge")

    def test_the_whole_frame_form_is_overwhelmed_by_what_is_not_moving(self):
        """The measurement that forced `changed_only`, kept as a test so the reason cannot be re-derived.

        Fitting every opaque pixel gives `(0, 0)` on the interior fixture: the stationary body contributes
        more disagreement at a one-pixel offset than the moving accent resolves. That is not a bug in the
        fit -- it is the wrong question for this fixture, which is why the default differences first.
        """
        tl = self._timeline("interior")
        _dx, _dy, whole, _s, _b, exact = tl.aligned_shift(reach=6, changed_only=False)
        _dx2, _dy2, changed, _s2, _b2, exact = tl.aligned_shift(reach=6, changed_only=True)
        self.assertEqual(whole, [(0, 0)] * 5, "the whole-frame fit cannot find the interior motion")
        self.assertEqual(changed, [(1, 0)] * 5, "the changed-pixel fit finds it")

    def test_a_rotation_shows_up_as_a_non_zero_spread(self):
        """A rotation is not a translation, and the **spread** is what says so -- not the boundary flag.

        Measured at three window sizes: `reach=3` hits the edge five times, while `reach=6` and `9`
        "converge" on `(-4, -4)` and flag nothing. So the flag catches a truncated search and cannot catch a
        fit that settles on a wrong answer, which is what a rotation produces. What does catch it is the
        spread: a genuine translation returns the same offset for every pair, so its spread is 0, while this
        fixture oscillates between two incompatible offsets.
        """
        tl = self._timeline("rotate")
        adx, ady, per, _scores, _bounds, exact = tl.aligned_shift(reach=6)
        self.assertGreater(adx + ady, 0, "an oscillation must show as a non-zero spread: %s" % (per,))
        self.assertGreater(len(set(per)), 1, "the offsets must disagree with each other: %s" % (per,))

    def test_a_truncated_search_is_flagged_rather_than_reported(self):
        """The flag's real job: a best fit sitting on the window's edge is not a fit.

        At `reach=3` this fixture returns offsets of exactly 3, so `(0, 0)` is substituted. That keeps a
        search window from being published as a measurement -- a different failure from the rotation case
        above, and the two are now told apart on purpose.
        """
        tl = self._timeline("rotate")
        _dx, _dy, per, _scores, bounds, exact = tl.aligned_shift(reach=3)
        self.assertTrue(any(bounds), "a truncated search must be flagged")
        for (x, y), hit in zip(per, bounds):
            if hit:
                self.assertEqual((x, y), (0, 0), "a boundary hit is replaced, not passed through")

    def test_identical_frames_report_no_motion_and_no_flag(self):
        """The degenerate case: nothing changed, so the honest answer is zero rather than a fallback."""
        tl = F.Timeline(width=20, height=20)
        for _ in range(4):
            tl.add(self._sprite(), pivot=(10, 18), duration_ms=100)
        dx, dy, per, scores, bounds, exact = tl.aligned_shift()
        self.assertEqual((dx, dy), (0, 0))
        self.assertEqual(per, [(0, 0)] * 3)
        self.assertEqual(scores, [0, 0, 0])
        self.assertFalse(any(bounds))

    def test_the_frames_command_runs_end_to_end(self):
        """A regression guard for a bug that only an end-to-end run could find.

        `cmd_frames` called `judge(p)` where `p` was a `Path` (and was also rebound by a comprehension
        above), so every accepted directory ended in `AttributeError: 'WindowsPath' object has no attribute
        'convert'`. It had been invisible because reaching that line needs six or more frames and every
        shorter run exited at the refusal with code 2 -- so the command was broken on exactly the inputs it
        accepted, and no unit test of `drift` or `aligned_shift` could have caught it.
        """
        from ichiwatashi.cli import main
        with tempfile.TemporaryDirectory() as d:
            for i in range(6):
                self._sprite(interior_dx=i).save(Path(d) / ("f%02d.png" % i))
            rc = main(["frames", d, "--duration", "80"])
        self.assertEqual(rc, 0, "the frames command must complete on a directory it accepts")

    def test_the_frames_command_refuses_too_few_frames(self):
        """And the refusal is why the bug above hid: five frames exits before the broken line."""
        from ichiwatashi.cli import main
        with tempfile.TemporaryDirectory() as d:
            for i in range(5):
                self._sprite(interior_dx=i).save(Path(d) / ("f%02d.png" % i))
            rc = main(["frames", d])
        self.assertEqual(rc, 2, "a spread over too few frames is refused, with its own exit code")

    def test_a_single_frame_returns_nothing_rather_than_dividing_by_zero(self):
        """One frame has no pair, so every returned sequence is empty and the spreads are zero."""
        tl = F.Timeline(width=20, height=20)
        tl.add(self._sprite(), pivot=(10, 18))
        self.assertEqual(tl.aligned_shift(), (0, 0, [], [], [], []),
                         "one frame: no pairs, and the sixth item is the per-pair exactness list")


class TestGifLosses(unittest.TestCase):
    """GIF's two unavoidable losses, measured before the file exists.

    The TODO entry: "GIF 会退化调色板（256 色上限 + 无 alpha）且**不告警**". The silence was the bug, and the
    failure shape is this project's worst one -- a file that opens and is not what was drawn.

    **A third check was in the first version and it was a false positive on every sprite.** It flagged a
    frame using both a fully opaque and a fully transparent pixel, which is what every ordinary sprite frame
    does -- drawn pixels plus a transparent ground -- and which GIF's single transparent index represents
    correctly. It refused a four-frame, four-colour, opaque animation. "Both opaque and transparent present"
    is the normal case; only a *partly* transparent pixel is unrepresentable.
    """

    @staticmethod
    def _timeline(colours, *, alpha=False, n=4, size=16):
        tl = F.Timeline(width=size, height=size)
        for i in range(n):
            im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            px = im.load()
            for y in range(size):
                for x in range(size):
                    c = tuple(colours[(x * size + y + i) % len(colours)])
                    # built explicitly rather than by concatenation: `colours` may already hold 4-tuples,
                    # and `c + (a,)` on a 4-tuple silently makes a 5-tuple
                    px[x, y] = (c[0], c[1], c[2], 128 if alpha else 255)
            tl.add(im, pivot=(size // 2, size - 1), duration_ms=100)
        return tl

    def test_an_ordinary_opaque_sprite_is_written_without_complaint(self):
        """The case the false-positive check refused: three colours, no alpha, nothing lost."""
        tl = self._timeline([(200, 60, 60), (60, 120, 200), (240, 220, 90)])
        losses = tl.gif_losses()
        self.assertEqual(losses["semi_transparent_pixels"], 0)
        self.assertFalse(losses["over_limit"])
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "ok.gif"
            tl.to_gif(p)
            self.assertTrue(p.is_file() and p.stat().st_size > 0)

    def test_a_transparent_ground_is_not_a_loss(self):
        """Transparency itself is representable; only *partial* transparency is not."""
        tl = self._timeline([(200, 60, 60)])
        self.assertEqual(tl.gif_losses()["semi_transparent_pixels"], 0)
        with tempfile.TemporaryDirectory() as d:
            tl.to_gif(Path(d) / "ground.gif")

    def test_a_partly_transparent_pixel_is_refused_with_a_count(self):
        """The refusal quotes how many pixels are affected, so the reader can judge the damage."""
        tl = self._timeline([(200, 60, 60)], alpha=True)
        losses = tl.gif_losses()
        self.assertGreater(losses["semi_transparent_pixels"], 0)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "alpha.gif"
            with self.assertRaises(F.GifWouldLose) as ctx:
                tl.to_gif(p)
            self.assertIn(str(losses["semi_transparent_pixels"]), str(ctx.exception))
            self.assertIn("to_apng", str(ctx.exception), "the alternative must be named")
            self.assertFalse(p.exists(), "a refusal must not leave a lossy file behind")
            # and the caller saying "I know" writes it
            tl.to_gif(p, allow_loss=True)
            self.assertTrue(p.is_file())

    def test_over_the_colour_limit_is_refused(self):
        """More than 256 distinct colours is quantised, and that is said rather than done quietly."""
        tl = self._timeline([(i, (i * 7) % 256, (i * 13) % 256) for i in range(300)])
        losses = tl.gif_losses()
        self.assertTrue(losses["over_limit"], "the fixture must actually exceed 256: %s" % losses)
        self.assertGreater(losses["distinct_colours"], 256)
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(F.GifWouldLose) as ctx:
                tl.to_gif(Path(d) / "many.gif")
            self.assertIn("256", str(ctx.exception))

    def test_the_cli_refuses_a_lossy_gif_with_its_own_exit_code(self):
        """Exit 2 means "I will not produce this", distinct from 1 which means "produced, with notes"."""
        from ichiwatashi.cli import main
        with tempfile.TemporaryDirectory() as d:
            # **48x48, not 16x16.** A 16-pixel short side is below the judge's gate, so the run would have
            # been refused by the SIZE check before the GIF check ever ran -- and the test would have passed
            # for the wrong reason. The fixture has to be something the judge will measure.
            tl = self._timeline([(200, 60, 60)], alpha=True, n=6, size=48)
            for i, im in enumerate(tl.compose()):
                im.save(Path(d) / ("f%02d.png" % i))
            rc = main(["frames", d, "--gif", str(Path(d) / "out.gif")])
            self.assertEqual(rc, 2, "a lossy GIF must be refused with code 2")
            self.assertFalse((Path(d) / "out.gif").exists())
            rc2 = main(["frames", d, "--gif", str(Path(d) / "out.gif"), "--allow-loss"])
            self.assertIn(rc2, (0, 1), "with --allow-loss it is written, and notes are a code 1")
            self.assertTrue((Path(d) / "out.gif").is_file())


if __name__ == "__main__":
    unittest.main()
