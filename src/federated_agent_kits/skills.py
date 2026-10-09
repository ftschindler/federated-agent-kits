"""Skills: copied unchanged, except the one key that says which skill this is.

A skill is a directory, and a render copies it whole. That is the whole of
DESIGN.md section 7 for this kind, and it was the whole of this module until
`as:` had to mean something.

**The directory is not the identity.** Copilot in VS Code takes the frontmatter
`name` as the identifier and declines to load a skill whose `name` disagrees
with its directory. opencode and pi both key on the frontmatter name, pi falling
back to the directory only where there is none. So renaming the directory and
leaving `name: writing` in the file produced, depending on the harness, a skill
that silently stopped loading or the very collision `as:` had been invoked to
prevent - with a directory listing that looked correct either way.

So a renamed skill has its identity written over, exactly as a Copilot rule has
its `applyTo` written over, and for the same reason: a key that decides which
file this is, or whether it loads at all, is not a preference the author gets to
keep (DESIGN.md section 7).

**Everything else survives**, in the author's order, with the author's comments,
because only one key is assigned and the rest of the mapping is untouched.

**A skill nobody renamed is still copied byte for byte.** The rewrite is reached
only when the rendered name differs from the name in the source, which keeps the
ordinary render exactly as literal as it has always been.
"""

from __future__ import annotations

from federated_agent_kits import frontmatter
from federated_agent_kits.exits import AkitError
from federated_agent_kits.frontmatter import FENCE

#: The file that makes a directory a skill, and the only one in it this module
#: ever reads. A skill's other files are prose and scripts the author owns, and
#: its references are addressed relative to the directory, so a rename reaches
#: none of them.
MANIFEST_FILE = "SKILL.md"

#: The frontmatter key carrying a skill's identity.
NAME = "name"


class SkillError(AkitError):
    """A skill this build will not render, named with what to do about it."""


def as_copied(data: bytes, *, name: str) -> bytes:
    """One `SKILL.md`, with its identity set to the name it is rendered under.

    A file with no frontmatter at all is returned untouched rather than given a
    header. Such a skill is already one that opencode skips and Copilot will not
    load, rename or no rename, and pi is the one harness that reads it - by
    falling back to the directory name, which a rename has already changed. So
    there is nothing here a header would fix, and writing one would edit a
    document whose shape the author chose.
    """
    try:
        document = frontmatter.parse(data)
    except frontmatter.FrontmatterError as error:
        raise SkillError(
            f'the skill "{name}" opens with frontmatter that is {error.summary}.\n  {error.fix}'
        ) from error
    if document.front is None:
        return data
    front = document.front
    front[NAME] = name
    return f"{FENCE}\n{frontmatter.dump(front)}{FENCE}\n\n{document.body}".encode()
