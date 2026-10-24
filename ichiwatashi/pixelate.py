# -*- coding: utf-8 -*-
"""Turning a drawing into a pixel drawing: downsample by majority, then cut the palette.

**Why the downsampling is a majority vote and not an average.** An average produces colours that are not in
the source -- an eyebrow against skin becomes a dozen intermediate browns -- and a pixel drawing is defined
by having few colours that each mean something. Taking the most common colour of each block keeps a hard
edge hard and keeps every colour one the original actually used. Measured on the reference set: the same
image downsampled by averaging, then quantised, produced a face whose eyelashes had merged into the cheek.

**Why the palette is cut afterwards rather than during.** A drawing has an unbounded number of distinct
colours once it has been through a JPEG, so the count that matters is the one after the reduction. Cutting
first would mean deciding which of 85055 colours matter before knowing what survives the reduction.

**What this cannot do.** It cannot invent detail that the downsample threw away, and it cannot decide what
the drawing means: at 96 pixels wide a two-pixel eyebrow and a two-pixel scar look the same. The output is a
starting point for `grid` and hand work, which is the same relationship `build` has with its shapes.
"""
from __future__ import annotations

__all__ = ["sample", "reduce_colours", "pixelate"]

#: How close to a corner colour counts as background, per channel. Not zero, because a JPEG's white is not
#: exactly white: measured on the reference illustrations, the corner is 254,254,254 in some places and
#: 250,249,251 in others.
BACKGROUND_TOLERANCE = 24


def _corners(image):
    w, h = image.size
    return [image.getpixel(p)[:3] for p in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]


def _close(a, b, tolerance=BACKGROUND_TOLERANCE):
    return all(abs(int(x) - int(y)) <= tolerance for x, y in zip(a[:3], b[:3]))


