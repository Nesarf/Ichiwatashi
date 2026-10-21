# Ichiwatashi 0.3.1

Two layers that had been described and never built, plus the step that made one of them possible.

## Hints: what a script says about itself

`build` now reports **contradictions inside the script** — an entry nothing uses, a declared pass nothing
drew on, a shaded form with no edge, an outline sharing a band's colour, a canvas that is not a whole number
of units, a palette large enough to be a texture.

**Nothing here compares a drawing with real art.** `judge` does that, on work that already exists. A
construction script of three colours is not wrong for being three colours, and a hint that fires on
deliberate work is a hint nobody reads — the failure `calibration.py` already records twice.

`--no-hints` skips them.

## `shade` is a step now

It has been a canvas method since the beginning and `plan_steps` never knew it, so the shading hint would
have been coverage of code no script could reach.

```json
{"op": "shade", "light": {"h": "l"}, "dark": {"h": "d"}, "depth": 3}
```

Both bands are required and `depth` must be a positive integer: a shade step that does one side only is
almost always half a thought.

## `library DIR`: which parts are used, by what

```
parts: 3 part(s), 2 drawing(s), 0 ignored
  part    body.json              32x32  keys -  figure_a.json, figure_b.json
  draw    figure_a.json          32x32  places body.json, eyes_a.json
```

The split between a part and a drawing is the one the format already makes — **a drawing declares a
palette, a part does not** — so the scan works on a folder nobody organised. An unused part is reported and
does not fail; a drawing naming an absent part exits 1.

## Two defects, and the second found by breaking 28 tests

**Two-character palette keys corrupt the text grid.** `rows()` joins characters, so `hl` and `hd` made a
24-wide canvas produce rows 25 to 37 characters wide, and `build`'s ragged-row guard reported the symptom a
long way from the cause.

The first fix refused the key at write time — and broke 28 panel and figure tests, because **a panel's keys
are two characters** (`fd`, `tx`, `ct`) and are perfectly correct: a panel renders through `to_image` and
never becomes text. The check lives in `rows()`, which is the only place the requirement exists.

**The background counted as an unused entry**, so every script carried a hint. It is a key the canvas fills
itself with and no step ever names.

## Testing

**343 tests** (was 321), twenty-two new. One of them had to move: the key-length check was asserted through
`put`, then through `rows` once the refusal moved there — and the second version also asserts that the same
canvas renders as an image without complaint, which is the half that keeps the fix honest.
