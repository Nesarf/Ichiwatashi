"""`shade()` bands a shape by its own per-column extent. Right for upright forms, wrong for slanted
ones -- and the wrongness is more specific than "the bands are off".

The rule, from `builder.shade`: for each column of the region, the top `depth` pixels are lit and the
bottom `depth` are shadowed.

A band that runs along a form and keeps its width should keep a constant **perpendicular** thickness.
This rule fixes the **vertical** thickness instead, so the perpendicular thickness it produces is

    vertical thickness x length-factor = depth x sqrt(1 + slope^2)

which equals `depth` only where the edge is vertical. At 45 degrees it is 1.41 x depth; on the near
vertical flanks of a cone it is several times that. So the measurement is the perpendicular thickness
of the lit band, and the question is whether it is steady across the form or drifts with the slope.

The rectangle is the control: slope 0, so vertical and perpendicular must agree. If they disagree
there, the measurement is wrong rather than the rule.
"""
from __future__ import annotations

import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ichiwatashi.builder import Canvas  # noqa: E402


def band_thickness(canvas):
    """(mean vertical span of the lit band, edge length-factor, perpendicular thickness).

    Measured over the **middle rows only**. At the very top and bottom of a form each row's span is
    set by the silhouette rather than by the band -- the first version included them and read a disc
    as 2.83 wide, which was the outline being counted, not the band.
    """
    rows = canvas.rows()
    lo = len(rows) // 4
    hi = len(rows) - lo
    spans, left_edges = [], []
    for row in rows[lo:hi]:
        lit = [x for x, c in enumerate(row) if c == "l"]
        filled = [x for x, c in enumerate(row) if c in ("b", "l", "d")]
        if lit and filled:
            spans.append(len(lit))
            left_edges.append(min(filled))
    if len(spans) < 4:
        return None
    deltas = [left_edges[i + 1] - left_edges[i] for i in range(len(left_edges) - 1)]
    edge_slope = statistics.mean(deltas) if deltas else 0.0
    factor = (1 + edge_slope ** 2) ** 0.5
    vert = statistics.mean(spans)
    return vert, factor, vert / factor


def render(canvas, label):
    print(label)
    for row in canvas.rows():
        print("   " + "".join(row))
    print()


def build(kind, depth=1):
    if kind == "rectangle":
        c = Canvas(24, 16)
        c.rect(4, 2, 19, 13, key="b")
    elif kind == "cone":
        c = Canvas(28, 20)
        c.cone(2, 17, 2, 22, key="b")
    elif kind == "trapezoid":
        c = Canvas(28, 24)
        c.trap(2, 21, 20, 4, key="b")
    elif kind == "disc":
        c = Canvas(28, 20)
        c.disc(14, 10, 8, key="b")
    return c.shade({"b": "l"}, {"b": "d"}, depth=depth)


print("=== current output, two of the shapes ===")
for kind in ("rectangle", "cone"):
    render(build(kind), kind)

print("=== perpendicular thickness of the lit band ===")
print("%-12s %14s %12s %20s" % ("shape", "vertical mean", "length factor", "perpendicular mean"))
for kind in ("rectangle", "cone", "trapezoid", "disc"):
    r = band_thickness(build(kind))
    if r is None:
        print("%-12s %14s %12s %20s" % (kind, "-", "-", "too few rows"))
        continue
    vert, factor, perp = r
    print("%-12s %14.2f %12.2f %20.2f" % (kind, vert, factor, perp))

print()
print("The rule fixes the vertical count at `depth` for every column, so what it produces")
print("perpendicular to the edge is depth x length-factor. That is constant only where the edge is")
print("vertical: on a cone's near-vertical flank the band is several times wider than intended, and")
print("on a 45-degree slope it is 1.41x. A band meant to run along a form holds the perpendicular")
print("number steady and lets the vertical one vary, which is the opposite of what happens here.")
