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
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

from federated_agent_kits import adapters, cache, discovery, manifest, record, sources
from federated_agent_kits.adapters import Adapter
from federated_agent_kits.exits import AkitError, Exit
from federated_agent_kits.manifest import Kind, Merged, Scope, Subscription
from federated_agent_kits.reporting import (
    INDENT,
    KIND_TITLE,
    NOTHING,
    ORDERING,
    PLURAL,
    SCOPE_NAMED,
    SHORT,
    SINGULAR,
    Column,
    group,
    joined,
    scope_title,
    section,
    wrapped,
)
from federated_agent_kits.styling import Style

#: What `list` says about a harness and the order of its rules. Two rules can
#: contradict each other and the manifest decides which wins, but only as far as
#: the text we write: a harness reading one file of ours gets the sequence, and
#: a harness reading a directory is told by its own documentation not to depend
#: on one (DESIGN.md section 7). Nobody should have to learn which from
#: behaviour.
ORDER: dict[bool, str] = {
    True: "reads rules in the order the manifest lists them",
    False: "promises no order between rules, so two that contradict are a coin toss",
}

#: What a machineless harness is told to do instead of being detected.
NAMING = "needs listing by name in a project's manifest"


@dataclass(frozen=True)
class Target:
    """Where one part would land for one harness, and whether it is there."""

    harness: str
    path: Path
    rendered: bool
    region: str | None = None
    """The marker id, where this lands inside a file somebody else owns."""

    @property
    def described(self) -> str:
        """How this reads in a sentence, since a block is not a path."""
        if self.region is None:
            return str(self.path)
        return f'"{self.region}" block in {self.path}'


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
    orders_rules: bool
    """Whether this harness reads our rules in the order the manifest put them."""

    kinds: tuple[Kind, ...]
    scopes: tuple[Scope, ...]
    """The manifests whose `harnesses:` list puts this one in play."""

    doors: Mapping[Kind, tuple[str, ...]] = field(default_factory=dict)
    """Every destination this harness offers each kind, where it offers a choice.

    Empty for a harness with one destination per kind, which is most of them.
    `akit list` is where somebody finds out there is a choice at all, so the
    names are printed rather than left to the help text (DESIGN.md section 6).
    """

    sending: Mapping[Kind, str] = field(default_factory=dict)
    """Which of them a manifest picked, where one did."""


@dataclass(frozen=True)
class Collision:
    """One rendered name two subscriptions both want (DESIGN.md section 6)."""

    kind: Kind
    name: str
    wanted_by: tuple[Subscription, ...]


@dataclass(frozen=True)
class Shape:
    """What the reader asked the report to look like, as opposed to what it says."""

    by_kind: bool = False
    scopes: tuple[Scope, ...] = ORDERING


#: The whole report, which is what somebody who passed no flag asked for.
WHOLE = Shape()


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
    written: record.Records
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
            region = adapter.region(subscription.kind, subscription.scope, name)
            found.append(
                Target(
                    harness=adapter.name,
                    path=path,
                    rendered=self.written.holds(path, region),
                    region=region,
                )
            )
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


def _taken(adapter: Adapter, doors: Mapping[str, Mapping[Kind, str]]) -> dict[Kind, str]:
    """Which destination this harness is actually taking each kind through.

    The manifest's choice only where the adapter offers it. A name no adapter
    offers is a finding `akit doctor` makes, and a line here saying it was in
    use would tell somebody the opposite of what the renderer will do.
    """
    return {kind: door for kind, door in doors.get(adapter.name, {}).items() if door in adapter.variants(kind)}


