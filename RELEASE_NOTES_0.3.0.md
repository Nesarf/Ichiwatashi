# Ichiwatashi 0.3.0

Six verbs that make the tool a place to put pixels, rather than a thing that guesses what they should be.
Every one of them is deterministic, reversible, and opens back up into what the script said.

## `mirror` — one half, then the other

Draw the left, let the tool place the right. **The axis is a column index, not the canvas centre**, and on
an even width those differ: a 32-wide canvas has columns 0..31 and its centre falls at 15.5, so `axis=15`
and `axis=16` give two drawings that are each symmetric and one pixel apart. Which column is the spine is a
drawing decision.

Only non-background pixels are copied. Mirroring the background as well would erase what had already been
drawn on the destination side — the one way this verb could destroy work without saying so.

## `part` — one body, several expressions

A part is another shape script, placed whole. `file` resolves against the script that names it, so a folder
of parts travels with the drawings that use them.

**One level deep, deliberately.** A part may not place a part: that is a graph, a graph can be cyclic, and
the case this exists for — one body with a few faces — is one level. A refusal is a smaller promise than a
resolver with a cycle detector.

Keys belong to the host, so a part naming an entry the canvas lacks fails where the colour is looked up
rather than drawing nothing quietly.

## `layers` — the same drawing in passes

A script can declare passes and name one per step. The order is the declaration order, bottom first, and
**each pass keeps its own history** — an `undo` steps back the pass it is aimed at.

`--hide` composes without a pass: it stays in the script and leaves the picture, which is the whole reason
to keep a draft layer.

Not transparency. A pixel sprite lands on one colour, and a stack that could fade would be exporting
something the format cannot carry.

## `copy` and `flip` — region verbs

`copy` reads a rectangle and places it at an offset, **adding**: its empty pixels do not erase what they
land on. `flip` mirrors the rectangle in place, and that one **does** write the empties back, because they
moved too. Skip that and the result is the original plus its mirror in the holes it left behind — invisible
on a solid rectangle, obvious on a sprite. In the code the difference is one call: `blit` adds, `stamp`
moves.

A rectangle that leaves the canvas keeps its requested size, with the outside filled as background, so a
block read at one offset and written at another still lines up.

## `mask` — a rectangle every later write lands inside

Enforced at the one function every write reaches: shapes, `outline`, `blit`, `stamp`, `mirror`. A mask
honoured by `put` and not by `blit` looks right in the simplest case and leaks everywhere else, which is why
the tests enumerate the paths instead of trusting one.

`recolor` ignores it on purpose — it rewrites pixels that are already there — and a mask is **not a history
entry**: it is the condition a drawing was made under, not a drawing.

## `unit` — one step of the grid is N pixels

Positions snap (`x0`, `x1`, `y0`, `y1`, `cx`, `cy`); sizes do not (`w0`, `w1`, `r`), because rounding a
radius changes the shape rather than placing it. At the default of 1 every coordinate is exactly where the
script says.

Half-way rounds away from zero, so `snap(-v)` is `-snap(v)`. The first version used `floor(v/u + 0.5)`,
which sends -2 to 0 while sending 2 to 4; a rule that changes with the sign of the coordinate is one more
thing to remember for no reason.

The grid JSON carries the unit and `from_grid` reads it back.

## Testing

**321 tests** (was 250), seventy-one new, and three of them were wrong before they were right:

- A test asserted a flipped copy landed at the block's left edge when the flip had moved it one column
  right. **The code was right**; the test now says what the flip actually promises.
- A test asserted a pixel sat inside a snapped rectangle that it was outside of, because the arithmetic
  was done in my head instead of on the numbers.
- `spec.get("layers") or ["base"]` treated an empty list as "no layers declared", so a script declaring
  none passed validation and drew onto `base`. Found by writing the test for the empty case.

Each new guard was checked by breaking it: disabling the mask's check turns eight of its fourteen tests
red; swapping `stamp` for `blit` in `flip` turns exactly the test that names that failure red.
