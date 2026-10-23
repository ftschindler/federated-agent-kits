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

**It fetches only what the cache cannot answer.** A source whose pinned commit
is already in the cache is read from there, so a render on a train writes the
same files as a render at a desk. A source this machine has never seen is cloned
at the commit the manifest already names, because the alternative is that a
colleague's fresh clone renders nothing and is told to run a command that moves
the pins their repository committed. No pin moves and no manifest is written:
only `add` and `update` change what a kit contains.

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
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NamedTuple, TextIO

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
    skills,
    sources,
    targets,
)
from federated_agent_kits import (
    renames as renames_,
)
from federated_agent_kits.adapters import Adapter
from federated_agent_kits.adapters.adapter import SEPARATOR
from federated_agent_kits.cache import Privacy
from federated_agent_kits.exits import AkitError, Exit, RefusalError, UsageError
from federated_agent_kits.manifest import Kind, Merged, Scope, Subscription
from federated_agent_kits.paths import located
from federated_agent_kits.record import Explanation, Record, Records, Region, Spot, Written
from federated_agent_kits.reporting import (
    INDENT,
    NOTHING,
    ONE,
    ORDERING,
    PLURAL,
    SCOPE_TITLE,
    SINGULAR,
    Column,
    counted,
    joined,
    scope_title,
    section,
    wrapped,
)
from federated_agent_kits.styling import Style

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


class Ignored(NamedTuple):
    """One repository's ignore block, as this render found and left it.

    `maintained` is the difference between the two kinds of repository a render
    now meets. The project's `.gitignore` is ours to keep correct, so `changed`
    there means the file was rewritten. A repository that merely happens to
    contain a global render root is somebody else's, so `changed` means the
    block is missing or stale and nothing was done about it: `akit doctor`
    reports it, and `akit render --global --gitignore` is what writes it.
    """

    root: Path
    listed: tuple[str, ...]
    changed: bool
    maintained: bool


def _ignore_state(found: Ignored) -> str:
    """The verb for this block, which depends on whether we were allowed to write it."""
    if not found.changed:
        return "already listed"
    return "now lists" if found.maintained else "does not list"


@dataclass(frozen=True)
class Outcome:
    """Everything one render did, before any of it has been printed."""

    manifests: dict[Scope, Path | None]
    harnesses: dict[Scope, tuple[str, ...]]
    entries: tuple[Entry, ...]
    withdrawals: tuple[Withdrawal, ...] = ()
    replaced: tuple[Spot, ...] = ()
    """Spots whose rendered copy somebody had edited, overwritten by this render.

    Reported rather than protected: an explained file is refreshed from its
    source, and the edit is gone whether or not anybody is told. Being told is
    the part this build owes (DESIGN.md section 10).
    """

    pruned: tuple[Path, ...] = ()
    unpruned: tuple[Path, ...] = ()
    """Prune candidates that were listed and then not deleted, because nobody said yes.

    Carried rather than dropped so the report can name them and the exit code
    can say the command did not do what it was asked to. `--prune` that found
    something, printed it and returned success would be indistinguishable from
    `--prune` that found nothing.
    """

    ignored: tuple[Ignored, ...] = ()
    """Each repository whose `.gitignore` was considered, and how it stands."""

    unknown: tuple[str, ...] = ()
    suspended: str | None = None
    """Why nothing was withdrawn, or `None` when withdrawal ran."""

    checking: bool = False
    """Whether this was `--check`, which reports a verdict rather than a diary."""

    withdrawing: bool = False
    """Whether this was a `remove`, which took files away and wrote none."""

    outstanding: int = 0
    """Files a render would write that this pass did not, because it was a withdrawal.

    The manifest being behind its disk is worth knowing and is not `remove`'s to
    fix, so it is counted here and named in the summary with the command that
    does fix it. Zero on every other pass, where what would be written was.
    """

    outstanding_blocks: int = 0

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
        """Whether this render changed nothing at all, which it usually should.

        A render with a problem in it is never quiet, however little it wrote.
        "Nothing changed: the files on disk already match the manifests" is a
        claim about the disk, and a subscription that produced nothing because
        it was refused has left the disk not matching anything.
        """
        changed = any(found.changed and found.maintained for found in self.ignored)
        return not (self.written or self.blocks_written or self.deleted or self.pruned or changed or self.problems)

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
        for found_block in self.ignored:
            if found_block.changed and found_block.maintained:
                found.append(f"the akit block in {found_block.root / ignore.GITIGNORE} is out of date")
        return tuple(found)

    def of_scope(self, scope: Scope) -> tuple[Entry, ...]:
        return tuple(entry for entry in self.entries if entry.subscription.scope is scope)

    @property
    def exit_code(self) -> Exit:
        if self.checking and self.stale:
            return Exit.ERROR
        return Exit.ERROR if self.problems or self.unknown or self.unpruned else Exit.OK


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
    gitignore: bool = False
    """`--gitignore`, which lets a render write the block of a repository it found.

    The project's own is written without being asked, because a render is
    already the thing that maintains it. A repository that happens to contain a
    global render root is somebody else's file in somebody's home directory, so
    it is reported until this says otherwise.
    """

    yes: bool = False
    """`--yes`, which is how something with nobody at a keyboard answers `--prune`.

    Here rather than as an argument of its own because it is a flag of the same
    command and means nothing without `prune`: the two are read together or not
    at all, which is what this value is for.
    """

    @property
    def narrowed(self) -> bool:
        return bool(self.only or self.without)


#: The flags nobody passed: both scopes, every harness the manifests name, and
#: no pruning. A module-level value rather than a default built per call, so
#: "everything" is one object the whole program compares against.
EVERYTHING = Choices()

#: What `--prune` asks before it deletes anything: here is the list, may I.
#: A callable rather than a flag on `Choices` because the answer is a person's
#: and the question has to be put to them in the middle of a render, after the
#: candidates are known and before any of them is gone.
Approval = Callable[[tuple[Path, ...]], bool]


def declined(candidates: tuple[Path, ...]) -> bool:
    """The answer when nobody was asked, which is no.

    The default for every caller that is not the command line: a library call
    that wanted these deleted can say so, and one that did not say anything gets
    the outcome that destroys nothing.
    """
    return False


