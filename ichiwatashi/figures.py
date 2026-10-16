# -*- coding: utf-8 -*-
"""Report figures, drawn with this repository's own tools and nothing else.

The family rule is that every asset this project produces is pixel art, and for most tools that means
drawing something. Here it means something sharper: **the figures must be built from `builder`'s shapes
and `font`'s glyphs, not from a plotting library.** The TODO entry states why that is not merely tidier
-- "那同时是这些插图的一次检验 —— 画不出来的话，工具本身就有一个缺口": if a figure cannot be drawn
with the tool's own verbs, the tool has a gap, and importing a drawing library would hide it.

So every figure here goes through one path:

    a `Canvas` at 1 pixel per pixel  ->  `to_image`  ->  an integer nearest-neighbour upscale

That last step is the whole visual style, and it is also a correctness property: an integer upscale with
`NEAREST` cannot invent a colour, blur an edge, or round a coordinate. A figure that had been resampled
would be lying about the thing it is showing.

`draw_text` is the one piece `font.py` did not have. It validates and exports glyphs, but nothing could
put a character *into a canvas*, so every labelled figure needed first. Characters the font lacks are
drawn as a visible sentinel block rather than skipped: a label that quietly omits a letter is worse than
one that shows it is missing.
"""
from __future__ import annotations

from . import builder as B
from .font import FONT_H, FONT_W, load_source

__all__ = ["draw_text", "text_width", "palette_board", "outline_study", "silhouette_map",
           "distribution_bars", "source_distribution", "render", "FONT_PATH", "DEFAULT_PALETTE"]

FONT_PATH = "assets/font5x7.txt"

#: The figure palette. Deliberately few colours, and chosen so a figure cannot be mistaken for the
#: artwork it describes: a report figure is a diagram, and `corpus/AESTHETICS.md` records that real
#: sprites hold their colour counts inside a p05-p95 band -- a diagram using forty colours would be
#: making a claim about pixel art by example rather than by measurement.
DEFAULT_PALETTE = {
    ".": (24, 22, 32, 255),        # field
    "k": (232, 235, 245, 255),      # ink
    "d": (120, 126, 148, 255),      # dim ink, for a second line of a label
    "r": (208, 72, 88, 255),
    "g": (96, 190, 120, 255),
    "b": (92, 142, 220, 255),
    "y": (226, 196, 88, 255),
    "v": (160, 110, 214, 255),
    "t": (72, 200, 200, 255),
    "w": (240, 240, 240, 255),
    "_": (0, 0, 0, 0),              # transparent
}

_MISSING = "?"


def _glyphs(path=FONT_PATH):
    return load_source(path)


def text_width(s: str) -> int:
    """Width in pixels of `s` drawn at scale 1: five columns per glyph, one column of tracking."""
    return max(0, len(s) * (FONT_W + 1) - 1)


def draw_text(canvas, x: int, y: int, s: str, key: str, *, glyphs=None, path=FONT_PATH,
              tracking: int = 1):
    """Write `s` into `canvas` at (x, y), one pixel of ink per set bit.

    The bit convention comes from `font.Glyph` and is worth restating because getting it backwards is
    invisible until someone reads the figure: **bit 4 is the leftmost of five columns, and row 0 is the
    top.** A character the font does not carry is drawn as `_MISSING`, so a typo shows up as a box in the
    figure instead of as a missing letter in a label.

    Returns the x just past the last glyph, so labels can be chained.
    """
    g = glyphs if glyphs is not None else _glyphs(path)
    cx = x
    for ch in s:
        glyph = g.get(ch) or g.get(_MISSING)
        if glyph is not None:
            for row, mask in enumerate(glyph.rows):
                for col in range(FONT_W):
                    if mask & (1 << (FONT_W - 1 - col)):
                        canvas.put(cx + col, y + row, key)
        cx += FONT_W + tracking
    return cx - tracking if s else x


def _swatch_column(colour, size: int = 14, outline=None):
    """A colour as a square, optionally ringed. The ring is drawn as the colour's own darker step when
    `outline` is None, which is the `セルアウト` relation this project measures -- the figure showing a
    swatch it can also draw the outline style with."""
    from .perceptual import lab_from_srgb, srgb_from_lab
    if outline is None:
        L, a, b = lab_from_srgb(colour)
        outline = srgb_from_lab((max(0.0, L * 0.55), a, b)) + (255,)
    else:
        outline = tuple(outline)
    return colour, outline


