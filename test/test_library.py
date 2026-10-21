# -*- coding: utf-8 -*-
"""A folder of parts: what is in it, what names it, and what is no longer named by anything.

The scan rests on the distinction the format already makes -- a drawing declares a palette, a part does not --
so it works on a folder nobody has organised, which is the only kind of folder that exists.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from ichiwatashi import library as LIB


def write(directory, name, body):
    path = Path(directory) / name
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


PART = {"width": 8, "height": 8, "steps": [
    {"op": "rect", "x0": 1, "y0": 1, "x1": 3, "y1": 3, "key": "h"}]}
DRAWING = {"width": 16, "height": 16, "palette": {"h": "#111111"},
           "steps": [{"op": "part", "file": "body.json", "x": 0, "y": 0}]}


class TestTheScan(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_palette_is_what_makes_a_file_a_drawing(self):
        write(self.dir, "body.json", PART)
        write(self.dir, "figure.json", DRAWING)
        result = LIB.scan(self.dir)
        self.assertEqual([p["name"] for p in result["parts"]], ["body.json"])
        self.assertEqual([s["name"] for s in result["scripts"]], ["figure.json"])

    def test_the_reference_resolves_to_the_part(self):
        write(self.dir, "body.json", PART)
        write(self.dir, "figure.json", DRAWING)
        result = LIB.scan(self.dir)
        self.assertEqual(len(result["scripts"][0]["uses"]), 1)
        self.assertEqual(result["scripts"][0]["uses"][0], (Path(self.dir) / "body.json").resolve())

    def test_a_part_nothing_names_is_an_orphan(self):
        write(self.dir, "body.json", PART)
        write(self.dir, "old_hand.json", PART)
        write(self.dir, "figure.json", DRAWING)
        result = LIB.scan(self.dir)
        self.assertEqual(result["orphans"], ["old_hand.json"])

    def test_a_named_part_that_is_absent_is_reported_with_both_names(self):
        write(self.dir, "figure.json", DRAWING)
        result = LIB.scan(self.dir)
        self.assertEqual(result["missing"], [("figure.json", "body.json")])

    def test_anything_that_is_not_a_shape_script_is_ignored_not_guessed(self):
        write(self.dir, "body.json", PART)
        write(self.dir, "notes.json", {"hello": "world"})
        (Path(self.dir) / "broken.json").write_text("{not json", encoding="utf-8")
        result = LIB.scan(self.dir)
        self.assertEqual(sorted(result["ignored"]), ["broken.json", "notes.json"])

    def test_a_directory_that_is_not_one_is_refused(self):
        with self.assertRaises(ValueError):
            LIB.scan(Path(self.dir) / "nowhere")


class TestTheReport(unittest.TestCase):

    def test_it_names_what_uses_what_and_what_uses_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "body.json", PART)
            write(d, "unused.json", PART)
            write(d, "figure.json", DRAWING)
            text = LIB.describe(LIB.scan(d))
        self.assertIn("2 part(s), 1 drawing(s)", text)
        self.assertIn("figure.json", text)
        self.assertIn("not used by any drawing here", text)

    def test_a_missing_part_is_called_out_where_it_is_named(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "figure.json", DRAWING)
            text = LIB.describe(LIB.scan(d))
        self.assertIn("MISSING body.json", text)
        self.assertIn("figure.json", text)


if __name__ == "__main__":
    unittest.main()
