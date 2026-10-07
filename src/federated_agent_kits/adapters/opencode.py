"""opencode: skills in a directory it already reads, rules pointed at once, no agents yet.

opencode is the cheap end of DESIGN.md section 4. It already reads
`.agents/skills/` without being told, its config takes an `instructions` list of
globs so rules are the second shape, and question 6 answers itself because it
walks up to the git worktree root, which is where `.akit.yaml` already is.

Agents are declined. opencode has them, in `.opencode/agent/*.md`, and the reason
they are not here is the one in DESIGN.md section 7: the frontmatter keys and the
tool names disagree across harnesses, and 1.0 ships the declining path in every
adapter rather than in a fixture. T13 fills the two empty mappings in.

**Every path below is a snapshot.** They were where opencode kept things when
this was written, and when one moves, this file is the diff.
"""

from __future__ import annotations

from federated_agent_kits.adapters.adapter import Adapter, Destination, Pointer, RuleShape
from federated_agent_kits.manifest import Kind, Scope

#: The three directories opencode accepts a skill in, nearest its own first. We
#: write to the last of them, which is the one every other harness in this
#: repository also reads, so a skill wanted by two harnesses is one copy
#: (DESIGN.md section 7).
SKILL_DIRECTORIES: tuple[str, ...] = (".opencode/skills", ".claude/skills", ".agents/skills")
SKILLS = ".agents/skills"

#: The directory we own and point opencode at. Not `AGENTS.md`: that file is
#: shared with every other harness that walks up looking for one, and writing
#: into it would make a rule's removal a surgical edit to somebody's prose when
#: it could be a deleted file instead.
PROJECT_RULES = ".opencode/instructions"
USER_RULES = ".config/opencode/instructions"

#: The one key we touch, in a config a person owns, once, at setup. T6 writes it.
PROJECT_CONFIG = "opencode.json"
USER_CONFIG = ".config/opencode/opencode.json"
INSTRUCTIONS = "instructions"

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
    rule_shape=RuleShape.POINTED,
    rule_suffix=".md",
    pointer={
        Scope.USER: Pointer(config=USER_CONFIG, key=INSTRUCTIONS),
        Scope.PROJECT: Pointer(config=PROJECT_CONFIG, key=INSTRUCTIONS),
    },
    evidence=EVIDENCE,
)

__all__ = ["ADAPTER"]
