"""The file a person edits: read, merged across its two scopes, and written back.

This is the only code in the project that edits a file somebody owns in place,
so the whole module is shaped around giving back what it was handed. Comments,
key order, quoting style and blank lines survive, because `akit add` writing a
pin must not also reflow the thirty lines around it (DESIGN.md section 6). That
is why the dependency is a round-tripper rather than a YAML parser, and why a
`Manifest` keeps the parsed document beside the subscriptions it extracted: the
dataclasses are what the rest of the program reads, and the document is what
gets written.

**A manifest knows what you asked for and never where it is.** No path is
resolved here, nothing is cloned, no source is contacted, and a pin is a string.
That is T3's work, and keeping the two apart is what lets this module be tested
without a network or a cache (DESIGN.md section 6, "Where a source actually is").

**Neither scope overrules the other.** The two files render into two different
directories, so a name used in both produces two copies and nothing is
suppressed. `merge` therefore resolves nothing: it concatenates, tags each
subscription with the scope it came from, and leaves collisions for `list` and
`doctor` to report. The one place order means anything is rules, where yours
come before the repository's, so a repository gets the last word on its own
ground.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from platformdirs import user_config_path
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import MarkedYAMLError

from federated_agent_kits.exits import AkitError

APPLICATION = "akit"
USER_MANIFEST = "manifest.yaml"
PROJECT_MANIFEST = ".akit.yaml"

#: The only schema version this build understands. A manifest naming another one
#: is refused rather than read optimistically: the failure of guessing is a
#: subscription silently not rendering, which looks like nothing happening.
SUPPORTED_VERSION = 1

#: An absent `harnesses:` key means this, which is the ordinary repository.
#: `detected` is a name like any other and expands in T4 (DESIGN.md section 6).
DEFAULT_HARNESSES: tuple[str, ...] = ("detected",)

#: The separator before a commit. `#` and not `@`, because a git URL already has
#: one of those: `git@github.com:org/repo.git`.
PIN = "#"


class Kind(StrEnum):
    """The three kinds of thing a kit is made of, spelled as the manifest spells them."""

    SKILL = "skills"
    RULE = "rules"
    AGENT = "agents"


#: Rules are a list and the other two are mappings, which is the asymmetry in
#: DESIGN.md section 6 rather than an inconsistency: two skills cannot
#: contradict each other, so their order is noise, and two rules can.
ORDERED = (Kind.RULE,)


class Scope(StrEnum):
    """Which file a subscription came from, which is the whole of what decides its scope."""

    USER = "user"
    PROJECT = "project"


class ManifestError(AkitError):
    """A manifest that cannot be read, naming the line and what to do about it.

    Exit code 1 rather than a usage error: the command was typed correctly and a
    file on disk is malformed. Every instance carries a fix, because a parser
    that says only what is wrong leaves the person to guess the schema.
    """

    def __init__(self, path: Path | None, line: int, problem: str, fix: str) -> None:
        self.path = path
        self.line = line
        self.problem = problem
        self.fix = fix
        where = "manifest" if path is None else str(path)
        at = "" if line == UNKNOWN_LINE else f":{line}"
        super().__init__(f"{where}{at}: {problem}\n  {fix}")


@dataclass(frozen=True)
class Subscription:
    """One kit, wanted from one source, in one scope."""

    kind: Kind
    source: str
    """The key with its pin removed. Still unresolved: this may be a shorthand, a
    URL or a path, and which it is is T3's question."""

    pin: str | None
    """The commit after `#`, or `None` for a path source, which has none."""

    name: str
    """The kit as the source calls it, or `"*"` for every kit of this kind."""

    rename: str | None
    """What `as:` said, or `None`."""

    scope: Scope
    line: int
    """Where this entry sits in its own file, for an error that can be acted on."""

    @property
    def key(self) -> str:
        """The source key as it is written in the file, pin included."""
        return self.source if self.pin is None else f"{self.source}{PIN}{self.pin}"

    @property
    def rendered_name(self) -> str:
        """What this kit is called once it is on disk, which is what can collide."""
        return self.rename or self.name

    @property
    def is_wildcard(self) -> bool:
        return self.name == "*"


@dataclass
class Manifest:
    """One file: what it subscribes to, which harnesses it names, and its own text.

    `document` is kept so that writing can give back the comments and the layout
    it was handed. Nothing outside this module should read it.
    """

    scope: Scope
    path: Path | None
    subscriptions: tuple[Subscription, ...]
    harnesses: tuple[str, ...]
    document: CommentedMap = field(repr=False)

    def of_kind(self, kind: Kind) -> tuple[Subscription, ...]:
        return tuple(entry for entry in self.subscriptions if entry.kind is kind)


