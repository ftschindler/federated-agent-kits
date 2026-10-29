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

**Rules have two doors, and a repository's go through `AGENTS.md` by default.**
The Copilot harness discovers a workspace-root `AGENTS.md` as a repository
instruction, alongside `.github/copilot-instructions.md` and `CLAUDE.md`, which
`copilot instruction list` reports for a checkout holding all three. So this
harness and opencode read one file, and a repository rendering for both writes
each rule once rather than twice. That is the reason `copilot-ci` gives for the
same default, and it holds here for the same two readers (DESIGN.md section 7).

**`chat.useAgentsMdFile` is not why, and reaching for it is the trap.** That
setting defaults to on and governs the *Local* harness, and VS Code's own
settings reference says it does not control Copilot's instruction discovery.
The two harnesses inside the editor have separate discovery, and this adapter
names the Copilot one, so the setting is the wrong evidence for the right
answer.

`.github/instructions/` is the other door, taking one `*.instructions.md` per
rule. It stays offered rather than being replaced, because it is the only one of
the two with room to scope a rule to paths: a marker block inside somebody's
`AGENTS.md` cannot carry an `applyTo` glob, so a rule that wants one picks
`--rules instructions` and gets a directory of files back.

Two things about that directory are not paths and are easy to miss. A file there
is a *targeted* instruction: it loads when its `applyTo` glob matches a file
being changed, or when its `description` matches the task, and with neither it
waits to be attached by hand. So every rule rendered through that door carries
`applyTo: "**"`, or they are rules that are never read. And Copilot's
documentation declines to promise any order between them, so nothing there is
prefixed or renamed to imply one, which is why that door answers `orders=False`
while `AGENTS.md` answers True (DESIGN.md section 7).

**Your own rules have one door and it is not `AGENTS.md`.** There is no personal
file here that opencode also reads, so the sharing that decides the project
default has nothing to divide. `~/.copilot/instructions/` is what the Copilot
harness reads, and VS Code documents it as the Copilot user location and ships
it in the default `chat.instructionsFilesLocations`. It is a directory of ours
in the first shape, and it is unnamed because a destination with no alternative
is not a choice anybody makes.

`chat.instructionsFilesLocations` would make rules the second shape and it is
still not what to use. It is current rather than deprecated, and its default now
carries `~/.copilot/instructions` among four entries, but it is a VS Code editor
setting: the editor forwards those locations to a harness it is hosting, and no
other client inherits them. Pointing it at a directory of ours would be a rule
the Copilot CLI and the Copilot app could not see, which is the whole reason the
native location is written to instead. `chat.agentSkillsLocations` is the same
argument for skills.

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
GITHUB_SKILLS = ".github/skills"
COPILOT_SKILLS = ".copilot/skills"
CLAUDE_SKILLS = ".claude/skills"
PROJECT_SKILL_DIRECTORIES: tuple[str, ...] = (SKILLS, GITHUB_SKILLS, CLAUDE_SKILLS)
USER_SKILL_DIRECTORIES: tuple[str, ...] = (SKILLS, COPILOT_SKILLS, CLAUDE_SKILLS)

#: One file per rule, in a directory we own. The suffix is how Copilot finds
#: them, so it is not ours to choose.
PROJECT_RULES = ".github/instructions"
USER_RULES = ".copilot/instructions"
SUFFIX = ".instructions.md"

#: The other project door, and the default: one file opencode reads as well, so
#: a rule rendered for both harnesses is one block rather than two copies.
AGENTS_RULES = "AGENTS.md"

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
        (Kind.SKILL, Scope.USER): (
            Destination(write=SKILLS, read=USER_SKILL_DIRECTORIES, variant="agents"),
            Destination(write=COPILOT_SKILLS, read=USER_SKILL_DIRECTORIES, variant="copilot"),
            Destination(write=CLAUDE_SKILLS, read=USER_SKILL_DIRECTORIES, variant="claude"),
        ),
        (Kind.SKILL, Scope.PROJECT): (
            Destination(write=SKILLS, read=PROJECT_SKILL_DIRECTORIES, variant="agents"),
            Destination(write=GITHUB_SKILLS, read=PROJECT_SKILL_DIRECTORIES, variant="github"),
            Destination(write=CLAUDE_SKILLS, read=PROJECT_SKILL_DIRECTORIES, variant="claude"),
        ),
        (Kind.RULE, Scope.USER): (
            Destination(
                write=USER_RULES,
                shape=RuleShape.DIRECTORY,
                suffix=SUFFIX,
                frontmatter=FRONTMATTER,
                orders=False,
            ),
        ),
        (Kind.RULE, Scope.PROJECT): (
            Destination(write=AGENTS_RULES, variant="agents-md"),
            Destination(
                write=PROJECT_RULES,
                variant="instructions",
                shape=RuleShape.DIRECTORY,
                suffix=SUFFIX,
                frontmatter=FRONTMATTER,
                orders=False,
            ),
        ),
    },
    rule_shape=RuleShape.SHARED_FILE,
    orders_rules=True,
    evidence=EVIDENCE,
)

__all__ = ["ADAPTER"]
