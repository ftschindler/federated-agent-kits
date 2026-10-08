"""The refusal that keeps the employer's kits in, both halves of it.

DESIGN.md section 8. **A private source's parts do not render into a public
target, and a private source is not named in a public target's committed
manifest.** No override, no `--force`, exit code 3, and a message naming the
source, the target and the command that undoes it.

**It is per harness and per spot, not per repository.** A repository may render
to five harnesses and commit the output of one. So what this asks of every file
a render plans to write is whether that file ends up committed, and it asks it
of the file rather than of the harness that wanted it: skills share one
directory, so a kit rendered for opencode in a repository that also names the
cloud agent is committed by that fact alone.

Two kinds of spot are committed, and they are the two kinds DESIGN.md section 6
says have to be.

The first is anything a machineless harness reads, because nobody runs `akit`
in its checkout and an uncommitted file it is supposed to read does not exist.

The second is a rule written between markers inside a file somebody else owns.
`AGENTS.md` is committed for reasons that have nothing to do with us, and a
block of the employer's prose inside it is in the history either way. Section 8
lists that as the first of the three things that can actually leak, so it is
checked whether or not a machineless harness is named.

**Classification is lazy, which is what keeps an ordinary render offline.** A
render only asks who can read this repository when it has already found a
private source landing in a committed spot. Every source public means no leak is
possible and no question worth the network, so a laptop render on a train is the
same render as yesterday's, and the one that goes near a remote is the one with
something to lose.

**A source nobody classified is refused in the dangerous position only.** A
remote cached by a build that predates the classification file has no answer
either way, and guessing "public" is the guess this whole section forbids. So it
is a refusal when it lands in a committed spot in a public repository, naming
`akit update` as the way to find out, and it is nothing at all anywhere else.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from federated_agent_kits import sources
from federated_agent_kits.cache import Privacy
from federated_agent_kits.exits import RefusalError
from federated_agent_kits.sources import SourceKey, SourceKind

INDENT = "  "


@dataclass(frozen=True)
class Exposure:
    """One private thing, and the committed place it was about to appear in."""

    source: str
    where: Path
    known: bool = True
    """False for a source this machine has never classified, which reads differently."""

    @property
    def described(self) -> str:
        unknown = "" if self.known else ", which this machine has never classified"
        return f"{self.source}{unknown} -> {self.where}"


class LeakError(RefusalError):
    """A private source about to be committed into a repository anybody can read."""

    def __init__(self, root: Path, remotes: Sequence[str], exposures: Sequence[Exposure], fix: str) -> None:
        self.exposures = tuple(exposures)
        listed = "\n".join(f"{INDENT * 2}{exposure.described}" for exposure in exposures)
        reachable = remotes[0] if remotes else "a remote anybody can read"
        super().__init__(
            f"refusing to write a private source into {root}, which is public ({reachable}):\n"
            f"{listed}\n"
            f"{INDENT}Nothing was written. These files are committed, so putting them there publishes the source.\n"
            f"{INDENT}{fix}"
        )


def unclassified(source: str) -> str:
    return f"`akit update {source}`, which says whether it is private"


def of_parts(root: Path, remotes: Sequence[str], exposures: Sequence[Exposure]) -> LeakError:
    """The first half: parts landing somewhere this repository commits."""
    unknowns = [exposure.source for exposure in exposures if not exposure.known]
    if unknowns:
        fix = f"Run {unclassified(unknowns[0])}, or drop the subscription with `akit remove`."
    else:
        fix = (
            "Drop the subscription with `akit remove`, or stop committing renders here with "
            "`akit harness remove <name>`."
        )
    return LeakError(root, remotes, exposures, fix)


def of_manifest(root: Path, remotes: Sequence[str], exposures: Sequence[Exposure]) -> LeakError:
    """The second half: a private source named in a file this repository commits.

    The URL is the leak on its own. `git@git.acme.example:team/unreleased.git`
    tells somebody this project exists, who is building it and roughly what it
    is for, whether or not they can clone it (DESIGN.md section 8).
    """
    fix = "Subscribe to it in your own manifest instead: `akit remove <name>` then `akit add <source> <name> --global`."
    return LeakError(root, remotes, exposures, fix)


def is_private(source: SourceKey, known: Mapping[str, Privacy]) -> bool | None:
    """Whether this source is private, or `None` for one nobody has classified.

    **A path source is as public as the repository it sits in**, so it is never
    the private half of a leak. A path inside the target is the same files in
    the same commit behind the same remote, and a path outside one can only
    appear in a manifest that is not committed, whose renders go to machine-level
    directories with no remote to leak into (DESIGN.md section 8).
    """
    if source.kind is SourceKind.PATH:
        return False
    found = known.get(source.raw)
    if found is None:
        return None
    return found is Privacy.PRIVATE


def exposures(wanted: Iterable[tuple[str, Path]], known: Mapping[str, Privacy]) -> list[Exposure]:
    """Every source in `wanted` that may not be committed, paired with where it would land."""
    found: list[Exposure] = []
    for source, where in wanted:
        private = is_private(sources.parse(source), known)
        if private is False:
            continue
        found.append(Exposure(source=source, where=where, known=private is True))
    return found


__all__ = ["Exposure", "LeakError", "exposures", "is_private", "of_manifest", "of_parts", "unclassified"]
