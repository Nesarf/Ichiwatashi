# -*- coding: utf-8 -*-
"""A unit of N pixels: coordinates land on its grid, sizes do not.

The distinction is the whole feature. Snapping a radius or a taper width changes the shape; snapping a
position only decides where the shape sits. With `unit` at its default of 1 every call is the identity, so
nothing that existed before this changed.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from ichiwatashi import builder as B
from ichiwatashi import cli
from ichiwatashi import layers as L

BG = B.Canvas(1, 1).bg


class TestSnapping(unittest.TestCase):

    def test_it_rounds_to_the_nearest_multiple(self):
        c = B.Canvas(16, 16, unit=4)
        self.assertEqual(c.snap(0), 0)
        self.assertEqual(c.snap(1), 0)
        self.assertEqual(c.snap(2), 4)
        self.assertEqual(c.snap(5), 4)
        self.assertEqual(c.snap(6), 8)

    def test_negative_coordinates_round_away_from_zero_at_the_half(self):
        c = B.Canvas(16, 16, unit=4)
        self.assertEqual(c.snap(-1), 0)
        self.assertEqual(c.snap(-2), -4)
        self.assertEqual(c.snap(-5), -4)
        self.assertEqual(c.snap(-6), -8)

    def test_a_unit_of_one_is_the_identity(self):
        c = B.Canvas(16, 16)
        for v in (-7, -1, 0, 1, 5, 13):
            self.assertEqual(c.snap(v), v)

    def test_a_bad_unit_is_refused(self):
        for bad in (0, -2, True, 1.5, "4"):
            with self.subTest(unit=bad):
                with self.assertRaises(ValueError):
                    B.Canvas(8, 8, unit=bad)


class TestThroughAScript(unittest.TestCase):

    def test_positions_move_to_the_grid(self):
        spec = {"width": 16, "height": 16, "unit": 4, "steps": [
            {"op": "rect", "x0": 5, "y0": 5, "x1": 9, "y1": 9, "key": "h"},
        ]}
        canvas = B.Canvas(16, 16, unit=4)
        cli.apply_plan(canvas, cli.plan_steps(spec))
        # 5 -> 4 and 9 -> 8, so the rectangle is 4..8 inclusive
        self.assertEqual(canvas.get(4, 4), "h")
        self.assertEqual(canvas.get(8, 8), "h")
        self.assertEqual(canvas.get(3, 4), BG)
        self.assertEqual(canvas.get(4, 8), "h")
        self.assertEqual(canvas.get(9, 8), BG)

    def test_a_radius_keeps_its_size(self):
        """Snapping a radius would change the shape; only positions are on the grid."""
        spec = {"width": 16, "height": 16, "unit": 4, "steps": [
            {"op": "disc", "cx": 8, "cy": 8, "r": 3, "key": "h"},
        ]}
        snapped = B.Canvas(16, 16, unit=4)
        cli.apply_plan(snapped, cli.plan_steps(spec))
        plain = B.Canvas(16, 16)
        plain.disc(8, 8, 3, "h")
        self.assertEqual(snapped.state(), plain.state(),
                         "a radius of 3 on the grid drew a different shape from a radius of 3 off it")

    def test_a_bad_unit_in_the_script_is_refused_by_name(self):
        for bad in (0, -1, "4"):
            with self.subTest(unit=bad):
                with self.assertRaises(cli.SpecError) as ctx:
                    cli.plan_steps({"width": 8, "height": 8, "unit": bad, "steps": []})
                self.assertIn("unit", str(ctx.exception))


class TestItTravelsWithTheFile(unittest.TestCase):

    def test_the_grid_carries_the_unit_and_reads_it_back(self):
        canvas = B.Canvas(8, 8, unit=2)
        canvas.rect(0, 0, 3, 3, "h")
        grid = canvas.to_grid({"h": (255, 255, 255), ".": None})
        self.assertEqual(grid["unit"], 2)
        back, _palette = B.from_grid(grid)
        self.assertEqual(back.unit, 2)
        self.assertEqual(back.state(), canvas.state())

    def test_every_layer_shares_the_unit(self):
        stack = L.Layers(8, 8, ["a", "b"], unit=4)
        self.assertEqual(stack.unit, 4)
        self.assertEqual(stack.snap(5), 4)
        self.assertEqual(stack.layer("b").unit, 4)


if __name__ == "__main__":
    unittest.main()
