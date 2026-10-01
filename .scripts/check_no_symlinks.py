#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""Fail if any tracked file is a symlink.

A symlink is stored as a mode-120000 blob whose content is the target path. Git
on Windows writes that content out as an ordinary file unless the clone has
`core.symlinks` enabled, which needs developer mode or an elevated shell; the
default is off. The link does not break loudly - it becomes a one-line text file
holding something like `../../JOURNAL.md`, and every reader downstream gets that
string as the document.

This repo had exactly one (`skills/fkb/JOURNAL.md`, the journal placed beside the
skill that is being developed). It is a guard rather than a preference because
the failure is invisible on the machine that introduces it: a contributor on
Linux sees a working link and a green suite, and the damage only appears in
somebody else's clone.

Asks git rather than the filesystem, so it reports what would be *committed* -
which is the thing that travels, and the thing a Windows clone reads.
"""

from __future__ import annotations

import subprocess
import sys

SYMLINK_MODE = "120000"


def main() -> int:
    listed = subprocess.run(
        ["git", "ls-files", "--stage", "-z"],
        capture_output=True,
        text=True,
        check=False,
    )
    if listed.returncode != 0:
        print(f"check_no_symlinks: `git ls-files` failed\n{listed.stderr}", file=sys.stderr)
        return 1

    offenders = []
    for record in listed.stdout.split("\0"):
        if not record:
            continue
        # `<mode> <object> <stage>\t<path>`
        meta, _, path = record.partition("\t")
        if meta.split(" ", maxsplit=1)[0] == SYMLINK_MODE:
            offenders.append(path)

    if not offenders:
        return 0

    print("Symlinks are committed, which a Windows clone turns into text files:")
    for path in offenders:
        print(f"  {path}")
    print(
        "\nCommit a real file, or leave the path untracked and let each developer\n"
        "place their own copy (see CONTRIBUTING.md > Working on Windows)."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
