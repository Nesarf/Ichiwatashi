# Ichiwatashi（一渡始）

Deterministic measurement and parametric construction for pixel art.

> 中文说明：[README.zh-CN.md](README.zh-CN.md)

---

## What this is, and why measurement comes first

A generate-judge-refine loop needs a **judge** before it needs a generator. This is the judge, plus the
construction and palette and frame pieces that a loop turns out to need.

The order is not a preference. **Pointing the first version of the judge at a sprite known to be good
falsified two of its own assumptions immediately:**

| Assumption | What the measurement said |
|---|---|
| "Fewer isolated pixels is better" | A real 72乘113 fighting-game frame had **10.1%** isolated pixels — 312 of them — against **1.35%** in a hand attempt. The good sprite looked worse **because the count was absolute and the sprites were different sizes.** As a rate the good sprite is *dirtier* still, and correctly so: at 21 colours across 546 clusters, those pixels **are the detail** — single-pixel highlights, eyes, cloth texture. So the metric needs a rate **and** a cluster shape to tell noise from detail, and a rate-only rule raises a false positive on known-good art. |
| "One consistent outline colour is disciplined" | The good sprite scored **0.662** and the hand attempt **0.991** — so the metric was inverted. **And then the inversion was wrong as well, which is the more useful half of the lesson.** Pointed at 161 real TH155 sprites that number has a median of **0.003** — they are *all* flat — while TH123 sits at 0.726. Two generations of correct work. So it was never measuring discipline: it was measuring **how many colours the character's palette has**, which is why one pipeline scored futo 0.055 and hijiri exactly 0.000. It is now two quantities, `outline_variation` and `outline_predictability`, and `outline_style()` names the style (flat / systematic / noisy) **without grading it**. `corpus/AESTHETICS.md` records the published technique this corresponds to — 「セルアウト」, where an outline is the body's own colour darkened, which is what a near-1.0 predictability means. |

**Both of those would have been trained into a model as ground truth**, and neither is visible without
a known-good sample to point at. **The second one shows the limit of that remedy too**: pointing the
metric at good art is what revealed the inversion, and pointing it at a *second* generation of good art
is what revealed that the inversion had only swapped which convention got called correct. One corpus is
a sample of one art direction, so the reference is now keyed by generation — see `calibration.py`.

### And then the thresholds were measured rather than chosen

One known-good sprite falsifies an obviously wrong rule. It cannot set a threshold — so the judge was
pointed at **120 real sprites** (8bpp character frames from `th123a.dat`, 24–128 px, seeded sample from
3853 eligible). The distributions live in `ichiwatashi/calibration.py` with their provenance:

| metric | p05 | p25 | median | p75 | p95 |
|---|---|---|---|---|---|
| `colours_used` | 16 | 22 | **26** | 31 | 37 |
| `isolated_rate` | 0.074 | 0.099 | **0.116** | 0.134 | 0.160 |
| `outline_variation` | 0.578 | 0.658 | **0.726** | 0.801 | 0.855 |
| `bbox_fill` | 0.345 | 0.458 | **0.538** | 0.589 | 0.652 |
| `largest_cluster_rate` | 0.039 | 0.063 | **0.090** | 0.136 | 0.228 |

**Only 1 of the 120 raises any note now**, which is the property worth keeping: a report that fires on
good work is a report that gets ignored.

Two things fell out of the distribution that a single sample could not have shown:

- **The old isolated-pixel rule fired above 5%, which is below the fifth percentile of real sprites.**
  Real art sits at 7.4–16%. Both of the 32乘32 attempts were wrong in *opposite* directions — one at
  15.4% (fragmented) and one at 1.35% (too coherent, and flagged by a high bounding-box fill instead).
  **A "lower is better" rule can only ever see one of those two failures.**
- **Real sprites use 26 colours at the median.** Both attempts used 10 and 12, which is a real gap and
  now gets said out loud.

### And a third corpus showed the metrics measure a convention as well as art