def _yaml() -> YAML:
    """One configured round-tripper, built per call because a `YAML` is stateful."""
    yaml = YAML()
    yaml.preserve_quotes = True
    # Off, or ruamel rewraps a long line somebody chose to leave long, and the
    # round-trip stops being byte-for-byte on exactly the files that are hardest
    # to notice it on.
    yaml.width = 4096
    return yaml


#: What a line number is when ruamel cannot supply one. Zero rather than `None`
#: so that every caller has an `int`: the alternative puts a "or if we do not
#: know" branch at each of the dozen raise sites, none of which any input can
#: reach, and a coverage gate then has to be argued with rather than met.
UNKNOWN_LINE = 0


def _line_of(node: object, key: object) -> int:
    """The 1-based line a mapping key or a sequence item sits on, or `UNKNOWN_LINE`."""
    location = getattr(node, "lc", None)
    if location is None:  # pragma: no cover - every node a round-tripper builds has one
        return UNKNOWN_LINE
    if isinstance(node, CommentedMap) and key in node:
        return location.key(key)[0] + 1
    if isinstance(node, CommentedSeq) and isinstance(key, int):
        return location.item(key)[0] + 1
    return UNKNOWN_LINE  # pragma: no cover - reached only by asking for a key that is absent


def _shape(value: object) -> str:
    """What a value is, named the way the manifest's own documentation names it.

    `type(value).__name__` would say `CommentedSeq`, which is this project's YAML
    library leaking into a message somebody is meant to act on. There is no
    branch for a mapping because every caller handles one before asking.
    """
    if isinstance(value, CommentedSeq | list):
        return "a list"
    if isinstance(value, bool):
        return "a true/false value"
    if isinstance(value, int | float):
        return "a number"
    if value is None:
        return "empty"
    return "a value"


def split_pin(key: str) -> tuple[str, str | None]:
    """A source key into its source and its commit.

    Split from the right, because the pin is at the end and a key may legitimately
    contain an earlier `#`.
    """
    source, separator, pin = key.rpartition(PIN)
    if not separator:
        return key, None
    return source, pin


def _entries(value: object, node: object, key: object, path: Path | None) -> list[tuple[str, str | None]]:
    """One entry's value as a list of `(name, as)`, whatever shape it was written in.

    A string, a mapping, or a list of either. The shapes are uniform across the
    three kinds on purpose: rules differ from skills in whether the *block* is
    ordered, not in how one subscription is spelled.
    """
    line = _line_of(node, key)
    if isinstance(value, str):
        return [(value, None)]
    if isinstance(value, CommentedMap):
        return [_named(value, line, path)]
    if isinstance(value, CommentedSeq):
        found: list[tuple[str, str | None]] = []
        for index, item in enumerate(value):
            if isinstance(item, str):
                found.append((item, None))
            elif isinstance(item, CommentedMap):
                found.append(_named(item, _line_of(value, index), path))
            else:
                raise ManifestError(
                    path,
                    _line_of(value, index),
                    f"a kit is written as {_shape(item)}, not a name or a mapping",
                    "Write the kit name, or `- name: kb` with `as: upstream-kb` beneath it.",
                )
        return found
    raise ManifestError(
        path,
        line,
        f"a subscription is written as {_shape(value)}",
        'Write a kit name, a list of them, or ["*"] for every kit the source holds.',
    )


def _named(entry: CommentedMap, line: int, path: Path | None) -> tuple[str, str | None]:
    """A `{name:, as:}` mapping, which is what a kit that needs more than its name becomes."""
    unknown = set(entry) - {"name", "as"}
    if unknown:
        raise ManifestError(
            path,
            line,
            f"a kit carries unknown key(s): {', '.join(sorted(str(key) for key in unknown))}",
            "A kit takes `name:` and `as:` and nothing else.",
        )
    if "name" not in entry:
        raise ManifestError(
            path,
            line,
            "a kit mapping has no `name:`",
            "Write `- name: kb` with `as: upstream-kb` beneath it.",
        )
    rename = entry.get("as")
    return str(entry["name"]), None if rename is None else str(rename)


def _check_version(document: CommentedMap, path: Path | None) -> None:
    if "version" not in document:
        raise ManifestError(
            path,
            1,
            "no `version:` key",
            f"Add `version: {SUPPORTED_VERSION}` as the first line.",
        )
    version = document["version"]
    if version != SUPPORTED_VERSION:
        raise ManifestError(
            path,
            _line_of(document, "version"),
            f"`version: {version}` is not a version this build knows",
            f"This build reads `version: {SUPPORTED_VERSION}`. Upgrade akit, or correct the file.",
        )


