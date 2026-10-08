"""The seven questions of DESIGN.md section 4, as one dataclass.

A harness is a file, not a branch. What that claim costs is this interface
staying wide enough to hold the awkward answers without anything outside an
adapter changing, so each of the seven questions is a field here and the three
jobs that vary together - detection, where a source keeps a part, and where this
harness reads one - sit in one place rather than in three registries keyed by
harness name.

**Declining a kind is an answer, not a gap.** Every adapter shipped for 1.0
declines agents (DESIGN.md section 7 has four harnesses disagreeing about what an
agent even is), so the path where a kind has no destination is the ordinary path
rather than the exceptional one, and nothing may crash on it.

**Read and write are two lists because a repository can be its own source.**
Where we put a skill is one directory. Where a *source* may have left one is a
wider set, and discovery that confused the two would read this tool's own output
back in and double it on the next pass.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from federated_agent_kits.manifest import Kind, Scope, worktree_root

#: The separator every declared path is written with, regardless of platform.
#: These are declarations rather than paths, and `Path.joinpath` turns one into
#: the other at the moment it is used, so a Windows machine never meets a
#: hard-coded backslash and a declaration never has to be spelled twice.
SEPARATOR = "/"


class RuleShape(StrEnum):
    """Which of the three ways of taking rules this harness is (DESIGN.md section 7)."""

    DIRECTORY = "directory"
    """A directory we own, one file per rule. The shape we want everywhere."""

    POINTED = "pointed"
    """A directory we own, which the harness has to be pointed at once at setup."""

    SHARED_FILE = "shared-file"
    """One fixed file we have to share, each rule between its own marker pair."""


@dataclass(frozen=True)
class Pointer:
    """What a `POINTED` harness is pointed with: one key, in one config a person owns.

    Written at setup and never at render, and touching exactly this key: the rest
    of that file is somebody's, and T6 is where the writing lands.
    """

    config: str
    """The config file, relative to the scope's base directory."""

    key: str
    """The one key in it that names the directory we own."""


@dataclass(frozen=True)
class Destination:
    """Where one kind goes, and where this harness also reads it from, in one scope.

    `write` is `None` for a kind this harness takes but has nowhere to receive in
    this scope. A kind declined outright has no `Destination` at all, which is
    the difference between "not here" and "not at all".
    """

    write: str | None
    read: tuple[str, ...] = ()

    @property
    def directories(self) -> tuple[str, ...]:
        """Every directory involved, written first and never twice.

        A harness reads what it writes, so the written directory belongs in this
        list; it is stated rather than assumed because an adapter that writes
        somewhere it does not read is a harness that will never see its kits, and
        making the two one field would hide that.
        """
        if self.write is None:
            return self.read
        return (self.write, *(entry for entry in self.read if entry != self.write))


def git_root(start: Path) -> Path | None:
    """The default answer to question 6: a repository's kits sit beside its `.akit.yaml`.

    True for every harness that walks up looking for files, and not true for pi,
    which anchors on the nearest ancestor holding a `.pi` directory. That is why
    this is a function an adapter may replace rather than something computed
    once by the caller.
    """
    return worktree_root(start)


