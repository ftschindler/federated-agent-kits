"""The render record, read. Writing it is T5's, and so is deciding when it changes.

A render leaves a record in the state directory saying every file it wrote, the
subscriptions and harnesses that explain each one, and a hash of the copy
(DESIGN.md section 6). Three commands need to read it before anything writes it:
`akit list` says whether a part was rendered and where, discovery subtracts what
we wrote so a repository that is its own source does not read its own output
back, and `akit doctor` is most of what it reports.

So the schema and the reader land here, with T4, and the writer lands with T5.
The halves are split rather than postponed because a `list` that guessed from
what happens to be on disk would be a second, quieter definition of "rendered",
and the two would disagree the first time somebody copied a skill in by hand.

**An absent record is not an error.** A machine that has never rendered has none,
and that is the state every fresh clone is in.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from platformdirs import user_state_path

from federated_agent_kits.exits import AkitError

APPLICATION = "akit"
RECORD = "render.json"

#: Bumped when the shape below changes. A record this build does not understand
#: is discarded rather than guessed at: everything in it can be rebuilt by
#: rendering again, which is the one piece of state in this system that is
#: genuinely disposable.
SUPPORTED_VERSION = 1


class RecordError(AkitError):
    """The record is there and cannot be read, which is a thing `doctor` reports."""

    def __init__(self, path: Path, problem: str) -> None:
        super().__init__(
            f"the render record at {path} {problem}.\nRun `akit render` to write a new one, "
            f"or delete the file: everything in it can be rebuilt."
        )


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


@dataclass(frozen=True)
class Record:
    """What this machine wrote where. Empty when nothing has been rendered yet."""

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
    return Record(path=path, written=tuple(_entry(raw, path) for raw in written))


__all__ = ["RECORD", "SUPPORTED_VERSION", "Record", "RecordError", "Written", "load", "location", "root"]
