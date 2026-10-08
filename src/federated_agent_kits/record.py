"""The render record: what was written under one root, kept beside that root.

A render leaves a record saying every file it wrote, the subscriptions and
harnesses that explain each one, and a hash of the copy (DESIGN.md section 6).
Three commands read it before `render` writes it: `akit list` says whether a part
was rendered and where, discovery subtracts what we wrote so a repository that is
its own source does not read its own output back, and `akit doctor` is most of
what it reports.

**There is one record per scope root, not one per machine.** Yours lives in the
state directory and covers what lands in your home directory. A repository's
lives inside that repository and covers what lands there. The two mirror the two
manifests, which is the shape everything else in this system already has.

One file for the whole machine was the first design and it had three faults, all
of them the same fault. Two repositories rendering at once overwrote each
other's entries, because each render rewrites the file whole. A repository that
was deleted left entries nothing could ever collect, because withdrawal only
runs in the root they belong to. And a render in one repository could withdraw
another's files, because scope says which manifest and not which repository.
Splitting the file removes all three rather than checking for them: the record
you can open is the record you are responsible for.

**It is also the list of files this tool may delete, and the list is
exhaustive.** A file not in here was not written by us, so no command touches
it, whatever directory it is sitting in and whatever it is called.

**An absent record is not an error.** A root that has never been rendered into
has none, and that is the state every fresh clone is in. A record that empties is
removed rather than left as an empty file.

**Every entry is a whole file, until T6.** A rule written into a file somebody
else owns is recorded as a region: the marker id beside the path, the hash over
the bytes between the markers, and no permission to delete the host
(DESIGN.md section 6). No adapter shipping for 1.0 takes rules that way, so the
field lands with the renderer that first writes one. An absent field already
means "leave alone", so adding it then costs no version bump.

**Deleting a record costs one `akit render`**, which is why each is written whole
rather than edited. One thing does not come back: a file rendered before its
record was lost is now unknown rather than unexplained, and `render --prune` is
the only thing that will touch it.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from platformdirs import user_state_path

from federated_agent_kits.exits import AkitError
from federated_agent_kits.manifest import Kind, Scope, worktree_root

APPLICATION = "akit"
RECORD = "render.json"

#: The directory a repository's own state goes in, beside its `.akit.yaml`. A
#: directory rather than a dotted file because the ignore block then needs one
#: line for everything this tool keeps there, now and later.
DIRECTORY = ".akit"

#: Bumped when the shape below changes. A record this build does not understand
#: is discarded rather than guessed at: everything in it can be rebuilt by
#: rendering again, which is the one piece of state in this system that is
#: genuinely disposable.
SUPPORTED_VERSION = 1

#: What separates the three parts of an explanation. A vertical bar rather than a
#: colon or a slash, both of which a source key is full of: `github.com/acme/kits`
#: and `git@github.com:acme/kits.git` are ordinary keys and a kit name is a
#: directory name, so this is the one character none of the three can contain.
SEPARATOR = "|"

#: How many parts an explanation has, which is what tells a readable one from a
#: string somebody put in the file by hand. Three rather than four: the scope
#: used to be one of them and is now said by which file the entry is in.
PARTS = 3

#: How bytes become the hash that decides whether a rendered file is still a copy.
ALGORITHM = "sha256"


class RecordError(AkitError):
    """The record is there and cannot be read, which is a thing `doctor` reports."""

    def __init__(self, path: Path, problem: str) -> None:
        super().__init__(
            f"the render record at {path} {problem}.\nRun `akit render` to write a new one, "
            f"or delete the file: everything in it can be rebuilt."
        )


@dataclass(frozen=True)
class Explanation:
    """One reason a file is on disk: this subscription, wanting this name.

    Written into the record as one string rather than as an object, because what
    the record does with it is set arithmetic: withdrawal asks whether anything
    still explains a file, and a set of strings answers that without a schema for
    the answer.
    """

    kind: Kind
    source: str
    name: str
    """What the kit is rendered as, which is the `as:` name when there is one."""

    def __str__(self) -> str:
        return SEPARATOR.join((self.kind, self.source, self.name))

    @classmethod
    def parse(cls, text: str) -> Explanation | None:
        """The parts of an explanation, or `None` for a string that is not one.

        `None` rather than a refusal: the record is a cache of facts about this
        disk, so a line in it this build cannot read is a line that explains
        nothing, and a file nothing explains is one we leave alone. Refusing
        would turn a stale record into a command that cannot run.
        """
        parts = text.split(SEPARATOR)
        if len(parts) != PARTS:
            return None
        kind, source, name = parts
        if kind not in tuple(Kind):
            return None
        return cls(kind=Kind(kind), source=source, name=name)


def digest(data: bytes) -> str:
    """The hash that decides whether a rendered file is still a copy of its source."""
    return hashlib.new(ALGORITHM, data).hexdigest()


def digest_of(path: Path) -> str | None:
    """The hash of a file on disk, or `None` if it is not there any more."""
    try:
        return digest(path.read_bytes())
    except OSError:
        return None


@dataclass(frozen=True)
class Written:
    """One file a render put on disk, and everything that explains it.

    `explained_by` is a set rather than one subscription because two
    subscriptions and two harnesses can want the same bytes in the same place,
    and a withdrawal that deleted on the first explanation going away would take
    a file somebody still wants (DESIGN.md section 6).
    """

    path: Path
    digest: str
    """A hash of what was written, which is how an edited copy is left alone."""

    explained_by: frozenset[str] = field(default_factory=frozenset)
    harnesses: frozenset[str] = field(default_factory=frozenset)

    @property
    def explanations(self) -> tuple[Explanation, ...]:
        """The readable explanations, which is every one this build understands."""
        found = (Explanation.parse(entry) for entry in sorted(self.explained_by))
        return tuple(entry for entry in found if entry is not None)

    def still_a_copy(self) -> bool:
        """Whether the bytes on disk are the ones we put there.

        The question the whole withdrawal table turns on. A file whose hash has
        drifted is the only file in a rendered directory that contains something
        somebody wrote, and it is never ours to delete.
        """
        return digest_of(self.path) == self.digest


@dataclass(frozen=True)
class Record:
    """What was written under one root. Empty when nothing has been rendered there."""

    path: Path | None
    written: tuple[Written, ...] = ()

    @property
    def paths(self) -> frozenset[Path]:
        """Every file in the record, resolved, for discovery to subtract."""
        return frozenset(entry.path for entry in self.written)

    def holds(self, path: Path) -> bool:
        """Whether a render explains this path, or anything inside it.

        A skill is a directory and the record names files, so a directory counts
        as rendered when a recorded file is inside it. Asking only about equality
        would answer "no" for every skill, which is the kind this question is
        mostly asked about.
        """
        here = path.resolve()
        return any(entry.path == here or entry.path.is_relative_to(here) for entry in self.written)


@dataclass(frozen=True)
class Records:
    """Every record in play, which is what a reader wants and a writer never does.

    `akit list` and discovery ask about the disk rather than about one root, so
    they get both. `render` writes one root at a time and takes them apart again,
    because writing both from one value is how the single record's faults got in.
    """

    by_scope: Mapping[Scope, Record]

    def of(self, scope: Scope) -> Record:
        return self.by_scope.get(scope, Record(path=None))

    @property
    def paths(self) -> frozenset[Path]:
        return frozenset(path for record in self.by_scope.values() for path in record.paths)

    def holds(self, path: Path) -> bool:
        return any(record.holds(path) for record in self.by_scope.values())


def root(state_root: Path | None = None) -> Path:
    """The state directory, looked up per platform rather than spelled `~/.local/state`."""
    return state_root or user_state_path(APPLICATION, appauthor=False)


def user_location(state_root: Path | None = None) -> Path:
    """Where your own record lives, which is machine state and never a repository's."""
    return root(state_root) / RECORD


