"""GitHub Copilot in VS Code: skills in the shared directory, rules as files we own.

**The harness is the agent, not the editor**, which is why this is
`copilot-vscode` and not `vscode`. VS Code hosts several agent harnesses and
they do not agree with each other: Cline reads `.cline/skills/`, Roo Code reads
`.roo/skills/`, the Claude Code extension reads `.claude/skills/`, and Amazon Q
has rules in `.amazonq/rules/` and no skills at all. Every one of those is "VS
Code" to the person using it. Naming this adapter after the editor would claim
the id for whichever harness happened to be written first and leave the next one
needing a name that sounds like a subtype of it.

That Copilot now ships inside a stock VS Code does not change the answer. It is
still an extension, it still has to be signed in to, and the paths below are
Copilot's rather than the editor's.

**Skills go where opencode already puts them.** Copilot reads `.agents/skills/`
and `~/.agents/skills/`, alongside `.github/skills/`, `.claude/skills/` and their
personal counterparts. Writing to the one directory opencode also reads is what
makes a skill wanted by two harnesses one copy rather than two
(DESIGN.md section 7).

**Rules are the first shape**: `.github/instructions/*.instructions.md`, one file
per rule, so removing one rule is a deleted file rather than an edit to a file
holding its neighbours.

Two things about that directory are not paths and are easy to miss. A file there
is a *targeted* instruction: it loads when its `applyTo` glob matches a file
being changed, or when its `description` matches the task, and with neither it
waits to be attached by hand. So T6 writes `applyTo: "**"` into every rule it
renders here, or renders rules that are never read. And Copilot's documentation
declines to promise any order between them, so nothing here is prefixed or
renamed to imply one (DESIGN.md section 7).

Two settings would make either kind the second shape and neither is usable.
`chat.instructionsFilesLocations` and `chat.agentSkillsLocations` both take
absolute and `~` paths, and both are deprecated and honoured only by the Local
agent, so neither Agent Host nor the cloud agent would read anything we wrote
there.

Question 6 is the awkward one and it is not solved here. VS Code anchors on the
open workspace, which is usually the repository, sometimes one folder inside it,
and sometimes several at once. The git root is right for the usual case and
`akit doctor` is where the others get reported, because nothing on this machine
can see which folder somebody opened.

**Every path below is a snapshot** and will move.
"""

from __future__ import annotations

from federated_agent_kits.adapters.adapter import Adapter, Destination, RuleShape
from federated_agent_kits.manifest import Kind, Scope
from federated_agent_kits.rules import APPLY_TO, EVERYTHING

#: The shared directory, written at both scopes, and the harness-specific ones
#: it also accepts, which a source may equally have left a skill in.
SKILLS = ".agents/skills"
PROJECT_SKILL_DIRECTORIES: tuple[str, ...] = (SKILLS, ".github/skills", ".claude/skills")
USER_SKILL_DIRECTORIES: tuple[str, ...] = (SKILLS, ".copilot/skills", ".claude/skills")

#: One file per rule, in a directory we own. The suffix is how Copilot finds
#: them, so it is not ours to choose.
PROJECT_RULES = ".github/instructions"
USER_RULES = ".copilot/instructions"
SUFFIX = ".instructions.md"

#: The frontmatter every rule rendered here carries, whatever its source said.
#: `applyTo` decides whether the file is read: with neither it nor a
#: `description`, VS Code's documentation says to "attach the file manually when
#: you want to use it", and `**` is the documented way to match every file. The
#: value is written over the source's, because a rule narrowed to `src/**` stops
#: applying the moment somebody opens a different folder as the workspace, and
#: that failure is silent.
FRONTMATTER = {APPLY_TO: EVERYTHING}

#: Question 7, across the places VS Code and the Copilot agent host leave
#: something, on both operating systems. `~/.vscode` is an extensions directory
#: and exists after the first install; the `User` directories hold settings;
#: `.vscode-server` is what a remote or container session leaves behind.
#:
#: Detecting the editor is a deliberate proxy for detecting the harness. Copilot
#: ships inside a stock VS Code but has to be signed in to, and a signed-in
#: session is not something this machine can be asked about. The proxy errs
#: towards rendering: a harness detected and unused costs a directory nobody
#: reads, and a harness missed renders nothing and fails nothing, which is the
#: expensive half.
EVIDENCE: tuple[str, ...] = (
    ".vscode",
    ".vscode-server",
    ".vscode-insiders",
    ".copilot",
    ".config/Code/User",
    ".config/Code - Insiders/User",
    "AppData/Roaming/Code/User",
    "Library/Application Support/Code/User",
)

ADAPTER = Adapter(
    name="copilot-vscode",
    summary="GitHub Copilot in VS Code, on this machine",
    has_a_machine=True,
    destinations={
        (Kind.SKILL, Scope.USER): Destination(write=SKILLS, read=USER_SKILL_DIRECTORIES),
        (Kind.SKILL, Scope.PROJECT): Destination(write=SKILLS, read=PROJECT_SKILL_DIRECTORIES),
        (Kind.RULE, Scope.USER): Destination(write=USER_RULES),
        (Kind.RULE, Scope.PROJECT): Destination(write=PROJECT_RULES),
    },
    rule_shape=RuleShape.DIRECTORY,
    rule_suffix=SUFFIX,
    rule_frontmatter=FRONTMATTER,
    evidence=EVIDENCE,
)

__all__ = ["ADAPTER"]
