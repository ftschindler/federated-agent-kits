"""A pull request URL, turned into the branch it would merge and where it would merge it.

Git cannot answer this. `ls-remote` says what `refs/pull/16/head` points at and
nothing about the branch behind it, the repository that branch lives in, or the
branch it is meant to land on. Those are the forge's facts, so this is the one
module that asks a forge rather than a remote
([ftschindler/agent-kits#16](https://github.com/ftschindler/agent-kits/issues/16)).

**It is asked once, by a person, and never again.** `akit discover` and `akit
add` are typed by somebody who pasted the URL, and whatever `gh` or a token on
their machine can see is what they can see. What comes back is written into the
manifest as ordinary keys - the branch, its target, and the pull request's
name - so `render`, `list`, `update` and a CI check afterwards are git and
nothing else (DESIGN.md section 6, "A pull request is a branch with somewhere
to go").

**GitHub only.** A GitLab merge request is refused when its URL is parsed,
with the branch-shaped URL to use instead, because a half-supported forge is
worse than a sentence saying which one is.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from federated_agent_kits.exits import AkitError
from federated_agent_kits.sources import DEFAULT_FORGE, SourceKey, at_branch

#: The environment variables a GitHub token is conventionally found in, in the
#: order `gh` itself reads them.
TOKENS = ("GH_TOKEN", "GITHUB_TOKEN")

#: How long the forge gets to answer. A person is waiting at a prompt.
TIMEOUT = 20


class ForgeError(AkitError):
    """A pull request that could not be turned into a branch, and what to type instead."""

    def __init__(self, source: SourceKey, problem: str) -> None:
        self.source = source
        number = source.pull
        super().__init__(
            f"{source.raw}: {problem}\n"
            f"  Follow its branch instead, as `{source.url}/tree/<branch>`, or take its head without following it:\n"
            f"    '{source.url}#refs/pull/{number}/head'"
        )


@dataclass(frozen=True)
class PullRequest:
    """What a subscription to a pull request needs to know, and nothing else."""

    name: str
    """`owner/repo#16`, which is what a person calls it and what the manifest records."""

    head: str
    """The source key that follows its branch, in the repository the branch lives in."""

    target: str
    """The source key for the branch it merges into: where `update` goes once it has."""

    merged: bool
    open: bool


def _api(host: str) -> str:
    """Where the REST API of a GitHub host is: its own subdomain on github.com, a path elsewhere."""
    return "https://api.github.com" if host == DEFAULT_FORGE else f"https://{host}/api/v3"


def _with_gh(host: str, path: str) -> dict[str, Any] | None:
    """`gh api`, which knows whatever the person is signed into. `None` where it cannot say."""
    if shutil.which("gh") is None:
        return None
    found = subprocess.run(
        ["gh", "api", "--hostname", host, path],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        timeout=TIMEOUT,
    )
    if found.returncode != 0:
        return None
    answer: dict[str, Any] = json.loads(found.stdout)
    return answer


def _over_https(host: str, path: str) -> dict[str, Any] | None:
    """The same question over plain HTTPS, with a token if one is in the environment."""
    request = urllib.request.Request(f"{_api(host)}/{path}", headers={"Accept": "application/vnd.github+json"})
    token = next((os.environ[name] for name in TOKENS if os.environ.get(name)), None)
    if token is not None:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            answer: dict[str, Any] = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError):
        return None
    return answer


def ask(host: str, path: str) -> dict[str, Any] | None:
    """One GitHub API call, through `gh` if it can answer and over HTTPS if not."""
    return _with_gh(host, path) or _over_https(host, path)


def pull_request(source: SourceKey) -> PullRequest:
    """The pull request a `/pull/<n>` key names, as the two keys a subscription follows."""
    host = urlsplit(source.url).netloc
    repository = urlsplit(source.url).path.strip("/")
    answer = ask(host, f"repos/{repository}/pulls/{source.pull}")
    if answer is None:
        raise ForgeError(source, f"{host} could not be asked about pull request #{source.pull}")
    head, base = answer.get("head") or {}, answer.get("base") or {}
    lives_in = (head.get("repo") or {}).get("html_url")
    if lives_in is None:
        raise ForgeError(source, "the repository its branch lived in has been deleted")
    return PullRequest(
        name=f"{repository}#{source.pull}",
        head=at_branch(lives_in, str(head["ref"])),
        target=at_branch(str(base["repo"]["html_url"]), str(base["ref"])),
        merged=bool(answer.get("merged")),
        open=answer.get("state") == "open",
    )


__all__ = ["ForgeError", "PullRequest", "ask", "pull_request"]
