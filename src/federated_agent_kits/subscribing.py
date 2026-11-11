"""The four commands that write a manifest: `add`, `remove`, `update`, `harness`.

One shape between them. Each one decides which manifest it is editing, makes one
edit, writes the file back, and makes the disk agree with that edit, so that the
kit is usable - or gone - when the command returns rather than after a second
command somebody has to know about. Nobody has to hold the manifest format in
their head, which is the whole point of these four existing at all.

**Agreeing with the edit is not the same as rendering.** `add`, `harness add`
and `update` write what they subscribed to. `remove` and `harness remove`
withdraw what they dropped and write nothing else: a subtractive command that
caught the whole manifest up in passing could write more files than it took
away, which is what `render.WITHDRAWING` exists to stop.

**The two commands that fetch and also write are both here.** `add` clones a
source this machine does not have, and `update` asks a source it does have what
moved (DESIGN.md section 10). Both do it through `discovering.fetch`, which is
also what `akit discover` uses, so a source arrives in the cache the same way
whichever of the three asked for it. Everything else in this package works from
the cache, so a render on a train produces what it produced yesterday.

**`update` edits a pin and never a name.** A part that disappeared upstream stops
that key, leaves the pin where it was, and names the three ways out. Dropping the
name on somebody's behalf would take a rule out of every prompt their agents see,
and adding one would subscribe them to a kit they have never read; neither is a
thing to infer from a rename somebody else made (DESIGN.md section 10).

**A refusal here is a question, not a failure of nerve.** Two manifests
subscribing to one name, a kit name that is both a skill and a rule, a harness no
adapter knows: each of them has two defensible answers and no way to tell which
was meant, so each is reported with the flag that settles it.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

from federated_agent_kits import adapters, cache, discovering, discovery, editing, render, sources
from federated_agent_kits import manifest as manifests
from federated_agent_kits.cache import Fetched
from federated_agent_kits.exits import Exit, RefusalError, UsageError
from federated_agent_kits.manifest import Kind, Manifest, Scope, Subscription
from federated_agent_kits.reporting import (
    MISSING,
    PLURAL,
    SHORT,
    Column,
    counted,
    group,
    joined,
    manifest_title,
    section,
    wrapped,
)
from federated_agent_kits.sources import SourceKey
from federated_agent_kits.styling import Style

#: The kinds a kit can be, in the order `add` looks for an unqualified name in.
SEARCHED: tuple[Kind, ...] = tuple(Kind)

#: A kind as it reads about one kit. `Kind` is spelled the way the manifest
#: spells it, which is the plural heading of a block, and "a skills called
#: writing" is not a sentence.
SINGULAR: dict[Kind, str] = {Kind.SKILL: "skill", Kind.RULE: "rule", Kind.AGENT: "agent"}

#: What the `--kind` flag takes, which is the singular somebody would type.
BY_FLAG: dict[str, Kind] = {word: kind for kind, word in SINGULAR.items()}

ONE = 1


class AmbiguityError(UsageError):
    """A command that was understood and has two answers, with the flag that picks one.

    A usage error rather than a refusal: the fix is a flag on the same command,
    and the caller that has to tell those apart is the one reading the exit code
    (DESIGN.md section 8 keeps 3 for the leak refusal, which has no flag).
    """


@dataclass(frozen=True)
class Call:
    """Where one of these commands is standing, and which manifest it was pointed at.

    The same shape as `render._Pass` and for the same reason: four values that
    travel together through every verb, rather than four parameters threaded
    through each of them and a fifth added by the next task.
    """

    start: Path
    places: render.Directories
    only_global: bool = False
    only_project: bool = False
    named: Path | None = None

    def chosen(self, *, creating: bool = True) -> editing.Chosen:
        return editing.choose(
            self.start,
            editing.Wanted(
                only_global=self.only_global,
                only_project=self.only_project,
                named=self.named,
                user_path=self.places.user_manifest,
                creating=creating,
            ),
        )

    @property
    def scoped(self) -> bool:
        """Whether a file was named, which is what decides if an ambiguity is one."""
        return self.only_global or self.only_project or self.named is not None


@dataclass(frozen=True)
class Note:
    """One sentence about what the manifest edit did, and the data behind it."""

    text: str
    data: dict[str, Any] = field(default_factory=dict)


#: The verb whose report is about what moved rather than about a line it wrote.
UPDATE = "update"

#: What the live account says about one key, by the status its note carries.
#: Short, because this is read while it scrolls past rather than afterwards.
PROGRESS: dict[str, str] = {
    "path": "a path, read as it is on disk",
    "unchanged": "up to date",
    "stopped": "stopped, see below",
}


@dataclass(frozen=True)
class Watcher:
    """Where the live account of a slow command goes while it is still running.

    `akit update` fetches once per key, so the time it takes is a loop a person
    is sitting through with nothing to look at. This is what they look at.

    **It is a second channel, not a second report.** What it says goes to
    `stderr`, because `stdout` is the record: the same bytes that go into a
    pipe, a log and a pull request comment ([DESIGN.md] section 10), and a line
    whose content depends on which sources happened to be cold is not those
    bytes. Nothing here is the only place a fact appears; every pin that moved
    is in the report as well, so output that was never captured loses nothing.

    `out` of `None` is silence, which is what `--json` and every caller that
    did not ask for this get. Handing it a buffer is how a test reads it
    without caring which file descriptor it went to.
    """

    out: TextIO | None = None
    style: Style = field(default_factory=Style.plain)

    def starting(self, path: Path, *, subscriptions: int, keys: int) -> None:
        """What is about to be looked at, said before the first fetch rather than after.

        A manifest with nothing in it has no loop to sit through, so there is
        nothing to announce here at all. That it was empty is the report's to
        say, because it is the answer rather than a sign of progress towards
        one.
        """
        if self.out is None or not keys:
            return
        print(
            f"Found {counted(subscriptions, 'subscription')} under {counted(keys, 'key')} "
            f"in {self.style.place(str(path))}, looking for updates\n",
            file=self.out,
        )

    def resolved(self, entry: _Key, said: str, column: Column) -> None:
        """One key, the moment it answered."""
        if self.out is None:
            return
        print(f"  {column.padded(_named(entry))}  {said}", file=self.out)

    def finished(self, *, keys: int) -> None:
        """The blank line between the live account and the report that follows it.

        Only where there was an account. Nothing was said about a manifest with
        nothing in it, so there is nothing to separate from what comes next.
        """
        if self.out is not None and keys:
            print("", file=self.out)


#: Nobody is watching, which is the default and what `--json` gets.
UNWATCHED = Watcher()


def _named(entry: _Key) -> str:
    """How one key reads in the live account: its kind, then the source it names."""
    return f"{entry.kind.value:<{_KIND_WIDTH}}  {entry.source}"


#: Wide enough for `skills`, which is the longest of the three kinds.
_KIND_WIDTH = 6


@dataclass(frozen=True)
class Movement:
    """One key whose pin moved, and what moved under it.

    The unit is the key rather than the kit, because a pin belongs to a key: a
    key holding three kits moves for all three or for none of them, and one
    diff over the three is the change that pin actually names.
    """

    kind: Kind
    source: str
    was: str | None
    """The commit it was pinned to, or `None` for a key that carried no pin."""

    now: str
    ref: str
    diff: str
    """Empty when the pin moved and nothing under it that you subscribe to did."""

    onto: str | None = None
    """The key it follows from now on, where the branch it followed has landed elsewhere."""

    @property
    def changed(self) -> bool:
        return bool(self.diff.strip())

    @property
    def heading(self) -> str:
        """What the diff below it is a diff of, which a bare `diff --git` does not say."""
        was = "an unpinned key" if self.was is None else self.was[:SHORT]
        onto = "" if self.onto is None else f" on {self.onto}"
        return f"{self.kind.value} from {self.source}, {was} to {self.now[:SHORT]}{onto}"


@dataclass(frozen=True)
class _Edit:
    """One manifest edit, before it is written and rendered."""

    command: str
    written: Manifest
    notes: list[Note] = field(default_factory=list)
    changed: bool = False
    diffs: list[str] = field(default_factory=list)
    moved: list[Movement] = field(default_factory=list)
    withdrawing: bool = False
    """Whether what follows this edit takes files away rather than making them match.

    True for the two subtractive verbs and nothing else. `add` and `harness
    add` end with a render because the kit they just subscribed to has to exist
    when the command returns; `remove` has nothing to make exist.

    A `harness add` that moved a harness to another destination is still one of
    those: it both takes the old copy away and writes the new one, and an
    ordinary render does both, so it is the withdrawal-only mode that would
    leave the command half-done.
    """


@dataclass(frozen=True)
class Outcome:
    """What a manifest-writing command did, before the render it ends with."""

    command: str
    path: Path | None
    scope: Scope
    created: bool
    notes: tuple[Note, ...]
    rendered: render.Outcome
    changed: bool
    diffs: tuple[str, ...] = ()
    """What `update` found between the old commit and the new one, per key that moved."""

    moved: tuple[Movement, ...] = ()
    """Every key whose pin `update` moved, with the diff under each. Empty for the rest."""

    @property
    def found_nothing(self) -> bool:
        """An `update` that had no key to ask: an empty manifest, or one that is not there.

        `update` writes one note per key, so no notes means no keys. There is
        nothing to say about pins that do not exist, and a report saying so in
        three headed sections says it at more length than it is worth.
        """
        return self.command == UPDATE and not self.notes

    @property
    def exit_code(self) -> Exit:
        """The render's, because every one of these ends with one."""
        return self.rendered.exit_code