@dataclass(frozen=True)
class Mode:
    """Whether this pass may fetch, may write, and answers with a verdict.

    Three independent facts about one pass, grouped because only one caller
    ever sets any of them. `render` is the default and `--check` is the other,
    and a third combination would be a new command rather than a new flag.
    """

    offline: bool = True
    """True only for the pass `akit doctor` walks, which may not touch the cache.

    Resolution asks a remote where the cache falls short, so a render and a
    check both bring back the commits their pins already name and neither
    re-fetches a source the cache can answer for. `doctor` reports rather than
    acts, and a clone is an act, so it is the one pass that refuses the network
    and says a source is missing instead (DESIGN.md section 10).
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

    withdrawing: bool = False
    """Whether this pass takes files away and writes none, which is what `remove` is.

    The walk is the ordinary one: every remaining subscription is planned, so
    the record's candidate list is as trustworthy as it is in a full render and
    withdrawal decides what it decides. What changes is everything after the
    decision. No planned spot is filled, no block is refreshed, and the record
    keeps the digests it already had, minus what went.

    It exists because `remove` reads as subtractive and was not. A manifest
    behind its disk would be caught up in passing, so dropping one subscription
    could write more files than it withdrew, into places no previous command had
    touched (DESIGN.md section 10). Counting those and naming the command that
    performs them is this pass's other half.
    """


#: An ordinary render: writing, reporting what it did, and fetching a source
#: the cache has never seen at the commit its pin already names.
RENDERING = Mode(offline=False)

#: `--check`: fetches what it must, writes nothing, answers yes or no.
CHECKING = Mode(offline=False, writing=False, checking=True)

#: What `akit doctor` walks with: the ordinary render, with every act suspended
#: and the network refused. Not `CHECKING`, which judges one repository's
#: committed half; what `doctor` wants is the whole plan a plain `akit render`
#: would carry out, so that "nothing explains this file any more" is the same
#: sentence in both commands. A clone is an act, so this pass declines it and
#: reports a source the cache lacks instead.
INSPECTING = Mode(writing=False)

#: What `akit remove` and `akit harness remove` walk with: deletions carried
#: out, nothing written, and the files the manifest is now behind on counted
#: rather than brought up to date.
WITHDRAWING = Mode(offline=False, withdrawing=True)

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
    """Whether resolution may go near the network, which only `doctor` refuses.

    A cached source holding the commit its pin names is read from the cache by
    every pass, so this decides one thing: what happens to a source this machine
    has never seen. A render and a check clone it at the commit the manifest
    already names. `doctor` reports that it is missing, because a clone is an
    act and `doctor` performs none (DESIGN.md section 10).
    """

    writing: bool = True
    """Whether anything on disk may actually change.

    False is the same walk with every act suspended, which is what `--check`
    is: the copy, the withdrawal, the ignore block and the two record saves all
    ask this before they touch a file, and the counting happens either way.
    """

    gitignore: bool = False
    """Whether a repository that merely contains a render root may have its block written.

    Beside `writing` because it is the same kind of fact: what this pass is
    allowed to do to a file. The project's own block is not asked, because a
    render is the thing that maintains it; this is the one in somebody's home
    directory that `akit render --global --gitignore` names on purpose.
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

    @property
    def claim(self) -> _Claim:
        return _Claim(explanation=self.explanation, source=self.subscription.source, scope=self.scope)


@dataclass(frozen=True)
class _Claim:
    """Who wants a spot filled, which is three facts that always travel together.

    One value rather than three parameters because every caller has all three or
    none: a claim is what a record entry is explained by, and splitting it would
    let a caller name a source without the scope it belongs to.
    """

    explanation: str
    source: str
    scope: Scope


def _spot_wanted(writes: dict[Spot, _Target], spot: Spot, data: bytes, claim: _Claim, harness: str) -> str | None:
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
            explained_by={claim.explanation},
            harnesses={harness},
            sources={claim.source},
            scopes={claim.scope},
        )
        return None
    if standing.digest != digest:
        path, region = spot
        where = path if region is None else f'the "{region}" block in {path}'
        return (
            f"another subscription already wants different bytes at {where}; "
            f"this copy was not written. Give one of them a different name with `as:`"
        )
    standing.explained_by.add(claim.explanation)
    standing.harnesses.add(harness)
    standing.sources.add(claim.source)
    standing.scopes.add(claim.scope)
    return None


def _skill_bytes(wanted: _Wanted, file: Path) -> bytes:
    """What one file of a skill is rendered as, which is its own bytes unless it is the identity.

    Only the `SKILL.md` at the skill's root, and only when the rendered name is
    not the one the source gave it. Everything else - references, scripts, a
    nested `SKILL.md` that is some other skill's - is copied literally, and a
    skill nobody renamed is copied literally throughout (DESIGN.md section 7).
    """
    data = file.read_bytes()
    if file.parent != wanted.part.path or file.name != skills.MANIFEST_FILE:
        return data
    if wanted.name == wanted.part.name:
        return data
    return skills.as_copied(data, name=wanted.name)


def _linked(path: Path, name: str) -> str | None:
    """Why this spot may not be written, when the thing at it is a link.

    `akit` owns the kit directory it writes and every file under it, and owning
    something means being allowed to delete it. A link is not a thing we can own:
    the bytes land wherever it points, the record would claim that destination,
    and a withdrawal would then delete files somewhere nobody subscribed
    anything into. One was a git working tree (DESIGN.md section 6).

    Only the leaf is asked about. A home directory assembled out of a dotfiles
    checkout puts a link above almost every target on the machine, and refusing
    that would refuse the arrangement rather than the mistake.

    Reported as a problem on the subscription rather than raised, so the rest of
    the render still happens and nothing is withdrawn while one subscription is
    unaccounted for (`_suspension`).
    """
    if not path.is_symlink():
        return None
    return (
        f"{path} is a symlink, and a rendered kit is a copy rather than a link we follow. "
        f"Nothing was written there.\n"
        f"  Delete the link and run `akit render`, which writes the kit in its place, or run "
        f"`akit remove {name}` if the link is what you want."
    )


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
        linked = _linked(directory, wanted.name)
        if linked is not None:
            clash = linked
            continue
        spots: list[Spot] = []
        for file in _files_of(wanted.part.path):
            spot = (located(directory / file.relative_to(wanted.part.path)), None)
            problem = _linked(spot[0], wanted.name) or _spot_wanted(
                writes,
                spot,
                _skill_bytes(wanted, file),
                wanted.claim,
                adapter.name,
            )
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
        spot = (located(target), region)
        problem = (None if region is not None else _linked(spot[0], wanted.name)) or _spot_wanted(
            writes,
            spot,
            written,
            wanted.claim,
            adapter.name,
        )
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


