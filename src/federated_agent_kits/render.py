"""`akit render`: make the files on disk match the manifests, twice in a row.

The only command that writes kit files, and the one every other verb ends with.
Three properties decide the shape of everything below, and all three are from
DESIGN.md section 10.

**It never deletes a file it cannot prove it wrote.** The render record is the
whole candidate list, so withdrawal has three outcomes rather than two: a copy
whose hash still matches is deleted, a copy somebody edited is left alone and
named, and a file that is not in the record is not our business whatever
directory it is sitting in. A hand-written skill beside a rendered one is
therefore safe by construction rather than by a guess about what our files look
like.

**It is idempotent.** A file whose bytes already agree with the source is not
rewritten, so a second render reports a no-op rather than performing one, which
is what makes this safe from a git hook or the end of another command.

**It never fetches.** Resolution is offline, so a render can change files on
disk and never what a kit contains. Only `add` and `update` move a pin.

Two cases suspend withdrawal entirely, and both are deliberate.

A narrowing flag means this is the render you want now rather than the setup you
keep, and `--no-harness` that deleted the files it skipped would be a delete
command wearing a skip command's name. What it leaves behind are orphans
`akit doctor` reports.

A subscription that could not be resolved means the candidate list is short by
however much that source explained. Deleting on an incomplete list is how an
offline render takes away the kits a cached source would have kept, so a render
with a problem in it writes what it can, withdraws nothing, and says so.

**Skills and rules. Agents land with T13**, so a subscription of that kind is
reported as waiting rather than silently producing nothing.

**A rule is written in one of two places, and the second is not a file of
ours.** A harness that reads a directory of rules gets one file per rule, which
behaves exactly like a skill from here on. A harness that reads one shared file
gets a block between markers inside it, and that is why everything below is
keyed by a spot rather than by a path: a path alone cannot tell two rules in one
`AGENTS.md` apart, and withdrawing one of them has to leave the other and the
prose around both (DESIGN.md section 6).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

from federated_agent_kits import (
    adapters,
    cache,
    discovery,
    ignore,
    leaks,
    manifest,
    privacy,
    record,
    rules,
    sources,
    targets,
)
from federated_agent_kits.adapters import Adapter
from federated_agent_kits.adapters.adapter import SEPARATOR
from federated_agent_kits.cache import Privacy
from federated_agent_kits.exits import AkitError, Exit, RefusalError, UsageError
from federated_agent_kits.listing import PLURAL, SCOPE_TITLE, joined
from federated_agent_kits.manifest import Kind, Merged, Scope, Subscription
from federated_agent_kits.record import Explanation, Record, Records, Region, Spot, Written

INDENT = "  "

#: The kinds this build actually puts on disk. Agents are T13, and a kind that
#: is not here is reported as waiting rather than skipped in silence: a
#: subscription that produces nothing and says nothing is the failure
#: DESIGN.md section 3 spends rule 5 on.
RENDERED: tuple[Kind, ...] = (Kind.SKILL, Kind.RULE)

#: The three outcomes of the withdrawal table in DESIGN.md section 10, named
#: once so the reporter and the engine cannot drift into two spellings.
DELETED = "deleted"
KEPT = "kept"
GONE = "gone"

WAITING: dict[Kind, str] = {
    Kind.AGENT: "every adapter declines agents for now; they land with T13",
}

#: The count at which a noun stops needing its plural.
ONE = 1


#: Directories a copy never descends into. A source's skill is a directory of
#: files, and the only thing in one that is not part of the kit is a repository.
SKIPPED = frozenset({".git"})


@dataclass(frozen=True)
class Placement:
    """Where one part landed, and for which harnesses, after the writing was done."""

    path: Path
    """A skill's directory, a rule's file, or the file a rule's block sits in."""

    harnesses: tuple[str, ...]
    written: int
    """Spots that appeared or changed. Zero is the ordinary second render."""

    unchanged: int
    region: str | None = None
    """The marker id, when this landed inside a file we do not own."""

    spots: tuple[Spot, ...] = ()
    """What this placement is counting, which a path alone cannot say.

    Two rules in one `AGENTS.md` are two placements on one path, so attributing
    a change by "is this under that directory" would credit each of them with
    the other's work.
    """


@dataclass(frozen=True)
class Entry:
    """One subscription, as much of it as this render could do."""

    subscription: Subscription
    name: str
    found_as: str
    relative: str
    placements: tuple[Placement, ...] = ()
    problem: str | None = None
    waiting: str | None = None
    """Why this kind produced nothing, for the kinds a later task renders."""


@dataclass(frozen=True)
class Withdrawal:
    """One thing the record explained and nothing in scope explains any more."""

    path: Path
    action: str
    """`deleted`, `kept` for an edited copy, or `gone` for one already removed."""

    region: str | None = None
    """The marker id, for a rule removed from a file that stays where it is."""

    @property
    def described(self) -> str:
        """How this reads in a sentence, since a block is not a path."""
        if self.region is None:
            return str(self.path)
        return f'the "{self.region}" block in {self.path}'


@dataclass(frozen=True)
class Outcome:
    """Everything one render did, before any of it has been printed."""

    manifests: dict[Scope, Path | None]
    harnesses: dict[Scope, tuple[str, ...]]
    entries: tuple[Entry, ...]
    withdrawals: tuple[Withdrawal, ...] = ()
    pruned: tuple[Path, ...] = ()
    ignored: tuple[tuple[Path, tuple[str, ...], bool], ...] = ()
    """Each repository whose `.gitignore` was considered, what it now lists, and
    whether the file changed."""

    unknown: tuple[str, ...] = ()
    suspended: str | None = None
    """Why nothing was withdrawn, or `None` when withdrawal ran."""

    checking: bool = False
    """Whether this was `--check`, which reports a verdict rather than a diary."""

    unexplained: tuple[Path, ...] = ()
    """Committed files nothing in the manifest accounts for, which only `--check` looks for."""

    @property
    def problems(self) -> tuple[Entry, ...]:
        return tuple(entry for entry in self.entries if entry.problem is not None)

    written: int = 0
    """Files that appeared or changed, counted once each.

    Not the sum of the placements. A file both scopes explain has a placement
    per scope, which is the honest per-line report and would double the total:
    a dotfiles render of one two-file skill would say it wrote four.
    """

    unchanged: int = 0
    blocks_written: int = 0
    """Rules that appeared or changed inside a file we do not own.

    Counted apart from files, because the summary would otherwise say it wrote
    three files into a repository where it edited one and left two paragraphs in
    it alone.
    """

    blocks_unchanged: int = 0

    @property
    def deleted(self) -> tuple[Withdrawal, ...]:
        return tuple(entry for entry in self.withdrawals if entry.action == DELETED)

    @property
    def quiet(self) -> bool:
        """Whether this render changed nothing at all, which it usually should."""
        changed = any(changed for _, _, changed in self.ignored)
        return not (self.written or self.blocks_written or self.deleted or self.pruned or changed)

    @property
    def stale(self) -> tuple[str, ...]:
        """What a committed render would have to change to be correct, in sentences.

        Three things can be out of date and all three are committed. A file
        whose bytes differ from what the manifest says, a file sitting in a
        directory we own that the manifest no longer accounts for, and the
        ignore block, which is the inverse of what gets committed and so goes
        stale the moment a machineless harness is named (DESIGN.md section 6).
        """
        found: list[str] = []
        if self.written or self.blocks_written:
            found.append(f"{counted(self.written + self.blocks_written, 'committed file')} would be written")
        if self.unexplained:
            found.append(f"{counted(len(self.unexplained), 'committed file')} nothing subscribes to any more")
            found.extend(f"  {path}" for path in self.unexplained)
        for root, _, changed in self.ignored:
            if changed:
                found.append(f"the akit block in {root / ignore.GITIGNORE} is out of date")
        return tuple(found)

    def of_scope(self, scope: Scope) -> tuple[Entry, ...]:
        return tuple(entry for entry in self.entries if entry.subscription.scope is scope)

    @property
    def exit_code(self) -> Exit:
        if self.checking and self.stale:
            return Exit.ERROR
        return Exit.ERROR if self.problems or self.unknown else Exit.OK


