# -*- coding: utf-8 -*-
"""Turning a drawing into a pixel drawing: majority sampling, palette cut, and the rim between areas."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from PIL import Image

from ichiwatashi import pixelate as PX


def canvas(w, h, colour=(255, 255, 255, 255)):
    return Image.new("RGBA", (w, h), colour)


def blocks(image):
    """The set of colours, ignoring transparency, so a test can ask what survived."""
    return {p[:3] for p in image.getdata() if p[3]}


class TestSampling(unittest.TestCase):

    def test_a_majority_vote_does_not_invent_a_colour(self):
        """Averaging a black-and-white check produces greys that were never in the source."""
        im = canvas(8, 8)
        px = im.load()
        for y in range(8):
            for x in range(8):
                # Four-pixel-wide bars: every 2x2 block is one colour, so the vote is unambiguous. A
                # checkerboard would tie inside every block and the test would measure the tie-break.
                px[x, y] = (0, 0, 0, 255) if (x // 4) % 2 == 0 else (255, 255, 255, 255)
        small = PX.sample(im, width=4)
        self.assertEqual(len(blocks(small)), 2)
        self.assertTrue(all(c in {(0, 0, 0), (255, 255, 255)} for c in blocks(small)))

    def test_the_other_side_follows_the_aspect_ratio(self):
        small = PX.sample(canvas(800, 400), width=80)
        self.assertEqual(small.size, (80, 40))

    def test_asking_for_more_pixels_than_there_are_is_refused(self):
        with self.assertRaises(ValueError) as ctx:
            PX.sample(canvas(8, 8), width=16)
        self.assertIn("invent pixels", str(ctx.exception))

    def test_a_fractional_target_is_refused(self):
        with self.assertRaises(ValueError):
            PX.sample(canvas(8, 8), width=2.5)


class TestTheBackground(unittest.TestCase):

    def test_a_flat_border_becomes_transparent(self):
        im = canvas(40, 40)
        for y in range(10, 30):
            for x in range(10, 30):
                im.putpixel((x, y), (200, 30, 30, 255))
        out = PX.pixelate(im, width=20, colours=4)
        self.assertEqual(out.getpixel((0, 0))[3], 0, "the border should have become transparent")
        self.assertEqual(out.getpixel((10, 10))[3], 255, "the figure should still be opaque")

    def test_a_drawing_without_a_flat_ground_is_left_alone(self):
        """A border split three ways has no ground; guessing one would erase part of it."""
        im = canvas(40, 40, (10, 120, 40, 255))
        for y in range(40):
            for x in range(40):
                if 14 <= x < 27:
                    im.putpixel((x, y), (250, 220, 20, 255))
                elif x >= 27:
                    im.putpixel((x, y), (200, 30, 30, 255))
        self.assertIsNone(PX._ground(im))


class TestTheEdge(unittest.TestCase):

    def test_two_areas_get_a_rim_between_them_and_one_area_gets_none(self):
        im = canvas(40, 40, (0, 0, 0, 0))
        for y in range(40):
            for x in range(40):
                if 5 <= x < 20 and 5 <= y < 35:
                    im.putpixel((x, y), (240, 240, 240, 255))
                elif 20 <= x < 35 and 5 <= y < 35:
                    im.putpixel((x, y), (200, 40, 40, 255))
        out = PX.pixelate(im, width=40, colours=8, edges=True, background=None, denoise=0)
        white_rim = out.getpixel((19, 20))
        red_rim = out.getpixel((20, 20))
        self.assertLess(white_rim[0], 240, "the white area should have kept a darker rim")
        self.assertLess(red_rim[1], 40, "the red area should have kept a darker rim")
        self.assertNotEqual(white_rim[:3], (0, 0, 0), "the rim is the area's own colour darkened, not black")

    def test_one_area_alone_keeps_its_flat_fill(self):
        im = canvas(40, 40, (0, 0, 0, 0))
        for y in range(10, 30):
            for x in range(10, 30):
                im.putpixel((x, y), (240, 240, 240, 255))
        out = PX.pixelate(im, width=40, colours=8, edges=True, background=None, denoise=0)
        self.assertEqual(out.getpixel((20, 20))[:3], (240, 240, 240))

    def test_a_small_area_is_not_rimmed_away(self):
        """At 320 pixels wide an eye highlight is a few pixels; a rim would replace it entirely."""
        im = canvas(40, 40, (0, 0, 0, 0))
        for y in range(10, 30):
            for x in range(10, 30):
                im.putpixel((x, y), (240, 240, 240, 255))
        for y in range(20, 23):
            for x in range(20, 23):
                im.putpixel((x, y), (255, 255, 255, 255))
        out = PX.pixelate(im, width=40, colours=8, edges=True, background=None, denoise=0,
                          edge_min_area=24)
        self.assertEqual(out.getpixel((21, 21))[:3], (255, 255, 255))

    def test_near_colours_count_as_one_area(self):
        """Quantising a gradient leaves near-identical steps; each one must not become its own rim."""
        im = canvas(40, 20, (0, 0, 0, 0))
        for y in range(20):
            for x in range(40):
                shade = 240 - (x % 4) * 3          # four bands, three levels apart
                im.putpixel((x, y), (shade, shade, shade, 255))
        out = PX.pixelate(im, width=40, colours=16, edges=True, background=None, denoise=0,
                          edge_tolerance=24, edge_min_area=8)
        darkest = min(c[0] for c in blocks(out))
        self.assertGreaterEqual(darkest, 231,
                                "a rim appeared between near-identical bands: %r"
                                % (sorted(blocks(out)),))


class TestTheHeadBias(unittest.TestCase):
    """Giving the top of the drawing more rows than its proportion, so a face has pixels to live in."""

    def test_one_is_the_identity(self):
        im = canvas(40, 20, (10, 120, 40, 255))
        plain = PX.sample(im, width=20)
        same = PX.sample(im, width=20, head_bias=1.0)
        self.assertEqual(same.tobytes(), plain.tobytes())

    def test_above_one_reads_further_up_the_source_in_the_middle(self):
        """Half way down the output must come from above half way down the source: that is what stretches
        the head. A vertical gradient makes the difference a number instead of an impression."""
        im = canvas(20, 40)
        px = im.load()
        for y in range(40):
            for x in range(20):
                shade = 255 - y * 6
                px[x, y] = (shade, shade, shade, 255)
        plain = PX.sample(im, width=20, height=20, head_bias=1.0)
        biased = PX.sample(im, width=20, height=20, head_bias=1.3)
        self.assertGreater(biased.getpixel((0, 10))[0], plain.getpixel((0, 10))[0])

    def test_a_non_positive_bias_is_refused(self):
        with self.assertRaises(ValueError):
            PX.sample(canvas(10, 10), width=5, head_bias=0)


if __name__ == "__main__":
    unittest.main()