def _anchor(scope: Scope, start: Path, home: Path) -> Path:
    """What a relative path key is read against, which is per scope and never the cwd."""
    if scope is Scope.USER:
        return home
    return manifests.worktree_root(start) or start


def _parts(root: Path, kind: Kind, name: str, *, rendered: Iterable[Path] = ()) -> tuple[discovery.Part, ...]:
    return discovery.named(
        root,
        kind,
        name,
        extra_directories=adapters.source_directories(kind),
        rendered=rendered,
    )


def _kinds_holding(root: Path, name: str, wanted: Kind | None) -> tuple[Kind, ...]:
    if wanted is not None:
        return (wanted,) if _parts(root, wanted, name) else ()
    return tuple(kind for kind in SEARCHED if _parts(root, kind, name))


def _already(found: Manifest, kind: Kind, source: str, name: str, rename: str | None) -> Subscription | None:
    return next(
        (
            entry
            for entry in found.of_kind(kind)
            if entry.source == source and entry.name == name and entry.rename == rename
        ),
        None,
    )


def _taken(found: Manifest, kind: Kind, rendered: str) -> Subscription | None:
    return next((entry for entry in found.of_kind(kind) if entry.rendered_name == rendered), None)


def add(call: Call, *, source: str, name: str, rename: str | None = None, kind: Kind | None = None) -> Outcome:
    """Subscribe to one kit, in four steps and in order (DESIGN.md section 10).

    Resolve, check the kit is really there, write one line, render. The order is
    the behaviour: a typo fails at step two with a list of what the source does
    hold, and the manifest is byte-identical afterwards.
    """
    chosen = call.chosen()
    asked = discovering.named(source)
    raw = asked.key.raw
    anchor = _anchor(chosen.scope, call.start, call.places.home)
    found = discovering.fetch(
        asked.key, asked.ref, anchor=anchor, cache_root=call.places.cache, state_root=call.places.state
    )
    root, pin, comment = found.root, found.commit, found.comment
    holding = _kinds_holding(root, name, kind)
    if not holding:
        wanted = "" if kind is None else f", as a {SINGULAR[kind]}"
        raise UsageError(
            f"{asked.typed} holds no kit called `{name}`{wanted}.\n{discovering.described(discovering.offers(root))}"
        )
    written = chosen.manifest
    notes: list[Note] = []
    changed = False
    for holds in holding:
        rendered = rename or name
        existing = _already(written, holds, raw, name, rename)
        if existing is not None:
            notes.append(
                Note(
                    f"Already subscribed: {SINGULAR[holds]} `{rendered}` from {raw}, "
                    f"at {existing.pin[:SHORT] if existing.pin else 'the path it is read from'}.",
                    {"kind": str(holds), "name": rendered, "status": "unchanged"},
                )
            )
            continue
        clash = _taken(written, holds, rendered)
        if clash is not None:
            raise AmbiguityError(
                f"`{rendered}` is already subscribed in {chosen.path}, as a {SINGULAR[holds]} from {clash.source}.\n"
                "  Render it under another name with --as, or remove the other subscription first."
            )
        written = editing.subscribe(
            written,
            editing.Entry(
                kind=holds,
                key=raw if pin is None else f"{raw}{manifests.PIN}{pin}",
                name=name,
                rename=rename,
                comment=comment,
            ),
        )
        changed = True
        where = f" at {pin[:SHORT]}" if pin is not None else ""
        notes.append(
            Note(
                f"Subscribed: {SINGULAR[holds]} `{rendered}` from {raw}{where}.",
                {"kind": str(holds), "name": rendered, "source": raw, "pin": pin, "status": "added"},
            )
        )
    pull = asked.pull_request
    if changed and pull is not None:
        origin = manifests.Origin(pull_request=pull.name, merges_into=pull.target)
        written = editing.describe_source(written, raw, origin)
        notes.append(
            Note(
                f"Following pull request {pull.name} on its branch; `akit update` moves to {pull.target} "
                "once the branch is gone and its kits have landed there.",
                {"pull_request": pull.name, "follows": raw, "merges_into": pull.target, "status": "following"},
            )
        )
    return _finish(call, chosen, _Edit("add", written, notes, changed=changed))


