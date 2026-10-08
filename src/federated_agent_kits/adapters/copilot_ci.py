"""GitHub Copilot in CI: the harness with no machine, where everything is committed.

The cloud agent runs on GitHub's infrastructure. It clones one repository, works
in it, and is gone. Nobody runs `akit render` in that checkout, so **a file this
harness is supposed to read and that is not committed does not exist**. That one
property is what makes this adapter different from the two before it, and it is
the half of DESIGN.md section 4 the first two could not demonstrate.

It follows that this harness cannot be detected. There is nothing it leaves on
your disk, because it was never on your disk. `has_a_machine` is False, which
takes it out of `detected` entirely, so it arrives only by being named:
`akit harness add copilot-ci`.

**Naming it moves a directory into the repository's history**, which is the
intended behaviour rather than a side effect. Skills share one directory with
opencode and Copilot in VS Code, and git cannot ignore a directory halfway, so
the moment this harness is in the list `.agents/skills/` leaves the `.gitignore`
block and the skills every other harness was reading privately get committed.
That is why the leak refusal in `leaks.py` lands in the same task as this file.

**The id is `copilot-ci` and GitHub now calls this the "cloud agent".** It was
"Copilot coding agent" when DESIGN.md section 4 was written and GitHub renamed
it in April 2026. The id is not renamed with it: it is a key in manifests other
people have committed, so changing it breaks their file to track somebody else's
marketing, and what it actually names here is the property that matters, which
is a harness this tool can never run on.

**Agents are declined, like everywhere else in 1.0.** This harness has the
best-documented agent format of the four, `.github/agents/<name>.agent.md` with
a required `description` and a 30,000-character cap, and T13 is where that is
filled in. Until then the path is written down here and nowhere else.

**Every path below was checked against GitHub's documentation on 2026-10-08**
and all of them still stand: the three skills directories, each holding
`<name>/SKILL.md`; `.github/instructions/*.instructions.md` with `applyTo`
frontmatter; and the agent path and its cap. A root-level `skills/` is not among
the directories it reads, which is what a repository that is its own source has
to know: its hand-written `skills/` is not what the cloud agent sees, and the
rendered copy in `.agents/skills/` is.
"""

from __future__ import annotations

from federated_agent_kits.adapters.adapter import Adapter, Destination, RuleShape
from federated_agent_kits.manifest import Kind, Scope
from federated_agent_kits.rules import APPLY_TO, EVERYTHING

#: The shared directory, which is also where opencode and Copilot in VS Code
#: write, and the two harness-specific ones a source may equally have used.
SKILLS = ".agents/skills"
SKILL_DIRECTORIES: tuple[str, ...] = (SKILLS, ".github/skills", ".claude/skills")

#: One file per rule, in a directory we own, committed.
RULES = ".github/instructions"
SUFFIX = ".instructions.md"

#: Declined until T13, and recorded because this is the harness that documents
#: the format best: `description` required, `name` defaulting to the filename,
#: `tools` and `mcp-servers` optional, and a 30,000-character cap on the prompt
#: that is the only hard size limit any harness states.
AGENTS = ".github/agents"
SUFFIX_AGENT = ".agent.md"
PROMPT_LIMIT = 30_000

#: The same frontmatter Copilot in VS Code needs, for the same reason: a
#: `.instructions.md` file with neither `applyTo` nor `description` waits to be
#: attached by hand, and a rule nobody attaches is a rule that never runs.
FRONTMATTER = {APPLY_TO: EVERYTHING}

ADAPTER = Adapter(
    name="copilot-ci",
    summary="GitHub Copilot in CI, which reads only what the repository commits",
    has_a_machine=False,
    destinations={
        (Kind.SKILL, Scope.PROJECT): Destination(write=SKILLS, read=SKILL_DIRECTORIES),
        (Kind.RULE, Scope.PROJECT): Destination(write=RULES),
    },
    rule_shape=RuleShape.DIRECTORY,
    rule_suffix=SUFFIX,
    rule_frontmatter=FRONTMATTER,
)

__all__ = ["ADAPTER"]
