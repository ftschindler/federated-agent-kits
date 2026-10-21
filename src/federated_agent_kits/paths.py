"""What a path means when this tool writes it down, which is never where it leads.

Two questions, asked everywhere a file is claimed as ours, and separated from
both the record and the renderer because discovery asks the first one too.

**A path is tidied, not resolved.** `Path.resolve` answers where a path leads,
and that is the wrong question about a file we are about to call our property.
`~/.agents/skills/fkb` pointing into a dotfiles checkout is an ordinary
arrangement somebody made years before `akit` existed; resolving a target
through it records their working tree as ours, and the next withdrawal deletes
the files in it. That happened, and it is why `located` exists rather than a
call to `resolve` with a comment beside it.

An ancestor that is a link is still followed when the bytes are written, and
deliberately: a home directory arranged out of a checkout is the user's own
arrangement and not ours to refuse. What is refused is a link at the leaf, where
the directory or file is the one `akit` claims (DESIGN.md section 6).

**A path belongs to a root, or it does not.** Every target is built by joining
names onto a scope root (`Adapter.target`), so a tidied path is under that root
by construction, and `under` is how a record says so out loud about entries it
did not write this run.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path


def located(path: Path) -> Path:
    """One path, absolute and with `.` and `..` taken out, by text alone.

    `Path.absolute` makes it absolute without asking the filesystem anything,
    and `normpath` tidies the result the same way. Between them they are the
    wanted half of `resolve`: a link on the way stays a link, and the name
    written down is the name somebody would type.

    Spelled in two calls rather than as `os.path.abspath`, which is the same
    thing, because the lint rule for that one offers `Path.resolve` as the
    replacement. Taking it would restore the bug this module exists to prevent.
    """
    return Path(os.path.normpath(path.absolute()))


def under(path: Path, roots: Iterable[Path]) -> bool:
    """Whether this path is somewhere the thing holding it answers for.

    No roots at all means every path qualifies, which is what a reader passes.
    A reader subtracts what it is told and deletes nothing, so narrowing it
    would hide entries from a question that is safe either way. A writer passes
    its roots and gets the narrowing.
    """
    listed = tuple(roots)
    return not listed or any(path == root or path.is_relative_to(root) for root in listed)


__all__ = ["located", "under"]