def _candidates(pool: Iterable[Subscription], name: str, kind: Kind | None) -> tuple[Subscription, ...]:
    return tuple(entry for entry in pool if entry.rendered_name == name and (kind is None or entry.kind is kind))


def _in_one_file(found: Sequence[Subscription], name: str, *, scoped: bool) -> tuple[Subscription, ...]:
    """Every subscription a name meant, once it is certain which file they are in.

    A name is a kit rather than a part, so a skill and the rule that makes a
    model reach for it go together: that is what made them one kit when they
    were added. Two manifests are the case with no answer, because dropping the
    wrong one silently changes what everybody else gets (DESIGN.md section 10).
    """
    if len({entry.scope for entry in found}) > ONE and not scoped:
        raise AmbiguityError(
            f"`{name}` is subscribed in both manifests, and dropping the wrong one would change "
            "what everybody else gets.\n  Name the file: --global for the global manifest, --project for this project's."
        )
    return tuple(found)


def _scope_flag(call: Call, scope: Scope) -> str:
    """The flag that points `remove` at one file, spelled the way the caller did.

    A caller who named a file gets that file back, because `--global` would be
    a different command on a machine where both exist. Everybody else gets the
    flag for the scope the subscription is actually in, which is what makes a
    printed invocation runnable rather than illustrative.
    """
    if call.named is not None:
        return f"--manifest {call.named}"
    return "--global" if scope is Scope.USER else "--project"


def _covers(call: Call, chosen: editing.Chosen, entry: Subscription) -> tuple[str, ...]:
    """Which parts one subscription renders, read from the cache and never fetched.

    Only a `"*"` has an answer worth printing: every other subscription renders
    the one name it already says. A cache that cannot answer returns nothing,
    and the sentence built from this says less rather than guessing.
    """
    if not entry.is_wildcard:
        return (entry.rendered_name,)
    key = sources.parse(entry.source)
    anchor = _anchor(entry.scope, call.start, call.places.home)
    try:
        resolved = cache.resolve(key, pin=entry.pin, anchor=anchor, cache_root=call.places.cache, offline=True)
    except cache.CacheError:
        return ()
    return tuple(sorted({part.name for part in _parts(resolved.root, entry.kind, discovery.WILDCARD)}))


def _invocation(call: Call, entry: Subscription) -> str:
    """The command that drops one subscription, as it would be typed into a shell.

    `--kind` only where the name needs it. A name is a kit, so `akit remove
    writing` is meant to take the skill and the rule that came in together; a
    `"*"` is one subscription per kind under one name, and there the kind is
    the only thing telling two lines apart.

    The quotes around a `"*"` are not decoration. No interactive shell passes
    one through unquoted, and an example without them is a line that expands to
    the current directory on its way to argparse.
    """
    kind = f" --kind {SINGULAR[entry.kind]}" if entry.is_wildcard else ""
    name = f"'{entry.rendered_name}'" if entry.is_wildcard else entry.rendered_name
    return f"akit remove {_scope_flag(call, entry.scope)}{kind} {name}"


def _what_it_drops(entry: Subscription, covered: Sequence[str]) -> str:
    if not entry.is_wildcard:
        return f"the {SINGULAR[entry.kind]} from {entry.source}"
    every = f"every {SINGULAR[entry.kind]} from {entry.source}"
    return f"{every}: {', '.join(covered)}" if covered else every


def _offer(call: Call, chosen: editing.Chosen, pool: Sequence[Subscription]) -> list[str]:
    """Every subscription that can be removed, and the line that removes it.

    Printed rather than pointed at. The message this replaces sent a reader to
    `akit list`, which is where the name they just typed came from, so doing
    what it said produced the same name and the same refusal. What was missing
    was never the list of parts; it was which lines of the manifest are the
    removable things, and those are not the same set.

    Grouped by the command rather than by the line, because a name is a kit: a
    skill and the rule that makes a model reach for it are two lines and one
    `akit remove`, and printing that command twice would suggest running it
    twice.
    """
    lines: list[str] = []
    grouped: dict[str, list[Subscription]] = {}
    for entry in pool:
        grouped.setdefault(_invocation(call, entry), []).append(entry)
    for invocation, entries in grouped.items():
        lines.append(f"    {invocation}")
        lines.append(
            f"      drops {joined([_what_it_drops(entry, _covers(call, chosen, entry)) for entry in entries])}"
        )
    return lines


def _not_subscribed(call: Call, chosen: editing.Chosen, pool: Sequence[Subscription], name: str) -> UsageError:
    """What `remove` says about a name it cannot act on, which is three things.

    That the name is not a subscription; where it came from if a `"*"` is what
    puts it on disk, because that is the one case where `akit list` printed it
    and this refuses it; and what this manifest does hold, as commands.
    """
    where = f" in {chosen.path}" if call.scoped else ""
    said = [f"nothing is subscribed under the name `{name}`{where}."]
    for entry in pool:
        if entry.is_wildcard and name in _covers(call, chosen, entry):
            said.append(
                f"  It is one of the {PLURAL[entry.kind]} the subscription `*` from {entry.source} renders, "
                f"and that line is what can be dropped. Dropping it takes the others with it."
            )
    if pool:
        said.append("  What this manifest holds, and what drops each:")
        said.extend(_offer(call, chosen, pool))
    else:
        said.append("  This manifest subscribes to nothing at all.")
    return UsageError("\n".join(said))


