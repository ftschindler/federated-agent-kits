"""Finding the parts inside a source, without the source having agreed to anything.

Almost every source in the world predates this idea (DESIGN.md section 5), so a
part is found by looking where parts already are rather than by reading anything
the repository would have had to add. Each kind has a fixed set of directories,
each is walked three levels deep, and a part nearer the top shadows a deeper one
of the same name.

**The directories a source keeps a part in are not the directories we render
into.** They read as one list today only because a harness reads what it writes,
and they stop being one list the moment a repository is its own source: a render
writes a skill into `.agents/skills/`, and discovery that treated that as an
input would find our own output and double it on the next pass. So the
directories an adapter declares arrive here as an argument rather than as an
import, and so does the set of paths the render record says we wrote.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from federated_agent_kits.manifest import Kind

#: What marks a skill: a directory with this file in it. The file is the part's
#: content and the directory is the part, because a skill brings its
#: `references/` with it.
SKILL_FILE = "SKILL.md"

#: What marks a rule or an agent: one markdown file, whose stem is its name.
MARKDOWN = ".md"

#: Where each kind is looked for, relative to the root of the source. The empty
#: string is the root itself, so a repository holding one skill and nothing else
#: is a source without having been arranged into one. The three dotted skill
#: directories are what `npx skills add` already accepts, which is what
#: repositories in the wild already look like (DESIGN.md section 5).
KIND_DIRECTORIES: dict[Kind, tuple[str, ...]] = {
    Kind.SKILL: ("", "skills", "skills/.curated", "skills/.experimental", "skills/.system"),
    Kind.RULE: ("", "rules"),
    Kind.AGENT: ("", "agents"),
}

#: `<dir>/<name>`, `<dir>/<category>/<name>` and one category deeper. Three
#: rather than "as deep as it goes", because a walk with no bottom turns a
#: vendored dependency into sixty kits nobody subscribed to.
DEPTH = 3

#: How deep the root of the source itself is read. One level, and not `DEPTH`:
#: the root is in the list so that a repository holding a kit and nothing else
#: is a source (DESIGN.md section 5), not so that every markdown file within
#: three levels of it is a part. Walking it to `DEPTH` makes `rules/thing.md` an
#: agent as well as a rule, because the root contains `rules/` and `agents/`
#: both.
ROOT_LEVELS = 1

#: What a part found at the root of a base directory sits at, which is shallower
#: than anything else and therefore shadows all of it.
ROOT_DEPTH = 0

#: Directories a walk never descends into. `.git` is the expensive one and the
#: rest are the ones that hold somebody else's code: a part found in a vendored
#: dependency was not offered by this source.
SKIPPED = frozenset({".git", "node_modules", ".venv", "venv", "__pycache__", ".tox", "dist", "build"})

WILDCARD = "*"


@dataclass(frozen=True)
class Part:
    """One thing a source offers, found rather than declared."""

    kind: Kind
    name: str
    """What the source calls it: a skill's directory name, a rule's filename stem."""

    path: Path
    """The skill's directory, or the rule or agent's file. What a render copies."""

    relative: str
    """Where it sits inside the source, for a message that can be acted on."""

    depth: int
    """How far down it was found, which is what decides a shadowing contest."""


def _interesting(directory: Path) -> Iterable[Path]:
    """The children of one directory worth looking at, in a stable order.

    A dotted name is skipped wholesale. The three dotted skill directories that
    are part of the convention are reached because `KIND_DIRECTORIES` names
    them, not by being walked into, so skipping them here costs nothing and
    keeps `.github`, `.venv` and a stray `.DS_Store` out of every result.
    """
    for child in sorted(directory.iterdir()):
        if child.name.startswith(".") or child.name in SKIPPED:
            continue
        yield child


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


@dataclass(frozen=True)
class _Walk:
    """One pass over one base directory, so the recursion carries one argument.

    `found` is mutated rather than returned because the walk is depth-first over
    several base directories and the order they were found in is what decides a
    shadowing tie.
    """

    kind: Kind
    root: Path
    limit: int
    found: list[Part]

    def add(self, path: Path, name: str, depth: int, relative: str | None = None) -> None:
        self.found.append(
            Part(
                kind=self.kind,
                name=name,
                path=path,
                relative=_relative(path, self.root) if relative is None else relative,
                depth=depth,
            )
        )


def _skills_in(walk: _Walk, directory: Path, depth: int) -> None:
    if depth == ROOT_DEPTH and (directory / SKILL_FILE).is_file():
        # A repository that is one skill, which DESIGN.md section 5 calls a
        # source and a kit of one part without anybody having decided so. It has
        # no directory of its own inside the source, so it takes the source's
        # name.
        walk.add(directory, directory.name, ROOT_DEPTH, relative=".")
        return
    for child in _interesting(directory):
        if not child.is_dir():
            continue
        if (child / SKILL_FILE).is_file():
            walk.add(child, child.name, depth + 1)
        elif depth + 1 < walk.limit:
            _skills_in(walk, child, depth + 1)


def _files_in(walk: _Walk, directory: Path, depth: int) -> None:
    for child in _interesting(directory):
        if child.is_dir():
            if depth + 1 < walk.limit:
                _files_in(walk, child, depth + 1)
        elif child.suffix == MARKDOWN:
            walk.add(child, child.stem, depth + 1)


def _shadowed(found: Iterable[Part]) -> tuple[Part, ...]:
    """One part per name, the shallowest winning, in the order they were found.

    A tie is impossible within one base directory and perfectly possible across
    two, where the earlier directory wins: the list in `KIND_DIRECTORIES` is
    written root-first for exactly that reason.
    """
    kept: dict[str, Part] = {}
    for part in found:
        standing = kept.get(part.name)
        if standing is None or part.depth < standing.depth:
            kept[part.name] = part
    return tuple(kept.values())


def _is_ours(part: Part, rendered: set[Path]) -> bool:
    """Whether this part is something a render wrote rather than something the source offers.

    The record names files and a skill is a directory, so a part is ours when it
    is a rendered file or when a rendered file is inside it. Matching only on
    equality would miss every skill, which is the one kind this subtraction
    exists for.
    """
    here = part.path.resolve()
    return any(path == here or path.is_relative_to(here) for path in rendered)


def parts(
    root: Path,
    kind: Kind,
    *,
    extra_directories: Iterable[str] = (),
    rendered: Iterable[Path] = (),
) -> tuple[Part, ...]:
    """Every part of one kind a source offers.

    `extra_directories` is what the adapters declare they read for this kind,
    passed in so that adding a harness cannot mean editing this walk.
    `rendered` is what the render record says this tool wrote, subtracted so a
    repository that is its own source never reads its own output back.
    """
    ours = {path.resolve() for path in rendered}
    found: list[Part] = []
    for relative in (*KIND_DIRECTORIES[kind], *extra_directories):
        directory = root if relative == "" else root.joinpath(*relative.split("/"))
        if not directory.is_dir():
            continue
        walk = _Walk(kind=kind, root=root, limit=ROOT_LEVELS if relative == "" else DEPTH, found=found)
        if kind is Kind.SKILL:
            _skills_in(walk, directory, ROOT_DEPTH)
        else:
            _files_in(walk, directory, ROOT_DEPTH)
    return _shadowed(part for part in found if not _is_ours(part, ours))


def named(
    root: Path,
    kind: Kind,
    name: str,
    *,
    extra_directories: Iterable[str] = (),
    rendered: Iterable[Path] = (),
) -> tuple[Part, ...]:
    """The parts one subscription asks for: every part for `"*"`, or the one named.

    An empty result is not an error here. The command that asked is the one that
    knows what to say about it, and `akit add` says what the source does hold
    rather than only that this is not in it (DESIGN.md section 10).
    """
    offered = parts(root, kind, extra_directories=extra_directories, rendered=rendered)
    if name == WILDCARD:
        return offered
    return tuple(part for part in offered if part.name == name)


__all__ = [
    "DEPTH",
    "KIND_DIRECTORIES",
    "SKILL_FILE",
    "WILDCARD",
    "Part",
    "named",
    "parts",
]
