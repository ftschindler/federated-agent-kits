"""The shape every command's output has, so a person learns it once.

`styling.py` decides whether this stream takes colour and marks. This decides
what a report made of them looks like: where a heading sits in the hierarchy,
how a column of marks is built, and what the two scopes are called
(DESIGN.md section 10, "What a report looks like").

It exists because `list` was written first and got the shape right, and the
next verb to want a heading would otherwise have copied the three lines that
make one and then drifted from them. Three things decide what belongs here.

**A level is a rule character, and no caller picks one.** `section` is `=` and
`group` is `-`, so a verb says which of the two it meant rather than which
character it wanted, and a report cannot end up with a group above a section.

**A mark is a claim about this machine.** `marked` is the only line shape that
prints one, so everything that makes a claim makes it in the same three
columns, and a thing with no machine to be on has `listed` instead.

**The two scopes are called global and project, everywhere.** Those are the
words the flags use, so one pair of names is defined here rather than one pair
per command.

Nothing here knows what any verb is about. A heading that only `list` wants
stays in `listing.py`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from federated_agent_kits.manifest import Kind, Scope
from federated_agent_kits.styling import Style

#: The two rule characters, by what they are under. A section is one of the
#: parts a report is made of; a group is a division inside one of those.
SECTION = "="
GROUP = "-"

#: What stands where a mark would, for a line that has no claim to make. Three
#: columns, which is what both shapes of mark in `styling` are.
UNMARKED = "-  "

INDENT = "  "

#: What each scope is called as a heading. "Yours" was the wrong word for it: a
#: project's subscriptions render onto your machine too, and the thing the two
#: differ in is which file the subscription is in rather than who it belongs to.
SCOPE_TITLE: dict[Scope, str] = {
    Scope.USER: "Global subscriptions",
    Scope.PROJECT: "Project subscriptions",
}

#: How a scope is named inside a sentence, as opposed to as a heading. The same
#: two words the headings and the flags use, so a reader who has met one has
#: met all three.
SCOPE_NAMED: dict[Scope, str] = {
    Scope.USER: "the global manifest",
    Scope.PROJECT: "this project's manifest",
}

#: What a scope's manifest is called as a heading, for the commands whose
#: report is about the file itself rather than about what is in it.
SCOPE_MANIFEST: dict[Scope, str] = {
    Scope.USER: "The global manifest",
    Scope.PROJECT: "This project's manifest",
}

#: The project's comes first, because that is the one the directory you are
#: standing in decides and the one a colleague cloning the repository also gets.
ORDERING: tuple[Scope, ...] = (Scope.PROJECT, Scope.USER)

#: What is missing when a scope has no manifest, by the name that scope's file
#: has. "No manifest found" says nothing about which file to go and write.
MISSING: dict[Scope, str] = {Scope.USER: "no manifest.yaml found", Scope.PROJECT: "no .akit.yaml found"}

#: Plurals for the three kinds, for a line that reads like English.
PLURAL: dict[Kind, str] = {Kind.SKILL: "skills", Kind.RULE: "rules", Kind.AGENT: "agents"}

#: And the singulars, because a line naming one kit names one kind.
SINGULAR: dict[Kind, str] = {Kind.SKILL: "skill", Kind.RULE: "rule", Kind.AGENT: "agent"}

NOTHING = "nothing subscribed here"

#: How much of a commit a person reads, in every verb that shows one. The whole
#: of one is in `--json` and in the manifest, so this answers only how much is
#: worth reading on a line of prose. Seven is what git itself abbreviates to in
#: a repository this size, and it lives here rather than in each verb because
#: two verbs showing one commit at two lengths cannot be compared by eye.
SHORT = 7


#: The length at which a list stops needing an "and" in it.
ONE = 1


def joined(items: Iterable[str]) -> str:
    """`a`, `a and b`, `a, b and c`. Empty is the caller's problem, not this one's."""
    listed = list(items)
    if len(listed) <= ONE:
        return "".join(listed)
    return f"{', '.join(listed[:-1])} and {listed[-1]}"


def counted(number: int, noun: str) -> str:
    """`no files`, `1 file`, `3 files`, because a report is sentences and not a log."""
    if number == 0:
        return f"no {noun}s"
    return f"{number} {noun}" if number == ONE else f"{number} {noun}s"


def section(title: str, out: TextIO, style: Style) -> None:
    """One of the parts a report is made of, with a blank line under its rule."""
    print(style.heading(title, SECTION), end="", file=out)


def group(title: str, out: TextIO, style: Style) -> None:
    """One division inside a section, ruled a level down from it."""
    print(style.heading(title, GROUP), end="", file=out)


def scope_title(scope: Scope, path: Path | None) -> str:
    """A scope's heading, naming the file it is about or the file that is not there."""
    return f"{SCOPE_TITLE[scope]} ({path if path is not None else MISSING[scope]})"