def remove(call: Call, *, name: str, kind: Kind | None = None) -> Outcome:
    """Drop what one name subscribes to, and withdraw what it rendered.

    Withdraw, and nothing else. What the rest of the manifest would render is
    counted and named rather than written, which `_finish` is about.
    """
    chosen = call.chosen()
    pool = (
        chosen.manifest.subscriptions
        if call.scoped
        else manifests.load(call.start, user_path=call.places.user_manifest).subscriptions
    )
    found = _candidates(pool, name, kind)
    if not found:
        raise _not_subscribed(call, chosen, pool, name)
    written = chosen.manifest
    notes: list[Note] = []
    for wanted in _in_one_file(found, name, scoped=call.scoped):
        written = editing.unsubscribe(written, wanted)
        notes.append(
            Note(
                f"Unsubscribed: {SINGULAR[wanted.kind]} `{name}` from {wanted.source}.",
                {"kind": str(wanted.kind), "name": name, "source": wanted.source, "status": "removed"},
            )
        )
    return _finish(call, chosen, _Edit("remove", written, notes, changed=True, withdrawing=True))


def harness(call: Call, *, action: str, name: str, doors: Mapping[Kind, str] | None = None) -> Outcome:
    """Edit the `harnesses:` list, and render or withdraw for the harness named.

    `detected` is a name like any other here: removing it is how a repository
    pins the list to exactly what it names, and on a machine holding a harness
    the list no longer names, the render that follows withdraws that harness's
    files as any other removal would.

    **A name nobody knows can be removed and cannot be added.** Adding one is a
    typo and fails saying so. Removing one is how that typo gets taken out
    again, and it is the fix `akit doctor` names for it, so refusing here would
    leave the only way out of a misspelt harness list a hand edit.

    **Naming a destination is how one is changed as well as set.** A harness
    already in the list is ordinarily a no-op to add, and it stops being one
    when `--rules` or `--skills` says something the manifest does not: the
    entry is rewritten, and the render that follows withdraws from the
    destination it left.
    """
    _check_doors(name, doors)
    known = {*adapters.BY_NAME, adapters.DETECTED}
    chosen = call.chosen()
    listed = chosen.manifest.harnesses
    if name not in known and not (action == "remove" and name in listed):
        raise UsageError(f"no adapter answers to the harness `{name}`.\n  Known harnesses: {', '.join(sorted(known))}.")
    if action == "add":
        if name in listed and (doors or {}) == dict(chosen.manifest.doors.get(name, {})):
            note = Note(
                f"Already named: {name} is in the harnesses list of {chosen.path}.",
                {"harness": name, "status": "unchanged"},
            )
            return _finish(call, chosen, _Edit("harness", chosen.manifest, [note]))
        written = editing.name_harness(chosen.manifest, name, doors)
        note = Note(
            _named_note(name, doors, listed=name in listed),
            {"harness": name, "status": "changed" if name in listed else "added"}
            | ({"doors": {kind.value: door for kind, door in doors.items()}} if doors else {}),
        )
        return _finish(call, chosen, _Edit("harness", written, [note], changed=True))
    if name not in listed:
        note = Note(
            f"Not named: {name} was not in the harnesses list of {chosen.path}.",
            {"harness": name, "status": "unchanged"},
        )
        return _finish(call, chosen, _Edit("harness", chosen.manifest, [note]))
    written = editing.unname_harness(chosen.manifest, name)
    note = Note(
        f"Dropped: {name} is no longer rendered for, and what it rendered is withdrawn.",
        {"harness": name, "status": "removed"},
    )
    return _finish(call, chosen, _Edit("harness", written, [note], changed=True, withdrawing=True))


def _named_note(name: str, doors: Mapping[Kind, str] | None, *, listed: bool) -> str:
    """What `harness add` says it did, which differs when the harness was already there."""
    if not doors:
        return f"Named: {name} is now rendered for, installed on this machine or not."
    sent = ", ".join(f"{kind.value} to {door}" for kind, door in doors.items())
    if listed:
        return f"Changed: {name} now sends {sent}, and what it wrote elsewhere is withdrawn."
    return f"Named: {name} is now rendered for, sending {sent}."


def _check_doors(name: str, doors: Mapping[Kind, str] | None) -> None:
    """A destination this harness does not offer, typed just now, is a usage error.

    The same split `--harness` keeps: a name in a manifest is somebody else's
    file and gets reported, and a name you typed a moment ago is a mistake to
    correct before anything is written.
    """
    adapter = adapters.BY_NAME.get(name)
    if adapter is None:
        return
    for kind, door in (doors or {}).items():
        offered = adapter.variants(kind)
        if door not in offered:
            known = ", ".join(offered) if offered else "none: it has one destination for that kind"
            raise UsageError(f"{name} has no {kind.value} destination called `{door}`.\n  It offers: {known}.")


@dataclass(frozen=True)
class _Key:
    """One source key under one kind block, which is the unit a pin belongs to."""

    kind: Kind
    key: str
    source: str
    pin: str | None
    names: tuple[str, ...]


def _keys(found: Manifest, name: str | None) -> tuple[_Key, ...]:
    """Every pin this run may move, grouped the way the manifest groups them.

    A pin is a property of the key and not of each name beneath it, so a key
    whose names are not all still there moves for none of them (DESIGN.md
    section 10).
    """
    grouped: dict[tuple[Kind, str], list[Subscription]] = {}
    for entry in found.subscriptions:
        grouped.setdefault((entry.kind, entry.key), []).append(entry)
    wanted = [
        _Key(kind=kind, key=key, source=entries[0].source, pin=entries[0].pin, names=tuple(e.name for e in entries))
        for (kind, key), entries in grouped.items()
        if name is None or any(entry.rendered_name == name for entry in entries)
    ]
    if name is not None and not wanted:
        raise UsageError(
            f"nothing is subscribed under the name `{name}` in {found.path}.\n"
            "  Run `akit list` to see what is, or drop the name to update everything."
        )
    return tuple(wanted)


