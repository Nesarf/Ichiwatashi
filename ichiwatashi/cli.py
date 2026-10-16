# -*- coding: utf-8 -*-
"""Command line: measure a sprite, build one from a script, sample a palette, assemble frames.

Every subcommand prints what it measured and how, because a number without its method is a claim.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import calibration as C
from .judge import outline_style
from .scope import MIN_SHORT_SIDE as SCOPE_MIN


def _fmt_report(r, name):
    lines = ["%s  %dx%d  %d opaque pixel(s)" % (name, r.width, r.height, r.opaque)]
    lines.append("  colours used     %d distinct, among the drawn pixels" % r.colours_used)
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
    # **What the runs actually form, said separately from the factor.** The factor is one number and
    # the class is another, because the same rule that finds an upscale also fires on a flat mask and
    # on a solid block: 59 of 300 real sprites were flagged as upscaled and all 59 were one colour.
    # Printing the class next to the factor is what keeps a mask from being read as scaled art.
    if r.periodic_class != "none":
        lines.append("  periodicity      %s" % r.periodic_class)
    # And where the grid sits, when a factor was measured. A non-zero phase means the runs are
    # multiples of the factor but do not line up with the origin -- which is a crop, a real
    # condition the factor alone reports as a plain upscale.
    if r.upscale > 1 and r.phase_agree >= 0.5:
        if r.phase:
            lines.append("  grid offset      %d mod %d  (%.1f%% of the runs agree) -- a crop out of "
                         "a larger upscale" % (r.phase, r.upscale, 100 * r.phase_agree))
        else:
            lines.append("  grid offset      none  (%.1f%% of the runs start on multiples of %d)"
                         % (100 * r.phase_agree, r.upscale))
    lines.append("  isolated pixels  %d  (%.2f%%)" %
                 (r.isolated, 100 * r.isolated_rate))
    lines.append("  clusters         %d, largest %d (%.1f%%), median %s" %
                 (r.clusters, r.largest_cluster, 100 * r.largest_cluster_rate, r.median_cluster))
    # **The parenthetical that used to be here said a flat outline was the fault**, and it fired on
    # 161 of 161 real TH155 sprites. Measuring both generations with one pipeline: TH123 sits at
    # 0.726 and TH155 at 0.004, and both are correct work. So this names the style and prints the
    # evidence instead of grading it -- `outline_style` is a description, not a score.
    style = outline_style(r.outline_variation, r.outline_predictability, r.outline_colours)
    lines.append("  outline          %s: variation %.3f over %d border pixel(s), %d colour(s), "
                 "%.0f%% predictable from the fill"
                 % (style, r.outline_variation, r.border_pixels, r.outline_colours,
                    100 * r.outline_predictability))
    lines.append("  bounding box     %sx%s, %.0f%% full" % (r.bbox[0], r.bbox[1], 100 * r.bbox_fill))
    if r.dither_pixels:
        lines.append("  dither pixels    %d" % r.dither_pixels)
    for n in r.notes:
        lines.append("  note: %s" % n)
    return "\n".join(lines)


def cmd_judge(a):
    from .scope import OutOfScopeError

    # `judge` is both a submodule and a function re-exported by the package, and the package name
    # wins -- so importing the submodule here silently binds the function instead. Import the
    # function directly and the ambiguity disappears.
    from .judge import judge

    rc = 0
    for p in a.paths:
        try:
            r = judge(p, generation=a.generation, anyway=a.anyway)
        except OutOfScopeError as e:
            # Refused rather than measured. The exit code is 2 -- distinct from 1, which means "measured,
            # and a note was raised" -- because "I cannot measure this" and "I measured it and it looks
            # unlike the reference" are different answers and a caller has to be able to tell them apart.
            print("REFUSED: %s" % Path(p).name)
            # The message is multi-paragraph, so every line after the first gets the same indent. A
            # refusal the reader cannot parse is a refusal they will work around instead of reading.
            for line in str(e).splitlines():
                print("  " + line)
            print()
            rc = 2
            continue
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

#: Steps that change the history rather than the canvas. **These are what make a shape script editable
#: without re-running it**: the TODO entry's complaint was "改一个比例就要重跑整个脚本", and the answer is
#: that a script can step back over its own earlier steps and try something else in place, so the reader
#: sees both attempts in one run instead of two files.
HISTORY_OPS = ("undo", "redo")


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
        if kind in HISTORY_OPS:
            count = step.get("count", 1)
            if not isinstance(count, int) or count < 1:
                raise SpecError("step %d (%s): count must be a positive integer" % (i, kind))
            plan.append((kind, {"count": count}))
            continue
        if kind == "outline":
            if "key" not in step:
                raise SpecError("step %d (outline): missing key" % i)
            plan.append(("outline", dict(step)))
            continue
        if kind not in SHAPE_ARGS:
            raise SpecError("step %d: unknown op %r (known: %s, outline, %s)"
                            % (i, kind, ", ".join(sorted(SHAPE_ARGS)), ", ".join(HISTORY_OPS)))
        missing = [k for k in SHAPE_ARGS[kind] if k not in step]
        if missing:
            raise SpecError("step %d (%s): missing %s" % (i, kind, ", ".join(missing)))
        if "key" not in step:
            raise SpecError("step %d (%s): missing key" % (i, kind))
        plan.append((kind, dict(step)))
    return plan


def cmd_font(a):
    """Emit the shared bitmap font in a form another tool can embed.

    This is the family rule made operable: the source lives here and the consumer gets data in its own
    format, rather than each tool growing its own font. `volcano-separator` is the first consumer, and
    its table is what the source in `assets/` was checked against.
    """
    from .font import check_font, load_source, render_table, to_volcano_hex

    glyphs = load_source(a.source)
    if a.check:
        c = check_font(glyphs)
        print("%d glyph(s), all %dx%d" % (c["glyphs"], 5, 7))
        if c["missing"]:
            print("  not in this font: %s" % c["missing"])
        else:
            print("  covers the full window set (letters, digits, punctuation)")
        print("  space glyph: %s" % ("yes" if c["has_space"] else "NO"))
        if c["distinct_shapes"] != 1:
            print("  WARNING: %d distinct glyph shapes -- a variable-width font would need the "
                  "consumer's assumptions checked" % c["distinct_shapes"])
        return 0

    ordered = [glyphs[k] for k in sorted(glyphs)]
    if a.format == "powershell":
        # The consumer's own shape: a hashtable body it can paste, and the encoding its renderer reads.
        print(render_table(ordered, per_line=4))
    elif a.format == "hex":
        for k in sorted(glyphs):
            print("%s	%s" % (k, glyphs[k].hex()))
    elif a.format == "text":
        for k in sorted(glyphs):
            print("%r:" % k)
            print(glyphs[k])
    return 0


def cmd_build(a):
    from . import builder as B

    spec = json.loads(Path(a.script).read_text(encoding="utf-8"))
    canvas = B.Canvas(spec["width"], spec["height"])
    applied, undone, redone = 0, 0, 0
    for kind, step in plan_steps(spec):
        if kind in HISTORY_OPS:
            hits = sum(1 for _ in range(step["count"]) if getattr(canvas, kind)())
            if kind == "undo":
                undone += hits
            else:
                redone += hits
            continue
        applied += 1
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
    # **A refused undo is reported rather than passed over.** Stepping back further than the history goes
    # is a mistake in the script, and a run that printed the same thing either way would let a reader
    # believe an edit had been rolled back when the canvas never moved.
    if undone or redone:
        print("history: %d step(s) applied, %d undone, %d redone -> %s"
              % (applied, undone, redone, ", ".join(canvas.history()[-4:])))
        wanted = sum(st["count"] for k, st in plan_steps(spec) if k == "undo")
        if undone < wanted:
            print("  NOTE: %d of %d undo step(s) did nothing -- the history is shorter than the script "
                  "assumes" % (wanted - undone, wanted))
    rows = canvas.rows()
    bad = [(i, len(r)) for i, r in enumerate(rows) if len(r) != canvas.width]
    if bad:
        raise SystemExit("ragged rows: %s" % bad)
    return 0


def cmd_frames(a):
    from PIL import Image
    from . import frames as F
    from .judge import judge
    from .scope import MIN_FRAMES_FOR_SPREAD, OutOfScopeError

    ims = sorted(Path(a.directory).glob("*.png"))
    if not ims:
        raise SystemExit("no .png in %s" % a.directory)
    # A spread over two frames is a statement about two numbers. Refused for the same reason a 7px
    # glyph is: the number would be printed and would mean something other than what it looks like.
    if len(ims) < MIN_FRAMES_FOR_SPREAD and not a.anyway:
        print("REFUSED: %d frame(s). A drift spread needs at least %d to say anything about motion; "
              "below that it is the difference between two drawings.\n"
              "Pass --anyway to see it anyway, as an uncalibrated number."
              % (len(ims), MIN_FRAMES_FOR_SPREAD))
        return 2
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


def cmd_figures(a):
    """Draw the report figures for one sprite.

    **Every figure is drawn with this repository's own tools** -- `builder`'s shapes and `font`'s glyphs,
    never a plotting library. The family rule is that this project's assets are pixel art, and for a
    measuring tool that has a second edge the TODO entry spells out: if a figure cannot be drawn with the
    tool's own verbs, the tool has a gap, and importing a drawing library would hide it.

    The output path is one way only: a canvas at one pixel per pixel, then an integer `NEAREST` upscale.
    A figure that had been resampled would be lying about the pixels it shows.
    """
    from PIL import Image
    from . import figures as FIG
    from . import palette as P
    from .judge import judge

    src = Image.open(a.image).convert("RGBA")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    board = P.sample(src, n=a.colours)
    r = judge(src)

    written = []
    for name, (canvas, keys), scale in (
        ("palette", FIG.palette_board(board, title="PALETTE %d" % len(board)), a.scale),
        ("silhouette", FIG.silhouette_map(src, title="SILHOUETTE"), max(2, a.scale // 3)),
        ("outline", FIG.outline_study(src, title="OUTLINE"), max(2, a.scale // 3)),
    ):
        p = out / ("%s.png" % name)
        FIG.render(canvas, keys, scale).convert("RGB").save(p)
        written.append(p)
    # a distribution figure only means something with more than one sample, so it is drawn from the
    # sprite's own metrics against the shipped bands rather than faked from a single row
    labels = ["colour", "isolated", "fill"]
    values = [float(r.colours_used), r.isolated_rate, r.bbox_fill]
    spans = ((9.0, 60.0), (0.0236, 0.1816), (0.284, 0.775))
    refs = (26.0, 0.116, 0.538)
    canvas, keys = FIG.distribution_bars(labels, values, title="THIS SPRITE", span=spans, reference=refs)
    p = out / "distribution.png"
    FIG.render(canvas, keys, max(3, a.scale // 2)).convert("RGB").save(p)
    written.append(p)
    for p in written:
        im = Image.open(p)
        print("wrote %s  %d x %d" % (p, im.width, im.height))
    return 0


def cmd_ungrid(a):
    """Read a grid JSON back, render it, and offer it as a shape script again.

    **This closes the loop the TODO entry named**: export a grid, edit it by hand, read it back. Two
    outputs, because the two are useful for different things -- the PNG is the picture the hand edits
    produced, and the `--emit-script` output is the same grid as a shape script the parametric path can
    keep working from. Without this a hand-edited grid could only be looked at, never built on.
    """
    from . import builder as B

    spec = json.loads(Path(a.grid).read_text(encoding="utf-8"))
    try:
        canvas, palette = B.from_grid(spec)
    except ValueError as e:
        # named rather than traced: the refusal already says which row or which character, and a
        # traceback from inside `from_rows` would bury that under three frames of this function
        raise SystemExit("REFUSED: %s" % e)
    print("%s  %dx%d  %d key(s): %s"
          % (Path(a.grid).name, canvas.width, canvas.height, len(palette),
             ", ".join(sorted(repr(k) for k in palette))))
    if a.out:
        out = Path(a.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        canvas.to_image(palette).save(out)
        print("wrote %s" % out)
    if a.preview:
        canvas.preview(scale=a.scale, palette=palette).convert("RGB").save(a.preview)
        print("wrote %s (x%d)" % (a.preview, a.scale))
    if a.emit_script:
        rows = canvas.rows()
        script = {"width": canvas.width, "height": canvas.height,
                  "bg": canvas.bg, "palette": spec.get("palette") or {}, "pixels": rows,
                  "note": "emitted by `ichiwatashi ungrid --emit-script`; the pixels are literal, so "
                          "this is a grid the build path can carry rather than a shape description"}
        Path(a.emit_script).write_text(json.dumps(script, indent=2), encoding="utf-8")
        print("wrote %s" % a.emit_script)
    return 0


def cmd_grid(a):
    """Write a canvas out as `{width, height, bg, palette, pixels}` for hand editing.

    The other half of `ungrid`. Until both halves existed a grid could only be produced, never read, so a
    file that had been corrected by hand could not come back.
    """
    from . import builder as B

    spec = json.loads(Path(a.script).read_text(encoding="utf-8"))
    canvas = B.Canvas(spec["width"], spec["height"], spec.get("bg", "."))
    for kind, step in plan_steps(spec):
        if kind in HISTORY_OPS:
            for _ in range(step["count"]):
                getattr(canvas, kind)()
            continue
        if kind == "outline":
            canvas.outline(step["key"], diagonal=step.get("diagonal", False))
            continue
        args = [step[k] for k in SHAPE_ARGS[kind]]
        if kind in ("trap", "cone") and "cx" in step:
            args.append(step["cx"])
        args.append(step["key"])
        getattr(canvas, kind)(*args)
    grid = canvas.to_grid(spec.get("palette") or {})
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(grid, indent=2), encoding="utf-8")
    print("wrote %s  %dx%d  %d key(s)" % (out, canvas.width, canvas.height, len(grid["palette"])))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ichiwatashi", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    j = sub.add_parser("judge", help="measure a sprite against known-good samples")
    j.add_argument("paths", nargs="+")
    j.add_argument("--fail-on-note", action="store_true",
                   help="exit non-zero when any note was raised, for use in a check")
    j.add_argument("--anyway", action="store_true",
                   help="measure something the reference has no subject for, and treat the numbers as "
                        "uncalibrated. Without this, an input below %d px on its short side is refused: "
                        "the metrics do not degrade gracefully there, they measure a property the input "
                        "does not have. A 5x7 font glyph is 7 px and all 58 of its glyphs come back "
                        "flagged, which reads as a finding and is not one." % SCOPE_MIN)
    j.add_argument("--generation", choices=C.GENERATIONS, default=None,
                   help="which reference table applies. The two generations sit far apart -- "
                        "TH123 at 26 colours and TH155 at 43 -- so judging one with the "
                        "other's thresholds flags correct work (measured: 80 of 160 TH155 sprites "
                        "against 8 with the right table). Defaults to %s." % C.DEFAULT_GENERATION)
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

    g = sub.add_parser("grid", help="write a shape script's canvas as an editable grid JSON")
    g.add_argument("script")
    g.add_argument("--out", required=True, help="where to write the {width, height, bg, palette, pixels}")
    g.set_defaults(func=cmd_grid)

    ug = sub.add_parser("ungrid", help="read a grid JSON back, render it, and re-emit it")
    ug.add_argument("grid")
    ug.add_argument("--out", help="write the rendered PNG here")
    ug.add_argument("--preview", help="also write a nearest-neighbour enlargement here")
    ug.add_argument("--scale", type=int, default=8)
    ug.add_argument("--emit-script", help="write the grid back out as a script the build path accepts")
    ug.set_defaults(func=cmd_ungrid)

    ft = sub.add_parser("font", help="emit the shared 5x7 bitmap font for another tool to embed")
    ft.add_argument("--source", default=str(Path(__file__).resolve().parents[1] / "assets" / "font5x7.txt"),
                    help="the font source; defaults to this repository's own copy")
    ft.add_argument("--format", choices=("powershell", "hex", "text"), default="powershell",
                    help="powershell: the hashtable body volcano-separator reads. hex: char<TAB>hex. "
                         "text: each glyph drawn as # and . so it can be read or diffed.")
    ft.add_argument("--check", action="store_true",
                    help="report what the font can and cannot say, instead of emitting it")
    ft.set_defaults(func=cmd_font)

    f = sub.add_parser("frames", help="assemble frames and report drift")
    f.add_argument("directory")
    f.add_argument("--out", help="write an APNG here")
    f.add_argument("--width", type=int)
    f.add_argument("--height", type=int)
    f.add_argument("--duration", type=int, default=100)
    f.add_argument("--scale", type=int, default=1)
    f.add_argument("--anyway", action="store_true",
                   help="report a drift spread from fewer frames than the measurement needs, as an "
                        "uncalibrated number")
    f.set_defaults(func=cmd_frames)

    fg = sub.add_parser("figures", help="draw the report figures for a sprite, in pixel art")
    fg.add_argument("image")
    fg.add_argument("--out", default="figures", help="directory for the PNGs (default: ./figures)")
    fg.add_argument("--scale", type=int, default=6,
                    help="integer upscale; the figures are drawn at 1 pixel per pixel and enlarged with "
                         "NEAREST, so this cannot resample")
    fg.add_argument("--colours", type=int, default=16, help="how many palette swatches to draw")
    fg.set_defaults(func=cmd_figures)

    a = ap.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
