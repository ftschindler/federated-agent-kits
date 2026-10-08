"""Markdown with a YAML header, which is the shape every kind of part has.

A rule is one of these and so is a `SKILL.md`, and until now only rules parsed
one. Skills needed it too the moment `as:` had to rewrite the key that says
which skill a directory holds (DESIGN.md section 7), and a second parser would
have been a second answer to "where does the body start".

Two callers, two vocabularies. The reader here raises `FrontmatterError` and
each kind catches it to say "rule" or "skill" in its own words, so the message a
person sees still names the thing they subscribed to rather than a file format.

**A file that opens with `---` and never closes it is not broken frontmatter.**
It is a body that begins with a horizontal rule, and reading it as a failed
header would refuse a part that renders perfectly well everywhere.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.error import YAMLError

from federated_agent_kits.exits import AkitError

#: What separates a header from a body, and what a file has to open with for
#: there to be a header at all.
FENCE = "---"


class FrontmatterError(AkitError):
    """A header this build cannot read, in the words of the file format.

    Never raised at a person: `rules.py` and `skills.py` each catch it and say
    which part of theirs was malformed, because "the rule \"prose-style\"" is
    something somebody can go and look at and "a YAML header" is not.

    `fix` is the advice that belongs to this particular failure rather than to
    the kind of part it happened in, which is why it travels with the error and
    not with the caller.
    """

    def __init__(self, message: str, *, fix: str) -> None:
        super().__init__(message)
        self.summary = message
        self.fix = fix


@dataclass(frozen=True)
class Document:
    """One part as it was written: the keys it carried, and the prose under them."""

    front: CommentedMap | None
    """The author's own header, or `None` where the file had none."""

    body: str
    """Everything after the header, unchanged, ending in exactly one newline."""


def yaml() -> YAML:
    """One configured round-tripper, built per call because a `YAML` is stateful.

    `width` is set far past any line we write so that a long `description:`
    comes back on one line. Letting ruamel fold it would rewrite an author's
    header every render, and a header that changes on every render is a hash
    that never settles.
    """
    configured = YAML()
    configured.preserve_quotes = True
    configured.width = 4096
    return configured


def dump(front: CommentedMap) -> str:
    """A header back to text, with the author's order and comments kept."""
    stream = io.StringIO()
    yaml().dump(front, stream)
    return stream.getvalue()


def _text(data: bytes) -> str:
    """Source bytes as text, with line endings settled before anything reads them.

    A part authored on Windows and rendered on Linux has to produce the same
    bytes as the other way round, or two machines rendering one repository
    disagree about whether it is up to date.
    """
    return data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")


def _ends_once(body: str) -> str:
    """The body with its surrounding blank lines settled.

    The blank line after a closing fence is the fence's separator rather than
    the author's paragraph break, and a trailing newline is a habit two editors
    disagree about. Both are decided here so that one source renders to the same
    bytes whatever its whitespace was, which is what keeps a second render a
    no-op.
    """
    return "" if not body.strip() else body.strip("\n") + "\n"


def parse(data: bytes) -> Document:
    """One markdown file into its header and its body."""
    text = _text(data)
    lines = text.split("\n")
    if not lines or lines[0].strip() != FENCE:
        return Document(front=None, body=_ends_once(text))
    try:
        closing = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == FENCE)
    except StopIteration:
        return Document(front=None, body=_ends_once(text))
    header = "\n".join(lines[1:closing])
    try:
        front = yaml().load(header or "{}")
    except YAMLError as error:
        raise FrontmatterError(
            f"not valid YAML: {error}",
            fix="Correct it in the source, or remove the `---` block: a part with no frontmatter renders everywhere.",
        ) from error
    if not isinstance(front, CommentedMap):
        raise FrontmatterError(
            "not a mapping of keys",
            fix="Write `key: value` lines between the `---` fences, or remove them.",
        )
    return Document(front=front, body=_ends_once("\n".join(lines[closing + 1 :])))