def _diff_paths(key: SourceKey, parts: Iterable[discovery.Part]) -> tuple[str, ...]:
    """Where each part sits inside the repository, which is what git is handed."""
    prefix = "" if key.subdirectory is None else f"{key.subdirectory}/"
    return tuple(sorted({f"{prefix}{part.relative}" for part in parts}))


@dataclass(frozen=True)
class _Moved:
    """One key's answer: what it moved to, or why it did not move."""

    note: Note
    pin: str | None
    comment: str | None
    diff: str
    onto: str | None = None
    """The source key that replaces this one, for a key whose branch landed elsewhere."""


def _places_of(found: Iterable[discovery.Part]) -> tuple[str, ...]:
    return tuple(sorted({part.relative for part in found}))


def _before(entry: _Key, places: render.Directories, anchor: Path) -> dict[str, tuple[str, ...]]:
    """Where each name sat at the commit the manifest is pinned to, for the move report.

    Read offline from the cache, because this is the commit `render` has been
    using all along. A cache that no longer holds it reports nothing rather than
    failing: a pin the cache has lost is `akit doctor`'s finding, and `update` is
    on its way to replacing that pin anyway.
    """
    key = sources.parse(entry.source)
    if entry.pin is None:
        return {}
    try:
        resolved = cache.resolve(key, pin=entry.pin, anchor=anchor, cache_root=places.cache, offline=True)
    except cache.CacheError:
        return {}
    return {name: _places_of(_parts(resolved.root, entry.kind, name)) for name in entry.names}


