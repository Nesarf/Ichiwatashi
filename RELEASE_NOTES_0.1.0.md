# Ichiwatashi 0.1.0

Measure pixel art before generating any, and construct it from shapes rather than by drawing pixels.

The name is 一渡始 — "one crossing, the beginning". The tool exists because the alternative was measuring by
eye, and the eye cannot see the single closest pair in a palette or the one property a metric is quietly
failing to apply.

## What it measures

`ichiwatashi judge IMAGE` reports a sprite's palette size, its outline behaviour, whether it is periodic and
at what phase, its interior detail, and its pixel scale — and compares each number against a reference
distribution measured from 120 real sprites of a generation, saying when a value sits outside the range that
distribution covers.

```
canvas            40x28  anchor -1,-1
colours used      16 distinct, among the drawn pixels
pixel scale       1  (no integer factor found; 1 is normal for hand-authored art)
periodicity       none
outline           flat: variation 0.000 over 74 border pixel(s), 1 colour(s), 100% predictable from the fill
```

Two properties of that output are deliberate and both came from being wrong first:

- **A number outside the reference range is a note, not a verdict.** Which outline style is right depends on
  the art direction. An earlier version reported a whole generation of correct work as defective.
- **Below 24 pixels of short side the tool refuses with exit code 2 rather than measuring.** A metric applied
  to an input that does not have the property returns "not applicable" in the shape of a result, which is
  worse than no answer. Pass `--anyway` for the numbers as uncalibrated.

## What it builds

`Canvas` draws with shapes — `rect`, `ellipse`, `line`, `poly`, `shade`, `outline`, `put` — and `font` renders
text from a 5x7 bitmap table. Figures in this project's own documentation are drawn the same way; nothing here
draws with a plotting library.

`undo` / `redo` use snapshots rather than diffs, because `shade` and `outline` read their neighbours while
writing, and the acceptance test is pixel identity.

`from_grid` reads a hand-editable JSON grid back in, so detail can be fixed by hand and re-read.

## What it knows about frames

`ichiwatashi frames DIR` reads an animation and reports two different measurements of motion:

- `drift()` — how far the **silhouette's edge** moved, relative to the anchor.
- `aligned_shift()` — how far each frame must be moved to sit on the one before it, which is the translation
  the drawing actually underwent. **A breathing chest or a turning head keeps the outline and moves everything
  that matters**, which is exactly what the first one cannot see.

`to_apng` keeps real alpha. `to_gif` **refuses by default** when the frames cannot be represented without loss
and says what would change, because GIF has no alpha channel and a 256-colour table. `allow_loss=True` is the
caller saying "I know".

## What it says about a palette

`palette.sample` merges near-duplicates first — samplers that do not merge measure the encoder, not the art.
`palette.separation` reports the minimum and median distance between two boards, because the closest pair is
what gets confused at small sizes and it is exactly what a person choosing cannot see.

`palette.roles` names what job each colour does, judged by **the relation a colour stands in** rather than by
where it sits: a colour is an outline when it appears on the outline side of a fill/outline pair more often
than on the fill side. Over all 160 corpus sprites every one yields an outline colour; the count is 1 for 100
of them and up to 7 for a drawing that outlines different parts differently. Skin / hair / cloth are **not**
reported, because nothing in a pixel grid says which region is skin.

## What this release does not do

Stated rather than left to be discovered:

- **No frame durations are read from the source data.** TH105's `.pat` carries no timing; it may live in game
  code. For now timing is an input.
- **The corpus generality claim is narrower than the word suggests.** The per-row ledger covers one of the
  three sources; the other two exist as aggregate percentiles or are deliberately excluded. `corpus/README.md`
  says which is which.
- **Palette attribution is unlocked on a few manifest rows.** Four criteria were tried and none discriminated.
- **GIF timing and palette are lossy, and the tool now refuses rather than degrades.**
- **No GUI, no interactive viewer.** It is a command line and a library.

## Installing

```
pip install ichiwatashi
```

Python 3.9 or newer, and Pillow 9 or newer. Pillow is a requirement rather than an extra: a tool that reads and
writes images and cannot open a PNG is not a degraded install, it is a broken one.

## Licence and provenance

MIT. The font table in `ichiwatashi/assets/font5x7.txt` is this project's own, and the reference distributions
in `ichiwatashi/calibration.py` are measurements of third-party game assets recorded as facts. **No sample
artwork is distributed with this package** — `corpus/POLICY.md` explains the three gates that decide what may
be committed and what may not.
