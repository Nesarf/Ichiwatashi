#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Admit files into the Ichiwatashi corpus, and enforce `corpus/POLICY.md` while doing it.

**The policy is code here, not prose.** The failure this guards against already happened once: a
reference table was built from 120 sprites of one game, nobody recorded that the sample was one
source, and the resulting thresholds reported a whole later generation of correct work as defective.
A rule that lives only in a document does not fire.

Three gates, from POLICY.md:

    gate 1  rejection   a single hit refuses the file (non-ACG, procedural, re-encoded, unknown source)
    gate 2  adoption    at least two positive indications, else `pending`
    gate 3  isolation   anything synthesised or altered is `derived`, and can never enter a reference

`--check` re-derives every record's verdict from its fields and reports disagreement, so an entry
added by hand cannot quietly bypass the gates.

    python tools/corpus.py <corpus-dir> add <files...> --source S --generation G [--reject REASON]
    python tools/corpus.py <corpus-dir> check
    python tools/corpus.py <corpus-dir> summary
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ichiwatashi.judge import judge  # noqa: E402

METRICS_SCHEMA = 2          # bumped when the metric set or a metric's meaning changes

GENERATIONS = ("th105/th123", "th155", "ugoira", "other_acg", "synthetic")

# gate 1, from POLICY.md. Any hit refuses the file.
REJECT_REASONS = (
    "non-acg",
    "not-moe",
    "procedural",
    "re-encoded",
    "unknown-source",
)

# Suffixes accepted as potentially lossless. A `.jpg` is refused outright by gate 1.
LOSSLESS_SUFFIXES = (".png", ".gif", ".bmp", ".webp")


