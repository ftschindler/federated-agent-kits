#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""The version, and the four things the release pipeline does to it.

  version.py current                 # what shipped last
  version.py next <level>            # what a major, minor or patch would make it
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
#: Anchored to the start of a line and to the `[project]` spelling, so a
#: `requires-python` or a dependency specifier carrying a version is not matched.
VERSION_LINE = re.compile(r'^version = "(?P<version>[^"]+)"$', re.MULTILINE)

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"


def read_version(text: str) -> str:
    match = VERSION_LINE.search(text)
    if not match:
        sys.exit('version: no `version = "..."` line in pyproject.toml')
    return match.group("version")


def replace_version(text: str, new: str) -> str:
    if not SEMVER.match(new):
        sys.exit(f"version: {new!r} is not a version of the form 1.2.3")
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


def version_changed(base: str, head: str = "HEAD") -> bool:
    """Whether the diff from `base` touches the version line.

    The whole file is not off limits - a pull request may add a classifier or a
    dependency - so the question is about the one line the release job owns,
    which means reading the diff rather than the file list.
    """
    diff = subprocess.run(
        ["git", "diff", "--unified=0", f"{base}...{head}", "--", str(PYPROJECT)],
        capture_output=True,
        text=True,
        check=True,
        cwd=str(REPO_ROOT),
    ).stdout
    changed = [line for line in diff.splitlines() if re.match(r"^[+-]version = \"", line)]
    return bool(changed)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("current", help="print the version in pyproject.toml")
    following = sub.add_parser("next", help="print what the next version would be")
    following.add_argument("level", choices=LEVELS)
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
    if arguments.action == "write":
        PYPROJECT.write_text(replace_version(text, arguments.version), encoding="utf-8")
        print(f"pyproject.toml now says {arguments.version}.")
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
