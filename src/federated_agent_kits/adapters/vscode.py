"""VS Code: fixed paths everywhere, rules as a directory we own, no agents yet.

VS Code is the opposite of opencode. It insists on fixed paths, so everything is
written where it already looks and nothing is pointed anywhere. That makes rules
the first shape - `.github/instructions/*.instructions.md`, one file per rule,
which is the shape DESIGN.md section 7 wants everywhere because removing one rule
is then a deleted file rather than an edit to a file holding its neighbours.

There is a setting that would make it the second shape and we are not using it.
`chat.instructionsFilesLocations` takes absolute and `~` paths, is marked
deprecated, and is honoured only by the Local agent, so neither Agent Host nor the
cloud agent would see anything we wrote there.

**Skills are the weak leg, and this file is where that is paid for.** DESIGN.md
section 4 records that the user-wide skills location varies, which is a fact
about the documentation rather than a reason to render nothing: a skill
subscribed at user scope has to land somewhere or user-scope subscriptions do not
work for anybody using VS Code. So it is written to `~/.claude/skills/`, the
Claude-compatible directory the harness already reads at project scope, and the
other two candidates are in the read list. If that is the wrong directory it is
one line here, which is the whole point of an adapter.

Question 6 is the awkward one and it is not solved here. VS Code anchors on the
open workspace, which is usually the repository, sometimes one folder inside it,
and sometimes several at once. The git root is the right answer for the usual
case and `akit doctor` is where the others get reported, because no computation
on this machine can see which folder somebody opened.

**Every path below is a snapshot** and will move.
"""

from __future__ import annotations

from federated_agent_kits.adapters.adapter import Adapter, Destination, RuleShape
from federated_agent_kits.manifest import Kind, Scope

PROJECT_SKILLS = ".claude/skills"
PROJECT_SKILL_DIRECTORIES: tuple[str, ...] = (".claude/skills", ".agents/skills")

USER_SKILLS = ".claude/skills"
USER_SKILL_DIRECTORIES: tuple[str, ...] = (".claude/skills", ".copilot/skills", ".agents/skills")

#: One file per rule, in a directory we own. The suffix is part of how VS Code
#: finds them, so it is not ours to choose.
PROJECT_RULES = ".github/instructions"
USER_RULES = ".copilot/instructions"
SUFFIX = ".instructions.md"

#: Question 7, across the places VS Code and its agent host leave something on
#: both operating systems. `~/.vscode` is an extensions directory and exists
#: after the first install; the `User` directories hold settings; `.vscode-server`
#: is what a remote or container session leaves behind.
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
    name="vscode",
    summary="VS Code and its Copilot agent host, on this machine",
    has_a_machine=True,
    destinations={
        (Kind.SKILL, Scope.USER): Destination(write=USER_SKILLS, read=USER_SKILL_DIRECTORIES),
        (Kind.SKILL, Scope.PROJECT): Destination(write=PROJECT_SKILLS, read=PROJECT_SKILL_DIRECTORIES),
        (Kind.RULE, Scope.USER): Destination(write=USER_RULES),
        (Kind.RULE, Scope.PROJECT): Destination(write=PROJECT_RULES),
    },
    rule_shape=RuleShape.DIRECTORY,
    rule_suffix=SUFFIX,
    evidence=EVIDENCE,
)

__all__ = ["ADAPTER"]