@dataclass(frozen=True)
class Choices:
    """What the flags narrowed this render to, as one value rather than four.

    Together rather than as separate parameters because they are read together:
    three of the four decide whether withdrawal may run at all, and a caller
    that set one without considering the others is the bug this groups against.
    """

    scopes: tuple[Scope, ...] = tuple(Scope)
    only: tuple[str, ...] = ()
    without: tuple[str, ...] = ()
    prune: bool = False

    @property
    def narrowed(self) -> bool:
        return bool(self.only or self.without)


#: The flags nobody passed: both scopes, every harness the manifests name, and
#: no pruning. A module-level value rather than a default built per call, so
#: "everything" is one object the whole program compares against.
#: The flags nobody passed: both scopes, every harness the manifests name, and
#: no pruning. A module-level value rather than a default built per call, so
#: "everything" is one object rather than a new one on each entry.
EVERYTHING = Choices()


@dataclass(frozen=True)
class Mode:
    """Whether this pass may fetch, may write, and answers with a verdict.

    Three independent facts about one pass, grouped because only one caller
    ever sets any of them. `render` is the default and `--check` is the other,
    and a third combination would be a new command rather than a new flag.
    """

    offline: bool = True
    """False only for `--check`, which runs where there is no cache at all.

    An ordinary render reads the commits already in the cache, so it can change
    files on disk and never what a kit contains. A CI runner has never
    rendered, and has nothing to recompute a committed render from unless it
    fetches the commits its pins already name (DESIGN.md section 10).
    """

    writing: bool = True
    """False is the same walk with every act suspended.

    The copy, the withdrawal, the ignore block and the two record saves all ask
    this before they touch a file, and the counting happens either way.
    """

    checking: bool = False
    """Whether this is judging rather than doing, which changes who it judges for.

    A check drops `detected` and keeps only the harnesses a manifest names that
    have no machine, so its verdict reads the same in every clone.
    """


#: An ordinary render: offline, writing, reporting what it did.
RENDERING = Mode()

#: `--check`: fetches what it must, writes nothing, answers yes or no.
CHECKING = Mode(offline=False, writing=False, checking=True)

#: The half of the world `--check` looks at. Your own subscriptions render to
#: machine-level directories that no repository commits, so they cannot go
#: stale and are not its business.
COMMITTED = Choices(scopes=(Scope.PROJECT,))


@dataclass(frozen=True)
class Directories:
    """The roots this render reads and writes under.

    Every one of them has a per-platform answer this package already knows, and
    every one is a parameter so that a test can put the whole machine inside a
    `tmp_path` rather than trusting a bug not to reach the developer's own
    config, cache or state directory.
    """

    home: Path
    user_manifest: Path | None = None
    cache: Path | None = None
    state: Path | None = None


@dataclass
class _Target:
    """One spot several subscriptions and harnesses may all want the same bytes in."""

    data: bytes
    """What goes there, computed at plan time.

    Bytes rather than the file to copy from, because a rule is translated on the
    way out and a skill is not, and the two have to arrive at the same engine.
    """

    digest: str
    explained_by: set[str] = field(default_factory=set)
    harnesses: set[str] = field(default_factory=set)
    sources: set[str] = field(default_factory=set)
    """The source keys behind this spot, which the leak refusal asks about.

    Kept apart from `explained_by` rather than parsed back out of it: an
    explanation is a sentence for a record, and a refusal that recovered a URL
    by splitting one on colons would break on the first `git@host:org/repo.git`.
    """

    scopes: set[Scope] = field(default_factory=set)
    """Which records get an entry for this file.

    Usually one. Both when your home directory is itself a git repository, where
    the project anchor and the user root are the same directory and the two
    scopes land on one path (DESIGN.md section 6).
    """


def counted(number: int, noun: str) -> str:
    """`no files`, `1 file`, `3 files`, because a report is sentences and not a log."""
    if number == 0:
        return f"no {noun}s"
    return f"{number} {noun}" if number == ONE else f"{number} {noun}s"


def _files_of(directory: Path) -> tuple[Path, ...]:
    """Every file inside a skill, in a stable order, with a repository left out."""
    found: list[Path] = []
    for child in sorted(directory.iterdir()):
        if child.name in SKIPPED:
            continue
        if child.is_dir():
            found.extend(_files_of(child))
        else:
            found.append(child)
    return tuple(found)


def _narrow(
    picked: tuple[Adapter, ...], only: Sequence[str] | None, without: Sequence[str] | None
) -> tuple[Adapter, ...]:
    """The expanded harness list, narrowed by the flags, which can never widen it."""
    chosen = picked
    if only:
        chosen = tuple(adapter for adapter in chosen if adapter.name in set(only))
    if without:
        chosen = tuple(adapter for adapter in chosen if adapter.name not in set(without))
    return chosen


def _check_names(named: Sequence[str] | None, flag: str) -> None:
    """A harness nobody knows, typed on the command line, is a usage error.

    Different from the same name in a manifest, which `list` reports and this
    command carries through: a manifest is a file somebody else may have written
    for a harness you have not installed, and a flag is what you typed just now.
    """
    unknown = [name for name in named or () if name not in adapters.BY_NAME]
    if unknown:
        known = ", ".join(sorted(adapters.BY_NAME))
        raise UsageError(f"{flag} names a harness no adapter knows: {', '.join(unknown)}.\n  Known harnesses: {known}.")


