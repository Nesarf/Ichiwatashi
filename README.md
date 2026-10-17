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

Five pixel-art figures — the sampled palette, the silhouette, the outline study, this sprite's metrics
against the shipped reference bands, and (with `--corpus DIR`) the corpus source distribution. **Every one is drawn with this repository's own tools**:
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

## Panels: a frame that verifies itself

NTVI assigns this repository the shared pixel layer — font, palette, **panel layout** — which the other tools
embed. Something three other projects will embed has to be **verifiable by itself**, so `ichiwatashi/panel.py`
is a description, a renderer and a pixel check rather than a GUI:

```
ichiwatashi panel out.png --width 96 --title "Ichiwatashi" --scale 4
out.png  96x40 logical, written at 384x160
  3840 pixel(s) checked, 0 disagreed with the layout
```

**`draw` and `check` walk one definition.** `_role_at` decides what each pixel carries; `draw` paints it and
`check` compares against it. A first version had the renderer paint "a dark rectangle then a light face" while
the checker derived the expected role from a diagonal split — **two renderers agreeing with each other
verifies nothing.** What the check now verifies is the pixels against the layout, which is what it is for.

**And it caught two real things while being built.**

- **90 problems on a correct panel** — the title glyphs are drawn *over* the title bar, so those pixels are
  legitimately not the bar's colour. `check(..., title=...)` now steps over exactly the glyph box, computed
  from the same metrics `draw` used, so the rest of the bar is still verified.
- **A 64-pixel panel titled "Ichiwatashi" drew "Ichi wa.ta.sk"** — the bar had 58 pixels and the word needs
  65, so the panel displayed a different word and saved successfully. That is the same failure as a figure
  whose label ran off its canvas. **A title that does not fit is now refused**, and the message names both
  numbers.

The defaults derive from the font: `title_h = 9` because a 5x7 glyph needs a pixel of clearance above and
below. A title bar that cannot hold a glyph is not a title bar.

### What makes it a window rather than a panel

Two things, and both are **checkable properties rather than rendering choices**:

- **Size tiers.** `compact` 72x30, `normal` 96x40, `wide` 160x48 — **one layout at three sizes**, which is only
  true because every tier passes the same `check`. A test asserts that, and it is what keeps three tiers from
  becoming three layouts.
- **Activity.** The title bar's colour is the visible record of whether a window is the active one, so
  `title` and `title_inactive` are two **roles**, not a tint applied at render time. Measured: a panel drawn
  active and checked as inactive reports **751 problems**, all in the title bar. **A tint would have been a
  detail no test could see.**

```
ichiwatashi panel out.png --tier compact --title "Ichi" --scale 3
t-compact.png  compact tier 72x30, written at 216x90, active
  2160 pixel(s) checked, 0 disagreed with the layout
```

### Input: a model, not a toolkit

"A keyboard-operable window" sounds like a GUI problem and is mostly not one. What a window *does* with a key —
which control is next, whether Enter activates or closes, whether Escape backs out — is a small state machine,
and **that is the part that can be wrong**. The toolkit only delivers the keystroke.

So `ichiwatashi/keys.py` contains no toolkit at all:

```
$ ichiwatashi panel --tier compact --title "Ichi" --controls 3 \
    --dispatch "focus_next focus_next activate" --text
  controls: 3, starting at 0
    focus_next   -> moved      index=1
    focus_next   -> moved      index=2
    activate     -> activated  index=2

########################################################################
#++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++#
#+--------------------------------------------------------------------##
#+---###--------------------------------------------------------------##
...
active  focus 3/3
```

**One character is one logical pixel**, so the interface can be compared as a string — which a toolkit window
cannot be: what a test can see of it is whatever the toolkit exposes, and that is not the pixels. The geometry
comes from `panel.layout`, because two independent ideas of where a border goes is the defect this repository
already fixed once.

Two things the split bought, both measured:

- **The escape-sequence order is now a test.** `\x1b[Z` starts with `\x1b`, so a table tried in the wrong order
  reads every arrow key as Escape plus stray characters — **the symptom is a window that closes when you press
  Up**. Longest-first is asserted.
- **A binding that never fired.** `parse_key("q")` returns `char:q` while the table says `q`, so `"q": "quit"`
  sat there and never triggered — measured, pressing `q` returned `ignored`. A `char:` key not found verbatim
  is now looked up by its letter.

Measured availability before choosing any of this: `tkinter` present, `msvcrt` present, `curses` and `termios`
absent, terminal 80 by 24 — **so a real window is reachable; what was decided first is what to verify.**

## The clear ground is not a colour

`palette.sample` merges near-duplicates first — a sampler that does not merge measures the encoder, not the
art — and it counts **only opaque pixels**. A first version converted to RGB before counting, which turned
every transparent pixel into `#000000`; on a real 207x179 sheet that black became the **most frequent entry**
in the palette of a sprite that does not contain it.

