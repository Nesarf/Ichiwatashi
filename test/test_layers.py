# -*- coding: utf-8 -*-
"""Layers: an ordered stack of passes, each with its own history, composed on the way out.

Two properties carry the weight here. **Composition copies non-background pixels**, so a pass that drew
nothing cannot blank the pass under it -- the same rule `blit`, `mirror` and parts all follow. And **the
export path composes**: `to_image` and `to_grid` give the whole drawing, because a reader looks at the
whole drawing and not at whichever pass happened to be current.
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


class TestTheStack(unittest.TestCase):

    def test_a_script_without_layers_still_works(self):
        spec = {"width": 8, "height": 8, "steps": [
            {"op": "rect", "x0": 1, "y0": 1, "x1": 2, "y1": 2, "key": "h"},
        ]}
        canvas = L.Layers(8, 8, spec.get("layers"))
        cli.apply_plan(canvas, cli.plan_steps(spec))
        self.assertEqual(canvas.names, ["base"])
        self.assertEqual(canvas.flatten().get(1, 1), "h")

    def test_each_step_draws_on_the_layer_it_names(self):
        spec = {"width": 8, "height": 8, "layers": ["ink", "colour"], "steps": [
            {"op": "rect", "x0": 0, "y0": 0, "x1": 1, "y1": 1, "key": "k", "layer": "ink"},
            {"op": "rect", "x0": 4, "y0": 4, "x1": 5, "y1": 5, "key": "w", "layer": "colour"},
        ]}
        canvas = L.Layers(8, 8, spec["layers"])
        cli.apply_plan(canvas, cli.plan_steps(spec))
        self.assertEqual(canvas.layer("ink").get(0, 0), "k")
        self.assertEqual(canvas.layer("colour").get(0, 0), B.Canvas(1, 1).bg)
        composed = canvas.flatten()
        self.assertEqual(composed.get(0, 0), "k")
        self.assertEqual(composed.get(4, 4), "w")

    def test_the_order_is_the_declaration_order_and_the_top_wins(self):
        spec = {"width": 8, "height": 8, "layers": ["under", "over"], "steps": [
            {"op": "rect", "x0": 2, "y0": 2, "x1": 2, "y1": 2, "key": "h", "layer": "under"},
            {"op": "rect", "x0": 2, "y0": 2, "x1": 2, "y1": 2, "key": "w", "layer": "over"},
        ]}
        canvas = L.Layers(8, 8, spec["layers"])
        cli.apply_plan(canvas, cli.plan_steps(spec))
        self.assertEqual(canvas.flatten().get(2, 2), "w")

    def test_a_pass_that_drew_nothing_does_not_blank_the_one_under_it(self):
        spec = {"width": 8, "height": 8, "layers": ["body", "empty"], "steps": [
            {"op": "rect", "x0": 3, "y0": 3, "x1": 4, "y1": 4, "key": "h", "layer": "body"},
        ]}
        canvas = L.Layers(8, 8, spec["layers"])
        cli.apply_plan(canvas, cli.plan_steps(spec))
        self.assertEqual(canvas.flatten().get(3, 3), "h")

    def test_hiding_a_layer_omits_it_from_the_picture_and_keeps_it_in_the_file(self):
        canvas = L.Layers(8, 8, ["draft", "ink"])
        canvas.use("draft").put(1, 1, "h")
        canvas.use("ink").put(2, 2, "k")
        hidden = canvas.flatten(hide=("draft",))
        self.assertEqual(hidden.get(1, 1), B.Canvas(1, 1).bg)
        self.assertEqual(hidden.get(2, 2), "k")
        self.assertEqual(canvas.layer("draft").get(1, 1), "h", "hiding deleted the pass")

    def test_hiding_an_unknown_layer_is_refused_by_name(self):
        with self.assertRaises(ValueError) as ctx:
            L.Layers(8, 8, ["a"]).flatten(hide=("nope",))
        self.assertIn("nope", str(ctx.exception))


class TestHistoryIsPerLayer(unittest.TestCase):

    def test_undo_steps_back_the_layer_it_is_aimed_at(self):
        canvas = L.Layers(8, 8, ["a", "b"])
        canvas.use("a").put(1, 1, "h")
        canvas.use("b").put(2, 2, "k")
        canvas.use("b").undo()
        self.assertEqual(canvas.layer("b").get(2, 2), B.Canvas(1, 1).bg)
        self.assertEqual(canvas.layer("a").get(1, 1), "h", "undo on b removed a pixel from a")

    def test_the_stack_state_reports_every_layer(self):
        canvas = L.Layers(8, 8, ["a", "b"])
        canvas.use("a").put(1, 1, "h")
        before = canvas.state()
        canvas.use("b").put(2, 2, "k")
        self.assertNotEqual(canvas.state(), before)


class TestRefusals(unittest.TestCase):

    def test_an_unknown_layer_in_a_step_is_named(self):
        with self.assertRaises(cli.SpecError) as ctx:
            cli.plan_steps({"width": 8, "height": 8, "layers": ["a"],
                            "steps": [{"op": "rect", "x0": 0, "y0": 0, "x1": 0, "y1": 0,
                                       "key": "h", "layer": "typo"}]})
        self.assertIn("typo", str(ctx.exception))
        self.assertIn("a", str(ctx.exception))

    def test_a_duplicate_layer_name_is_refused(self):
        with self.assertRaises(cli.SpecError) as ctx:
            cli.plan_steps({"width": 8, "height": 8, "layers": ["a", "a"], "steps": []})
        self.assertIn("duplicate", str(ctx.exception))

    def test_layers_must_be_a_non_empty_list_of_names(self):
        for bad in ([], [""], ["a", 3], "a"):
            with self.subTest(layers=bad):
                with self.assertRaises(cli.SpecError):
                    cli.plan_steps({"width": 8, "height": 8, "layers": bad, "steps": []})

    def test_a_plain_canvas_refuses_a_step_that_names_a_layer(self):
        """The fast path must not silently ignore a layer it cannot honour."""
        spec = {"width": 8, "height": 8, "layers": ["a"], "steps": [
            {"op": "rect", "x0": 0, "y0": 0, "x1": 0, "y1": 0, "key": "h", "layer": "a"},
        ]}
        with self.assertRaises(cli.SpecError) as ctx:
            cli.apply_plan(B.Canvas(8, 8), cli.plan_steps(spec))
        self.assertIn("no layers", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