@dataclass
class _Referring:
    """One rule that named a renamed kit, kept until the note can be planned.

    Collected during the main pass rather than looked for afterwards, because
    the rule's bytes and the scope it was rendered in are both in hand there and
    neither is cheap to recover once the loop has moved on.
    """

    scope: Scope
    renames: tuple[renames_.Rename, ...]
    subscription: Subscription


def _renamed(merged: Merged) -> tuple[renames_.Rename, ...]:
    """Every kit installed under a name its source did not give it.

    Skills only. A renamed rule is a file of ours whose name nothing else says
    out loud, and agents land with T13 along with the declared `skills:` list
    that makes their references rewritable rather than prose.
    """
    return tuple(
        renames_.Rename(source=entry.source, original=entry.name, rendered=entry.rename)
        for entry in merged.subscriptions
        if entry.kind is Kind.SKILL and entry.rename and not entry.is_wildcard
    )


def _plan_note(walk: _Pass, referring: Sequence[_Referring], writes: dict[Spot, _Target]) -> list[Entry]:
    """The `akit-renames` rule, in every scope where some rule referred to a rename.

    Explained by the subscription that did the renaming, so the note withdraws
    by the ordinary rules the moment that subscription stops renaming, stops
    being subscribed, or stops being referred to (DESIGN.md section 7).

    Every contributor writes identical bytes into one spot, so this goes through
    `_spot_wanted` exactly as a shared skill does and arrives as one placement
    explained by several subscriptions.
    """
    entries: list[Entry] = []
    by_scope: dict[Scope, list[_Referring]] = {}
    for entry in referring:
        by_scope.setdefault(entry.scope, []).append(entry)
    for scope in sorted(by_scope, key=lambda found: found.value):
        here = by_scope[scope]
        data = renames_.note([rename for entry in here for rename in entry.renames])
        placements: list[Placement] = []
        for adapter in walk.chosen[scope]:
            target = adapter.target(Kind.RULE, scope, renames_.RENAMES, walk.anchor(adapter, scope))
            if target is None:
                continue
            region = adapter.region(Kind.RULE, renames_.RENAMES)
            written = (
                rules.as_block(data, name=renames_.RENAMES, ours=True)
                if region is not None
                else rules.as_file(data, name=renames_.RENAMES, keys=adapter.rule_frontmatter, ours=True)
            )
            spot = (located(target), region)
            for entry in here:
                _spot_wanted(
                    writes,
                    spot,
                    written,
                    _Claim(
                        explanation=str(
                            Explanation(kind=Kind.RULE, source=entry.subscription.source, name=renames_.RENAMES)
                        ),
                        source=entry.subscription.source,
                        scope=scope,
                    ),
                    adapter.name,
                )
            placements.append(
                Placement(path=target, harnesses=(adapter.name,), written=0, unchanged=0, region=region, spots=(spot,))
            )
        if placements:
            entries.append(
                Entry(
                    subscription=_note_subscription(scope),
                    name=renames_.RENAMES,
                    found_as=renames_.RENAMES,
                    relative="",
                    placements=_shared(placements),
                )
            )
    return entries


def _note_subscription(scope: Scope) -> Subscription:
    """What the note reports itself as, which is a rule nobody subscribed to.

    It has to be a `Subscription` because that is what an `Entry` carries, and
    naming `akit` as its source is the honest answer: this one really is ours
    rather than any repository's.
    """
    return Subscription(
        kind=Kind.RULE, source="akit", pin=None, name=renames_.RENAMES, rename=None, scope=scope, line=0
    )


def _plan(walk: _Pass, merged: Merged) -> tuple[list[Entry], dict[Spot, _Target]]:
    """Every subscription as the spots it wants filled, with nothing written yet.

    The order is the manifest's, and for rules that is the whole of the promise
    DESIGN.md section 7 makes: the blocks in one shared file come out in the
    order this loop met them.
    """
    writes: dict[Spot, _Target] = {}
    entries: list[Entry] = []
    renamed = _renamed(merged)
    referring: list[_Referring] = []
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
        for part in parts:
            entries.append(_plan_part(walk, subscription, part, writes))
            if subscription.kind is not Kind.RULE or not renamed:
                continue
            found = renames_.referenced(renamed, subscription.source, part.path.read_bytes())
            if found:
                referring.append(_Referring(scope=subscription.scope, renames=found, subscription=subscription))
    entries.extend(_plan_note(walk, referring, writes))
    return entries, writes


def _replaced(before: Mapping[Scope, Record], writes: Mapping[Spot, _Target]) -> tuple[Spot, ...]:
    """Every spot about to be overwritten where somebody had edited our copy.

    A file something still explains is refreshed rather than protected: the
    source says what it holds, so a render writes the source's bytes over
    whatever is there, and the withdrawal table's middle row is about deletion
    and never about this (DESIGN.md section 10). Editing a rendered file you
    still subscribe to therefore loses the edit, which is what "nothing you
    wrote by hand lives in one" has always meant.

    What that leaves owing is the report. The three hashes needed to tell the
    cases apart are all in hand at this moment and nowhere else: what we wrote
    last time, what is there now, and what is about to be. A spot counts here
    only when all three disagree in the one way that means somebody typed in it:
    the disk has drifted from what we recorded, and it is not already what this
    render is about to put there. A file whose disk and record agree is an
    ordinary update from a changed source, and a file that is already correct is
    not being written at all.

    A spot whose file has gone is not a replacement either. That is a restore,
    which is the case DESIGN.md section 2 means by calling a rendered file
    disposable, and it is the good outcome rather than a loss.
    """
    found: list[Spot] = []
    for record_ in before.values():
        for entry in record_.written:
            planned = writes.get(entry.spot)
            if planned is None:
                continue
            standing = entry.current()
            if standing is None or standing in (entry.digest, planned.digest):
                continue
            found.append(entry.spot)
    return tuple(sorted(set(found), key=lambda spot: (str(spot[0]), spot[1] or "")))