@dataclass(frozen=True)
class _Pass:
    """One render, so the six things every subscription needs travel together."""

    start: Path
    home: Path
    cache_root: Path | None
    before: Records
    chosen: dict[Scope, tuple[Adapter, ...]]
    offline: bool = True
    """Whether resolution may go near the network, which only `--check` sets.

    An ordinary render reads the commits already in the cache, so it can change
    files on disk and never what a kit contains. A check runs where there is no
    cache at all, because a CI runner has never rendered, and has nothing to
    recompute a committed render from unless it fetches the commits its pins
    already name (DESIGN.md section 10).
    """

    writing: bool = True
    """Whether anything on disk may actually change.

    False is the same walk with every act suspended, which is what `--check`
    is: the copy, the withdrawal, the ignore block and the two record saves all
    ask this before they touch a file, and the counting happens either way.
    """

    resolutions: list[tuple[str, cache.Resolved]] = field(default_factory=list)
    """Every source this pass resolved, so the ones it fetched can be classified.

    An ordinary render fetches nothing and this stays empty of classifications,
    which makes carrying it a no-op. `--check` fetches, and what it learns on
    the way is the privacy of each source, which is the one fact the leak
    refusal cannot work out for itself (DESIGN.md section 8).
    """

    def anchor(self, adapter: Adapter, scope: Scope) -> Path:
        """The base a target is computed against, which is the harness's and not ours."""
        if scope is Scope.USER:
            return self.home
        return adapter.anchor(self.start) or self.start

    def resolve(self, subscription: Subscription) -> cache.Resolved:
        anchor = self.home if subscription.scope is Scope.USER else (manifest.worktree_root(self.start) or self.start)
        key = sources.parse(subscription.source)
        found = cache.resolve(
            key, pin=subscription.pin, anchor=anchor, cache_root=self.cache_root, offline=self.offline
        )
        self.resolutions.append((subscription.source, found))
        return found


@dataclass(frozen=True)
class _Wanted:
    """One found part, as the thing being placed rather than as four arguments."""

    subscription: Subscription
    part: discovery.Part
    name: str
    """What it is rendered as, which is the `as:` name when there is one."""

    @property
    def explanation(self) -> str:
        return str(Explanation(kind=self.subscription.kind, source=self.subscription.source, name=self.name))

    @property
    def scope(self) -> Scope:
        return self.subscription.scope


def _spot_wanted(writes: dict[Spot, _Target], spot: Spot, data: bytes, wanted: _Wanted, harness: str) -> str | None:
    """Add one wanted spot to the plan, or say why it could not be added.

    A spot two subscriptions want with different bytes is a collision the
    manifest could not refuse, because a `"*"` cannot know what it will match.
    It is reported rather than resolved, and the first writer keeps it: picking
    a winner silently is what `as:` exists to avoid.
    """
    digest = record.digest(data)
    standing = writes.get(spot)
    if standing is None:
        writes[spot] = _Target(
            data=data,
            digest=digest,
            explained_by={wanted.explanation},
            harnesses={harness},
            sources={wanted.subscription.source},
            scopes={wanted.scope},
        )
        return None
    if standing.digest != digest:
        path, region = spot
        where = path if region is None else f'the "{region}" block in {path}'
        return (
            f"another subscription already wants different bytes at {where}; "
            f"this copy was not written. Give one of them a different name with `as:`"
        )
    standing.explained_by.add(wanted.explanation)
    standing.harnesses.add(harness)
    standing.sources.add(wanted.subscription.source)
    standing.scopes.add(wanted.scope)
    return None


def _plan_skill(walk: _Pass, wanted: _Wanted, writes: dict[Spot, _Target]) -> tuple[list[Placement], str | None]:
    """A skill, copied unchanged into every directory a harness in scope reads."""
    placements: list[Placement] = []
    clash: str | None = None
    for adapter in walk.chosen[wanted.scope]:
        directory = adapter.target(
            wanted.subscription.kind, wanted.scope, wanted.name, walk.anchor(adapter, wanted.scope)
        )
        if directory is None:
            continue
        spots: list[Spot] = []
        for file in _files_of(wanted.part.path):
            spot = ((directory / file.relative_to(wanted.part.path)).resolve(), None)
            problem = _spot_wanted(writes, spot, file.read_bytes(), wanted, adapter.name)
            if problem is not None:
                clash = problem
                continue
            spots.append(spot)
        placements.append(
            Placement(path=directory, harnesses=(adapter.name,), written=0, unchanged=0, spots=tuple(spots))
        )
    return placements, clash


def _plan_rule(walk: _Pass, wanted: _Wanted, writes: dict[Spot, _Target]) -> tuple[list[Placement], str | None]:
    """A rule, translated per harness into whichever of the two shapes it wants.

    One source file becomes a file of ours for a harness that reads a directory,
    carrying whatever frontmatter that harness needs in order to load it at all,
    and a block between markers for a harness that reads one shared file. The
    translation is why rules are not written once for everybody the way skills
    are (DESIGN.md section 7).
    """
    placements: list[Placement] = []
    clash: str | None = None
    data = wanted.part.path.read_bytes()
    for adapter in walk.chosen[wanted.scope]:
        target = adapter.target(wanted.subscription.kind, wanted.scope, wanted.name, walk.anchor(adapter, wanted.scope))
        if target is None:
            continue
        region = adapter.region(wanted.subscription.kind, wanted.name)
        written = (
            rules.as_block(data, name=wanted.name)
            if region is not None
            else rules.as_file(data, name=wanted.name, keys=adapter.rule_frontmatter)
        )
        spot = (target.resolve(), region)
        problem = _spot_wanted(writes, spot, written, wanted, adapter.name)
        if problem is not None:
            clash = problem
            continue
        placements.append(
            Placement(path=target, harnesses=(adapter.name,), written=0, unchanged=0, region=region, spots=(spot,))
        )
    return placements, clash


def _plan_part(
    walk: _Pass,
    subscription: Subscription,
    part: discovery.Part,
    writes: dict[Spot, _Target],
) -> Entry:
    """Where one found part goes, added to the writes and reported as a line."""
    wanted = _Wanted(subscription=subscription, part=part, name=subscription.rename or part.name)
    plan = _plan_skill if subscription.kind is Kind.SKILL else _plan_rule
    try:
        placements, clash = plan(walk, wanted, writes)
    except AkitError as error:
        return _unrendered(subscription, problem=str(error))
    return Entry(
        subscription=subscription,
        name=wanted.name,
        found_as=part.name,
        relative=part.relative,
        placements=_shared(placements),
        problem=clash,
    )