def _moved_parts(before: dict[str, tuple[str, ...]], after: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    """Names whose directory inside the source changed.

    Reported rather than acted on, because it is cheap to notice now and
    surprising to discover later (DESIGN.md section 10).
    """
    return tuple(
        f"{name} moved from {', '.join(was)} to {', '.join(after[name])}"
        for name, was in before.items()
        if was and after.get(name) and was != after[name]
    )


def _vanished(entry: _Key, before: dict[str, tuple[str, ...]], root: Path) -> tuple[str, ...]:
    """What a `"*"` subscription stopped covering, which is the one thing it can do quietly."""
    if discovery.WILDCARD not in entry.names:
        return ()
    was = set(before.get(discovery.WILDCARD, ()))
    now = {part.relative for part in _parts(root, entry.kind, discovery.WILDCARD)}
    return tuple(sorted(was - now))


def _stopped(entry: _Key, fetched: Fetched, missing: Sequence[str]) -> _Moved:
    return _Moved(
        note=Note(
            f"{entry.kind.value}: {entry.source} has no {SINGULAR[entry.kind]} called "
            f"{', '.join(missing)} at {fetched.commit[:SHORT]}, so its pin stays at {(entry.pin or '')[:SHORT]}.\n"
            f"  Upstream deleted it or renamed it, and the two want opposite things. Three ways out:\n"
            f"    akit remove {missing[0]}            # it is gone\n"
            f"    akit add {entry.source} <new-name>  # it was renamed\n"
            f"    keep this key where it is, and subscribe to the rest under a second key",
            {"source": entry.source, "kind": str(entry.kind), "status": "stopped", "missing": list(missing)},
        ),
        pin=None,
        comment=None,
        diff="",
    )


def _unmoved(entry: _Key, text: str, status: str, data: dict[str, Any]) -> _Moved:
    return _Moved(
        note=Note(text, {"source": entry.source, "kind": str(entry.kind), "status": status, **data}),
        pin=None,
        comment=None,
        diff="",
    )


@dataclass(frozen=True)
class _Asked:
    """What one run of `update` brings to every key: where things are, and what was typed."""

    places: render.Directories
    anchor: Path
    to: str | None = None
    """`--to`: the branch every key this run touches follows from now on."""


def _target(entry: _Key, origin: manifests.Origin, branch: str) -> SourceKey:
    """The key a subscription moves to: `branch`, in the repository the pull request merges into.

    A key that came from no pull request moves within its own repository. The
    directory a key selected comes along, because the kits are expected to sit
    where they sat. A key with no forge layout cannot be given a branch at all,
    and saying so here is better than writing one that reads differently.
    """
    key = sources.parse(entry.source)
    base = key.url if origin.merges_into is None else sources.parse(origin.merges_into).url
    moved = sources.parse(sources.at_branch(base, branch, key.subdirectory))
    if moved.ref != branch:
        raise UsageError(
            f"{entry.source} is not a forge URL, so it cannot be pointed at a branch by name.\n"
            f"  Pin it yourself instead: akit add '{entry.source}#{branch}' <kit>"
        )
    return moved


def _same_parts(entry: _Key, key: SourceKey, target: SourceKey, landed: Fetched, places: render.Directories) -> bool:
    """Whether every part this key names is the same, byte for byte, at the target's tip.

    The check that survives a squash merge, which rewrites every commit and
    leaves the content alone. It compares git's own object ids for each part's
    directory, which name content rather than history and so mean the same
    thing in a fork as in the repository it merged into.

    The target's parts are read first. A pull request from a branch of the
    same repository shares one clone with its target, and reading the pinned
    commit checks that clone out at it.
    """
    new = _diff_paths(target, [part for name in entry.names for part in _parts(landed.root, entry.kind, name)])
    pin = entry.pin or ""
    try:
        resolved = cache.resolve(key, pin=pin, anchor=places.home, cache_root=places.cache, offline=True)
    except cache.CacheError:
        return False
    old = _diff_paths(key, [part for name in entry.names for part in _parts(resolved.root, entry.kind, name)])
    inside = [path.removeprefix(_prefix(key)) for path in old]
    if not old or inside != [path.removeprefix(_prefix(target)) for path in new]:
        return False
    return all(
        cache.object_id(key, pin, was, cache_root=places.cache)
        == cache.object_id(target, landed.commit, now, cache_root=places.cache)
        for was, now in zip(old, new, strict=True)
    )


def _prefix(key: SourceKey) -> str:
    return "" if key.subdirectory is None else f"{key.subdirectory}/"


def _branch_gone(entry: _Key, key: SourceKey, origin: manifests.Origin, asked: _Asked) -> _Moved:
    """A key whose branch the remote no longer has: landed and followed, or stopped with the ways out.

    Git alone decides, because the forge was asked once when this was added and
    its answer is in the manifest. The kits have landed when the pinned commit
    is in the target's history, which a merge or a fast-forward leaves, or when
    every part is identical at the target's tip, which is what a squash leaves.
    Anything else stops: an abandoned pull request's branch is deleted too, and
    following its target then would subscribe somebody to what they never chose.
    """
    if origin.merges_into is not None and entry.pin is not None:
        target = _target(entry, origin, sources.parse(origin.merges_into).ref or "")
        try:
            landed = cache.refresh(target, ref=target.ref, cache_root=asked.places.cache)
        except cache.MissingRefError:
            landed = None
        if landed is None:
            return _gone(entry, key, origin)
        gone = f"its branch `{key.ref}` is gone and"
        if cache.contains(target, entry.pin, landed.commit, cache_root=asked.places.cache):
            said = f"{gone} {origin.pull_request or 'its last commit'} was merged into {target.ref}"
        elif _same_parts(entry, key, target, landed, asked.places):
            said = f"{gone} what it subscribes to is identical at the tip of {target.ref}"
        else:
            return _gone(entry, key, origin)
        discovering.classify(target, landed.privacy, asked.places.state)
        return _switched(entry, key, landed, said, asked.places)
    return _gone(entry, key, origin)


def _gone(entry: _Key, key: SourceKey, origin: manifests.Origin) -> _Moved:
    """The refusal for a deleted branch, naming what it was and the three ways on."""
    pin = (entry.pin or "")[:SHORT]
    name = entry.names[0]
    pull = "" if origin.pull_request is None else f" (pull request {origin.pull_request})"
    if origin.merges_into is None:
        why = "and nothing in the manifest says where it went"
        branch = "<branch>"
    else:
        target = sources.parse(origin.merges_into)
        why = f"and akit could not confirm its kits landed in {target.ref} of {target.url}"
        branch = target.ref or "<branch>"
    return _Moved(
        note=Note(
            f"{entry.kind.value}: {entry.source} used to track the branch `{key.ref}`{pull}, which is now deleted, "
            f"{why}, so its pin stays at {pin}.\n"
            f"  It may have been merged with its kits changed on the way, or abandoned. Three ways on:\n"
            f"    akit update {name} --to {branch}   # follow {branch} from now on\n"
            f"    akit remove {name}   # drop it\n"
            f"    leave it pinned at {pin} by not updating it",
            {
                "source": entry.source,
                "kind": str(entry.kind),
                "status": "stopped",
                "reason": "branch deleted",
                "branch": key.ref,
                "pull_request": origin.pull_request,
                "merges_into": origin.merges_into,
            },
        ),
        pin=None,
        comment=None,
        diff="",
    )


def _switched(entry: _Key, key: SourceKey, fetched: Fetched, why: str, places: render.Directories) -> _Moved:
    """A key that follows another branch from now on, with what moved under it.

    The diff is shown where the two branches share a clone, which is every pull
    request from a branch of the same repository. Across a fork there is no one
    clone holding both commits, and the move is reported without one.
    """
    target = fetched.source
    found = {name: _parts(fetched.root, entry.kind, name) for name in entry.names}
    missing = sorted(name for name, parts in found.items() if not parts and name != discovery.WILDCARD)
    if missing:
        return _stopped(entry, fetched, missing)
    diff = ""
    if entry.pin is not None and key.identity == target.identity:
        every = [part for parts in found.values() for part in parts]
        diff = cache.difference(target, entry.pin, fetched.commit, _diff_paths(target, every), cache_root=places.cache)
    was = "an unpinned key" if entry.pin is None else entry.pin[:SHORT]
    return _Moved(
        note=Note(
            f"{entry.kind.value}: {entry.source} now follows {target.raw}, because {why}. "
            f"It moves from {was} to {fetched.commit[:SHORT]}.",
            {
                "source": entry.source,
                "kind": str(entry.kind),
                "status": "moved",
                "from": entry.pin,
                "to": fetched.commit,
                "ref": fetched.ref,
                "onto": target.raw,
                "changed": bool(diff.strip()),
            },
        ),
        pin=fetched.commit,
        comment=discovering.frozen_comment(fetched),
        diff=diff,
        onto=target.raw,
    )


def _update_key(entry: _Key, origin: manifests.Origin, asked: _Asked) -> _Moved:
    """One key, asked what moved, and answered without ever editing a name."""
    places, anchor = asked.places, asked.anchor
    key = sources.parse(entry.source)
    if not key.is_remote:
        return _unmoved(
            entry,
            f"{entry.kind.value}: {entry.source} is a path, which has no pin: it is read as it is on disk.",
            "path",
            {},
        )
    if asked.to is not None:
        target = _target(entry, origin, asked.to)
        fetched = cache.refresh(target, ref=target.ref, cache_root=places.cache)
        discovering.classify(target, fetched.privacy, places.state)
        return _switched(entry, key, fetched, f"it was asked to follow `{asked.to}`", places)
    before = _before(entry, places, anchor)
    try:
        fetched = cache.refresh(key, ref=key.ref, cache_root=places.cache)
    except cache.MissingRefError:
        if key.ref is None:
            raise
        return _branch_gone(entry, key, origin, asked)
    discovering.classify(key, fetched.privacy, places.state)
    if fetched.commit == entry.pin:
        return _unmoved(
            entry,
            f"{entry.kind.value}: {entry.source} is already at the newest commit of {fetched.ref}.",
            "unchanged",
            {"ref": fetched.ref},
        )
    found = {name: _parts(fetched.root, entry.kind, name) for name in entry.names}
    missing = sorted(name for name, parts in found.items() if not parts and name != discovery.WILDCARD)
    if missing:
        return _stopped(entry, fetched, missing)
    after = {name: _places_of(parts) for name, parts in found.items()}
    every = [part for parts in found.values() for part in parts]
    diff = ""
    if entry.pin is not None:
        diff = cache.difference(key, entry.pin, fetched.commit, _diff_paths(key, every), cache_root=places.cache)
    was = "an unpinned key" if entry.pin is None else entry.pin[:SHORT]
    said = [
        f"{entry.kind.value}: {entry.source} moves from {was} to {fetched.commit[:SHORT]}, following {fetched.ref}.",
        *(f"  {moved}" for moved in _moved_parts(before, after)),
        *(f"  gone upstream: {gone}" for gone in _vanished(entry, before, fetched.root)),
    ]
    return _Moved(
        note=Note(
            "\n".join(said),
            {
                "source": entry.source,
                "kind": str(entry.kind),
                "status": "moved",
                "from": entry.pin,
                "to": fetched.commit,
                "ref": fetched.ref,
                "changed": bool(diff.strip()),
                "moved_parts": list(_moved_parts(before, after)),
                "gone": list(_vanished(entry, before, fetched.root)),
            },
        ),
        pin=fetched.commit,
        comment=discovering.frozen_comment(fetched),
        diff=diff,
    )


def _said(moved: _Moved) -> str:
    """The one phrase the live account gets for a key, from the status it answered with."""
    status = str(moved.note.data.get("status", ""))
    if status == "moved" and moved.pin is not None:
        return f"moved to {moved.pin[:SHORT]}"
    return PROGRESS.get(status, status)


def update(call: Call, *, name: str | None = None, watching: Watcher = UNWATCHED, to: str | None = None) -> Outcome:
    """Fetch, move the pins that may move, and say what changed under each one.

    Three things happen here and the slow one is in the middle. Reading the
    manifest is local and instant; fetching is one network round trip per key;
    rendering is local again. So the count is announced before the loop rather
    than after it, and each key reports the moment it answers, because a person
    waiting on six fetches should be able to see which one they are waiting on.

    `watching` is silent unless a caller asked for it, and nothing it says is
    said only there.

    A project with no manifest is not an error here. There are no pins to move,
    which this says in one sentence; it is `add` that has to refuse, because
    `add` is the one with something to put in a file it would be creating.
    """
    if to is not None and name is None:
        raise UsageError(
            "--to moves a subscription onto another branch, and needs the name of the one to move.\n"
            f"  akit update <name> --to {to}"
        )
    chosen = call.chosen(creating=False)
    keys = _keys(chosen.manifest, name)
    asked = _Asked(places=call.places, anchor=_anchor(chosen.scope, call.start, call.places.home), to=to)
    left: set[str] = set()
    watching.starting(chosen.path, subscriptions=len(chosen.manifest.subscriptions), keys=len(keys))
    column = Column.of([_named(entry) for entry in keys], watching.style)
    written = chosen.manifest
    notes: list[Note] = []
    diffs: list[str] = []
    movements: list[Movement] = []
    changed = False
    for entry in keys:
        moved = _update_key(entry, chosen.manifest.origin(entry.source), asked)
        watching.resolved(entry, _said(moved), column)
        notes.append(moved.note)
        if moved.pin is None:
            continue
        if moved.onto is None:
            written = editing.repin(written, kind=entry.kind, key=entry.key, pin=moved.pin, comment=moved.comment)
        else:
            written = editing.rekey(
                written,
                kind=entry.kind,
                key=entry.key,
                to=f"{moved.onto}{manifests.PIN}{moved.pin}",
                comment=moved.comment,
            )
            left.add(entry.source)
        changed = True
        movements.append(
            Movement(
                kind=entry.kind,
                source=entry.source,
                was=entry.pin,
                now=moved.pin,
                ref=str(moved.note.data.get("ref", "")),
                diff=moved.diff,
                onto=moved.onto,
            )
        )
        if moved.diff.strip():
            diffs.append(moved.diff)
    for source in sorted(left):
        written = editing.forget_source(written, source)
    watching.finished(keys=len(keys))
    return _finish(call, chosen, _Edit(UPDATE, written, notes, changed=changed, diffs=diffs, moved=movements))


def _finish(call: Call, chosen: editing.Chosen, edit: _Edit) -> Outcome:
    """Write the manifest if it changed, then render or withdraw, as the verb asks.

    **The two additive verbs render and the two subtractive ones do not.** A
    kit you just subscribed to has to be on disk when `add` returns, or the
    command has told you about a file that is not there. A kit you just dropped
    has to be off disk for the same reason, and that is a withdrawal, which is
    the half of a render that deletes. Making `remove` perform the other half
    as well meant a command that reads as subtractive catching the whole
    manifest up in passing, writing files no previous command had written, into
    directories the removal had nothing to do with (DESIGN.md section 10). What
    it does instead is count them and name `akit render`.

    **A refusal puts the manifest back.** `add` and `harness add` are the two
    commands that can create a leak, and the render that follows them is what
    notices (DESIGN.md section 8). It cannot notice before the line is written,
    because what it judges is the manifest on disk, and asking the question a
    second way here would be a second definition of the word "leak" that could
    drift from the engine's. So the line is written, the render decides, and a
    refusal restores the file byte for byte before it reaches the caller.

    What that leaves is total from where the caller stands: exit code 3, the
    manifest it had, and nothing rendered.

    **The render covers the scope that was edited and no other.** These commands
    write one manifest, and a report about the other one answers a question
    nobody asked: `akit add --global` has nothing to say about what this project
    subscribes to, and saying it anyway buries the thing that did change. The
    other scope is a whole `akit render` away for anybody who wants it.
    """
    before = _bytes_of(chosen.path) if edit.changed else None
    if edit.changed:
        manifests.write(edit.written, chosen.path)
    try:
        rendered = render.render(
            call.start,
            call.places,
            render.Choices(scopes=(chosen.scope,)),
            render.WITHDRAWING if edit.withdrawing else render.RENDERING,
        )
    except RefusalError:
        _restore(chosen.path, before)
        raise
    return Outcome(
        command=edit.command,
        path=chosen.path,
        scope=chosen.scope,
        created=edit.changed and not chosen.existed,
        notes=tuple(edit.notes),
        rendered=rendered,
        changed=edit.changed,
        diffs=tuple(edit.diffs),
        moved=tuple(edit.moved),
    )


def _bytes_of(path: Path) -> bytes | None:
    """What the manifest held, or `None` for one this command is about to create."""
    return path.read_bytes() if path.is_file() else None


def _restore(path: Path, before: bytes | None) -> None:
    """Put the manifest back exactly, including back to not existing at all."""
    if before is None:
        path.unlink(missing_ok=True)
    else:
        path.write_bytes(before)


def _stopped_notes(outcome: Outcome) -> tuple[Note, ...]:
    """The keys that found a part gone upstream, which is the one thing `update` cannot decide."""
    return tuple(note for note in outcome.notes if note.data.get("status") == "stopped")


def _print_upstream(outcome: Outcome, out: TextIO, style: Style) -> None:
    """Every pin that moved, and under each one the diff that pin names.

    One group per key rather than per kit, because a pin belongs to a key: a
    key holding three kits moves for all three or for none, and the diff over
    the three is the change that pin actually is.

    A key that moved while nothing under it that you subscribe to changed gets
    a trailing line rather than a heading of its own. A heading with nothing
    beneath it reads as something missing, and on a `*` subscription following
    an active branch most of them would be empty.
    """
    section("Changed upstream", out, style)
    if not outcome.moved:
        print("nothing moved: every pin is already at the newest commit it follows", file=out)
        print("", file=out)
        return
    for movement in outcome.moved:
        if not movement.changed:
            continue
        group(movement.heading, out, style)
        print(movement.diff.rstrip("\n"), file=out)
        print("", file=out)
    quiet = [movement for movement in outcome.moved if not movement.changed]
    if quiet:
        moved = joined([f"{movement.kind.value} from {movement.source}" for movement in quiet])
        print(f"Moved without changing anything you subscribe to: {moved}.", file=out)
        print("", file=out)


def _print_nothing_found(outcome: Outcome, out: TextIO, style: Style) -> None:
    """The whole answer for a manifest with nothing in it, which is one sentence.

    On `stdout` rather than with the live account, because it is what the
    command found rather than a sign that it is still working. A person who
    redirected the output to read later should not get an empty file.
    """
    where = MISSING[outcome.scope] if outcome.path is None else str(outcome.path)
    print(f"No subscriptions found in {style.place(where)}, not looking for updates.", file=out)


def _print_followed(outcome: Outcome, out: TextIO, style: Style) -> None:
    """Keys that follow another branch from now on, each with the reason it moved.

    Its own section because it is a different change from a pin moving: the
    manifest now names another branch, often another repository, and a person
    reading the report should not have to find that out from `akit list`.
    """
    followed = [note for note in outcome.notes if note.data.get("onto")]
    if not followed:
        return
    section("Now following another branch", out, style)
    for note in followed:
        wrapped(f"- {note.text}", [], out, indent="")
    print("", file=out)


def _print_stopped(outcome: Outcome, out: TextIO, style: Style) -> None:
    """Keys whose pin stayed put because a part they name is gone from the source."""
    stopped = _stopped_notes(outcome)
    if not stopped:
        return
    section("Stopped", out, style)
    for note in stopped:
        said = note.text.splitlines()
        wrapped(f"- {said[0]}", said[1:], out, indent="")
    print("", file=out)


def _print_edit(outcome: Outcome, out: TextIO, style: Style) -> None:
    """What a manifest-writing command did to the file it was pointed at."""
    section(manifest_title(outcome.scope, outcome.path), out, style)
    if outcome.created and outcome.path is not None:
        print(f"Created {style.place(str(outcome.path))}.", file=out)
    for note in outcome.notes:
        said = note.text.splitlines()
        wrapped(f"- {said[0]}", said[1:], out, indent="")
    print("", file=out)


def text(outcome: Outcome, out: TextIO, *, style: Style | None = None) -> None:
    """What happened to the manifest, and under it the render that followed.

    Two shapes, because `update` and the other three answer different
    questions. `add`, `remove` and `harness` change one line and say which;
    `update` asks every key whether it may move and reports what came back, so
    its sections are what moved and what the move contained.

    What either of them says is a list, written the way every other list in a
    report is, because a reader who has just met one in the section below
    should not have to learn a second shape for the section above it.

    A diff keeps its own format. It is a diff, people read those as diffs, and
    wrapping one in this report's furniture would make it harder to read rather
    than more familiar. What it does get is a heading saying what it is a diff
    of, which `diff --git a/skills/akit/VERSION` alone does not.

    An `update` with no subscriptions to look at is one sentence and no
    sections. Three headed sections agreeing that nothing happened is a report
    about the absence of a report. It goes no further than that sentence only
    while the render it ends with also did nothing, so this cannot hide a
    withdrawal.

    **The file is named once.** The section above says which manifest was
    edited, and the one below used to repeat the same path under a different
    heading, which reads as two reports about two files until you compare the
    characters. The second heading stays and its path goes.
    """
    shown = style or Style.plain()
    if outcome.found_nothing:
        _print_nothing_found(outcome, out, shown)
        if outcome.rendered.quiet and not outcome.rendered.withdrawals:
            return
        print("", file=out)
    elif outcome.command == UPDATE:
        _print_upstream(outcome, out, shown)
        _print_followed(outcome, out, shown)
        _print_stopped(outcome, out, shown)
    else:
        _print_edit(outcome, out, shown)
    render.text(outcome.rendered, out, style=shown, naming=False)


def payload(outcome: Outcome) -> dict[str, Any]:
    return {
        "command": outcome.command,
        "manifest": None if outcome.path is None else str(outcome.path),
        "scope": str(outcome.scope),
        "created": outcome.created,
        "changed": outcome.changed,
        "notes": [{"said": note.text, **note.data} for note in outcome.notes],
        "diffs": list(outcome.diffs),
        "moved": [
            {
                "kind": str(movement.kind),
                "source": movement.source,
                "from": movement.was,
                "to": movement.now,
                "ref": movement.ref,
                "changed": movement.changed,
                "diff": movement.diff,
                "onto": movement.onto,
            }
            for movement in outcome.moved
        ],
        "render": render.payload(outcome.rendered),
    }


def report(outcome: Outcome, out: TextIO, *, as_json: bool) -> Exit:
    """One command's answer, in whichever form was asked for."""
    if as_json:
        print(json.dumps(payload(outcome), indent=2), file=out)
    else:
        text(outcome, out, style=Style.of(out))
    return outcome.exit_code


__all__ = [
    "BY_FLAG",
    "AmbiguityError",
    "Call",
    "Note",
    "Outcome",
    "add",
    "harness",
    "payload",
    "remove",
    "report",
    "text",
    "update",
]
