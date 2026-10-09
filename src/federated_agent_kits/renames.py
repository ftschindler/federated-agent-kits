"""The note a rename leaves, so that a rule still points at the skill it means.

A kit's parts name each other. The rule that makes a model reach for a skill is
the reason DESIGN.md section 1 gives for a kit being a composition at all, and
naming the skill is how it does it: *load the `writing` skill when revising a
draft*. Inside one source that name is unique and nothing more is needed, which
is exactly the ceremony a source is promised it never has to perform.

`as:` breaks that sentence. The skill is installed as `felix-writing` and the
rule still says `writing`.

**The reference is not rewritten, because it cannot be found.** It is prose, and
the name is usually an ordinary word. One line of a real rule carries both
readings at once - "**Load the `writing` skill** when writing anything longer
than a reply" - and no rule separates a reference from a verb reliably enough to
edit somebody's prose on the strength of it.

**So a rename writes a rule of our own instead**, under the reserved id in
`RENAMES`. It states which name each renamed kit is installed under, which is a
mapping rather than a correction: it reads correctly before or after the rule it
explains. That matters, because a harness reading a directory of rules declines
to promise an order at all (DESIGN.md section 7), and a note that had to win an
argument would need one.

**It is written only when a rule actually names a renamed kit from the same
source.** A rule costs tokens on every turn, so a note that always rendered
would be permanent weight for a condition most setups never meet. The search is
therefore not only how the note is aimed, it is what keeps it out of the
ordinary render, which has no renames in it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from federated_agent_kits import frontmatter

#: The marker id and filename the note is written under. Reserved, so that a
#: subscription to a rule by this name is refused rather than quietly fighting
#: with us over one marker (DESIGN.md section 7).
RENAMES = "akit-renames"

#: What the note declares to the harnesses that need frontmatter to load a rule
#: at all. `applyTo` is added by the renderer like any other rule's; this is the
#: description Copilot shows and loads on.
DESCRIPTION = "Which name each renamed kit is installed under, where a rule refers to it by another."


@dataclass(frozen=True)
class Rename:
    """One kit installed under a name that is not the one its source gave it."""

    source: str
    original: str
    """What the source calls it, and what a rule from that source will say."""

    rendered: str
    """What it is installed as, which is the `as:` name."""


def _mentions(body: str, name: str) -> bool:
    """Whether this prose names `name` as a whole word, backticked or bare.

    Backticks are markdown's convention for an identifier and are the better
    signal, but requiring them assumes an author who was careful at the one
    moment it mattered, and a rule written by somebody who was not is exactly
    the rule this note exists for. So a bare mention counts too, as long as it
    is a whole word: matching inside one would fire on `rewriting` for a kit
    called `writing`, which is a sentence about something else entirely.

    The asymmetry is deliberate and is the reason a loose match is affordable. A
    false positive costs one sentence that is true anyway, since the kit really
    is installed under that name. A false negative leaves the stale reference
    this whole module exists to answer.
    """
    return re.search(rf"(?<![0-9A-Za-z_-]){re.escape(name)}(?![0-9A-Za-z_-])", body) is not None


def referenced(renames: Iterable[Rename], rule_source: str, rule_body: bytes) -> tuple[Rename, ...]:
    """Every rename this one rule refers to, which is same-source only.

    A rule naming `writing` in a different repository means that repository's
    `writing`, or the word. The assumption that a bare name resolves locally is
    the one its author was entitled to make, so it is the only one read into it
    (DESIGN.md section 7).
    """
    body = frontmatter.parse(rule_body).body
    return tuple(rename for rename in renames if rename.source == rule_source and _mentions(body, rename.original))


def note(renames: Sequence[Rename]) -> bytes:
    """The note as a rule source, for the renames some rule was found to refer to.

    Shaped like a rule a source could have written, frontmatter and all, so that
    it goes through exactly the same renderer as every other rule: dropped for a
    harness reading one shared file, merged with that harness's own keys for one
    reading a directory. A second code path writing the same markdown would be a
    second place for the two shapes to drift apart.

    Sorted by the name a rule will say, so that the same set of renames produces
    the same bytes whatever order the manifest listed them in. A note whose text
    depended on iteration order would be a hash that moved on its own, and every
    render after the first would report writing a file it had not changed.
    """
    lines = [
        frontmatter.FENCE,
        f"description: {DESCRIPTION}",
        frontmatter.FENCE,
        "",
        "# Kits installed under another name",
        "",
        "Where a rule refers to one of these by the name on the left, the kit is installed",
        "under the name on the right. Use the installed name.",
        "",
    ]
    lines += [
        f"- `{rename.original}` is installed as `{rename.rendered}`" for rename in sorted(set(renames), key=_order)
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _order(rename: Rename) -> tuple[str, str, str]:
    return (rename.original, rename.rendered, rename.source)
