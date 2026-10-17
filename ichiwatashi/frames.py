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

import re
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["Frame", "Timeline", "GifWouldLose", "LOSS_KINDS", "read_delays"]

#: The losses GIF cannot avoid, by name. **Two, not three, and the names are what a caller allows.**
#: A third candidate -- "a frame mixes opaque and transparent pixels" -- was a false positive on every
#: ordinary sprite and is gone; see `gif_losses`.
LOSS_KINDS = ("transparency", "palette")


class GifWouldLose(Exception):
    """Raised when a GIF would not be what was drawn, unless the caller said `allow_loss=True`.

    A named exception rather than a warning, because the alternative -- writing the file and mentioning it --
    leaves the lossy file on disk for whoever reads it next. The tool's other refusals take the same shape:
    `scope.OutOfScopeError` for something too small to measure, and the frames-count check that exits 2.
    """


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

    def apply_delays(self, delays, *, unit: str = "ms"):
        """Set each frame's duration from a list, and refuse a list that does not fit.

        **The count is checked rather than padded.** A four-value table against six frames has no honest
        resolution: broadcast one value and the animation is wrong everywhere, pad with a default and the
        made-up number becomes indistinguishable from a measured one afterwards. So a mismatch raises with
        both counts in the message.
        """
        delays = list(delays)
        if len(delays) != len(self.frames):
            raise ValueError("%d duration(s) for %d frame(s); a duration table has to match the frames"
                             % (len(delays), len(self.frames)))
        if unit not in ("ms", "cs"):
            raise ValueError("unit must be 'ms' or 'cs', got %r" % (unit,))
        for f, d in zip(self.frames, delays):
            value = int(d)
            if value < 0:
                raise ValueError("a negative duration (%r) is not a duration" % (value,))
            f.duration_ms = value if unit == "ms" else value * 10
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

    def aligned_shift(self, *, reach: int = 4, changed_only: bool = True):
        """How far each frame must move to sit on the one before it -- the second drift measure.

        **What `drift` cannot see, and what this replaces it with.** `drift` compares the top-left corner of
        each frame's bounding box against its placement: it reads how far the *silhouette's edge* moved. The
        limitation is recorded on the TODO entry rather than papered over -- "it only takes the first opaque
        row/column, so a shape that moves inside while its silhouette stays put reads 0" -- and it is real,
        because a breathing chest or a turning head keeps the outline and moves everything that matters.

        **`changed_only` is the whole difficulty and was found by measuring, not by design.** The first
        version minimised disagreement over *every* opaque pixel, and on a fixture where a 16-pixel accent
        slid one pixel inside a fixed 330-pixel silhouette it returned `(0, 0)` for every pair: the moving
        accent contributed 32 disagreeing pixels at a one-pixel offset while the stationary body contributed
        52 at a zero offset, so the best fit was correctly "do not move". The metric was overwhelmed by the
        part of the drawing that was not moving.

        So with `changed_only` the pair of frames is first differenced **at zero offset**, which identifies
        the pixels that moved or changed at all, and the offset search then runs over those alone. A region
        that shifted by one contributes far more changed pixels than a region that merely got an edge
        redraw, so the majority of the changed set does translate with the motion. Set `changed_only=False`
        for the whole-frame form, which answers a different question -- how far the drawing as a whole moved
        -- and is the right one when a large area moves together.

        Returns `(dx_spread, dy_spread, per_frame, best_scores, boundaries, exact)`:

            exact                   True per pair where the fit was **exact** -- every changed pixel found a
                                    match at that offset, so the residual is 0. **This is the judgement that
                                    was missing, and pixel art is what makes it clean**: a frame is an integer
                                    grid, so a real translation must match exactly, and a residual above
                                    zero means something other than a translation happened. Measured across
                                    three motion kinds: a one-pixel translation gives `matched = 1.0000` at
                                    every window size, a 90-degree rotation gives 0.58 / 0.71 / 0.74 / 0.74
                                    as the window widens, and a horizontal flip gives 0.83 / 0.87. Nothing
                                    that is not a translation reaches 1.0, and the translation reaches it
                                    regardless of window size.

        The other items:

            dx_spread / dy_spread   max minus min of the per-frame shifts -- the shape `drift` also returns
            per_frame               the offsets themselves, **and these are the useful reading**: a uniform
                                    per-pair shift is speed, while a spread is a jump. Note that a whole
                                    animation translating one pixel per frame has a spread of 0 -- the
                                    spread answers "did the motion stutter", not "did it move"
            best_scores             residual disagreement at the best offset, per pair
            boundaries              True where the best fit landed on the edge of the search window, i.e.
                                    where no answer was found and `(0, 0)` was substituted. **This only
                                    catches a search that ran out of room** -- a fit that settles on a wrong
                                    answer inside the window flags nothing, which is why `exact` exists

        **The spread is what refuses a rotation, and that was measured rather than assumed.** A first
        version of this docstring claimed the boundary flag would catch it. Measured on the rotation fixture
        at three window sizes: at `reach=3` the fit hits the edge five times, while at `reach=6` and `9` it
        "converges" on `(-4, -4)` and flags nothing at all. So **the flag only catches a search that was cut
        off; it cannot catch a fit that settles on a wrong answer**, which is what a rotation produces.

        The signal that does catch it is the **spread**: a genuine translation gives the same offset for
        every pair, so its spread is 0, while the rotation fixture returns `[(-4, -4), (0, -1), ...]` with a
        spread of `(4, 3)`. A caller that reads the spread as "is this motion a translation" gets the right
        answer; a caller that reads it as "how far did it move" does not, and the return tuple's shape is
        the reason both are available.

        When nothing changed between two frames the residual is 0 and the shift is `(0, 0)`, which is the
        truth rather than a fallback.
        """
        frames = self.compose()
        if len(frames) < 2:
            return 0, 0, [], [], [], []
        W, H = frames[0].size
        shifts, scores, boundaries, exact = [], [], [], []
        for a, b in zip(frames, frames[1:]):
            pa, pb = a.load(), b.load()
            if changed_only:
                seta = {(x, y) for y in range(H) for x in range(W) if pa[x, y] != pb[x, y]}
            else:
                seta = {(x, y) for y in range(H) for x in range(W)
                        if pa[x, y][3] or pb[x, y][3]}
            if not seta:
                # identical frames: no motion, and saying so is the truth rather than a fallback
                # identical frames: an exact zero shift, because every changed pixel (there are none)
                # matches. Saying `exact=True` here is the truth rather than a special case.
                shifts.append((0, 0))
                scores.append(0)
                boundaries.append(False)
                exact.append(True)
                continue
            best = None
            for dy in range(-reach, reach + 1):
                for dx in range(-reach, reach + 1):
                    diff = 0
                    for (x, y) in seta:
                        nx, ny = x + dx, y + dy
                        # a shifted read that leaves the frame counts as a disagreement, which is what
                        # keeps the fit from preferring an offset that simply compares fewer pixels
                        ca = pa[x, y]
                        cb = pb[nx, ny] if (0 <= nx < W and 0 <= ny < H) else (0, 0, 0, 0)
                        if ca != cb:
                            diff += 1
                    if best is None or diff < best[0]:
                        best = (diff, dx, dy)
            # **A best fit that lands on the search boundary is not a fit.** Measured on a fixture where a
            # mark changed orientation rather than position, this returned (-4, -4) then (-6, -6) with
            # `reach` at 6 -- sitting exactly on the edge both times, which means the search ran out of room
            # rather than found an answer. Reporting it as a shift would be reporting the search window.
            # The honest result is to widen `reach` or to refuse, so the caller is told which happened.
            if abs(best[1]) == reach or abs(best[2]) == reach:
                truncated = True
                best = (best[0], 0, 0)
            else:
                truncated = False
            boundaries.append(truncated)
            # **`exact` requires both: not cut off, and nothing left over.** A truncated search has no
            # residual worth reading (it is the worst offset in the window, kept only for the note), so it
            # cannot be exact. And a residual above zero means the best available translation still leaves
            # changed pixels unexplained -- which for an integer grid means the change was not a translation.
            exact.append((not truncated) and best[0] == 0)
            shifts.append((best[1], best[2]))
            scores.append(best[0])
        xs = [s[0] for s in shifts]
        ys = [s[1] for s in shifts]
        return max(xs) - min(xs), max(ys) - min(ys), shifts, scores, boundaries, exact

    def gif_losses(self, *, scale: int = 1, background=None) -> dict:
        """What writing these frames as a GIF would cost, measured before the file exists.

        **GIF cannot hold alpha and cannot exceed 256 colours, and `to_gif` used to say nothing at all.**
        The TODO entry called that out -- "GIF 会退化调色板（256 色上限 + 无 alpha）且不告警" -- and it is the
        failure shape this project treats as the worst one: the file is produced, it opens, and it is not
        what was drawn. A sprite on a transparent ground flattens onto whatever background was passed, and a
        sprite with more than 256 colours is quantised.

        Returned as a dict rather than a boolean so a refusal can quote numbers:

            semi_transparent_pixels   pixels with alpha strictly between 0 and 255, summed over frames
            distinct_colours          distinct RGBA values across the frames, which is what the 256 limit
                                      applies to after compositing
            over_limit                distinct_colours is above 256

        **There was a third check here and it was a false positive on every sprite.** It flagged a frame that
        used both a fully opaque and a fully transparent pixel -- which is what every ordinary sprite frame
        does, drawn pixels plus a transparent ground, and it is exactly the case GIF's single transparent
        index represents correctly. The first version therefore refused a four-frame, four-colour, fully
        opaque animation, and the reason is worth keeping: "has both opaque and transparent pixels" is the
        normal case, not the lost one. Only a *partly* transparent pixel is unrepresentable.
        """
        frames = self.compose(background=background)
        if scale != 1:
            frames = [f.resize((f.width * scale, f.height * scale), Image.NEAREST) for f in frames]
        semi = 0
        colours = set()
        for f in frames:
            data = list(f.get_flattened_data())
            alphas = [p[3] for p in data]
            semi += sum(1 for a in alphas if 0 < a < 255)
            colours.update(data)
        # `kinds` is derived here rather than left to the caller: the whole point of naming the losses is that
        # a caller should not have to re-derive which ones apply from a pair of numbers.
        kinds = []
        if semi:
            kinds.append("transparency")
        if len(colours) > 256:
            kinds.append("palette")
        return {
            "semi_transparent_pixels": semi,
            "distinct_colours": len(colours),
            "over_limit": len(colours) > 256,
            "frames": len(frames),
            "kinds": kinds,
        }

    def to_gif(self, path, *, scale: int = 1, background=None, loop: int = 0, allow_loss: bool = False,
               allow=()):
        """Write an animated GIF, refusing the losses GIF cannot avoid unless the caller allows them.

        **The refusal is the point, and `to_apng` is why it can be offered.** GIF has no alpha channel and a
        256-colour table, so a sprite on a transparent ground, or one with a wide palette, comes out
        different from what was drawn -- silently, before this change. A file that opens and is not what was
        rendered is worse than a refusal, because the reader has nothing to go on.

        **`allow` names which losses are acceptable, because they are not equally acceptable.** A partly
        transparent pixel being flattened to opaque-or-clear loses information that cannot be recovered. A
        palette above 256 being quantised also loses information, but it is a *degree*: the file still shows
        the right shapes in approximately the right colours. A caller who is fine with the second and not the
        first had no way to say so -- `allow_loss` was all or nothing, and "I accept quantisation but not
        flattened alpha" was inexpressible.

            allow={"palette"}      write it, quantised, but refuse if alpha would be flattened
            allow={"transparency"} the reverse
            allow=LOSS_KINDS      everything, which is what `allow_loss=True` means

        `gif_losses()["kinds"]` reports which losses are present, so a caller can ask before deciding.
        """
        if allow_loss:
            allowed = set(LOSS_KINDS)
        else:
            allowed = set(allow)
            unknown = allowed - set(LOSS_KINDS)
            if unknown:
                # an unknown name silently granting nothing would be the "I allowed it and it still refused"
                # case, which reads as a bug in the refusal rather than a typo in the argument
                raise ValueError("unknown loss kind(s) %s; known: %s"
                                 % (sorted(unknown), ", ".join(LOSS_KINDS)))
        losses = self.gif_losses(scale=scale, background=background)
        refused, accepted = [], []
        if losses["semi_transparent_pixels"]:
            msg = ("%d pixel(s) are partly transparent, which GIF cannot represent: they become either "
                   "fully opaque or fully clear" % losses["semi_transparent_pixels"])
            (accepted if "transparency" in allowed else refused).append(("transparency", msg))
        if losses["over_limit"]:
            msg = ("the frames use %d distinct colours where GIF allows 256, so the palette is quantised"
                   % losses["distinct_colours"])
            (accepted if "palette" in allowed else refused).append(("palette", msg))
        if refused:
            lines = ["%s would not be what was drawn:" % path]
            for kind, msg in refused:
                lines.append("  %s: %s" % (kind, msg))
            if accepted:
                lines.append("(allowed: %s)" % ", ".join(k for k, _ in accepted))
            lines.append("Use to_apng for real alpha and no colour limit, or allow the loss with "
                         "allow={\"transparency\"} / {\"palette\"} / allow_loss=True.")
            raise GifWouldLose("\n".join(lines))
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


