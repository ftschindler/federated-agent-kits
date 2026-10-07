"""Turning a key into a directory on this disk, and saying how private it was.

Cloning is not a step of any command. It is what resolution does when it meets a
remote source the cache does not hold (DESIGN.md section 6), so everything here
hangs off one `resolve` call: a path source is read where it is, a cached remote
is used as it stands, and a remote nobody has yet is fetched now.

**The privacy classification is a side effect of fetching, not a question we can
ask later.** A source that needed credentials is private and one that clones
anonymously is public (DESIGN.md section 8), and "needed credentials" is only
observable while cloning. So the first attempt is made with the developer's
credentials taken away: no helper, no prompt, no global config. If that works the
source is public. If it fails, the same clone is tried again with their git
configured as they configured it, and a source that then succeeds is private.

That ordering costs a wasted attempt on a private source and nothing on a public
one, which is the right way round: the wasted attempt is a shallow clone that
fails during the handshake, before any object is transferred. The reverse
ordering would make every public source pay for a second round trip.

**Everything is cloned shallow, and deepened only when a pin asks for it.** The
cache exists to hold the parts a kit is made of, not the history they arrived
with. A pinned commit outside the one-commit window is fetched by name, and the
fall back to a full fetch exists for the forges that decline that.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from platformdirs import user_cache_path

from federated_agent_kits.exits import AkitError
from federated_agent_kits.sources import SourceKey, SourceKind, local_path

APPLICATION = "akit"
SOURCES = "sources"

#: Everything that lets git reach the developer: a credential helper that could
#: answer, a prompt that could ask, and the config that names either. Applied to
#: the first attempt only, which is what makes that attempt a test of whether
#: the source is public rather than a test of whether this laptop can see it.
WITHOUT_CREDENTIALS: dict[str, str] = {
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_ASKPASS": "",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
}

#: Flags that make the anonymous attempt cheap and silent. `credential.helper=`
#: on the command line as well as the scrubbed config, because a helper can also
#: be set per URL and the empty value resets the whole list.
ANONYMOUS_FLAGS: tuple[str, ...] = ("-c", "credential.helper=", "-c", "core.askPass=")

#: git's own namespace, removed from whatever environment we inherited. A render
#: run from a pre-commit hook starts inside somebody's commit, with `GIT_DIR` and
#: friends exported, and a clone that inherited those would operate on their
#: repository rather than on the cache.
GIT_PREFIX = "GIT_"

#: One commit is all a render reads. A pin outside it is fetched by name.
SHALLOW = ("--depth", "1", "--no-tags")

#: What a file or a directory is chmodded to before it is removed. git writes
#: its objects read-only, and on Windows a read-only file cannot be unlinked.
WRITABLE = 0o700


class CacheError(AkitError):
    """A source that could not be made into a directory, and what to do about it."""

    def __init__(self, source: SourceKey, problem: str, fix: str) -> None:
        self.source = source
        super().__init__(f"{source.raw}: {problem}\n  {fix}")


class Privacy(StrEnum):
    """What cloning the source turned out to need.

    Two states and no third, because the rule in DESIGN.md section 8 has two
    sides. A source that could not be reached at all is an error rather than a
    classification: refusing is what that section asks for, and guessing is what
    it forbids.
    """

    PUBLIC = "public"
    PRIVATE = "private"


@dataclass(frozen=True)
class Resolved:
    """A source, as a directory this machine can read.

    `privacy` is `None` for two different reasons, and both mean "ask somewhere
    else". A path source takes the classification of the repository it sits in,
    which costs nothing to work out and is not this module's business. A cached
    remote was classified when it was fetched, and the render record is where
    that was written down (DESIGN.md section 6).
    """

    source: SourceKey
    root: Path
    """The directory discovery reads, with a subdirectory key already applied."""

    commit: str | None
    """What the clone is checked out at, or `None` for a path source."""

    privacy: Privacy | None
    fetched: bool
    """Whether this resolution went near the network."""


def root() -> Path:
    """Where clones live: the platform cache directory, never a spelled-out `~/.cache`."""
    return user_cache_path(APPLICATION, appauthor=False) / SOURCES


def location(source: SourceKey, *, cache_root: Path | None = None) -> Path:
    """Where one source's clone belongs, which is the same for every spelling of it."""
    return (cache_root or root()) / source.cache_slug


def _environment(*, anonymous: bool) -> dict[str, str]:
    """The environment a git invocation gets, with the outer repository taken out."""
    environment = {key: value for key, value in os.environ.items() if not key.startswith(GIT_PREFIX)}
    if anonymous:
        environment.update(WITHOUT_CREDENTIALS)
    return environment


