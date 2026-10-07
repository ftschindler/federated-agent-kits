"""A source key as a person writes it, turned into something resolvable.

A manifest key names a source and says nothing about where that source is on
this disk (DESIGN.md section 6, "Where a source actually is"). This module is the
first half of closing that gap: it reads the five forms a key may take and says
what each one names. Fetching is `cache.py`'s job, and nothing here touches the
network or the filesystem.

**Normalisation is the point, not a tidy-up.** `owner/repo`,
`https://github.com/owner/repo`, `https://github.com/owner/repo.git` and
`git@github.com:owner/repo.git` are one repository written four ways, and a
cache that did not know it would clone it four times and then let `update` move
four pins independently. So every key carries an `identity`, which is what the
cache is keyed on, beside the `url` git is actually handed.

**A subdirectory URL is still that repository.** `.../tree/main/skills/writing`
clones the same thing as `.../tree/main`; what it adds is a ref to clone and a
directory to look in, which is discovery's business and not the cache's.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from federated_agent_kits.exits import AkitError

#: Where a bare `owner/repo` is assumed to live. The shorthand exists because it
#: is what people already type, and what they already mean by it is GitHub.
DEFAULT_FORGE = "github.com"

#: The segment a forge puts between a repository and a path inside it. GitHub
#: spells it `/tree/<ref>/<path>`; GitLab spells the same thing `/-/tree/...`,
#: which splits into these two in order.
TREE = "tree"
GITLAB_SEPARATOR = "-"

#: Suffixes that make a URL a file rather than a repository. A manifest records
#: which revision you have, and none of these has one: updating a `SKILL.md` at
#: some URL would mean fetching it again and hoping (DESIGN.md section 5).
NOT_A_REPOSITORY = (".md", ".zip", ".tar", ".tar.gz", ".tgz", ".txt", ".json", ".yaml", ".yml")

#: A forge path that names one file inside a repository rather than the
#: repository. Worth its own message because it is what the browser's address
#: bar holds when somebody is looking at the skill they want.
BLOB = "blob"

#: What a URL's path needs at least: an owner and a repository. Anything shorter
#: names a user or an organisation, which holds repositories and is not one.
OWNER_AND_REPOSITORY = 2

_SHORTHAND = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$")
_SCP_LIKE = re.compile(r"^(?P<user>[A-Za-z0-9._-]+@)?(?P<host>[A-Za-z0-9.-]+):(?P<path>[^/].*)$")
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:[\\/]")
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")

#: How long a cache directory's readable half may be. The identity is hashed
#: anyway, so this only decides how much of it a person can recognise when they
#: look in the cache directory; the limit is Windows' path length being the
#: shortest of the two platforms rather than any property of a key.
SLUG_LIMIT = 48


class SourceError(AkitError):
    """A key that does not name a source, with what to write instead.

    Exit code 1 rather than a usage error, because the key usually arrives from
    a manifest rather than from the command line, and the fix is to that file.
    """

    def __init__(self, key: str, problem: str, fix: str) -> None:
        self.key = key
        self.problem = problem
        self.fix = fix
        super().__init__(f"{key}: {problem}\n  {fix}")


class SourceKind(StrEnum):
    """Whether a source has to be fetched, which is the only distinction that changes anything."""

    REMOTE = "remote"
    """A git repository somewhere else. Cloned into the cache, pinned to a commit."""

    PATH = "path"
    """A directory already on this disk. Never cloned, never cached, never pinned."""


@dataclass(frozen=True)
class SourceKey:
    """One key, read. Still not resolved: no path here exists until `cache.py` says so."""

    raw: str
    """Exactly what the manifest said, for every message about this source."""

    kind: SourceKind

    url: str
    """What git is handed, or the path as written for a path source."""

    identity: str
    """The same string for every spelling of one repository, and what the cache is keyed on."""

    ref: str | None = None
    """A branch or tag a subdirectory URL named, which is where a clone starts."""

    subdirectory: str | None = None
    """The directory inside the source a key selected, or `None` for the whole of it."""

    @property
    def is_remote(self) -> bool:
        return self.kind is SourceKind.REMOTE

    @property
    def cache_slug(self) -> str:
        """A directory name for this source: recognisable, unique, and legal on Windows.

        The readable half is for somebody looking at their own cache directory.
        The digest is what makes it unique, since two identities can perfectly
        well slugify to the same string.
        """

        readable = _UNSAFE.sub("-", self.identity).strip("-").lower()[:SLUG_LIMIT]
        digest = sha256(self.identity.encode("utf-8")).hexdigest()[:12]
        return f"{readable}-{digest}"


def _looks_like_a_path(key: str) -> bool:
    """Whether a key names somewhere on this disk rather than somewhere else.

    Deliberately syntactic: a path is recognised by how it is written, not by
    whether it happens to exist today. The alternative makes a typo in a
    committed manifest mean something different on a machine that has a
    directory by that name.
    """
    if key in {".", ".."}:
        return True
    if key.startswith(("./", "../", ".\\", "..\\", "~", "/", "\\")):
        return True
    return bool(_WINDOWS_DRIVE.match(key))


def _refuse_a_file(key: str, path: str, segments: list[str]) -> None:
    """A URL naming a file rather than a repository, which has no revision to pin.

    `/blob/` is checked first because it is the more specific of the two and the
    likelier to be pasted: it is what the browser's address bar holds while
    somebody is looking at the skill they want.
    """
    if BLOB in segments:
        raise SourceError(
            key,
            "this names one file inside a repository",
            "Drop everything from `/blob/` onwards and subscribe to the kit by name, "
            "or point at its directory with `/tree/<branch>/<directory>`.",
        )
    lowered = path.lower()
    if lowered.endswith(NOT_A_REPOSITORY):
        raise SourceError(
            key,
            "this names a file, not a git repository",
            "A source is a repository. Name the repository that holds this file, and subscribe to the kit by name.",
        )


def _split_forge_path(key: str, segments: list[str]) -> tuple[list[str], str | None, str | None]:
    """A forge URL's path into `(repository, ref, subdirectory)`.

    The two spellings differ by one segment: GitHub writes `/tree/<ref>/<path>`
    and GitLab writes `/-/tree/<ref>/<path>`, so the `-` is dropped and the rest
    is read the same way.
    """
    if TREE not in segments:
        return segments, None, None
    cut = segments.index(TREE)
    repository = segments[:cut]
    if repository and repository[-1] == GITLAB_SEPARATOR:
        repository = repository[:-1]
    rest = segments[cut + 1 :]
    if not rest:
        raise SourceError(
            key,
            "this ends at `/tree/` and names no branch",
            "Write `/tree/<branch>` for the whole repository, or `/tree/<branch>/<directory>` for one part of it.",
        )
    ref, *inside = rest
    return repository, ref, str(PurePosixPath(*inside)) if inside else None


def _identity(host: str, repository: list[str]) -> str:
    """One string per repository, whatever spelling it arrived in.

    Lowercased, because forges are case-insensitive about owners and the
    filesystem the cache sits on may be too, and a `.git` suffix removed because
    it is optional in every form that accepts it.
    """
    tail = list(repository)
    tail[-1] = tail[-1].removesuffix(".git")
    # `urlsplit` calls the whole authority the netloc, so `ssh://git@host/...`
    # arrives here as `git@host`. Two spellings of one repository differing by a
    # username would otherwise be two cache entries.
    bare = host.rpartition("@")[2]
    return "/".join([bare.lower(), *(segment.lower() for segment in tail)])


def _from_url(key: str, url: str) -> SourceKey:
    """Any URL with a scheme: a forge URL, a git URL, or a `file://` one."""
    parsed = urlsplit(url)
    segments = [segment for segment in parsed.path.split("/") if segment]
    _refuse_a_file(key, parsed.path, segments)
    if parsed.scheme == "file":
        # A local repository served over `file://`, which is how this project's
        # own tests clone without anybody's server. There is no forge layout to
        # read, so the whole path is the repository and its identity is itself.
        return SourceKey(raw=key, kind=SourceKind.REMOTE, url=url, identity=url.rstrip("/"))
    if len(segments) < OWNER_AND_REPOSITORY:
        raise SourceError(
            key,
            "this URL names no repository",
            "A source URL names an owner and a repository: `https://github.com/owner/repo`.",
        )
    repository, ref, subdirectory = _split_forge_path(key, segments)
    clone = f"{parsed.scheme}://{parsed.netloc}/{'/'.join(repository)}"
    return SourceKey(
        raw=key,
        kind=SourceKind.REMOTE,
        url=clone,
        identity=_identity(parsed.netloc, repository),
        ref=ref,
        subdirectory=subdirectory,
    )


def _from_scp(key: str, match: re.Match[str]) -> SourceKey:
    """`git@github.com:org/repo.git`, which is a URL with the slash left out."""
    host = match.group("host")
    path = match.group("path")
    segments = [segment for segment in path.split("/") if segment]
    _refuse_a_file(key, path, segments)
    if len(segments) < OWNER_AND_REPOSITORY:
        raise SourceError(
            key,
            "this URL names no repository",
            "A source URL names an owner and a repository: `git@github.com:owner/repo.git`.",
        )
    return SourceKey(raw=key, kind=SourceKind.REMOTE, url=key, identity=_identity(host, segments))


def parse(key: str) -> SourceKey:
    """One source key, in any of its five forms.

    The key arrives with its pin already removed, because splitting `#<commit>`
    off is the manifest's business and a pin is not part of naming a source.
    """
    key = key.strip()
    if not key:
        raise SourceError(
            key,
            "a source key is empty",
            "Write a source: `owner/repo`, a git URL, or a path like `.` or `../my-kits`.",
        )
    if _looks_like_a_path(key):
        return SourceKey(raw=key, kind=SourceKind.PATH, url=key, identity=key)
    if "://" in key:
        return _from_url(key, key)
    scp = _SCP_LIKE.match(key)
    if scp is not None:
        return _from_scp(key, scp)
    if _SHORTHAND.match(key):
        owner, repository = key.split("/")
        return SourceKey(
            raw=key,
            kind=SourceKind.REMOTE,
            url=f"https://{DEFAULT_FORGE}/{owner}/{repository}",
            identity=_identity(DEFAULT_FORGE, [owner, repository]),
        )
    raise SourceError(
        key,
        "this is not a source",
        "A source is `owner/repo`, a forge or git URL, a URL into a subdirectory, or a path "
        "beginning with `.`, `~` or a drive letter.",
    )


def local_path(source: SourceKey, *, anchor: Path) -> Path:
    """Where a path source actually is, with a relative key read against `anchor`.

    A relative path means the same thing on every machine because it resolves
    against the repository root rather than against whichever directory the
    command was typed in (DESIGN.md section 6). An absolute one is already an
    answer and only ever makes sense in your own manifest.
    """
    written = Path(source.url).expanduser()
    if written.is_absolute():
        return written
    return (anchor / written).resolve()


def escapes(source: SourceKey, *, anchor: Path) -> bool:
    """Whether a path key reaches outside the repository that would commit it.

    `.` and `./kits` mean the same thing on every machine; `../my-kits` and
    `/home/me/kits` mean something only on yours. A committed manifest may hold
    the first kind and not the second, which is a check rather than a convention
    and belongs in the hook this project ships (DESIGN.md section 6).
    """
    if source.is_remote:
        return False
    resolved = local_path(source, anchor=anchor)
    return not resolved.is_relative_to(anchor.resolve())


__all__ = [
    "DEFAULT_FORGE",
    "SourceError",
    "SourceKey",
    "SourceKind",
    "escapes",
    "local_path",
    "parse",
]
