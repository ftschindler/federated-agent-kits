"""The four commands that write a manifest: `add`, `remove`, `update`, `harness`.

One shape between them. Each one decides which manifest it is editing, makes one
edit, writes the file back, and renders, so that the kit is usable when the
command returns rather than after a second command somebody has to know about.
Nobody has to hold the manifest format in their head, which is the whole point
of these four existing at all.

**Only two commands fetch, and both are here.** `add` clones a source this
machine does not have, and `update` asks a source it does have what moved
(DESIGN.md section 10). Everything else in this package works from the cache, so
a render on a train produces what it produced yesterday, and that property is
kept by these two being the only places `cache.refresh` is called.

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
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from federated_agent_kits import adapters, cache, discovery, editing, privacy, render, sources
from federated_agent_kits import manifest as manifests
from federated_agent_kits.cache import Fetched, Privacy, RefKind, UnreachableError
from federated_agent_kits.exits import Exit, RefusalError, UsageError
from federated_agent_kits.manifest import Kind, Manifest, Scope, Subscription
from federated_agent_kits.sources import SourceKey

#: A pin somebody typed that is already an answer. Checked rather than asked
#: about, because a commit cannot move and the remote has nothing to add.
COMMIT = re.compile(r"[0-9a-f]{7,40}")

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

    def chosen(self) -> editing.Chosen:
        return editing.choose(
            self.start,
            only_global=self.only_global,
            only_project=self.only_project,
            named=self.named,
            user_path=self.places.user_manifest,
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


@dataclass(frozen=True)
class _Edit:
    """One manifest edit, before it is written and rendered."""

    command: str
    written: Manifest
    notes: list[Note] = field(default_factory=list)
    changed: bool = False
    diffs: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Outcome:
    """What a manifest-writing command did, before the render it ends with."""

    command: str
    path: Path | None
    created: bool
    notes: tuple[Note, ...]
    rendered: render.Outcome
    changed: bool
    diffs: tuple[str, ...] = ()
    """What `update` found between the old commit and the new one, per key that moved."""

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


def _offered(root: Path) -> dict[Kind, tuple[str, ...]]:
    """Every part the source holds, by kind, which is what a typo gets told."""
    found: dict[Kind, tuple[str, ...]] = {}
    for kind in SEARCHED:
        names = tuple(
            sorted(
                {part.name for part in discovery.parts(root, kind, extra_directories=adapters.source_directories(kind))}
            )
        )
        if names:
            found[kind] = names
    return found


def _described(offered: dict[Kind, tuple[str, ...]]) -> str:
    if not offered:
        return "  That source holds no skills, rules or agents at all."
    lines = [f"  It holds {kind.value}: {', '.join(names)}" for kind, names in offered.items()]
    return "\n".join(lines)


def _resolve_for_add(
    key: SourceKey,
    ref: str | None,
    *,
    anchor: Path,
    cache_root: Path | None,
    state_root: Path | None,
) -> tuple[Path, str | None, str | None]:
    """The source as a directory, the commit to pin to, and what the comment says.

    A path source has no pin and no comment. A commit somebody typed is already
    an answer and is only fetched. Anything else is a name on the other end, so
    the remote is asked what it points at now, and a machine that cannot reach it
    but already holds a clone pins to what it has rather than failing: `add` of a
    cached source works offline (DESIGN.md section 10).

    **Whatever the fetch learned about how private the source is, is written
    down here.** It is only observable while cloning, and the command that
    refuses to commit a private kit runs long afterwards and on a different day
    (DESIGN.md section 8). A fetch that classified nothing, because the cache
    already held the source, leaves what was already known.
    """
    if not key.is_remote:
        if ref is not None:
            raise UsageError(
                f"{key.raw}#{ref}: a path source has no commit to pin.\n"
                "  Drop the `#`, or subscribe to the repository rather than to the directory."
            )
        return cache.resolve(key, anchor=anchor, cache_root=cache_root).root, None, None
    if ref is not None and COMMIT.fullmatch(ref):
        resolved = cache.resolve(key, pin=ref, anchor=anchor, cache_root=cache_root)
        _classified(key, resolved.privacy, state_root)
        return resolved.root, ref, None
    try:
        fetched = cache.refresh(key, ref=ref, cache_root=cache_root)
    except UnreachableError:
        resolved = cache.resolve(key, anchor=anchor, cache_root=cache_root, offline=True)
        return resolved.root, resolved.commit, "frozen: the commit this machine already had"
    _classified(key, fetched.privacy, state_root)
    return fetched.root, fetched.commit, _frozen(fetched)


def _classified(key: SourceKey, found: Privacy | None, state_root: Path | None) -> None:
    """Remember what this fetch turned out to need, or leave what was known.

    `None` means this resolution never went near the network, so it learned
    nothing and has nothing to say. Writing it as a classification would turn a
    silence into an answer, and the answer it would turn into is the guess
    DESIGN.md section 8 forbids.
    """
    if found is None:
        return
    privacy.save({**privacy.load(state_root), key.raw: found}, state_root)


def _frozen(fetched: Fetched) -> str:
    """The comment beside a pin: what it followed, and when for the thing that moves.

    A tag does not move, so dating one would say something untrue about it. A
    branch does, so the date is the only part of the comment that tells a reader
    how old the pin is. Nothing parses either, which is the only safe thing to do
    with a comment.
    """
    if fetched.kind is RefKind.TAG:
        return f"frozen: {fetched.ref}"
    return f"frozen: {fetched.ref}, {datetime.now(tz=UTC).date().isoformat()}"


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
    raw, ref = manifests.split_pin(source)
    key = sources.parse(raw)
    anchor = _anchor(chosen.scope, call.start, call.places.home)
    root, pin, comment = _resolve_for_add(
        key, ref, anchor=anchor, cache_root=call.places.cache, state_root=call.places.state
    )
    holding = _kinds_holding(root, name, kind)
    if not holding:
        wanted = "" if kind is None else f", as a {SINGULAR[kind]}"
        raise UsageError(f"{raw} holds no kit called `{name}`{wanted}.\n{_described(_offered(root))}")
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
                    f"at {existing.pin[:9] if existing.pin else 'the path it is read from'}.",
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
        where = f" at {pin[:9]}" if pin is not None else ""
        notes.append(
            Note(
                f"Subscribed: {SINGULAR[holds]} `{rendered}` from {raw}{where}.",
                {"kind": str(holds), "name": rendered, "source": raw, "pin": pin, "status": "added"},
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
            "what everybody else gets.\n  Name the file: --global for yours, --project for this repository's."
        )
    return tuple(found)


def remove(call: Call, *, name: str, kind: Kind | None = None) -> Outcome:
    """Drop what one name subscribes to, and withdraw what it rendered."""
    chosen = call.chosen()
    pool = (
        chosen.manifest.subscriptions
        if call.scoped
        else manifests.load(call.start, user_path=call.places.user_manifest).subscriptions
    )
    found = _candidates(pool, name, kind)
    if not found:
        where = f" in {chosen.path}" if call.scoped else ""
        raise UsageError(
            f"nothing is subscribed under the name `{name}`{where}.\n"
            "  Run `akit list` to see what is, and check the name it is rendered under."
        )
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
    return _finish(call, chosen, _Edit("remove", written, notes, changed=True))


def harness(call: Call, *, action: str, name: str) -> Outcome:
    """Edit the `harnesses:` list, and render or withdraw for the harness named.

    `detected` is a name like any other here: removing it is how a repository
    pins the list to exactly what it names, and on a machine holding a harness
    the list no longer names, the render that follows withdraws that harness's
    files as any other removal would.
    """
    known = {*adapters.BY_NAME, adapters.DETECTED}
    if name not in known:
        raise UsageError(f"no adapter answers to the harness `{name}`.\n  Known harnesses: {', '.join(sorted(known))}.")
    chosen = call.chosen()
    listed = chosen.manifest.harnesses
    if action == "add":
        if name in listed:
            note = Note(
                f"Already named: {name} is in the harnesses list of {chosen.path}.",
                {"harness": name, "status": "unchanged"},
            )
            return _finish(call, chosen, _Edit("harness", chosen.manifest, [note]))
        written = editing.name_harness(chosen.manifest, name)
        note = Note(
            f"Named: {name} is now rendered for, installed on this machine or not.",
            {"harness": name, "status": "added"},
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
    return _finish(call, chosen, _Edit("harness", written, [note], changed=True))


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
            f"{', '.join(missing)} at {fetched.commit[:9]}, so its pin stays at {(entry.pin or '')[:9]}.\n"
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


def _update_key(entry: _Key, places: render.Directories, anchor: Path) -> _Moved:
    """One key, asked what moved, and answered without ever editing a name."""
    key = sources.parse(entry.source)
    if not key.is_remote:
        return _unmoved(
            entry,
            f"{entry.kind.value}: {entry.source} is a path, which has no pin: it is read as it is on disk.",
            "path",
            {},
        )
    before = _before(entry, places, anchor)
    fetched = cache.refresh(key, ref=key.ref, cache_root=places.cache)
    _classified(key, fetched.privacy, places.state)
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
    was = "an unpinned key" if entry.pin is None else entry.pin[:9]
    said = [
        f"{entry.kind.value}: {entry.source} moves from {was} to {fetched.commit[:9]}, following {fetched.ref}.",
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
        comment=_frozen(fetched),
        diff=diff,
    )


def update(call: Call, *, name: str | None = None) -> Outcome:
    """Fetch, move the pins that may move, and print what changed under each one."""
    chosen = call.chosen()
    written = chosen.manifest
    notes: list[Note] = []
    diffs: list[str] = []
    changed = False
    for entry in _keys(chosen.manifest, name):
        moved = _update_key(entry, call.places, _anchor(chosen.scope, call.start, call.places.home))
        notes.append(moved.note)
        if moved.pin is None:
            continue
        written = editing.repin(written, kind=entry.kind, key=entry.key, pin=moved.pin, comment=moved.comment)
        changed = True
        if moved.diff.strip():
            diffs.append(moved.diff)
    return _finish(call, chosen, _Edit("update", written, notes, changed=changed, diffs=diffs))


def _finish(call: Call, chosen: editing.Chosen, edit: _Edit) -> Outcome:
    """Write the manifest if it changed, then render, which every one of these ends with.

    **A refusal puts the manifest back.** `add` and `harness add` are the two
    commands that can create a leak, and the render that follows them is what
    notices (DESIGN.md section 8). It cannot notice before the line is written,
    because what it judges is the manifest on disk, and asking the question a
    second way here would be a second definition of the word "leak" that could
    drift from the engine's. So the line is written, the render decides, and a
    refusal restores the file byte for byte before it reaches the caller.

    What that leaves is total from where the caller stands: exit code 3, the
    manifest it had, and nothing rendered.
    """
    before = _bytes_of(chosen.path) if edit.changed else None
    if edit.changed:
        manifests.write(edit.written, chosen.path)
    try:
        rendered = render.render(call.start, call.places)
    except RefusalError:
        _restore(chosen.path, before)
        raise
    return Outcome(
        command=edit.command,
        path=chosen.path,
        created=edit.changed and not chosen.existed,
        notes=tuple(edit.notes),
        rendered=rendered,
        changed=edit.changed,
        diffs=tuple(edit.diffs),
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


def text(outcome: Outcome, out: TextIO) -> None:
    """What happened, in sentences, with the render that followed underneath it."""
    if outcome.created and outcome.path is not None:
        print(f"Created {outcome.path}.", file=out)
    for note in outcome.notes:
        print(note.text, file=out)
    for diff in outcome.diffs:
        print("", file=out)
        print(diff.rstrip("\n"), file=out)
    print("", file=out)
    render.text(outcome.rendered, out)


def payload(outcome: Outcome) -> dict[str, Any]:
    return {
        "command": outcome.command,
        "manifest": None if outcome.path is None else str(outcome.path),
        "created": outcome.created,
        "changed": outcome.changed,
        "notes": [{"said": note.text, **note.data} for note in outcome.notes],
        "diffs": list(outcome.diffs),
        "render": render.payload(outcome.rendered),
    }


def report(outcome: Outcome, out: TextIO, *, as_json: bool) -> Exit:
    """One command's answer, in whichever form was asked for."""
    if as_json:
        print(json.dumps(payload(outcome), indent=2), file=out)
    else:
        text(outcome, out)
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
