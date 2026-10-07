"""An environment for running `git` in, with the repository it was started from taken out.

`git` tells its hooks where the repository is by putting it in the environment:
`GIT_DIR`, `GIT_INDEX_FILE`, `GIT_WORK_TREE` and friends are exported for the
duration of a hook and inherited by everything it starts. A suite run from a
pre-commit hook therefore begins inside somebody's commit, and every `git`
command it issues without thinking about it operates on **this** repository
rather than on the throwaway one the test just built.

The symptom is not a failure, which is what makes it worth a module. A test that
commits into a temporary repository succeeds, and the commit lands in the
developer's own history. In the sibling project this was found as three commits
by a fixture's author on a working branch, and a file staged out of a test
fixture.

So every `git` this suite runs, directly or through `akit`, is handed an
environment with the whole `GIT_` namespace removed. Wholesale rather than by a
list of the variables known to cause it: the list is long, git is free to add to
it, and nothing this suite runs wants a `GIT_` variable it did not set itself.

Ported from `federated-knowledge-skills`, which is where it was paid for.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

GIT_PREFIX = "GIT_"

#: A committer nobody has to be. Passed as `-c` flags rather than written into a
#: config file, so a fixture repository needs no `git config` of its own and the
#: developer's identity is never consulted.
FIXED_AUTHOR: tuple[str, ...] = (
    "-c",
    "user.email=akit-tests@invalid",
    "-c",
    "user.name=akit tests",
    "-c",
    "commit.gpgsign=false",
)

#: Everything that would make git reach outside the test: a credential helper
#: that could answer a prompt, a prompt at all, or the developer's own config.
NO_OUTSIDE_WORLD: dict[str, str] = {
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_ASKPASS": "",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
}


def without_git_variables(env: Mapping[str, str]) -> dict[str, str]:
    """The given environment with the `GIT_` namespace taken out."""
    return {key: value for key, value in env.items() if not key.startswith(GIT_PREFIX)}


def outside_any_repository(**overrides: str) -> dict[str, str]:
    """The current environment, minus every `GIT_` variable, plus what is passed.

    The rest of the environment is carried rather than built from scratch: a
    hand-built environment listing `PATH` and `HOME` is enough on Linux and not
    on Windows, where git needs `SYSTEMROOT` to resolve anything at all.

    Overrides are applied after the scrub, so a caller that means to set a `GIT_`
    variable still can. Setting one deliberately is the opposite of inheriting it
    by accident.
    """
    return {**without_git_variables(os.environ), **NO_OUTSIDE_WORLD, **overrides}


def git(*args: str, cwd: Path | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Run git with the outer repository and the developer's identity taken out."""
    return subprocess.run(
        ["git", *args],
        cwd=None if cwd is None else str(cwd),
        env=outside_any_repository() if env is None else env,
        capture_output=True,
        text=True,
        check=True,
    )


def local_remote(path: Path, layout: Mapping[str, str]) -> str:
    """A real git repository on disk, to be cloned over a `file:` URL.

    Cloning is mostly mechanics, and mechanics do not need somebody else's
    server. What a real remote is for is repository shapes nobody here controls,
    which is a different test and a different marker.
    """
    path.mkdir(parents=True, exist_ok=True)
    for relative, text in layout.items():
        target = path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    git("init", "-q", "-b", "main", str(path))
    git("-C", str(path), "add", "-A")
    git("-C", str(path), *FIXED_AUTHOR, "commit", "-qm", "initial")
    # `Path.as_uri()` rather than an f-string: a Windows path pasted after
    # `file://` yields `file://C:\\...`, which git reads as a host named `c`.
    return path.as_uri()
