# -*- coding: utf-8 -*-
"""Ichiwatashi (一渡始) -- deterministic pixel-art measurement and parametric construction.

Four parts, and they exist in this order for a reason:

    judge     measure a sprite from its pixels alone; no model, no drift, explainable
    builder   describe a silhouette with shapes, then outline it automatically
    palette   sample a reference for hue, keep material and identity boards apart
    frames    canvases, pivots and timing -- the three things that decide whether motion reads

**Why measurement comes first.** A generate-judge-refine loop needs a judge before it needs a
generator, and pointing the first version of this judge at a sprite known to be good immediately
falsified two of its own assumptions -- isolated pixels had to be counted as a rate rather than a
total, and "the outline is one consistent colour" turned out to describe beginner work rather than
discipline. **Both would have been trained into a model as ground truth.**
"""
from .judge import Report, judge
from .builder import Canvas, from_rows
from . import keys as K
from . import panel as Pn
from . import terminal as T
from . import portable as Pt
from . import window as W
from .frames import Frame, Timeline, GifWouldLose, even_durations, with_hold, read_delays
from .palette import sample, saturate, separation, best_accents

__version__ = "0.2.0"

__all__ = ["Report", "judge", "Canvas", "from_rows", "Frame", "Timeline", "GifWouldLose", "read_delays",
           "even_durations", "with_hold", "sample", "saturate", "separation",
           "best_accents", "__version__"]
