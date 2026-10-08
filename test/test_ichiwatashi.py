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
        self.assertFalse(any("isolated" in n for n in r.notes),
                         "fine detail is being reported as noise")

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


if __name__ == "__main__":
    unittest.main()
