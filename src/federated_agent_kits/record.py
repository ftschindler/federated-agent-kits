"""The render record: what this machine wrote where, and how private each source was.

A render leaves a record in the state directory saying every file it wrote, the
subscriptions and harnesses that explain each one, and a hash of the copy
(DESIGN.md section 6). Three commands read it before `render` writes it: `akit
list` says whether a part was rendered and where, discovery subtracts what we
wrote so a repository that is its own source does not read its own output back,
and `akit doctor` is most of what it reports.

The schema and the reader landed with T4 and the writer with T5, which is also
what decides when the record changes. The halves were split rather than
postponed because a `list` that guessed from what happens to be on disk would be
a second, quieter definition of "rendered", and the two would disagree the first
time somebody copied a skill in by hand.

**It is also the list of files this tool may delete, and the list is
exhaustive.** A file not in here was not written by us, so no command touches
it, whatever directory it is sitting in and whatever it is called.

**An absent record is not an error.** A machine that has never rendered has none,
and that is the state every fresh clone is in.

**Deleting it costs one `akit render`**, which is why it is written whole each
time rather than edited. One thing does not come back: a file rendered before the
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

from federated_agent_kits.cache import Privacy
from federated_agent_kits.exits import AkitError
from federated_agent_kits.manifest import Kind, Scope

APPLICATION = "akit"
RECORD = "render.json"

#: Bumped when the shape below changes. A record this build does not understand
#: is discarded rather than guessed at: everything in it can be rebuilt by
#: rendering again, which is the one piece of state in this system that is
#: genuinely disposable.
SUPPORTED_VERSION = 1

#: What separates the four parts of an explanation. A vertical bar rather than a
#: colon or a slash, both of which a source key is full of: `github.com/acme/kits`
#: and `git@github.com:acme/kits.git` are ordinary keys and a kit name is a
#: directory name, so this is the one character none of the four can contain.
SEPARATOR = "|"

#: How many parts an explanation has, which is what tells a readable one from a
#: string somebody put in the file by hand.
PARTS = 4

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
    """One reason a file is on disk: this subscription, in this scope, wanting this name.

    Written into the record as one string rather than as an object, because what
    the record does with it is set arithmetic: withdrawal asks whether anything
    still explains a file, and a set of strings answers that without a schema
    for the answer. `parse` gives the string back as its parts, for the one
    caller that has to know which scope a file belongs to.
    """

    scope: Scope
    kind: Kind
    source: str
    name: str
    """What the kit is rendered as, which is the `as:` name when there is one."""

    def __str__(self) -> str:
        return SEPARATOR.join((self.scope, self.kind, self.source, self.name))

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
        scope, kind, source, name = parts
        if scope not in tuple(Scope) or kind not in tuple(Kind):
            return None
        return cls(scope=Scope(scope), kind=Kind(kind), source=source, name=name)


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

    @property
    def scopes(self) -> frozenset[Scope]:
        """Which manifests this file belongs to, which is what scope narrowing reads."""
        return frozenset(entry.scope for entry in self.explanations)

    def still_a_copy(self) -> bool:
        """Whether the bytes on disk are the ones we put there.

        The question the whole withdrawal table turns on. A file whose hash has
        drifted is the only file in a rendered directory that contains something
        somebody wrote, and it is never ours to delete.
        """
        return digest_of(self.path) == self.digest


@dataclass(frozen=True)
class Record:
    """What this machine wrote where. Empty when nothing has been rendered yet."""

    path: Path | None
    written: tuple[Written, ...] = ()
    sources: Mapping[str, Privacy] = field(default_factory=dict)
    """How each remote source classified when it was fetched.

    Here rather than anywhere else because it is only observable while cloning
    (DESIGN.md section 8), and `render` never clones: it carries forward what
    `add` and `update` learned. T8 is what reads it, and the plumbing lands with
    the writer so that the schema is settled once.
    """

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


def root() -> Path:
    """The state directory, looked up per platform rather than spelled `~/.local/state`."""
    return user_state_path(APPLICATION, appauthor=False)


def location(state_root: Path | None = None) -> Path:
    return (state_root or root()) / RECORD


def _entry(raw: object, path: Path) -> Written:
    if not isinstance(raw, dict) or not isinstance(raw.get("path"), str) or not isinstance(raw.get("digest"), str):
        raise RecordError(path, "has an entry that is not a written file")
    return Written(
        path=Path(raw["path"]).resolve(),
        digest=raw["digest"],
        explained_by=frozenset(raw.get("explained_by", ())),
        harnesses=frozenset(raw.get("harnesses", ())),
    )


def _sources(raw: object, path: Path) -> dict[str, Privacy]:
    """The privacy classifications, refused rather than half-read.

    Stricter than `Explanation.parse`, which forgives a line it cannot read: an
    unreadable explanation costs a file being left alone, and an unreadable
    classification would cost the refusal in DESIGN.md section 8 being skipped.
    """
    if not isinstance(raw, dict):
        raise RecordError(path, "has a `sources` that is not an object")
    found: dict[str, Privacy] = {}
    for key, value in raw.items():
        if value not in tuple(Privacy):
            raise RecordError(path, f"classifies the source {key} as {value!r}, which is neither public nor private")
        found[str(key)] = Privacy(value)
    return found


def load(state_root: Path | None = None) -> Record:
    """The record, or an empty one when this machine has never rendered."""
    path = location(state_root)
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
    return Record(
        path=path,
        written=tuple(_entry(raw, path) for raw in written),
        sources=_sources(document.get("sources", {}), path),
    )


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
        "sources": {key: str(record.sources[key]) for key in sorted(record.sources)},
    }


def save(record: Record, state_root: Path | None = None) -> Path:
    """Write the record whole, creating the state directory if this is the first render."""
    path = location(state_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload(record), indent=2) + "\n", encoding="utf-8", newline="\n")
    return path


__all__ = [
    "RECORD",
    "SUPPORTED_VERSION",
    "Explanation",
    "Record",
    "RecordError",
    "Written",
    "digest",
    "digest_of",
    "load",
    "location",
    "payload",
    "root",
    "save",
]
