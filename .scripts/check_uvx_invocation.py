#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""Fail if any tracked file contains a copyable invocation of `akit` through uvx
that does not name the distribution.

uvx reads its first argument as a distribution to resolve and infers the command
from it. The distribution here is `federated-agent-kits` and the command inside
it is `akit`, so naming only the command asks PyPI for a project of that name,
which exists and belongs to somebody else. The correct spelling is:

    uvx --from federated-agent-kits akit render

This is a guard rather than a convention because the wrong form reads perfectly.
It was in the README, in DESIGN.md and in IMPLEMENTATION.md from the day they
were written, survived every review, and was only found by somebody running it,
which answers that the package provides no executables. That the unrelated
project ships no console script today is luck, and one release by its owner away
from this repository's README executing a stranger's code.

**The rule is literal and has no opt-out**, which is a deliberate second choice.
The first attempt treated a fenced block as an instruction and an inline code
span as a mention, so that a document could discuss the mistake. It passed on
the very sentence that caused this: DESIGN.md said the wrong form "works in a
clone with nothing installed first", inline, which is a promise a reader acts on
rather than a mention. There is no reliable way to tell a warning from a claim by
looking at the markup, so instead the sequence simply never appears, and the
three passages explaining the mistake say "naming only the command" rather than
spelling it. The exemptions are this file, its test, and `JOURNAL.md`, which have
to contain the form in order to catch it, prove it is caught, and record what
happened. None of them instructs anybody to run anything.

Asks git rather than walking the tree, so it reports what would be committed,
which is what a reader copies out of a rendered README.
"""

from __future__ import annotations

import re
import subprocess
import sys

#: uvx, then any run of flags, then the command as a whole word. The flags are
#: captured rather than skipped so the correct spelling can be let through:
#: `--from` is separated from the command by its value and possibly by further
#: flags, so the pattern has to span the whole run and judge it as a group. The
#: optional value in each flag backtracks, which is what stops `--quiet` from
#: swallowing the command name and hiding the match.
BARE_INVOCATION = re.compile(r"uvx(?P<flags>(?:\s+-{1,2}[^\s]+(?:[=\s]+[^\s]+)?)*)\s+akit\b")

#: The three files that have to contain the wrong form in order to do their job:
#: this guard, the test that proves it catches one, and the journal, which
#: records what happened and quotes the sentence that caused it. Named outright
#: rather than matched by a pattern, so the list cannot quietly grow, and no
#: document that instructs anybody is on it.
EXEMPT = (
    ".scripts/check_uvx_invocation.py",
    "tests/test_support_scripts.py",
    "JOURNAL.md",
)

SUGGESTION = "uvx --from federated-agent-kits akit"


def offences(text: str) -> list[int]:
    """The line numbers invoking the command through uvx without the distribution."""
    found = []
    for number, line in enumerate(text.splitlines(), start=1):
        match = BARE_INVOCATION.search(line)
        if match is not None and "--from" not in match.group("flags"):
            found.append(number)
    return found


def tracked_files() -> list[str]:
    listed = subprocess.run(["git", "ls-files", "-z"], capture_output=True, text=True, check=False)
    if listed.returncode != 0:
        print(f"check_uvx_invocation: `git ls-files` failed\n{listed.stderr}", file=sys.stderr)
        raise SystemExit(1)
    return [path for path in listed.stdout.split("\0") if path]


def committed_text(path: str) -> str | None:
    """The indexed content of one file, or `None` if it is not text.

    The index rather than the working tree: this runs as a pre-commit hook, and
    what a reader eventually copies is what was committed.
    """
    shown = subprocess.run(["git", "show", f":{path}"], capture_output=True, check=False)
    try:
        return shown.stdout.decode("utf-8")
    except UnicodeDecodeError:  # a binary file carries no instruction for a reader
        return None


def main() -> int:
    offenders: list[tuple[str, int]] = []
    for path in tracked_files():
        if path in EXEMPT:
            continue
        text = committed_text(path)
        if text is not None:
            offenders.extend((path, number) for number in offences(text))

    if not offenders:
        return 0

    print("uvx resolves its first argument as a distribution, and that name is not ours.")
    for path, number in offenders:
        print(f"  {path}:{number}")
    print(f"\nWrite `{SUGGESTION}` instead. If you are explaining the mistake rather")
    print("than instructing somebody to make it, say so without spelling it out.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
