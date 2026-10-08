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

**Skills only, for now.** Rules land with T6 and agents with T13, so a
subscription of either kind is reported as waiting rather than silently
producing nothing.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

from federated_agent_kits import adapters, cache, discovery, ignore, manifest, record, sources
from federated_agent_kits.adapters import Adapter
from federated_agent_kits.adapters.adapter import SEPARATOR
from federated_agent_kits.exits import AkitError, Exit, UsageError
from federated_agent_kits.listing import PLURAL, SCOPE_TITLE, joined
from federated_agent_kits.manifest import Kind, Merged, Scope, Subscription
from federated_agent_kits.record import Explanation, Record, Records, Written

INDENT = "  "

#: The kinds this build actually puts on disk. Rules are T6 and agents are T13,
#: and a kind that is not here is reported as waiting rather than skipped in
#: silence: a subscription that produces nothing and says nothing is the failure
#: DESIGN.md section 3 spends rule 5 on.
RENDERED: tuple[Kind, ...] = (Kind.SKILL,)

#: The three outcomes of the withdrawal table in DESIGN.md section 10, named
#: once so the reporter and the engine cannot drift into two spellings.
DELETED = "deleted"
KEPT = "kept"
GONE = "gone"

WAITING: dict[Kind, str] = {
    Kind.RULE: "rules are not rendered yet; they land with T6",
    Kind.AGENT: "every adapter declines agents for now; they land with T13",
}

#: The count at which a noun stops needing its plural.
ONE = 1


#: Directories a copy never descends into. A source's skill is a directory of
#: files, and the only thing in one that is not part of the kit is a repository.
SKIPPED = frozenset({".git"})


@dataclass(frozen=True)
class Placement:
    """Where one part landed, and for which harnesses, after the copy was made."""

    path: Path
    """The directory a skill was copied into, which is what a person wants told."""

    harnesses: tuple[str, ...]
    written: int
    """Files that appeared or changed. Zero is the ordinary second render."""

    unchanged: int


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
    """One file the record explained and nothing in scope explains any more."""

    path: Path
    action: str
    """`deleted`, `kept` for an edited copy, or `gone` for one already removed."""


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

    @property
    def deleted(self) -> tuple[Withdrawal, ...]:
        return tuple(entry for entry in self.withdrawals if entry.action == DELETED)

    @property
    def quiet(self) -> bool:
        """Whether this render changed nothing at all, which it usually should."""
        changed = any(changed for _, _, changed in self.ignored)
        return not (self.written or self.deleted or self.pruned or changed)

    def of_scope(self, scope: Scope) -> tuple[Entry, ...]:
        return tuple(entry for entry in self.entries if entry.subscription.scope is scope)

    @property
    def exit_code(self) -> Exit:
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
    """One file several subscriptions and harnesses may all want in one place."""

    source: Path
    digest: str
    explained_by: set[str] = field(default_factory=set)
    harnesses: set[str] = field(default_factory=set)
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

    def anchor(self, adapter: Adapter, scope: Scope) -> Path:
        """The base a target is computed against, which is the harness's and not ours."""
        if scope is Scope.USER:
            return self.home
        return adapter.anchor(self.start) or self.start

    def resolve(self, subscription: Subscription) -> cache.Resolved:
        anchor = self.home if subscription.scope is Scope.USER else (manifest.worktree_root(self.start) or self.start)
        key = sources.parse(subscription.source)
        return cache.resolve(key, pin=subscription.pin, anchor=anchor, cache_root=self.cache_root, offline=True)