def _check_shape(document: CommentedMap, kind: Kind, path: Path | None) -> None:
    """A kind block that is a mapping where it should be a list, or the reverse.

    Worth its own refusal rather than a generic one because the two spellings are
    each other's obvious typo, and the consequence of the wrong one is silent:
    a YAML mapping does not promise the order that decides which rule wins.
    """
    block = document[kind.value]
    ordered = kind in ORDERED
    if ordered and isinstance(block, CommentedMap):
        raise ManifestError(
            path,
            _line_of(document, kind.value),
            "`rules:` is written as a mapping, which has no order",
            "Write rules as a list, `- owner/repo: prose-style`, because order decides which rule wins.",
        )
    if not ordered and isinstance(block, CommentedSeq):
        raise ManifestError(
            path,
            _line_of(document, kind.value),
            f"`{kind.value}:` is written as a list",
            f"Write `{kind.value}:` as a mapping of source to kits. Only `rules:` is a list, "
            "because only rules have an order.",
        )


def _sources(document: CommentedMap, kind: Kind, path: Path | None) -> list[tuple[str, object, object, object]]:
    """Each `(key, value, node, index)` under one kind block, in the file's own order."""
    block = document[kind.value]
    if isinstance(block, CommentedSeq):
        found = []
        for index, item in enumerate(block):
            if not isinstance(item, CommentedMap) or len(item) != 1:
                raise ManifestError(
                    path,
                    _line_of(block, index),
                    "a rule entry is not one source mapped to its rules",
                    "Write one source per list item: `- owner/repo#9f2c1ab: prose-style`.",
                )
            key = next(iter(item))
            found.append((str(key), item[key], item, key))
        return found
    return [(str(key), block[key], block, key) for key in block]


def parse(text: str, *, scope: Scope, path: Path | None = None) -> Manifest:
    """One manifest's text into the subscriptions it names.

    Every refusal carries a line and a fix, because this is a file somebody
    typed and the useful answer is which line to change.
    """
    try:
        document = _yaml().load(text)
    except MarkedYAMLError as error:
        line = UNKNOWN_LINE if error.problem_mark is None else error.problem_mark.line + 1
        raise ManifestError(path, line, f"this is not valid YAML: {error.problem}", "Correct the syntax.") from error

    if document is None:
        raise ManifestError(
            path,
            1,
            "the manifest is empty",
            f"A manifest needs at least `version: {SUPPORTED_VERSION}`.",
        )
    if not isinstance(document, CommentedMap):
        raise ManifestError(
            path,
            1,
            f"the manifest is {_shape(document)}, not a mapping of keys",
            f"A manifest starts with `version: {SUPPORTED_VERSION}` and then the kind blocks.",
        )

    _check_version(document, path)

    known = {"version", "harnesses", *(kind.value for kind in Kind)}
    for key in document:
        if str(key) not in known:
            raise ManifestError(
                path,
                _line_of(document, key),
                f"`{key}:` is not a key a manifest has",
                f"A manifest takes version, harnesses, and {', '.join(kind.value for kind in Kind)}.",
            )

    subscriptions: list[Subscription] = []
    for kind in Kind:
        if kind.value not in document:
            continue
        _check_shape(document, kind, path)
        seen: dict[str, int] = {}
        for key, value, node, index in _sources(document, kind, path):
            source, pin = split_pin(key)
            line = _line_of(node, index)
            for name, rename in _entries(value, node, index, path):
                rendered = rename or name
                if rendered in seen:
                    raise ManifestError(
                        path,
                        line,
                        f"`{rendered}` is subscribed to twice in this file, under {kind.value}",
                        f"Drop one, or give one of them a different name with `as:`. "
                        f"The first is on line {seen[rendered]}.",
                    )
                seen[rendered] = line
                subscriptions.append(
                    Subscription(
                        kind=kind,
                        source=source,
                        pin=pin,
                        name=name,
                        rename=rename,
                        scope=scope,
                        line=line,
                    )
                )

    return Manifest(
        scope=scope,
        path=path,
        subscriptions=tuple(subscriptions),
        harnesses=_harnesses(document, path),
        document=document,
    )


def _harnesses(document: CommentedMap, path: Path | None) -> tuple[str, ...]:
    if "harnesses" not in document:
        return DEFAULT_HARNESSES
    named = document["harnesses"]
    if not isinstance(named, CommentedSeq):
        raise ManifestError(
            path,
            _line_of(document, "harnesses"),
            "`harnesses:` is not a list",
            "Write `harnesses: [detected, copilot-ci]`. The list is the whole answer.",
        )
    return tuple(str(name) for name in named)


def dump(manifest: Manifest) -> str:
    """The manifest back as text, with everything a person put there still in it."""
    stream = io.StringIO()
    _yaml().dump(manifest.document, stream)
    return stream.getvalue()


