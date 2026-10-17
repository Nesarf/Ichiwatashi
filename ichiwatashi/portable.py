# -*- coding: utf-8 -*-
"""The panel as portable data, so a tool written in another language can draw the same one.

**Why this exists.** NTVI assigns this repository the shared pixel layer and the other three tools embed it.
Two of them (Nanodesu, Torikago) are Python; **Volcano Separator is PowerShell and Node** -- so "embed" cannot
mean `import`, and it must not mean a runtime dependency either, which is the rule the family already settled:
**source is shared, dependency is not.**

What can cross all three boundaries is data. So `export()` writes a panel's measurements, roles, characters and
colours as JSON, and `verify()` checks a rendering against that file -- which gives an embedder something to be
wrong *against* rather than something to be trusted.

**The file carries its own checksum**, over the canonical JSON of everything except the checksum itself, so an
embedder can tell "I read this file" from "I read a different file with the same name".
"""
from __future__ import annotations

import json

from . import panel as Pn

__all__ = ["FORMAT", "export", "load", "verify", "canonical"]

#: Bumped when the meaning of a field changes. **A reader can refuse a version it does not know**, which is
#: what keeps four repositories from disagreeing silently about what `close` means.
FORMAT = "ichiwatashi.panel/1"


def canonical(obj):
    """The JSON text that the checksum covers: sorted keys, no spaces, no non-ASCII escaping.

    **Canonical rather than "whatever `json.dumps` gives"**, because the checksum has to be reproducible by a
    reader in another language -- and key order and spacing are exactly the things two JSON writers disagree
    about.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def export(tier_name="normal", *, spec=None, title=None, active=True, width=None, height=None):
    """A panel described as plain data, ready to be written to a file and read elsewhere.

    Includes **both** colour and character per role, because the embedders differ: a window renderer needs
    RGB, a terminal or a log needs one character per pixel. Neither is optional -- an embedder that has to
    invent one of them has stopped sharing a layer and started writing its own.
    """
    base, tw, th = Pn.tier(tier_name)
    spec = base if spec is None else spec
    w = tw if width is None else width
    h = th if height is None else height
    where = Pn.layout(spec, w, h)
    from . import terminal as T

    body = {
        "format": FORMAT,
        "tier": tier_name,
        "size": [w, h],
        "spec": {"border": spec.border, "title_h": spec.title_h, "pad": spec.pad,
                 "bevel": spec.bevel, "close": spec.close},
        "layout": {k: list(v) if isinstance(v, tuple) else v
                   for k, v in where.items() if not k.startswith("_")},
        "close_pixels": sorted([list(p) for p in where.get("_close_px", set())]),
        "title": title,
        "title_room": list(Pn.title_room(spec, where)),
        "active": active,
        "roles": list(Pn.PANEL_ROLES),
        # **`keys` maps a role to the key a renderer holds, and everything else is keyed by that key.** An
        # embedder reads one table and gets the colour and the character for the same index; the first version
        # keyed `colours` by key and `chars` by role name, so a reader had to know which was which -- and the
        # tests caught it, not a reader.
        "keys": dict(Pn.PANEL_KEYS),
        "colours": {k: list(v) for k, v in Pn.PANEL_PALETTE.items()},
        "chars": {Pn.PANEL_KEYS[r]: T.CHARS[r] for r in Pn.PANEL_ROLES},
        # `title_text` has no single character -- its glyphs are drawn as themselves -- so a reader that finds
        # `null` here knows to draw the font rather than a mark
        "chars_note": "null means the role is drawn as font glyphs, not as one character",
    }
    body["checksum"] = _checksum(body)
    return body


def _checksum(body):
    import hashlib

    payload = {k: v for k, v in body.items() if k != "checksum"}
    return hashlib.sha256(canonical(payload).encode("utf-8")).hexdigest()


def load(path):
    """Read an exported panel and refuse it if the format is unknown or the checksum disagrees."""
    with open(path, encoding="utf-8") as fh:
        body = json.load(fh)
    if body.get("format") != FORMAT:
        raise ValueError("%s has format %r, this build speaks %r"
                         % (path, body.get("format"), FORMAT))
    want = body.get("checksum")
    got = _checksum(body)
    if want != got:
        # **the checksum is what makes this a shared fact rather than a file with a familiar name**
        raise ValueError("%s does not match its own checksum (file says %s, content is %s)"
                         % (path, want, got))
    return body


def verify(spec, canvas, *, body, title=None):
    """Check a rendering against an exported panel, **rather than against this build's tables.**

    The point of the file is that another tool can be wrong against it. So this compares a `builder.Canvas`
    to the roles, keys and layout *in the file* -- if this repository's tables have moved on since the export,
    the check says so instead of silently passing.
    """
    if isinstance(body, str):
        body = load(body)
    if body["format"] != FORMAT:
        raise ValueError("unknown format %r" % (body["format"],))
    if list(body["size"]) != [canvas.width, canvas.height]:
        return [(-1, -1, "size", "%dx%d, file says %s"
                 % (canvas.width, canvas.height, body["size"]))]
    if body.get("checksum") != _checksum(body):
        return [(-1, -1, "checksum", "the file has been edited since it was exported")]
    keys = body["keys"]
    where = body["layout"]
    close_px = {(p[0], p[1]) for p in body["close_pixels"]}
    spec_obj = Pn.PanelSpec(**body["spec"])
    problems = []
    skip = None
    if title:
        start, _room = body["title_room"]
        from . import figures as FIG

        skip = (start, where["title"][1] + 1, start + FIG.text_width(title),
                where["title"][1] + 1 + 7)
    for y in range(canvas.height):
        for x in range(canvas.width):
            role = Pn._role_at(spec_obj, {"title": tuple(where["title"]), "well": tuple(where["well"]),
                                          "content": tuple(where["content"]), "frame": tuple(where["frame"]),
                                          "close": tuple(where["close"]) if where.get("close") else None,
                                          "_close_px": close_px},
                               x, y, active=body["active"])
            if role is None:
                continue
            if skip and skip[0] <= x < skip[2] and skip[1] <= y < skip[3]:
                continue
            want = keys[role]
            got = canvas.get(x, y)
            if got != want:
                problems.append((x, y, role, got))
    return problems
