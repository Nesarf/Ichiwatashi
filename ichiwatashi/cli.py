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

#: The font source that ships with the package. One definition, resolved from this module, because
#: `figures.FONT_PATH` used to be a bare relative string and broke whenever the cwd was not the repo.
FONT_SOURCE = Path(__file__).resolve().parent / "assets" / "font5x7.txt"

#: The panel size tiers, read from the panel module so --tier validates against what exists.
from . import panel as _panel
PANEL_TIERS = tuple(sorted(_panel.TIERS))
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


def cmd_profile(a):
    """Where a sprite sits between the measured generations.

    **It runs `judge` first and reads its numbers.** A position computed from a second measurement of
    the same image would be a second answer to "what does this measure", and the two could disagree
    without anything noticing. What this adds is the placement; the numbers stay the judge's.
    """
    from .scope import OutOfScopeError
    from .judge import judge
    from . import profile as PR

    rc = 0
    for p in a.paths:
        try:
            r = judge(p, generation=a.generation, anyway=a.anyway)
        except OutOfScopeError as e:
            print("REFUSED: %s" % Path(p).name)
            for line in str(e).splitlines():
                print("  " + line)
            print()
            rc = 2
            continue
        result = PR.nearest(r, generations=(a.generation,) if a.generation else None)
        print(PR.describe(result, "%s  %dx%d  opaque %d" % (Path(p).name, r.width, r.height, r.opaque)))
        print()
    return rc


def cmd_palette(a):
    from PIL import Image
    from . import palette as P

    im = Image.open(a.image)
    if a.crop:
        im = im.crop(tuple(int(v) for v in a.crop.split(",")))
    cols = P.sample(im, a.count, merge_distance=a.merge)
    by_role = P.roles(im, cols)
    print("%s  %dx%d" % (Path(a.image).name, im.width, im.height))
    # **Three numbers, because one of them was being read as another.** `--count 8` on a 16-colour sprite
    # printed "4 colour(s) after merging within 24", which reads as "this image has 4 colours" when it has
    # 16 -- and the reader cannot tell whether `--count` or `--merge` produced the shortfall. Measured on a
    # real sprite: 16 distinct colours, grouped to 4 by the threshold of 24, with `--count 8` never reached.
    # Both parameters are honest; only saying which one bound the result makes it readable.
    # **Opaque pixels only.** The first version converted to RGB, which folds the transparent ground's
    # colour into the count: a 207x179 sheet with a clear background reported one colour more than it draws
    # with, and that one is not a colour of the artwork. `sample()` also works in RGB, so the two numbers
    # stay comparable; what changes is that the count does not include a region nobody drew.
    raw = im.convert("RGBA").getcolors(maxcolors=1 << 24)
    # `getcolors()` yields `(count, colour)`, not `(colour, count)` -- unpacking it the other way round
    # is what made the first version of this line fail with `TypeError: int is not subscriptable`
    n_distinct = len({c for _n, c in (raw or []) if c[3] > 0})
    if n_distinct and n_distinct != len(cols):
        print("  %d distinct colour(s) in the drawing" % n_distinct)
    # **Four cases, because "fewer than --count" has three different causes.** Measured on one sprite:
    # `--count 8` gave 4 (the threshold of 24 merged 18 colours into 4 groups), and `--count 40 --merge 4`
    # gave 18 -- which a two-way test reported as "the threshold limited this", sending the reader to lower
    # `--merge` when the drawing simply has 18 colours. Naming the wrong cause is worse than naming none.
    if len(cols) == n_distinct:
        # the drawing itself is the limit; neither parameter reduced anything
        print("  all %d colour(s) this drawing uses (--count %d allows more; merging within %d reduced none)"
              % (len(cols), a.count, a.merge))
    elif len(cols) < a.count:
        print("  merged to %d within %d per channel -- the threshold is what limited this, not --count %d"
              % (len(cols), a.merge, a.count))
        print("    lower --merge to see more; 0 measures the encoder rather than the art")
    else:
        # **No attribution here, deliberately.** `--count 4 --merge 24` returns 4 colours on this sprite
        # because the threshold also produced 4 groups -- so "merging did not limit this" would be false
        # whenever the two happen to coincide, and that is exactly when a reader would most want the truth.
        # The cap is `--count`; whether merging would have given more is not stated because it is not known.
        print("  %d colour(s) -- the first %d of the merged set, capped by --count"
              % (len(cols), a.count))
    # **The role is printed beside each colour, because it answers a question the hex does not.** A reader
    # looking at sixteen hex values cannot tell which one is the outline; `roles` can, and it is judged by
    # the relation (how often a colour is on the outline side of a fill/outline pair) rather than by
    # position. See its docstring for why the positional criterion failed on 16 of 20 sprites.
    for c in cols:
        role = by_role.get(tuple(c[:3]), "-")
        print("    #%02X%02X%02X  %s" % (c[0], c[1], c[2], role))
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


