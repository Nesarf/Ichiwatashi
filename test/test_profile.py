# -*- coding: utf-8 -*-
"""The placement between generations: what it says, what it refuses to say, and why the numbers are the
judge's own.

The property worth keeping is that a position can always be opened up into the metrics it came from.
So most of these tests are about the arithmetic being the *same* arithmetic `judge` uses -- one band
width outside is one, two metrics half a width out is `sqrt(0.5)` and not one -- and about the case
where the answer is "these two generations cannot be told apart".
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from ichiwatashi import calibration as C
from ichiwatashi import profile as PR

try:
    from PIL import Image
    HAVE_PILLOW = True
except ImportError:
    HAVE_PILLOW = False

needs_pillow = unittest.skipUnless(HAVE_PILLOW, "pillow is the `window` extra and is not installed")


def median_row(generation):
    """A report sitting exactly on one generation's medians, for every metric it compares."""
    row = {}
    for metric in PR.METRICS:
        ref = C.REFERENCE_BY_GENERATION[generation].get(metric)
        if ref is not None:
            row[metric] = ref.median
    return row


class TestTheShapeOfARow(unittest.TestCase):

    def test_every_generation_gets_a_row_ordered_by_distance(self):
        row = median_row(C.DEFAULT_GENERATION)
        result = PR.nearest(row)
        self.assertEqual(len(result["all"]), len(C.GENERATIONS))
        distances = [r["distance"] for r in result["all"]]
        self.assertEqual(distances, sorted(distances))

    def test_a_metric_a_generation_does_not_carry_is_not_compared(self):
        """TH155 has no `colours_used` band, and the count travels with the row so the asymmetry shows."""
        row = median_row(C.DEFAULT_GENERATION)
        th123 = PR.position(row, "th105/th123")
        th155 = PR.position(row, "th155")
        self.assertEqual(th123["compared"], len(PR.METRICS))
        self.assertEqual(th155["compared"], len(PR.METRICS) - 1)
        self.assertNotIn("colours_used", [r["metric"] for r in th155["rows"]])

    def test_an_unknown_generation_is_refused_rather_than_defaulted(self):
        with self.assertRaises(ValueError) as ctx:
            PR.position(median_row(C.DEFAULT_GENERATION), "th999")
        self.assertIn("th999", str(ctx.exception))


class TestTheArithmetic(unittest.TestCase):

    def test_a_value_inside_every_band_costs_nothing(self):
        result = PR.position(median_row(C.DEFAULT_GENERATION), C.DEFAULT_GENERATION)
        self.assertEqual(result["distance"], 0.0)
        self.assertEqual(result["inside"], result["compared"])

    def test_one_band_width_outside_is_a_distance_of_one(self):
        ref = C.REFERENCE_BY_GENERATION[C.DEFAULT_GENERATION]["colours_used"]
        width = ref.p95 - ref.p05
        row = median_row(C.DEFAULT_GENERATION)
        row["colours_used"] = ref.p95 + width
        result = PR.position(row, C.DEFAULT_GENERATION)
        self.assertAlmostEqual(result["distance"], 1.0, places=4)

    def test_two_metrics_half_a_width_out_is_a_length_not_a_sum(self):
        """`0.5` out on two metrics is `sqrt(0.5)` and not `1.0`: a sum would call the same
        displacement twice as far purely because it happened on two axes."""
        ref = C.REFERENCE_BY_GENERATION[C.DEFAULT_GENERATION]
        row = median_row(C.DEFAULT_GENERATION)
        for metric in ("colours_used", "isolated_rate"):
            band = ref[metric]
            row[metric] = band.p95 + 0.5 * (band.p95 - band.p05)
        result = PR.position(row, C.DEFAULT_GENERATION)
        self.assertAlmostEqual(result["distance"], 0.5 ** 0.5, places=3)

    def test_the_distance_can_be_read_back_as_the_metrics_it_came_from(self):
        ref = C.REFERENCE_BY_GENERATION[C.DEFAULT_GENERATION]["bbox_fill"]
        row = median_row(C.DEFAULT_GENERATION)
        row["bbox_fill"] = ref.p05 - 2 * (ref.p95 - ref.p05)
        result = PR.position(row, C.DEFAULT_GENERATION)
        worst = max(result["rows"], key=lambda r: abs(r["offset"]))
        self.assertEqual(worst["metric"], "bbox_fill")
        # The offset is a magnitude and the side is a separate field, because `how_far` returns both
        # "far below" and "far above" as a positive number -- which its own docstring claimed otherwise
        # about until this module needed to say which side.
        self.assertEqual(worst["direction"], "below")
        self.assertAlmostEqual(worst["offset"], 2.0, places=3)


class TestWhatItRefusesToSay(unittest.TestCase):

    def test_two_generations_at_the_same_distance_are_not_separated(self):
        """A sprite inside both bands carries no evidence for either, and saying which sorted first
        would be a coin flip with a decimal point on it."""
        result = PR.nearest(median_row(C.DEFAULT_GENERATION))
        self.assertFalse(result["separated"])

    def test_a_sprite_far_outside_one_generation_is_separated(self):
        ref = C.REFERENCE_BY_GENERATION["th105/th123"]["colours_used"]
        row = median_row(C.DEFAULT_GENERATION)
        row["colours_used"] = ref.p95 + 3 * (ref.p95 - ref.p05)
        result = PR.nearest(row)
        self.assertTrue(result["separated"])
        self.assertEqual(result["placed"]["generation"], "th155")

    def test_the_lines_name_a_state_and_not_a_grade(self):
        result = PR.nearest(median_row(C.DEFAULT_GENERATION))
        text = PR.describe(result, "sprite.png")
        for word in ("wrong", "bad", "good", "fail"):
            self.assertNotIn(word, text.lower())
        self.assertIn("inside", text)
        self.assertIn("sprite.png", text)


@needs_pillow
class TestAgainstARealMeasurement(unittest.TestCase):

    def test_it_places_a_drawn_sprite_without_reshaping_the_judge(self):
        import random
        from ichiwatashi.judge import judge

        random.seed(7)
        im = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
        pixels = [[(0, 0, 0, 0)] * 32 for _ in range(32)]
        palette = [(20 * i + 5, 40 + 6 * i, 90 - 2 * i, 255) for i in range(18)]
        for y in range(6, 26):
            for x in range(8, 24):
                pixels[y][x] = random.choice(palette)
        for y in range(32):
            for x in range(32):
                im.putpixel((x, y), pixels[y][x])
        path = Path(self.id().replace(".", "_") + ".png")
        with self.subTest(path=str(path)):
            im.save(path)
            try:
                report = judge(str(path), anyway=True)
                result = PR.nearest(report)
                self.assertGreaterEqual(result["placed"]["compared"], 1)
                self.assertGreaterEqual(result["placed"]["distance"], 0.0)
                self.assertIn("nearest", PR.describe(result))
            finally:
                path.unlink()


if __name__ == "__main__":
    unittest.main()
