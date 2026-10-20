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


#: The two Python readers are separate copies **on purpose** -- embedded, never imported, so each tree runs
#: without the other existing. The data check above says both trees embed one layout; it says nothing about
#: whether both *readers* still draw that layout the same way. That is the one thing which can drift while
#: every tree's own suite stays green, and it has already happened once: a case-folding defect lived in both
#: copies for a while, and no test in either tree could see it -- it was found by reading, not by running.
READERS = {
    "torikago": "triage",
    "nanodesu": "nanodesu-release",
}

#: The same question for every reader: mixed case, an indent, a tab the font may not hold, and enough lines to
#: reach a second page so the page marker is compared too. **Written down rather than derived**, because the
#: point is that two implementations are asked one question -- a question that moved with the data would not be
#: one question.
PROBE_TITLE = "SHARED LAYOUT"
PROBE_LINES = ["report line one", "  indented line two", "MiXeD case and a tab\there", "last line"]
PROBE_PAGES = ["line %d" % i for i in range(60)]


def _reader(name, path):
    """Load one reader by path. They share a module name, so each gets a distinct one here."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("embed_%s" % name.replace("-", "_"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def compare_renderings(root):
    """Ask every Python reader for the same picture and compare the bytes. Returns problems.

    Two renderings are compared because they fail differently: the **character** form needs no image library,
    so a machine without one can still tell whether the readers agree; the **image** form is what a person
    actually sees, and it is the only way to catch a divergence in colour, in the marker's placement, or in the
    integer upscale.
    """
    problems, texts, images, notes = [], {}, {}, []
    layout_path = root / "triage" / ("panel.json")
    font_path = root / "triage" / ("font.json")
    for name, tree in READERS.items():
        path = root / tree / "panel_window.py"
        if not path.is_file():
            problems.append("%s: no reader at %s" % (name, path))
            continue
        try:
            mod = _reader(name, path)
            layout = mod.load(layout_path)
            draw = mod.load_font(font_path)
        except (OSError, ValueError, ImportError) as exc:
            problems.append("%s: its reader could not load the shared files (%s)" % (name, exc))
            continue
        try:
            plain = mod.text(layout, PROBE_LINES, title=PROBE_TITLE)
            paged = mod.text(layout, PROBE_PAGES, title=PROBE_TITLE, page=1)
        except ValueError as exc:
            problems.append("%s: it refused text this build accepts (%s)" % (name, exc))
            continue
        texts[name] = _sha("\n".join(plain + paged))
        try:
            first = mod.image(layout, PROBE_LINES, title=PROBE_TITLE, scale=2, draw_fn=draw)
            second = mod.image(layout, PROBE_PAGES, title=PROBE_TITLE, scale=2, draw_fn=draw, page=1)
        except ImportError:
            notes.append("%s: no image library here, so its pixels could not be compared" % name)
            continue
        images[name] = hashlib.sha256(first.tobytes() + second.tobytes()).hexdigest()

    for kind, seen in (("text", texts), ("image", images)):
        if len(seen) > 1 and len(set(seen.values())) > 1:
            problems.append("the two %s renderings are not identical: %s"
                            % (kind, "; ".join("%s gives %s" % (n, d[:8]) for n, d in seen.items())))
        for name, digest in seen.items():
            print("%-18s %-5s %s" % (name, kind, digest[:16]))
    for note in notes:
        print("  note: %s" % note)
    if not texts and not images:
        problems.append("no reader produced a rendering, so agreement was not tested")
    return problems


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
    print("renderings  (one layout, one text, every Python reader)")
    problems.extend(compare_renderings(root))

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
