# Ichiwatashi 0.4.1

A patch that turns one option off, because on the drawings it was built for it made them worse.

## `--edges` is refused at the command line

Tried on two illustrations at 320 and 160 wide: it delineated the areas between a coat and a leg, and it also
drew stripes along every gradient — every quantisation step became its own region. `edge_tolerance` removed
the worst of it and the picture was still worse than the same drawing without edges.

So the flag is **refused, not deleted**:

```
REFUSED: --edges is disabled for now. On the two illustrations it was tried against it drew stripes
along the gradients, and the result was worse than the same drawing without it. The implementation is
still in the library for the case where it belongs
```

The implementation, `edge_darken`, `edge_min_area`, `edge_tolerance` and their tests stay where they were.
The judgement is about a result on these drawings, not a defect: an option that is wrong for a long gradient
may still be right for a drawing of flat colour blocks, and deleting it would mean rebuilding it when that
drawing turns up.

A refused run exits 2 and **writes nothing** — half a product is worse than no product.

## Testing

**358 tests** (was 357). The new one pins both halves: the exit code, and the absence of the output file.