def _with_layer(layer, body):
    """Attach the current layer to a plan entry, when the script declares layers at all."""
    if layer is None:
        return body
    body = dict(body)
    body["layer"] = layer
    return body


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
    # **Layers are declared once and named per step.** Declared rather than inferred from the steps, so a
    # typo is an error at the top of the file instead of a silently new pass at the bottom.
    # **`layers` present but empty is an error, not a fallback.** A script that declares no passes and one
    # that declares an empty list are different intentions, and only one of them is a mistake.
    names = spec["layers"] if "layers" in spec else ["base"]
    if not isinstance(names, list) or not names or any(not isinstance(n, str) or not n for n in names):
        raise SpecError("spec: 'layers' must be a non-empty list of names")
    if len(set(names)) != len(names):
        raise SpecError("spec: 'layers' declares a duplicate name")
    plan = []
    for i, step in enumerate(spec["steps"]):
        if not isinstance(step, dict):
            raise SpecError("step %d: not an object" % i)
        kind = step.get("op")
        layer = step.get("layer")
        if layer is not None and layer not in names:
            raise SpecError("step %d: unknown layer %r (declared: %s)"
                            % (i, layer, ", ".join(names)))
        if kind in HISTORY_OPS:
            count = step.get("count", 1)
            if not isinstance(count, int) or count < 1:
                raise SpecError("step %d (%s): count must be a positive integer" % (i, kind))
            plan.append((kind, _with_layer(layer, {"count": count})))
            continue
        if kind == "outline":
            if "key" not in step:
                raise SpecError("step %d (outline): missing key" % i)
            plan.append(("outline", _with_layer(layer, dict(step))))
            continue
        if kind == "mirror":
            # `axis` is a column index and has to be an integer: a fractional axis would put the mirror
            # line between pixels, and the two sides would then differ by a subpixel nobody can see.
            axis = step.get("axis")
            if not isinstance(axis, int) or isinstance(axis, bool):
                raise SpecError("step %d (mirror): 'axis' must be an integer column" % i)
            direction = step.get("direction", "left")
            if direction not in ("left", "right", "both"):
                raise SpecError("step %d (mirror): 'direction' must be left, right or both" % i)
            plan.append(("mirror", _with_layer(layer, {"axis": axis, "direction": direction})))
            continue
        if kind == "part":
            # A part is another shape script, placed whole. `file` is resolved against the script that
            # names it, so a library of parts travels with the drawing that uses them.
            for field in ("file", "x", "y"):
                if field not in step:
                    raise SpecError("step %d (part): missing %s" % (i, field))
            flip = step.get("flip", False)
            if not isinstance(flip, bool):
                raise SpecError("step %d (part): 'flip' must be true or false" % i)
            plan.append(("part", _with_layer(layer, {"file": step["file"], "x": step["x"], "y": step["y"], "flip": flip})))
            continue
        if kind in ("copy", "flip"):
            # Region verbs. The rectangle is inclusive on both corners, the same convention every shape
            # in this file uses, so a block read with `crop` writes back at the same numbers.
            for field in ("x0", "y0", "x1", "y1"):
                if field not in step:
                    raise SpecError("step %d (%s): missing %s" % (i, kind, field))
            if step["x1"] < step["x0"] or step["y1"] < step["y0"]:
                raise SpecError("step %d (%s): give x1 >= x0 and y1 >= y0" % (i, kind))
            if kind == "copy":
                for field in ("dx", "dy"):
                    if field not in step:
                        raise SpecError("step %d (copy): missing %s" % (i, field))
                flip = step.get("flip", False)
                if not isinstance(flip, bool):
                    raise SpecError("step %d (copy): 'flip' must be true or false" % i)
                plan.append(("copy", _with_layer(layer, {
                    "x0": step["x0"], "y0": step["y0"], "x1": step["x1"], "y1": step["y1"],
                    "dx": step["dx"], "dy": step["dy"], "flip": flip})))
                continue
            axis = step.get("axis", "x")
            if axis not in ("x", "y"):
                raise SpecError("step %d (flip): 'axis' must be x or y" % i)
            plan.append(("flip", _with_layer(layer, {
                "x0": step["x0"], "y0": step["y0"], "x1": step["x1"], "y1": step["y1"], "axis": axis})))
            continue
        if kind in ("mask", "unmask"):
            if kind == "unmask":
                plan.append(("unmask", _with_layer(layer, {})))
                continue
            for field in ("x0", "y0", "x1", "y1"):
                if field not in step:
                    raise SpecError("step %d (mask): missing %s" % (i, field))
            if step["x1"] < step["x0"] or step["y1"] < step["y0"]:
                raise SpecError("step %d (mask): give x1 >= x0 and y1 >= y0" % i)
            plan.append(("mask", _with_layer(layer, {
                "x0": step["x0"], "y0": step["y0"], "x1": step["x1"], "y1": step["y1"]})))
            continue
        if kind not in SHAPE_ARGS:
            raise SpecError("step %d: unknown op %r (known: %s, outline, %s)"
                            % (i, kind, ", ".join(sorted(SHAPE_ARGS)), ", ".join(HISTORY_OPS)))
        missing = [k for k in SHAPE_ARGS[kind] if k not in step]
        if missing:
            raise SpecError("step %d (%s): missing %s" % (i, kind, ", ".join(missing)))
        if "key" not in step:
            raise SpecError("step %d (%s): missing key" % (i, kind))
        plan.append((kind, _with_layer(layer, dict(step))))
    return plan