The judge was pointed at 40 frames of a pixel-art animation from a different artist and a different
decade. Raw, they measured `bbox_fill` **1.000** and `outline_variation` **0.000** — raising "the
silhouette is a block" and "the outline is flat" — and **40 of 40 were flagged.**

Both notes were false, and for a reason the tool had no way to see: those frames are **opaque and fill
their canvas**, with the subject on a background rather than on transparency. `bbox_fill` and
`outline_variation` cannot be measured on such an image at all — they read 1.000 and 0.000 whatever is
drawn. After the background was made transparent and each frame cropped to its subject, the same
frames measured **0.642** and **0.564**, both inside the reference range.

So `judge` now recognises a rendered frame and says so, instead of producing two confident notes about
the export rather than the drawing. That is the same failure as the 5% threshold and the 35% flag rate:
**a report that fires on good work gets ignored, and the way to find these is to point the tool at work
that is already known to be good.**

With the convention matched, the two corpora can be compared at all:

| metric | TH123 (n=120) | animated pixel art (n=40) |
|---|---|---|
| `isolated_rate` | 0.116 (0.074–0.160) | **0.057 (0.036–0.078)** |
| `outline_variation` | 0.726 (0.578–0.855) | 0.564 (0.245–0.703) |
| `bbox_fill` | 0.538 (0.345–0.652) | **0.642 (0.613–0.685)** |
| `largest_cluster_rate` | 0.090 (0.039–0.228) | 0.149 (0.060–0.191) |

Two differences survive, and one row is deliberately missing: `palette_size` was **forced to 16** when
the second corpus was reconstructed from a lossy source, so that number is the reconstruction's and not
the artist's. **A metric that a processing step sets is not evidence about the art**, which is the same
distinction the merging sampler exists to make.

Notes are phrased as *unlike the reference* rather than *wrong*, and the range used is p05–p95 — so by
construction about one good sprite in ten sits outside it. That rate is deliberate: it keeps the note
meaning something.

---

## Install

```bash
pip install -e .
```

Pillow is a hard dependency: a tool that reads and writes images and cannot open a PNG is broken, not
degraded.

## Figures

```bash
ichiwatashi figures sprite.png --out figures/ --scale 6 --colours 16
```

Four pixel-art figures — the sampled palette, the silhouette, the outline study, and this sprite's
metrics against the shipped reference bands. **Every one is drawn with this repository's own tools**:
`builder`'s shapes and `font`'s glyphs, never a plotting library. The family rule is that this project's
assets are pixel art, and for a measuring tool that has a second edge — *if a figure cannot be drawn with
the tool's own verbs, the tool has a gap, and importing a drawing library would hide it.*

The output path is one way only: a canvas at one pixel per pixel, then an integer `NEAREST` upscale. A
figure that had been resampled would be lying about the pixels it shows, so the renderer is asserted to
invent no colour: every pixel in a figure comes from the figure's own key table.

Two layout decisions were forced by reading the pixels back rather than by looking:

- **A swatch needs a field-coloured pad.** The ring on each swatch is its own darker step, which is the
  `outline_predictability` relation drawn instead of tabulated — and for a near-black colour that derives
  a near-black ring, so one swatch in a sixteen-colour board had no edge at all. The pad guarantees a
  boundary whatever the colours are.
- **A bar chart needs a span per row.** Three judge metrics on one shared scale measure 43.0, 0.115 and
  0.41; the first filled the plot and the other two were invisible. Each row is now drawn inside its own
  reference band with the shipped reference marked on it, which is the comparison `tools/calibrate.py`
  prints as text.

## History

```json
{"op": "rect", "x0": 2, "y0": 2, "x1": 17, "y1": 9, "key": "r"},
{"op": "undo"},
{"op": "rect", "x0": 6, "y0": 2, "x1": 13, "y1": 9, "key": "r"}
```

A shape script can step back over its own earlier steps and try something else in place, so one run shows
both attempts instead of two files. `{"op": "undo", "count": 2}` steps back twice; `redo` steps forward.
**A refused undo is printed**, because a run that said the same thing either way would let a reader
believe an edit had been rolled back when the canvas never moved.

