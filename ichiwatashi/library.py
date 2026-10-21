# -*- coding: utf-8 -*-
"""A folder of parts, and which drawings use which -- the inventory a construction tool needs.

**Why this is a command and not a convention in the README.** A folder of parts drifts in three ways that no
single file can show: a part nobody uses any more, a script naming a part that was renamed, and two parts
that have grown into the same shape. The first two are checkable from the files alone, so they are checked;
the third is not, and is not claimed.

The distinction the scan rests on is the one the script format already makes: **a drawing declares a
palette, a part does not.** A part is placed onto a canvas and borrows that canvas's keys, so its file has
`width`, `height` and `steps` and no palette -- which is exactly what separates the two kinds of JSON in one
folder without a naming convention nobody would keep.
"""
from __future__ import annotations

import json
from pathlib import Path

__all__ = ["scan", "describe"]


def _load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def scan(directory):
    """Every shape script in `directory`, split into parts and drawings, with the references resolved.

    Files that are not readable JSON objects with `width`, `height` and `steps` are listed as ignored rather
    than guessed at: a folder of parts is also a folder of whatever else the person keeps there.
    """
    root = Path(directory)
    if not root.is_dir():
        raise ValueError("not a directory: %s" % root)

    parts, scripts, ignored = [], [], []
    for path in sorted(root.glob("*.json")):
        spec = _load(path)
        if not isinstance(spec, dict) or not {"width", "height", "steps"} <= set(spec):
            ignored.append(path.name)
            continue
        entry = {
            "name": path.name,
            "path": path,
            "width": spec.get("width"),
            "height": spec.get("height"),
            "keys": sorted((spec.get("palette") or {}).keys()),
            "uses": [],
        }
        for step in spec.get("steps") or []:
            if isinstance(step, dict) and step.get("op") == "part" and isinstance(step.get("file"), str):
                entry["uses"].append((path.parent / step["file"]).resolve())
        if "palette" in spec:
            scripts.append(entry)
        else:
            parts.append(entry)

    by_path = {p["path"].resolve(): p for p in parts}
    used_paths = set()
    missing = []
    for script in scripts:
        for target in script["uses"]:
            if target in by_path:
                used_paths.add(target)
            else:
                missing.append((script["name"], target.name))
    orphans = [p["name"] for p in parts if p["path"].resolve() not in used_paths]
    return {"root": root, "parts": parts, "scripts": scripts, "ignored": ignored,
            "orphans": orphans, "missing": missing}


def describe(result, *, path_of=None):
    """The scan as lines. `path_of` keeps a caller from printing absolute paths it did not ask for."""
    def shown(entry):
        return path_of(entry["path"]) if path_of else entry["name"]

    used_by = {}
    for script in result["scripts"]:
        for target in script["uses"]:
            used_by.setdefault(target, []).append(script["name"])

    out = ["%s: %d part(s), %d drawing(s), %d ignored"
           % (result["root"], len(result["parts"]), len(result["scripts"]), len(result["ignored"]))]
    for part in result["parts"]:
        users = used_by.get(part["path"].resolve(), [])
        state = ", ".join(users) if users else "not used by any drawing here"
        out.append("  part    %-22s %dx%d  keys %s  %s"
                   % (shown(part), part["width"], part["height"],
                      ", ".join(part["keys"]) or "-", state))
    for script in result["scripts"]:
        names = [t.name for t in script["uses"]]
        out.append("  draw    %-22s %dx%d  places %s"
                   % (shown(script), script["width"], script["height"], ", ".join(names) or "nothing"))
    for script_name, target in result["missing"]:
        out.append("  MISSING %s is named by %s and is not in this folder" % (target, script_name))
    if result["ignored"]:
        out.append("  ignored %s" % ", ".join(result["ignored"]))
    return "\n".join(out)