def _git(
    *arguments: str,
    cwd: Path | None = None,
    anonymous: bool,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """One git invocation. No shell, no `&&`, and never the ambient git environment."""
    flags = ANONYMOUS_FLAGS if anonymous else ()
    return subprocess.run(
        ["git", *flags, *arguments],
        cwd=None if cwd is None else str(cwd),
        env=_environment(anonymous=anonymous),
        capture_output=True,
        text=True,
        check=check,
    )


def _clone(source: SourceKey, destination: Path, *, anonymous: bool) -> subprocess.CompletedProcess[str]:
    branch = ("--branch", source.ref) if source.ref is not None else ()
    return _git(
        "clone",
        *SHALLOW,
        *branch,
        "--quiet",
        source.url,
        str(destination),
        anonymous=anonymous,
        check=False,
    )


def _discard(destination: Path) -> None:
    """Take a failed clone's half-written directory away before trying again.

    git removes what it created when a clone fails, so this is usually a no-op.
    It is here because the one case where it is not - a directory left behind
    with objects in it - would make the second attempt fail for a reason that
    has nothing to do with credentials, and report the source as unreachable.

    Written out rather than `shutil.rmtree`: a `.git` directory on Windows holds
    read-only objects, so removing one needs a chmod per entry, and the hook
    parameter that would do it is spelled differently on each Python version
    this package supports.
    """
    if not destination.exists():
        return
    for child in sorted(destination.rglob("*"), key=lambda entry: len(entry.parts), reverse=True):
        child.chmod(WRITABLE)
        if child.is_dir():
            child.rmdir()
        else:
            child.unlink()
    destination.rmdir()


def _fetch(source: SourceKey, destination: Path) -> Privacy:
    """Clone the source, and report what cloning it turned out to need.

    Anonymously first. A source that clones that way is public, and that is the
    common case and the cheap one. A source that does not is tried again with
    the user's git as they configured it, and one that then succeeds needed
    credentials, which is the definition DESIGN.md section 8 uses.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    anonymous = _clone(source, destination, anonymous=True)
    if anonymous.returncode == 0:
        return Privacy.PUBLIC
    _discard(destination)
    credentialed = _clone(source, destination, anonymous=False)
    if credentialed.returncode == 0:
        return Privacy.PRIVATE
    _discard(destination)
    raise CacheError(
        source,
        f"this source could not be cloned from {source.url}",
        "Check the URL, and that you can clone it yourself:\n"
        f"    git clone {source.url}\n"
        f"  git said: {_said(credentialed)}",
    )


def _said(result: subprocess.CompletedProcess[str]) -> str:
    """git's own last word, which is the only thing that says what actually went wrong."""
    text = (result.stderr or result.stdout).strip()
    lines = [line for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else f"exit code {result.returncode}"


def _holds(destination: Path, commit: str) -> bool:
    """Whether the clone already has this commit, which decides whether anything is fetched."""
    found = _git("cat-file", "-e", f"{commit}^{{commit}}", cwd=destination, anonymous=True, check=False)
    return found.returncode == 0


def _deepen(source: SourceKey, destination: Path, commit: str) -> None:
    """Fetch one commit a shallow clone does not hold, and fall back to all of them.

    Fetching a commit by name is what most forges allow and what keeps this
    cheap. The ones that do not allow it fail the same way whatever you ask for,
    so the fall back is the whole history rather than a cleverer request.
    """
    by_name = _git("fetch", *SHALLOW, "--quiet", "origin", commit, cwd=destination, anonymous=True, check=False)
    if by_name.returncode == 0 and _holds(destination, commit):
        return
    everything = _git("fetch", "--unshallow", "--quiet", "origin", cwd=destination, anonymous=True, check=False)
    if everything.returncode != 0 or not _holds(destination, commit):
        raise CacheError(
            source,
            f"this source does not hold the commit it is pinned to, {commit}",
            "The commit may have been rewritten or force-pushed away. Run `akit update` to move the pin.",
        )


def _checkout(source: SourceKey, destination: Path, commit: str) -> None:
    if not _holds(destination, commit):
        _deepen(source, destination, commit)
    _git(
        "-c",
        "advice.detachedHead=false",
        "checkout",
        "--quiet",
        "--detach",
        commit,
        cwd=destination,
        anonymous=True,
    )


def _head(destination: Path) -> str:
    return _git("rev-parse", "HEAD", cwd=destination, anonymous=True).stdout.strip()


def _inside(source: SourceKey, directory: Path) -> Path:
    """The directory a subdirectory key selected, refused rather than silently empty."""
    if source.subdirectory is None:
        return directory
    chosen = directory.joinpath(*source.subdirectory.split("/"))
    if not chosen.is_dir():
        raise CacheError(
            source,
            f"the source has no `{source.subdirectory}` in it",
            "Check the directory in the URL, or name the repository alone and subscribe to the kit by name.",
        )
    return chosen


def _path_source(source: SourceKey, anchor: Path) -> Resolved:
    """A source that is already here: read where it is, with no clone and no pin."""
    directory = local_path(source, anchor=anchor)
    if not directory.is_dir():
        raise CacheError(
            source,
            f"there is no directory at {directory}",
            "A path source is read where it is. Check the path, or subscribe to the repository instead.",
        )
    return Resolved(source=source, root=_inside(source, directory), commit=None, privacy=None, fetched=False)


def resolve(
    source: SourceKey,
    *,
    pin: str | None = None,
    anchor: Path,
    cache_root: Path | None = None,
    offline: bool = False,
) -> Resolved:
    """One key, as a directory on this disk.

    `anchor` is the repository root a relative path key is read against, so that
    the same committed manifest means the same thing on every machine. `offline`
    is what a command that may not fetch passes: a source the cache already
    holds resolves, and one it does not fails saying which it was, rather than
    quietly producing less than yesterday.
    """
    if source.kind is SourceKind.PATH:
        return _path_source(source, anchor)

    destination = location(source, cache_root=cache_root)
    cached = (destination / ".git").exists()
    if cached and (pin is None or _holds(destination, pin)):
        if pin is not None:
            _checkout(source, destination, pin)
        return Resolved(
            source=source,
            root=_inside(source, destination),
            commit=_head(destination),
            privacy=None,
            fetched=False,
        )
    if offline:
        raise CacheError(
            source,
            "this source is not in the cache" if not cached else f"the cache does not hold the commit {pin}",
            "This command does not fetch. Run `akit add` or `akit update` for this source while online.",
        )
    privacy = None if cached else _fetch(source, destination)
    if pin is not None:
        _checkout(source, destination, pin)
    return Resolved(
        source=source,
        root=_inside(source, destination),
        commit=_head(destination),
        privacy=privacy,
        fetched=True,
    )


__all__ = [
    "CacheError",
    "Privacy",
    "Resolved",
    "location",
    "resolve",
    "root",
]