def apply_plan(canvas, plan, *, base_dir=None, _depth=0):
    """Draw a validated plan onto a canvas. Returns `(applied, undone, redone)`.

    **One implementation, two callers.** `build` draws the script onto a canvas and `grid` draws the same
    script onto one to export an editable grid; the two had the same loop written twice, and adding an op
    to one of them would have left the other rejecting a script it had just accepted (the validator is
    shared, the loop was not).

    `base_dir` is what a `part` step's relative `file` resolves against -- the directory of the script
    that names it, so a folder of parts and the drawing that uses them move together.
    """
    from . import builder as B

    applied = undone = redone = 0
    for kind, step in plan:
        if kind in HISTORY_OPS:
            hits = sum(1 for _ in range(step["count"]) if getattr(canvas, kind)())
            if kind == "undo":
                undone += hits
            else:
                redone += hits
            continue
        applied += 1
        wanted = step.get("layer")
        if wanted is not None:
            use = getattr(canvas, "use", None)
            if use is None:
                raise SpecError("step names layer %r but this canvas has no layers" % wanted)
            use(wanted)
        if kind == "outline":
            canvas.outline(step["key"], diagonal=step.get("diagonal", False))
            continue
        if kind == "mirror":
            canvas.mirror(step["axis"], direction=step["direction"])
            continue
        if kind == "part":
            path = Path(step["file"])
            if not path.is_absolute():
                if base_dir is None:
                    raise SpecError("part %r is relative and no base directory was given"
                                    % step["file"])
                path = Path(base_dir) / path
            # **One level, and the refusal is the design.** A part that places a part is a graph, a graph
            # can be cyclic, and the thing this exists for -- one body with several expressions -- is one
            # level deep. Refusing is a smaller promise than a resolver with a cycle detector, and this
            # project's rule is to make the smaller promise.
            if _depth >= 1:
                raise SpecError("part %s: a part may not place another part" % path.name)
            if not path.is_file():
                raise SpecError("part %s: no such file" % path)
            sub = json.loads(path.read_text(encoding="utf-8"))
            part = B.Canvas(sub["width"], sub["height"], sub.get("bg", "."))
            apply_plan(part, plan_steps(sub), base_dir=path.parent, _depth=_depth + 1)
            canvas.blit(part, step["x"], step["y"], flip=step["flip"])
            continue
        # **Keyword arguments, because the two call shapes disagree about where `cx` goes.**
        # `trap(y0, y1, w0, w1, key, cx=None)` and `cone` put `key` before `cx`, while `rect` has no `cx`
        # at all -- the version this replaces appended `cx` before `key`, so a script that *did* pass `cx`
        # bound that number to `key` and then `_taper` divided a string by two. No script in the suite
        # used `cx` until the mirrored demo did, which is how a latent defect survives a green suite.
        if kind == "copy":
            block = canvas.crop(step["x0"], step["y0"], step["x1"], step["y1"])
            # `blit`, so the copied block's empty pixels do not stamp out what they land on: a copy is an
            # addition, and the pixels it did not draw are not its business.
            canvas.blit(block, step["x0"] + step["dx"], step["y0"] + step["dy"], flip=step["flip"])
            continue
        if kind == "flip":
            # `flip` stamps including the background, because the empties inside the rectangle moved too.
            canvas.flip(step["x0"], step["y0"], step["x1"], step["y1"], axis=step["axis"])
            continue
        if kind == "mask":
            canvas.mask(step["x0"], step["y0"], step["x1"], step["y1"])
            continue
        if kind == "unmask":
            canvas.unmask()
            continue
        kwargs = {k: step[k] for k in SHAPE_ARGS[kind]}
        kwargs["key"] = step["key"]
        if kind in ("trap", "cone") and "cx" in step:
            kwargs["cx"] = step["cx"]
        getattr(canvas, kind)(**kwargs)
    return applied, undone, redone


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
    elif a.format == "json":
        # **A form another language can read without parsing a PowerShell literal.** The keys are the
        # characters and the values are 14 hex digits, which is the same encoding the table has always used.
        import json as _json

        body = {"format": "ichiwatashi.font/1",
                "glyph_w": 5, "glyph_h": 7,
                "glyphs": {k: "".join("%02X" % r for r in glyphs[k].rows) for k in sorted(glyphs)}}
        body["checksum"] = __import__("hashlib").sha256(
            _json.dumps({k: v for k, v in body.items() if k != "checksum"},
                        sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        print(_json.dumps(body, ensure_ascii=False, indent=1, sort_keys=True))
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
    from . import layers as L

    spec = json.loads(Path(a.script).read_text(encoding="utf-8"))
    plan = plan_steps(spec)
    canvas = L.Layers(spec["width"], spec["height"], spec.get("layers"))
    applied, undone, redone = apply_plan(canvas, plan, base_dir=Path(a.script).parent)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    # **`--hide` composes without a pass rather than deleting it.** The pass stays in the script and in the
    # grid; what changes is the picture. That is the reason to have layers at all: the draft is the one a
    # caller wants to keep in the file and out of the render.
    hidden = tuple(a.hide or ())
    composed = canvas.flatten(hide=hidden)
    composed.to_image(spec["palette"]).save(out)
    print("wrote %s" % out)
    if hidden:
        print("  hid %d layer(s): %s" % (len(hidden), ", ".join(hidden)))
    if a.preview:
        composed.preview(scale=8, palette=spec["palette"]).convert("RGB").save(a.preview)
        print("wrote %s (x8, for looking at)" % a.preview)
    # **A refused undo is reported rather than passed over.** Stepping back further than the history goes
    # is a mistake in the script, and a run that printed the same thing either way would let a reader
    # believe an edit had been rolled back when the canvas never moved.
    if undone or redone:
        # History is per layer now, so the labels are flattened in stack order. Printing the pairs would
        # show a reader `('ink', [...])`, which says nothing a person wants from a one-line summary.
        recent = [label for _name, labels in canvas.history() for label in labels][-4:]
        print("history: %d step(s) applied, %d undone, %d redone -> %s"
              % (applied, undone, redone, ", ".join(recent)))
        wanted = sum(st["count"] for k, st in plan_steps(spec) if k == "undo")
        if undone < wanted:
            print("  NOTE: %d of %d undo step(s) did nothing -- the history is shorter than the script "
                  "assumes" % (wanted - undone, wanted))
    # The composed drawing, not the current layer: the ragged-row guard is about what gets written.
    rows = canvas.flatten().rows()
    bad = [(i, len(r)) for i, r in enumerate(rows) if len(r) != canvas.width]
    if bad:
        raise SystemExit("ragged rows: %s" % bad)
    return 0


def cmd_panel(a):
    """Draw a panel and verify it before writing anything.

    **The verification is not optional and not a flag.** A panel is the piece the other tools are meant to
    embed, so a panel that is written without being checked is a panel somebody else inherits unchecked. If
    `panel.check` returns anything, the file is not written and the exit code is 2 -- the same meaning this
    command family gives it: "I will not produce this".
    """
    from . import panel as Pn

    try:
        base, tw, th = Pn.tier(a.tier)
    except ValueError as exc:
        print("REFUSED: %s" % exc)
        return 2
    # **an explicit --width / --height overrides the tier**, so the tier is a starting point and not a
    # constraint -- but the layout is the same either way, which is what `check` verifies below.
    width = a.width if a.width is not None else tw
    height = a.height if a.height is not None else th
    spec = Pn.PanelSpec(border=a.border, title_h=a.title_h, pad=a.pad, bevel=not a.no_bevel)
    try:
        canvas = Pn.draw(spec, width, height, keys=Pn.PANEL_KEYS, title=a.title, active=not a.inactive)
    except ValueError as exc:
        print("REFUSED: %s" % exc)
        return 2
    problems = Pn.check(spec, canvas, keys=Pn.PANEL_KEYS, title=a.title, active=not a.inactive)
    if problems:
        print("REFUSED: the rendered panel disagrees with its own layout in %d place(s)" % len(problems))
        for x, y, role, found in problems[:8]:
            if x < 0:
                print("  layout: %s" % found)
            else:
                print("  (%d,%d) expected %s, found %r" % (x, y, role, found))
        if len(problems) > 8:
            print("  ... and %d more" % (len(problems) - 8))
        return 2
    # **the focus ring lives in the key model, not in a toolkit**, so a transcript can be produced and read
    # here without a display. That is what makes "keyboard-operable" verifiable instead of demonstrated.
    from . import keys as K
    from . import terminal as TERM

    focus = K.Focus(a.controls, index=min(a.focus, max(0, a.controls - 1)) if a.controls else 0)
    if a.dispatch:
        print("  controls: %d, starting at %d" % (focus.count, focus.index))
        for name in a.dispatch.split():
            try:
                effect = focus.apply(name)
            except ValueError as exc:
                print("REFUSED: %s" % exc)
                return 2
            print("    %-12s -> %-10s index=%d" % (name, effect, focus.index))
        print()
    if a.export:
        # **The portable form is what a tool in another language reads.** Volcano Separator is PowerShell and
        # Node, so "embed" cannot be an import; the file carries its own checksum so a reader can tell "this
        # file" from "a file with this name".
        from . import portable as Pt
        import json as _json

        body = Pt.export(a.tier, spec=spec, title=a.title, active=not a.inactive,
                         width=width, height=height)
        with open(a.export, "w", encoding="utf-8") as fh:
            fh.write(_json.dumps(body, ensure_ascii=False, indent=1, sort_keys=True))
        print("%s  panel exported: %s tier %dx%d, %d role(s), checksum %s"
              % (Path(a.export).name, body["tier"], width, height, len(body["roles"]),
                 body["checksum"][:16]))
        return 0
    if a.verify:
        from . import portable as Pt

        try:
            body = Pt.load(a.verify)
        except (OSError, ValueError) as exc:
            print("REFUSED: %s" % exc)
            return 2
        vw, vh = body["size"]
        vspec = Pn.PanelSpec(**body["spec"])
        cv = Pn.draw(vspec, vw, vh, keys=Pn.PANEL_KEYS, title=body.get("title"),
                     active=body.get("active", True))
        bad = Pt.verify(vspec, cv, body=body, title=body.get("title"))
        if bad:
            print("REFUSED: this build's rendering disagrees with %s in %d place(s)"
                  % (Path(a.verify).name, len(bad)))
            for x, y, role, found in bad[:6]:
                print("  (%s,%s) expected %s, found %r" % (x, y, role, found))
            return 2
        print("%s  matches this build: %d pixel(s) agree, checksum %s"
              % (Path(a.verify).name, vw * vh, body["checksum"][:16]))
        return 0
    if a.window:
        # **A window needs a display, and there is no way to fake one.** So the failure is caught and named
        # rather than allowed to surface as a Tcl traceback -- a caller on a headless machine should be told
        # what is missing, not handed a stack.
        from . import window as W

        try:
            W.open_window(spec, width, height, title=a.title, controls=a.controls,
                          scale=max(1, a.scale), hint=a.hint)
        except Exception as exc:
            print("REFUSED: could not open a window: %s" % exc)
            print("  pass --text to print the same panel instead")
            return 2
        return 0
    if a.text:
        for line in TERM.frame(spec, width, height, title=a.title, active=not a.inactive,
                               focus=focus if a.controls else None, hint=a.hint):
            print(line)
        return 0
    if not a.out:
        print("REFUSED: give an output path, or pass --text to print the window instead")
        return 2
    im = Pn.render(spec, width, height, keys=Pn.PANEL_KEYS, palette=Pn.PANEL_PALETTE,
                   title=a.title, scale=a.scale, active=not a.inactive)
    im.save(a.out)
    print("%s  %s tier %dx%d, written at %dx%d, %s"
          % (Path(a.out).name, a.tier, width, height, im.width, im.height,
             "inactive" if a.inactive else "active"))
    print("  %d pixel(s) checked, 0 disagreed with the layout" % (width * height))
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
    if a.delays:
        # **Timing is read from wherever it already lives, because it does not have to be invented.** The
        # TODO entry said it would need a runtime probe; `うごイラ` ships a per-frame delay table, and GIF,
        # APNG and WebP store one per frame, so the honest question is which container to read. A table that
        # does not fit the frame count raises rather than being padded -- see `Timeline.apply_delays`.
        delays, note = F.read_delays(a.delays, unit=a.delays_unit)
        if not delays:
            print("REFUSED: %s" % (note or "no durations in %s" % a.delays))
            return 2
        # **A table that does not fit is refused, not raised.** Measured: three values against six frames
        # came out as a traceback with exit 1, which is the same shape as the earlier `OutOfScopeError` --
        # a caller should not have to read a refusal out of a stack trace. Exit 2 keeps the meaning this
        # project gives it: "I will not produce this", distinct from 1, "produced, with notes".
        try:
            tl.apply_delays(delays, unit=a.delays_unit)
        except ValueError as exc:
            print("REFUSED: %s" % exc)
            return 2
        print("  durations: %s" % note)
    d = tl.drift()
    print("%d frame(s)  canvas %dx%d  anchor %s" % (len(ims), tl.width, tl.height, tl.anchor))
    print("  total %d ms" % tl.total_ms())
    print("  content drift relative to the anchor: %d x %d pixel(s)" % d)
    # **The second measure, printed beside the first because neither subsumes the other.** `drift` reads the
    # silhouette's edge; this reads how far each frame must move to sit on the previous one, which is what
    # catches a shape moving *inside* a fixed outline. The spread is the refusal: a genuine translation gives
    # one offset per pair, so a non-zero spread means the motion is not a translation and the offsets should
    # not be read as distances.
    adx, ady, per, scores, bounds, exact = tl.aligned_shift()
    if per:
        print("  aligned shift between frames: %s" % ", ".join("%+d,%+d" % p for p in per))
        print("    spread %d x %d  (0 means one steady offset; non-zero means the motion is not a "
              "translation)" % (adx, ady))
        # **`exact` is the judgement that was missing, and it is a count rather than a threshold.** A frame
        # is an integer grid, so a real translation matches every changed pixel; a residual above zero means
        # something other than a translation happened. Measured: a one-pixel translation is exact at every
        # window size, while a rotation reaches 0.58 to 0.74 and a flip 0.83 to 0.87 -- nothing that is not a
        # translation reaches 1.0. So the reader is told which pairs are exact, not given a score to weigh.
        if exact:
            n_exact = sum(1 for e in exact if e)
            cut = sum(1 for b in bounds if b) if bounds else 0
            if n_exact == len(exact):
                print("    exactness: all %d pair(s) are exact integer translations" % len(exact))
            elif cut == len(exact):
                # **"best available" would be a lie here**: every fit landed on the window's edge, so the
                # reported (0,0) is the flag rather than an answer and there is no offset to read at all.
                print("    exactness: none of the %d pair(s) is a translation -- every fit ran out of search "
                      "window, so no offset was found and none is reported" % len(exact))
            else:
                print("    exactness: %d of %d pair(s) are exact translations; the rest leave changed pixels "
                      "unexplained, so their offsets are the best available and not a translation"
                      % (n_exact, len(exact)))
        if any(bounds):
            n = sum(1 for b in bounds if b)
            print("    NOTE: %d of %d fits landed on the search window's edge, so those are reported as "
                  "0,0 -- the window was too small rather than the shift being zero" % (n, len(bounds)))
        if any(scores):
            print("    residual disagreement at the best offset: %s" % scores)
    if a.out:
        tl.to_apng(a.out, scale=a.scale)
        print("wrote %s" % a.out)
    if a.gif:
        # **A GIF is offered and its losses are refused rather than silently taken.** GIF has no alpha and a
        # 256-colour table; `to_gif` raises `GifWouldLose` naming what would change, and `--allow-loss` is
        # the caller saying "I know". Exit code 2 for the same reason the frames-count refusal uses it:
        # "I will not produce this" is a different answer from "I produced it and it has notes".
        try:
            # **The kinds are passed through rather than collapsed to a boolean.** A caller who accepts
            # quantisation but not flattened alpha can now say so; before this, `--allow-loss` granted both
            # and nothing granted one.
            tl.to_gif(a.gif, scale=a.scale, allow_loss=a.allow_loss, allow=set(a.allow or ()))
            print("wrote %s" % a.gif)
        except F.GifWouldLose as e:
            print("REFUSED: %s" % e)
            return 2
        except ValueError as e:
            print("REFUSED: %s" % e)
            return 2
    # **`p` was rebound by the comprehension above, and that shadowing hid a second bug.** `ims` holds
    # `Path` objects; the loop variable `p` is reused for the aligned-shift offsets before this line runs.
    # Even unshadowed it would be wrong, because `judge` takes an image -- `cmd_judge` passes a *path*
    # because it reads the file itself, and `judge` opens whatever it is given. So the image that was
    # already opened is passed explicitly and the filename comes from the path.
    #
    # **This was invisible until now because reaching this line needs six or more frames**, and every
    # shorter run exited at the refusal above with code 2 -- so the frames command has been broken on any
    # directory it accepted.
    # **And the judge can refuse the input, which this command has to survive.** Measured on six 16x16
    # frames: `judge` will not measure them -- short side 16, below what its metrics apply to -- and the
    # exception came out of `cmd_frames` as a traceback, while `ichiwatashi judge` on the same file prints
    # `REFUSED` with the explanation and exits 1. A command that dies where its sibling refuses makes the
    # caller read a refusal out of a stack trace.
    try:
        r = judge(first)
    except OutOfScopeError as exc:
        print("REFUSED: %s" % ims[0].name)
        for line in str(exc).strip().split("\n"):
            print("  %s" % line)
        return 1
    print(_fmt_report(r, ims[0].name))
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

    # **The corpus source figure is drawn from the corpus records, not from the sprite**, so it is only
    # produced when a corpus directory is named. It is the one figure whose subject is the corpus rather
    # than a drawing, and it is the honest way to show that a declared source contributes nothing.
    if a.corpus:
        import collections
        root = Path(a.corpus)
        sources = [json.loads(l) for l in (root / "sources.jsonl").read_text(encoding="utf-8").splitlines()
                   if l.strip()]
        manifest = [json.loads(l) for l in (root / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
                    if l.strip()]
        counts = collections.Counter(m.get("source_id") for m in manifest)
        ids = [s["source_id"] for s in sources]
        for sid in counts:
            if sid not in ids:
                ids.append(sid)
        by_id = {x["source_id"]: x for x in sources}
        # **The title says "manifest rows", and the first version said "CORPUS SOURCES".** That version was
        # read -- correctly, by its own words -- as a picture of the whole corpus, in which two of three
        # sources contributed nothing. The truth is that `manifest.jsonl` is the per-sample ledger of ONE
        # generation: `th123-hisoutensoku-rip`'s 120 samples exist only as aggregate percentiles in
        # `calibration.py`, and `ugoira-40frames`' 40 frames are deliberately out of the reference table. So
        # the figure measures rows, the title says rows, and the note distinguishes "aggregate only" and
        # "excluded" from anything genuinely missing.
        canvas, keys = FIG.source_distribution(
            ids, counts, title="MANIFEST ROWS n=%d" % len(manifest))
        p = out / "corpus-sources.png"
        FIG.render(canvas, keys, max(2, a.scale // 3)).convert("RGB").save(p)
        written.append(p)
        for sid in ids:
            if counts.get(sid):
                continue
            src = by_id.get(sid) or {}
            ledger = src.get("ledger")
            if ledger == "aggregate":
                print("  %-24s no rows BY DESIGN: %s sample(s) exist as aggregate percentiles in "
                      "calibration.py" % (sid, src.get("sample")))
            elif ledger == "excluded":
                print("  %-24s no rows BY DESIGN: %s sample(s) are deliberately out of the reference "
                      "table" % (sid, src.get("sample")))
            else:
                print("  %-24s no rows and no ledger field: declared but unmeasured" % sid)
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
    from . import layers as L

    spec = json.loads(Path(a.script).read_text(encoding="utf-8"))
    canvas = L.Layers(spec["width"], spec["height"], spec.get("layers"), spec.get("bg", "."))
    apply_plan(canvas, plan_steps(spec), base_dir=Path(a.script).parent)
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

    pr = sub.add_parser("profile", help="place a sprite between the measured generations")
    pr.add_argument("paths", nargs="+")
    pr.add_argument("--generation", choices=C.GENERATIONS, default=None,
                    help="compare against this generation only. Without it every generation is tried "
                         "and the report says whether they can be told apart at all")
    pr.add_argument("--anyway", action="store_true",
                    help="place something the reference has no subject for; the numbers are then "
                         "uncalibrated, exactly as with `judge --anyway`")
    pr.set_defaults(func=cmd_profile)

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
    b.add_argument("--hide", action="append", default=[], metavar="LAYER",
                   help="omit a declared layer from the picture; it stays in the script")
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
    # **`parent`, not `parents[1]`.** The source moved from `<repo>/assets/` to `<package>/assets/` so that
    # it ships in the wheel -- it did not, and an installed copy could not find its own font. Resolving from
    # the module rather than the repository also stops the default from depending on the current directory.
    ft.add_argument("--source", default=str(FONT_SOURCE),
                    help="the font source; defaults to the copy inside the package")
    ft.add_argument("--format", choices=("powershell", "json", "hex", "text"), default="powershell",
                    help="powershell: the hashtable body volcano-separator reads. hex: char<TAB>hex. "
                         "text: each glyph drawn as # and . so it can be read or diffed.")
    ft.add_argument("--check", action="store_true",
                    help="report what the font can and cannot say, instead of emitting it")
    ft.set_defaults(func=cmd_font)

    pn = sub.add_parser("panel", help="draw a panel and verify it against its own layout")
    pn.add_argument("out", nargs="?", help="where to write the PNG; omit with --text")
    pn.add_argument("--export", metavar="FILE",
                    help="write the panel as portable JSON: layout, roles, keys, colours and characters, "
                         "with a checksum, so a tool in another language can draw the same one")
    pn.add_argument("--verify", metavar="FILE",
                    help="check that this build's rendering still matches an exported panel")
    pn.add_argument("--window", action="store_true",
                    help="open a real window (needs tkinter and a display); refuses rather than crashing "
                         "when either is missing")
    pn.add_argument("--text", action="store_true",
                    help="print the window as text (one character per logical pixel) instead of writing a PNG")
    pn.add_argument("--controls", type=int, default=0,
                    help="how many controls the focus ring holds (0 = none, and the status line says so)")
    pn.add_argument("--focus", type=int, default=0, help="which control starts with the focus")
    pn.add_argument("--dispatch", metavar="ACTIONS",
                    help="apply a space-separated action list to the focus ring and print what each did "
                         "(focus_next focus_prev activate cancel close quit)")
    pn.add_argument("--hint", help="a line of help text shown in the status line")
    pn.add_argument("--tier", choices=tuple(PANEL_TIERS), default="normal",
                   help="a size tier: one layout at several sizes (default normal)")
    pn.add_argument("--width", type=int, default=None, help="override the tier's width")
    pn.add_argument("--height", type=int, default=None, help="override the tier's height")
    pn.add_argument("--inactive", action="store_true",
                    help="draw the inactive title bar; the state is a role, so the check verifies it")
    pn.add_argument("--title")
    pn.add_argument("--scale", type=int, default=1,
                    help="integer upscale; 1 writes at one pixel per pixel")
    pn.add_argument("--border", type=int, default=2)
    pn.add_argument("--title-h", dest="title_h", type=int, default=9,
                    help="title bar height; the default holds a 5x7 glyph with a pixel above and below")
    pn.add_argument("--pad", type=int, default=2)
    pn.add_argument("--no-bevel", action="store_true",
                    help="draw a flat frame instead of a lit top-left and shaded bottom-right")
    pn.set_defaults(func=cmd_panel)

    f = sub.add_parser("frames", help="assemble frames and report drift")
    f.add_argument("directory")
    f.add_argument("--out", help="write an APNG here (real alpha, no colour limit)")
    f.add_argument("--gif", help="write an animated GIF here; refused when the frames cannot be "
                                 "represented without loss, unless --allow-loss is given")
    f.add_argument("--allow-loss", action="store_true",
                   help="allow every loss: shorthand for --allow transparency --allow palette")
    f.add_argument("--allow", action="append", choices=("transparency", "palette"), default=None,
                   metavar="KIND",
                   help="allow one kind of loss and still refuse the others; repeatable. "
                        "transparency = partly transparent pixels are flattened, palette = above 256 colours "
                        "is quantised")
    f.add_argument("--width", type=int)
    f.add_argument("--height", type=int)
    f.add_argument("--duration", type=int, default=100,
                   help="milliseconds per frame, when no table is given")
    f.add_argument("--delays", metavar="FILE",
                   help="read per-frame durations from here: a GIF/APNG/WebP that stores them, or a text "
                        "table of one number per line. Takes precedence over --duration")
    f.add_argument("--delays-unit", choices=("ms", "cs"), default="ms",
                   help="unit of the table's values (default ms; GIF files always report in ms)")
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
    fg.add_argument("--corpus", help="also draw the corpus source distribution from this corpus directory "
                                     "(the one figure whose subject is the corpus rather than a drawing)")
    fg.set_defaults(func=cmd_figures)

    a = ap.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
