"""opencode: skills in a directory it already reads, rules in the file both versions read.

opencode is the harness this project was written on, and it is also the one
that has already moved. Its v1 config takes an `instructions` key of files,
globs and https URLs, which made rules the second shape in DESIGN.md section 4:
a directory we own, pointed at once, never edited again. v2 keeps that key and
does not load it, and its documentation says to use `AGENTS.md`.

So rules go into `AGENTS.md`, between markers, which is the third shape and the
one DESIGN.md section 7 calls the fallback. Both versions read it. The second
shape would be pleasanter to render into and would fail silently on v2, which is
the failure question 6 of section 4 exists to avoid: the files are written, they
are sitting where we left them, and the agent behaves as if they were never
there.

**The pointer is gone with it.** `Pointer` and `RuleShape.POINTED` stay in the
interface because a harness that wants pointing is an ordinary harness, and T10's
guide documents all three shapes. Nothing shipped answers that way today.

Agents are declined. opencode has them, in `.opencode/agent/*.md`, and the reason
they are not here is the one in DESIGN.md section 7: the frontmatter keys and the
tool names disagree across harnesses, and 1.0 ships the declining path in every
adapter rather than in a fixture. T13 fills the two empty mappings in.

**Every path below is a snapshot**, checked against opencode's own documentation
on 2026-10-08, against v1.18.35 and the published v2 documentation. When one
moves, this file is the diff.
"""

from __future__ import annotations

from federated_agent_kits.adapters.adapter import Adapter, Destination, RuleShape
from federated_agent_kits.manifest import Kind, Scope

#: The three directories opencode accepts a skill in, nearest its own first. We
#: write to the last of them, which is the one every other harness in this
#: repository also reads, so a skill wanted by two harnesses is one copy
#: (DESIGN.md section 7). v2 lists all three as discovery sources too, under
#: `.opencode/skills` and the two compatibility paths.
SKILL_DIRECTORIES: tuple[str, ...] = (".opencode/skills", ".claude/skills", ".agents/skills")
SKILLS = ".agents/skills"

#: The one file both versions read rules from. Shared with the user and with
#: every other harness that walks up looking for one, which is what makes this
#: the third shape rather than a directory of ours.
#:
#: v2 documents the order: the global file first, then every `AGENTS.md` from
#: the working directory towards home, stopping at the project root for a
#: workspace outside it. They are combined rather than overriding each other,
#: and opencode states that it does not resolve conflicts between them. So the
#: order our blocks appear in inside one file is the whole of the order we can
#: promise, which is what DESIGN.md section 7 already says.
PROJECT_RULES = "AGENTS.md"
USER_RULES = ".config/opencode/AGENTS.md"

#: Question 7. Any one of these means opencode has run here. The list is longer
#: than `~/.config/opencode` because that is the Linux answer written down as if
#: it were the only one, and a harness that goes undetected renders nothing and
#: fails nothing.
EVIDENCE: tuple[str, ...] = (
    ".config/opencode",
    ".local/share/opencode",
    ".cache/opencode",
    ".opencode",
    "AppData/Roaming/opencode",
    "AppData/Local/opencode",
)

ADAPTER = Adapter(
    name="opencode",
    summary="opencode, on this machine",
    has_a_machine=True,
    destinations={
        (Kind.SKILL, Scope.USER): Destination(write=SKILLS, read=SKILL_DIRECTORIES),
        (Kind.SKILL, Scope.PROJECT): Destination(write=SKILLS, read=SKILL_DIRECTORIES),
        (Kind.RULE, Scope.USER): Destination(write=USER_RULES),
        (Kind.RULE, Scope.PROJECT): Destination(write=PROJECT_RULES),
    },
    rule_shape=RuleShape.SHARED_FILE,
    orders_rules=True,
    evidence=EVIDENCE,
)

__all__ = ["ADAPTER"]
