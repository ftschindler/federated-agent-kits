"""Cursor on this machine: skills in the shared directory, rules in `.cursor/rules/`.

Cursor is two harnesses, and this is the one on your laptop. The other,
`cursor_cloud.py`, runs in a cloud VM that clones the repository and never sees
the user-scope half of this file. They are split for the reason DESIGN.md
section 4 splits the two Copilots: the question that decides everything else is
whether `akit render` can run where the harness reads, and the two answers
disagree. One adapter spanning both would have to write user-scope files that
one half cannot read and claim detection for a harness that was never on this
disk.

**The id is `cursor-local` rather than `cursor`.** The bare name would read as
"Cursor, the product", which is both of these, and the manifest line that then
needs qualifying is somebody else's. Pairing the two names is what makes the
choice between them a choice rather than a default with an exception.

**Skills go where opencode and Copilot already put them.** Cursor documents
`.cursor/skills/` and `.agents/skills/` as its own, plus `.claude/skills/` and
`.codex/skills/` for compatibility, at both scopes. Writing to `.agents/skills/`
is what makes a skill wanted by three harnesses one copy rather than three
(DESIGN.md section 7). The narrower directories are in `read` because a source
repository laid out for Cursor alone will have used one.

**Rules are the first shape, and the suffix is not ours to choose.** A file in
`.cursor/rules/` is read only if it is called `.mdc`; a plain `.md` sitting
beside it is ignored outright, which is the silent failure question 2 exists to
avoid. User-scope rule files at `~/.cursor/rules/` are documented and local to
this machine, and they are not the same thing as the "User Rules" typed into
Cursor's settings, which are account-stored and have no path to render to. We
write the files and leave the settings alone.

**`alwaysApply: true` is this harness's `applyTo`.** A rule in `.cursor/rules/`
with no `alwaysApply`, no `globs` and no `description` is discovered, listed,
and loaded only when somebody `@`-mentions it by hand. So the key is written
over whatever the source said, for the reason Copilot's is. It is a YAML
boolean and not the string `"true"`, which is why `rule_frontmatter` takes a
bool at all.

**`AGENTS.md` is declined deliberately, though Cursor reads it.** opencode
already writes rules into that file as marker blocks, and a second harness
claiming it would put two adapters' blocks in one host for no gain: Cursor reads
`.cursor/rules/` as well, and a directory we own makes withdrawing one rule a
deleted file rather than an edit next to somebody's prose.

**Agents are declined, like everywhere else in 1.0.** Cursor's are subagents in
`.cursor/agents/*.md`, user-scope in `~/.cursor/agents/`, with `name`,
`description`, `model`, `readonly` and `is_background` in the frontmatter and
`.claude/agents/` and `.codex/agents/` read for compatibility. No hard size cap
is documented; rules are advised to stay under 500 lines and skills warn over
roughly 5,000 tokens. That is written down here so T13 does not research it
twice.

**Every path below was checked against Cursor's documentation on 2026-10-23**:
the skill directories, the `.mdc` rule suffix and its three frontmatter keys,
the user rule directory, and the subagent path. The evidence paths are the
weakest part, as they are for `copilot-vscode`: Cursor publishes `~/.cursor` and
nothing else, and the application-data directories below follow the VS Code
convention the editor is forked from.
"""

from __future__ import annotations

from federated_agent_kits.adapters.adapter import Adapter, Destination, RuleShape
from federated_agent_kits.manifest import Kind, Scope

#: The shared directory we write to, and the harness-specific ones a source may
#: equally have left a skill in. Cursor reads all of them at both scopes, under
#: the home directory for yours and the project anchor for a repository's.
SKILLS = ".agents/skills"
SKILL_DIRECTORIES: tuple[str, ...] = (SKILLS, ".cursor/skills", ".claude/skills", ".codex/skills")

#: One file per rule, in a directory we own, at both scopes. The same relative
#: path twice is not the two scopes colliding: one hangs off a home directory
#: and the other off the project anchor.
RULES = ".cursor/rules"
SUFFIX = ".mdc"

#: Declined until T13, and recorded because the research is done.
AGENTS = ".cursor/agents"
SUFFIX_AGENT = ".md"

#: The key that decides whether the rule is loaded without being asked for, as
#: the boolean Cursor's parser wants rather than a string that looks like one.
ALWAYS_APPLY = "alwaysApply"
FRONTMATTER: dict[str, str | bool] = {ALWAYS_APPLY: True}

#: Question 7, on every platform rather than the one this was typed on.
#: `~/.cursor` is Cursor's own and documented; the application-data directories
#: follow the convention Cursor inherits from VS Code. `.cursor-server` is what
#: a remote or container session leaves on the host it runs on, which is the
#: machine rendering for it.
EVIDENCE: tuple[str, ...] = (
    ".cursor",
    ".cursor-server",
    ".config/Cursor/User",
    "AppData/Roaming/Cursor/User",
    "Library/Application Support/Cursor/User",
)

ADAPTER = Adapter(
    name="cursor-local",
    summary="Cursor, on this machine",
    has_a_machine=True,
    destinations={
        (Kind.SKILL, Scope.USER): Destination(write=SKILLS, read=SKILL_DIRECTORIES),
        (Kind.SKILL, Scope.PROJECT): Destination(write=SKILLS, read=SKILL_DIRECTORIES),
        (Kind.RULE, Scope.USER): Destination(write=RULES),
        (Kind.RULE, Scope.PROJECT): Destination(write=RULES),
    },
    rule_shape=RuleShape.DIRECTORY,
    rule_suffix=SUFFIX,
    rule_frontmatter=FRONTMATTER,
    evidence=EVIDENCE,
)

__all__ = ["ADAPTER"]