def _shared(placements: Iterable[Placement]) -> tuple[Placement, ...]:
    """One line per place, naming every harness that reads it.

    Both adapters shipped today write skills to the same directory, so the
    honest report is one copy wanted by two harnesses rather than the same path
    printed twice (DESIGN.md section 7). Rules group by the block as well as by
    the file, since two of them in one `AGENTS.md` are two places and not one.
    """
    grouped: dict[Spot, tuple[list[str], list[Spot]]] = {}
    for place in placements:
        names, spots = grouped.setdefault((place.path, place.region), ([], []))
        names.extend(place.harnesses)
        spots.extend(spot for spot in place.spots if spot not in spots)
    return tuple(
        Placement(path=path, harnesses=tuple(names), written=0, unchanged=0, region=region, spots=tuple(spots))
        for (path, region), (names, spots) in grouped.items()
    )


def _unrendered(subscription: Subscription, *, problem: str | None = None, waiting: str | None = None) -> Entry:
    """A subscription that produced no files, and the one sentence saying why."""
    return Entry(
        subscription=subscription,
        name=subscription.rendered_name,
        found_as=subscription.name,
        relative="",
        problem=problem,
        waiting=waiting,
    )


def _plan(walk: _Pass, merged: Merged) -> tuple[list[Entry], dict[Spot, _Target]]:
    """Every subscription as the spots it wants filled, with nothing written yet.

    The order is the manifest's, and for rules that is the whole of the promise
    DESIGN.md section 7 makes: the blocks in one shared file come out in the
    order this loop met them.
    """
    writes: dict[Spot, _Target] = {}
    entries: list[Entry] = []
    for subscription in merged.subscriptions:
        if subscription.kind not in RENDERED:
            entries.append(_unrendered(subscription, waiting=WAITING[subscription.kind]))
            continue
        try:
            resolved = walk.resolve(subscription)
        except AkitError as error:
            entries.append(_unrendered(subscription, problem=str(error)))
            continue
        parts = discovery.named(
            resolved.root,
            subscription.kind,
            subscription.name,
            extra_directories=adapters.source_directories(subscription.kind),
            rendered=walk.before.paths,
        )
        if not parts:
            wanted = "anything" if subscription.is_wildcard else f'a {subscription.kind} called "{subscription.name}"'
            entries.append(_unrendered(subscription, problem=f"this source does not hold {wanted}"))
            continue
        entries.extend(_plan_part(walk, subscription, part, writes) for part in parts)
    return entries, writes


def _perform(
    entries: list[Entry], writes: dict[Spot, _Target], removals: Iterable[Region], *, writing: bool = True
) -> tuple[list[Entry], dict[Spot, bool]]:
    """Fill every planned spot whose bytes are not already there, and count both.

    The comparison is the hash rather than the modification time. A render that
    rewrote an identical file would still be idempotent on disk and would churn
    every `mtime` a harness, a watcher or a build system might be reading.

    Withdrawal has already decided which blocks go, and they arrive here rather
    than being deleted where that decision was made, because a shared file is
    written once: the blocks that stay, the blocks that arrive and the blocks
    that go are one rewrite of one file, not three.

    `writing=False` performs the comparison and skips the write, which is the
    whole of `--check`: what it wants to know is which spots *would* have
    changed, and that is the number this counts either way.
    """
    done: dict[Spot, bool] = {}
    for (target, region), planned in writes.items():
        if region is not None:
            continue
        done[(target, region)] = record.digest_of(target) != planned.digest
        if done[(target, region)] and writing:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(planned.data)
    done.update(_weave(writes, removals, writing=writing))
    counted: list[Entry] = []
    for entry in entries:
        placements = tuple(
            Placement(
                path=place.path,
                harnesses=place.harnesses,
                region=place.region,
                spots=place.spots,
                written=sum(1 for spot in place.spots if done.get(spot)),
                unchanged=sum(1 for spot in place.spots if done.get(spot) is False),
            )
            for place in entry.placements
        )
        counted.append(
            Entry(
                subscription=entry.subscription,
                name=entry.name,
                found_as=entry.found_as,
                relative=entry.relative,
                placements=placements,
                problem=entry.problem,
                waiting=entry.waiting,
            )
        )
    return counted, done


def _weave(writes: dict[Spot, _Target], removals: Iterable[Region], *, writing: bool = True) -> dict[Spot, bool]:
    """Rewrite every file we share, once each, and say which blocks changed.

    A host file is somebody's prose and may not exist yet. It is created when a
    rule wants to be in it and never deleted when the last one leaves, because
    an entry for a block may take its own text out and nothing else
    (DESIGN.md section 6).

    A block counts as written when its text changed *or* when it moved. Order is
    the thing rules have that skills do not, so swapping two rules in a manifest
    rewrites this file while every block in it keeps its bytes, and counting
    bytes alone would report that render as having changed nothing.
    """
    hosts: dict[Path, list[rules.Block]] = {}
    for (path, region), planned in writes.items():
        if region is None:
            continue
        hosts.setdefault(path, []).append(rules.Block(id=region, body=planned.data.decode("utf-8")))
    taken: dict[Path, set[str]] = {}
    for path, region in removals:
        taken.setdefault(path, set()).add(region)
        hosts.setdefault(path, [])
    done: dict[Spot, bool] = {}
    for path, blocks in hosts.items():
        before = path.read_text(encoding="utf-8").replace("\r\n", "\n") if path.is_file() else ""
        standing = rules.blocks_in(before)
        was = [found for found in standing if found in {block.id for block in blocks}]
        for index, block in enumerate(blocks):
            moved = index >= len(was) or was[index] != block.id
            done[(path, block.id)] = moved or standing.get(block.id) != block.body
        after = rules.weave(before, blocks, remove=taken.get(path, set()))
        if after != before and writing:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(after, encoding="utf-8", newline="\n")
    return done


def _tidy(path: Path, boundaries: Iterable[Path]) -> None:
    """Remove the directories a deletion emptied, and stop at the scope's own root.

    A withdrawn skill leaves its directory behind, and a directory with nothing
    in it is a harness being offered an empty kit. The walk stops at the home
    directory or the project anchor, so it can never climb out of the scope it
    was deleting in.
    """
    stops = {Path(entry).resolve() for entry in boundaries}
    directory = path.parent
    while directory not in stops and any(directory.is_relative_to(stop) for stop in stops):
        if not directory.is_dir() or any(directory.iterdir()):
            return
        directory.rmdir()
        directory = directory.parent


