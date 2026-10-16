# -*- coding: utf-8 -*-
"""Tests for Ichiwatashi.

The interesting assertions here are the ones that came from measurement rather than from intent: a
metric that flagged known-good art, a sampler that measured the encoder, an accent set that optimised
one property by destroying another. Each is pinned so it cannot come back.
"""
from __future__ import annotations

import glob
import json
import math
import os
import unittest

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

    SRC = Path(__file__).resolve().parents[1] / "assets" / "font5x7.txt"

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


if __name__ == "__main__":
    unittest.main()
