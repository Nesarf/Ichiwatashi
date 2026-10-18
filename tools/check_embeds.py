# -*- coding: utf-8 -*-
"""Check that every tool embedding the shared pixel layer embeds the *same* one.

The family rule is that Ichiwatashi produces the shared layer once and each tool embeds the output, so
that run time stays self-contained. That rule has a failure mode with no natural detector: the copies
drift. Three trees embedding three slightly different panels would still each render a frame that looks
right, and nothing would be red -- one of them simply would not be the layout anybody agreed on.

This walks the embedding sites on this machine and answers two questions per site:

  1. does the file match this build of Ichiwatashi, pixel for pixel?
  2. is its checksum the same as the other sites'?

**A site that answers yes to the first and no to the second is the interesting case.** That is what a
title baked into the export looks like: the layout is identical, so each site verifies against this
build, and yet the files differ -- which is why the exported panel carries no title. The layout is
shared; the words in the bar are each tool's own, passed at render time.

Run:
    python tools/check_embeds.py
    python tools/check_embeds.py --root D:/another/checkout

Exit code 0 when every site agrees, 1 when one does not, 2 when no site was found at all -- the last
one matters, because "nothing to check" is not the same answer as "everything matches".
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

#: Where each embedding site keeps its two files, relative to the checkout root. **Written down rather
#: than discovered**, because a search would also find the source and the build directory and then
#: report agreement between a file and itself.
SITES = {
    "torikago": ("triage", "panel.json", "font.json"),
    "nanodesu": ("nanodesu-release", "panel.json", "font.json"),
    "volcano-separator": ("../volcano-separator/bin", "panel.json", None),
}


def checksum_of(path: Path) -> str:
    """The canonical JSON a reader hashes: sorted keys, no spaces, no ASCII escaping.

    That is the definition both readers use, and it is what makes a file that was re-indented -- or
    checked out with different line endings -- still the same layout.
    """
    from ichiwatashi import portable as Pt

    body = json.loads(path.read_text(encoding="utf-8"))
    return Pt.canonical({k: v for k, v in body.items() if k != "checksum"})


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def verify_panel(path: Path) -> tuple:
    """(matches this build, body, why). **A file whose checksum disagrees is a finding, not a crash.**

    `portable.load` raises on a bad checksum, which is right for a reader and wrong for a checker that
    is supposed to report on several sites and keep going.
    """
    from ichiwatashi import panel as Pn
    from ichiwatashi import portable as Pt

    try:
        body = Pt.load(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return False, None, str(exc)
    width, height = body["size"]
    spec = Pn.PanelSpec(**body["spec"])
    canvas = Pn.draw(spec, width, height, keys=Pn.PANEL_KEYS, title=body.get("title"),
                     active=body.get("active", True))
    bad = Pt.verify(spec, canvas, body=body, title=body.get("title"))
    return not bad, body, ("%d pixel(s) disagree with this build" % len(bad)) if bad else ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="does every consumer embed the same shared layer?")
    ap.add_argument("--root", default=str(HERE.parent),
                    help="the directory holding the sibling checkouts (default: the one above this one)")
    a = ap.parse_args(argv)
    root = Path(a.root)

    from ichiwatashi import font as F

    source = Path(__file__).resolve().parent.parent / "ichiwatashi" / "assets" / "font5x7.txt"
    source_glyphs = F.load_source(source)
    print("source  : %d glyph(s) from %s" % (len(source_glyphs), source.name))
    print()

    seen_panel, seen_font = {}, {}
    problems, checked = [], 0
    for name, (relative, panel_name, font_name) in SITES.items():
        base = root / relative
        panel = (base / panel_name)
        if not panel.is_file():
            print("%-18s no panel at %s" % (name, panel))
            continue
        checked += 1
        ok, body, why = verify_panel(panel)
        if body is None:
            print("%-18s panel UNREADABLE: %s" % (name, why))
            problems.append("%s: its panel could not be read (%s)" % (name, why))
            continue
        seen_panel.setdefault(_sha(checksum_of(panel)), []).append(name)
        print("%-18s panel %s  %d x %d  checksum %s" % (
            name, "matches this build" if ok else "DOES NOT MATCH THIS BUILD",
            body["size"][0], body["size"][1], body["checksum"][:16]))
        if not ok:
            problems.append("%s: %s" % (name, why))
        if body.get("title") is not None:
            # Not a failure on its own, but it is what makes two sites' checksums differ.
            problems.append("%s: the export carries a title (%r), so its copy can never match another "
                            "site's" % (name, body["title"]))
        if font_name:
            font_path = base / font_name
            if not font_path.is_file():
                problems.append("%s: no font at %s" % (name, font_path))
                continue
            try:
                font_body = json.loads(font_path.read_text(encoding="utf-8"))
                font_digest = _sha(checksum_of(font_path))
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                print("%-18s font  UNREADABLE: %s" % ("", exc))
                problems.append("%s: its font could not be read (%s)" % (name, exc))
                continue
            count = len(font_body["glyphs"])
            seen_font.setdefault(font_digest, []).append(name)
            print("%-18s font  %d glyph(s)  checksum %s" % ("", count, font_body["checksum"][:16]))
            if count != len(source_glyphs):
                problems.append("%s: its font holds %d glyph(s), the source has %d"
                                % (name, count, len(source_glyphs)))

    print()
    if checked == 0:
        print("no embedding site was found under %s -- that is not the same answer as agreement" % root)
        return 2
    for kind, seen in (("panel", seen_panel), ("font", seen_font)):
        if len(seen) > 1:
            problems.append("the %s copies are not identical: %s"
                            % (kind, "; ".join("%s in %s" % (digest[:8], ", ".join(names))
                                               for digest, names in seen.items())))
    if problems:
        for p in problems:
            print("PROBLEM: %s" % p)
        return 1
    print("%d site(s) embed the same panel and the same font, and both match this build" % checked)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