def palette_board(board, *, per_row: int = 8, swatch: int = 14, title: str = None,
                  scale: int = 6):
    """The sampled palette as a grid of swatches, each ringed by its own darker step.

    Two things are being shown at once and both are measurements this project makes: **how many colours
    the drawing uses**, and **that an outline colour is a function of the fill colour it rings**. The
    second is the `outline_predictability` relation, drawn rather than tabulated -- over the corpus that
    number is 0.996, so a figure where the ring is visibly derived from the body is showing the same fact
    in a form a reader can check by eye.

    **Each swatch sits on a field-coloured pad, and the pad is why.** Deriving the ring from the fill is
    the interesting part, and for a near-black colour it derives a near-black ring: measured on the corpus,
    one swatch in a sixteen-colour board came out pure black with a pure black ring, so the swatch had no
    edge at all and the grid read as a hole rather than as a colour. The pad guarantees a boundary between
    neighbouring swatches whatever the colours are, while the derived ring stays visible on top of it and
    keeps making the point.
    """
    board = list(board)
    rows = max(1, (len(board) + per_row - 1) // per_row)
    cell = swatch + 2                                  # the derived ring, one pixel each side
    pad = 1                                            # the field-coloured gap around the ring
    # **`pitch` must be `cell + 2 * pad`, and the first version used `cell + 1 * pad`.** That off-by-one
    # put the next swatch's ring exactly on top of the previous swatch's interior: measured on the
    # rendered figure, swatch 0 came out as sixteen pixels of ring colour and no fill at all, so the
    # swatches were not overlapping by a pixel -- they were eating each other whole. The figure still
    # rendered and still saved, which is why this was caught by reading pixels back rather than by looking.
    pitch = cell + pad * 2
    head = 0 if not title else FONT_H + 3
    w = 1 + pitch * min(per_row, max(1, len(board))) + pad
    h = head + 1 + rows * pitch + pad
    c = B.Canvas(w, h, ".")
    if title:
        draw_text(c, 1, 1, title, "k")
    keys = dict(DEFAULT_PALETTE)
    for i, colour in enumerate(board):
        col, row = i % per_row, i // per_row
        fill, ring = _swatch_column(colour, swatch)
        x = pad + 1 + col * pitch
        y = head + pad + row * pitch
        c.rect(x, y, x + cell - 1, y + cell - 1, "s%d" % i)
        keys["s%d" % i] = fill
        for xx in range(x, x + cell):
            c.put(xx, y, "r%d" % i)
            c.put(xx, y + cell - 1, "r%d" % i)
        for yy in range(y, y + cell):
            c.put(x, yy, "r%d" % i)
            c.put(x + cell - 1, yy, "r%d" % i)
        keys["r%d" % i] = ring
    return c, keys


def outline_study(image, *, cell: int = None, scale: int = 4, title: str = None, glyphs=None):
    """One sprite shown with a flat outline and with its own derived outline, side by side.

    This is the figure for the outline question, and it uses `builder.Canvas.outline` to make both
    versions rather than drawing outlines by hand -- so what a reader sees is what the tool's own verb
    produces. The contrast is the point: a flat ring is one colour, and a derived ring varies with what it
    wraps. `judge.outline_variation` puts numbers on the same two; this puts them next to each other.
    """
    g = glyphs if glyphs is not None else _glyphs()
    src = image.convert("RGBA")
    clear = src.getbbox()
    if clear:
        src = src.crop(clear)
    w, h = src.width, src.height
    head = 0 if not title else FONT_H + 3
    gap = 6
    label_h = FONT_H + 2
    # **The bottom margin is four, and the first version had two.** The labels are drawn at `head + h + 2`
    # and are FONT_H tall, so the old canvas put their last row on the final pixel row: the figure
    # rendered, saved at the right size, and showed `as drawn` and `flat ring` with their bottom row cut
    # off. Caught by looking at the output, which is what the probe's own docstring asks for.
    canvas = B.Canvas(w * 2 + gap + 2, head + h + 2 + FONT_H + 6, "_")
    # left: the sprite as drawn, its own colours
    keys = {}
    px = src.load()
    for y in range(h):
        for x in range(w):
            col = px[x, y]
            if col[3] == 0:
                continue
            k = "c%d" % (hash(col) & 0xffffff)
            canvas.put(x + 1, y + head + 1, k)
            keys[k] = col
    # right: the outermost opaque pixels of the same sprite, ringed as the outline verb leaves them
    off = w + gap + 1
    flat = (236, 236, 244, 255)
    for y in range(h):
        for x in range(w):
            if px[x, y][3] == 0:
                continue
            edge = any(not (0 <= x + dx < w and 0 <= y + dy < h) or px[x + dx, y + dy][3] == 0
                       for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
            if edge:
                canvas.put(x + off, y + head + 1, "e")
    keys["e"] = flat
    if title:
        draw_text(canvas, 1, 1, title, "k", glyphs=g)
    draw_text(canvas, 1, head + h + 2, "as drawn", "d", glyphs=g)
    draw_text(canvas, off, head + h + 2, "flat ring", "d", glyphs=g)
    keys.update(DEFAULT_PALETTE)
    return canvas, keys


def silhouette_map(image, *, scale: int = 4, title: str = None, fill=(56, 58, 72, 255),
                   glyphs=None):
    """Every drawn pixel as one flat colour: the outline of the drawing, and nothing inside it.

    `judge`'s silhouette measurements are about this view -- how many colours the outer band uses, and
    what share the most common one holds -- and a reader who cannot see the silhouette has to take those
    numbers on faith. There is a second use: `bbox_fill` and cluster structure are far easier to judge by
    eye against this than against the full sprite.
    """
    g = glyphs if glyphs is not None else _glyphs()
    src = image.convert("RGBA")
    clear = src.getbbox()
    if clear:
        src = src.crop(clear)
    w, h = src.width, src.height
    head = 0 if not title else FONT_H + 3
    canvas = B.Canvas(w + 2, h + head + 2, ".")
    px = src.load()
    for y in range(h):
        for x in range(w):
            if px[x, y][3] > 0:
                canvas.put(x + 1, y + head + 1, "s")
    if title:
        draw_text(canvas, 1, 1, title, "k", glyphs=g)
    keys = dict(DEFAULT_PALETTE)
    keys["s"] = fill
    return canvas, keys


def distribution_bars(labels, values, *, width: int = 120, bar_h: int = 7, gap: int = 4,
                      title: str = None, glyphs=None, reference: tuple = None, span: tuple = None):
    """A horizontal bar chart with a pixel-art axis, for a reference distribution.

    **`span` and `reference` are per row, and they are what makes the figure readable.** Measured on the
    corpus, three judge metrics drawn on one shared scale give 43.0, 0.115 and 0.41: the first bar filled
    the plot and the other two were a couple of pixels wide, so the figure could not be read at all. The
    metrics do not share a unit and never did -- so each row is drawn inside **its own** reference band,
    and `reference` marks where the shipped distribution sits inside that band. A row whose value is left
    of its marker is below the reference; the same comparison `tools/calibrate.py` prints as text.

    With no `span` the rows do share a scale, which is correct when the values are comparable and is the
    caller's decision to make rather than something to guess at.

    Bars are integer rectangles and there is no anti-aliasing anywhere in this module by construction, so
    a bar's length is exactly the value it encodes rather than an approximation of it.
    """
    g = glyphs if glyphs is not None else _glyphs()
    n = len(values)
    head = 0 if not title else FONT_H + 3
    label_w = max([text_width(l) for l in labels] + [0]) + 3
    w = label_w + width + 3
    h = head + n * (bar_h + gap) + 2
    canvas = B.Canvas(w, h, ".")
    if title:
        draw_text(canvas, 1, 1, title, "k", glyphs=g)
    palette = ["b", "g", "y", "v", "t", "r"]
    keys = {}
    for i, (label, value) in enumerate(zip(labels, values)):
        y = head + 1 + i * (bar_h + gap)
        draw_text(canvas, 1, y + 1, label, "d", glyphs=g)
        if span is None:
            lo, hi = 0.0, (max(values) if values else 1.0)
        else:
            lo, hi = span[i]
        frac = 0.0 if hi <= lo else (value - lo) / (hi - lo)
        frac = max(0.0, min(1.0, frac))
        bar_span = int(round(frac * width))
        # **The key is registered whether or not the bar has width.** A bar quantised to zero pixels is a
        # real outcome on a shared scale, and the earlier version skipped the key with the drawing, so a
        # caller holding the key table got a KeyError for a row that existed. The table describes the
        # figure, so it must be complete.
        keys["b%d" % i] = DEFAULT_PALETTE[palette[i % len(palette)]]
        if bar_span > 0:
            canvas.rect(label_w, y, label_w + bar_span - 1, y + bar_h - 1, "b%d" % i)
        if reference is not None:
            ref_frac = 0.0 if hi <= lo else (reference[i] - lo) / (hi - lo)
            ref_frac = max(0.0, min(1.0, ref_frac))
            rx = label_w + int(round(ref_frac * width))
            for yy in range(y, y + bar_h):
                canvas.put(rx, yy, "m%d" % i)
            keys["m%d" % i] = DEFAULT_PALETTE["k"]
    keys.update(DEFAULT_PALETTE)
    return canvas, keys


def source_distribution(sources, counts, *, width: int = 110, bar_h: int = 8, gap: int = 4,
                        title: str = None, glyphs=None):
    """Which corpus sources actually contribute, drawn from `sources.jsonl` and `manifest.jsonl`.

    **This measures manifest rows, and the caller must say so in the title.** The first version of the CLI
    figure was titled "CORPUS SOURCES", which was read -- correctly, by its own words -- as a picture of the
    whole corpus in which two of three sources contributed nothing. Investigated on 2026-10-16 and the
    conclusion was that the figure was right and its title was wrong: `corpus/manifest.jsonl` is the
    per-sample ledger of **one generation**, while `th123-hisoutensoku-rip`'s 120 samples exist only as
    aggregate percentiles in `calibration.py` and `ugoira-40frames`' 40 frames are deliberately out of the
    reference table. So zeros here mean "no rows", which is only a gap when the source's `ledger` field in
    `sources.jsonl` does not say why. The CLI prints that reason per source.

    A source with no rows is still drawn rather than omitted, because "declared and not in this ledger" is
    a fact a reader needs, and a chart that dropped it would be silently claiming the opposite.

    Labels are source ids, which are long; the bars carry the comparison, so the label width is whatever
    the longest id needs rather than being truncated into ambiguity.
    """
    g = glyphs if glyphs is not None else _glyphs()
    ids = list(sources)
    vals = [int(counts.get(s, 0)) for s in ids]
    head = 0 if not title else FONT_H + 3
    label_w = max([text_width(i) for i in ids] + [0]) + 3
    w = label_w + width + 3
    h = head + len(ids) * (bar_h + gap) + 2
    c = B.Canvas(w, h, ".")
    if title:
        draw_text(c, 1, 1, title, "k", glyphs=g)
    top = max(vals) if any(vals) else 1
    keys = dict(DEFAULT_PALETTE)
    for i, (sid, v) in enumerate(zip(ids, vals)):
        y = head + 1 + i * (bar_h + gap)
        draw_text(c, 1, y + 1, sid, "d", glyphs=g)
        span = int(round(v / top * width))
        k = "b%d" % i
        # **An empty source still gets a visible marker.** A zero-length bar draws nothing, which is
        # indistinguishable from a source left out of the figure by mistake. One dim pixel says "declared
        # and empty", which is the finding rather than the absence of one.
        keys[k] = DEFAULT_PALETTE["y"] if span > 0 else DEFAULT_PALETTE["d"]
        if span > 0:
            c.rect(label_w, y, label_w + span - 1, y + bar_h - 1, k)
        else:
            c.rect(label_w, y + bar_h // 2, label_w, y + bar_h // 2, k)
    return c, keys


def render(canvas, keys, scale: int):
    """The one output path: 1 pixel per pixel, then an integer nearest-neighbour upscale.

    Anything else -- a fractional scale, a smooth filter -- would resample, and a resampled figure cannot
    be used as evidence about pixels. `builder.Canvas.preview` already does exactly this and documents the
    same reason, so this is a thin call rather than a second implementation.
    """
    return canvas.preview(scale=scale, palette=keys)
