"""How private each source turned out to be, remembered for the one command that refuses.

A source is private when fetching it needed credentials, and that is only
observable while cloning (DESIGN.md section 8). So it is written down when it
happens, by `akit add` and `akit update`, and read later by the refusal that
keeps a private kit out of a public repository.

**This is a fact about the cache, not about a render.** It belongs to the
machine: one classification per source key, however many repositories subscribe
to it. The render record used to carry it, back when there was one record for
the whole machine. There is now one record per scope root, and copying the same
classification into every repository's record, or picking one record to be the
odd one that also holds machine state, would both be worse than a file with one
job.

**An unreadable entry is refused rather than forgiven.** Everywhere else in this
package a stale fact means "leave it alone", which is the safe direction. Here
the safe direction is the other way: a classification we cannot read is a
refusal we would skip, so this file is strict where the record is lenient.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path

from federated_agent_kits.cache import Privacy, Resolved
from federated_agent_kits.exits import AkitError
from federated_agent_kits.record import root

SOURCES = "sources.json"

#: Bumped when the shape below changes. Discarding this file costs one `akit
#: update` per source, which is the price of being wrong about it being cheap.
SUPPORTED_VERSION = 1


class ClassificationError(AkitError):
    """The classifications are there and cannot be read, which `doctor` reports."""

    def __init__(self, path: Path, problem: str) -> None:
        super().__init__(
            f"the source classifications at {path} {problem}.\nRun `akit update` to work them out again, "
            f"or delete the file: every entry in it is learned by fetching."
        )


def location(state_root: Path | None = None) -> Path:
    """Beside the render record, in the state directory, and never in a repository."""
    return root(state_root) / SOURCES


def load(state_root: Path | None = None) -> dict[str, Privacy]:
    """What this machine knows, or nothing at all on a machine that has not fetched."""
    path = location(state_root)
    if not path.is_file():
        return {}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ClassificationError(path, f"is not valid JSON ({error.msg}, line {error.lineno})") from error
    if not isinstance(document, dict):
        raise ClassificationError(path, "is not an object")
    if document.get("version") != SUPPORTED_VERSION:
        raise ClassificationError(path, f"says version {document.get('version')!r}, and this build understands 1")
    sources = document.get("sources", {})
    if not isinstance(sources, dict):
        raise ClassificationError(path, "has a `sources` that is not an object")
    found: dict[str, Privacy] = {}
    for key, value in sources.items():
        if value not in tuple(Privacy):
            raise ClassificationError(
                path, f"classifies the source {key} as {value!r}, which is neither public nor private"
            )
        found[str(key)] = Privacy(value)
    return found


def save(classifications: Mapping[str, Privacy], state_root: Path | None = None) -> Path:
    """Write them whole, sorted, so two equal sets of facts are one file."""
    path = location(state_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "version": SUPPORTED_VERSION,
        "sources": {key: str(classifications[key]) for key in sorted(classifications)},
    }
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n")
    return path


def learned(known: Mapping[str, Privacy], resolutions: Iterable[tuple[str, Resolved]]) -> dict[str, Privacy]:
    """What is known after a command that may have fetched, which `render` never is.

    A resolution that did not go near the network reports nothing and leaves
    what was already known, so carrying this through a command that only reads
    the cache is a no-op rather than a loss.
    """
    found = dict(known)
    for key, resolved in resolutions:
        if resolved.privacy is not None:
            found[key] = resolved.privacy
    return found


__all__ = ["SOURCES", "ClassificationError", "learned", "load", "location", "save"]
