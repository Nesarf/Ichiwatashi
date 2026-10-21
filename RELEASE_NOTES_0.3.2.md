# Ichiwatashi 0.3.2

A patch for one false hint, found by testing the published 0.3.1 rather than the checkout.

## The hint that could not see the answer

A script whose steps are all `part` reported:

```
hints (1):
  - palette entries no step uses: 'h', 'k', 'w'
```

Those three entries were being used — by its parts. **A part draws with the host's keys from its own
file**, so the drawing that places it has no usage of its own to count, and the check read "nothing here
names this" as "nothing names this anywhere".

The unused-entry hint is now skipped for any script that places a part, because that script cannot answer
the question. The other hints still apply to it: an empty pass, a shaded form with no edge, a canvas that is
not a whole number of units.

**A check that cannot see the usage must not report the absence.** That sentence is the whole patch.

## Why the checkout would not have caught it

The suite's own scripts draw their own keys, so the case never arose there: every script in it was one the
hint could reason about. It took running the installed package against a folder of parts — the shape the
`library` command exists for — to produce a script the hint was wrong about.

## Testing

**344 tests** (was 343). The new one is the exact case: a script of nothing but parts reports no unused
entries, while the scripts that draw with their own keys still do.
