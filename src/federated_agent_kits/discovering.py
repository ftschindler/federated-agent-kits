"""`akit discover`: what a source holds, asked without subscribing to anything.

The listing this prints already existed, as the error path of a failed `akit
add`: a kit name the source does not hold is answered with every kit it does
hold. That is the right answer to a question nobody could ask, and the only way
to reach it was to type a name on purpose that was not there
([#39](https://github.com/ftschindler/federated-agent-kits/issues/39)). So the
listing lives here, `add` imports it for its refusal, and one verb asks the
question honestly.

**It fetches, and that is the point rather than a cost.** A source this machine
does not have is cloned into the same cache `add` and `render` read, at the same
location, with the same classification of whether it needed credentials written
down. So a `discover` is not a look through a window: afterwards the source is
on this disk, and the `add` or `render` that follows works from the cache and
needs no network. It is the second read-only command that goes near a remote,
beside `render --check`, and its help says so.

**Nothing else about it writes.** No manifest is read, none is edited, and
nothing is rendered, which is what makes it safe to run against a repository
somebody just linked you.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from federated_agent_kits import adapters, cache, discovery, frontmatter, privacy, sources
from federated_agent_kits import manifest as manifests
from federated_agent_kits.cache import Fetched, Privacy, RefKind, UnreachableError
from federated_agent_kits.discovery import SKILL_FILE
from federated_agent_kits.exits import Exit, UsageError
from federated_agent_kits.manifest import Kind
from federated_agent_kits.reporting import INDENT, KIND_TITLE, PLURAL, SHORT, group, section
from federated_agent_kits.sources import SourceKey
from federated_agent_kits.styling import Style

#: A pin somebody typed that is already an answer. Checked rather than asked
#: about, because a commit cannot move and the remote has nothing to add.
COMMIT = re.compile(r"[0-9a-f]{7,40}")

#: The kinds a source is searched for, in the order a report prints them.
SEARCHED: tuple[Kind, ...] = tuple(Kind)

#: The frontmatter key that says what a part is for, in one line. Skills,
#: rules and Copilot's instruction files all spell it this way, so `--verbose`
#: has one key to read rather than one per kind.
DESCRIPTION = "description"

#: What a source that offers nothing is told to be. Not an error: a repository
#: with no kits in it is a true answer to the question, and the exit code is
#: reserved for not having been able to ask.
NOTHING = "This source holds no skills, rules or agents at all."


@dataclass(frozen=True)
class Offer:
    """One part a source holds, as much of it as can be said without subscribing."""

    kind: Kind
    name: str
    relative: str
    """Where it sits inside the source, which is what says whether a plain
    `owner/repo` shorthand is enough to reach it."""

    description: str | None
    """The one line of the part's own frontmatter, where it has one."""


@dataclass(frozen=True)
class Source:
    """A source as a directory on this disk, and what the fetch learned on the way.

    The three commands that fetch want three different halves of this. `add`
    writes `commit` into the manifest and `comment` beside it; `discover` prints
    `commit` and the `ref` it followed. One shape rather than a tuple whose
    third element two callers read differently.
    """

    root: Path
    commit: str | None
    """`None` for a path source, which is read where it is and never pinned."""

    comment: str | None
    """What `add` writes beside the pin, saying what it followed and when."""

    ref: str | None
    """The branch or tag that was resolved, for a report that names it."""


@dataclass(frozen=True)
class Holding:
    """Everything `akit discover` found, before anything has been printed."""

    source: str
    """The key as it was typed, minus any pin, which is what to type again."""

    resolved: Source
    offers: tuple[Offer, ...]
    kind: Kind | None
    """The `--kind` it was narrowed to, which changes what "nothing" means."""

    def of_kind(self, kind: Kind) -> tuple[Offer, ...]:
        return tuple(offer for offer in self.offers if offer.kind is kind)


def classify(key: SourceKey, found: Privacy | None, state_root: Path | None) -> None:
    """Remember what this fetch turned out to need, or leave what was known.

    `None` means this resolution never went near the network, so it learned
    nothing and has nothing to say. Writing it as a classification would turn a
    silence into an answer, and the answer it would turn into is the guess
    DESIGN.md section 8 forbids.
    """
    if found is None:
        return
    privacy.save({**privacy.load(state_root), key.raw: found}, state_root)