The API is `Canvas.undo()` / `redo()` / `history()` / `state()` / `clear_history()`, and a caller looping
over `put` for a dynamically computed region can group it with `with canvas._shape("name"):`.

**Undo stores a snapshot of the cells rather than a diff, and that is the acceptance test talking.** This
project's rule is that state is reconstructable rather than trusted; a diff-based undo would need every
verb to be exactly invertible, and `shade` and `outline` both read the canvas while writing to it, so an
inverse of those is not a local operation. A snapshot needs nothing of the kind: undo puts the cells back
to a state that was *observed*, so "pixel-identical to what it was" holds by construction. The cost was
measured before choosing — a 512 by 512 canvas is 262,144 single-character strings and copying that list
takes about a millisecond.

## Use

### Measure

```bash
ichiwatashi judge sprite.png
```

```
sprite.png  32x32  474 opaque pixel(s)
  palette          12 colour(s)
  pixel scale      1  (1 is normal for hand-authored art)
  isolated pixels  73  (15.40%)
  clusters         100, largest 46 (9.7%), median 1
  outline variation 0.088 over 102 border pixel(s)  flat -- known-good sprites vary this with the local colour
  bounding box     26x32, 57% full
  note: the outline is almost one flat colour (variation 0.09); known-good sprites vary it with the local colour
```

`--fail-on-note` exits non-zero, so it can be a check rather than a report.

### Sample a palette

```bash
ichiwatashi palette sheet.png --count 16 --merge 24 --saturate 2.0 --crop 64,0,482,941
```

**`--merge` is the point.** A 40-frame JPEG animation reported **25,398 distinct RGB values**, and the
head of that list was `#005D77` followed by `#005E77`, `#015C77`, `#005D76` — one colour and its
compression halo. Merging within 24 levels per channel turns that back into the ~10 colours the artist
used. `--merge 0` is available and measures the encoder instead.

Two boards, and they are different objects:

- **material board** — sampled from a reference; what the drawing is made of
- **accent board** — chosen by role; what makes the character recognisable

A frequency-sampled board is a *distribution*, and a distribution is mostly the region two characters
share. Sampled from two character sheets: zero shared colours and a median separation of 0.303, but a
**minimum** of 0.026 — the pair that close being white hair against a near-black outline, which both
characters have. The minimum is what gets confused at small sizes.

### Build

```bash
ichiwatashi build sprite.json --out sprite.png --preview sprite_x8.png
```

A shape script:

```json
{
  "width": 32, "height": 32,
  "palette": {".": "transparent", "h": "#600018", "w": "#FDFDFD", "k": "#2A222C"},
  "steps": [
    {"op": "cone",  "y0": 0, "y1": 6, "w0": 1, "w1": 11, "key": "h"},
    {"op": "disc",  "cx": 15.5, "cy": 14, "r": 5.5, "key": "w"},
    {"op": "outline", "key": "k"}
  ]
}
```

**Why shapes rather than placing pixels.** Authoring a grid by hand requires already having a finished
silhouette in mind, which is the skill being learned. Two hand attempts at 32乘32 produced blocks that
were not recognisable. The same sprite as a cone, a disc and a trapezoid was readable on the second
attempt — because **getting a proportion wrong became editing three numbers instead of re-placing
hundreds of pixels**, and iterating is what converges.

That is not a claim that shapes beat hands; a person placing pixels deliberately will beat this. An
author who cannot yet do that will not, and this gets them to something that communicates.

**The outline pass is not decoration.** Without it a silhouette dissolves into the background at small
sizes. It is automatic here for the same reason it exists: it is a rule, not a decision.

### Frames

```bash
ichiwatashi frames ./frames --out loop.apng --duration 40
```

Reports **drift**: how far the content moves relative to the anchor. That is the number that says
whether an animation will jitter.

