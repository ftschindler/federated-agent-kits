"""Rules: one source file, rendered into the two shapes a harness can take.

A rule is one markdown file in a source. What a harness wants in return differs
more than for any other kind (DESIGN.md section 7), so this module turns one
source file into either of two things:

- **A file in a directory we own**, for a harness that reads one. Copilot's
  `.github/instructions/*.instructions.md` is the shipped case, and the body is
  the source's body with the frontmatter the harness needs merged into it.
- **A block between markers, inside a file somebody else owns.** opencode's
  `AGENTS.md` is the shipped case, at both scopes. Everything outside the
  markers is theirs and survives every render.

**The third shape is where the care goes.** The host file is prose a person
writes, so a render has to put our text back without disturbing a word of
theirs, and has to do it identically the second time. Three properties make that
true, and each has a test:

A block is replaced in the slot it is already in, so a paragraph somebody wrote
between two blocks stays between those two blocks.

The slots are filled in manifest order, so a pair of blocks swapped by hand is
swapped back. Order is the one thing rules have that skills do not, and a
harness that reads one file of ours is the only kind that can be given it.

A block this build did not plan and was not asked to remove is left exactly as
it is. That covers a rendered block somebody edited, which withdrawal keeps and
reports, and anything a different tool put in the same file with the same
marker spelling.

**The host file is never deleted.** A record entry for a block may take its own
text out and nothing else, so a repository that stops subscribing to every rule
is left with the `AGENTS.md` it had, minus our paragraphs (DESIGN.md section 6).

**The second shape is not here.** A harness that reads a directory once it has
been pointed at one would be rendered to exactly like the first shape, and the
difference is a line written into its config at setup. Nothing shipping for 1.0
answers that way, so there is no renderer for it and `RuleShape.POINTED` has no
code behind it. DESIGN.md section 7 says so outright.
"""

from __future__ import annotations

import io
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.error import YAMLError
from ruamel.yaml.scalarstring import DoubleQuotedScalarString

from federated_agent_kits.exits import AkitError

#: What opens and closes one rule inside a file we share. An HTML comment
#: because the host is markdown somebody reads: the markers carry the id a
#: withdrawal needs and render as nothing. The `akit` in the middle is what
#: keeps us from claiming a `BEGIN` somebody else's tool wrote.
BEGIN = "<!-- BEGIN akit {id} -->"
END = "<!-- END akit {id} -->"

_BEGIN_PATTERN = re.compile(r"^<!--\s*BEGIN akit (?P<id>\S+)\s*-->$")
_END_PATTERN = re.compile(r"^<!--\s*END akit (?P<id>\S+)\s*-->$")

#: What separates frontmatter from a body, and what a frontmatter block has to
#: start with for there to be one at all.
FENCE = "---"

#: The key Copilot loads a targeted instruction file on, and the glob that means
#: "every file". Without `applyTo` or `description` such a file is discovered,
#: listed, and never loaded unless somebody attaches it by hand, so this is not
#: a nicety (DESIGN.md section 4). Single-quoted because that is how Copilot's
#: own documentation writes it.
APPLY_TO = "applyTo"
EVERYTHING = "**"

#: What a rule may be called. The name becomes a filename for one shape and a
#: marker id for the other, so it has to survive both: one path segment, no
#: whitespace, and nothing Windows refuses.
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

#: What a harness needing no frontmatter of its own declares. A shared mapping
#: rather than a fresh one per call, and read-only so that a caller cannot put a
#: key into every future render by accident.
NO_KEYS: Mapping[str, str] = MappingProxyType({})

#: Names Windows will not give a file, whatever the extension after them. A
#: rule called `aux` renders fine on Linux and fails on the other half of the
#: support matrix, which is the kind of difference DESIGN.md section 9 exists
#: to keep out.
RESERVED = frozenset(
    {"con", "prn", "aux", "nul", *(f"com{digit}" for digit in range(1, 10)), *(f"lpt{digit}" for digit in range(1, 10))}
)


class RuleError(AkitError):
    """A rule this build will not render, named with what to do about it."""