def _withdraw(
    before: Mapping[Scope, Record],
    writes: dict[Spot, _Target],
    scopes: Sequence[Scope],
    boundaries: Mapping[Path, set[str]],
) -> tuple[list[Withdrawal], dict[Scope, list[Written]], list[Region]]:
    """The three outcomes of DESIGN.md section 10's withdrawal table, per record.

    One record per root does most of the narrowing by itself: the entries a
    render may consider are the ones in the records it opened, so a render in
    one repository cannot reach another's files however the adapters have moved
    their directories since.

    What is left is the one case where two roots genuinely overlap. A home
    directory that is also a git repository makes the project anchor and the
    user root the same place, so both records can claim one spot. A record this
    run is not rendering still speaks for its own, which is why the sibling is
    read before anything is deleted and why `--global` in a dotfiles repository
    cannot take a file the repository still wants.

    A block is decided here and removed later. Its host holds other blocks and
    somebody's prose, so taking it out is part of the one rewrite that file
    gets rather than a deletion of its own.

    This never runs on a pass that may not write, because every such pass is a
    check and every check suspends withdrawal (`_suspension`). So there is no
    dry run threaded through here: the caller decides, once, whether to call it.
    """
    rendered = set(scopes)
    silent = [record for scope, record in before.items() if scope not in rendered]
    handled: set[Spot] = set()
    done: list[Withdrawal] = []
    removals: list[Region] = []
    kept: dict[Scope, list[Written]] = {}
    for scope, found in before.items():
        staying: list[Written] = []
        kept[scope] = staying
        if scope not in rendered:
            staying.extend(found.written)
            continue
        for entry in found.written:
            if entry.spot in writes:
                continue
            if any(entry.spot in other.spots for other in silent):
                staying.append(entry)
                continue
            if entry.spot in handled:
                continue
            handled.add(entry.spot)
            if entry.current() is None:
                done.append(Withdrawal(path=entry.path, action=GONE, region=entry.region))
            elif not entry.still_a_copy():
                staying.append(entry)
                done.append(Withdrawal(path=entry.path, action=KEPT, region=entry.region))
            elif entry.region is not None:
                removals.append((entry.path, entry.region))
                done.append(Withdrawal(path=entry.path, action=DELETED, region=entry.region))
            else:
                entry.path.unlink()
                _tidy(entry.path, boundaries)
                done.append(Withdrawal(path=entry.path, action=DELETED))
    return done, kept, removals


def _directories(picked: Iterable[Adapter], walk: _Pass, scopes: Sequence[Scope]) -> dict[Path, set[str]]:
    """Every directory these harnesses own, per scope root.

    Taken from the adapters rather than from what was written, because both
    callers need the directories a kit *could* be in: one is looking for a kit
    nothing explains, and the other for the kits a withdrawal is allowed to
    consider at all.

    A file we share is not one of them. `AGENTS.md` is somebody's prose with our
    paragraphs in it, so it is neither a directory to tidy, nor a directory to
    prune, nor a line to put in a `.gitignore`.
    """
    found: dict[Path, set[str]] = {}
    for scope in scopes:
        for adapter in picked:
            for kind in RENDERED:
                destination = adapter.destination(kind, scope)
                if destination is None or destination.write is None or adapter.shares_the_file(kind):
                    continue
                found.setdefault(walk.anchor(adapter, scope), set()).add(destination.write)
    return found


def _prune(owned: dict[Path, set[str]], explained: set[Path]) -> list[Path]:
    """Delete what nothing explains in a directory we own, one kit at a time.

    The one deletion this tool cannot prove is safe, which is why it is a flag.
    A kit rendered before the record was lost is indistinguishable from a kit
    somebody wrote by hand in the same directory, so this takes both and the
    other three commands take neither.
    """
    removed: list[Path] = []
    for base, written in owned.items():
        for relative in sorted(written):
            directory = base.joinpath(*relative.split(SEPARATOR))
            if not directory.is_dir():
                continue
            for child in sorted(directory.iterdir()):
                if any(path == child or path.is_relative_to(child) for path in explained):
                    continue
                _remove(child)
                removed.append(child)
    return removed


def _remove(path: Path) -> None:
    """One file, or one kit directory and everything in it."""
    if path.is_dir():
        for child in sorted(path.rglob("*"), key=lambda entry: len(entry.parts), reverse=True):
            child.rmdir() if child.is_dir() else child.unlink()
        path.rmdir()
    else:
        path.unlink()


def _committed(picked: Iterable[Adapter], scope: Scope) -> set[str]:
    """The directories a harness with no machine reads, which this repository commits.

    The inverse of the ignore block, computed rather than maintained (DESIGN.md
    section 6). Nobody runs `akit` in a cloud agent's checkout, so a file it
    reads and that is not committed does not exist, and naming that harness is
    what takes its directories out of the block.

    **A directory with two readers is committed if either of them commits**,
    which is why this answers in directory names rather than per harness. Skills
    share one directory, so naming the cloud agent puts the skills opencode was
    reading privately into the repository's history. That is the intended
    behaviour and the reason the leak refusal lands in the same task.
    """
    found: set[str] = set()
    for adapter in adapters.machineless(picked):
        for kind in RENDERED:
            destination = adapter.destination(kind, scope)
            found.update({} if destination is None or destination.write is None else {destination.write})
    return found


def _ignore_block(
    walk: _Pass,
    owned: dict[Path, set[str]],
    explained: Iterable[Path],
    scopes: Sequence[Scope],
    *,
    keeps_a_record: bool,
) -> tuple[tuple[Path, tuple[str, ...], bool], ...]:
    """Maintain the repository's ignore block, from the directories it wrote into.

    From what is on disk rather than from what the adapters declare, which is
    what lets a directory that stops being rendered leave the block on the next
    render (DESIGN.md section 6). An adapter-shaped list would keep ignoring a
    directory for as long as the harness was installed, whether or not anything
    of ours was ever in it.

    The repository's own record is in that list too, and it is the one entry
    that is not a rendered kit. It is state about this machine sitting inside a
    shared repository, so it is ignored for the same reason everything else here
    is, and it leaves the block on the render that removes it.

    **Whether it is listed follows from what this render would leave behind,
    not from the file being there now.** A CI runner has never rendered, so the
    record is absent on every fresh checkout, and a block computed from the file
    on disk would call every repository's `.gitignore` stale the moment
    `--check` looked at it.

    Only inside a repository, and only for the project scope: your home
    directory is not a working tree, so nothing rendered there can be committed
    by accident.

    **What a machineless harness reads is subtracted**, so this block and the
    committed set are each other's inverse and nobody keeps two lists in step by
    hand.
    """
    root = manifest.worktree_root(walk.start)
    if root is None or Scope.PROJECT not in scopes:
        return ()
    committed = _committed(walk.chosen.get(Scope.PROJECT, ()), Scope.PROJECT)
    inside = [path for path in explained if path.is_relative_to(root)]
    listed = {
        f"{directory.relative_to(root).as_posix()}/"
        for base, written in owned.items()
        for relative in written
        if relative not in committed
        for directory in (base.joinpath(*relative.split(SEPARATOR)),)
        if directory.is_relative_to(root) and any(path.is_relative_to(directory) for path in inside)
    }
    if keeps_a_record:
        listed.add(f"{record.DIRECTORY}/")
    return ((root, tuple(sorted(listed)), ignore.maintain(root, listed, writing=walk.writing)),)


