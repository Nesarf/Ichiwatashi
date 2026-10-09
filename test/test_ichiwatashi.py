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

    def test_a_flat_outline_raises_a_note_and_a_varied_one_does_not(self):
        """The rule that was inverted. Measured: a known-good sprite varies its outline by 0.662, a
        hand attempt by 0.088 -- and the known-good value is the healthy one."""
        im = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        px = im.load()
        for y in range(3, 13):
            for x in range(3, 13):
                px[x, y] = (200, 200, 200, 255)          # one block, one outline colour
        for y in range(3, 13):
            for x in range(3, 13):
                if x in (3, 12) or y in (3, 12):
                    px[x, y] = (20, 20, 20, 255)
        r_flat = judge_fn(im)
        self.assertLess(r_flat.outline_variation, 0.1)
        self.assertTrue(any("flat" in n for n in r_flat.notes))

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
        `(y0, y1, w0, w1)` from a rectangle `(x0, y0, x1, y1)`. A missing field must say which."""
        import json
        import subprocess
        import sys
        import tempfile
        import os
        spec = {"width": 8, "height": 8, "palette": {".": "transparent"},
                "steps": [{"op": "cone", "y0": 0, "y1": 3, "w0": 1, "key": "h"}]}
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "s.json")
            open(f, "w", encoding="utf-8").write(json.dumps(spec))
            r = subprocess.run([sys.executable, "-m", "ichiwatashi.cli", "build", f,
                                "--out", os.path.join(d, "o.png")],
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("w1", r.stdout + r.stderr)


        """A positional rule drew a diagonal sash nobody asked for -- twice: first as
        `(x + y) % 7 == 0`, then again as `(x + y) < (width + height) / 2` after the comment had
        already been changed to say it was fixed.

        So the assertion is not "how many distinct rows" but the property that actually distinguishes
        the two: **a positional rule makes each row differ from the next, and a shape-relative rule
        makes whole rows constant.** A diagonal shows up as rows that vary horizontally.
        """
        c = B.Canvas(16, 16)
        c.rect(2, 2, 13, 13, "b")
        c.shade({"b": "L"}, {"b": "D"})
        rows = [r for r in c.rows() if set(r) != {"."}]
        for r in rows:
            body = r.strip(".")
            self.assertEqual(len(set(body)), 1,
                             "row %r varies horizontally, so the shading is positional again" % r)
        # And it must actually shade: one flat colour for the whole shape would pass the check above.
        self.assertGreater(len({r for r in rows}), 1, "nothing was shaded")
        self.assertLessEqual(len({r for r in rows}), 3)

class TestFrames(unittest.TestCase):

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

    These cases were measured on synthesised integer upscales of real TH155 sprites
    (`tools/make_pixel_scale_counterexample.py`, 6 sprites x factors 2/3/4 = 18 clean cases), and
    they pin all three findings, including the one that says the metric is weaker than it looks.
    """

    @staticmethod
    def _blocks(n, cols=4, rows=4):
        """A drawing whose every horizontal run is exactly `n`: an n x n block per source pixel.

        `n=1` is the hand-authored case (runs of 1), `n>1` is an integer upscale.
        """
        im = Image.new("RGBA", (cols * n, rows * n), (0, 0, 0, 0))
        px = im.load()
        for by in range(rows):
            for bx in range(cols):
                c = ((bx * 60 + 40) % 256, (by * 60 + 40) % 256, ((bx + by) * 40 + 30) % 256, 255)
                for y in range(by * n, (by + 1) * n):
                    for x in range(bx * n, (bx + 1) * n):
                        px[x, y] = c
        return im

    def test_a_hand_authored_drawing_reads_one(self):
        """The unit case -- but note what it actually returns.

        Runs of 1 are filtered out (`r for r in runs if r > 1`), so a drawing made of single pixels
        leaves nothing to take a GCD of and `_run_gcd` returns 0. Measured on real art it is 1: a
        hand drawing is not one-pixel confetti, it has runs of many lengths, and their GCD is 1.
        So the value 1 means "has runs of 1 and of other lengths" -- it does *not* mean "unit scale
        confirmed", which is the distinction `cli.py`'s wording walks past.
        """
        self.assertEqual(judge_fn(self._blocks(1)).pixel_scale, 0,
                         "all-runs-of-1 leaves no GCD to take; 0 is the honest answer here")

    def test_a_real_looking_hand_drawing_reads_one(self):
        """Runs of several different lengths, which is what hand-authored art actually looks like."""
        im = Image.new("RGBA", (24, 8), (0, 0, 0, 0))
        px = im.load()
        for y in range(8):
            x = 0
            for run, c in ((3, (200, 40, 40, 255)), (5, (40, 200, 40, 255)),
                           (2, (40, 40, 200, 255)), (7, (200, 200, 40, 255)),
                           (4, (200, 40, 200, 255)), (3, (40, 200, 200, 255))):
                for i in range(run):
                    if x + i < 24:
                        px[x + i, y] = c
                x += run
        self.assertEqual(judge_fn(im).pixel_scale, 1)

    def test_an_integer_upscale_reads_its_factor(self):
        """Measured 18/18 on real sprites. So the metric is not a constant -- it really does detect
        an integer upscale, which is why a stray pixel breaking it (next test) is a genuine
        weakness rather than a metric that never worked in the first place."""
        for n in (2, 3, 4, 6):
            with self.subTest(n=n):
                self.assertEqual(judge_fn(self._blocks(n)).pixel_scale, n)

    def test_one_stray_pixel_returns_it_to_one(self):
        """**The measured weakness, and the reason this metric cannot be shown as a silent number.**

        On the real sprites, recolouring a *single* pixel of a 3x upscale dropped the reading from
        3 to 1 in **16 of 18** clean cases (the two survivors had the stray land where a run of 1
        was already present, so the GCD was already 1). One short run drags the GCD down, so:

            a clean upscale              reads n
            an upscale with one bad px   reads 1   <- indistinguishable from hand-authored art

        `cli.py` prints "1 is normal for hand-authored art" next to the value, so on that image the
        report states something confidently wrong. This test pins the behaviour so the wording
        cannot quietly start implying that 1 means clean.
        """
        self.assertEqual(judge_fn(self._blocks(3)).pixel_scale, 3,
                         "control: the unmodified 3x drawing must read 3")
        im = self._blocks(3)
        px = im.load()
        px[3, 3] = ((px[3, 3][0] + 128) % 256, px[3, 3][1], px[3, 3][2], 255)
        self.assertEqual(judge_fn(im).pixel_scale, 1,
                         "one stray pixel should drop the reading to 1 -- if this fails, the metric "
                         "got more robust and the cli wording can be revisited")

    def test_quantisation_does_not_break_it(self):
        """The direction I expected to fail, and it does not.

        The TODO predicted "a man-made noisy upscale would drag the GCD back to 1 and look fine".
        Measured 0/18 -- quantising to 8 levels leaves every run intact, because the property is
        about run *lengths*, not colour count. What breaks it is a single miscoloured pixel, not a
        reduced palette. Recorded so the wrong prediction is not re-derived.
        """
        im = self._blocks(3)
        px = im.load()
        for y in range(im.height):
            for x in range(im.width):
                r, g, b, a = px[x, y]
                if a:
                    px[x, y] = ((r // 8) * 8, (g // 8) * 8, (b // 8) * 8, a)
        self.assertEqual(judge_fn(im).pixel_scale, 3)


if __name__ == "__main__":
    unittest.main()
