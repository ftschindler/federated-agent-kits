"""Every adapter, in one tuple, plus the three questions asked of all of them at once.

Adding a harness touches two things: a new file beside this one, and the line in
`ADAPTERS` registering it. That is rule 7 of DESIGN.md section 3, and
T10 turns it into a test rather than a promise.

The interface lives in `adapter.py` rather than here so that an adapter can
import it without importing the registry that imports the adapter. One module
holding both would be a cycle resolved by an import halfway down a file, which
works and is the kind of thing somebody tidies up on a Friday.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path

from federated_agent_kits.adapters import opencode, vscode
from federated_agent_kits.adapters.adapter import Adapter, Destination, Pointer, RuleShape, git_root
from federated_agent_kits.manifest import Kind, Scope

#: Every harness this build knows. One line per adapter, and nothing else in the
#: system is edited when one arrives.
ADAPTERS: tuple[Adapter, ...] = (opencode.ADAPTER, vscode.ADAPTER)

BY_NAME: dict[str, Adapter] = {adapter.name: adapter for adapter in ADAPTERS}

#: The name that means "whatever this machine has". A member of the
#: `harnesses:` list like any other, which is what lets a repository name one
#: more harness without turning the rest off (DESIGN.md section 6).
DETECTED = "detected"


def detected(home: Path) -> tuple[Adapter, ...]:
    """Every harness that has left evidence on this disk."""
    return tuple(adapter for adapter in ADAPTERS if adapter.detected(home))


def expand(names: Sequence[str], home: Path) -> tuple[tuple[Adapter, ...], tuple[str, ...]]:
    """A `harnesses:` list as adapters, and the names no adapter answers to.

    `detected` expands in place, a named harness is taken unconditionally
    whether or not this machine has it, and the unknown names come back rather
    than raising: this is read by `akit list`, which reports a failure per line
    because it is what you run when something is already wrong.
    """
    chosen: dict[str, Adapter] = {}
    unknown: list[str] = []
    for name in names:
        if name == DETECTED:
            for adapter in detected(home):
                chosen.setdefault(adapter.name, adapter)
        elif name in BY_NAME:
            chosen.setdefault(name, BY_NAME[name])
        elif name not in unknown:
            unknown.append(name)
    return tuple(chosen.values()), tuple(unknown)


def source_directories(kind: Kind) -> tuple[str, ...]:
    """Every directory any adapter would read this kind from, for the discovery walk.

    Project-scope rather than user-scope, because what this answers is where a
    *source repository* may have left a part, and a source is a repository. It is
    the whole registry rather than the detected ones: a repository laid out for a
    harness you do not have still holds the parts it holds.
    """
    found: list[str] = []
    for adapter in ADAPTERS:
        destination = adapter.destination(kind, Scope.PROJECT)
        if destination is None:
            continue
        found.extend(entry for entry in destination.directories if entry not in found)
    return tuple(found)


def kinds_taken(adapters: Iterable[Adapter]) -> tuple[Kind, ...]:
    """The union of what these harnesses take, in the order `Kind` declares them."""
    chosen = {kind for adapter in adapters for kind in adapter.kinds}
    return tuple(kind for kind in Kind if kind in chosen)


__all__ = [
    "ADAPTERS",
    "BY_NAME",
    "DETECTED",
    "Adapter",
    "Destination",
    "Pointer",
    "RuleShape",
    "detected",
    "expand",
    "git_root",
    "kinds_taken",
    "source_directories",
]
