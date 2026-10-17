# -*- coding: utf-8 -*-
"""A real window over the panel layer: `tkinter` displays what `panel` already verified.

**The division of labour is the point.** `tkinter` here does exactly two things -- put an image on screen and
hand keystrokes over -- because **everything else is already verifiable elsewhere**: the geometry comes from
`panel.layout`, the pixels from `panel.render` (which `panel.check` verifies), the actions from `keys`, and the
status line from `terminal`. A toolkit that only displays and delivers cannot make any of those wrong.

**Why not the whole interface in `tkinter` widgets.** A `Button` draws itself with the system theme, which is
the opposite of pixel art, and a `Label` with a text font cannot be held to a 5-by-7 grid. So the window
carries **one image** and nothing else -- one logical pixel of the panel becomes `scale` screen pixels, nearest
neighbour, and the panel's own character is preserved because it was drawn at one pixel per pixel first.

**What cannot be tested here, stated rather than glossed.** Opening a window needs a display; a test run has
none. So the tests cover `tk_key` -- **the only toolkit-specific logic, and it is a pure function** -- and
everything behind it is covered by `panel`, `keys` and `terminal`. The window itself is the one part of this
package that is exercised by running it.
"""
from __future__ import annotations

__all__ = ["TK_KEYS", "tk_key", "open_window"]


#: `tkinter`'s names for keys, mapped to this package's names. **Only the names that differ or that the panel
#: uses** -- a toolkit's key name is not a stable interface, so the table is explicit rather than clever.
TK_KEYS = {
    "Tab": "tab",
    "ISO_Left_Tab": "shift+tab",     # what Shift+Tab actually arrives as on X11 and Windows
    "Return": "enter",
    "KP_Enter": "enter",
    "Escape": "esc",
    "space": "space",
    "Up": "up",
    "Down": "down",
    "Left": "left",
    "Right": "right",
    "BackSpace": "backspace",
}


def tk_key(keysym, char=None):
    """A `tkinter` key event as this package's key name, or `None` if it carries no action.

    **The only place a toolkit's vocabulary meets ours, and it is a pure function** -- which is why it is
    testable without a display. Two decisions worth stating:

    - **`keysym` first, `char` second.** A keysym names the key ("Tab", "Up"); a char is what was typed, which
      for letters is the letter. Binding on keysym alone would lose the arrow keys, and on char alone would
      lose Tab and Return.
    - **`None` for anything unmapped**, rather than a guessed `char:` -- an unknown keysym is unknown, and
      turning it into a character would make `F5` press the letter `f` five times.
    """
    if keysym in TK_KEYS:
        return TK_KEYS[keysym]
    if char and len(char) == 1 and char.isprintable():
        # a printable character carries its own identity; `keys.py` puts it in the `char:` namespace
        return "char:%s" % char.lower()
    return None


def open_window(spec, width, height, *, title=None, controls=0, scale=2, palette=None, hint=None):
    """Open a window showing the panel, with the focus ring driven by the keyboard.

    **`scale` is an integer and is refused otherwise**, because a fractional scale would resample the panel and
    a smooth filter would invent colours that are not in the palette. At `scale=2` a 72x30 panel occupies
    144x60 screen pixels.

    Returns nothing: it runs until the window is closed (close, quit, or Escape). Callers that need it
    non-blocking should run it in a thread, and the function is deliberately not made non-blocking here
    because a window that returns before it is closed has already lost the events that would have closed it.
    """
    from . import keys as K
    from . import panel as Pn
    from . import terminal as TERM

    if not isinstance(scale, int) or scale < 1:
        raise ValueError("scale must be a positive whole number, got %r" % (scale,))
    # **imported inside the function on purpose**: `tkinter` needs a display to import on some builds, and a
    # module that cannot be imported on a headless machine would take the whole package with it
    import tkinter as tk

    from PIL import ImageTk

    pal = Pn.PANEL_PALETTE if palette is None else palette
    focus = K.Focus(controls)
    root = tk.Tk()
    root.title(title or "ichiwatashi")
    root.resizable(False, False)
    # **The system's title bar and border are removed, because the panel already is one.** A decorated window
    # would put the operating system's chrome above a title bar this project drew to a 5x7 grid -- two title
    # bars, one of them not pixel art, and the outer one not ours. Measured off the first attempt: the
    # screenshot showed a light system bar above a dark panel, and the panel's own bar was redundant inside it.
    #
    # **What that costs is stated rather than glossed**: an undecorated window cannot be moved by its frame
    # and has no close button, so both are reimplemented below -- dragging the title bar, and clicking the
    # mark the panel already draws.
    root.overrideredirect(True)

    image_holder = {"photo": None}

    def redraw():
        im = Pn.render(spec, width, height, keys=Pn.PANEL_KEYS, palette=pal, title=title,
                       scale=scale, active=True)
        photo = ImageTk.PhotoImage(im)
        # **the reference has to be kept**: tkinter does not hold the image, and a garbage-collected
        # PhotoImage shows an empty window -- a bug that looks like the panel failed to draw
        image_holder["photo"] = photo
        canvas.itemconfigure(item, image=photo)

    def on_key(event):
        key = tk_key(event.keysym, event.char)
        if key is None:
            return
        action = K.action_for(key)
        if action is None:
            return
        effect = focus.apply(action)
        if effect == "left":
            root.destroy()
            return
        redraw()
        status.configure(text=TERM.status_line(focus=focus, active=True,
                                               hint=hint or "tab moves  enter activates  esc leaves"))

    im0 = Pn.render(spec, width, height, keys=Pn.PANEL_KEYS, palette=pal, title=title,
                    scale=scale, active=True)
    photo0 = ImageTk.PhotoImage(im0)
    image_holder["photo"] = photo0
    canvas = tk.Canvas(root, width=photo0.width(), height=photo0.height(), highlightthickness=0, bd=0)
    canvas.pack()
    item = canvas.create_image(0, 0, anchor="nw", image=photo0)
    status = tk.Label(root, anchor="w")
    status.configure(text=TERM.status_line(focus=focus if controls else None, active=True,
                                           hint=hint or "tab moves  enter activates  esc leaves"))
    status.pack(fill="x")
    root.bind("<Key>", on_key)

    # **Dragging and closing, because the system no longer provides either.** Both are computed from
    # `panel.layout`, so a window at any tier drags from its own title bar and closes on its own mark -- the
    # hit areas follow the drawing rather than being guessed constants.
    where = Pn.layout(spec, width, height)
    title_rect = where["title"]
    close_px = where.get("_close_px", set())
    drag = {"x": 0, "y": 0}

    def to_logical(event):
        # screen coordinates back to panel coordinates: one logical pixel is `scale` real ones
        return event.x // scale, event.y // scale

    def on_press(event):
        lx, ly = to_logical(event)
        if (lx, ly) in close_px:
            root.destroy()
            return
        tx0, ty0, tx1, ty1 = title_rect
        if tx0 <= lx < tx1 and ty0 <= ly < ty1:
            # remember where inside the title bar the drag started, so the window does not jump to the cursor
            drag["x"] = event.x_root - root.winfo_x()
            drag["y"] = event.y_root - root.winfo_y()

    def on_drag(event):
        if drag["x"] or drag["y"]:
            root.geometry("+%d+%d" % (event.x_root - drag["x"], event.y_root - drag["y"]))

    def on_release(_event):
        drag["x"] = drag["y"] = 0

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    root.mainloop()
