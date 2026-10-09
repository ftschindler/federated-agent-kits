#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""The version, and the four things the release pipeline does to it.

  version.py current                 # what shipped last
  version.py next <level>            # what a major, minor or patch would make it
  version.py dev <level> <serial>    # the same, as a throwaway rehearsal version
  version.py write <version>         # put it in pyproject.toml
  version.py check-untouched <base>  # refuse a pull request that edited it

Its own file rather than a few lines of `sed` in a workflow, for the reason the
test invocation is its own file: what the release does should be runnable, and
readable, without a CI run to see it. `uv run .scripts/version.py next minor`
answers the question on a laptop.

The bump level comes from a label on the pull request, which is the one place a
human already looks at the change as a whole. Reading it from commit messages was
the alternative and is rejected: the subjects here are sentences about the work,
and turning those into a machine's opinion about severity means writing them for
the machine instead.

The version is a single line in `pyproject.toml` rather than a file of its own,
because the package is the unit that ships (DESIGN.md section 9) and
`akit --version` reads it back out of the installed metadata. Two places to write
it would be two places to forget.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

LEVELS = ("major", "minor", "patch")
SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
#: What may be written into `pyproject.toml`: a release, or a release with a dev
#: segment behind it. The dev segment is numeric because PEP 440 says so, and
#: because the obvious thing to put there instead - a commit sha - is not a
#: number. The other obvious spelling, `0.2.1+g6ec3cb1`, parses fine and is
#: refused by both indexes: warehouse forbids local versions outright.
WRITABLE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(\.dev\d+)?$")
#: Anchored to the start of a line and to the `[project]` spelling, so a
#: `requires-python` or a dependency specifier carrying a version is not matched.
VERSION_LINE = re.compile(r'^version = "(?P<version>[^"]+)"$', re.MULTILINE)

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"
#: The one place other than `pyproject.toml` that carries the number, and not a
#: second source of truth: a skill copied into somebody's skills directory keeps
#: no link to the package it describes, so a file beside it is the only way it
#: can say how old it is. It is written here, from the same number, in the same
#: commit, which is what keeps the two from disagreeing.
SKILL_VERSION = REPO_ROOT / "skills" / "akit" / "VERSION"


def read_version(text: str) -> str:
    match = VERSION_LINE.search(text)
    if not match:
        sys.exit('version: no `version = "..."` line in pyproject.toml')
    return match.group("version")


def dev_version(current: str, level: str, serial: str) -> str:
    """The version this change would release, marked as a rehearsal of it.

    The serial is a run id rather than a commit sha, and not by preference. An
    index accepts a given version exactly once and never again, even after a
    deletion, so re-running a workflow on the same commit has to produce a
    different string - which a sha does not, and a run id does.
    """
    if not serial.isdigit():
        sys.exit(f"version: {serial!r} is not a number, and a dev segment has to be one")
    return f"{next_version(current, level)}.dev{serial}"


def replace_version(text: str, new: str) -> str:
    if not WRITABLE.match(new):
        sys.exit(f"version: {new!r} is not a version of the form 1.2.3 or 1.2.3.dev4")
    replaced, count = VERSION_LINE.subn(f'version = "{new}"', text, count=1)
    if count != 1:
        sys.exit('version: no `version = "..."` line in pyproject.toml')
    return replaced


def next_version(current: str, level: str) -> str:
    match = SEMVER.match(current.strip())
    if not match:
        sys.exit(f"version: {current!r} is not a version of the form 1.2.3")
    major, minor, patch = (int(part) for part in match.groups())
    if level == "major":
        # Zero the ones beneath, always: 0.4.2 major is 1.0.0, never 1.4.2. The
        # mistake is invisible in the tag and permanent in the history.
        return f"{major + 1}.0.0"
    if level == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def write_skill_version(new: str) -> None:
    """Put `new` in the skill's VERSION file, which ships inside the skill itself.

    Written whole rather than edited, because the file holds one line and
    nothing else. A rehearsal version is written here too: a dev build whose
    skill claims the release it rehearses would be a copy on disk that cannot be
    told from the real one.
    """
    SKILL_VERSION.write_text(f"{new}\n", encoding="utf-8")


def version_changed(base: str, head: str = "HEAD") -> bool:
    """Whether the diff from `base` *rewrites* the version line.

    The whole file is not off limits - a pull request may add a classifier or a
    dependency - so the question is about the one line the release job owns,
    which means reading the diff rather than the file list.

    A removed line is what makes it a rewrite. An added one with nothing removed
    is the version arriving in a repository that has none, which happens exactly
    once, in the pull request that creates `pyproject.toml`. Carving that out as
    a named exception would leave a rule that has to be remembered, in a check
    whose whole job is to be remembered for you: afterwards the line exists on
    the base branch, so every further write to it removes something and is
    refused.
    """
    diff = subprocess.run(
        ["git", "diff", "--unified=0", f"{base}...{head}", "--", str(PYPROJECT)],
        capture_output=True,
        text=True,
        check=True,
        cwd=str(REPO_ROOT),
    ).stdout
    return any(re.match(r"^-version = \"", line) for line in diff.splitlines())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("current", help="print the version in pyproject.toml")
    following = sub.add_parser("next", help="print what the next version would be")
    following.add_argument("level", choices=LEVELS)
    rehearsal = sub.add_parser("dev", help="print a throwaway version for a rehearsal upload")
    rehearsal.add_argument("level", choices=LEVELS)
    rehearsal.add_argument("serial", help="a number unique to this run, such as a run id")
    write = sub.add_parser("write", help="write a version into pyproject.toml")
    write.add_argument("version")
    check = sub.add_parser("check-untouched", help="fail if the diff from <base> edits the version")
    check.add_argument("base")
    arguments = parser.parse_args(argv)

    text = PYPROJECT.read_text(encoding="utf-8")
    if arguments.action == "current":
        print(read_version(text))
        return 0
    if arguments.action == "next":
        print(next_version(read_version(text), arguments.level))
        return 0
    if arguments.action == "dev":
        print(dev_version(read_version(text), arguments.level, arguments.serial))
        return 0
    if arguments.action == "write":
        PYPROJECT.write_text(replace_version(text, arguments.version), encoding="utf-8")
        write_skill_version(arguments.version)
        print(f"pyproject.toml now says {arguments.version}, and so does the skill's VERSION.")
        return 0
    if version_changed(arguments.base):
        print(
            "::error::pyproject.toml's version is written by the release job. "
            "Label this pull request major, minor, patch or no-release instead.",
            file=sys.stderr,
        )
        return 1
    print("The version line is untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
