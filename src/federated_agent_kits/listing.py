"""`akit list`: what you subscribed to, where it came from, and where it would land.

The first command that does anything, and deliberately the one that only reads.
Resolution, the walk and the harness list all have to be right before a renderer
is allowed near a file, and this is the chance to get them right without a
file-writing bug on top (IMPLEMENTATION.md, T4).

Three rules shape the code below.

**Nothing is fetched.** Every resolution is offline, so a source this machine does
not have is a line saying so rather than a clone nobody asked for.

**Nothing stops the command.** A failure belongs to the line it happened on,
because this is what somebody runs when something is already wrong and a report
that gives up at the first bad entry is a report about the first bad entry.

**Where a part "would be rendered" is computed the same way a render will compute
it**, through `Adapter.target`, so the two cannot drift into two answers.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from federated_agent_kits import adapters, cache, discovery, manifest, record, sources
from federated_agent_kits.adapters import Adapter
from federated_agent_kits.exits import AkitError, Exit
from federated_agent_kits.manifest import Kind, Merged, Scope, Subscription

#: What each scope is called in a sentence, since "user" and "project" are our
#: words for it and not anybody else's.
SCOPE_TITLE: dict[Scope, str] = {
    Scope.USER: "Your subscriptions",
    Scope.PROJECT: "This repository's subscriptions",
}

#: Plurals for the three kinds, for a line that reads like English.
PLURAL: dict[Kind, str] = {Kind.SKILL: "skills", Kind.RULE: "rules", Kind.AGENT: "agents"}

#: How a scope is named inside a sentence, as opposed to as a heading.
SCOPE_NAMED: dict[Scope, str] = {Scope.USER: "your manifest", Scope.PROJECT: "this repository"}

NOTHING = "  nothing subscribed here"
INDENT = "  "

#: The length at which a list stops needing an "and" in it.
ONE = 1


def joined(items: Iterable[str]) -> str:
    """`a`, `a and b`, `a, b and c`. Empty is the caller's problem, not this one's."""
    listed = list(items)
    if len(listed) <= ONE:
        return "".join(listed)
    return f"{', '.join(listed[:-1])} and {listed[-1]}"


@dataclass(frozen=True)
class Target:
    """Where one part would land for one harness, and whether it is there."""

    harness: str
    path: Path
    rendered: bool


@dataclass(frozen=True)
class Found:
    """One part a subscription actually resolves to, with every place it goes."""

    name: str
    """What it is rendered as, which is `as:` when there is one."""

    found_as: str
    """What the source calls it, which differs only under `as:`."""

    relative: str
    """Where it sits inside the source, so a surprise can be acted on."""

    targets: tuple[Target, ...]


@dataclass(frozen=True)
class Line:
    """One subscription, as much as could be said about it."""

    subscription: Subscription
    where: Path | None
    """The directory on this disk the source resolved to, or `None` if it did not."""

    commit: str | None
    found: tuple[Found, ...]
    problem: str | None
    """What went wrong on this line alone. Everything else still printed."""


@dataclass(frozen=True)
class HarnessLine:
    """One harness, and whether anything will be rendered for it."""

    name: str
    summary: str
    known: bool
    """False for a name in a manifest that no adapter answers to."""

    detected: bool
    has_a_machine: bool
    kinds: tuple[Kind, ...]
    scopes: tuple[Scope, ...]
    """The manifests whose `harnesses:` list puts this one in play."""


@dataclass(frozen=True)
class Collision:
    """One rendered name two subscriptions both want (DESIGN.md section 6)."""

    kind: Kind
    name: str
    wanted_by: tuple[Subscription, ...]


@dataclass(frozen=True)
class Inventory:
    """Everything `akit list` found, before anything has been printed."""

    manifests: dict[Scope, Path | None]
    lines: tuple[Line, ...]
    harnesses: tuple[HarnessLine, ...]
    collisions: tuple[Collision, ...]

    def of_scope(self, scope: Scope) -> tuple[Line, ...]:
        return tuple(line for line in self.lines if line.subscription.scope is scope)


@dataclass(frozen=True)
class _Reading:
    """One pass of `list`, so the five things every line needs travel together.

    The same shape as `discovery._Walk` and for the same reason: a per-line
    helper that took `start`, `home`, the cache root, the record and the chosen
    harnesses as arguments would be five parameters threaded through four
    functions, and the next task would add a sixth.
    """

    start: Path
    home: Path
    cache_root: Path | None
    written: record.Record
    chosen: dict[Scope, tuple[Adapter, ...]]

    def anchor(self, adapter: Adapter, scope: Scope) -> Path:
        """The base a target is computed against: your home, or this harness's project anchor.

        The anchor is the harness's rather than ours, which is question 6 of
        DESIGN.md section 4 and the one that otherwise renders into a directory
        the harness never looks at.
        """
        if scope is Scope.USER:
            return self.home
        return adapter.anchor(self.start) or self.start

    def targets(self, subscription: Subscription, name: str) -> tuple[Target, ...]:
        found: list[Target] = []
        for adapter in self.chosen[subscription.scope]:
            path = adapter.target(subscription.kind, subscription.scope, name, self.anchor(adapter, subscription.scope))
            if path is None:
                continue
            found.append(Target(harness=adapter.name, path=path, rendered=self.written.holds(path)))
        return tuple(found)

    def resolve(self, subscription: Subscription) -> cache.Resolved:
        anchor = self.home if subscription.scope is Scope.USER else (manifest.worktree_root(self.start) or self.start)
        key = sources.parse(subscription.source)
        return cache.resolve(key, pin=subscription.pin, anchor=anchor, cache_root=self.cache_root, offline=True)

    def line(self, subscription: Subscription) -> Line:
        try:
            resolved = self.resolve(subscription)
        except AkitError as error:
            return Line(subscription=subscription, where=None, commit=None, found=(), problem=str(error))
        parts = discovery.named(
            resolved.root,
            subscription.kind,
            subscription.name,
            extra_directories=adapters.source_directories(subscription.kind),
            rendered=self.written.paths,
        )
        found = tuple(
            Found(
                name=subscription.rename or part.name,
                found_as=part.name,
                relative=part.relative,
                targets=self.targets(subscription, subscription.rename or part.name),
            )
            for part in parts
        )
        problem = None
        if not found:
            wanted = "anything" if subscription.is_wildcard else f'a {subscription.kind} called "{subscription.name}"'
            problem = f"this source does not hold {wanted}"
        return Line(
            subscription=subscription, where=resolved.root, commit=resolved.commit, found=found, problem=problem
        )


def _harness_lines(merged: Merged, home: Path) -> tuple[tuple[HarnessLine, ...], dict[Scope, tuple[Adapter, ...]]]:
    """Every harness worth a line, and the expansion each scope ended up with.

    Every registered adapter gets a line whether or not it is in play, because
    "Copilot is installed and this repository does not render for it" is exactly
    the thing somebody runs `list` to find out.
    """
    chosen: dict[Scope, tuple[Adapter, ...]] = {}
    scopes: dict[str, list[Scope]] = {}
    unknown: dict[str, list[Scope]] = {}
    for scope in Scope:
        picked, missing = adapters.expand(merged.harnesses(scope), home)
        chosen[scope] = picked
        for adapter in picked:
            scopes.setdefault(adapter.name, []).append(scope)
        for name in missing:
            unknown.setdefault(name, []).append(scope)
    lines = [
        HarnessLine(
            name=adapter.name,
            summary=adapter.summary,
            known=True,
            detected=adapter.detected(home),
            has_a_machine=adapter.has_a_machine,
            kinds=adapter.kinds,
            scopes=tuple(scopes.get(adapter.name, ())),
        )
        for adapter in adapters.ADAPTERS
    ]
    lines.extend(
        HarnessLine(
            name=name,
            summary="named in a manifest, and no adapter answers to it",
            known=False,
            detected=False,
            has_a_machine=False,
            kinds=(),
            scopes=tuple(where),
        )
        for name, where in unknown.items()
    )
    return tuple(lines), chosen


def survey(
    start: Path,
    *,
    home: Path,
    user_path: Path | None = None,
    cache_root: Path | None = None,
    state_root: Path | None = None,
) -> Inventory:
    """Read the manifests, the record and the disk, and work out what is where."""
    merged = manifest.load(start, user_path=user_path)
    written = record.load(state_root)
    harnesses, chosen = _harness_lines(merged, home)
    reading = _Reading(start=start, home=home, cache_root=cache_root, written=written, chosen=chosen)
    lines = tuple(reading.line(subscription) for subscription in merged.subscriptions)
    collisions = tuple(
        Collision(kind=kind, name=name, wanted_by=wanted)
        for (kind, name), wanted in sorted(merged.collisions().items())
    )
    return Inventory(
        manifests={
            Scope.USER: merged.user.path if merged.user else None,
            Scope.PROJECT: merged.project.path if merged.project else None,
        },
        lines=lines,
        harnesses=harnesses,
        collisions=collisions,
    )


def _pin(line: Line) -> str:
    if line.subscription.pin is not None:
        return f", pinned to {line.subscription.pin}"
    if line.commit is not None:
        return f", at {line.commit}"
    return ", unpinned"


def _print_line(line: Line, out: TextIO) -> None:
    subscription = line.subscription
    named = f' as "{subscription.rename}"' if subscription.rename else ""
    print(f"{INDENT}{subscription.kind} {subscription.name}{named}, from {subscription.source}{_pin(line)}", file=out)
    if line.where is not None:
        print(f"{INDENT * 2}read from {line.where}", file=out)
    if line.problem is not None:
        reported = line.problem.splitlines()
        print(f"{INDENT * 2}problem: {reported[0]}", file=out)
        for rest in reported[1:]:
            print(f"{INDENT * 3}{rest}", file=out)
    for part in line.found:
        renamed = f" (found as {part.found_as})" if part.found_as != part.name else ""
        print(f"{INDENT * 2}{part.name}{renamed}, at {part.relative} in the source", file=out)
        if not part.targets:
            print(f"{INDENT * 3}no harness in this scope takes {PLURAL[subscription.kind]}", file=out)
        for target in part.targets:
            state = "rendered" if target.rendered else "not rendered"
            print(f"{INDENT * 3}{target.harness}: {target.path} ({state})", file=out)


def _print_harness(entry: HarnessLine, out: TextIO) -> None:
    if not entry.known:
        print(f"{INDENT}{entry.name}: {entry.summary}", file=out)
        print(f"{INDENT * 2}named by {joined(SCOPE_NAMED[scope] for scope in entry.scopes)}", file=out)
        return
    if not entry.has_a_machine:
        presence = "has no machine, so it arrives only by being named"
    else:
        presence = "detected on this machine" if entry.detected else "not detected on this machine"
    takes = joined(PLURAL[kind] for kind in entry.kinds) or "nothing"
    rendering = (
        f"rendering for {joined(SCOPE_NAMED[scope] for scope in entry.scopes)}"
        if entry.scopes
        else "in no manifest's harness list"
    )
    print(f"{INDENT}{entry.name}: {presence}", file=out)
    print(f"{INDENT * 2}takes {takes}, and is {rendering}", file=out)


def text(inventory: Inventory, out: TextIO) -> None:
    """The report a person reads: grouped by scope, and silent about nothing."""
    for scope in Scope:
        path = inventory.manifests[scope]
        where = str(path) if path is not None else "no manifest found"
        print(f"{SCOPE_TITLE[scope]} ({where})", file=out)
        lines = inventory.of_scope(scope)
        if not lines:
            print(NOTHING, file=out)
        for line in lines:
            _print_line(line, out)
        print("", file=out)
    print("Harnesses", file=out)
    for entry in inventory.harnesses:
        _print_harness(entry, out)
    print("", file=out)
    print("Name collisions", file=out)
    if not inventory.collisions:
        print(f"{INDENT}none", file=out)
    for collision in inventory.collisions:
        wanted = joined(f"{entry.source} ({SCOPE_NAMED[entry.scope]})" for entry in collision.wanted_by)
        print(f'{INDENT}{collision.kind} "{collision.name}" is wanted by {wanted}', file=out)
        print(f"{INDENT * 2}fix: subscribe to one of them with `--as <other-name>`", file=out)


def payload(inventory: Inventory) -> dict[str, Any]:
    """The same information as data, which is what the skill reads."""
    return {
        "manifests": {str(scope): None if path is None else str(path) for scope, path in inventory.manifests.items()},
        "subscriptions": [
            {
                "kind": str(line.subscription.kind),
                "name": line.subscription.name,
                "rendered_name": line.subscription.rendered_name,
                "source": line.subscription.source,
                "pin": line.subscription.pin,
                "scope": str(line.subscription.scope),
                "resolved_to": None if line.where is None else str(line.where),
                "commit": line.commit,
                "problem": line.problem,
                "parts": [
                    {
                        "name": part.name,
                        "found_as": part.found_as,
                        "relative": part.relative,
                        "targets": [
                            {"harness": target.harness, "path": str(target.path), "rendered": target.rendered}
                            for target in part.targets
                        ],
                    }
                    for part in line.found
                ],
            }
            for line in inventory.lines
        ],
        "harnesses": [
            {
                "name": entry.name,
                "known": entry.known,
                "detected": entry.detected,
                "has_a_machine": entry.has_a_machine,
                "kinds": [str(kind) for kind in entry.kinds],
                "scopes": [str(scope) for scope in entry.scopes],
            }
            for entry in inventory.harnesses
        ],
        "collisions": [
            {
                "kind": str(collision.kind),
                "name": collision.name,
                "wanted_by": [
                    {"source": entry.source, "scope": str(entry.scope), "line": entry.line}
                    for entry in collision.wanted_by
                ],
            }
            for collision in inventory.collisions
        ],
    }


def run(out: TextIO, *, as_json: bool, start: Path | None = None, home: Path | None = None) -> Exit:
    """`akit list`. Always succeeds: a failure is a line, not an exit code.

    `doctor` is the command that exits non-zero on a broken setup. This one is
    the inventory you read on the way to it, and a hook that ran it would rather
    be told than stopped.
    """
    inventory = survey(start or Path.cwd(), home=home or Path.home())
    if as_json:
        print(json.dumps(payload(inventory), indent=2), file=out)
    else:
        text(inventory, out)
    return Exit.OK


__all__ = ["Collision", "Found", "HarnessLine", "Inventory", "Line", "Target", "payload", "run", "survey", "text"]
