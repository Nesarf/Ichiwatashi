# -*- coding: utf-8 -*-
"""Tests for Ichiwatashi.

The interesting assertions here are the ones that came from measurement rather than from intent: a
metric that flagged known-good art, a sampler that measured the encoder, an accent set that optimised
one property by destroying another. Each is pinned so it cannot come back.
"""
from __future__ import annotations

import unittest

from PIL import Image

from ichiwatashi import builder as B
from ichiwatashi import frames as F
from ichiwatashi.judge import judge as judge_fn
from ichiwatashi.judge import _opaque
from ichiwatashi import palette as P


def coords_note(r):
    return r.notes


def flat(size, colour=(0, 0, 0, 255)):
    return Image.new("RGBA", size, colour)


class TestJudge(unittest.TestCase):

    def test_a_sprite_that_is_one_block_is_reported_as_one(self):
        """A full rectangle is the degenerate case: one cluster, a full bounding box, no outline."""
        im = flat((16, 16))
        r = judge_fn(im)
        self.assertEqual(r.palette_size, 1)
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
        im = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        px = im.load()
        for y in range(3, 13):
            for x in range(3, 13):
                px[x, y] = (200, 200, 200, 255)
        for y in range(3, 13):
            for x in range(3, 13):
                if x in (3, 12) or y in (3, 12):
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

        # and end to end: a systematic outline is recognised as such
        im = Image.new("RGBA", (20, 20), (0, 0, 0, 0))
        px = im.load()
        fills = [(200, 60, 60, 255), (60, 200, 60, 255), (60, 60, 200, 255), (200, 200, 60, 255)]
        for k, f in enumerate(fills):
            x0 = 4 + k * 3
            for y in range(5, 15):
                for x in range(x0, x0 + 3):
                    px[x, y] = f
        # outline each fill with a darkened version of itself, which is the systematic convention
        for k, f in enumerate(fills):
            x0 = 4 + k * 3
            dark = (f[0] // 3, f[1] // 3, f[2] // 3, 255)
            for y in range(5, 15):
                px[x0, y] = dark
                px[x0 + 2, y] = dark
            for x in range(x0, x0 + 3):
                px[x, 5] = dark
                px[x, 14] = dark
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
        im = flat((8, 8), (10, 20, 30, 255))
        self.assertEqual(judge_fn(im), judge_fn(im))

    def test_fully_transparent_does_not_divide_by_zero(self):
        r = judge_fn(flat((8, 8), (0, 0, 0, 0)))
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


class TestGenerationBuckets(unittest.TestCase):
    """A single reference table judged a second generation of correct work and flagged all of it.

    TH123 and TH155 are different populations: `palette_size` has a median of 26 in one and 43 in
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
        # a palette_size of 70 is far above TH123's band and simply not a metric for TH155
        self.assertIsNotNone(C.outside("palette_size", 70.0, generation="th105/th123"))
        self.assertIsNone(C.outside("palette_size", 70.0, generation="th155"))
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
        self.assertIsNone(C.outside("palette_size", 70.0, generation="gba-era"))
        self.assertIsNone(C.outside("bbox_fill", 0.85, generation="gba-era"))
        self.assertEqual(C.how_far("bbox_fill", 0.85, generation="gba-era"), 0.0)

    def test_palette_size_is_absent_from_the_th155_bucket_on_purpose(self):
        """It is not a property of those drawings: the palettes are interchangeable within a
        character, and 92.5% of sprites change colour count when decoded with another member of the
        set. A threshold derived from one palette per sprite would be derived from a coin toss."""
        from ichiwatashi import calibration as C
        self.assertNotIn("palette_size", C.REFERENCE_BY_GENERATION["th155"])
        self.assertIn("palette_size", C.REFERENCE_BY_GENERATION["th105/th123"])

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
        im = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        px = im.load()
        for y in range(2, 14):
            for x in range(2, 14):
                px[x, y] = (200, 60, 60, 255)
        a = judge_fn(im)
        b = judge_fn(im, generation="th155")
        self.assertTrue(any("th105/th123" in n for n in a.notes) or not a.notes)
        self.assertFalse(any("th105/th123" in n for n in b.notes),
                         "the second call was judged with the first generation's table: %s" % b.notes)


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
        for i in range(int(C.REFERENCE["palette_size"].median)):
            r, g, b = colorsys.hsv_to_rgb(i / 26.0, 0.7, 0.8)
            colours.append((int(r * 255), int(g * 255), int(b * 255), 255))
        for y in range(6, 58):
            for x in range(6, 58):
                px[x, y] = colours[(x * 3 + y * 5) % len(colours)]
        r = judge(im)
        self.assertFalse(any("palette_size" in n for n in r.notes),
                         "a sprite at the reference palette size was flagged: %s" % r.notes)


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
        im = Image.new("RGBA", (40, 8), (0, 0, 0, 0))
        px = im.load()
        for y in range(8):
            x = 0
            for run, c in ((3, (200, 40, 40, 255)), (5, (40, 200, 40, 255)),
                           (2, (40, 40, 200, 255)), (7, (200, 200, 40, 255)),
                           (4, (200, 40, 200, 255)), (3, (40, 200, 200, 255)),
                           (9, (120, 60, 20, 255)), (4, (20, 120, 60, 255))):
                for i in range(run):
                    if x + i < 40:
                        px[x + i, y] = c
                x += run
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
        law = {2: 2, 3: 3, 4: 2, 5: 1, 6: 2, 7: 1, 8: 2}
        for n, want in law.items():
            with self.subTest(n=n):
                im = self._blocks(n, cols=10, rows=10)
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
        r = judge_fn(small)
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


if __name__ == "__main__":
    unittest.main()
