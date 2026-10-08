"""How public the repository being written into is, worked out from its remotes.

The other half of DESIGN.md section 8. A *source* is private when cloning it
needed credentials, which `cache.py` learns while fetching. A *target* is the
repository a render writes into, and it is classified here, by asking its
remotes who is allowed to read them.

**The same two probes, for the same reason.** `git ls-remote` with the
credential helpers off and no prompt answers for a remote anybody can read, and
fails for every other kind. The same call with this machine's git configured as
the user configured it then answers for a remote they have access to. So a
remote that answers anonymously is public, a remote that answers only with
credentials is private, and a remote that answers neither way cannot be reached.
Reading git's error text instead would make a refusal depend on the wording of a
message that is not ours and changes between versions.

**A repository with no remote at all is private**, because nothing can leave it.

**Only the unreachable case is refused**, and it is a failure to classify rather
than a classification. The repository may be either and a network that is down
is not evidence about who can read it, so the answer is to try again rather than
to guess. That is the transient refusal DESIGN.md section 8 names; the other one
is the leak itself and lives in `leaks.py`.

**Nothing here is remembered between runs.** A repository made public last week
with a cached "private" beside it is a refusal that silently stops happening,
which is the failure the section exists for. The cost is one or two `ls-remote`
calls, and only in a repository that actually commits a private kit.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from federated_agent_kits import cache
from federated_agent_kits.exits import RefusalError

#: How long one probe may take before the remote counts as unreachable. A
#: render runs from a git hook, so a remote that is simply not answering has to
#: fail rather than hang: the alternative is somebody's commit blocked on a DNS
#: timeout with no output. Generous enough for a slow forge on a slow link.
TIMEOUT = 30

#: Every config key a remote's URL can be written under, which is how they are
#: listed without parsing `git remote -v`'s two-lines-per-remote output. It ends
#: in `url` rather than `\.url` so that `remote.origin.pushurl` is included: a
#: kit committed here reaches whoever can read the place it is pushed to, and a
#: repository that fetches from a mirror and pushes to the real thing would
#: otherwise be classified on the wrong one.
URLS = r"^remote\..*url$"


class Publicity(StrEnum):
    """Who can read the repository being rendered into.

    Two states, like `cache.Privacy`, and for the same reason: the rule in
    DESIGN.md section 8 has two sides and no third. Not reusing that enum keeps
    the two halves of a refusal message from being the same word, since "this
    private source may not go into this private target" is not a sentence
    anybody should be able to write by passing the wrong argument.
    """

    PUBLIC = "public"
    PRIVATE = "private"


class UnreachableTargetError(RefusalError):
    """Every remote this repository has declined to answer, so it cannot be judged."""

    def __init__(self, root: Path, remotes: tuple[str, ...]) -> None:
        listed = "\n".join(f"    {url}" for url in remotes)
        super().__init__(
            f"cannot tell whether {root} is public, because none of its remotes answered:\n"
            f"{listed}\n"
            "  This repository commits rendered kits, so a private kit cannot be written into it "
            "until that question has an answer.\n"
            "  Nothing was written. Check the network and run the same command again."
        )


@dataclass(frozen=True)
class Target:
    """One repository, and who turned out to be able to read it."""

    root: Path
    publicity: Publicity
    remotes: tuple[str, ...]

    @property
    def is_public(self) -> bool:
        return self.publicity is Publicity.PUBLIC


def tracked(path: Path, *, root: Path) -> bool:
    """Whether git has this file, which is what "committed" means for a check.

    DESIGN.md section 6 forbids an escaping path in a *committed* manifest, and
    that word is load-bearing. A `.akit.yaml` git does not track breaks nobody
    else's clone, because nobody else has it: a scratch repository, a kit being
    written, a fixture. The moment it is added, the same file means something
    only on the machine it was written on, and that is what gets refused.

    `ls-files --error-unmatch` answers with an exit code rather than with output
    that would have to be matched against a path spelled two ways on two
    platforms.
    """
    found = cache.git("ls-files", "--error-unmatch", "--", str(path), cwd=root, anonymous=False, check=False)
    return found.returncode == 0


def remotes(root: Path) -> tuple[str, ...]:
    """Every URL this repository pushes to or fetches from, in config order.

    One URL may appear twice, under `remote.origin.url` and
    `remote.origin.pushurl`, and a repository may have several remotes. All of
    them count: a kit committed here reaches whoever can read any one of them.
    """
    found = cache.git("config", "--get-regexp", URLS, cwd=root, anonymous=False, check=False)
    urls: list[str] = []
    for line in found.stdout.splitlines():
        _, _, url = line.partition(" ")
        if url.strip() and url.strip() not in urls:
            urls.append(url.strip())
    return tuple(urls)


def _answers(url: str, *, anonymous: bool) -> bool:
    """Whether `ls-remote` gets a reply, which is the whole of the test.

    `--exit-code` is deliberately not passed: an empty repository answers with
    no refs and is still a repository somebody can read, and treating that as a
    failure would classify a brand-new public repository as unreachable.
    """
    try:
        found = cache.git("ls-remote", "--quiet", url, anonymous=anonymous, check=False, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return False
    return found.returncode == 0


def classify(root: Path) -> Target:
    """Who can read this repository, or a refusal when nothing will say.

    Anonymously across every remote first, because one readable remote makes the
    repository readable and there is no point asking the rest. Only then with
    credentials, which costs a second round trip on a private repository and
    nothing on a public one.
    """
    urls = remotes(root)
    if not urls:
        return Target(root=root, publicity=Publicity.PRIVATE, remotes=())
    if any(_answers(url, anonymous=True) for url in urls):
        return Target(root=root, publicity=Publicity.PUBLIC, remotes=urls)
    if any(_answers(url, anonymous=False) for url in urls):
        return Target(root=root, publicity=Publicity.PRIVATE, remotes=urls)
    raise UnreachableTargetError(root, urls)


__all__ = ["TIMEOUT", "Publicity", "Target", "UnreachableTargetError", "classify", "remotes", "tracked"]