def manifest_title(scope: Scope, path: Path | None) -> str:
    """A manifest's heading, for a command that wrote to one rather than read it."""
    return f"{SCOPE_MANIFEST[scope]} ({path if path is not None else MISSING[scope]})"


def width_of(names: Iterable[str]) -> int:
    """How wide a column of these names has to be. Empty is zero, not an error."""
    return max((len(name) for name in names), default=0)


@dataclass(frozen=True)
class Column:
    """A block of lines whose names line up and whose marks read down.

    The width, the style and the indent travel together because every line in
    one block shares all three, and a function taking them one at a time would
    let two lines of the same block disagree about any of them.
    """

    width: int
    style: Style
    indent: str = ""

    @classmethod
    def of(cls, names: Iterable[str], style: Style, indent: str = "") -> Column:
        return cls(width=width_of(names), style=style, indent=indent)

    def padded(self, name: str) -> str:
        """A name in the column, coloured, and padded by its length rather than its bytes.

        The padding is counted before the colour goes on, because an escape
        sequence is zero columns wide on a terminal and several characters long
        in a string.
        """
        return self.style.harness(name) + " " * (self.width - len(name))

    def marked(self, name: str, says: str, out: TextIO, *, present: bool) -> None:
        """One line whose first three columns say whether what it describes is on disk."""
        print(f"{self.indent}{self.style.mark(present)} {self.padded(name)}  {says}", file=out)

    def listed(self, name: str, says: str, out: TextIO) -> None:
        """The same line without the claim, for a thing with no machine to be on.

        A mark here would be a claim about this machine, and a harness that runs
        on somebody else's has none to make. The dash occupies the three columns
        a mark would have, so a listed block and a marked one in the same report
        put their names and their text in the same place.
        """
        print(f"{self.indent}{UNMARKED} {self.padded(name)}  {says}", file=out)


def wrapped(first: str, rest: Iterable[str], out: TextIO, *, indent: str = INDENT) -> None:
    """A sentence that arrived with newlines in it, printed under one indent.

    Several things a report prints are composed elsewhere and can be more than
    one line. Printing one of them raw would put the continuation at column
    zero, which reads as a new entry rather than as the rest of this one.

    Whatever indentation those lines arrived with is kept, because the sentence
    that composed them is the one that knows whether it meant anything by it.
    """
    print(f"{indent}{first}", file=out)
    for line in rest:
        print(f"{indent}{INDENT}{line}", file=out)


__all__ = [
    "GROUP",
    "INDENT",
    "MISSING",
    "NOTHING",
    "ONE",
    "ORDERING",
    "PLURAL",
    "SCOPE_MANIFEST",
    "SCOPE_NAMED",
    "SCOPE_TITLE",
    "SECTION",
    "SHORT",
    "SINGULAR",
    "UNMARKED",
    "Column",
    "counted",
    "group",
    "joined",
    "manifest_title",
    "scope_title",
    "section",
    "width_of",
    "wrapped",
]
