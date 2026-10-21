# -*- coding: utf-8 -*-
"""A mask restricts where a write lands, and every path that writes has to obey it.

The test that matters most is the enumeration: `put`, `rect`, `outline`, `blit`, `stamp` and `mirror` all
reach the grid, and a mask honoured by one of them and not the others would look correct in the simplest
case and leak in every other.
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


class TestEveryWritePathObeysIt(unittest.TestCase):

    def test_put(self):
        c = B.Canvas(8, 8).mask(0, 0, 3, 3)
        c.put(1, 1, "h")
        c.put(5, 5, "h")
        self.assertEqual(c.get(1, 1), "h")
        self.assertEqual(c.get(5, 5), BG)

    def test_shapes_go_through_put_and_so_are_clipped(self):
        c = B.Canvas(8, 8).mask(0, 0, 3, 3)
        c.rect(0, 0, 7, 7, "h")
        self.assertEqual(c.get(0, 0), "h")
        self.assertEqual(c.get(3, 3), "h")
        self.assertEqual(c.get(4, 4), BG)

    def test_outline_is_clipped(self):
        c = B.Canvas(8, 8)
        c.rect(1, 1, 2, 2, "h")
        c.mask(0, 0, 2, 2)
        c.outline("k")
        self.assertEqual(c.get(2, 2), "h", "the filled pixel should be untouched")
        outside = [(x, y) for y in range(8) for x in range(8) if (x > 2 or y > 2) and c.get(x, y) != BG]
        self.assertEqual(outside, [], "the outline escaped the mask")

    def test_blit_is_clipped(self):
        c = B.Canvas(8, 8).mask(0, 0, 2, 2)
        block = B.Canvas(4, 4)
        block.rect(0, 0, 3, 3, "h")
        c.blit(block, 0, 0)
        self.assertEqual(c.get(2, 2), "h")
        self.assertEqual(c.get(3, 3), BG)

    def test_stamp_is_clipped(self):
        c = B.Canvas(8, 8).mask(0, 0, 2, 2)
        block = B.Canvas(4, 4)
        block.rect(0, 0, 3, 3, "h")
        c.stamp(block, 0, 0)
        self.assertEqual(c.get(2, 2), "h")
        self.assertEqual(c.get(3, 3), BG)

    def test_mirror_is_clipped(self):
        c = B.Canvas(16, 4).mask(0, 0, 7, 3)
        c.put(1, 1, "h")
        c.mirror(7)
        self.assertEqual(c.get(1, 1), "h")
        self.assertEqual(c.get(13, 1), BG, "the reflection went past the mask")

    def test_unmask_lets_writes_through_again(self):
        c = B.Canvas(8, 8).mask(0, 0, 1, 1)
        c.put(5, 5, "h")
        self.assertEqual(c.get(5, 5), BG)
        c.unmask()
        c.put(5, 5, "h")
        self.assertEqual(c.get(5, 5), "h")


class TestItsOwnRules(unittest.TestCase):

    def test_an_empty_rectangle_is_refused(self):
        with self.assertRaises(ValueError) as ctx:
            B.Canvas(8, 8).mask(3, 3, 1, 1)
        self.assertIn("empty mask", str(ctx.exception))

    def test_a_mask_larger_than_the_canvas_is_fine(self):
        c = B.Canvas(8, 8).mask(-4, -4, 20, 20)
        c.put(7, 7, "h")
        self.assertEqual(c.get(7, 7), "h")

    def test_a_mask_is_not_a_history_entry(self):
        """A mask is the condition a drawing was made under, not a drawing."""
        c = B.Canvas(8, 8)
        before = len(c.history())
        c.mask(0, 0, 3, 3)
        self.assertEqual(len(c.history()), before)

    def test_recolor_ignores_the_mask_on_purpose(self):
        """`recolor` rewrites pixels that are already there; where they were drawn is not its business."""
        c = B.Canvas(8, 8)
        c.rect(0, 0, 7, 7, "h")
        c.mask(0, 0, 1, 1)
        c.recolor({"h": "w"})
        self.assertEqual(c.get(6, 6), "w")


class TestThroughAScript(unittest.TestCase):

    def test_mask_and_unmask_are_steps(self):
        spec = {"width": 8, "height": 8, "steps": [
            {"op": "mask", "x0": 0, "y0": 0, "x1": 2, "y1": 2},
            {"op": "rect", "x0": 0, "y0": 0, "x1": 7, "y1": 7, "key": "h"},
            {"op": "unmask"},
            {"op": "rect", "x0": 6, "y0": 6, "x1": 7, "y1": 7, "key": "w"},
        ]}
        canvas = B.Canvas(8, 8)
        cli.apply_plan(canvas, cli.plan_steps(spec))
        self.assertEqual(canvas.get(1, 1), "h")
        self.assertEqual(canvas.get(4, 4), BG, "the masked rectangle leaked")
        self.assertEqual(canvas.get(6, 6), "w")

    def test_an_inverted_mask_is_refused_with_the_rule(self):
        with self.assertRaises(cli.SpecError) as ctx:
            cli.plan_steps({"width": 8, "height": 8,
                            "steps": [{"op": "mask", "x0": 4, "y0": 0, "x1": 2, "y1": 3}]})
        self.assertIn("x1 >= x0", str(ctx.exception))

    def test_a_mask_needs_all_four_numbers(self):
        with self.assertRaises(cli.SpecError) as ctx:
            cli.plan_steps({"width": 8, "height": 8,
                            "steps": [{"op": "mask", "x0": 0, "y0": 0, "x1": 3}]})
        self.assertIn("y1", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
