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
| "Fewer isolated pixels is better" | A real 72×113 fighting-game frame had **10.1%** isolated pixels — 312 of them — against **1.35%** in a hand attempt. The good sprite looked worse **because the count was absolute and the sprites were different sizes.** As a rate the good sprite is *dirtier* still, and correctly so: at 21 colours across 546 clusters, those pixels **are the detail** — single-pixel highlights, eyes, cloth texture. So the metric needs a rate **and** a cluster shape to tell noise from detail, and a rate-only rule raises a false positive on known-good art. |
| "One consistent outline colour is disciplined" | The good sprite scored **0.662** and the hand attempt **0.991** — and the good sprite is right. Commercial pixel art varies its outline with the local colour: hair gets a cool outline, cloth a warm one. **A single flat outline is the beginner's move.** The metric was inverted. |

**Both of those would have been trained into a model as ground truth**, and neither is visible without
a known-good sample to point at. That is the whole argument for this repository existing as a
measuring tool first.

---

## Install

```bash
pip install -e .
```

Pillow is a hard dependency: a tool that reads and writes images and cannot open a PNG is broken, not
degraded.

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
silhouette in mind, which is the skill being learned. Two hand attempts at 32×32 produced blocks that
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
