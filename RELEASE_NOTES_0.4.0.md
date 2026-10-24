# Ichiwatashi 0.4.0

`pixelate`: a drawing in, a smaller drawing out. Not a pixel drawing yet — that is what the palette is for.

## What it does, in the order it does it

**Sampling is a majority vote, not an average.** An average produces colours that were never in the source,
and a pixel drawing is defined by having few colours that each mean something. Measured on the reference
set: averaging then quantising merged an eyelash into the cheek.

**Then the palette is cut** (`--colours`, default 24) — or not cut at all (`--colours 0`), which is the
drawing made smaller rather than made out of few colours. The two questions are separate on purpose.

**`--sample` decides what a block becomes**, and it is the option a face lives or dies on. `mode` takes the
commonest colour and keeps flat areas flat; an eyelash one pixel wide in a twelve-pixel block is not common
and disappears, which is how the first swordswoman came out with no eyes. `darkest` keeps every line and
comes out heavier. `contrast` takes the pixel furthest from the block's own average, and keeps lines and
highlights both.

**`--head-bias` gives the top of the drawing more rows than its proportion.** A pixel character is drawn
with a head larger than life, because a face needs pixels to be a face; shrinking an illustration
mechanically keeps the illustration's proportions and the face arrives with three pixels for eyes. The row
mapping is `t ** head_bias`.

**`--edges` darkens the rim inside every region**, in the region's own colour multiplied down — a yellow
sleeve gets a dark yellow rim, never black, because one black outline over a drawing of twelve colours
flattens it. It is off by default and it is not always right: see the second lesson below.

**A one-pixel outline** (`--outline #RRGGBB`) around the figure, for separating a drawing from its ground.

## Two things the pictures taught, which the numbers had not

**The first edge implementation drew stripes.** Regions were exact-colour connected components, so after
quantisation every band of a long gradient became its own region and every band got a rim — a face covered
in fine lines. `edge_tolerance` exists because of that picture: at 24, near-identical steps count as one
area and the rim appears only where the drawing really changes colour.

**Contrast sampling is what brought the face back.** At 320 pixels wide the mode vote produced a character
with no readable eyes; contrast produced eyes, lashes and a mouth, at the cost of speckle from the JPEG. The
lesson is smaller than it looks: the block-to-pixel rule decides what survives, and it is a choice, not a
detail.

## What this cannot do

It cannot invent detail the downsample threw away, and it cannot decide what the drawing meant. At 160
pixels wide a two-pixel eyebrow and a two-pixel scar are the same two pixels. The output is a starting point
for `grid` and hand work.

## Testing

**357 tests** (was 354). The head-bias tests use a vertical gradient, so "the head stretched" is a number
compared against the unbiased sample rather than an impression: half way down the output must read from
above half way down the source.