def _harness_lines(merged: Merged, home: Path) -> tuple[tuple[HarnessLine, ...], dict[Scope, tuple[Adapter, ...]]]:
    """Every harness worth a line, and the expansion each scope ended up with.

    Every registered adapter gets a line whether or not it is in play, because
    "Copilot is installed and this repository does not render for it" is exactly
    the thing somebody runs `list` to find out.
    """
    chosen: dict[Scope, tuple[Adapter, ...]] = {}
    scopes: dict[str, list[Scope]] = {}
    unknown: dict[str, list[Scope]] = {}
    sending: dict[str, dict[Kind, str]] = {}
    for scope in Scope:
        picked, missing, _ = adapters.expand(merged.harnesses(scope), home, merged.doors(scope))
        chosen[scope] = picked
        for adapter in picked:
            scopes.setdefault(adapter.name, []).append(scope)
            sending.setdefault(adapter.name, {}).update(_taken(adapter, merged.doors(scope)))
        for name in missing:
            unknown.setdefault(name, []).append(scope)
    lines = [
        HarnessLine(
            name=adapter.name,
            summary=adapter.summary,
            known=True,
            detected=adapter.detected(home),
            has_a_machine=adapter.has_a_machine,
            orders_rules=adapter.orders(Kind.RULE, Scope.PROJECT),
            doors={kind: adapter.variants(kind) for kind in adapter.kinds if adapter.variants(kind)},
            sending=sending.get(adapter.name, {}),
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
            orders_rules=False,
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
    written = record.load_all(start, state_root=state_root)
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
        return f", pinned to {line.subscription.pin[:SHORT]}"
    if line.commit is not None:
        return f", at {line.commit[:SHORT]}"
    return ", unpinned"


def _origin(line: Line) -> tuple[str, str, str]:
    """What two subscriptions have to share to be printed under one heading."""
    return (line.subscription.source, _pin(line), "" if line.where is None else str(line.where))


def _grouped(lines: Iterable[Line]) -> dict[tuple[str, str, str], list[Line]]:
    """The lines of one scope, by the source they came from, in the manifest's order."""
    groups: dict[tuple[str, str, str], list[Line]] = {}
    for line in lines:
        groups.setdefault(_origin(line), []).append(line)
    return groups


def _print_targets(part: Found, kind: Kind, out: TextIO, style: Style) -> None:
    """One column of marks, one harness each, and where that harness takes it."""
    if not part.targets:
        print(f"{INDENT}no harness in this scope takes {PLURAL[kind]}", file=out)
        return
    column = Column.of((target.harness for target in part.targets), style, indent=INDENT)
    for target in part.targets:
        stale = "" if target.rendered else " (not rendered)"
        column.marked(target.harness, f"{style.place(target.described)}{stale}", out, present=target.rendered)


def _print_problem(line: Line, out: TextIO) -> None:
    if line.problem is None:
        return
    reported = line.problem.splitlines()
    wrapped(f"problem: {reported[0]}", reported[1:], out)


def _part_suffix(part: Found, style: Style) -> str:
    """Where a part came from, said only when the name on disk is not the source's."""
    if part.found_as == part.name:
        return ""
    return f" ({part.found_as}, from {style.place(part.relative)})"


def _print_by_source(lines: tuple[Line, ...], out: TextIO, style: Style) -> None:
    """The default shape: one heading per source, and its kits under it."""
    for (source, pin, where), together in _grouped(lines).items():
        print(f"From {style.source(source)}{pin}:", file=out)
        if where:
            print(f"{INDENT}read from {style.place(where)}", file=out)
        for line in together:
            kind = line.subscription.kind
            for part in line.found:
                print(f"- {SINGULAR[kind]} {style.kit(part.name)}{_part_suffix(part, style)}", file=out)
                _print_targets(part, kind, out, style)
            if not line.found:
                print(f"- {SINGULAR[kind]} {style.kit(line.subscription.name)}", file=out)
                _print_problem(line, out)
        print("", file=out)


def _print_by_kind(lines: tuple[Line, ...], out: TextIO, style: Style) -> None:
    """`--by-kind`: every skill, then every rule, each saying where it came from."""
    for kind in Kind:
        of_kind = [line for line in lines if line.subscription.kind is kind]
        if not of_kind:
            continue
        group(KIND_TITLE[kind], out, style)
        for line in of_kind:
            origin = f"from {style.source(line.subscription.source)}{_pin(line)}"
            for part in line.found:
                print(f"- {style.kit(part.name)}{_part_suffix(part, style)}, {origin}", file=out)
                _print_targets(part, kind, out, style)
            if not line.found:
                print(f"- {style.kit(line.subscription.name)}, {origin}", file=out)
                _print_problem(line, out)
        print("", file=out)


def _print_harness(entry: HarnessLine, column: Column, out: TextIO) -> None:
    """One harness this machine either has or does not, with its mark."""
    if not entry.known:
        column.marked(entry.name, entry.summary, out, present=False)
        print(f"{INDENT * 2}named by {joined(SCOPE_NAMED[scope] for scope in entry.scopes)}", file=out)
        return
    column.marked(entry.name, _presence(entry), out, present=entry.detected)
    print(f"{INDENT * 2}takes {_takes(entry)}, and {_rendering(entry)}", file=out)
    if Kind.RULE in entry.kinds:
        print(f"{INDENT * 2}{ORDER[entry.orders_rules]}", file=out)
    _print_doors(entry, out)


def _print_doors(entry: HarnessLine, out: TextIO) -> None:
    """The destinations this harness offers a kind, and which one it is taking.

    Printed only where there is a choice, because "this harness has one place
    for skills" is not news and every harness would otherwise carry two lines
    nobody reads.
    """
    for kind, offered in entry.doors.items():
        taken = entry.sending.get(kind, offered[0])
        rest = [door for door in offered if door != taken]
        print(f"{INDENT * 2}takes {kind.value} through {taken}, and could take them through {joined(rest)}", file=out)


def _presence(entry: HarnessLine) -> str:
    return "detected on this machine" if entry.detected else "not detected on this machine"


def _takes(entry: HarnessLine) -> str:
    return joined(PLURAL[kind] for kind in entry.kinds) or "nothing"


def _rendering(entry: HarnessLine) -> str:
    if not entry.scopes:
        return "is in no manifest's harness list"
    return f"is rendering for {joined(SCOPE_NAMED[scope] for scope in entry.scopes)}"


def _print_machineless(entry: HarnessLine, column: Column, out: TextIO) -> None:
    """One harness with nothing to detect, so no mark and nothing to be absent from.

    A mark here would be a claim about this machine, and a harness that runs on
    somebody else's has none to make. What decides whether it is in play is a
    manifest naming it, which is what the line says instead.
    """
    whether = _rendering(entry) if entry.scopes else NAMING
    column.listed(entry.name, f"takes {_takes(entry)}, and {whether}", out)
    _print_doors(entry, out)


def _print_harnesses(inventory: Inventory, out: TextIO, style: Style) -> None:
    machineless = [entry for entry in inventory.harnesses if entry.known and not entry.has_a_machine]
    on_this_machine = [entry for entry in inventory.harnesses if entry.has_a_machine or not entry.known]
    column = Column.of((entry.name for entry in inventory.harnesses), style)
    section("Harnesses", out, style)
    for entry in on_this_machine:
        _print_harness(entry, column, out)
    if machineless:
        print("", file=out)
        group("Harnesses with no machine", out, style)
        for entry in machineless:
            _print_machineless(entry, column, out)
    print("", file=out)


def text(inventory: Inventory, out: TextIO, *, shape: Shape = WHOLE, style: Style | None = None) -> None:
    """The report a person reads: grouped by scope, and silent about nothing."""
    shown = style or Style.plain()
    for scope in shape.scopes:
        section(scope_title(scope, inventory.manifests[scope]), out, shown)
        lines = inventory.of_scope(scope)
        if not lines:
            print(f"{NOTHING}\n", file=out)
        elif shape.by_kind:
            _print_by_kind(lines, out, shown)
        else:
            _print_by_source(lines, out, shown)
    _print_harnesses(inventory, out, shown)
    section("Name collisions", out, shown)
    if not inventory.collisions:
        print("none", file=out)
    for collision in inventory.collisions:
        wanted = joined(f"{shown.source(entry.source)} ({SCOPE_NAMED[entry.scope]})" for entry in collision.wanted_by)
        print(f'{collision.kind} "{shown.kit(collision.name)}" is wanted by {wanted}', file=out)
        print(f"{INDENT}fix: subscribe to one of them with `--as <other-name>`", file=out)


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
                            {
                                "harness": target.harness,
                                "path": str(target.path),
                                "region": target.region,
                                "rendered": target.rendered,
                            }
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
                "orders_rules": entry.orders_rules,
                "doors": {kind.value: list(offered) for kind, offered in entry.doors.items()},
                "sending": {kind.value: door for kind, door in entry.sending.items()},
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


def scopes_from(*, only_global: bool, only_project: bool) -> tuple[Scope, ...]:
    """Which sections the report prints, from the two flags that narrow it."""
    if only_global == only_project:
        return ORDERING
    return (Scope.USER,) if only_global else (Scope.PROJECT,)


def run(
    out: TextIO, *, as_json: bool, shape: Shape = WHOLE, start: Path | None = None, home: Path | None = None
) -> Exit:
    """`akit list`. Always succeeds: a failure is a line, not an exit code.

    `doctor` is the command that exits non-zero on a broken setup. This one is
    the inventory you read on the way to it, and a hook that ran it would rather
    be told than stopped.
    """
    inventory = survey(start or Path.cwd(), home=home or Path.home())
    if as_json:
        print(json.dumps(payload(inventory), indent=2), file=out)
    else:
        text(inventory, out, shape=shape, style=Style.of(out))
    return Exit.OK


__all__ = [
    "Collision",
    "Found",
    "HarnessLine",
    "Inventory",
    "Line",
    "Shape",
    "Target",
    "payload",
    "run",
    "scopes_from",
    "survey",
    "text",
]