def sample(image, *, width=None, height=None, pick="mode", head_bias=1.0):
    """Downsample by majority colour per block, keeping transparency.

    `width` or `height` may be given; the other follows the aspect ratio. Both are integers: a fractional
    target would put block boundaries between pixels, which is the same mistake as a fractional upscale.

    **`pick` decides what a block becomes, and the choice is what a face lives or dies on.** `mode` takes the
    commonest colour, which keeps flat areas flat; an eyelash one pixel wide in a twelve-pixel block is not
    common and disappears. `darkest` takes the darkest pixel of the block, so every line survives and the
    drawing comes out heavier. `contrast` takes the pixel furthest from the block's own average, which keeps
    both lines and highlights -- the closest of the three to what a person does by hand when shrinking a
    drawing with a face in it.

    **`head_bias` gives the top of the drawing more rows than its proportion.** A pixel character is drawn
    with a head larger than life, because a face needs pixels to be a face; a photograph shrunk mechanically
    keeps the photograph's proportions and the face arrives with three pixels for eyes. Above 1.0 the row
    mapping is `t ** head_bias`, which stretches the upper part of the image: 1.2 takes a fifth of the figure's
    body height away from the legs and gives it to the head. It is a proportional change, so it can make a
    drawing look top-heavy -- the value is a judgement about the drawing, not a default to leave alone.
    """
    if pick not in ("mode", "darkest", "contrast"):
        raise ValueError("pick must be 'mode', 'darkest' or 'contrast', got %r" % (pick,))
    if head_bias <= 0:
        raise ValueError("head_bias must be positive, got %r" % (head_bias,))
    if width is None and height is None:
        raise ValueError("give width or height")
    for name, value in (("width", width), ("height", height)):
        if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 1):
            raise ValueError("%s must be a positive integer, got %r" % (name, value))

    im = image.convert("RGBA")
    w, h = im.size
    if width is None:
        width = max(1, round(w * height / h))
    if height is None:
        height = max(1, round(h * width / w))
    if width > w or height > h:
        raise ValueError("asking for %dx%d from a %dx%d image would invent pixels"
                         % (width, height, w, h))

    px = im.load()
    out = []
    for ty in range(height):
        if head_bias == 1.0:
            y0 = ty * h // height
            y1 = max(y0 + 1, (ty + 1) * h // height)
        else:
            y0 = int(h * (ty / height) ** head_bias)
            y1 = max(y0 + 1, int(h * ((ty + 1) / height) ** head_bias))
        row = []
        for tx in range(width):
            x0 = tx * w // width
            x1 = max(x0 + 1, (tx + 1) * w // width)
            counts = {}
            opaque = 0
            for y in range(y0, y1):
                for x in range(x0, x1):
                    pixel = px[x, y]
                    if pixel[3] < 128:
                        continue
                    opaque += 1
                    key = pixel[:3]
                    counts[key] = counts.get(key, 0) + 1
            if opaque * 2 < (x1 - x0) * (y1 - y0):
                row.append((0, 0, 0, 0))          # the block is mostly empty: it stays empty
            else:
                if pick == "darkest":
                    best = min(counts, key=lambda c: (c[0] + c[1] + c[2], c))
                elif pick == "contrast":
                    n = sum(counts.values())
                    avg = tuple(sum(c[i] * counts[c] for c in counts) / n for i in range(3))
                    best = max(counts, key=lambda c: (sum((c[i] - avg[i]) ** 2 for i in range(3)),
                                                     counts[c], c))
                else:
                    # Ties go to the colour that appeared first: a dict keeps insertion order, so `next`
                    # picks the earliest, which is deterministic for a given image and block order. A
                    # random tie-break would make two runs of the same input differ.
                    best_count = max(counts.values())
                    best = next(k for k in counts if counts[k] == best_count)
                row.append(best + (255,))
        out.append(row)

    from PIL import Image

    # `Image.new`, not `image.__class__.new`: a file opened from a JPEG is a `JpegImageFile`, which has no
    # `new` -- the factory lives on the module, and the first version of this line failed exactly there.
    result = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    for y, row in enumerate(out):
        for x, pixel in enumerate(row):
            result.putpixel((x, y), pixel)
    return result


def reduce_colours(image, colours):
    """Cut the palette to at most `colours`, leaving transparency alone.

    Pillow's median cut is used rather than something written here: it is deterministic, it is already
    depended on, and a hand-rolled quantiser would be a second thing to calibrate. Transparent pixels are
    excluded from the vote and restored afterwards -- otherwise the transparent colour takes a palette slot
    and one real colour is lost.
    """
    from PIL import Image

    if not isinstance(colours, int) or isinstance(colours, bool) or colours < 2:
        raise ValueError("colours must be an integer of at least 2, got %r" % (colours,))
    im = image.convert("RGBA")
    w, h = im.size
    opaque = [im.getpixel((x, y))[:3] for y in range(h) for x in range(w)
              if im.getpixel((x, y))[3] >= 128]
    if not opaque:
        return im.copy()

    # A flat RGB copy for the quantiser, with transparency remembered separately.
    flat = Image.new("RGB", (w, h), opaque[0])
    mask = Image.new("L", (w, h), 0)
    flat_px, mask_px = flat.load(), mask.load()
    src = im.load()
    for y in range(h):
        for x in range(w):
            pixel = src[x, y]
            if pixel[3] >= 128:
                flat_px[x, y] = pixel[:3]
                mask_px[x, y] = 255
    cut = flat.quantize(colors=min(colours, len(set(opaque))), method=Image.MEDIANCUT).convert("RGB")

    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out_px, cut_px = out.load(), cut.load()
    for y in range(h):
        for x in range(w):
            if mask_px[x, y]:
                out_px[x, y] = cut_px[x, y] + (255,)
    return out


def _ground(image, tolerance=BACKGROUND_TOLERANCE):
    """The colour the drawing sits on, or None when it does not sit on one colour.

    **The four corners are not enough, and the first version used them.** A JPEG of a drawing on white has
    corners at 254,254,254 and 250,249,251, and a drawing that runs to the edge has a corner on the figure.
    So the whole border is sampled and bucketed: the most common bucket wins, and it only counts as a ground
    if more than half the border is that colour. Below that, the drawing has no flat ground and every pixel
    is kept.
    """
    w, h = image.size
    px = image.load()
    border = [(x, 0) for x in range(w)] + [(x, h - 1) for x in range(w)]
    border += [(0, y) for y in range(1, h - 1)] + [(w - 1, y) for y in range(1, h - 1)]
    counts = {}
    for x, y in border:
        pixel = px[x, y]
        if pixel[3] < 128:
            continue
        bucket = (pixel[0] // 8, pixel[1] // 8, pixel[2] // 8)
        entry = counts.setdefault(bucket, [0, [0, 0, 0]])
        entry[0] += 1
        entry[1][0] += pixel[0]
        entry[1][1] += pixel[1]
        entry[1][2] += pixel[2]
    total = sum(e[0] for e in counts.values())
    if not total:
        return None
    best = max(counts.values(), key=lambda e: e[0])
    if best[0] < total * 0.5:
        return None
    return tuple(round(c / best[0]) for c in best[1])


def _near(a, b, tolerance):
    return (abs(a[0] - b[0]) <= tolerance and abs(a[1] - b[1]) <= tolerance
            and abs(a[2] - b[2]) <= tolerance)


def _edges(image, *, darken=0.55, min_area=24, floor=16, tolerance=24):
    """Darken the border of every colour region, so two touching areas have an edge between them.

    **Two different lines, and the outer one alone was not enough.** `_outline` draws where the figure meets
    emptiness; inside the figure, a white coat against a white leg has no edge at all, and at 320 pixels wide
    those two areas read as one shape. This draws the *inner* line: every region large enough to be a form
    keeps a rim in its own darker colour.

    **Not black, on purpose.** Each rim is the region's own colour multiplied down, so a yellow sleeve gets a
    dark yellow rim and a white dress gets a grey one. One black outline over a drawing of twelve colours
    flattens it; twelve dark rims that belong to their colours keep the drawing's own palette legible.

    **Regions are near-colour, not exact-colour, and that is the difference between a rim and noise.** The
    first version compared exact colours, so after quantisation every band of a gradient became its own
    region and every band got a rim -- a face covered in stripes. Quantising a long gradient always leaves
    several near-identical steps; at `tolerance` 24 they count as one area and the rim appears only where the
    drawing really changes colour.

    `min_area` protects the small things: at 320 pixels wide an eye highlight is two or three pixels, and
    rimming it would eat it. Regions below the threshold keep their flat colour and no border.
    """
    from PIL import Image

    im = image.convert("RGBA")
    w, h = im.size
    src = im.load()
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out.putdata(list(im.getdata()))
    dst = out.load()
    seen = [[False] * w for _ in range(h)]
    neighbours = ((1, 0), (-1, 0), (0, 1), (0, -1))

    for y in range(h):
        for x in range(w):
            if seen[y][x]:
                continue
            seen[y][x] = True
            pixel = src[x, y]
            if pixel[3] < 128:
                continue
            colour = pixel[:3]
            region = []
            stack = [(x, y)]
            while stack:
                cx, cy = stack.pop()
                region.append((cx, cy))
                for dx, dy in neighbours:
                    nx, ny = cx + dx, cy + dy
                    if 0 <= nx < w and 0 <= ny < h and not seen[ny][nx]:
                        other = src[nx, ny]
                        if other[3] >= 128 and _near(other[:3], colour, tolerance):
                            seen[ny][nx] = True
                            stack.append((nx, ny))
            if len(region) < min_area:
                continue
            dark = tuple(max(floor, int(c * darken)) for c in colour)
            for cx, cy in region:
                for dx, dy in neighbours:
                    nx, ny = cx + dx, cy + dy
                    if not (0 <= nx < w and 0 <= ny < h):
                        continue
                    other = src[nx, ny]
                    if other[3] < 128 or not _near(other[:3], colour, tolerance):
                        dst[cx, cy] = dark + (255,)
                        break
    return out


def pixelate(image, *, width=None, height=None, colours=24, background="auto", outline=None, denoise=1,
             edges=False, edge_darken=0.55, edge_min_area=24, edge_tolerance=24, pick="mode",
             head_bias=1.0):
    """`sample` then `reduce_colours`, with an optional automatic background and an optional outline.

    `background="auto"` reads the border and, when more than half of it is one colour, treats that colour as
    the ground and makes everything close to it transparent. It is turned off by `background=None`, and a
    drawing with no flat ground is left alone rather than guessed at.

    `denoise` is a median filter applied before the downsample, and it is on by default because **the
    commonest source of a drawing to pixelate is a JPEG**: its ringing survives a majority vote as speckle,
    and a median filter removes the speckle while keeping the edge it is meant to preserve. Set it to 0 for
    a clean source.

    `edges` draws a darker rim inside every region large enough to be a form -- the line *between* two
    touching areas, which the outer outline cannot provide. `edge_darken` is the multiplier applied to the
    region's own colour (0.55 means "half again as dark", never black), and `edge_min_area` keeps the rim off
    features small enough that the rim would replace them.
    """
    from PIL import ImageFilter

    im = image.convert("RGBA")
    if denoise:
        for _ in range(denoise):
            im = im.filter(ImageFilter.MedianFilter(3))
    if background == "auto":
        ground = _ground(im)
        if ground is not None:
            px = im.load()
            w, h = im.size
            for y in range(h):
                for x in range(w):
                    pixel = px[x, y]
                    if pixel[3] >= 128 and _close(pixel, ground):
                        px[x, y] = (0, 0, 0, 0)
    small = sample(im, width=width, height=height, pick=pick, head_bias=head_bias)
    # `colours=0` (or None) means **no cut at all**: the drawing is only downsampled and every colour the
    # majority vote produced survives. That is a different thing from a palette -- the drawing made smaller,
    # not the drawing made out of few colours.
    if colours:
        small = reduce_colours(small, colours)
    if edges:
        small = _edges(small, darken=edge_darken, min_area=edge_min_area,
                        tolerance=edge_tolerance)
        # Every rim is a new colour by construction, so the palette is re-cut afterwards rather than left to
        # grow by one per region. The extra eight slots are the rims; without them a drawing of twenty-four
        # colours would arrive with sixty.
        if colours:
            small = reduce_colours(small, colours + 8)
    if outline:
        small = _outline(small, outline)
    return small


def _outline(image, key):
    """One-pixel outline in `key` around the figure, drawn only into empty cells."""
    from PIL import Image

    im = image.convert("RGBA")
    w, h = im.size
    px = im.load()
    rgb = tuple(int(key[i:i + 2], 16) for i in (1, 3, 5)) if isinstance(key, str) else tuple(key)[:3]
    add = []
    for y in range(h):
        for x in range(w):
            if px[x, y][3] >= 128:
                continue
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h and px[nx, ny][3] >= 128:
                    add.append((x, y))
                    break
    out = Image.new("RGBA", (w, h))
    out.putdata(list(im.getdata()))
    out_px = out.load()
    for x, y in add:
        out_px[x, y] = rgb + (255,)
    return out