def _plan_part(
    walk: _Pass,
    subscription: Subscription,
    part: discovery.Part,
    writes: dict[Path, _Target],
) -> Entry:
    """Where one found part goes, added to the writes and reported as a line.

    A target two subscriptions want with different bytes is a collision the
    manifest could not refuse, because a `"*"` cannot know what it will match.
    It is reported rather than resolved, and the first writer keeps the file:
    picking a winner silently is what `as:` exists to avoid.
    """
    name = subscription.rename or part.name
    explanation = str(Explanation(kind=subscription.kind, source=subscription.source, name=name))
    placements: list[Placement] = []
    clash: str | None = None
    for adapter in walk.chosen[subscription.scope]:
        directory = adapter.target(
            subscription.kind, subscription.scope, name, walk.anchor(adapter, subscription.scope)
        )
        if directory is None:
            continue
        for file in _files_of(part.path):
            target = (directory / file.relative_to(part.path)).resolve()
            digest = record.digest(file.read_bytes())
            standing = writes.get(target)
            if standing is None:
                writes[target] = _Target(
                    source=file,
                    digest=digest,
                    explained_by={explanation},
                    harnesses={adapter.name},
                    scopes={subscription.scope},
                )
            elif standing.digest != digest:
                clash = (
                    f"another subscription already wants different bytes at {target}; "
                    f"this copy was not written. Give one of them a different name with `as:`"
                )
                continue
            else:
                standing.explained_by.add(explanation)
                standing.harnesses.add(adapter.name)
                standing.scopes.add(subscription.scope)
        placements.append(Placement(path=directory, harnesses=(adapter.name,), written=0, unchanged=0))
    return Entry(
        subscription=subscription,
        name=name,
        found_as=part.name,
        relative=part.relative,
        placements=_shared(placements),
        problem=clash,
    )