And the `palette` command names **which parameter limited the result**, in four cases rather than two, because
"fewer than `--count`" has three different causes:

```
18 distinct colour(s) in the drawing
merged to 4 within 24 per channel -- the threshold is what limited this, not --count 8
  lower --merge to see more; 0 measures the encoder rather than the art
```
```
all 18 colour(s) this drawing uses (--count 40 allows more; merging within 4 reduced none)
```
```
4 colour(s) -- the first 4 of the merged set, capped by --count
```

The third case deliberately does **not** say what merging would have done: `--count 4 --merge 24` can return
four colours for both reasons at once, and **naming the wrong cause is worse than naming none**.

## Palette roles

`palette.roles(image)` says what job each colour does, and it judges that by **the relation a colour stands
in**, not by where it sits:

```
#927BCE  fill
#000000  fill
#0C0009  outline
```

Two colours a reader cannot tell apart as hex values — `#000000` and `#0C0009` — are different roles, which
is the point.

**Only the outline role is measured confidently.** The TODO entry asked for 皮肤 / 头发 / 服装 / 描边 / 高光
slots; four of those need semantics a pixel grid does not carry, because nothing in the data says which
region is skin rather than cloth. `highlight` is deliberately not assigned: the obvious criterion (most
neighbours are darker) put 224 colours into that role across 20 sprites, four to seventeen per sprite — that
is what a gradient looks like at every step, not a role.

The criterion is the `(fill, outline)` pair relation `judge._outline` already builds, and **the positional
alternative was measured first and failed**: "touches transparency" produced no outline role at all on 16 of
20 real sprites, while `outline_predictability` simultaneously read ~1.0. An outline colour is also used for
the interior contours between hair locks, so most of its occurrences never touch the background.

Over all 160 sprites, every one has at least one outline colour; the count is 1 for 100 of them, 2 for 38, 3
for 4, 5 for 3, 6 for 14 and 7 for 1. The most common single outline colour is `(26, 0, 35)` in 80 sprites,
and `(12, 0, 9)` in 37 — so it is not one constant across the generation.

## Frame drift, two ways

`Timeline.drift()` compares each frame's bounding-box corner against its placement: it measures how far the
**silhouette's edge** moved. `Timeline.aligned_shift()` measures how far each frame must be moved to sit on
the one before it, which is the translation the drawing actually underwent — and it sees motion the first
one cannot, because a breathing chest or a turning head keeps the outline and moves everything that matters.

```
content drift relative to the anchor: 0 x 0 pixel(s)
aligned shift between frames: +1,+0, +1,+0, +1,+0, +1,+0, +1,+0
  spread 0 x 0  (0 means one steady offset; non-zero means the motion is not a translation)
```

Two things about that output are deliberate. The **per-pair offsets** are the useful reading (a steady
value is speed; a spread is a stutter). And the **spread is the refusal**: a genuine translation returns one
offset for every pair, so a non-zero spread means the motion is not a translation and the offsets should not
be read as distances. A best fit that lands on the edge of the search window is reported as `0, 0` with a
note, because a truncated search is not a measurement.

**And `exact` answers the question that flag cannot.** Frames are an integer grid, so a genuine translation
matches every changed pixel and leaves a residual of zero. Measured as a matched fraction: a one-pixel
translation gives **1.0000 at every window size**, while a 90-degree rotation gives 0.58 to 0.74 as the window
widens and a horizontal flip 0.83 to 0.87. **Nothing that is not a translation reaches 1.0, and the
translation reaches it regardless of the window** — which is what makes this a judgement rather than a note.
So the CLI reports it as a count:

```
exactness: all 5 pair(s) are exact integer translations
```

And when a fit ran out of search window it says so, instead of offering the flagged `0, 0` as an answer:

```
exactness: none of the 5 pair(s) is a translation -- every fit ran out of search window, so no offset was
found and none is reported
```

Read one thing as a caution: fitting **every** opaque pixel is overwhelmed by whatever is not moving. On a
fixture where a 16-pixel accent slides inside a fixed 330-pixel silhouette, the whole-frame fit correctly
returns `(0, 0)` for every pair. The default differences the pair first and fits only the pixels that
changed, which is why it finds the motion.

## Frame timing, read rather than invented

`ichiwatashi frames DIR --delays FILE` takes per-frame durations from a file that already carries them, and
`frames.read_delays()` does the reading.

**Timing does not have to be designed by hand.** A per-frame delay table is a normal thing for a container to
store — `うごイラ` is "frames plus a delay table", and GIF, APNG and WebP each store a duration per frame. So
the question is which container to read, not where timing could possibly come from.

Two sources:

