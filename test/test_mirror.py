# -*- coding: utf-8 -*-
"""Reflecting one half onto the other: the axis is a drawing decision, and a mirror must not eat work.

The property that matters here is not "the sprite looks symmetric". It is that **the operation cannot
silently destroy something**: a mirror that copied the background over the destination side would erase
whatever had already been drawn there, and the result would still be a symmetric-looking image.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from ichiwatashi import builder as B
from ichiwatashi import cli


class TestTheAxisIsAColumn(unittest.TestCase):
    """On an even width the geometric centre falls between two columns, and the tool does not pick one."""

    def test_a_fractional_axis_is_refused(self):
        with self.assertRaises(ValueError) as ctx:
            B.Canvas(32, 8).mirror(15.5)
        self.assertIn("integer", str(ctx.exception))

    def test_an_axis_outside_the_canvas_is_refused(self):
        for axis in (-1, 32):
            with self.subTest(axis=axis):
                with self.assertRaises(ValueError):
                    B.Canvas(32, 8).mirror(axis)

    def test_an_unknown_direction_is_refused(self):
        with self.assertRaises(ValueError):
            B.Canvas(32, 8).mirror(15, direction="sideways")


class TestWhatIsCopied(unittest.TestCase):

    def test_the_left_half_lands_on_the_right(self):
        c = B.Canvas(32, 4)
        c.put(10, 1, "h")
        c.mirror(15)
        self.assertEqual(c.get(10, 1), "h")
        self.assertEqual(c.get(2 * 15 - 10, 1), "h")

    def test_the_axis_column_maps_to_itself(self):
        c = B.Canvas(32, 4)
        c.put(15, 2, "k")
        c.mirror(15)
        self.assertEqual(c.get(15, 2), "k")
        self.assertEqual(c.get(14, 2), B.Canvas(1, 1).bg)

    def test_the_background_is_not_copied_over_the_other_side(self):
        """The failure this prevents: a mirror that writes background erases the destination half."""
        c = B.Canvas(32, 4)
        c.put(20, 1, "h")          # drawn on the right half, which `left` treats as the destination
        c.put(10, 2, "w")
        c.mirror(15)
        self.assertEqual(c.get(20, 1), "h", "background written from the empty left half erased it")
        self.assertEqual(c.get(10, 2), "w")
        self.assertEqual(c.get(20, 2), "w")

    def test_the_right_half_can_be_the_source(self):
        c = B.Canvas(32, 4)
        c.put(20, 1, "h")
        c.mirror(15, direction="right")
        self.assertEqual(c.get(10, 1), "h")

    def test_both_completes_the_empty_side_and_keeps_what_is_there(self):
        c = B.Canvas(32, 4)
        c.put(4, 1, "h")           # left only
        c.put(26, 2, "w")          # right only
        c.mirror(15, direction="both")
        self.assertEqual(c.get(26, 1), "h")
        self.assertEqual(c.get(4, 2), "w")


class TestHistory(unittest.TestCase):

    def test_one_reflection_is_one_step_back(self):
        c = B.Canvas(32, 4)
        c.put(10, 1, "h")
        before = c.state()
        c.mirror(15)
        self.assertNotEqual(c.state(), before)
        self.assertTrue(c.undo())
        self.assertEqual(c.state(), before)


class TestInAScript(unittest.TestCase):

    def test_the_validator_accepts_and_validates_a_mirror_step(self):
        plan = cli.plan_steps({"width": 32, "height": 8,
                               "steps": [{"op": "mirror", "axis": 15}]})
        self.assertEqual(plan, [("mirror", {"axis": 15, "direction": "left"})])
        for bad, message in (
            ({"op": "mirror"}, "'axis' must be an integer"),
            ({"op": "mirror", "axis": "15"}, "'axis' must be an integer"),
            ({"op": "mirror", "axis": 15.5}, "'axis' must be an integer"),
            ({"op": "mirror", "axis": 15, "direction": "up"}, "'direction' must be"),
        ):
            with self.subTest(step=bad):
                with self.assertRaises(cli.SpecError) as ctx:
                    cli.plan_steps({"width": 32, "height": 8, "steps": [bad]})
                self.assertIn(message, str(ctx.exception))

    def test_the_plan_draws_through_the_shared_applier(self):
        """`build` and `grid` share one loop now; this is the loop, exercised directly."""
        spec = {"width": 32, "height": 8, "steps": [
            {"op": "rect", "x0": 4, "y0": 1, "x1": 10, "y1": 3, "key": "h"},
            {"op": "mirror", "axis": 15},
        ]}
        c = B.Canvas(spec["width"], spec["height"])
        applied, undone, redone = cli.apply_plan(c, cli.plan_steps(spec))
        self.assertEqual((applied, undone, redone), (2, 0, 0))
        # the rect's nearest column to the axis mirrors to its counterpart, one pixel at a time
        for y in range(1, 4):
            for x in range(4, 11):
                self.assertEqual(c.get(2 * 15 - x, y), "h", "column %d did not reach its mirror" % x)


if __name__ == "__main__":
    unittest.main()