def read_delays(source, *, unit: str = "ms"):
    """Per-frame durations from a file that already carries them, or from a plain text table.

    **The TODO entry said timing would have to wait for a runtime probe, because TH105's `.pat` carries no
    timing.** That is true of that format and false as a general conclusion: **frame timing exists
    independently of pixels and is a normal thing for a container to store.** `うごイラ` ships "frames plus a
    per-frame delay table", GIF and APNG store a duration per frame, and WebP does too. So the question is not
    "where would timing come from" but "which containers can be read", and this reads them.

    Three sources, and **what each can and cannot represent matters**:

        an image file (GIF / APNG / WebP)   the durations the file itself stores. **GIF keeps them in
                                            hundredths of a second**, so a GIF never reports finer than 10 ms
                                            -- a 33 ms delay written to a GIF comes back as 30. That is the
                                            format, not the reader, and it is why the returned values are
                                            checked against `unit`.
        a text table                        one number per line (also accepts commas and whitespace), for
                                            the case where the timing was measured or designed elsewhere.

    Returns `(delays, note)` where `delays` is a list of ints in `unit` ("ms" or "cs") and `note` is a short
    string saying where they came from, or `None` if the source carried none. **An absent duration is reported
    as absent rather than filled with a default**, because a made-up 100 ms is indistinguishable from a
    measured one once it is in the Timeline.
    """
    if unit not in ("ms", "cs"):
        raise ValueError("unit must be 'ms' or 'cs', got %r" % (unit,))
    path = Path(source)

    def to_unit(value_ms):
        return value_ms if unit == "ms" else max(1, round(value_ms / 10))

    if path.is_file():
        try:
            from PIL import Image

            im = Image.open(path)
            n = getattr(im, "n_frames", 1)
            # **"is an image" and "stores durations" are two questions, and the first version conflated
            # them.** A single-frame PNG failed the `n > 1` test, fell through to the text reader, and came
            # back with five numbers parsed out of its binary header -- a still image reported as having
            # timing. Opening it successfully means it is an image; from there, no duration is an answer of
            # "none", not a reason to try reading it as text.
            if n <= 1:
                return [], "%s is a single frame and stores no duration" % path.name
            delays = []
            for i in range(n):
                im.seek(i)
                delays.append(int(im.info.get("duration") or 0))
            if any(delays):
                return [to_unit(d) for d in delays], "%d frame(s) from %s" % (n, path.name)
            return [], "%s has %d frames but stores no duration" % (path.name, n)
        except Exception:
            pass  # not an image; fall through to the text reader

    if path.suffix.lower() == ".zip":
        return _delays_from_zip(path, unit)

    text = path.read_text(encoding="utf-8", errors="replace")
    numbers = [int(float(tok)) for tok in re.findall(r"-?\d+(?:\.\d+)?", text)]
    if not numbers:
        return [], "%s contains no numbers" % path.name
    if unit == "ms":
        # **the text table is taken as already being in the requested unit** -- it is a table somebody wrote
        # for this purpose, not a container's internal representation, so reinterpreting it would be wrong
        return numbers, "%d value(s) from %s" % (len(numbers), path.name)
    return numbers, "%d value(s) from %s (read as centiseconds)" % (len(numbers), path.name)


