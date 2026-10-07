"""The `.gitignore` block a render maintains, in a file the repository owns.

Everything `akit render` writes for a harness that runs on your laptop is
generated and disposable, so it is ignored rather than committed, and forgetting
one line is how a rendered kit ends up in somebody's history (DESIGN.md section
6). Maintaining that list by hand is the thing that would be forgotten, so the
block is computed from what the render actually wrote and rewritten whole every
time.

**Everything outside the markers survives, in its own order.** This is a file a
person owns and mostly wrote, which is the same treatment the third rule shape
gets in DESIGN.md section 7.

**A line the user already wrote is left where it is and duplicated inside the
block.** git does not mind an entry twice, and the alternative is this code
deciding that somebody's `*.md` covers `.agents/skills/`, getting it wrong, and
leaving a directory unignored. Duplicating costs a line; removing ours stays
safe either way.

**An empty block is no block.** A repository that renders nothing gets its
markers taken out rather than left as a pair of comments around nothing, so a
repository that stops using this tool ends up with the `.gitignore` it had.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

GITIGNORE = ".gitignore"
BEGIN = "# BEGIN akit"
END = "# END akit"


def block(directories: Iterable[str]) -> list[str]:
    """The marker block for these directories, or nothing at all for none of them."""
    listed = sorted(set(directories))
    if not listed:
        return []
    return [BEGIN, *listed, END]


def rewrite(text: str, directories: Iterable[str]) -> str:
    """The same file with our block replaced by this one, and nothing else touched.

    The block goes back where it was if it was there, and at the end if it was
    not, because a person who moved it meant to.
    """
    lines = text.split("\n")
    trailing = lines and lines[-1] == ""
    if trailing:
        lines = lines[:-1]
    replacement = block(directories)
    kept: list[str] = []
    placed = False
    inside = False
    for line in lines:
        if line.strip() == BEGIN:
            inside = True
            kept.extend(replacement)
            placed = True
        elif inside:
            if line.strip() == END:
                inside = False
        else:
            kept.append(line)
    if not placed and replacement:
        if kept and kept[-1].strip():
            kept.append("")
        kept.extend(replacement)
    while kept and not kept[-1].strip():
        kept.pop()
    if not kept:
        return ""
    return "\n".join(kept) + "\n"


def maintain(root: Path, directories: Iterable[str]) -> bool:
    """Put the block in this repository's `.gitignore`, and say whether anything changed.

    A repository with nothing to ignore and no `.gitignore` gets no file,
    because the one a render would create would be empty and an empty file
    written by a tool is noise somebody has to work out the meaning of. That
    falls out of the comparison rather than needing a branch: an absent file
    reads as nothing, and nothing is what an empty block rewrites to.
    """
    path = root / GITIGNORE
    before = path.read_text(encoding="utf-8").replace("\r\n", "\n") if path.is_file() else ""
    after = rewrite(before, directories)
    if after == before:
        return False
    path.write_text(after, encoding="utf-8", newline="\n")
    return True


__all__ = ["BEGIN", "END", "GITIGNORE", "block", "maintain", "rewrite"]
