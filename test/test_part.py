# -*- coding: utf-8 -*-
"""Parts: one drawing placed inside another, which is what makes a body reusable across expressions.

The promise kept here is deliberately small -- one level deep, keys shared with the host palette, pixels
clipped at the edge rather than refused -- and most of these tests are about the smallness being real
rather than about the drawing looking right.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from ichiwatashi import builder as B
from ichiwatashi import cli


def write(directory, name, body):
    path = Path(directory) / name
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


class TestTheValidator(unittest.TestCase):

    def test_a_part_needs_a_file_and_a_position(self):
        for step, missing in (({"op": "part", "x": 0, "y": 0}, "file"),
                              ({"op": "part", "file": "a.json", "y": 0}, "x"),
                              ({"op": "part", "file": "a.json", "x": 0}, "y")):
            with self.subTest(step=step):
                with self.assertRaises(cli.SpecError) as ctx:
                    cli.plan_steps({"width": 8, "height": 8, "steps": [step]})
                self.assertIn(missing, str(ctx.exception))

    def test_flip_must_be_a_boolean(self):
        with self.assertRaises(cli.SpecError) as ctx:
            cli.plan_steps({"width": 8, "height": 8,
                            "steps": [{"op": "part", "file": "a.json", "x": 0, "y": 0, "flip": "yes"}]})
        self.assertIn("true or false", str(ctx.exception))


class TestPlacing(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        write(self.dir, "dot.json", {"width": 4, "height": 4, "steps": [
            {"op": "rect", "x0": 0, "y0": 0, "x1": 1, "y1": 1, "key": "h"},
        ]})

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_part_lands_at_the_offset(self):
        spec = {"width": 16, "height": 16, "steps": [
            {"op": "part", "file": "dot.json", "x": 5, "y": 7},
        ]}
        canvas = B.Canvas(16, 16)
        cli.apply_plan(canvas, cli.plan_steps(spec), base_dir=self.dir)
        self.assertEqual(canvas.get(5, 7), "h")
        self.assertEqual(canvas.get(6, 8), "h")
        self.assertEqual(canvas.get(4, 7), B.Canvas(1, 1).bg)

    def test_the_part_background_does_not_erase_the_host(self):
        """A part placed over existing work must add to it, not blank it out."""
        spec = {"width": 16, "height": 16, "steps": [
            {"op": "part", "file": "dot.json", "x": 0, "y": 0},
        ]}
        canvas = B.Canvas(16, 16)
        canvas.put(3, 3, "w")      # inside the part's empty area
        cli.apply_plan(canvas, cli.plan_steps(spec), base_dir=self.dir)
        self.assertEqual(canvas.get(3, 3), "w")

    def test_flip_mirrors_the_part_before_placing(self):
        spec = {"width": 16, "height": 16, "steps": [
            {"op": "part", "file": "dot.json", "x": 0, "y": 0, "flip": True},
        ]}
        canvas = B.Canvas(16, 16)
        cli.apply_plan(canvas, cli.plan_steps(spec), base_dir=self.dir)
        # the 2x2 block in the corner moves to the other side of the part's own 4x4 canvas
        self.assertEqual(canvas.get(2, 0), "h")
        self.assertEqual(canvas.get(0, 0), B.Canvas(1, 1).bg)

    def test_pixels_outside_the_host_are_clipped_not_refused(self):
        spec = {"width": 8, "height": 8, "steps": [
            {"op": "part", "file": "dot.json", "x": -1, "y": -1},
        ]}
        canvas = B.Canvas(8, 8)
        cli.apply_plan(canvas, cli.plan_steps(spec), base_dir=self.dir)
        self.assertEqual(canvas.get(0, 0), "h")

    def test_a_missing_part_names_the_file(self):
        spec = {"width": 8, "height": 8, "steps": [
            {"op": "part", "file": "nowhere.json", "x": 0, "y": 0},
        ]}
        with self.assertRaises(cli.SpecError) as ctx:
            cli.apply_plan(B.Canvas(8, 8), cli.plan_steps(spec), base_dir=self.dir)
        self.assertIn("nowhere.json", str(ctx.exception))

    def test_a_relative_part_without_a_base_directory_is_refused(self):
        spec = {"width": 8, "height": 8, "steps": [
            {"op": "part", "file": "dot.json", "x": 0, "y": 0},
        ]}
        with self.assertRaises(cli.SpecError) as ctx:
            cli.apply_plan(B.Canvas(8, 8), cli.plan_steps(spec))
        self.assertIn("base directory", str(ctx.exception))


class TestOneLevelOnly(unittest.TestCase):

    def test_a_part_that_places_a_part_is_refused_by_name(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "inner.json", {"width": 4, "height": 4, "steps": [
                {"op": "rect", "x0": 0, "y0": 0, "x1": 1, "y1": 1, "key": "h"},
            ]})
            write(d, "outer.json", {"width": 8, "height": 8, "steps": [
                {"op": "part", "file": "inner.json", "x": 1, "y": 1},
            ]})
            spec = {"width": 16, "height": 16, "steps": [
                {"op": "part", "file": "outer.json", "x": 0, "y": 0},
            ]}
            with self.assertRaises(cli.SpecError) as ctx:
                cli.apply_plan(B.Canvas(16, 16), cli.plan_steps(spec), base_dir=d)
            self.assertIn("may not place another part", str(ctx.exception))


class TestOneBodyManyExpressions(unittest.TestCase):
    """The reason parts exist: the body is drawn once and each expression adds to it."""

    def test_two_expressions_share_a_body_and_differ_in_the_part_that_changes(self):
        body = {"width": 8, "height": 8, "steps": [
            {"op": "rect", "x0": 2, "y0": 4, "x1": 5, "y1": 7, "key": "h"},
        ]}
        with tempfile.TemporaryDirectory() as d:
            write(d, "body.json", body)
            write(d, "eye_up.json", {"width": 8, "height": 8, "steps": [
                {"op": "rect", "x0": 3, "y0": 1, "x1": 3, "y1": 1, "key": "w"},
            ]})
            write(d, "eye_down.json", {"width": 8, "height": 8, "steps": [
                {"op": "rect", "x0": 3, "y0": 2, "x1": 3, "y1": 2, "key": "w"},
            ]})
            made = []
            for expression in ("eye_up.json", "eye_down.json"):
                spec = {"width": 8, "height": 8, "steps": [
                    {"op": "part", "file": "body.json", "x": 0, "y": 0},
                    {"op": "part", "file": expression, "x": 0, "y": 0},
                ]}
                canvas = B.Canvas(8, 8)
                cli.apply_plan(canvas, cli.plan_steps(spec), base_dir=d)
                self.assertEqual(canvas.get(2, 4), "h", "the body is missing from both expressions")
                made.append(canvas.state())
            self.assertNotEqual(made[0], made[1], "the two expressions came out identical")


if __name__ == "__main__":
    unittest.main()
