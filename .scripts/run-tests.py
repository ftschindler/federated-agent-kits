#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""Run one marked layer of the test suite, on any operating system.

Usage:
  run-tests.py <marker> [extra pytest args...]

One code path for make, the pre-commit hooks and CI. The alternative is the same
`uv run --with ... pytest -m <marker>` line written three times, which is three
shell features in one: word splitting, a `$(...)` that `make` hands to `/bin/sh`,
and a hook wrapping the whole thing in `bash -c`. None of those exist on a
Windows shell, and this repository treats Windows as an equal target.

Two details are load-bearing and neither is obvious.

`--no-project` with `--with <repo root>`: the project is installed into the
throwaway environment rather than synced into a `.venv`, so no `uv.lock` of ours
is created. DESIGN.md section 9 refuses a lockfile, and an install is also what
makes `importlib.metadata.version` answer, which is where `akit --version` reads
from.

`PYTHONPATH=src` on top of that install: the source tree shadows the installed
copy, so coverage measures the files in the repository rather than an unrelated
path in a cache directory. The installed copy is still what supplies the package
metadata and the `akit` console script.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG = REPO_ROOT / "tests" / "pytest.toml"

#: The layer whose job it is to reach every line of `src/`. The others run the
#: same code through a subprocess, where coverage cannot see it, so gating them
#: on a percentage would be measuring the wrong thing.
COVERED = "unit"

#: pytest's "no tests were collected". A marker whose tests arrive in a later
#: task - `federation` and `agent` do - is an empty layer rather than a broken
#: one, and a CI job that fails because its tests do not exist yet would be a job
#: somebody switches off and forgets to switch back on.
#:
#: It is forgiven only when nothing was selected by hand. A run given a `-k` has
#: named something it expects to exist, and the CI matrix names one agent test
#: per job: forgiving an empty collection there would turn a renamed test into a
#: green job that ran nothing, which is the failure this whole file is careful
#: about elsewhere.
NOTHING_COLLECTED = 5

MARKERS = ("unit", "cli", "federation", "agent")

#: The layer that talks to a live model, and the only one whose failures are not
#: all about this repository: a session that produces nothing for ten minutes is
#: a provider having a bad afternoon, and it has failed runs on branches that
#: changed no Python at all. One retry, and only for that timeout - any other
#: failure is the agent doing the wrong thing, which is the layer's whole point
#: and must not be retried into a pass.
RETRIED = "agent"
RETRY = ("--reruns", "1", "--only-rerun", "OpencodeTimeoutError")


def command_for(marker: str, extra: list[str]) -> list[str]:
    coverage = [
        "--cov",
        "--cov-branch",
        f"--cov-config={REPO_ROOT / 'pyproject.toml'}",
        "--cov-report=term-missing",
    ]
    retries = ["--with", "pytest-rerunfailures"] if marker == RETRIED else []
    return [
        "uv",
        "run",
        "--no-project",
        "--with",
        "pytest",
        "--with",
        "pytest-cov",
        *retries,
        "--with",
        str(REPO_ROOT),
        "pytest",
        "-c",
        str(CONFIG),
        "--rootdir",
        str(REPO_ROOT),
        "-m",
        marker,
        *(coverage if marker == COVERED else []),
        *(RETRY if marker == RETRIED else ()),
        "-v",
        *extra,
    ]


def main() -> int:
    if not sys.argv[1:]:
        sys.exit(f"usage: run-tests.py <{'|'.join(MARKERS)}> [pytest args...]")
    marker, *extra = sys.argv[1:]
    if marker not in MARKERS:
        sys.exit(f"run-tests: {marker!r} is not one of {', '.join(MARKERS)}")
    command = command_for(marker, extra)
    print(" ".join(command), file=sys.stderr)
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(REPO_ROOT / "src")
    result = subprocess.run(command, cwd=REPO_ROOT, check=False, env=environment)
    if result.returncode == NOTHING_COLLECTED and not extra:
        print(f"run-tests: no tests are marked {marker!r} yet.", file=sys.stderr)
        return 0
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
