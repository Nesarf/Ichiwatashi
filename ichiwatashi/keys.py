# -*- coding: utf-8 -*-
"""Keyboard input as a model: keys become actions, actions move a focus ring.

**Why this is separate from any window, and why it comes first.** "A keyboard-operable window" sounds like a
GUI problem and is mostly not one. What a window *does* with a key -- which widget it goes to next, whether
Enter activates or closes, whether Escape closes or cancels -- is a small state machine, and it is the part
that can be wrong. The toolkit is a delivery mechanism for keystrokes; the decisions are elsewhere.

So this module has no toolkit in it at all. It maps a **key sequence** to an **action** and keeps a **focus
ring**, which means every rule below can be tested without a display, a terminal, or a keyboard.

Measured availability on this machine, before choosing: `tkinter` present, `msvcrt` present (Windows key
reads), `curses` and `termios` absent (they are POSIX), terminal 80x24. **Both a real window and a terminal
are reachable, so the choice is about what to verify first, not about what is possible.**
"""
from __future__ import annotations

from dataclasses import dataclass

__all__ = ["ACTIONS", "DEFAULT_BINDINGS", "parse_key", "action_for", "Focus"]


#: What a key can mean. **Deliberately a closed set**: an action that is not here is not an action, and a
#: binding to it is a typo rather than an extension.
ACTIONS = (
    "focus_next",     # move to the next widget in the ring
    "focus_prev",     # ... and the previous one
    "activate",       # do the focused thing
    "cancel",         # back out of whatever is happening, without doing the focused thing
    "close",          # ask for the window to go away
    "quit",           # ask for the program to stop
)

#: The default bindings. **Named by what a key *is*, not by the byte it arrives as** -- translation from bytes
#: happens in `parse_key`, so a terminal and a toolkit can share this table.
DEFAULT_BINDINGS = {
    "tab": "focus_next",
    "down": "focus_next",
    "shift+tab": "focus_prev",
    "up": "focus_prev",
    "enter": "activate",
    "space": "activate",
    "esc": "cancel",
    "q": "quit",
    "ctrl+w": "close",
}

#: Names that arrive as escape sequences rather than as one character, in the order they must be tried --
#: a prefix can match the start of a longer sequence, so the longest has to be checked first.
_ESCAPES = (
    ("\x1b[Z", "shift+tab"),
    ("\x1b[A", "up"),
    ("\x1b[B", "down"),
    ("\x1b[C", "right"),
    ("\x1b[D", "left"),
    ("\x1b", "esc"),
    ("\t", "tab"),
    ("\r", "enter"),
    ("\n", "enter"),
    (" ", "space"),
)


def parse_key(sequence: str) -> str:
    """One keystroke as a name, from the bytes a terminal delivers.

    **The order of `_ESCAPES` is the whole difficulty.** `\\x1b[Z` starts with `\\x1b`, so a table tried in the
    wrong order reports every arrow key as Escape followed by two stray characters -- and the symptom is a
    window that closes when you press Up. Longest first, which is what the tuple's order encodes and what the
    test asserts.
    """
    if not sequence:
        raise ValueError("an empty sequence is not a keystroke")
    for prefix, name in _ESCAPES:
        if sequence == prefix:
            return name
    if len(sequence) == 1:
        ch = sequence
        if ch.isprintable():
            return "char:%s" % ch.lower()
        raise ValueError("unprintable character %r has no name" % (ch,))
    raise ValueError("%r is not one keystroke; %d characters" % (sequence, len(sequence)))


def action_for(key: str, *, bindings=None):
    """The action a key name carries, or `None` if it is unbound. **`None` rather than a default**, because
    an unbound key doing something is how a window surprises its user.

    **A printable key is looked up twice, and the first version was not.** `parse_key("q")` returns
    `"char:q"` -- one namespace for every keystroke, so an arrow and a letter cannot collide -- while the
    bindings table writes `"q"`, because that is what a person calls it. Checking only the full name meant
    `"q": "quit"` was in the table and **never fired**: measured, pressing `q` returned `ignored`. So a
    `char:` key that is not found verbatim is looked up by the letter alone.
    """
    table = DEFAULT_BINDINGS if bindings is None else bindings
    unknown = set(table.values()) - set(ACTIONS)
    if unknown:
        # checked on every call rather than once at import: a caller may pass its own table, and the typo has
        # to be reported where it was made
        raise ValueError("binding target(s) %s are not actions; known: %s"
                         % (sorted(unknown), ", ".join(ACTIONS)))
    if key in table:
        return table[key]
    if key.startswith("char:"):
        return table.get(key[len("char:"):])
    return None


@dataclass
class Focus:
    """A ring of `count` widgets, with one of them holding the focus.

    **A ring and not a list with two ends**: tabbing past the last widget goes to the first, which is what
    every desktop does and what a list would get wrong at the boundary. `count == 0` is allowed and means
    nothing can hold the focus -- a window with no controls is a legitimate state, not an error.
    """
    count: int
    index: int = 0

    def __post_init__(self):
        if self.count < 0:
            raise ValueError("a focus ring of %d widgets is not a ring" % self.count)
        if self.count and not (0 <= self.index < self.count):
            raise ValueError("index %d is outside a ring of %d" % (self.index, self.count))
        if not self.count and self.index != 0:
            raise ValueError("an empty ring cannot focus widget %d" % self.index)

    def apply(self, action: str):
        """Take one action and say what happened: `"moved"`, `"activated"`, `"left"`, or `"ignored"`.

        **The reply is a value rather than a side effect on the outside world**, so a test can drive a whole
        sequence of keystrokes and assert the transcript instead of watching a window. That is the same reason
        `judge` returns a `Report` rather than printing one.
        """
        if action not in ACTIONS:
            raise ValueError("%r is not an action; known: %s" % (action, ", ".join(ACTIONS)))
        if action == "focus_next":
            if not self.count:
                return "ignored"
            self.index = (self.index + 1) % self.count
            return "moved"
        if action == "focus_prev":
            if not self.count:
                return "ignored"
            self.index = (self.index - 1) % self.count
            return "moved"
        if action == "activate":
            return "activated" if self.count else "ignored"
        if action in ("cancel",):
            return "left"
        if action in ("close", "quit"):
            return "left"
        return "ignored"

    def press(self, sequence: str, *, bindings=None):
        """Convenience: parse, bind, apply. Returns `(key_name, action, effect)`.

        The three parts are returned together because a caller that only gets the effect cannot tell
        "unbound key" from "bound to something that did nothing", and the first is usually a typo.
        """
        key = parse_key(sequence)
        action = action_for(key, bindings=bindings)
        if action is None:
            return key, None, "ignored"
        return key, action, self.apply(action)
