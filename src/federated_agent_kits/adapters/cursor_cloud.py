"""Cursor's cloud agents: the other half of Cursor, where everything is committed.

A cloud agent runs in an isolated VM, clones one repository, works in it, and is
gone. Nobody runs `akit render` in that checkout, so **a file this harness is
supposed to read and that is not committed does not exist**. That is the same
property `copilot-ci` has and the reason this is a second adapter rather than a
scope inside `cursor_local.py`: question 6 of DESIGN.md section 4 is answered
differently, and every other answer follows from it.

It follows that this harness cannot be detected. `has_a_machine` is False, which
takes it out of `detected` entirely, so it arrives only by being named:
`akit harness add cursor-cloud`.

**Naming it commits two directories, which is the intended behaviour.** Skills
share `.agents/skills/` with opencode, both Copilots and `cursor-local`, and
rules share `.cursor/rules/` with `cursor-local`. git cannot ignore a directory
halfway, so the moment this harness is in the list both leave the `.gitignore`
block and the kits every other harness was reading privately get committed. The
leak refusal in `leaks.py` is what stops a private source's kit going with them.

**It is user-scope nothing.** The VM has no home directory of yours in it.
Cursor's account-level "User Rules" do travel there, but they are typed into
settings and have no path, and personal skills under `~/.cursor/skills/` reach a
cloud agent only through Cursor's own opt-in sync rather than through anything
written here. So `Scope.USER` is absent from `destinations` altogether, which is
the difference between "not here" and "not at all".

**What it reads that `cursor-local` does not is not ours.** `.cursor/environment.json`
configures the cloud VM and `.cursor/hooks.json` its hooks; neither is a kit and
neither is written by this tool. They are named here so the next person reading
this file does not go looking.

**Agents are declined**, as everywhere in 1.0, and the paths are recorded in
`cursor_local.py` rather than twice.

**Every path below was checked against Cursor's documentation on 2026-10-23.**
Cloud agents are documented as using the same rules and skills as a local agent,
with committed `.cursor/rules/*.mdc` and `AGENTS.md` the recommended way to
reach them, so the paths are deliberately `cursor-local`'s project half and the
duplication is a statement that the two were compared.
"""

from __future__ import annotations

from federated_agent_kits.adapters.adapter import Adapter, Destination, RuleShape
from federated_agent_kits.manifest import Kind, Scope

#: The shared directory, which is also where every other harness here writes,
#: and the Cursor-native and compatibility directories a source may have used.
SKILLS = ".agents/skills"
SKILL_DIRECTORIES: tuple[str, ...] = (SKILLS, ".cursor/skills", ".claude/skills", ".codex/skills")

#: One file per rule, in a directory we own, committed. `.mdc` because a plain
#: `.md` in that directory is ignored by Cursor outright.
RULES = ".cursor/rules"
SUFFIX = ".mdc"

#: The same key `cursor-local` writes, for the same reason: without it, and
#: without `globs` or a `description`, the rule is loaded only when somebody
#: mentions it by hand, and a cloud agent has nobody to do that.
ALWAYS_APPLY = "alwaysApply"
FRONTMATTER: dict[str, str | bool] = {ALWAYS_APPLY: True}

ADAPTER = Adapter(
    name="cursor-cloud",
    summary="Cursor's cloud agents, which read only what the repository commits",
    has_a_machine=False,
    destinations={
        (Kind.SKILL, Scope.PROJECT): (Destination(write=SKILLS, read=SKILL_DIRECTORIES),),
        (Kind.RULE, Scope.PROJECT): (Destination(write=RULES),),
    },
    rule_shape=RuleShape.DIRECTORY,
    rule_suffix=SUFFIX,
    rule_frontmatter=FRONTMATTER,
)

__all__ = ["ADAPTER"]
