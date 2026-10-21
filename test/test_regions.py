# -*- coding: utf-8 -*-
"""Region verbs: read a rectangle, write it back somewhere else, or flip it where it is.

The distinction these tests guard is between **adding** a block (`blit`, skips the background) and
**moving** one (`stamp`, writes the background too). Getting it backwards is invisible on a full rectangle
and obvious on a sprite with holes: the flipped result becomes the original plus its mirror, sitting in
the holes the original left behind.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from ichiwatashi import builder as B
from ichiwatashi import cli

BG = B.Canvas(1, 1).bg


class TestCrop(unittest.TestCase):

    def test_it_takes_the_rectangle_inclusive(self):
        c = B.Canvas(8, 8)
        c.put(2, 3, "h")
        block = c.crop(2, 3, 4, 5)
        self.assertEqual((block.width, block.height), (3, 3))
        self.assertEqual(block.get(0, 0), "h")

    def test_a_rectangle_leaving_the_canvas_keeps_its_requested_size(self):
        """A block shrunk to what fitted would draw correctly only at the origin it was taken from."""
        c = B.Canvas(4, 4)
        c.put(0, 0, "h")
        block = c.crop(-2, -2, 1, 1)
        self.assertEqual((block.width, block.height), (4, 4))
        self.assertEqual(block.get(2, 2), "h", "the inside corner did not land at its offset")
        self.assertEqual(block.get(0, 0), BG)

    def test_an_empty_rectangle_is_refused(self):
        with self.assertRaises(ValueError) as ctx:
            B.Canvas(4, 4).crop(2, 2, 1, 3)
        self.assertIn("empty rectangle", str(ctx.exception))


class TestStampVersusBlit(unittest.TestCase):

    def test_stamp_writes_the_background_and_blit_does_not(self):
        target = B.Canvas(4, 4)
        target.put(0, 0, "w")
        block = B.Canvas(2, 2)          # entirely background
        target.stamp(block, 0, 0)
        self.assertEqual(target.get(0, 0), BG, "stamp should have cleared the pixel")
        target.put(0, 0, "w")
        target.blit(block, 0, 0)
        self.assertEqual(target.get(0, 0), "w", "blit must not erase what it lands on")


class TestFlipInPlace(unittest.TestCase):

    def test_flipping_swaps_the_rectangle_and_leaves_the_empties_empty(self):
        c = B.Canvas(8, 8)
        c.put(1, 2, "h")
        c.flip(0, 0, 3, 3)
        self.assertEqual(c.get(2, 2), "h")
        self.assertEqual(c.get(1, 2), BG, "the original pixel stayed: the block's empties were skipped")

    def test_pixels_outside_the_rectangle_do_not_move(self):
        c = B.Canvas(8, 8)
        c.put(1, 1, "h")
        c.put(6, 6, "w")
        c.flip(0, 0, 3, 3)
        self.assertEqual(c.get(6, 6), "w")

    def test_the_y_axis_flips_top_to_bottom(self):
        c = B.Canvas(8, 8)
        c.put(1, 1, "h")
        c.flip(0, 0, 3, 3, axis="y")
        self.assertEqual(c.get(1, 2), "h")

    def test_an_unknown_axis_is_refused(self):
        with self.assertRaises(ValueError) as ctx:
            B.Canvas(4, 4).flip(0, 0, 3, 3, axis="z")
        self.assertIn("axis", str(ctx.exception))

    def test_a_flip_is_one_history_entry(self):
        c = B.Canvas(8, 8)
        c.put(1, 1, "h")
        before = c.state()
        c.flip(0, 0, 3, 3)
        self.assertTrue(c.undo())
        self.assertEqual(c.state(), before)


class TestCopyThroughAScript(unittest.TestCase):

    def test_copy_moves_a_block_without_erasing_the_destination(self):
        spec = {"width": 8, "height": 8, "steps": [
            {"op": "rect", "x0": 0, "y0": 0, "x1": 1, "y1": 1, "key": "h"},
            {"op": "copy", "x0": 0, "y0": 0, "x1": 1, "y1": 1, "dx": 4, "dy": 4},
        ]}
        canvas = B.Canvas(8, 8)
        cli.apply_plan(canvas, cli.plan_steps(spec))
        self.assertEqual(canvas.get(0, 0), "h", "the source was erased")
        self.assertEqual(canvas.get(4, 4), "h", "the copy did not land at the offset")

    def test_copy_can_flip_on_the_way(self):
        """`flip` mirrors the block inside the rectangle it was taken from, then places it at the offset."""
        spec = {"width": 8, "height": 8, "steps": [
            {"op": "rect", "x0": 0, "y0": 0, "x1": 0, "y1": 0, "key": "h"},
            {"op": "copy", "x0": 0, "y0": 0, "x1": 1, "y1": 0, "dx": 0, "dy": 2, "flip": True},
        ]}
        canvas = B.Canvas(8, 8)
        cli.apply_plan(canvas, cli.plan_steps(spec))
        # the pixel was at the left of a two-wide block, so the flip puts it one column right
        self.assertEqual(canvas.get(1, 2), "h")
        self.assertEqual(canvas.get(0, 2), BG)


class TestValidation(unittest.TestCase):

    def test_a_region_needs_both_corners(self):
        for missing in ("x0", "y0", "x1", "y1"):
            step = {"op": "flip", "x0": 0, "y0": 0, "x1": 1, "y1": 1}
            del step[missing]
            with self.subTest(missing=missing):
                with self.assertRaises(cli.SpecError) as ctx:
                    cli.plan_steps({"width": 8, "height": 8, "steps": [step]})
                self.assertIn(missing, str(ctx.exception))

    def test_an_inverted_rectangle_is_refused_with_the_rule(self):
        with self.assertRaises(cli.SpecError) as ctx:
            cli.plan_steps({"width": 8, "height": 8,
                            "steps": [{"op": "flip", "x0": 4, "y0": 0, "x1": 2, "y1": 3}]})
        self.assertIn("x1 >= x0", str(ctx.exception))

    def test_copy_needs_an_offset(self):
        with self.assertRaises(cli.SpecError) as ctx:
            cli.plan_steps({"width": 8, "height": 8,
                            "steps": [{"op": "copy", "x0": 0, "y0": 0, "x1": 1, "y1": 1, "dx": 1}]})
        self.assertIn("dy", str(ctx.exception))

    def test_copy_flip_must_be_a_boolean(self):
        with self.assertRaises(cli.SpecError):
            cli.plan_steps({"width": 8, "height": 8,
                            "steps": [{"op": "copy", "x0": 0, "y0": 0, "x1": 1, "y1": 1,
                                       "dx": 1, "dy": 1, "flip": "yes"}]})


if __name__ == "__main__":
    unittest.main()
