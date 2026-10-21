"""Whether this terminal takes colour and marks, and the small vocabulary that uses them.

A report is read by a person at a terminal and by a pipe into a file, and the
two want different bytes. The decision is taken once, here, from the stream the
report is about to be written to, and everything that prints asks this object
rather than looking at the environment itself.

**Colour is off unless the stream is a terminal that asked for it.** `NO_COLOR`
wins over everything, `FORCE_COLOR` turns it on where detection cannot (a CI log,
a test), and `TERM=dumb` is a terminal saying it cannot.

**Marks follow colour, and then ask the encoding.** A stream that cannot encode
a tick would raise on the first one, so the fallback is `[x]` and `[ ]`, which
is three columns wide exactly as the two-column marks plus their space are.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TextIO

#: The marks for a part that is on disk and one that is not, in both shapes.
#: Each is padded to three columns so a column of them lines up either way.
MARKS: dict[bool, tuple[str, str]] = {True: ("[x]", "\u2705 "), False: ("[ ]", "\u274c ")}

RESET = "\033[0m"

CODES: dict[str, str] = {
    "bold": "1",
    "dim": "2",
    "red": "31",
    "green": "32",
    "yellow": "33",
    "magenta": "35",
    "cyan": "36",
}


def encodable(out: TextIO, text: str) -> bool:
    """Whether this stream could write these characters without raising."""
    encoding = getattr(out, "encoding", None)
    if not encoding:  # a string buffer, which holds text rather than bytes
        return True
    try:
        text.encode(encoding)
    except (LookupError, UnicodeEncodeError):
        return False
    return True


def wanted(out: TextIO, environment: Mapping[str, str]) -> bool:
    """Whether colour was asked for, by the environment first and the stream second."""
    if environment.get("NO_COLOR"):
        return False
    if environment.get("FORCE_COLOR"):
        return True
    if environment.get("TERM") == "dumb":
        return False
    return out.isatty()


@dataclass(frozen=True)
class Style:
    """What this stream takes, and the only thing anything printing is allowed to ask."""

    colour: bool
    marks: bool

    @classmethod
    def of(cls, out: TextIO, environment: Mapping[str, str] | None = None) -> Style:
        colour = wanted(out, os.environ if environment is None else environment)
        return cls(colour=colour, marks=colour and encodable(out, MARKS[True][1]))

    @classmethod
    def plain(cls) -> Style:
        """No colour and no marks, which is what a pipe and every snapshot gets."""
        return cls(colour=False, marks=False)

    def paint(self, text: str, *names: str) -> str:
        if not self.colour:
            return text
        return f"\033[{';'.join(CODES[name] for name in names)}m{text}{RESET}"

    def mark(self, present: bool) -> str:
        """Three columns saying whether the thing is there."""
        plain, marked = MARKS[present]
        if not self.marks:
            return self.paint(plain, "green" if present else "red")
        return marked

    def kit(self, name: str) -> str:
        return self.paint(name, "bold")

    def harness(self, name: str) -> str:
        return self.paint(name, "cyan")

    def source(self, name: str) -> str:
        return self.paint(name, "magenta")

    def place(self, name: str) -> str:
        return self.paint(name, "dim")

    def heading(self, text: str, rule: str) -> str:
        """A title, the line under it, and the blank line that separates it from its block."""
        return f"{self.paint(text, 'bold')}\n{rule * len(text)}\n\n"


__all__ = ["CODES", "MARKS", "RESET", "Style", "encodable", "wanted"]