def _escaping(merged: Merged, root: Path | None) -> None:
    """Refuse a committed manifest that names a path outside its own repository.

    `.` and `./kits` mean the same thing in every clone. `../my-kits` means
    something only on the machine it was written on, and committing one breaks
    the repository for everybody else (DESIGN.md section 6). Your own manifest
    is never asked, because it is not committed and its paths are supposed to
    mean something only here.

    A refusal rather than a warning, so the one hook this project ships carries
    one command. `akit doctor` reports the same thing without a second check.

    **Only a manifest git actually tracks is asked.** The rule is about what a
    colleague gets when they clone, so a `.akit.yaml` nobody else has cannot
    break anybody's clone. That is also what makes writing a kit work: you
    subscribe to `~/kits/the-new-thing` in a scratch repository, render, and
    nothing objects until you try to commit the file saying so.
    """
    if root is None or merged.project is None or merged.project.path is None:
        return
    if not targets.tracked(merged.project.path, root=root):
        return
    escaping = [
        subscription.source
        for subscription in merged.subscriptions
        if subscription.scope is Scope.PROJECT and sources.escapes(sources.parse(subscription.source), anchor=root)
    ]
    if not escaping:
        return
    listed = "\n".join(f"{INDENT * 2}{source}" for source in sorted(set(escaping)))
    raise RefusalError(
        f"{merged.project.path} is committed, and names a path outside {root}:\n"
        f"{listed}\n"
        f"{INDENT}Nothing was written. Those paths exist on this machine and on no other, so a colleague "
        f"cloning this repository gets a render that fails.\n"
        f"{INDENT}Subscribe to them in your own manifest instead: `akit remove <name>` then "
        f"`akit add <path> <name> --global`."
    )


def _committed_spots(walk: _Pass, writes: dict[Spot, _Target], root: Path) -> dict[Spot, _Target]:
    """Every planned spot this repository would commit, which is what can leak.

    Two kinds, and they are the two DESIGN.md section 6 says have to be
    committed. Anything inside a directory a machineless harness reads, because
    nobody renders in its checkout. And any rule written between markers in a
    file somebody else owns, because that file is committed for reasons of its
    own and a block of the employer's prose inside it is in the history either
    way.
    """
    directories = [
        root.joinpath(*relative.split(SEPARATOR))
        for relative in _committed(walk.chosen.get(Scope.PROJECT, ()), Scope.PROJECT)
    ]
    return {
        (path, region): planned
        for (path, region), planned in writes.items()
        if path.is_relative_to(root)
        and (region is not None or any(path.is_relative_to(directory) for directory in directories))
    }


def _unexplained(walk: _Pass, writes: dict[Spot, _Target], root: Path | None) -> tuple[Path, ...]:
    """Committed files sitting in a directory we own that this plan does not explain.

    What `--check` asks instead of asking the render record. The record is
    machine state and a CI runner has none, and a check narrowed to the
    harnesses that commit would read every other harness's entries as
    unexplained and call a perfectly good repository stale.

    Asking the disk has neither problem. These directories are ours, everything
    in them is committed, and a file in one that the manifest no longer accounts
    for is a stale render whoever rendered it and whenever they did.
    """
    if root is None:
        return ()
    found: list[Path] = []
    for relative in sorted(_committed(walk.chosen.get(Scope.PROJECT, ()), Scope.PROJECT)):
        directory = root.joinpath(*relative.split(SEPARATOR))
        if not directory.is_dir():
            continue
        found.extend(
            path for path in sorted(directory.rglob("*")) if path.is_file() and (path.resolve(), None) not in writes
        )
    return tuple(found)


def _refuse_leaks(walk: _Pass, merged: Merged, writes: dict[Spot, _Target], known: Mapping[str, Privacy]) -> None:
    """Both halves of DESIGN.md section 8, asked only when there is something to lose.

    **The target is classified lazily**, which is what keeps an ordinary render
    offline. Every source public means no leak is possible, so there is no
    question worth a network call and a render on a train is the same render as
    yesterday's. The one that goes near a remote is the one with a private kit
    about to be committed.

    **The manifest half asks only about a manifest git tracks**, because the
    URL is the leak and an untracked file publishes nothing. `.akit.yaml` naming
    `git@git.acme.example:team/unreleased.git` tells a reader the project
    exists, who is building it and roughly what it is for, whether or not they
    can clone it. That is true the moment it is pushed and not before.
    """
    root = manifest.worktree_root(walk.start)
    if root is None or Scope.PROJECT not in walk.chosen:
        return
    parts = leaks.exposures(
        sorted(
            {
                (source, path)
                for (path, _), planned in _committed_spots(walk, writes, root).items()
                for source in planned.sources
            }
        ),
        known,
    )
    named = (
        [(subscription.source, merged.project.path) for subscription in merged.project.subscriptions]
        if merged.project is not None
        and merged.project.path is not None
        and targets.tracked(merged.project.path, root=root)
        else []
    )
    manifested = leaks.exposures(named, known)
    if not parts and not manifested:
        return
    target = targets.classify(root)
    if not target.is_public:
        return
    if parts:
        raise leaks.of_parts(root, target.remotes, parts)
    raise leaks.of_manifest(root, target.remotes, manifested)