def frozen_comment(fetched: Fetched) -> str:
    """The comment beside a pin: what it followed, and when for the thing that moves.

    A tag does not move, so dating one would say something untrue about it. A
    branch does, so the date is the only part of the comment that tells a reader
    how old the pin is. Nothing parses either, which is the only safe thing to do
    with a comment.
    """
    if fetched.kind is RefKind.TAG:
        return f"frozen: {fetched.ref}"
    return f"frozen: {fetched.ref}, {datetime.now(tz=UTC).date().isoformat()}"


def fetch(
    key: SourceKey,
    ref: str | None,
    *,
    anchor: Path,
    cache_root: Path | None,
    state_root: Path | None,
) -> Source:
    """The source as a directory, the commit it is at, and what a pin would say.

    A path source has no pin and no comment. A commit somebody typed is already
    an answer and is only fetched. Anything else is a name on the other end, so
    the remote is asked what it points at now, and a machine that cannot reach it
    but already holds a clone answers from what it has rather than failing: `add`
    and `discover` of a cached source both work offline (DESIGN.md section 10).

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
        resolved = cache.resolve(key, anchor=anchor, cache_root=cache_root)
        return Source(root=resolved.root, commit=None, comment=None, ref=None)
    if ref is not None and COMMIT.fullmatch(ref):
        resolved = cache.resolve(key, pin=ref, anchor=anchor, cache_root=cache_root)
        classify(key, resolved.privacy, state_root)
        return Source(root=resolved.root, commit=ref, comment=None, ref=None)
    try:
        fetched = cache.refresh(key, ref=ref, cache_root=cache_root)
    except UnreachableError:
        resolved = cache.resolve(key, anchor=anchor, cache_root=cache_root, offline=True)
        return Source(
            root=resolved.root,
            commit=resolved.commit,
            comment="frozen: the commit this machine already had",
            ref=None,
        )
    classify(key, fetched.privacy, state_root)
    return Source(root=fetched.root, commit=fetched.commit, comment=frozen_comment(fetched), ref=fetched.ref)


def _described_by(part: discovery.Part) -> str | None:
    """The one line a part says about itself, or nothing where it says none.

    A header this build cannot read is not an error here. `discover` reports
    what a source holds, and a kit with a malformed header is still one the
    source holds; the command that has to parse it is the render that would
    copy it, and that one says so in the words of the kit it refused.
    """
    file = part.path / SKILL_FILE if part.kind is Kind.SKILL else part.path
    try:
        document = frontmatter.parse(file.read_bytes())
    except frontmatter.FrontmatterError:
        return None
    if document.front is None:
        return None
    said = document.front.get(DESCRIPTION)
    if not isinstance(said, str):
        return None
    return " ".join(said.split()) or None


def offers(root: Path, *, kind: Kind | None = None) -> tuple[Offer, ...]:
    """Every part a source holds, in kind order and then by name within each kind."""
    found: list[Offer] = []
    for searched in SEARCHED if kind is None else (kind,):
        parts = discovery.parts(root, searched, extra_directories=adapters.source_directories(searched))
        found.extend(
            Offer(kind=searched, name=part.name, relative=part.relative, description=_described_by(part))
            for part in sorted(parts, key=lambda part: part.name)
        )
    return tuple(found)


def described(found: tuple[Offer, ...]) -> str:
    """The listing `add` prints when the kit it was given is not in the source.

    Indented by two, because it arrives as the second half of a refusal rather
    than as a report of its own.
    """
    if not found:
        return f"  {NOTHING}"
    lines = []
    for kind in SEARCHED:
        names = [offer.name for offer in found if offer.kind is kind]
        if names:
            lines.append(f"  It holds {kind.value}: {', '.join(names)}")
    return "\n".join(lines)


def look(
    source: str,
    *,
    start: Path,
    kind: Kind | None = None,
    cache_root: Path | None = None,
    state_root: Path | None = None,
) -> Holding:
    """Resolve one source, fetching it if this machine lacks it, and read what is in it."""
    raw, ref = manifests.split_pin(source)
    key = sources.parse(raw)
    anchor = manifests.worktree_root(start) or start
    resolved = fetch(key, ref, anchor=anchor, cache_root=cache_root, state_root=state_root)
    return Holding(source=raw, resolved=resolved, offers=offers(resolved.root, kind=kind), kind=kind)


def _at(holding: Holding, style: Style) -> str:
    """How the heading names the commit, in the words `akit list` uses for one."""
    if holding.resolved.commit is None:
        return ", read where it is"
    followed = "" if holding.resolved.ref is None else f" ({holding.resolved.ref})"
    return f", at {style.place(holding.resolved.commit[:SHORT])}{followed}"


def _nothing(holding: Holding) -> str:
    """What an empty answer says, which depends on what was asked."""
    if holding.kind is None:
        return NOTHING
    return f"This source holds no {PLURAL[holding.kind]}."


def text(holding: Holding, out: TextIO, *, verbose: bool = False, style: Style | None = None) -> None:
    """The report a person reads: one heading per kind, and the names under it."""
    shown = style or Style.plain()
    section(f"From {shown.source(holding.source)}{_at(holding, shown)}", out, shown)
    print(f"{INDENT}read from {shown.place(str(holding.resolved.root))}\n", file=out)
    if not holding.offers:
        print(f"{_nothing(holding)}\n", file=out)
    for kind in SEARCHED:
        of_kind = holding.of_kind(kind)
        if not of_kind:
            continue
        group(KIND_TITLE[kind], out, shown)
        for offer in of_kind:
            print(f"- {shown.kit(offer.name)}", file=out)
            if verbose:
                _print_detail(offer, out, shown)
        print("", file=out)
    print(f"Next: {_next(holding)}", file=out)


def _print_detail(offer: Offer, out: TextIO, style: Style) -> None:
    """What `--verbose` adds: where the part is, and what it says it is for."""
    print(f"{INDENT}at {style.place(offer.relative)} in the source", file=out)
    if offer.description is not None:
        print(f"{INDENT}{offer.description}", file=out)


def _next(holding: Holding) -> str:
    """The closing line, which is a command somebody can paste.

    It names a kit this source actually holds rather than a placeholder,
    because the whole point of having listed them is that there is now a real
    name to put there. A source holding nothing has no such name, and what is
    worth reading then is where a source is expected to keep its kits.
    """
    if not holding.offers:
        return "akit help sources, for where a source keeps the kits this one has none of"
    return f"akit add {holding.source} {holding.offers[0].name}, to subscribe to one of these"


def payload(holding: Holding) -> dict[str, Any]:
    """The same information as data, carrying the path a text listing leaves out."""
    return {
        "source": holding.source,
        "resolved_to": str(holding.resolved.root),
        "commit": holding.resolved.commit,
        "ref": holding.resolved.ref,
        "kind": None if holding.kind is None else str(holding.kind),
        "parts": [
            {
                "kind": str(offer.kind),
                "name": offer.name,
                "path": offer.relative,
                "description": offer.description,
            }
            for offer in holding.offers
        ],
    }


def run(out: TextIO, *, source: str, as_json: bool, verbose: bool = False, kind: Kind | None = None) -> Exit:
    """`akit discover`. A source it could read is a success, whatever it held.

    Where the cache and the privacy record live is not an argument, because
    this verb has no reason to put them anywhere but where every other verb
    looks. `look` takes them, which is what the tests use.
    """
    holding = look(source, start=Path.cwd(), kind=kind)
    if as_json:
        print(json.dumps(payload(holding), indent=2), file=out)
    else:
        text(holding, out, verbose=verbose, style=Style.of(out))
    return Exit.OK


__all__ = [
    "NOTHING",
    "Holding",
    "Offer",
    "Source",
    "classify",
    "described",
    "fetch",
    "frozen_comment",
    "look",
    "offers",
    "payload",
    "run",
    "text",
]