def project_location(worktree: Path) -> Path:
    """Where a repository's record lives, which is inside that repository.

    Beside `.akit.yaml` rather than in the state directory under a key, so that
    its lifetime is the repository's: delete the checkout and the record goes
    with it, move the checkout and the record moves too. Neither is true of a
    file somewhere else that names this path.
    """
    return worktree / DIRECTORY / RECORD


def locations(start: Path, *, state_root: Path | None = None) -> dict[Scope, Path]:
    """Every record that applies where this command is standing.

    The project one is absent outside a repository, which is an ordinary place
    to run this from and not an error.
    """
    found = {Scope.USER: user_location(state_root)}
    worktree = worktree_root(start)
    if worktree is not None:
        found[Scope.PROJECT] = project_location(worktree)
    return found


def _entry(raw: object, path: Path) -> Written:
    if not isinstance(raw, dict) or not isinstance(raw.get("path"), str) or not isinstance(raw.get("digest"), str):
        raise RecordError(path, "has an entry that is not a written file")
    return Written(
        path=Path(raw["path"]).resolve(),
        digest=raw["digest"],
        explained_by=frozenset(raw.get("explained_by", ())),
        harnesses=frozenset(raw.get("harnesses", ())),
    )


def load(path: Path) -> Record:
    """One record, or an empty one when nothing has been rendered into that root."""
    if not path.is_file():
        return Record(path=None)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise RecordError(path, f"is not valid JSON ({error.msg}, line {error.lineno})") from error
    if not isinstance(document, dict):
        raise RecordError(path, "is not an object")
    if document.get("version") != SUPPORTED_VERSION:
        raise RecordError(path, f"says version {document.get('version')!r}, and this build understands 1")
    written = document.get("written", [])
    if not isinstance(written, list):
        raise RecordError(path, "has a `written` that is not a list")
    return Record(path=path, written=tuple(_entry(raw, path) for raw in written))