def read(path: Path, *, scope: Scope) -> Manifest:
    """One manifest from disk.

    Newlines are normalised on the way in and written back as LF, which is the
    one thing a round-trip deliberately does not preserve: the repository commits
    LF, `.gitattributes` enforces it, and a CRLF manifest edited on Windows would
    otherwise make every later write a whole-file diff.
    """
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    return parse(text, scope=scope, path=path)


def write(manifest: Manifest, path: Path | None = None) -> None:
    """Write a manifest back, creating the directory above it if it is not there."""
    target = path or manifest.path
    if target is None:  # pragma: no cover - a parsed-from-string manifest has nowhere to go
        raise ValueError("this manifest has no path to write to")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(dump(manifest), encoding="utf-8", newline="\n")


def user_manifest_path() -> Path:
    """Yours, at a fixed place looked up per platform. Nothing searches for it."""
    return user_config_path(APPLICATION, appauthor=False, roaming=True) / USER_MANIFEST


def worktree_root(start: Path) -> Path | None:
    """The first directory at or above `start` holding a `.git`, or `None`.

    `.git` is a directory in an ordinary clone and a file in a worktree or a
    submodule, and both are roots: stopping at either is what keeps the walk from
    straying into the repository that contains this one.
    """
    for directory in (start, *start.parents):
        if (directory / ".git").exists():
            return directory
    return None


def find_project_manifest(start: Path) -> Path | None:
    """`.akit.yaml` beside the worktree root above `start`, if there is one.

    The walk stops at the first root, so it can reach neither another repository
    nor the user manifest, which lives in the config directory and is never on
    this path.
    """
    root = worktree_root(start)
    if root is None:
        return None
    candidate = root / PROJECT_MANIFEST
    return candidate if candidate.is_file() else None


@dataclass(frozen=True)
class Merged:
    """Both manifests as one sequence, with nothing resolved.

    This is the view every reading command works from. It tags rather than
    decides: a name in both scopes appears twice, because the two render to two
    different directories and neither can overwrite the other. Reporting that is
    `list` and `doctor`'s job (DESIGN.md section 6).
    """

    subscriptions: tuple[Subscription, ...]
    user: Manifest | None
    project: Manifest | None

    def of_kind(self, kind: Kind) -> tuple[Subscription, ...]:
        return tuple(entry for entry in self.subscriptions if entry.kind is kind)

    def harnesses(self, scope: Scope) -> tuple[str, ...]:
        """The harness list for one scope, which is the only thing it governs.

        Not merged across the two files. A subscription renders into its own
        scope and no other, so the repository's list decides what the repository
        gets and yours decides what your machine-level directories get.
        """
        manifest = self.user if scope is Scope.USER else self.project
        return DEFAULT_HARNESSES if manifest is None else manifest.harnesses

    def collisions(self) -> dict[tuple[Kind, str], tuple[Subscription, ...]]:
        """Every rendered name wanted by more than one subscription.

        Detected here because this is the first place that sees both files at
        once. It is reported and never resolved; the fix is `as:`.
        """
        grouped: dict[tuple[Kind, str], list[Subscription]] = {}
        for entry in self.subscriptions:
            if not entry.is_wildcard:
                grouped.setdefault((entry.kind, entry.rendered_name), []).append(entry)
        return {name: tuple(found) for name, found in grouped.items() if len(found) > 1}


def merge(user: Manifest | None, project: Manifest | None) -> Merged:
    """Both scopes into one sequence, yours first.

    Order only means anything for rules, and there yours come before the
    repository's so that a repository disagreeing with you gets the last word on
    its own ground. For the other two kinds the order is the files' own, which
    nothing downstream reads.
    """
    subscriptions: list[Subscription] = []
    for kind in Kind:
        for manifest in (user, project):
            if manifest is not None:
                subscriptions.extend(manifest.of_kind(kind))
    return Merged(subscriptions=tuple(subscriptions), user=user, project=project)


def load(start: Path, *, user_path: Path | None = None) -> Merged:
    """Both manifests, from a working directory, with whichever exists.

    Reading uses both, always. A missing file is not an error here: a machine
    with no personal manifest and a repository with no `.akit.yaml` are both
    ordinary, and the commands that need one to write to say so themselves.
    """
    yours = user_path or user_manifest_path()
    user = read(yours, scope=Scope.USER) if yours.is_file() else None
    found = find_project_manifest(start)
    project = read(found, scope=Scope.PROJECT) if found is not None else None
    return merge(user, project)


__all__ = [
    "DEFAULT_HARNESSES",
    "ORDERED",
    "PIN",
    "PROJECT_MANIFEST",
    "SUPPORTED_VERSION",
    "Kind",
    "Manifest",
    "ManifestError",
    "Merged",
    "Scope",
    "Subscription",
    "dump",
    "find_project_manifest",
    "load",
    "merge",
    "parse",
    "read",
    "split_pin",
    "user_manifest_path",
    "worktree_root",
    "write",
]