def render(start: Path, places: Directories, choices: Choices = EVERYTHING, mode: Mode = RENDERING) -> Outcome:
    """Make the files on disk match the manifests, and say everything that happened.

    `mode` is `RENDERING` for every caller but one. `CHECKING` is the same walk
    that fetches what the cache lacks, writes nothing, and judges only what this
    repository commits.
    """
    offline, writing, checking = mode.offline, mode.writing, mode.checking
    _check_names(choices.only, "--harness")
    _check_names(choices.without, "--no-harness")
    merged = manifest.load(start, user_path=places.user_manifest)
    _escaping(merged, manifest.worktree_root(start))
    files = record.locations(start, state_root=places.state)
    before = {scope: record.load(path) for scope, path in files.items()}
    chosen: dict[Scope, tuple[Adapter, ...]] = {}
    unknown: list[str] = []
    for scope in choices.scopes:
        expand = adapters.named if checking else adapters.expand
        picked, missing = expand(merged.harnesses(scope), places.home)
        chosen[scope] = _narrow(adapters.machineless(picked) if checking else picked, choices.only, choices.without)
        unknown.extend(name for name in missing if name not in unknown)
    walk = _Pass(
        start=start,
        home=places.home,
        cache_root=places.cache,
        before=Records(by_scope=before),
        chosen=chosen,
        offline=offline,
        writing=writing,
    )
    wanted = Merged(
        subscriptions=tuple(entry for entry in merged.subscriptions if entry.scope in set(choices.scopes)),
        user=merged.user,
        project=merged.project,
    )
    planned, writes = _plan(walk, wanted)
    known = privacy.learned(privacy.load(places.state), walk.resolutions)
    if writing:
        privacy.save(known, places.state)
    _refuse_leaks(walk, merged, writes, known)
    suspended = _suspension(planned, choices, checking=checking)
    owned = {
        base: written
        for scope in choices.scopes
        for base, written in _directories(chosen[scope], walk, (scope,)).items()
    }
    withdrawals: list[Withdrawal] = []
    removals: list[Region] = []
    kept: dict[Scope, list[Written]] = {scope: list(found.written) for scope, found in before.items()}
    if suspended is None:
        withdrawals, kept, removals = _withdraw(
            before, writes, choices.scopes, _directories(adapters.ADAPTERS, walk, choices.scopes)
        )
    entries, done = _perform(planned, writes, removals, writing=writing)
    standing: set[Path] = set()
    keeps_a_record = False
    for scope, path in files.items():
        after = _record_after(before[scope], writes, scope, kept.get(scope, ()))
        if writing:
            record.save(after, path)
        if scope is Scope.PROJECT:
            keeps_a_record = bool(after.written)
        standing |= set(after.paths)
    pruned = _prune(owned, standing) if choices.prune and suspended is None and writing else []
    return Outcome(
        checking=checking,
        manifests={
            Scope.USER: merged.user.path if merged.user else None,
            Scope.PROJECT: merged.project.path if merged.project else None,
        },
        harnesses={scope: tuple(adapter.name for adapter in chosen.get(scope, ())) for scope in choices.scopes},
        entries=tuple(entries),
        written=sum(1 for spot, changed in done.items() if changed and spot[1] is None),
        unchanged=sum(1 for spot, changed in done.items() if not changed and spot[1] is None),
        blocks_written=sum(1 for spot, changed in done.items() if changed and spot[1] is not None),
        blocks_unchanged=sum(1 for spot, changed in done.items() if not changed and spot[1] is not None),
        withdrawals=tuple(withdrawals),
        pruned=tuple(pruned),
        ignored=_ignore_block(walk, owned, standing, choices.scopes, keeps_a_record=keeps_a_record),
        unexplained=_unexplained(walk, writes, manifest.worktree_root(start)) if checking else (),
        unknown=tuple(unknown),
        suspended=suspended,
    )


def _suspension(entries: Sequence[Entry], choices: Choices, *, checking: bool) -> str | None:
    """Why this render may not delete anything, or `None` when it may.

    Every reason is the same shape: the candidate list the record offers is
    only trustworthy when this render saw everything that could explain a file.

    A check never saw everything by construction, since it keeps only the
    harnesses that commit, so the record's entries for every other harness would
    read as unexplained. It asks the disk a narrower question instead, which is
    also the only one a CI runner can answer (`_unexplained`).
    """
    if checking:
        return "this is a check, which judges the disk rather than the record and deletes nothing"
    if choices.narrowed:
        return "a narrowing flag was given, and narrowing skips work rather than undoing it"
    if any(entry.problem is not None for entry in entries):
        return "something could not be resolved, so the list of what is still explained is incomplete"
    return None


def _record_after(before: Record, writes: dict[Spot, _Target], scope: Scope, kept: Iterable[Written]) -> Record:
    """One root's record after this render: what it wrote there, plus what it did not touch.

    Filtered by scope rather than written whole, because a spot can be wanted by
    both roots and each record speaks only for its own.
    """
    entries = {
        spot: Written(
            path=spot[0],
            digest=planned.digest,
            explained_by=frozenset(planned.explained_by),
            harnesses=frozenset(planned.harnesses),
            region=spot[1],
        )
        for spot, planned in writes.items()
        if scope in planned.scopes
    }
    for entry in kept:
        entries.setdefault(entry.spot, entry)
    return Record(path=before.path, written=tuple(entries.values()))


def _print_entry(entry: Entry, out: TextIO) -> None:
    subscription = entry.subscription
    named = f' as "{entry.name}"' if subscription.rename else ""
    print(f"{INDENT}{subscription.kind} {entry.found_as}{named}, from {subscription.source}", file=out)
    if entry.waiting is not None:
        print(f"{INDENT * 2}not rendered: {entry.waiting}", file=out)
        return
    if entry.problem is not None:
        reported = entry.problem.splitlines()
        print(f"{INDENT * 2}problem: {reported[0]}", file=out)
        for rest in reported[1:]:
            print(f"{INDENT * 3}{rest}", file=out)
    if not entry.placements and entry.problem is None:
        print(f"{INDENT * 2}no harness in this scope takes {PLURAL[subscription.kind]}", file=out)
    for place in entry.placements:
        if place.region is not None:
            did = "wrote" if place.written else "already up to date:"
            where = f'the "{place.region}" block in {place.path}'
        else:
            did = (
                f"wrote {counted(place.written, 'file')}"
                if place.written
                else f"already up to date, {counted(place.unchanged, 'file')}"
            )
            where = f"in {place.path}"
        print(f"{INDENT * 2}{did} {where}, for {joined(place.harnesses)}", file=out)


def _print_withdrawals(outcome: Outcome, out: TextIO) -> None:
    print("Withdrawn", file=out)
    if outcome.suspended is not None:
        print(f"{INDENT}nothing: {outcome.suspended}", file=out)
    elif not outcome.withdrawals:
        print(f"{INDENT}nothing: every rendered file is still explained", file=out)
    for entry in outcome.withdrawals:
        if entry.action == DELETED:
            print(f"{INDENT}deleted {entry.described}, which nothing in scope explains any more", file=out)
        elif entry.action == GONE:
            print(f"{INDENT}{entry.described} was already gone, and is no longer recorded", file=out)
        else:
            print(f"{INDENT}left {entry.described} alone: it has been edited since it was rendered", file=out)
            print(f"{INDENT * 2}fix: run `akit doctor`, which says what to do with it", file=out)
    for path in outcome.pruned:
        print(f"{INDENT}pruned {path}, which nothing explains and no record claims", file=out)
    print("", file=out)


