# -*- coding: utf-8 -*-
"""Command line: measure a sprite, build one from a script, sample a palette, assemble frames.

Every subcommand prints what it measured and how, because a number without its method is a claim.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _fmt_report(r, name):
    lines = ["%s  %dx%d  %d opaque pixel(s)" % (name, r.width, r.height, r.opaque)]
    lines.append("  palette          %d colour(s)" % r.palette_size)
    # The parenthetical that used to be here was "(1 is normal for hand-authored art)", which is
    # true and misleading: 1 is also what an integer upscale reads once one pixel has been touched
    # up, and `pixel_scale` alone cannot tell the two apart. So report the factor the runs actually
    # support alongside it, and let `upscale == 0` carry the "nothing found" case explicitly.
    if r.upscale > 1:
        lines.append("  pixel scale      %d  (runs support a factor of %d, %.1f%% of them)"
                     % (r.pixel_scale, r.upscale, 100 * r.upscale_fraction))
    else:
        lines.append("  pixel scale      %d  (no integer factor found; 1 is normal for "
                     "hand-authored art)" % r.pixel_scale)
    lines.append("  isolated pixels  %d  (%.2f%%)" %
                 (r.isolated, 100 * r.isolated_rate))
    lines.append("  clusters         %d, largest %d (%.1f%%), median %s" %
                 (r.clusters, r.largest_cluster, 100 * r.largest_cluster_rate, r.median_cluster))
    lines.append("  outline variation %.3f over %d border pixel(s)  %s" %
                 (r.outline_variation, r.border_pixels,
                  "flat -- known-good sprites vary this with the local colour"
                  if r.outline_variation < 0.1 else ""))
    lines.append("  bounding box     %sx%s, %.0f%% full" % (r.bbox[0], r.bbox[1], 100 * r.bbox_fill))
    if r.dither_pixels:
        lines.append("  dither pixels    %d" % r.dither_pixels)
    for n in r.notes:
        lines.append("  note: %s" % n)
    return "\n".join(lines)


def cmd_judge(a):
    # `judge` is both a submodule and a function re-exported by the package, and the package name
    # wins -- so importing the submodule here silently binds the function instead. Import the
    # function directly and the ambiguity disappears.
    from .judge import judge

    rc = 0
    for p in a.paths:
        r = judge(p)
        print(_fmt_report(r, Path(p).name))
        print()
        if a.fail_on_note and r.notes:
            rc = 1
    return rc


def cmd_palette(a):
    from PIL import Image
    from . import palette as P

    im = Image.open(a.image)
    if a.crop:
        im = im.crop(tuple(int(v) for v in a.crop.split(",")))
    cols = P.sample(im, a.count, merge_distance=a.merge)
    print("%s  %dx%d" % (Path(a.image).name, im.width, im.height))
    print("  %d colour(s) after merging within %d per channel" % (len(cols), a.merge))
    for c in cols:
        print("    #%02X%02X%02X" % c)
    if a.saturate != 1.0:
        print("  raised to saturation x%.1f:" % a.saturate)
        for c in cols:
            print("    #%02X%02X%02X" % P.saturate(c, a.saturate))
    return 0


# Explicit per-op argument lists. An earlier version guessed the keys from the op name and got
# `cone` wrong, because a cone takes (y0, y1, w0, w1) while a rectangle takes (x0, y0, x1, y1) --
# a name-based guess cannot tell those apart, and the failure was a TypeError from deep inside.
SHAPE_ARGS = {
    "rect": ("x0", "y0", "x1", "y1"),
    "line": ("x0", "y0", "x1", "y1"),
    "disc": ("cx", "cy", "r"),
    "trap": ("y0", "y1", "w0", "w1"),
    "cone": ("y0", "y1", "w0", "w1"),
}


class SpecError(Exception):
    """A problem with the shape script itself, named by step."""


def plan_steps(spec):
    """Validate a shape script and return [(op, kwargs)] without drawing anything.

    Split out of `cmd_build` for two reasons, both from measurement. The test that covers a missing
    field used to spawn a real subprocess to read one error string, and on Windows that flakes
    (`OSError: [WinError 6]`) -- it failed roughly one run in three. And a validator that returns a
    value is testable directly, which a `SystemExit` raised mid-draw is not.

    Raises SpecError naming the step and the field, never a bare KeyError/IndexError: a traceback
    from inside `step[k]` tells the reader nothing about which step or which field was wrong.
    """
    if "width" not in spec or "height" not in spec:
        raise SpecError("spec: 'width' and 'height' are required")
    if not isinstance(spec.get("steps"), list):
        raise SpecError("spec: 'steps' must be a list")
    plan = []
    for i, step in enumerate(spec["steps"]):
        if not isinstance(step, dict):
            raise SpecError("step %d: not an object" % i)
        kind = step.get("op")
        if kind == "outline":
            if "key" not in step:
                raise SpecError("step %d (outline): missing key" % i)
            plan.append(("outline", dict(step)))
            continue
        if kind not in SHAPE_ARGS:
            raise SpecError("step %d: unknown op %r (known: %s, outline)"
                            % (i, kind, ", ".join(sorted(SHAPE_ARGS))))
        missing = [k for k in SHAPE_ARGS[kind] if k not in step]
        if missing:
            raise SpecError("step %d (%s): missing %s" % (i, kind, ", ".join(missing)))
        if "key" not in step:
            raise SpecError("step %d (%s): missing key" % (i, kind))
        plan.append((kind, dict(step)))
    return plan


def cmd_build(a):
    from . import builder as B

    spec = json.loads(Path(a.script).read_text(encoding="utf-8"))
    canvas = B.Canvas(spec["width"], spec["height"])
    for kind, step in plan_steps(spec):
        if kind == "outline":
            canvas.outline(step["key"], diagonal=step.get("diagonal", False))
            continue
        # `rect`/`line`/`disc`/`trap`/`cone` are the Canvas methods; `getattr` rather than a dict of
        # bound methods because the canvas is created per call and the names are already validated.
        args = [step[k] for k in SHAPE_ARGS[kind]]
        if kind in ("trap", "cone") and "cx" in step:
            args.append(step["cx"])
        args.append(step["key"])
        getattr(canvas, kind)(*args)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.to_image(spec["palette"]).save(out)
    print("wrote %s" % out)
    if a.preview:
        canvas.preview(scale=8, palette=spec["palette"]).convert("RGB").save(a.preview)
        print("wrote %s (x8, for looking at)" % a.preview)
    rows = canvas.rows()
    bad = [(i, len(r)) for i, r in enumerate(rows) if len(r) != canvas.width]
    if bad:
        raise SystemExit("ragged rows: %s" % bad)
    return 0


def cmd_frames(a):
    from PIL import Image
    from . import frames as F
    from .judge import judge

    ims = sorted(Path(a.directory).glob("*.png"))
    if not ims:
        raise SystemExit("no .png in %s" % a.directory)
    first = Image.open(ims[0])
    tl = F.Timeline(a.width or first.width, a.height or first.height)
    for i, p in enumerate(ims):
        tl.add(Image.open(p), duration_ms=a.duration)
    d = tl.drift()
    print("%d frame(s)  canvas %dx%d  anchor %s" % (len(ims), tl.width, tl.height, tl.anchor))
    print("  total %d ms" % tl.total_ms())
    print("  content drift relative to the anchor: %d x %d pixel(s)" % d)
    if a.out:
        tl.to_apng(a.out, scale=a.scale)
        print("wrote %s" % a.out)
    for p in ims[:1]:
        r = judge(p)
        print(_fmt_report(r, Path(p).name))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ichiwatashi", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    j = sub.add_parser("judge", help="measure a sprite against known-good samples")
    j.add_argument("paths", nargs="+")
    j.add_argument("--fail-on-note", action="store_true",
                   help="exit non-zero when any note was raised, for use in a check")
    j.set_defaults(func=cmd_judge)

    p = sub.add_parser("palette", help="sample colours from a reference")
    p.add_argument("image")
    p.add_argument("--count", type=int, default=20)
    p.add_argument("--merge", type=int, default=24,
                   help="merge colours within this many levels per channel; 0 measures the encoder")
    p.add_argument("--saturate", type=float, default=1.0)
    p.add_argument("--crop", help="x0,y0,x1,y1")
    p.set_defaults(func=cmd_palette)

    b = sub.add_parser("build", help="draw a sprite from a shape script")
    b.add_argument("script")
    b.add_argument("--out", required=True)
    b.add_argument("--preview", help="also write a nearest-neighbour x8 image here")
    b.set_defaults(func=cmd_build)

    f = sub.add_parser("frames", help="assemble frames and report drift")
    f.add_argument("directory")
    f.add_argument("--out", help="write an APNG here")
    f.add_argument("--width", type=int)
    f.add_argument("--height", type=int)
    f.add_argument("--duration", type=int, default=100)
    f.add_argument("--scale", type=int, default=1)
    f.set_defaults(func=cmd_frames)

    a = ap.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