```python
from ichiwatashi import Timeline, even_durations, with_hold

tl = Timeline(64, 64, anchor=(32, 60))
for im, pivot in frames:
    tl.add(im, pivot=pivot)

# Fix the total, then buy smoothness with frames and weight with duration.
durations = even_durations(800, 20)
durations = with_hold(durations, 12, 360)     # a one-shot motion wants one long hold
```

Two real animations were measured and they solve the same problem oppositely:

| | fixed canvas | per-frame crop + stored pivot |
|---|---|---|
| anchor | implicit (the canvas corner) | stored per frame |
| cost | texture — the background was 75.7% of each frame | the pivot must be right, or the animation drifts |
| good for | small looping sprites | large one-shot motions with big displacement |

**How a claimed pivot is checked.** Not by looking at the number. The same frames were laid out twice on
the same canvas — once by the stored pivot, once by frame centre — and compared. Pivot alignment put the
feet on one level line; centre alignment floated them. **A pivot that is claimed but never compared
against the alternative is a number with a story attached.**

**Timing, measured from a series by one author:** nine frames at 70 ms, twenty at 40 ms, forty at 20 ms —
frame count and per-frame duration moving in opposite directions while the total stayed between 0.6 and
1.1 seconds. A one-shot motion additionally wants a single long hold, which is how the same survey turned
up 360 ms and 500 ms outliers sitting alone among 60–170 ms neighbours.

---

## What this measures, and what it refuses to

**The judge has a subject, and it now says so instead of printing numbers for anything.** A metric
applied to something that does not have the property being measured returns *not applicable*, and
nothing in the arithmetic distinguishes that from a clean result. Two cases made this a code change
rather than a paragraph:

- `silhouette_share` is **1.000** on a single-colour form. That reads as "a uniform edge" and means
  nothing — every edge pixel is that colour by construction.
- The whole metric set on a 5乘7 bitmap font. Measured over all 58 glyphs of `volcano-separator`'s
  self-drawn pixel font: `colours_used` **1** against a band of 16–37, `isolated_rate` **0.000**
  against 0.074–0.160. Every glyph came back flagged as unlike any reference generation. A font and a
  fighting sprite are not the same kind of object, and nothing had said so.
  (`tools/probe_font_glyphs.py` is that measurement.)

So an input whose **short side is under 24 px** is refused with exit code **2**, distinct from 1, which
means "measured, and a note was raised". Those are different answers and a caller has to tell them
apart.

**The threshold is measured, not chosen.** The 160-sprite reference corpus has a smallest short side of
**62 px** (p05 91, median 123), so 24 refuses a 7 px glyph by a factor of three while clipping nothing
real — checked, not assumed: `TestScope::test_the_gate_clips_nothing_in_the_reference_corpus` runs the
judge over the whole corpus and asserts none of it raises.

**`--anyway` steps past the gate** and prints the numbers as uncalibrated. It exists for the case where
the caller knows what they are measuring; it is not a way to make a warning go away, because there is no
warning — there is a refusal, and overriding it is a decision the caller has to make on purpose.

**What this deliberately does not do** is recognise "a font panel" or any other non-sprite subject. A
screenshot of text is large, passes the gate, and still is not a sprite. A gate can catch the shapes
there are measurements for; anything subtler is a stated limit rather than a silent pass.

---

## What is deliberately not here

**No model, and no training.** Most of what makes pixel art read as pixel art is countable from the
pixels, and a countable answer is faster, explainable and does not drift. Only judgements like "is this
face appealing" need a learned model, and that is a small part of the whole. The pieces that are
measurable are all here; the pieces that are not are not pretended into existence.

## Layout

| | |
|---|---|
| `ichiwatashi/judge.py` | the measurements, each with the correction it carries |
| `ichiwatashi/builder.py` | shapes, and the outline pass |
| `ichiwatashi/palette.py` | merging sampler, saturation, the two boards |
| `ichiwatashi/frames.py` | canvas, pivot, timing, GIF/APNG |
| `test/` | 22 assertions, several of them pinning a mistake so it cannot return |

## Licence

MIT.
