"""Measure the TH155 reference bucket, and add the one metric the corpus never recorded.

`corpus/manifest.jsonl` has no `largest_cluster_rate`, because `tools/corpus.py` was written before
the bucketed reference needed it. Re-measuring the sprites is cheap and is the only honest way to
get the number -- so this does that, prints the percentiles that go into `calibration.py`, and says
which metric it can NOT supply and why.
"""
import io
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ichiwatashi.judge import judge  # noqa: E402
from PIL import Image  # noqa: E402

SPRITES = Path(r"E:\DaShaoHuo\downloads\ichiwatashi-corpus\th155")
MANIFEST = Path("corpus/manifest.jsonl")

BUCKET_METRICS = ("bbox_fill", "isolated_rate", "largest_cluster_rate",
                  "outline_predictability")


def pct(v, p):
    s = sorted(v)
    return s[min(len(s) - 1, int(len(s) * p))]


rows = []
for p in sorted(SPRITES.glob("*.png")):
    with Image.open(p) as im:
        rows.append(judge(im.convert("RGBA")))
print("measured %d sprites from %s" % (len(rows), SPRITES))

print()
print("=== TH155 bucket: percentiles for the generation-keyed reference ===")
print("%-24s %8s %8s %8s %8s %8s" % ("metric", "p05", "p25", "median", "p75", "p95"))
out = {}
for m in BUCKET_METRICS:
    v = [getattr(r, m) for r in rows]
    out[m] = (pct(v, .05), pct(v, .25), pct(v, .5), pct(v, .75), pct(v, .95))
    print("%-24s %8.3f %8.3f %8.3f %8.3f %8.3f" % ((m,) + out[m]))

print()
print("=== and the one this bucket cannot supply ===")
print("colours_used: median %.1f here, but it is not stable on this generation -- 92.5%% of sprites"
      % pct([float(r.colours_used) for r in rows], .5))
print("  change value when decoded with a different palette from the same character's set, with a")
print("  median spread of 27 on a median of 44.5. A threshold derived from one palette per sprite")
print("  would be a threshold derived from an arbitrary choice, so it is left out of the bucket.")

print()
print("=== corpus: add the metric the manifest never recorded ===")
records = [json.loads(x) for x in io.open(MANIFEST, encoding="utf-8") if x.strip()]
by_name = {}
for rec in records:
    by_name[rec["path_hint"]] = rec
updated = 0
for p, r in zip(sorted(SPRITES.glob("*.png")), rows):
    rec = by_name.get(p.name)
    if rec is None:
        continue
    if "largest_cluster_rate" not in rec:
        rec["largest_cluster_rate"] = round(r.largest_cluster_rate, 4)
        updated += 1
if updated:
    with io.open(MANIFEST, "w", encoding="utf-8", newline="\n") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
print("added largest_cluster_rate to %d records" % updated)
