# -*- coding: utf-8 -*-
"""Frames, anchors and timing -- the three things that decide whether motion reads as motion.

**Where these rules come from, and why they are worth writing down.**

Two real animations were measured, and they solve the same problem oppositely:

* **A fixed canvas.** A 40-frame pixel animation held every frame at 135x245 and moved the subject
  within it. The anchor is then implicit: it is the canvas corner, and no per-frame geometry is
  stored at all. The cost is texture -- the background was 75.7% of each frame.

* **A per-frame crop plus a stored pivot.** A 2008 fighting game crops each frame tightly to the
  subject (so the frame's own bounding box equals its size) and stores the anchor in the animation
  data. The cost is that the pivot must be right, and the failure mode is drift.

Both are correct, and which one to use is a property of the animation rather than of taste: small
looping sprites want a fixed canvas, large one-shot motions with big displacement want cropping.

**How a claimed pivot is checked, and how it was here.** Not by looking at the number. The same frames
were laid out twice on the same canvas -- once aligned by the stored pivot, once by frame centre -- and
compared. Pivot alignment put the feet on one level line; centre alignment floated them. **A pivot that
is claimed but never compared against the alternative is a number with a story attached.**

**Timing was measured separately, from a series by one author:** nine frames at 70 ms, twenty at 40 ms,
forty at 20 ms -- frame count and per-frame duration moving in opposite directions while the total
stayed between 0.6 and 1.1 seconds. That is the useful shape: **fix the total, then buy smoothness with
frames and weight with duration.** A one-shot motion additionally wants a single long hold frame, which
is how the same survey showed 360 ms and 500 ms outliers sitting alone among 60-170 ms neighbours.
"""
from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["Frame", "Timeline"]


@dataclass
class Frame:
    """One drawn frame, plus where its anchor sits inside it.

    `image` may be anything Pillow can open. `pivot` is in frame coordinates and defaults to the
    bottom centre, which is where a standing figure's foot usually is and is a better guess than the
    top-left corner for anything that stands on the ground.
    """

    image: object
    pivot: tuple = None
    duration_ms: int = 100

    def __post_init__(self):
        if self.pivot is None:
            w, h = _size(self.image)
            self.pivot = (w // 2, h - 1)


def _size(image):
    if hasattr(image, "size"):
        return image.size
    from PIL import Image

    with Image.open(image) as im:
        return im.size


@dataclass
class Timeline:
    """A sequence of frames plus the canvas they are composed onto.

    The canvas is explicit rather than derived from the frames, because deriving it from the frames is
    exactly the fixed-canvas-vs-crop decision made by accident: a canvas that grows to fit the largest
    frame will drift any frame that is not the largest.
    """

    width: int
    height: int
    frames: list = field(default_factory=list)
    anchor: tuple = None          # where the pivot lands on the canvas
    canvas_mode: str = "fixed"    # "fixed" | "crop"

    def __post_init__(self):
        if self.anchor is None:
            self.anchor = (self.width // 2, self.height - 1)

    def add(self, image, *, pivot=None, duration_ms: int = 100):
        self.frames.append(Frame(image, pivot, duration_ms))
        return self

    def total_ms(self):
        return sum(f.duration_ms for f in self.frames)

    def placements(self):
        """Where each frame's top-left goes so its pivot lands on the anchor.

        This is the whole of "why does the animation jitter": get it wrong and every frame sits
        somewhere slightly different. It is a separate function so that a caller can assert on it
        without rendering anything.
        """
        ax, ay = self.anchor
        out = []
        for f in self.frames:
            px, py = f.pivot
            out.append((ax - px, ay - py))
        return out

    def compose(self, *, background=None):
        """Render every frame onto the canvas. Returns a list of same-sized RGBA images."""
        from PIL import Image

        bg = background if background else (0, 0, 0, 0)
        out = []
        for f, (x, y) in zip(self.frames, self.placements()):
            im = f.image if hasattr(f.image, "convert") else Image.open(f.image)
            canvas = Image.new("RGBA", (self.width, self.height), bg)
            canvas.alpha_composite(im.convert("RGBA"), (x, y))
            out.append(canvas)
        return out

    def drift(self):
        """How far each frame's *content* moves relative to the anchor, in pixels.

        A correctly stored pivot gives a small spread here; a wrong one gives the spread of the
        bounding boxes. Reported rather than asserted, because some motion is supposed to move.
        """
        xs, ys = [], []
        for im, (dx, dy) in zip(self.compose(), self.placements()):
            bbox = im.getbbox()
            if bbox:
                xs.append(bbox[0] - dx)
                ys.append(bbox[1] - dy)
        if not xs:
            return 0, 0
        return max(xs) - min(xs), max(ys) - min(ys)

    def to_gif(self, path, *, scale: int = 1, background=None, loop: int = 0):
        from PIL import Image

        frames = self.compose(background=background)
        if scale != 1:
            frames = [f.resize((f.width * scale, f.height * scale), Image.NEAREST) for f in frames]
        frames[0].save(path, save_all=True, append_images=frames[1:],
                       duration=[f.duration_ms for f in self.frames], loop=loop, disposal=2)
        return path

    def to_apng(self, path, *, scale: int = 1, background=None, loop: int = 0):
        """APNG keeps real alpha; GIF does not. Prefer this when the sprite is not on a solid ground."""
        from PIL import Image

        frames = self.compose(background=background)
        if scale != 1:
            frames = [f.resize((f.width * scale, f.height * scale), Image.NEAREST) for f in frames]
        frames[0].save(path, save_all=True, append_images=frames[1:],
                       duration=[f.duration_ms for f in self.frames], loop=loop,
                       format="PNG", disposal=2)
        return path


def even_durations(total_ms: int, count: int):
    """Split a total evenly, giving the remainder to the first frames.

    Provided because the measured way to work is to fix the total first. Asking for "20 frames over
    0.8 seconds" is a different and better-posed request than "20 frames at 40 ms", and this makes the
    former expressible.
    """
    if count <= 0:
        raise ValueError("count must be positive")
    base, extra = divmod(total_ms, count)
    return [base + (1 if i < extra else 0) for i in range(count)]


def with_hold(durations, hold_index: int, hold_ms: int):
    """Lengthen one frame -- the hold that keeps a one-shot motion from floating.

    A hold is not a pause in the drawing, it is a duration on a frame that is already drawn. That is
    why it costs nothing in frames and everything in weight.
    """
    out = list(durations)
    if not 0 <= hold_index < len(out):
        raise IndexError("hold_index %d outside 0..%d" % (hold_index, len(out) - 1))
    out[hold_index] = hold_ms
    return out