def check_name(name: str) -> None:
    """Refuse a rule whose name cannot be both a filename and a marker id.

    Refused rather than sanitised. Two rules called `my rule` and `my-rule`
    sanitise to one file, and the loser disappears without anything failing,
    which is worse than being told to rename one of them.
    """
    if not SAFE_NAME.match(name) or name.endswith("."):
        raise RuleError(
            f'"{name}" is not a name a rule can have.\n'
            "  A rule becomes a filename and a marker, so it may hold letters, digits, "
            "dots, dashes and underscores, and must start with a letter or a digit.\n"
            "  Rename it in the source, or subscribe to it with `as: <another-name>`."
        )
    if name.split(".", maxsplit=1)[0].lower() in RESERVED:
        raise RuleError(
            f'"{name}" is a name Windows will not give a file.\n'
            "  Subscribe to it with `as: <another-name>`, so that this renders on both "
            "operating systems rather than one."
        )


def _yaml() -> YAML:
    """One configured round-tripper, built per call because a `YAML` is stateful."""
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 4096
    return yaml


@dataclass(frozen=True)
class Document:
    """One rule as it was written: the keys it carried, and the prose under them."""

    front: CommentedMap | None
    """The source's own frontmatter, or `None` where it had none."""

    body: str
    """Everything after the frontmatter, unchanged, ending in exactly one newline."""


def _text(data: bytes) -> str:
    """Source bytes as text, with line endings settled before anything reads them.

    A rule authored on Windows and rendered on Linux has to produce the same
    bytes as the other way round, or two machines rendering one repository
    disagree about whether it is up to date.
    """
    return data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")


def _ends_once(body: str) -> str:
    """The body with its surrounding blank lines settled.

    The blank line after a closing `---` is the fence's separator rather than
    the author's paragraph break, and a trailing newline is a habit two editors
    disagree about. Both are decided here so that the same rule renders to the
    same bytes whatever the source file's whitespace was, which is what keeps a
    second render a no-op.
    """
    return "" if not body.strip() else body.strip("\n") + "\n"


def parse(data: bytes, *, name: str) -> Document:
    """One rule file into its frontmatter and its body.

    A file that opens with `---` and never closes it is not frontmatter and is
    not an error either: it is a body that starts with a horizontal rule, and
    reading it as a broken header would refuse a rule that renders perfectly
    well everywhere.
    """
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
        front = _yaml().load(header or "{}")
    except YAMLError as error:
        raise RuleError(
            f'the rule "{name}" opens with frontmatter that is not valid YAML: {error}.\n'
            "  Correct it in the source, or remove the `---` block: a rule with no frontmatter "
            "renders everywhere."
        ) from error
    if not isinstance(front, CommentedMap):
        raise RuleError(
            f'the rule "{name}" opens with frontmatter that is not a mapping of keys.\n'
            "  Write `key: value` lines between the `---` fences, or remove them."
        )
    return Document(front=front, body=_ends_once("\n".join(lines[closing + 1 :])))


def _dump(front: CommentedMap) -> str:
    stream = io.StringIO()
    _yaml().dump(front, stream)
    return stream.getvalue()


def as_file(data: bytes, *, name: str, keys: Mapping[str, str] = NO_KEYS) -> bytes:
    """One rule as a file for a harness that reads a directory of them.

    `keys` are the ones the harness needs and the source cannot be trusted to
    have. They are written over whatever the source said, because a key that
    decides whether the file is loaded at all is not a preference: a Copilot
    rule carrying `applyTo: 'src/**'` is a rule that stops applying the moment
    somebody opens a different folder, and a rule with no `applyTo` never loads
    without being attached by hand (DESIGN.md section 4).

    Everything else the source wrote survives, in its own order, with its own
    comments. `description:` is the one that matters: it is the other key
    Copilot loads a rule on, and it is the author's to write.
    """
    check_name(name)
    document = parse(data, name=name)
    if not keys:
        return document.body.encode("utf-8")
    front = document.front if document.front is not None else CommentedMap()
    for key, value in keys.items():
        front[key] = DoubleQuotedScalarString(value)
    return f"{FENCE}\n{_dump(front)}{FENCE}\n\n{document.body}".encode()


def as_block(data: bytes, *, name: str) -> bytes:
    """One rule as the bytes that go between markers in a file we share.

    The frontmatter goes. A `description:` means something to Copilot and
    nothing to a harness reading one `AGENTS.md`, where it would render as a
    stray `---` rule in the middle of somebody's prose.

    No trailing newline, because the closing marker is the next line and these
    are the exact bytes the record hashes. A body that ended in one here and
    not when read back would make every rendered block look edited on the
    render after the one that wrote it.
    """
    check_name(name)
    return parse(data, name=name).body.rstrip("\n").encode("utf-8")