def _shared(placements: Iterable[Placement]) -> tuple[Placement, ...]:
    """One line per directory, naming every harness that reads it.

    Both adapters shipped today write skills to the same directory, so the
    honest report is one copy wanted by two harnesses rather than the same path
    printed twice (DESIGN.md section 7).
    """
    grouped: dict[Path, list[str]] = {}
    for place in placements:
        grouped.setdefault(place.path, []).extend(place.harnesses)
    return tuple(
        Placement(path=path, harnesses=tuple(names), written=0, unchanged=0) for path, names in grouped.items()
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


def _plan(walk: _Pass, merged: Merged) -> tuple[list[Entry], dict[Path, _Target]]:
    """Every subscription as the files it wants on disk, with nothing written yet."""
    writes: dict[Path, _Target] = {}
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


def _perform(entries: list[Entry], writes: dict[Path, _Target]) -> tuple[list[Entry], dict[Path, bool]]:
    """Write every planned file whose bytes are not already there, and count both.

    The comparison is the hash rather than the modification time. A render that
    rewrote an identical file would still be idempotent on disk and would churn
    every `mtime` a harness, a watcher or a build system might be reading.
    """
    done: dict[Path, bool] = {}
    for target, planned in writes.items():
        data = planned.source.read_bytes()
        if record.digest_of(target) == planned.digest:
            done[target] = False
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        done[target] = True
    counted: list[Entry] = []
    for entry in entries:
        placements = tuple(
            Placement(
                path=place.path,
                harnesses=place.harnesses,
                written=sum(1 for target, changed in done.items() if changed and target.is_relative_to(place.path)),
                unchanged=sum(
                    1 for target, changed in done.items() if not changed and target.is_relative_to(place.path)
                ),
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
    writes: dict[Path, _Target],
    scopes: Sequence[Scope],
    region: Mapping[Path, set[str]],
) -> tuple[list[Withdrawal], dict[Scope, list[Written]]]:
    """The three outcomes of DESIGN.md section 10's withdrawal table, per record.

    One record per root does most of the narrowing by itself: the entries a
    render may consider are the ones in the records it opened, so a render in
    one repository cannot reach another's files however the adapters have moved
    their directories since.

    What is left is the one case where two roots genuinely overlap. A home
    directory that is also a git repository makes the project anchor and the
    user root the same place, so both records can claim one path. A record this
    run is not rendering still speaks for its files, which is why the sibling is
    read before anything is deleted and why `--global` in a dotfiles repository
    cannot take a file the repository still wants.
    """
    rendered = set(scopes)
    silent = [record for scope, record in before.items() if scope not in rendered]
    handled: set[Path] = set()
    done: list[Withdrawal] = []
    kept: dict[Scope, list[Written]] = {}
    for scope, found in before.items():
        staying: list[Written] = []
        kept[scope] = staying
        if scope not in rendered:
            staying.extend(found.written)
            continue
        for entry in found.written:
            if entry.path in writes:
                continue
            if any(entry.path in other.paths for other in silent):
                staying.append(entry)
                continue
            if entry.path in handled:
                continue
            handled.add(entry.path)
            if not entry.path.exists():
                done.append(Withdrawal(path=entry.path, action=GONE))
            elif entry.still_a_copy():
                entry.path.unlink()
                _tidy(entry.path, region)
                done.append(Withdrawal(path=entry.path, action=DELETED))
            else:
                staying.append(entry)
                done.append(Withdrawal(path=entry.path, action=KEPT))
    return done, kept


def _directories(picked: Iterable[Adapter], walk: _Pass, scopes: Sequence[Scope]) -> dict[Path, set[str]]:
    """Every directory these harnesses own, per scope root.

    Taken from the adapters rather than from what was written, because both
    callers need the directories a kit *could* be in: one is looking for a kit
    nothing explains, and the other for the kits a withdrawal is allowed to
    consider at all.
    """
    found: dict[Path, set[str]] = {}
    for scope in scopes:
        for adapter in picked:
            for kind in RENDERED:
                destination = adapter.destination(kind, scope)
                if destination is None or destination.write is None:
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


def _ignore_block(
    walk: _Pass,
    owned: dict[Path, set[str]],
    explained: Iterable[Path],
    scopes: Sequence[Scope],
    kept: Path | None,
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

    Only inside a repository, and only for the project scope: your home
    directory is not a working tree, so nothing rendered there can be committed
    by accident. Every harness shipped today has a machine, so everything here
    is ignored; T8 is where naming a machineless harness starts taking entries
    back out.
    """
    root = manifest.worktree_root(walk.start)
    if root is None or Scope.PROJECT not in scopes:
        return ()
    inside = [path for path in explained if path.is_relative_to(root)]
    listed = {
        f"{directory.relative_to(root).as_posix()}/"
        for base, written in owned.items()
        for relative in written
        for directory in (base.joinpath(*relative.split(SEPARATOR)),)
        if directory.is_relative_to(root) and any(path.is_relative_to(directory) for path in inside)
    }
    if kept is not None and kept.is_file():
        listed.add(f"{record.DIRECTORY}/")
    return ((root, tuple(sorted(listed)), ignore.maintain(root, listed)),)


def render(start: Path, places: Directories, choices: Choices = EVERYTHING) -> Outcome:
    """Make the files on disk match the manifests, and say everything that happened."""
    _check_names(choices.only, "--harness")
    _check_names(choices.without, "--no-harness")
    merged = manifest.load(start, user_path=places.user_manifest)
    files = record.locations(start, state_root=places.state)
    before = {scope: record.load(path) for scope, path in files.items()}
    chosen: dict[Scope, tuple[Adapter, ...]] = {}
    unknown: list[str] = []
    for scope in choices.scopes:
        picked, missing = adapters.expand(merged.harnesses(scope), places.home)
        chosen[scope] = _narrow(picked, choices.only, choices.without)
        unknown.extend(name for name in missing if name not in unknown)
    walk = _Pass(start=start, home=places.home, cache_root=places.cache, before=Records(by_scope=before), chosen=chosen)
    wanted = Merged(
        subscriptions=tuple(entry for entry in merged.subscriptions if entry.scope in set(choices.scopes)),
        user=merged.user,
        project=merged.project,
    )
    planned, writes = _plan(walk, wanted)
    entries, done = _perform(planned, writes)

    suspended = _suspension(entries, choices)
    owned = {
        base: written
        for scope in choices.scopes
        for base, written in _directories(chosen[scope], walk, (scope,)).items()
    }
    withdrawals: list[Withdrawal] = []
    kept: dict[Scope, list[Written]] = {scope: list(found.written) for scope, found in before.items()}
    if suspended is None:
        withdrawals, kept = _withdraw(
            before, writes, choices.scopes, _directories(adapters.ADAPTERS, walk, choices.scopes)
        )
    standing: set[Path] = set()
    for scope, path in files.items():
        after = _record_after(before[scope], writes, scope, kept.get(scope, ()))
        record.save(after, path)
        standing |= set(after.paths)
    pruned = _prune(owned, standing) if choices.prune and suspended is None else []
    return Outcome(
        manifests={
            Scope.USER: merged.user.path if merged.user else None,
            Scope.PROJECT: merged.project.path if merged.project else None,
        },
        harnesses={scope: tuple(adapter.name for adapter in chosen.get(scope, ())) for scope in choices.scopes},
        entries=tuple(entries),
        written=sum(1 for changed in done.values() if changed),
        unchanged=sum(1 for changed in done.values() if not changed),
        withdrawals=tuple(withdrawals),
        pruned=tuple(pruned),
        ignored=_ignore_block(walk, owned, standing, choices.scopes, files.get(Scope.PROJECT)),
        unknown=tuple(unknown),
        suspended=suspended,
    )


def _suspension(entries: Sequence[Entry], choices: Choices) -> str | None:
    """Why this render may not delete anything, or `None` when it may.

    Both reasons are the same shape: the candidate list the record offers is
    only trustworthy when this render saw everything that could explain a file.
    """
    if choices.narrowed:
        return "a narrowing flag was given, and narrowing skips work rather than undoing it"
    if any(entry.problem is not None for entry in entries):
        return "something could not be resolved, so the list of what is still explained is incomplete"
    return None


def _record_after(before: Record, writes: dict[Path, _Target], scope: Scope, kept: Iterable[Written]) -> Record:
    """One root's record after this render: what it wrote there, plus what it did not touch.

    Filtered by scope rather than written whole, because a file can be wanted by
    both roots and each record speaks only for its own.
    """
    entries = {
        target: Written(
            path=target,
            digest=planned.digest,
            explained_by=frozenset(planned.explained_by),
            harnesses=frozenset(planned.harnesses),
        )
        for target, planned in writes.items()
        if scope in planned.scopes
    }
    for entry in kept:
        entries.setdefault(entry.path, entry)
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
        did = (
            f"wrote {counted(place.written, 'file')}"
            if place.written
            else f"already up to date, {counted(place.unchanged, 'file')}"
        )
        print(f"{INDENT * 2}{did} in {place.path}, for {joined(place.harnesses)}", file=out)


def _print_withdrawals(outcome: Outcome, out: TextIO) -> None:
    print("Withdrawn", file=out)
    if outcome.suspended is not None:
        print(f"{INDENT}nothing: {outcome.suspended}", file=out)
    elif not outcome.withdrawals:
        print(f"{INDENT}nothing: every rendered file is still explained", file=out)
    for entry in outcome.withdrawals:
        if entry.action == DELETED:
            print(f"{INDENT}deleted {entry.path}, which nothing in scope explains any more", file=out)
        elif entry.action == GONE:
            print(f"{INDENT}{entry.path} was already gone, and is no longer recorded", file=out)
        else:
            print(f"{INDENT}left {entry.path} alone: it has been edited since it was rendered", file=out)
            print(f"{INDENT * 2}fix: run `akit doctor`, which says what to do with it", file=out)
    for path in outcome.pruned:
        print(f"{INDENT}pruned {path}, which nothing explains and no record claims", file=out)
    print("", file=out)


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
        print(
            f"Wrote {counted(outcome.written, 'file')}, left {counted(outcome.unchanged, 'file')} alone as "
            f"already correct, and deleted {counted(len(outcome.deleted), 'file')}.",
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
                        "harnesses": list(place.harnesses),
                        "written": place.written,
                        "unchanged": place.unchanged,
                    }
                    for place in entry.placements
                ],
            }
            for entry in outcome.entries
        ],
        "withdrawn": [{"path": str(entry.path), "action": entry.action} for entry in outcome.withdrawals],
        "pruned": [str(path) for path in outcome.pruned],
        "ignored": [
            {"repository": str(root), "lists": list(listed), "changed": changed}
            for root, listed, changed in outcome.ignored
        ],
        "withdrawal_suspended": outcome.suspended,
        "changed_nothing": outcome.quiet,
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


__all__ = [
    "Choices",
    "Directories",
    "Entry",
    "Outcome",
    "Placement",
    "Withdrawal",
    "counted",
    "payload",
    "render",
    "run",
    "scopes_from",
    "text",
]
