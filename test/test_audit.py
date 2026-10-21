# -*- coding: utf-8 -*-
"""The construction-time hints: contradictions inside a script, not a comparison with real art.

Every hint here has to be checkable from the script alone. A check that compares a three-colour sprite with a
26-colour fighting-game frame would fire on most deliberate drawings and teach everyone to ignore the
report -- which is the failure `calibration.py` already records twice.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from ichiwatashi import audit as A
from ichiwatashi import cli


def spec(**over):
    base = {"width": 16, "height": 16,
            "palette": {"h": (1, 1, 1), "k": (0, 0, 0)},
            "steps": [{"op": "rect", "x0": 2, "y0": 2, "x1": 12, "y1": 12, "key": "h"},
                      {"op": "outline", "key": "k"}]}
    base.update(over)
    return base


def hints(s):
    return A.hints(s, cli.plan_steps(s))


class TestACleanScriptSaysNothing(unittest.TestCase):

    def test_nothing_to_report(self):
        self.assertEqual(hints(spec()), [])


class TestEachHint(unittest.TestCase):

    def test_an_entry_nothing_uses(self):
        s = spec(palette={"h": (1, 1, 1), "k": (0, 0, 0), "z": (9, 9, 9)})
        self.assertTrue(any("'z'" in line for line in hints(s)))

    def test_the_background_is_not_an_unused_entry(self):
        """Every canvas fills itself with the background, so no step names it -- and a hint that is always
        on is a hint nobody reads."""
        self.assertEqual(hints(spec()), [])
        s = spec(palette={".": None, "h": (1, 1, 1), "k": (0, 0, 0)})
        self.assertEqual(hints(s), [])

    def test_a_shading_band_counts_as_using_its_colour(self):
        """The band keys are targets, not sources; counting only sources called every band unused."""
        s = spec(palette={"h": (1, 1, 1), "hl": (2, 2, 2), "hd": (3, 3, 3), "k": (0, 0, 0)},
                 steps=[{"op": "rect", "x0": 2, "y0": 2, "x1": 12, "y1": 12, "key": "h"},
                        {"op": "shade", "light": {"h": "hl"}, "dark": {"h": "hd"}},
                        {"op": "outline", "key": "k"}])
        self.assertEqual(hints(s), [])

    def test_shaded_but_not_outlined(self):
        s = spec(palette={"h": (1, 1, 1), "hl": (2, 2, 2), "hd": (3, 3, 3)},
                 steps=[{"op": "rect", "x0": 2, "y0": 2, "x1": 12, "y1": 12, "key": "h"},
                        {"op": "shade", "light": {"h": "hl"}, "dark": {"h": "hd"}}])
        self.assertTrue(any("shaded and not outlined" in line for line in hints(s)))

    def test_an_outline_sharing_a_band_colour(self):
        s = spec(palette={"h": (1, 1, 1), "hl": (2, 2, 2), "hd": (3, 3, 3)},
                 steps=[{"op": "rect", "x0": 2, "y0": 2, "x1": 12, "y1": 12, "key": "h"},
                        {"op": "shade", "light": {"h": "hl"}, "dark": {"h": "hd"}},
                        {"op": "outline", "key": "hd"}])
        self.assertTrue(any("share" in line for line in hints(s)))

    def test_a_declared_layer_nothing_draws_on(self):
        s = spec(layers=["body", "ink"],
                 steps=[{"op": "rect", "x0": 2, "y0": 2, "x1": 12, "y1": 12, "key": "h",
                         "layer": "body"},
                        {"op": "outline", "key": "k", "layer": "body"}])
        self.assertTrue(any("'ink'" in line for line in hints(s)))

    def test_a_canvas_that_is_not_a_whole_number_of_units(self):
        s = spec(unit=4, width=18)
        self.assertTrue(any("width is 18" in line for line in hints(s)))

    def test_a_palette_large_enough_to_be_a_texture(self):
        big = {"k%d" % i: (i, i, i) for i in range(40)}
        s = spec(palette=big,
                 steps=[{"op": "rect", "x0": 2, "y0": 2, "x1": 12, "y1": 12, "key": "k0"}])
        self.assertTrue(any("40 entries" in line for line in hints(s)))


class TestTheShadeStepItself(unittest.TestCase):

    def test_both_bands_are_required(self):
        for side in ("light", "dark"):
            step = {"op": "shade", "light": {"h": "hl"}, "dark": {"h": "hd"}}
            del step[side]
            with self.subTest(side=side):
                with self.assertRaises(cli.SpecError) as ctx:
                    cli.plan_steps({"width": 8, "height": 8, "steps": [step]})
                self.assertIn(side, str(ctx.exception))

    def test_the_depth_must_be_a_positive_integer(self):
        with self.assertRaises(cli.SpecError):
            cli.plan_steps({"width": 8, "height": 8,
                            "steps": [{"op": "shade", "light": {"h": "hl"}, "dark": {"h": "hd"},
                                       "depth": 0}]})

    def test_it_draws(self):
        # Single-character keys: the grid is a character grid, and `_write` refuses anything longer.
        s = spec(palette={"h": (1, 1, 1), "l": (2, 2, 2), "d": (3, 3, 3), "k": (0, 0, 0)},
                 steps=[{"op": "rect", "x0": 2, "y0": 2, "x1": 12, "y1": 12, "key": "h"},
                        {"op": "shade", "light": {"h": "l"}, "dark": {"h": "d"}}])
        from ichiwatashi import builder as B
        canvas = B.Canvas(16, 16)
        cli.apply_plan(canvas, cli.plan_steps(s))
        rows = canvas.rows()
        self.assertIn("l", rows[2] + rows[3])
        self.assertIn("d", rows[11] + rows[12])


class TestAKeyIsOneCharacter(unittest.TestCase):
    """The grid is a character grid, so a longer key shifts every column after it -- but only when it is
    written as one. A panel's keys are two characters and are correct, which is why the refusal is in
    `rows()` rather than at write time."""

    def test_writing_a_grid_with_a_two_character_key_is_refused(self):
        from ichiwatashi import builder as B
        canvas = B.Canvas(8, 8)
        canvas.put(0, 0, "hl")
        with self.assertRaises(ValueError) as ctx:
            canvas.rows()
        self.assertIn("one character", str(ctx.exception))

    def test_rendering_the_same_canvas_as_an_image_is_fine(self):
        """Two-character keys render; only the text form has the requirement."""
        from ichiwatashi import builder as B
        canvas = B.Canvas(4, 4)
        canvas.put(0, 0, "hl")
        image = canvas.to_image({"hl": (255, 0, 0, 255), ".": None})
        self.assertEqual(image.size, (4, 4))


if __name__ == "__main__":
    unittest.main()