@dataclass(frozen=True)
class Adapter:
    """One harness: where it keeps things, what shape it wants them in, and how to tell it is here."""

    name: str
    """What a manifest's `harnesses:` list writes, and what `akit list` prints."""

    summary: str
    """One line, for `akit list` and for the error naming a harness nobody knows."""

    has_a_machine: bool
    """False for a harness `akit` can never run on, which can only arrive by being named."""

    destinations: Mapping[tuple[Kind, Scope], Destination]
    """Question 1 and question 4, per scope. A missing kind is a declined kind."""

    rule_shape: RuleShape
    rule_suffix: str = ".md"
    """What a rule is called in a directory we own, `.instructions.md` for some."""

    rule_frontmatter: Mapping[str, str] = field(default_factory=dict)
    """Keys every rule rendered for this harness carries, whatever the source said.

    Not a style preference. Copilot's `applyTo` decides whether the file is read
    at all, so a rule rendered without it is a rule that sits on disk and never
    loads (DESIGN.md section 4). A harness that needs no such key declares none,
    and the renderer then writes the body alone.
    """

    orders_rules: bool = False
    """Whether this harness reads our rules in the order the manifest put them.

    True only for a harness that takes them as one sequence we write, which is
    the third shape. A harness reading a directory gets no promise, and Copilot's
    documentation says outright not to depend on one, so `akit list` reports
    which it is rather than leaving somebody to learn it from behaviour
    (DESIGN.md section 7).
    """

    pointer: Mapping[Scope, Pointer] = field(default_factory=dict)
    """Question 3, and empty unless `rule_shape` is `POINTED`."""

    agent_frontmatter: Mapping[str, str] = field(default_factory=dict)
    """Question 4's other half: our key name to this harness's. Empty while agents are declined."""

    agent_tools: Mapping[str, str] = field(default_factory=dict)
    """Question 5. Empty while agents are declined; T13 fills it from three real agents."""

    evidence: tuple[str, ...] = ()
    """Question 7: paths under a home directory, any one of which means this harness is here."""

    anchor: Callable[[Path], Path | None] = git_root
    """Question 6, as a computation rather than an assumption."""

    def takes(self, kind: Kind) -> bool:
        """Whether this harness wants this kind at all, in any scope."""
        return any(declared is kind for (declared, _) in self.destinations)

    @property
    def kinds(self) -> tuple[Kind, ...]:
        """The kinds this harness takes, in the order `Kind` declares them."""
        return tuple(kind for kind in Kind if self.takes(kind))

    def destination(self, kind: Kind, scope: Scope) -> Destination | None:
        return self.destinations.get((kind, scope))

    def shares_the_file(self, kind: Kind) -> bool:
        """Whether this kind lands inside a file somebody else owns.

        True for rules in the third shape and for nothing else. The two callers
        both need it to decide whether a destination is a directory of ours at
        all: one maintains the ignore block, the other prunes, and both would be
        wrong about `AGENTS.md`.
        """
        return kind is Kind.RULE and self.rule_shape is RuleShape.SHARED_FILE

    def region(self, kind: Kind, name: str) -> str | None:
        """The marker id this part is written under, or `None` for a whole file.

        A region is what makes several rules one file: the record names the id
        beside the path, the hash covers only the bytes between those markers,
        and withdrawal takes the block out rather than the host (DESIGN.md
        section 6).
        """
        return name if self.shares_the_file(kind) else None

    def detected(self, home: Path) -> bool:
        """Whether this harness has left something on this disk.

        Evidence, never configuration, and never what a repository contains: a
        checkout holding `.github/agents/` says nothing about this machine, and
        inferring a harness from one would start committing rendered files
        nobody asked for (DESIGN.md section 4).
        """
        if not self.has_a_machine:
            return False
        return any(home.joinpath(*entry.split(SEPARATOR)).exists() for entry in self.evidence)

    def target(self, kind: Kind, scope: Scope, name: str, base: Path) -> Path | None:
        """Where one named part of one kind lands, or `None` if this harness declined it.

        `base` is the scope's root: a home directory for yours, the project
        anchor for a repository's. A shared-file harness answers with the file
        itself, because which bytes inside it belong to this rule is T6's
        question and not a path.
        """
        destination = self.destination(kind, scope)
        if destination is None or destination.write is None:
            return None
        written = base.joinpath(*destination.write.split(SEPARATOR))
        if kind is Kind.SKILL:
            return written / name
        if self.rule_shape is RuleShape.SHARED_FILE:
            return written
        return written / f"{name}{self.rule_suffix}"


__all__ = ["SEPARATOR", "Adapter", "Destination", "Pointer", "RuleShape", "git_root"]
