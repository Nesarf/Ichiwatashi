# Ichiwatashi 0.1.1

A patch release. Both changes come from the first release actually going out, and neither is a feature.

## The metadata claimed 3.9 and the sdist shipped a test that needed 3.11

`requires-python` says `>=3.9`. The version test read `pyproject.toml` with `tomllib`, which arrives in
3.11 — so `python -m unittest discover -s test -t .` from the 0.1.0 sdist fails on 3.9 with
`No module named 'tomllib'`. One test, and enough to make the claim false in the artifact that carries
the tests.

It now reads the single `version = "..."` line with a regex. A parser is not needed to read one string,
and adding a dependency to read it would be a second thing that can be absent.

## The Pillow accessor moved and the declared floor did not

`frames.py` called `get_flattened_data()`, which Pillow introduced in version 12, while `pyproject.toml`
says `Pillow>=9`. On Python 3.9 pip resolves to a Pillow older than the rename, and five frame tests
failed with `'Image' object has no attribute 'get_flattened_data'`.

`frames.pixel_rows` uses whichever spelling the installed Pillow has. Both return the same tuples,
which is what makes one name enough — and the floor stays where it is, because 3.9 is supported and
Pillow 12 does not install there.

**Both defects were found by the 3.9 matrix entries**, which had been red. The second was hidden behind
the first: only fixing the accessor revealed that `tomllib` was next.

## The sdist shipped a test directory that could not run

Without a `MANIFEST.in`, the sdist carried `test/test_ichiwatashi.py` and nothing else from that
directory. So `python -m unittest discover -s test -t .` failed there with *Start directory is not
importable* — there was no `__init__.py` — and the one fixture the colour-difference test reads was
missing as well. **A file that looks like a test suite and cannot run is the same shape as a wheel that
looked installed and could not find its own font.**

The sdist carries the whole test directory now, and running the suite from an *unpacked sdist* is part
of what was verified: 239 tests, two skipping. The second skip is the corpus ledger —
`corpus/` is repository evidence and stays out of the sdist on purpose, which is the choice the sibling
tool made too, so the test skips instead of failing over a packaging decision.

## The workflows are pinned now

Both workflow files referenced actions by tag — `@v4`, `@v5`, `@release/v1`. A tag is a movable pointer:
an upstream retag changes what the workflow runs, without anything in this repository changing. Commit
SHAs are pinned here, the same ones the two sibling repositories use, so the family runs the same
actions and a bump is a visible edit.

## Behaviour did not change, and this is still a release

Nothing in the installed package behaves differently. But the sdist ships the test suite, and a test
that fails on an interpreter the metadata claims to support is a defect in the artifact. PyPI does not
accept a replacement file, so the only honest fix is a new version.

## Testing

**239 tests**, green on Windows (1 skipped) and on Linux (5 skipped) both before and after these
changes, and the three Python 3.9 CI entries pass for the first time since the suite grew past what
that interpreter's Pillow offers.