def load_all(start: Path, *, state_root: Path | None = None) -> Records:
    """Both records, for the readers that ask about the disk rather than about a root."""
    return Records(by_scope={scope: load(path) for scope, path in locations(start, state_root=state_root).items()})


def payload(record: Record) -> dict[str, Any]:
    """The record as the JSON it is stored as, sorted so two equal records are equal files.

    Sorted rather than in the order the render happened to walk: the file is
    rewritten whole on every render, and an unsorted one would show a diff
    whenever a dictionary iterated differently, in a file somebody may well be
    watching to find out what changed.
    """
    return {
        "version": SUPPORTED_VERSION,
        "written": [
            {
                "path": str(entry.path),
                "digest": entry.digest,
                "explained_by": sorted(entry.explained_by),
                "harnesses": sorted(entry.harnesses),
            }
            for entry in sorted(record.written, key=lambda entry: str(entry.path))
        ],
    }


def save(record: Record, path: Path) -> Path | None:
    """Write one record whole, or take the file away when there is nothing to say.

    A record that empties is removed, and its directory with it when we made it,
    so a repository that stops being rendered into stops carrying a file about
    it. Writing an empty record instead would put a `.akit/` into every
    repository anybody ever ran this in.
    """
    if not record.written:
        _discard(path)
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload(record), indent=2) + "\n", encoding="utf-8", newline="\n")
    return path


def _discard(path: Path) -> None:
    if path.is_file():
        path.unlink()
    if path.parent.name == DIRECTORY and path.parent.is_dir() and not any(path.parent.iterdir()):
        path.parent.rmdir()


__all__ = [
    "DIRECTORY",
    "RECORD",
    "SUPPORTED_VERSION",
    "Explanation",
    "Record",
    "RecordError",
    "Records",
    "Written",
    "digest",
    "digest_of",
    "load",
    "load_all",
    "locations",
    "payload",
    "project_location",
    "root",
    "save",
    "user_location",
]