def _delays_from_zip(path, unit):
    """Per-frame durations from an animation archive, or a statement that the archive has none.

    **What `うごイラ` actually is, checked against a client rather than remembered.** The earlier note in this
    project said the format "is frames plus a per-frame delay table", which is **only true of exports that
    repackage it**. pixiv's own ZIP contains the frames and nothing else: gallery-dl's pixiv extractor reads
    the timing from the API (`/v1/ugoira/metadata` -> `["ugoira_metadata"]["frames"]`, each frame being
    `{"file": ..., "delay": ...}`) and the archive comes from a separate `zip_urls`/`originalSrc` URL. So a
    native archive **has no answer to give**, and the honest report is to say that instead of an empty list
    with no explanation.

    The reader therefore accepts both shapes:

        a table inside the archive     any of `metadata.json`, `ugoira_meta.json`, `frames.json`,
                                       `delays.txt`, `animation.json` -- in the pixiv metadata shape,
                                       as a bare `frames` array, or as a plain list of numbers
        frames only                    reported as having no timing, with the frame count, so the caller
                                       knows the archive was read and not mistaken for something else

    The pixiv shape nests one level (`{"ugoira_metadata": {"frames": [...]}}`) and the delay is in
    milliseconds there, so it is converted through `unit` like any other value.
    """
    import json
    import zipfile

    names = ("metadata.json", "ugoira_meta.json", "frames.json", "delays.txt", "animation.json")
    with zipfile.ZipFile(path) as z:
        members = z.namelist()
        images = [m for m in members if not m.endswith("/") and
                  m.lower().rsplit(".", 1)[-1] in ("jpg", "jpeg", "png", "webp", "gif")]
        table = None
        for candidate in names:
            hit = [m for m in members if m.rsplit("/", 1)[-1].lower() == candidate]
            if hit:
                table = hit[0]
                break

        def to_unit(value_ms):
            return value_ms if unit == "ms" else max(1, round(value_ms / 10))

        if table is None:
            return [], ("%s holds %d frame(s) and no delay table -- pixiv's own archives keep timing in the "
                        "API metadata, so it is not in this file" % (path.name, len(images)))

        raw = z.read(table)
        if table.lower().endswith(".json"):
            try:
                data = json.loads(raw.decode("utf-8", errors="replace"))
            except ValueError as exc:
                return [], "%s: %s is not valid JSON (%s)" % (path.name, table, exc)
            # the pixiv shape nests under `ugoira_metadata`; a bare `frames` key is the same thing un-nested
            if isinstance(data, dict):
                data = data.get("ugoira_metadata", data)
                frames = data.get("frames", data) if isinstance(data, dict) else data
            else:
                frames = data
            values = []
            for item in frames:
                if isinstance(item, dict):
                    # `delay` is the field pixiv uses; accept `duration`/`ms` rather than guess silently --
                    # a wrong key would produce an empty list and look like an archive with no timing
                    for key in ("delay", "duration", "ms", "duration_ms"):
                        if key in item:
                            values.append(int(item[key]))
                            break
                    else:
                        return [], ("%s: a frame entry in %s has no delay field (%s)"
                                    % (path.name, table, ", ".join(sorted(item))))
                else:
                    values.append(int(item))
            if not values:
                return [], "%s: %s parsed but held no delays" % (path.name, table)
            return [to_unit(v) for v in values], ("%d value(s) from %s inside %s"
                                                  % (len(values), table, path.name))
        # a plain text table inside the archive
        numbers = [int(float(tok)) for tok in re.findall(r"-?\d+(?:\.\d+)?",
                                                         raw.decode("utf-8", errors="replace"))]
        if not numbers:
            return [], "%s: %s inside the archive holds no numbers" % (path.name, table)
        return numbers, "%d value(s) from %s inside %s" % (len(numbers), table, path.name)


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
