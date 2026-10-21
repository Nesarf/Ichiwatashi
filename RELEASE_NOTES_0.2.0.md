# Ichiwatashi 0.2.0

`profile`: where a sprite sits between the measured generations.

## Why this is not a model

A learned verdict needs labels, and the only labels this project can defend are *"this came from
known-good work"* — which is exactly what the two reference buckets already are. So the first version
answers the question a caller actually asks — *which era does this look like?* — by placing four numbers
the judge already measures against bands the judge already carries. Nothing is trained, and every
distance opens back up into the numbers it came from. A model would not have that property.

## What a distance is

`calibration.how_far` reports how many p05–p95 band widths one value sits outside its range; zero when
inside. The distance is the length of that vector over four metrics, so `1.0` is "one metric one band
width out" and `0.707` is "two metrics half a width out each". A sum would have called the second one
`1.0` as well, and the two are not the same displacement.

## What it refuses to say

When a sprite is inside every band a generation compares, the distance is `0.00` — on **both**
generations, because there is no evidence either way. The report says the two are not separated instead
of naming the one that sorted first. A position is not a probability, and a tie is a result.

## The defect the feature found in an existing function

`calibration.how_far` had said **"signed"** in its docstring since it was written. Both branches return
a positive number, and nothing noticed because the only caller (`judge`) uses it to *order* its notes,
where the sign does not matter. This release needed to say which side a value fell on — "fewer colours
than any reference generation" and "more" are different findings — and the sign was not there.

The docstring is corrected and the direction is recorded separately (`below` / `above` / `none`). The
return value is unchanged on purpose: making it signed would reorder the judge's notes, and a feature
that arrives by silently changing an existing report is the kind of thing this project keeps writing
down.

## TH155 is compared on three metrics, not four

Its palettes are interchangeable — 92.5% of its sprites change colour count when decoded with another
member of the same set — so it has no `colours_used` band. `compared` travels in every row so a distance
computed from three metrics cannot be read as one computed from four.

## Testing

**250 tests** (was 239), eleven of them new. Verified to fail: with the distance temporarily forced to
`0.0`, three of them go red — the two arithmetic ones and the "far outside one generation is separated"
one. A number that has never been seen to be wrong is not being checked.