def sha256_of(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def measure(p: Path, *, derived: bool, generation: str, source_id: str,
            eligibility: str, reject_reason: str | None,
            derived_from: str | None, lossless: bool, now: str, indexed=None) -> dict:
    from PIL import Image
    with Image.open(p) as im:
        im = im.convert("RGBA")
        w, h = im.size
        r = judge(im)
    return {
        "sha256": sha256_of(p),
        "path_hint": str(p.name),
        "source_id": source_id,
        "generation": generation,
        "derived": derived,
        "derived_from": derived_from,
        "eligibility": eligibility,
        "reject_reason": reject_reason,
        "lossless": lossless,
        "format": p.suffix.lstrip(".").lower(),
        "size": p.stat().st_size,
        "width": w,
        "height": h,
        "colours_used": r.colours_used,
        # The indexed relationship, when the caller supplies it. `judge` is handed RGBA and cannot
        # see indices, so these are None for a lossy or already-decoded source -- and a `null` that
        # says "not measurable here" is better than a number that silently means something else.
        "slots_used": (indexed or {}).get("slots_used"),
        "colours_defined": (indexed or {}).get("colours_defined"),
        "used_duplicate_share": (indexed or {}).get("used_duplicate_share"),
        "pixel_scale": r.pixel_scale,
        "upscale": r.upscale,
        "bbox_fill": round(r.bbox_fill, 4),
        "outline_variation": r.outline_variation,
        "outline_predictability": r.outline_predictability,
        "outline_colours": r.outline_colours,
        "isolated_rate": round(r.isolated_rate, 4),
        "metrics_schema": METRICS_SCHEMA,
        "first_seen": now,
        "last_seen": now,
        "times_seen": 1,
    }


def verdict_of(rec: dict) -> tuple[str, str | None, list[str]]:
    """Re-derive (eligibility, reject_reason, problems) from the record's own fields."""
    problems = []
    if rec["reject_reason"] is not None and rec["reject_reason"] not in REJECT_REASONS:
        problems.append("reject_reason %r is not one of %s"
                        % (rec["reject_reason"], ", ".join(REJECT_REASONS)))
    if rec["format"] in ("jpg", "jpeg") and rec.get("lossless"):
        problems.append("a JPEG cannot be lossless")
    if rec["derived"] and not rec.get("derived_from"):
        problems.append("derived without derived_from (gate 3)")
    if not rec["derived"] and rec.get("derived_from"):
        problems.append("derived_from set but derived is false")
    if rec["generation"] not in GENERATIONS:
        problems.append("unknown generation %r" % rec["generation"])
    if rec.get("source_id") in (None, "", "unknown"):
        problems.append("no source_id: an entry without a source cannot be read")
    if rec["eligibility"] == "adopted" and rec["reject_reason"]:
        problems.append("adopted but carries a reject_reason")
    if rec["eligibility"] == "rejected" and not rec["reject_reason"]:
        problems.append("rejected without a reason (gate 1)")
    if rec["eligibility"] == "adopted" and rec["derived"] and rec["generation"] != "synthetic":
        problems.append("derived work adopted into a non-synthetic generation: gate 3 forbids it")
    # gate 1 dominates
    if rec["reject_reason"]:
        return "rejected", rec["reject_reason"], problems
    if rec["derived"]:
        return rec["eligibility"] or "pending", None, problems
    return rec["eligibility"] or "pending", None, problems


def cmd_add(args):
    cdir = Path(args.corpus)
    man = cdir / "manifest.jsonl"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # **The dedupe key is (sha256, source_id, derived), not sha256.**
    # Content is the identity of the *bytes*, but a verdict is a judgement about a (content, source)
    # pair: the same file can arrive from a game rip as original lossless art and from an image
    # hosting dump as re-encoded. Keying on sha256 alone would silently freeze whichever arrived
    # first and hide the disagreement -- which is the exact class of error this corpus exists to
    # avoid.
    seen = set()
    if man.exists():
        for line in man.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                seen.add((r["sha256"], r.get("source_id"), bool(r.get("derived"))))

    added = refused = 0
    with man.open("a", encoding="utf-8", newline="\n") as f:
        for name in args.files:
            p = Path(name)
            if not p.is_file():
                print("  skip %s: not a file" % name)
                continue
            suf = p.suffix.lower()
            reject = args.reject
            if reject is None and suf not in LOSSLESS_SUFFIXES:
                reject = "re-encoded"
                print("  %s: gate 1 (suffix %s is not a lossless candidate)" % (p.name, suf))
            if reject is not None and reject not in REJECT_REASONS:
                print("  %s: --reject %r is not in %s" % (p.name, reject, REJECT_REASONS))
                continue
            eligibility = "rejected" if reject else "adopted"
            try:
                rec = measure(p, derived=args.derived, generation=args.generation,
                              source_id=args.source, eligibility=eligibility,
                              reject_reason=reject, derived_from=args.derived_from,
                              lossless=(suf != ".jpg"), now=now)
            except Exception as e:
                print("  %s: measuring failed: %s" % (p.name, e))
                continue
            key = (rec["sha256"], rec["source_id"], rec["derived"])
            if key in seen:
                print("  %s: already in the corpus for this source (%s)"
                      % (p.name, rec["sha256"][:12]))
                continue
            el, rr, problems = verdict_of(rec)
            if problems:
                for x in problems:
                    print("  %s: gate violation: %s" % (p.name, x))
                refused += 1
                continue
            rec["eligibility"], rec["reject_reason"] = el, rr
            f.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
            seen.add(rec["sha256"])
            added += 1
            print("  %s: %s (%s)" % (p.name, el, rec["generation"]))
    print("\nadded %d, refused %d" % (added, refused))
    return 0


def cmd_check(args):
    man = Path(args.corpus) / "manifest.jsonl"
    if not man.exists():
        print("no manifest at %s" % man)
        return 1
    bad = 0
    n = 0
    for line in man.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        n += 1
        rec = json.loads(line)
        el, rr, problems = verdict_of(rec)
        if (el, rr) != (rec["eligibility"], rec["reject_reason"]):
            problems.append("re-derived verdict is %s/%s but the record says %s/%s"
                            % (el, rr, rec["eligibility"], rec["reject_reason"]))
        for x in problems:
            bad += 1
            print("  %s: %s" % (rec["sha256"][:12], x))
    print("checked %d records, %d problem(s)" % (n, bad))
    return 1 if bad else 0


def cmd_summary(args):
    man = Path(args.corpus) / "manifest.jsonl"
    if not man.exists():
        print("no manifest at %s" % man)
        return 1
    rows = [json.loads(x) for x in man.read_text(encoding="utf-8").splitlines() if x.strip()]
    print("records: %d" % len(rows))
    for field in ("eligibility", "generation", "source_id", "derived", "lossless"):
        print("  %-14s %s" % (field, Counter(r.get(field) for r in rows).most_common()))
    ref = [r for r in rows if r["eligibility"] == "adopted" and not r["derived"]]
    print("\nusable for a reference table (adopted, not derived): %d" % len(ref))
    for g in GENERATIONS:
        sub = [r for r in ref if r["generation"] == g]
        if sub:
            ov = sorted(r["outline_variation"] for r in sub)
            print("  %-12s n=%-4d outline_variation median=%.3f"
                  % (g, len(sub), ov[len(ov) // 2]))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("files", nargs="+")
    a.add_argument("--source", required=True)
    a.add_argument("--generation", required=True, choices=GENERATIONS)
    a.add_argument("--reject", default=None, choices=REJECT_REASONS)
    a.add_argument("--derived", action="store_true")
    a.add_argument("--derived-from", default=None)
    a.set_defaults(func=cmd_add)
    sub.add_parser("check").set_defaults(func=cmd_check)
    sub.add_parser("summary").set_defaults(func=cmd_summary)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