@dataclass(frozen=True)
class Block:
    """One rule's text, and the id its markers carry."""

    id: str
    body: str


@dataclass(frozen=True)
class _Slot:
    """One pair of markers already in a host file, and the lines between them."""

    id: str
    start: int
    stop: int
    """One past the `END` line, so a slot is `lines[start:stop]`."""

    body: str


def _slots(lines: Sequence[str]) -> list[_Slot]:
    """Every block already in this file, in the order the file has them.

    A `BEGIN` with no `END` after it claims the rest of the file, which is what
    a half-deleted block looks like and is the only reading that lets the next
    render repair it.
    """
    found: list[_Slot] = []
    index = 0
    while index < len(lines):
        opening = _BEGIN_PATTERN.match(lines[index].strip())
        if opening is None:
            index += 1
            continue
        closing = next(
            (later for later in range(index + 1, len(lines)) if _END_PATTERN.match(lines[later].strip()) is not None),
            None,
        )
        stop = len(lines) if closing is None else closing + 1
        body = "\n".join(lines[index + 1 : stop - 1 if closing is not None else stop])
        found.append(_Slot(id=opening.group("id"), start=index, stop=stop, body=body))
        index = stop
    return found


def blocks_in(text: str) -> dict[str, str]:
    """Every rule currently in this file, by id, for a hash to be taken of.

    The hash covers the bytes between the markers and never the whole file,
    because the host is prose somebody edits and a whole-file hash would stop
    matching the week after it was written (DESIGN.md section 6).
    """
    return {slot.id: slot.body for slot in _slots(text.split("\n"))}


def _rendered(block: Block) -> list[str]:
    body = block.body.rstrip("\n")
    middle = body.split("\n") if body else []
    return [BEGIN.format(id=block.id), *middle, END.format(id=block.id)]


def weave(text: str, blocks: Sequence[Block], *, remove: Iterable[str] = ()) -> str:
    """This file with our blocks in it, and everything else exactly where it was.

    Three kinds of slot, and only the first two are touched. A slot whose id we
    planned is refilled, and the refills go in the order `blocks` is in rather
    than the order the file happened to have them, so a hand-swapped pair comes
    back swapped. A slot named in `remove` is taken out. Every other slot is
    left alone, which is what keeps an edited block where withdrawal decided to
    leave it.

    A planned block with no slot to go in is appended, after a blank line.
    """
    taken = set(remove)
    planned = [block for block in blocks if block.id not in taken]
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    wanted = {block.id for block in planned}
    slots = _slots(lines)
    managed = [slot for slot in slots if slot.id in wanted]
    refills = dict(zip((slot.start for slot in managed), planned, strict=False))
    placed = {block.id for block in planned[: len(managed)]}

    kept: list[str] = []
    cursor = 0
    for slot in slots:
        kept.extend(lines[cursor : slot.start])
        cursor = slot.stop
        if slot.start in refills:
            kept.extend(_rendered(refills[slot.start]))
        elif slot.id in taken or slot.id in wanted:
            # Dropped, either because withdrawal took it or because there are
            # fewer blocks than slots now. Take one blank line with it, so a
            # removal closes the gap instead of leaving a widening hole behind.
            if cursor < len(lines) and not lines[cursor].strip():
                cursor += 1
            elif kept and not kept[-1].strip():
                kept.pop()
        else:
            kept.extend(lines[slot.start : slot.stop])
    kept.extend(lines[cursor:])

    for block in planned:
        if block.id in placed:
            continue
        if kept and kept[-1].strip():
            kept.append("")
        kept.extend(_rendered(block))
    while kept and not kept[-1].strip():
        kept.pop()
    if not kept:
        return ""
    return "\n".join(kept) + "\n"


__all__ = [
    "APPLY_TO",
    "BEGIN",
    "END",
    "EVERYTHING",
    "Block",
    "Document",
    "RuleError",
    "as_block",
    "as_file",
    "blocks_in",
    "check_name",
    "parse",
    "weave",
]