def _perform(
    entries: list[Entry],
    writes: dict[Spot, _Target],
    removals: Iterable[Region],
    *,
    writing: bool = True,
    withdrawing: bool = False,
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
    changed, and that is the number this counts either way. `withdrawing` is
    the same suspension for the same reason, on a pass that is writing: a
    `remove` deletes what it was asked to and counts the rest rather than
    performing it.
    """
    done: dict[Spot, bool] = {}
    for (target, region), planned in writes.items():
        if region is not None:
            continue
        done[(target, region)] = record.digest_of(target) != planned.digest
        if done[(target, region)] and writing and not withdrawing:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(planned.data)
    done.update(_weave(writes, removals, writing=writing, withdrawing=withdrawing))
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


def _weave(
    writes: dict[Spot, _Target], removals: Iterable[Region], *, writing: bool = True, withdrawing: bool = False
) -> dict[Spot, bool]:
    """Rewrite every file we share, once each, and say which blocks changed.

    A host file is somebody's prose and may not exist yet. It is created when a
    rule wants to be in it and never deleted when the last one leaves, because
    an entry for a block may take its own text out and nothing else
    (DESIGN.md section 6).

    A block counts as written when its text changed *or* when it moved. Order is
    the thing rules have that skills do not, so swapping two rules in a manifest
    rewrites this file while every block in it keeps its bytes, and counting
    bytes alone would report that render as having changed nothing.

    **A withdrawal takes its blocks out and refreshes none.** The rewrite is
    given no planned blocks at all, so every slot it is not removing is copied
    through exactly as it stands: a `remove` cannot update the rule beside the
    one it dropped. What those blocks *would* have become is still counted, by
    the same comparison every other pass makes.
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
        after = rules.weave(before, [] if withdrawing else blocks, remove=taken.get(path, set()))
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
    stops = {located(Path(entry)) for entry in boundaries}
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


def _prunable(owned: dict[Path, set[str]], explained: set[Path]) -> tuple[Path, ...]:
    """What nothing explains in a directory we own, one kit at a time.

    The one deletion this tool cannot prove is safe, which is why it is a flag.
    A kit rendered before the record was lost is indistinguishable from a kit
    somebody wrote by hand in the same directory, so this takes both and the
    other three commands take neither.

    Finding them and deleting them are separate because of that: a list that can
    be printed before anything happens is what lets the person who wrote one of
    these by hand say no (DESIGN.md section 10).

    **A symlink is never one of these**, and that follows from a rule rather
    than from caution: this tool never creates one (DESIGN.md section 9), so a
    link in a directory we own was made by a person and cannot be something we
    rendered. Following one would delete the contents of whatever it points at,
    which is the same incident `_linked` exists for, arriving through the other
    door.
    """
    found: list[Path] = []
    for base, written in owned.items():
        for relative in sorted(written):
            directory = base.joinpath(*relative.split(SEPARATOR))
            if not directory.is_dir():
                continue
            found.extend(
                child
                for child in sorted(directory.iterdir())
                if not child.is_symlink() and not any(path == child or path.is_relative_to(child) for path in explained)
            )
    return tuple(found)


def _remove(path: Path) -> None:
    """One file, or one kit directory and everything in it.

    A link is unlinked rather than descended into, here as well as in
    `_prunable`, because `is_dir` follows one and a directory walk through it
    would delete somebody else's files and then fail to `rmdir` the link. The
    caller already declines to offer a link; this is the same rule written
    where the deletion actually happens.
    """
    if path.is_dir() and not path.is_symlink():
        for child in sorted(path.rglob("*"), key=lambda entry: len(entry.parts), reverse=True):
            child.rmdir() if child.is_dir() and not child.is_symlink() else child.unlink()
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


def ignore_block(
    walk: _Pass,
    owned: dict[Path, set[str]],
    explained: Iterable[Path],
    scopes: Sequence[Scope],
    *,
    keeps_a_record: bool,
) -> tuple[Ignored, ...]:
    """Maintain the ignore block of every repository this render wrote into.

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

    **A render root is not always in the repository the command was run in.**
    The project scope's is, by construction. The global scope's is a directory
    under the home directory, and a home directory holding a git repository is
    ordinary rather than exotic: `~/.agents` kept as a repository to share or
    back up is the shape this tool exists to replace, so it is the shape a
    person arrives with. Asking each rendered directory which worktree contains
    it finds those, and finds nothing new for the project scope, where the
    answer is the anchor it already had.

    **What the global scope finds is reported and not written**, unless
    `--gitignore` asked for it. The project's `.gitignore` is a file the render
    is already in the business of maintaining; a repository in somebody's home
    directory that they never pointed this tool at is not. So the block is
    worked out either way, `akit doctor` says it is missing, and writing it
    stays a thing somebody names.

    **What a machineless harness reads is subtracted**, so this block and the
    committed set are each other's inverse and nobody keeps two lists in step by
    hand.
    """
    wanted = list(explained)
    found: dict[Path, set[str]] = {}
    maintained: set[Path] = set()
    root = manifest.worktree_root(walk.start)
    if root is not None and Scope.PROJECT in scopes:
        committed = _committed(walk.chosen.get(Scope.PROJECT, ()), Scope.PROJECT)
        listed = {
            f"{directory.relative_to(root).as_posix()}/"
            for base, written in owned.items()
            for relative in written
            if relative not in committed
            for directory in (base.joinpath(*relative.split(SEPARATOR)),)
            if directory.is_relative_to(root) and any(path.is_relative_to(directory) for path in wanted)
        }
        if keeps_a_record:
            listed.add(f"{record.DIRECTORY}/")
        found[root] = listed
        maintained.add(root)
    for directory in _global_directories(walk, scopes):
        above = manifest.worktree_root(directory)
        if above is None or above in maintained:
            continue
        if any(path.is_relative_to(directory) for path in wanted):
            found.setdefault(above, set()).add(f"{directory.relative_to(above).as_posix()}/")
    return tuple(
        Ignored(
            root=where,
            listed=tuple(sorted(listed)),
            changed=ignore.maintain(where, listed, writing=walk.writing and allowed),
            maintained=allowed,
        )
        for where, listed in sorted(found.items())
        for allowed in (where in maintained or walk.gitignore,)
    )


def _global_directories(walk: _Pass, scopes: Sequence[Scope]) -> list[Path]:
    """Every directory the global scope renders into, as paths rather than per root.

    The project half of the block is anchored at the repository the command was
    run in, which is one place and known. This half has as many places as there
    are harnesses, each under the home directory, and which repository contains
    one is a question about this machine rather than about this render.
    """
    if Scope.USER not in scopes:
        return []
    return [
        base.joinpath(*relative.split(SEPARATOR))
        for base, written in _directories(walk.chosen.get(Scope.USER, ()), walk, (Scope.USER,)).items()
        for relative in sorted(written)
    ]


def escaping(merged: Merged, root: Path | None) -> tuple[str, ...]:
    """Every path a committed manifest names that leaves its own repository.

    `.` and `./kits` mean the same thing in every clone. `../my-kits` means
    something only on the machine it was written on, and committing one breaks
    the repository for everybody else (DESIGN.md section 6). Your own manifest
    is never asked, because it is not committed and its paths are supposed to
    mean something only here.

    **Only a manifest git actually tracks is asked.** The rule is about what a
    colleague gets when they clone, so a `.akit.yaml` nobody else has cannot
    break anybody's clone. That is also what makes writing a kit work: you
    subscribe to `~/kits/the-new-thing` in a scratch repository, render, and
    nothing objects until you try to commit the file saying so.

    The answer rather than the refusal, because two commands want it and only
    one of them may raise: `render` refuses, and `doctor` reports.
    """
    if root is None or merged.project is None or merged.project.path is None:
        return ()
    if not targets.tracked(merged.project.path, root=root):
        return ()
    return tuple(
        sorted(
            {
                subscription.source
                for subscription in merged.subscriptions
                if subscription.scope is Scope.PROJECT
                and sources.escapes(sources.parse(subscription.source), anchor=root)
            }
        )
    )


def _escaping(merged: Merged, root: Path | None) -> None:
    """Refuse a committed manifest that names a path outside its own repository.

    A refusal rather than a warning, so the one hook this project ships carries
    one command. `akit doctor` reports the same thing without a second check.
    """
    found = escaping(merged, root)
    if not found:
        return
    committed = merged.project.path if merged.project is not None else None
    listed = "\n".join(f"{INDENT * 2}{source}" for source in found)
    raise RefusalError(
        f"{committed} is committed, and names a path outside {root}:\n"
        f"{listed}\n"
        f"{INDENT}Nothing was written. Those paths exist on this machine and on no other, so a colleague "
        f"cloning this project gets a render that fails.\n"
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
            path for path in sorted(directory.rglob("*")) if path.is_file() and (located(path), None) not in writes
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


@dataclass(frozen=True)
class Plan:
    """One render worked out, with nothing done about it.

    `render` is the caller that goes on to act. `akit doctor` is the one that
    does not: almost everything it reports is a disagreement between the record,
    the disk and what a render would do next, and working that out a second way
    would be a second definition of "explained" to keep in step with this one
    (DESIGN.md section 10).
    """

    merged: Merged
    walk: _Pass
    files: Mapping[Scope, Path]
    """Where each record lives, which is also which scopes are in play."""

    before: Mapping[Scope, Record]
    chosen: Mapping[Scope, tuple[Adapter, ...]]
    unknown: tuple[str, ...]
    entries: tuple[Entry, ...]
    writes: dict[Spot, _Target]
    owned: dict[Path, set[str]]
    """The directories these harnesses own, per scope root, which is where an orphan can be."""

    @property
    def spots(self) -> frozenset[Spot]:
        """Everything this render would fill, which is what still explains a file."""
        return frozenset(self.writes)

    @property
    def problems(self) -> tuple[Entry, ...]:
        return tuple(entry for entry in self.entries if entry.problem is not None)


def _roots(start: Path, places: Directories, chosen: Mapping[Scope, tuple[Adapter, ...]]) -> dict[Scope, set[Path]]:
    """Where each record's entries are allowed to be, which is where its render writes.

    Your record covers your home directory, and a project's covers the project
    (DESIGN.md section 6). The second is the anchor rather than the git root
    because an adapter answers question 6 for itself, and one that anchors
    somewhere other than the worktree writes there legitimately.

    An entry outside all of them is not a file this scope could have produced,
    so it is not one this scope may delete. That is a guard against two faults
    at once: a path recorded through a symlink, and a suite that wrote into a
    real record while pointed at a temporary directory.
    """
    found: dict[Scope, set[Path]] = {}
    for scope in chosen:
        if scope is Scope.USER:
            found[scope] = {located(places.home)}
            continue
        anchors = {adapter.anchor(start) or start for adapter in chosen[scope]}
        found[scope] = {located(path) for path in {manifest.worktree_root(start) or start, *anchors}}
    return found


def plan(start: Path, places: Directories, choices: Choices = EVERYTHING, mode: Mode = RENDERING) -> Plan:
    """Work out what a render would do, without doing any of it."""
    _check_names(choices.only, "--harness")
    _check_names(choices.without, "--no-harness")
    merged = manifest.load(start, user_path=places.user_manifest)
    files = record.locations(start, state_root=places.state)
    chosen: dict[Scope, tuple[Adapter, ...]] = {}
    unknown: list[str] = []
    for scope in choices.scopes:
        expand = adapters.named if mode.checking else adapters.expand
        picked, missing = expand(merged.harnesses(scope), places.home)
        chosen[scope] = _narrow(
            adapters.machineless(picked) if mode.checking else picked, choices.only, choices.without
        )
        unknown.extend(name for name in missing if name not in unknown)
    roots = _roots(start, places, chosen)
    before = {scope: record.load(path, roots=roots.get(scope, ())) for scope, path in files.items()}
    walk = _Pass(
        start=start,
        home=places.home,
        cache_root=places.cache,
        before=Records(by_scope=before),
        chosen=chosen,
        offline=mode.offline,
        writing=mode.writing,
        gitignore=choices.gitignore,
    )
    wanted = Merged(
        subscriptions=tuple(entry for entry in merged.subscriptions if entry.scope in set(choices.scopes)),
        user=merged.user,
        project=merged.project,
    )
    entries, writes = _plan(walk, wanted)
    return Plan(
        merged=merged,
        walk=walk,
        files=files,
        before=before,
        chosen=chosen,
        unknown=tuple(unknown),
        entries=tuple(entries),
        writes=writes,
        owned={
            base: written
            for scope in choices.scopes
            for base, written in _directories(chosen[scope], walk, (scope,)).items()
        },
    )


def render(
    start: Path,
    places: Directories,
    choices: Choices = EVERYTHING,
    mode: Mode = RENDERING,
    approve: Approval = declined,
) -> Outcome:
    """Make the files on disk match the manifests, and say everything that happened.

    `mode` is `RENDERING` for every caller but one. `CHECKING` is the same walk
    that fetches what the cache lacks, writes nothing, and judges only what this
    repository commits.

    `approve` is asked once, and only when `--prune` found something. It is the
    only question this package puts to a person, which is why it arrives as a
    parameter rather than as a call to `input` somewhere in here: a render is
    run from hooks and from tests, and neither has anybody to answer.
    """
    writing, checking, withdrawing = mode.writing, mode.checking, mode.withdrawing
    prepared = plan(start, places, choices, mode)
    merged, walk, writes = prepared.merged, prepared.walk, prepared.writes
    before, files, chosen = dict(prepared.before), prepared.files, prepared.chosen
    _escaping(merged, manifest.worktree_root(start))
    known = privacy.learned(privacy.load(places.state), walk.resolutions)
    if writing:
        privacy.save(known, places.state)
    _refuse_leaks(walk, merged, writes, known)
    suspended = _suspension(prepared.entries, choices, checking=checking)
    owned = prepared.owned
    withdrawals: list[Withdrawal] = []
    removals: list[Region] = []
    kept: dict[Scope, list[Written]] = {scope: list(found.written) for scope, found in before.items()}
    if suspended is None:
        withdrawals, kept, removals = _withdraw(
            before, writes, choices.scopes, _directories(adapters.ADAPTERS, walk, choices.scopes)
        )
    replaced = _replaced(before, writes) if not withdrawing else ()
    entries, done = _perform(list(prepared.entries), writes, removals, writing=writing, withdrawing=withdrawing)
    standing: set[Path] = set()
    keeps_a_record = False
    for scope, path in files.items():
        after = (
            _record_unchanged(before[scope], writes, kept.get(scope, ()))
            if withdrawing
            else _record_after(before[scope], writes, scope, kept.get(scope, ()))
        )
        if writing:
            record.save(after, path)
        if scope is Scope.PROJECT:
            keeps_a_record = bool(after.written)
        standing |= set(after.paths)
    candidates = _prunable(owned, standing) if choices.prune and suspended is None and writing else ()
    agreed = bool(candidates) and approve(candidates)
    pruned = tuple(candidates) if agreed else ()
    for path in pruned:
        _remove(path)
    files_done = {spot: changed for spot, changed in done.items() if spot[1] is None}
    blocks_done = {spot: changed for spot, changed in done.items() if spot[1] is not None}
    return Outcome(
        checking=checking,
        withdrawing=withdrawing,
        manifests={
            Scope.USER: merged.user.path if merged.user else None,
            Scope.PROJECT: merged.project.path if merged.project else None,
        },
        harnesses={scope: tuple(adapter.name for adapter in chosen.get(scope, ())) for scope in choices.scopes},
        entries=tuple(entries),
        written=0 if withdrawing else sum(1 for changed in files_done.values() if changed),
        unchanged=sum(1 for changed in files_done.values() if not changed),
        blocks_written=0 if withdrawing else sum(1 for changed in blocks_done.values() if changed),
        blocks_unchanged=sum(1 for changed in blocks_done.values() if not changed),
        outstanding=sum(1 for changed in files_done.values() if changed) if withdrawing else 0,
        outstanding_blocks=sum(1 for changed in blocks_done.values() if changed) if withdrawing else 0,
        withdrawals=tuple(withdrawals),
        replaced=replaced,
        pruned=pruned,
        unpruned=() if agreed else tuple(candidates),
        ignored=ignore_block(walk, owned, standing, choices.scopes, keeps_a_record=keeps_a_record),
        unexplained=_unexplained(walk, writes, manifest.worktree_root(start)) if checking else (),
        unknown=prepared.unknown,
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
        return "a subscription could not be rendered, so the list of what is still explained is incomplete"
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


def _record_unchanged(before: Record, writes: dict[Spot, _Target], kept: Iterable[Written]) -> Record:
    """One root's record after a withdrawal: what it said, minus what went.

    The record is a claim about bytes on disk, so a pass that wrote none may not
    adopt the digests it planned. Doing so would make every file the manifest is
    behind on look hand-edited to the next render, and a hand-edited file is
    kept and reported rather than refreshed: one `remove` would freeze the rest
    of the setup in place.

    What stays is therefore the entries this withdrawal did not take, in two
    groups: the spots something still explains, which are untouched on disk and
    keep the digest they had, and `kept`, which withdrawal has already decided
    about.
    """
    entries = {entry.spot: entry for entry in before.written if entry.spot in writes}
    for entry in kept:
        entries.setdefault(entry.spot, entry)
    return Record(path=before.path, written=tuple(entries.values()))


def _placed(place: Placement) -> str:
    """What one placement did, said the way the summary says it."""
    if place.region is not None:
        did = "wrote" if place.written else "already up to date:"
        return f'{did} the "{place.region}" block in {place.path}'
    did = (
        f"wrote {counted(place.written, 'file')}"
        if place.written
        else f"already up to date, {counted(place.unchanged, 'file')}"
    )
    return f"{did} in {place.path}"


def _print_entry(entry: Entry, out: TextIO, style: Style) -> None:
    """One kit, and under it the column of harnesses that now hold it.

    The same two levels `list` prints, so a kit line reads the same whether you
    asked what you subscribe to or what a render did about it. An entry that
    put nothing on disk has no harness to mark, and says why instead: a mark is
    a claim about a file, and there is no file to claim.
    """
    subscription = entry.subscription
    named = f' as "{style.kit(entry.name)}"' if subscription.rename else ""
    print(
        f"- {SINGULAR[subscription.kind]} {style.kit(entry.found_as)}{named}, from {style.source(subscription.source)}",
        file=out,
    )
    if entry.waiting is not None:
        print(f"{INDENT}not rendered: {entry.waiting}", file=out)
        return
    if entry.problem is not None:
        wrapped(f"problem: {entry.problem.splitlines()[0]}", entry.problem.splitlines()[1:], out)
    if not entry.placements and entry.problem is None:
        print(f"{INDENT}no harness in this scope takes {PLURAL[subscription.kind]}", file=out)
    column = Column.of((joined(place.harnesses) for place in entry.placements), style, indent=INDENT)
    for place in entry.placements:
        column.marked(joined(place.harnesses), style.place(_placed(place)), out, present=True)


def _print_unknown(outcome: Outcome, out: TextIO, style: Style) -> None:
    """Harness names a manifest asked for that this build has no adapter for."""
    if not outcome.unknown:
        return
    section("Unknown harnesses", out, style)
    for name in outcome.unknown:
        print(f'- a manifest names "{style.harness(name)}", and no adapter answers to it', file=out)
        print(f"{INDENT}fix: run `akit list` to see the harnesses this build knows", file=out)
    print("", file=out)


def _print_replacements(outcome: Outcome, out: TextIO, style: Style) -> None:
    """Name every rendered copy whose hand edit this render wrote over.

    Printed before the withdrawals and the summary, because it is the one thing
    in the report that describes something lost rather than something arranged.
    """
    if not outcome.replaced:
        return
    section("Replaced", out, style)
    print("The source decides what a rendered copy holds, so these went back to holding it.", file=out)
    for path, region in outcome.replaced:
        where = str(path) if region is None else f'the "{region}" block in {path}'
        print(f"- {style.place(where)} had been edited since it was rendered", file=out)
    print(f"{INDENT}fix: to keep a change, make it in the source, or subscribe to a kit of your own", file=out)
    print("", file=out)


def _print_withdrawals(outcome: Outcome, out: TextIO, style: Style) -> None:
    """What this render took away, which is a different question from what it wrote.

    No mark column here, and that is deliberate. A mark says whether a thing is
    on disk, and a withdrawal that worked leaves nothing on disk: marking one
    would paint the successful case red and the failed one green.
    """
    section("Withdrawn", out, style)
    if outcome.suspended is not None:
        print(f"nothing: {outcome.suspended}", file=out)
    elif not outcome.withdrawals:
        print("nothing: every rendered file is still explained", file=out)
    for entry in outcome.withdrawals:
        if entry.action == DELETED:
            print(f"- deleted {style.place(entry.described)}, which nothing in scope explains any more", file=out)
        elif entry.action == GONE:
            print(f"- {style.place(entry.described)} was already gone, and is no longer recorded", file=out)
        else:
            print(f"- left {style.place(entry.described)} alone: it has been edited since it was rendered", file=out)
            print(f"{INDENT}fix: run `akit doctor`, which says what to do with it", file=out)
    print("", file=out)


def _print_pruned(outcome: Outcome, out: TextIO, style: Style) -> None:
    """Files under a rendered directory that no record ever claimed.

    Its own section rather than a tail on the withdrawals, because a withdrawal
    is something this tool put there and took back, and this is something it
    found in a place it owns and did not recognise.
    """
    if not outcome.pruned:
        return
    section("Pruned", out, style)
    for path in outcome.pruned:
        print(f"- {style.place(str(path))}, which nothing explains and no record claims", file=out)
    print("", file=out)


def _print_unpruned(outcome: Outcome, out: TextIO, style: Style) -> None:
    """What `--prune` found and did not delete, because the answer was no.

    Named rather than counted. Each of these is either a render whose record is
    gone or something somebody wrote by hand, and the person reading is the only
    one who can tell those apart; a count tells them nothing they can act on.
    """
    if not outcome.unpruned:
        return
    section("Not pruned", out, style)
    print("Nothing was deleted. These are the ones `--prune` was going to take:", file=out)
    for path in outcome.unpruned:
        print(f"- {style.place(str(path))}", file=out)
    print(f"{INDENT}fix: run `akit render --prune --yes` to delete them, if none of them is yours", file=out)
    print("", file=out)


def _print_ignored(outcome: Outcome, out: TextIO, style: Style) -> None:
    if not outcome.ignored:
        return
    section("Ignore rules", out, style)
    for found in outcome.ignored:
        state = _ignore_state(found)
        where = style.place(str(found.root / ignore.GITIGNORE))
        print(f"- {where} {state} {joined(found.listed) or 'nothing of ours'}", file=out)
    print("", file=out)


def _shared_files(outcome: Outcome) -> tuple[Path, ...]:
    """The files somebody else owns that this render put blocks into, in the order met.

    Named rather than counted, because "left 4 rules there alone" leaves the
    reader to work out what "there" was, and the whole point of a block is that
    it sits in a file they also write in.
    """
    found: dict[Path, None] = {}
    for entry in outcome.entries:
        for place in entry.placements:
            if place.region is not None:
                found.setdefault(place.path, None)
    return tuple(found)


def _blocks(outcome: Outcome) -> str:
    """What this render did inside files somebody else owns, and which files those are."""
    if not (outcome.blocks_written or outcome.blocks_unchanged):
        return ""
    where = joined([str(path) for path in _shared_files(outcome)])
    named = f" in {where}" if where else ""
    return (
        f" Wrote {counted(outcome.blocks_written, 'rule')}{named}, which is a file somebody else "
        f"owns, and left {counted(outcome.blocks_unchanged, 'rule')} there alone."
        if outcome.blocks_written
        else f" Left {counted(outcome.blocks_unchanged, 'rule')}{named} alone, in a file somebody else owns."
    )


def _outstanding(outcome: Outcome) -> str:
    """What a withdrawal left for `akit render`, counted rather than carried out.

    The count is the point. "Run `akit render`" on its own asks somebody to
    decide blind, and the thing they would be deciding about is how much of
    their setup the manifest is behind on - which is exactly what this pass
    measured on its way past.
    """
    behind = []
    if outcome.outstanding:
        behind.append(counted(outcome.outstanding, "file"))
    if outcome.outstanding_blocks:
        behind.append(counted(outcome.outstanding_blocks, "rule"))
    if not behind:
        return "The rest of this manifest is already rendered."
    verb = "is" if len(behind) == ONE else "are"
    return f"{joined(behind).capitalize()} elsewhere in this manifest {verb} out of date, which `akit render` writes."


def _withdrawal_summary(outcome: Outcome) -> str:
    """What a `remove` did, which is deletions and a count of what it did not do.

    Files and blocks are counted apart for the reason they are counted apart
    everywhere else: a rule withdrawn from `AGENTS.md` deleted no file, and
    saying it did would have somebody looking for a file that is still there
    with everything else in it intact.
    """
    gone = [entry for entry in outcome.deleted if entry.region is None]
    blocks = [entry for entry in outcome.deleted if entry.region is not None]
    took = [counted(len(gone), "file")] if gone or not blocks else []
    took += [counted(len(blocks), "rule")] if blocks else []
    return f"Deleted {joined(took)} and wrote nothing. {_outstanding(outcome)}"


def _summary(outcome: Outcome) -> str:
    if outcome.withdrawing:
        return _withdrawal_summary(outcome)
    if outcome.quiet:
        return "Nothing changed: the files on disk already match the manifests."
    return (
        f"Wrote {counted(outcome.written, 'file')}, left {counted(outcome.unchanged, 'file')} alone as "
        f"already correct, and deleted {counted(len(outcome.deleted), 'file')}.{_blocks(outcome)}"
    )


def verdict(outcome: Outcome, out: TextIO) -> None:
    """What `--check` prints, which is an answer rather than a list of what it did.

    A check is read by a person watching a hook refuse their commit, and by the
    CI log nobody reads until it is red. Both want the verdict first and the
    detail under it.
    """
    harnesses = joined(outcome.harnesses.get(Scope.PROJECT, ()))
    if not harnesses:
        offered = joined([adapter.name for adapter in adapters.machineless(adapters.ADAPTERS)])
        print("Nothing to check: this project names no harness whose renders it commits.", file=out)
        print(f"{INDENT}`akit harness add <name>` with one of {offered} is what commits rendered kits.", file=out)
        return
    if not outcome.stale:
        print(f"Up to date: what this project commits for {harnesses} matches its manifest.", file=out)
        return
    print(f"Out of date: what this project commits for {harnesses} does not match its manifest.", file=out)
    for reason in outcome.stale:
        print(f"{INDENT}{reason}", file=out)
    print(f"{INDENT}fix: run `akit render` and commit what it writes.", file=out)


def text(outcome: Outcome, out: TextIO, *, style: Style | None = None, naming: bool = True) -> None:
    """The report a person reads: what went where, what went away, and what did not.

    A scope with nothing subscribed says that and stops. Which harnesses it
    would have rendered for is true, and answers a question nobody is asking
    about a scope with nothing to render: the next thing to do is subscribe to
    something, not to reconsider the harness list.

    `naming` is false where the report above this one already named the file.
    `akit add` printed one heading about the manifest it edited and then a
    second naming the same path, which reads as two reports about two things
    until you count the characters. The second heading stays, because what it
    is about genuinely differs; the path does not.

    **A withdrawal prints neither.** It wrote nothing, so a list of every kit
    and where it landed would be a list of what some other command did, and the
    one thing it did do - take files away - would be below it.
    """
    shown = style or Style.plain()
    if outcome.withdrawing:
        _print_withdrawals(outcome, out, shown)
        _print_ignored(outcome, out, shown)
        section("Summary", out, shown)
        print(_summary(outcome), file=out)
        return
    for scope in ORDERING:
        if scope not in outcome.harnesses:
            continue
        section(scope_title(scope, outcome.manifests[scope]) if naming else SCOPE_TITLE[scope], out, shown)
        entries = outcome.of_scope(scope)
        if not entries:
            print(NOTHING, file=out)
            print("", file=out)
            continue
        print(f"rendering for {joined(outcome.harnesses[scope]) or 'no harness in scope'}", file=out)
        for entry in entries:
            _print_entry(entry, out, shown)
        print("", file=out)
    _print_unknown(outcome, out, shown)
    _print_replacements(outcome, out, shown)
    _print_withdrawals(outcome, out, shown)
    _print_pruned(outcome, out, shown)
    _print_unpruned(outcome, out, shown)
    _print_ignored(outcome, out, shown)
    section("Summary", out, shown)
    print(_summary(outcome), file=out)


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
        "unpruned": [str(path) for path in outcome.unpruned],
        "replaced": [{"path": str(path), "region": region} for path, region in outcome.replaced],
        "ignored": [
            {
                "repository": str(found.root),
                "lists": list(found.listed),
                "changed": found.changed,
                "maintained": found.maintained,
            }
            for found in outcome.ignored
        ],
        "unexplained": [str(path) for path in outcome.unexplained],
        "withdrawal_suspended": outcome.suspended,
        "withdrawing": outcome.withdrawing,
        "outstanding": {"files": outcome.outstanding, "rules": outcome.outstanding_blocks},
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


#: What counts as yes at the prompt. `y` and nothing else, in either case: a
#: question whose destructive answer is the one you get by pressing return is
#: not a question.
AGREEMENT = frozenset({"y", "yes"})


def asking(out: TextIO, style: Style, *, yes: bool, interactive: bool, ask: Callable[[str], str] = input) -> Approval:
    """How `--prune` puts its question, which depends on who is there to answer.

    Three audiences and one answer each. A person at a terminal reads what is
    about to go and types it. A script passed `--yes`, which is what meaning it
    looks like, and is not stopped. Anything else - a hook, a pipe, a CI job -
    is nobody, and nobody says no: a prompt that cannot be answered is a hang,
    and a silent yes there is how the four hand-written skills in issue #30
    would have gone.

    Only the question prints the list, because only the question needs it
    first. The other two get the same paths from the report, under `Pruned` or
    under `Not pruned`, which is where every other thing this command did or
    declined to do is already written down.
    """

    def approve(candidates: tuple[Path, ...]) -> bool:
        if yes:
            return True
        if not interactive:
            return False
        section("About to be pruned", out, style)
        print("Nothing explains these, and no record claims them. `--prune` takes both", file=out)
        print("a render whose record was lost and a kit somebody wrote here by hand:", file=out)
        for path in candidates:
            print(f"- {style.place(str(path))}", file=out)
        print("", file=out)
        answer = ask(f"Delete {counted(len(candidates), 'thing')}? [y/N] ")
        print("", file=out)
        return answer.strip().lower() in AGREEMENT

    return approve


def run(
    out: TextIO,
    *,
    as_json: bool,
    choices: Choices = EVERYTHING,
    start: Path | None = None,
    home: Path | None = None,
) -> Exit:
    """`akit render`. Non-zero when a subscription could not be rendered.

    Whether anybody can be asked about `--prune` is worked out here rather than
    passed in: a terminal on the other end of stdin is a fact about this process,
    and `--json` means a program is reading, which is nobody to ask.
    """
    places = Directories(home=home or Path.home())
    style = Style.of(out)
    outcome = render(
        start or Path.cwd(),
        places,
        choices,
        approve=asking(out, style, yes=choices.yes, interactive=sys.stdin.isatty() and not as_json),
    )
    if as_json:
        print(json.dumps(payload(outcome), indent=2), file=out)
    else:
        text(outcome, out, style=style)
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
    "AGREEMENT",
    "CHECKING",
    "COMMITTED",
    "INSPECTING",
    "RENDERING",
    "Approval",
    "Choices",
    "Directories",
    "Entry",
    "Ignored",
    "Mode",
    "Outcome",
    "Placement",
    "Plan",
    "Withdrawal",
    "asking",
    "check",
    "declined",
    "escaping",
    "ignore_block",
    "payload",
    "plan",
    "render",
    "run",
    "scopes_from",
    "text",
    "verdict",
]
