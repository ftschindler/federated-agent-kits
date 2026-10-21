"""`akit doctor`: what is wrong with this setup, and which command fixes each one.

Reads everything and changes nothing, which is what makes it the safe thing to
run when you do not know what is going on (DESIGN.md section 10). Three
properties shape the code below and all three are that sentence taken seriously.

**Every check is a function returning findings**, so a check is testable as
itself and a new one is a line in `CHECKS` rather than a branch in a long
procedure. A finding names what is wrong and the command that fixes it; a check
with no fix to offer is a complaint, and `tests/test_doctor.py` refuses one.

**It reports on the setup it is standing in, which is two records and not every
record on the disk.** Yours, and the one in the repository you ran it from
(DESIGN.md section 6). Run outside a repository it sees your home directory and
says so. A check that went looking for every repository ever rendered into would
have to guess where they are, and would report each one's files as orphans from
wherever it happened to be run.

**It goes near the network in the one case `render` does.** A repository whose
manifest names a harness with no machine commits what it renders, so it has a
staleness check and a leak check to run and both are `render --check` by another
name. Everywhere else this works from the manifests, the cache and the records,
so `akit doctor` on a train is the same command as yesterday's.

Most of what it reports is a disagreement between the record, the disk and what
a render would do next, so it asks `render.plan` rather than working that out a
second way. A second definition of "explained" is the thing that would drift.

One bullet of DESIGN.md section 10 is missing on purpose: an agent naming a
skill or an MCP server you have not subscribed to has nothing to report until
agents render, so it lands with T13.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from federated_agent_kits import adapters, cache, ignore, manifest, record, render
from federated_agent_kits.adapters import Adapter
from federated_agent_kits.adapters.adapter import SEPARATOR
from federated_agent_kits.exits import AkitError, Exit, RefusalError
from federated_agent_kits.manifest import Merged, Scope
from federated_agent_kits.reporting import INDENT, SCOPE_NAMED, group, joined, section, wrapped
from federated_agent_kits.styling import Style

#: The heading each check's findings group under, by the stable id the finding
#: carries. Forty-four findings printed flat is the case this command hurts
#: most in, and the fix is grouping rather than colour: a kind read once is a
#: kind skipped forty-three times.
#:
#: `check` is a slug a script matches on, so it is deliberately not a heading.
#: This is the one place the two are tied together, which also means a new
#: check cannot reach the report without being given a name a person reads.
TITLE: dict[str, str] = {
    "unreadable": "Files this build cannot read",
    "collision": "Two kits wanting one name",
    "subscription": "Subscriptions that could not be rendered",
    "unknown-harness": "Harness names no adapter answers to",
    "harness-left-out": "Harnesses installed here and not rendered for",
    "harness-not-here": "Harnesses rendered for and not installed here",
    "edited": "Rendered copies edited by hand",
    "unexplained": "Rendered copies nothing explains any more",
    "orphan": "Renders no record knows about",
    "authored-render": "Content of your own where renders go",
    "foreign-entry": "Record entries naming somewhere that record does not cover",
    "abandoned-record": "Records of a project with no manifest",
    "dangling-pointer": "Harness configuration pointing nowhere",
    "escaping-path": "Committed manifests naming somewhere off this machine",
    "ignore-block": "Ignore rules that have drifted",
    "ignored-and-committed": "Ignored directories git is tracking anyway",
    "tracked-render": "Render directories git is tracking",
    "refused": "Renders that were refused",
    "committed-render": "Committed renders that could not be checked",
    "stale": "Committed renders that are out of date",
}


#: What makes a sentence a fix rather than a remark: it names something to run.
#: Written down here as well as asserted in the tests, because the one place it
#: is read is a check deciding whether a refusal's own advice is usable as one.
COMMANDED = ("akit ", "git ")


@dataclass(frozen=True)
class Finding:
    """One thing that is wrong, and the command that puts it right.

    `check` is the stable name a script matches on, because `what` is a sentence
    and sentences get rewritten. `fix` is never empty: a finding that cannot
    name a command is a thing to worry about with nothing to do next, and this
    command exists to be the opposite of that.
    """

    check: str
    what: str
    fix: str


@dataclass(frozen=True)
class Report:
    """Everything one `doctor` found, before any of it has been printed."""

    where: Path
    findings: tuple[Finding, ...]

    @property
    def healthy(self) -> bool:
        return not self.findings

    @property
    def exit_code(self) -> Exit:
        """Non-zero when it found something, so a script can ask without reading prose."""
        return Exit.OK if self.healthy else Exit.ERROR


@dataclass(frozen=True)
class Standing:
    """The setup one `doctor` is standing in, read once and handed to every check.

    `plan` is `None` when the manifests or a record could not be read at all,
    which is itself a finding. The checks that need it say so rather than
    guessing, because a plan that is short by one unreadable manifest would call
    every file that manifest explains an orphan.
    """

    start: Path
    places: render.Directories
    root: Path | None
    """The repository this was run in, or `None` for a home directory."""

    merged: Merged
    records: record.Records
    plan: render.Plan | None
    unreadable: str | None

    @property
    def scopes(self) -> tuple[Scope, ...]:
        """The manifests that actually exist, which is what a harness check may judge.

        A repository with no `.akit.yaml` has not left a harness out and has not
        named one nobody knows: it has said nothing, which is not a finding.
        """
        found = [Scope.USER] if self.merged.user is not None else []
        if self.merged.project is not None:
            found.append(Scope.PROJECT)
        return tuple(found)

    def base(self, scope: Scope) -> Path | None:
        return self.places.home if scope is Scope.USER else self.root

    def harnesses(self, scope: Scope) -> tuple[Adapter, ...]:
        return adapters.expand(self.merged.harnesses(scope), self.places.home)[0]


def _unreadable(standing: Standing) -> list[Finding]:
    """A manifest or a record this build cannot read, which stops everything else."""
    if standing.unreadable is None:
        return []
    return [
        Finding(
            check="unreadable",
            what=standing.unreadable,
            fix="fix the file named above, then run `akit doctor` again",
        )
    ]


def _collisions(standing: Standing) -> list[Finding]:
    """Two kits rendering to one name, which the manifest could not refuse by itself."""
    return [
        Finding(
            check="collision",
            what=(
                f'two subscriptions both render the {kind} "{name}": '
                f"{joined(f'{entry.source} ({SCOPE_NAMED[entry.scope]})' for entry in wanted)}"
            ),
            fix=f"run `akit remove {name}` for one of them, then `akit add <source> {name} --as <other-name>`",
        )
        for (kind, name), wanted in sorted(standing.merged.collisions().items())
    ]


def _subscriptions(standing: Standing) -> list[Finding]:
    """Every subscription that could not be turned into files, one line each.

    This is where a source missing from the cache and a pin the cache does not
    hold arrive, because both are a resolution that failed and `render.plan`
    already reports them per line rather than stopping. A target refused for
    being a symlink arrives here too, which is why the check is not named after
    resolution: not every subscription that produced nothing failed to resolve.

    **A problem that names a command of its own keeps it.** Every refusal in
    this package says what went wrong on the first line and what to do about it
    on the lines under it (DESIGN.md section 3, rule 5), and those lines were
    being dropped: the heading took the first line and the fix written here
    replaced the rest. `akit update` is the right answer for a pin the cache
    does not hold and the wrong one for a link somebody made by hand, and the
    sentence that knows which is the one the refusal already wrote.

    It has to name a command, because that is what a finding promises. A
    refusal whose second line is advice rather than an instruction - "check the
    path, or subscribe to the repository instead" - leaves this check to supply
    one, which is what the fallback is.
    """
    if standing.plan is None:
        return []
    return [
        Finding(
            check="subscription",
            what=(
                f"{entry.subscription.kind} {entry.subscription.name} from {entry.subscription.source} "
                f"cannot be rendered: {_said(entry)[0]}"
            ),
            fix=_offered(entry)
            or (
                f"run `akit update {entry.subscription.name}` to fetch it and move the pin, "
                f"or `akit remove {entry.subscription.name}` if it is gone for good"
            ),
        )
        for entry in standing.plan.problems
    ]


def _said(entry: render.Entry) -> Sequence[str]:
    """What a problem said, as the lines it was written in."""
    return (entry.problem or "").splitlines()


def _offered(entry: render.Entry) -> str:
    """The fix a problem wrote for itself, or nothing when it did not write one.

    Nothing also covers a problem whose own advice names no command: a finding
    that cannot say what to run is the thing `doctor` exists to be the opposite
    of, and `tests/test_doctor.py` refuses one on every call.
    """
    offered = " ".join(line.strip() for line in _said(entry)[1:])
    return offered if "`" in offered and any(verb in offered for verb in COMMANDED) else ""


def _rendered_files(standing: Standing) -> list[Finding]:
    """What the records claim, judged against the disk and against the next render.

    Two findings share one walk because they are two answers to one question
    about each entry. A copy whose hash has drifted is the only file in a
    rendered directory that holds something somebody wrote, and a copy nothing
    explains any more is what the next `render` will take away.

    The second half is skipped while anything is unresolved, for the reason
    `render` suspends withdrawal then: the list of what is still explained is
    incomplete, and every file the missing source would have explained would be
    reported as about to go.
    """
    found: list[Finding] = []
    complete = standing.plan is not None and not standing.plan.problems
    spots = standing.plan.spots if standing.plan is not None else frozenset()
    for entry in sorted(_entries(standing.records), key=lambda written: (str(written.path), written.region or "")):
        here = entry.path if entry.region is None else f'the "{entry.region}" block in {entry.path}'
        if entry.current() is not None and not entry.still_a_copy():
            found.append(
                Finding(
                    check="edited",
                    what=f"{here} has been edited since it was rendered",
                    fix=(
                        "run `akit render`, which writes the source's bytes back over it; to keep the change, "
                        "put it in a source of your own first"
                    ),
                )
            )
        elif complete and entry.spot not in spots:
            found.append(
                Finding(
                    check="unexplained",
                    what=f"{here} is rendered, and no subscription and harness in scope explains it any more",
                    fix="run `akit render`, which withdraws it",
                )
            )
    return found


def _entries(records: record.Records) -> list[record.Written]:
    """Every entry both records hold, each one once however many claim it."""
    seen: dict[record.Spot, record.Written] = {}
    for found in records.by_scope.values():
        for entry in found.written:
            seen.setdefault(entry.spot, entry)
    return list(seen.values())


def _orphans(standing: Standing) -> list[Finding]:
    """A kit sitting in a directory we own that no record claims and no render wants.

    What a lost record leaves behind, and the one thing `render --prune` is for.
    A kit somebody wrote by hand in the same directory looks exactly like one,
    which is why this reports and never deletes (DESIGN.md section 6).

    **A symlink is not one of these.** This tool never creates one (DESIGN.md
    section 9), so a link here was made by a person and cannot be a render
    whose record was lost. Reporting it as one offered `--prune` for it, and
    `--prune` followed it: the contents of whatever it pointed at went, and the
    command then died trying to remove the link as a directory.

    **The safe branch is named first, and it is the one in plain words.** The
    two outcomes are not equally bad: pruning a hand-written skill destroys the
    only copy of it, and leaving a stale render costs nothing until somebody
    asks. A fix line that opens with the destructive command on a finding this
    check cannot tell apart from an authored directory is an invitation to run
    it four times in a row, which is how issue #30 was found.

    **Where a repository contains the render root, it can tell them apart.** A
    directory git tracks was written by somebody and has a history, whatever it
    looks like from here, so it is authored content in generated territory
    rather than a render whose record was lost. That is a different fault with a
    different fix, and offering `--prune` for it was the wrong half of the
    sentence above.
    """
    if standing.plan is None:
        return []
    explained = set(standing.records.paths) | {path for path, _ in standing.plan.spots}
    found: list[Finding] = []
    for base, written in sorted(standing.plan.owned.items()):
        for relative in sorted(written):
            directory = base.joinpath(*relative.split(SEPARATOR))
            if not directory.is_dir():
                continue
            found.extend(
                _unexplained_finding(child)
                for child in sorted(directory.iterdir())
                if not child.is_symlink() and not any(path == child or path.is_relative_to(child) for path in explained)
            )
    return found


def _unexplained_finding(child: Path) -> Finding:
    """What a directory nothing explains is, which git can sometimes answer."""
    root = manifest.worktree_root(child)
    if root is not None and _tracked_inside(root, child.relative_to(root).as_posix()):
        return Finding(
            check="authored-render",
            what=f"{child} is tracked by the repository at {root}, and sits where akit renders",
            fix=(
                f"move it out of {child.parent} into a repository of its own, then `akit add <path> "
                f"{child.name} --global`: what renders there is generated, and this is not"
            ),
        )
    return Finding(
        check="orphan",
        what=f"{child} looks like a render, and no record knows about it",
        fix=(
            "leave it alone if you wrote it by hand, which looks identical from here; "
            "`akit render --prune` deletes it, and lists what it found and asks first"
        ),
    )


def _foreign(standing: Standing) -> list[Finding]:
    """A record naming a file outside the root that record answers for.

    Two faults put one here and both are this tool's own. A render target under
    a symlink used to be recorded as wherever the link pointed, which made a git
    working tree something a withdrawal would delete. And a test suite that
    redirected the render target but not the state directory wrote entries full
    of temporary paths into the real record.

    Neither is actionable by the person reading, and both are already handled:
    the entry is not loaded as an explanation, so nothing will act on it. What
    this adds is being told, because a record silently shorter than its file is
    the kind of thing that should not happen quietly twice.
    """
    return [
        Finding(
            check="foreign-entry",
            what=f"{found.path} claims {entry.path}, which is outside the root that record answers for",
            fix="run `akit render`, which writes the record back without it",
        )
        for found in standing.records.by_scope.values()
        for entry in found.foreign
    ]


def _abandoned_record(standing: Standing) -> list[Finding]:
    """A repository keeping a record of renders no manifest asks for any more.

    What deleting a `.akit.yaml` leaves behind. The files it names are still
    explained by nothing at all, and the next render is what collects both them
    and the record.
    """
    if standing.root is None or (standing.root / manifest.PROJECT_MANIFEST).is_file():
        return []
    kept = record.project_location(standing.root)
    if not kept.is_file():
        return []
    return [
        Finding(
            check="abandoned-record",
            what=f"{kept} says this project was rendered into, and it has no {manifest.PROJECT_MANIFEST} any more",
            fix="run `akit render`, which withdraws what nothing explains and takes the record with it",
        )
    ]


def _aimed_at(config: Path, key: str) -> tuple[str, ...]:
    """Where a harness config's one key points, or nothing if it points nowhere.

    A config that is absent or that this build cannot read is not a dangling
    pointer: nothing was pointed anywhere. The file belongs to a person and to a
    harness, and guessing at a shape neither of them promised is how a report
    turns into noise.
    """
    if not config.is_file():
        return ()
    try:
        document = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    if not isinstance(document, dict):
        return ()
    aimed = document.get(key)
    if isinstance(aimed, str):
        return (aimed,)
    if isinstance(aimed, list):
        return tuple(entry for entry in aimed if isinstance(entry, str))
    return ()


def _pointers(standing: Standing) -> list[Finding]:
    """A harness pointed at a directory of ours that is not there.

    What this tool leaves rather than editing somebody's config on the way out
    (DESIGN.md section 7). No adapter shipping for 1.0 takes rules this way, so
    the check is written against the interface rather than against a harness,
    and it starts reporting the day one arrives.
    """
    found: list[Finding] = []
    for adapter in adapters.ADAPTERS:
        for scope in Scope:
            pointer = adapter.pointer.get(scope)
            base = standing.base(scope)
            if pointer is None or base is None:
                continue
            config = base.joinpath(*pointer.config.split(SEPARATOR))
            found.extend(
                Finding(
                    check="dangling-pointer",
                    what=f"{config} points {adapter.name} at {base / aimed}, and there is nothing there",
                    fix=f"run `akit render`, or take the `{pointer.key}` key out of {config} by hand",
                )
                for aimed in _aimed_at(config, pointer.key)
                if not base.joinpath(*aimed.split(SEPARATOR)).exists()
            )
    return found


def _escaping_paths(standing: Standing) -> list[Finding]:
    """A committed manifest naming a path that leaves the repository.

    Somebody's laptop written into a shared file. `render` refuses it and this
    reports it, from the same answer, so the two cannot disagree about which
    paths count.
    """
    return [
        Finding(
            check="escaping-path",
            what=f"this project's committed manifest names {source}, which is outside {standing.root}",
            fix=(
                f"run `akit remove <name>` for it, then `akit add {source} <name> --global`: "
                f"that path exists on this machine and on no other"
            ),
        )
        for source in render.escaping(standing.merged, standing.root)
    ]


def _harness_names(standing: Standing) -> list[Finding]:
    """A `harnesses:` list naming something no adapter answers to, which nothing else validates."""
    found: list[Finding] = []
    for scope in standing.scopes:
        for name in adapters.expand(standing.merged.harnesses(scope), standing.places.home)[1]:
            found.append(
                Finding(
                    check="unknown-harness",
                    what=f'{SCOPE_NAMED[scope]} names the harness "{name}", and no adapter answers to it',
                    fix=f"run `akit harness remove {name}`, and `akit list` to see the harnesses this build knows",
                )
            )
    return found


def _left_out(standing: Standing) -> list[Finding]:
    """A harness on this machine that a manifest's list leaves out.

    The one failure that looks exactly like success: nothing is rendered for it,
    nothing fails, and the agent behaves as if the kits were never there
    (DESIGN.md section 6).
    """
    found: list[Finding] = []
    for scope in standing.scopes:
        chosen = {adapter.name for adapter in standing.harnesses(scope)}
        found.extend(
            Finding(
                check="harness-left-out",
                what=f"{adapter.name} is installed on this machine, and {SCOPE_NAMED[scope]} does not render for it",
                fix=f"run `akit harness add {adapter.name}{'' if scope is Scope.PROJECT else ' --global'}`",
            )
            for adapter in adapters.detected(standing.places.home)
            if adapter.name not in chosen
        )
    return found


def _not_reading(standing: Standing) -> list[Finding]:
    """Files in place for a harness this machine shows no sign of (DESIGN.md section 4).

    A render for a harness that is named rather than detected is not a mistake:
    a repository pins its list so that everybody gets the same files. It is
    worth one line anyway, because the other thing it looks like is a harness
    that has moved its directories and stopped reading ours.

    Only when something really is on disk for it, which is why this asks the
    records rather than the harness list or the plan. A repository that names a
    harness and has never rendered has nothing in place to go unread, and
    saying otherwise in a fresh clone is how this command would earn being
    ignored.
    """
    rendered = {name for entry in _entries(standing.records) for name in entry.harnesses}
    return [
        Finding(
            check="harness-not-here",
            what=f"kits are rendered for {adapter.name}, and this machine shows no sign of it being installed",
            fix=f"run `akit harness remove {adapter.name}` if you do not use it here",
        )
        for adapter in _rendering_for(standing)
        if adapter.has_a_machine and not adapter.detected(standing.places.home) and adapter.name in rendered
    ]


def _rendering_for(standing: Standing) -> list[Adapter]:
    """Every harness some manifest in play renders for, each one once.

    By name rather than as a set: an adapter is a frozen dataclass holding
    mappings, which makes it unhashable, and the thing two scopes naming one
    harness must not produce is two findings about it.
    """
    chosen: dict[str, Adapter] = {}
    for scope in standing.scopes:
        for adapter in standing.harnesses(scope):
            chosen.setdefault(adapter.name, adapter)
    return [chosen[name] for name in sorted(chosen)]


def _ignored(standing: Standing) -> list[Finding]:
    """The `.gitignore` block of every repository a render writes into, in both directions.

    A rendered directory missing from it is a laptop's kits on their way into
    somebody's history. A directory in it that git also tracks is the opposite
    and is worse: the files are committed and ignored at once, so nothing you do
    to them shows up in a diff again.

    **Both are asked of the global scope too**, because a home directory holding
    a git repository is ordinary. `~/.agents` kept as a repository to share or
    back up is the shape this tool replaces, so it is the shape a person arrives
    with, and a render into it is as committable as a render into a project. The
    difference is whose file the `.gitignore` is: a project's is maintained by
    every render, and this one is reported until `akit render --global
    --gitignore` is asked for.

    Only where that scope has actually rendered. A repository that has never run
    this has no block and needs none, and reporting one would be this command's
    answer to "you have not rendered yet", which is a sentence the whole of
    `akit list` already says better.
    """
    if standing.plan is None:
        return []
    plan = standing.plan
    keeps_a_record = any(Scope.PROJECT in planned.scopes for planned in plan.writes.values())
    explained = set(standing.records.paths) | {path for path, _ in plan.spots}
    found: list[Finding] = []
    for block in render.ignore_block(plan.walk, plan.owned, explained, tuple(Scope), keeps_a_record=keeps_a_record):
        scope = Scope.PROJECT if block.maintained else Scope.USER
        if not standing.records.of(scope).written:
            continue
        found.extend(_block_findings(standing, block))
        found.extend(
            _tracking_finding(block, relative) for relative in block.listed if _tracked_inside(block.root, relative)
        )
    return found


def _block_findings(standing: Standing, block: render.Ignored) -> list[Finding]:
    """The one finding a stale or missing block is worth, worded for whose file it is."""
    if not block.changed:
        return []
    where = block.root / ignore.GITIGNORE
    if not block.maintained:
        return [
            Finding(
                check="ignore-block",
                what=f"{block.root} is a git repository that akit renders into, and {where} does not say so",
                fix="run `akit render --global --gitignore`, which writes that block and nothing else new",
            )
        ]
    if _commits_renders(standing):
        return []
    return [
        Finding(
            check="ignore-block",
            what=f"the akit block in {where} does not list what this project renders",
            fix="run `akit render`, which rewrites that block whole",
        )
    ]


def _tracking_finding(block: render.Ignored, relative: str) -> Finding:
    """Git tracking a directory a render owns, which is the same fault in two settings.

    The untracking is named second on purpose. This directory is where renders
    go and may also hold a skill somebody wrote, which the check above reports
    one by one, and `git rm -r --cached` over the lot takes both. Doing the
    authored half first leaves a command whose whole effect is to stop
    committing generated files.
    """
    if not block.maintained:
        return Finding(
            check="tracked-render",
            what=f"git is tracking files in {block.root / relative}, which akit renders into",
            fix=(
                f"settle anything of your own reported in it first, then `git rm -r --cached {relative}` "
                f"in {block.root} and commit that: what is left there is generated"
            ),
        )
    return Finding(
        check="ignored-and-committed",
        what=f"{block.root / ignore.GITIGNORE} ignores {relative}, and git is tracking files in it",
        fix=(
            f"run `git rm -r --cached {relative}` and commit that, or `akit harness add <name>` "
            f"if this project means to commit them"
        ),
    )


def _tracked_inside(root: Path, relative: str) -> bool:
    """Whether git has anything under this directory, which is what "committed" means here."""
    found = cache.git("ls-files", "--", relative, cwd=root, anonymous=False, check=False)
    return bool(found.stdout.strip())


def _commits_renders(standing: Standing) -> bool:
    """Whether this repository names a harness whose renders it has to commit.

    Which is also who owns a stale ignore block. A repository that commits gets
    that said by the committed-render check, with the rest of what is out of
    date beside it, and saying it twice in one report is one finding too many.
    """
    if standing.merged.project is None:
        return False
    named = adapters.named(standing.merged.harnesses(Scope.PROJECT), standing.places.home)[0]
    return bool(adapters.machineless(named))


def _committed_render(standing: Standing) -> list[Finding]:
    """The staleness and leak checks, run only where something is actually committed.

    `render --check` by another name, and the one part of `doctor` that fetches.
    A repository naming no machineless harness commits nothing, so there is
    nothing to be stale and nothing to leak, and asking anyway would put a
    network call in the common case for no answer.
    """
    if standing.root is None or standing.merged.project is None:
        return []
    named = adapters.machineless(adapters.named(standing.merged.harnesses(Scope.PROJECT), standing.places.home)[0])
    if not named:
        return []
    listed = joined(adapter.name for adapter in named)
    try:
        outcome = render.render(standing.start, standing.places, render.COMMITTED, render.CHECKING)
    except RefusalError as refusal:
        return [
            Finding(
                check="refused",
                what=str(refusal),
                fix=f"run `akit harness remove {named[0].name}` to stop committing renders, or drop the subscription",
            )
        ]
    except AkitError as error:
        return [
            Finding(
                check="committed-render",
                what=f"what this project commits for {listed} could not be checked: {error}",
                fix="run `akit render --check` on its own to see the whole of it",
            )
        ]
    return [
        Finding(
            check="stale",
            what=f"what this project commits for {listed} is out of date: {reason.strip()}",
            fix="run `akit render` and commit what it writes",
        )
        for reason in outcome.stale
    ]


#: Every check, in the order a report reads best: what the setup says, then what
#: is on disk, then the two questions that need a network. One line per check is
#: the whole of adding one.
CHECKS: tuple[Callable[[Standing], list[Finding]], ...] = (
    _unreadable,
    _collisions,
    _subscriptions,
    _harness_names,
    _left_out,
    _not_reading,
    _rendered_files,
    _orphans,
    _foreign,
    _abandoned_record,
    _pointers,
    _escaping_paths,
    _ignored,
    _committed_render,
)


def _standing(start: Path, places: render.Directories) -> Standing:
    """Read the manifests, the records and the plan, and survive any of them failing.

    A manifest that will not parse is a finding rather than a traceback, which
    is the difference between a command you run when something is wrong and one
    that only works when nothing is.
    """
    root = manifest.worktree_root(start)
    try:
        plan = render.plan(start, places, render.EVERYTHING, render.INSPECTING)
    except AkitError as error:
        return Standing(
            start=start,
            places=places,
            root=root,
            merged=Merged(subscriptions=(), user=None, project=None),
            records=record.Records(by_scope={}),
            plan=None,
            unreadable=str(error),
        )
    return Standing(
        start=start,
        places=places,
        root=root,
        merged=plan.merged,
        records=record.Records(by_scope=dict(plan.before)),
        plan=plan,
        unreadable=None,
    )


def examine(start: Path, places: render.Directories) -> Report:
    """Run every check against the setup this is standing in."""
    standing = _standing(start, places)
    return Report(
        where=standing.root or places.home,
        findings=tuple(finding for check in CHECKS for finding in check(standing)),
    )


def _grouped(findings: tuple[Finding, ...]) -> dict[str, list[Finding]]:
    """The findings by their kind, in the order the checks ran rather than alphabetically.

    `CHECKS` runs unreadable first and stale last, which is roughly the order
    somebody has to fix them in: a manifest that will not parse makes every
    later heading a guess.
    """
    kinds: dict[str, list[Finding]] = {}
    for finding in findings:
        kinds.setdefault(finding.check, []).append(finding)
    return kinds


def text(report: Report, out: TextIO, *, style: Style | None = None) -> None:
    """The report a person reads: what is wrong, by kind, and under each one what to do.

    One section, grouped. The mark column every other report has is the wrong
    instrument here, because a mark distinguishes things and every finding is
    the same kind of thing: a problem. What distinguishes them is the fix, so
    that is the only indented line.

    And where a whole group shares one fix, it is printed once under the group
    rather than under every finding in it. Three identical `fix:` lines under
    one heading are three readings of the same sentence; flat, nobody could
    tell they were the same, which is what the grouping is for.
    """
    shown = style or Style.plain()
    print(f"Checked the setup in {shown.place(str(report.where))}", file=out)
    print("", file=out)
    if report.healthy:
        print("Nothing to report: the manifests, the records and the files on disk agree.", file=out)
        return
    section(f"Findings ({len(report.findings)})", out, shown)
    for kind, found in _grouped(report.findings).items():
        group(f"{TITLE[kind]} ({len(found)})", out, shown)
        shared = {finding.fix for finding in found}
        for finding in found:
            reported = finding.what.splitlines()
            wrapped(reported[0], (line.strip() for line in reported[1:]), out, indent="")
            if len(shared) > 1:
                print(f"{INDENT}fix: {finding.fix}", file=out)
        if len(shared) == 1:
            print(f"{INDENT}fix: {found[0].fix}", file=out)
        print("", file=out)


def payload(report: Report) -> dict[str, Any]:
    """The same information as data, which is what the skill reads most often."""
    return {
        "where": str(report.where),
        "healthy": report.healthy,
        "findings": [{"check": finding.check, "what": finding.what, "fix": finding.fix} for finding in report.findings],
    }


def run(out: TextIO, *, as_json: bool, start: Path | None = None, home: Path | None = None) -> Exit:
    """`akit doctor`. Non-zero when it found something, and nothing on disk changed."""
    report = examine(start or Path.cwd(), render.Directories(home=home or Path.home()))
    if as_json:
        print(json.dumps(payload(report), indent=2), file=out)
    else:
        text(report, out, style=Style.of(out))
    return report.exit_code


__all__ = ["CHECKS", "Finding", "Report", "Standing", "examine", "payload", "run", "text"]