def verdict(outcome: Outcome, out: TextIO) -> None:
    """What `--check` prints, which is an answer rather than a list of what it did.

    A check is read by a person watching a hook refuse their commit, and by the
    CI log nobody reads until it is red. Both want the verdict first and the
    detail under it.
    """
    harnesses = joined(outcome.harnesses.get(Scope.PROJECT, ()))
    if not harnesses:
        offered = joined([adapter.name for adapter in adapters.machineless(adapters.ADAPTERS)])
        print("Nothing to check: this repository names no harness whose renders it commits.", file=out)
        print(f"{INDENT}`akit harness add <name>` with one of {offered} is what commits rendered kits.", file=out)
        return
    if not outcome.stale:
        print(f"Up to date: what this repository commits for {harnesses} matches its manifest.", file=out)
        return
    print(f"Out of date: what this repository commits for {harnesses} does not match its manifest.", file=out)
    for reason in outcome.stale:
        print(f"{INDENT}{reason}", file=out)
    print(f"{INDENT}fix: run `akit render` and commit what it writes.", file=out)


def text(outcome: Outcome, out: TextIO) -> None:
    """The report a person reads: what went where, what went away, and what did not."""
    for scope in Scope:
        if scope not in outcome.harnesses:
            continue
        path = outcome.manifests[scope]
        where = str(path) if path is not None else "no manifest found"
        harnesses = joined(outcome.harnesses[scope]) or "no harness in scope"
        print(f"{SCOPE_TITLE[scope]} ({where}), rendering for {harnesses}", file=out)
        entries = outcome.of_scope(scope)
        if not entries:
            print(f"{INDENT}nothing subscribed here", file=out)
        for entry in entries:
            _print_entry(entry, out)
        print("", file=out)
    for name in outcome.unknown:
        print(f'A manifest names the harness "{name}", and no adapter answers to it.', file=out)
        print(f"{INDENT}fix: run `akit list` to see the harnesses this build knows", file=out)
    _print_withdrawals(outcome, out)
    for root, listed, changed in outcome.ignored:
        state = "now lists" if changed else "already listed"
        print(
            f"Ignore rules\n{INDENT}{root / ignore.GITIGNORE} {state} {joined(listed) or 'nothing of ours'}", file=out
        )
        print("", file=out)
    if outcome.quiet:
        print("Nothing changed: the files on disk already match the manifests.", file=out)
    else:
        blocks = (
            f" Wrote {counted(outcome.blocks_written, 'rule')} into a file somebody else owns, and left "
            f"{counted(outcome.blocks_unchanged, 'rule')} there alone."
            if outcome.blocks_written or outcome.blocks_unchanged
            else ""
        )
        print(
            f"Wrote {counted(outcome.written, 'file')}, left {counted(outcome.unchanged, 'file')} alone as "
            f"already correct, and deleted {counted(len(outcome.deleted), 'file')}.{blocks}",
            file=out,
        )


def payload(outcome: Outcome) -> dict[str, Any]:
    """The same information as data, which is what the skill reads."""
    return {
        "manifests": {str(scope): None if path is None else str(path) for scope, path in outcome.manifests.items()},
        "harnesses": {str(scope): list(names) for scope, names in outcome.harnesses.items()},
        "unknown_harnesses": list(outcome.unknown),
        "subscriptions": [
            {
                "kind": str(entry.subscription.kind),
                "name": entry.name,
                "found_as": entry.found_as,
                "source": entry.subscription.source,
                "scope": str(entry.subscription.scope),
                "relative": entry.relative,
                "problem": entry.problem,
                "waiting": entry.waiting,
                "placements": [
                    {
                        "path": str(place.path),
                        "region": place.region,
                        "harnesses": list(place.harnesses),
                        "written": place.written,
                        "unchanged": place.unchanged,
                    }
                    for place in entry.placements
                ],
            }
            for entry in outcome.entries
        ],
        "withdrawn": [
            {"path": str(entry.path), "region": entry.region, "action": entry.action} for entry in outcome.withdrawals
        ],
        "pruned": [str(path) for path in outcome.pruned],
        "ignored": [
            {"repository": str(root), "lists": list(listed), "changed": changed}
            for root, listed, changed in outcome.ignored
        ],
        "unexplained": [str(path) for path in outcome.unexplained],
        "withdrawal_suspended": outcome.suspended,
        "changed_nothing": outcome.quiet,
        "stale": list(outcome.stale),
    }


def scopes_from(*, only_global: bool, only_project: bool) -> tuple[Scope, ...]:
    """Which halves of the render the flags asked for, which is both unless one is named.

    Both by default because a kit you are writing is usually a global one and
    you are usually inside some repository while writing it (DESIGN.md section
    10). Naming both flags is the default spelled out, not a contradiction.
    """
    if only_global and not only_project:
        return (Scope.USER,)
    if only_project and not only_global:
        return (Scope.PROJECT,)
    return tuple(Scope)


def run(
    out: TextIO,
    *,
    as_json: bool,
    choices: Choices = EVERYTHING,
    start: Path | None = None,
    home: Path | None = None,
) -> Exit:
    """`akit render`. Non-zero when a subscription could not be rendered."""
    places = Directories(home=home or Path.home())
    outcome = render(start or Path.cwd(), places, choices)
    if as_json:
        print(json.dumps(payload(outcome), indent=2), file=out)
    else:
        text(outcome, out)
    return outcome.exit_code


def check(
    out: TextIO,
    *,
    as_json: bool,
    choices: Choices = EVERYTHING,
    start: Path | None = None,
    home: Path | None = None,
) -> Exit:
    """`akit render --check`. Non-zero when a committed render is out of date.

    The same walk with three things changed. It writes nothing. It judges the
    project scope and the harnesses the manifest names that have no machine, so
    its verdict is the same in every clone rather than a report that every
    repository is stale on a runner with no editors installed. And it fetches,
    because a runner has never rendered and has no cache to recompute a
    committed render from (DESIGN.md section 10).

    The narrowing flags are refused rather than honoured. Excluding the only
    harness that commits anything would leave a check with nothing to look at,
    which passes; inside a pre-commit hook that is the one place a false pass
    costs something.
    """
    if choices.narrowed:
        raise UsageError(
            "render --check does not take --harness or --no-harness.\n"
            "  Narrowing a check leaves it with less to look at, and a check that looked at nothing passes.\n"
            "  Run `akit render --check` on its own."
        )
    places = Directories(home=home or Path.home())
    outcome = render(
        start or Path.cwd(),
        places,
        COMMITTED,
        CHECKING,
    )
    if as_json:
        print(json.dumps(payload(outcome), indent=2), file=out)
    else:
        verdict(outcome, out)
    return outcome.exit_code


__all__ = [
    "CHECKING",
    "COMMITTED",
    "RENDERING",
    "Choices",
    "Directories",
    "Entry",
    "Mode",
    "Outcome",
    "Placement",
    "Withdrawal",
    "check",
    "counted",
    "payload",
    "render",
    "run",
    "scopes_from",
    "text",
    "verdict",
]