- **an image file that stores durations** (GIF / APNG / WebP)
- **a plain text table**, one number per line — commas and whitespace both work
- **an animation archive** (`.zip`), if it carries a table — `metadata.json`, `ugoira_meta.json`,
  `frames.json`, `delays.txt` or `animation.json`, in the pixiv metadata shape, as a bare `frames` array, or
  as a plain list of numbers

**A native `うごイラ` archive has no timing to give.** pixiv's ZIP contains the frames and nothing else; the
delays come from the API (`/v1/ugoira/metadata` → `["ugoira_metadata"]["frames"]`, each entry
`{"file": ..., "delay": ...}`). So an archive without a table is reported as such, with its frame count —
which proves it was read rather than mistaken for something else:

```
native.zip holds 4 frame(s) and no delay table -- pixiv's own archives keep timing in the API metadata,
so it is not in this file
```

Two limits, asserted rather than described:

- **GIF keeps its delays in hundredths of a second**, so it can never report finer than 10 ms. Asking a GIF
  for 33 ms gives back **30**. That is the format, not the reader.
- **a table that does not fit the frame count is refused, not padded.** Three values against six frames has
  no honest resolution: broadcast one value and the animation is wrong everywhere; fill a default and the
  invented number is indistinguishable from a measured one afterwards.

A single-frame image reports **no** duration rather than a guess. That case was a real bug in the first
version — a still PNG skipped the image branch because "has more than one frame" was used as the test for
"is an image", then fell through to the text reader and came back with five numbers parsed out of its binary
header.

## GIF, and what it cannot hold

`Timeline.to_gif()` **refuses by default** when the frames cannot be represented without loss, and
`gif_losses()` reports the same numbers before any file exists. GIF has no alpha channel and a 256-colour
table, so:

- **partly** transparent pixels become either fully opaque or fully clear;
- more than 256 distinct colours are quantised.

```
REFUSED: out.gif would not be what was drawn:
  192 pixel(s) are partly transparent, which GIF cannot represent: they become either fully opaque or fully clear
Use to_apng for real alpha and no colour limit, or pass allow_loss=True to write it anyway.
```

**The two losses are not equally acceptable, so they can be allowed one at a time.**

| kind | what it costs |
| --- | --- |
| `transparency` | a partly transparent pixel becomes opaque or clear — **information that cannot be recovered** |
| `palette` | above 256 colours the palette is quantised — a loss of **degree**: shapes stay, colours approximate |

```
ichiwatashi frames DIR --gif out.gif --allow palette
REFUSED: out.gif would not be what was drawn:
  transparency: 288 pixel(s) are partly transparent, which GIF cannot represent: they become either fully
  opaque or fully clear
Use to_apng for real alpha and no colour limit, or allow the loss with allow={"transparency"} /
{"palette"} / allow_loss=True.
```

`gif_losses()["kinds"]` says which losses are present, so a caller can ask before deciding, and a misspelled
kind is refused by name — otherwise "I allowed it and it still refused" reads as a broken refusal rather than
a typo. `LOSS_KINDS` holds **two** names, and a test asserts that count: a third candidate ("a frame mixes
opaque and transparent pixels") turned out to flag every ordinary sprite and was removed.

`--allow-loss` (or `allow_loss=True`) is the caller saying "I know" — the same shape as `judge(anyway=True)`
and the frames-count refusal. The refusal **leaves no file behind**, because a file that opens and is not
what was drawn is worse than no file: the reader has nothing to go on.

One thing that is *not* a loss, and the first version of this check got it wrong: a frame using both fully
opaque and fully transparent pixels. That is what every ordinary sprite frame looks like — drawn pixels on a
transparent ground — and it is exactly what GIF's single transparent index represents correctly. Only a
*partly* transparent pixel is unrepresentable.

## Grid round trip

```bash
ichiwatashi grid sprite.json --out sprite.grid.json     # a shape script's canvas, as editable JSON
#   ... edit sprite.grid.json by hand ...
ichiwatashi ungrid sprite.grid.json --out sprite.png --emit-script sprite.rebuilt.json
```

The form is `{width, height, bg, palette, pixels}`, where `pixels` is one string per row. Colors are
written `#RRGGBB`, or `#RRGGBBAA` when the palette carries alpha, or `transparent`.

**Reading a grid back validates it, and the validation is the reason `from_grid` exists** rather than
being a call to `from_rows`. Each refusal names something that would otherwise be a wrong picture far
from the file that caused it: a missing or non-positive size, rows that are not strings, a row count or
row width that disagrees with the header, a colour that is neither hex nor a known spelling — and the
quiet one, **a character with no palette entry**. An unknown key renders as nothing, so a typo in a
hand-edited file would leave a hole and raise no error anywhere. That check is only possible because the
grid carries its palette.

A round trip is asserted to be pixel-identical and byte-identical after rendering, because the point of
the feature is the TODO entry's own words: a grid could be written out and corrected by hand, and there
was no way to read it back, so **hand work could not return to the tool**.

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
