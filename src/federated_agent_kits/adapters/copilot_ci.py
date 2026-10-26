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

**This harness reads rules from more than one place, and that is why it is the
adapter with doors.** `.github/instructions/*.instructions.md` with `applyTo`
frontmatter is one of them; `AGENTS.md` at the repository root is another, and
GitHub's cloud agent has read it since August 2025. `.github/copilot-instructions.md`,
`CLAUDE.md` and `GEMINI.md` are three more that nothing here writes, because a
door is worth declaring only when somebody would choose it.

**`AGENTS.md` is the default, and the reason is one copy rather than two.**
opencode reads the same file, so a repository rendering for both harnesses
writes each rule once and both read it, which is what `.agents/skills/` already
does for skills (DESIGN.md section 7). The `.github/instructions` door keeps
what that costs: `applyTo` exists only in the first shape, so a repository that
wants its rules scoped to paths picks `instructions` and gets a directory of
files back.

**Every path below was checked against GitHub's documentation on 2026-10-23.**
The three skills directories, each holding `<name>/SKILL.md`; both rule doors;
and the agent path and its cap. A root-level `skills/` is not among the
directories it reads, which is what a repository that is its own source has to
know: its hand-written `skills/` is not what the cloud agent sees, and the
rendered copy in `.agents/skills/` is.
"""

from __future__ import annotations

from federated_agent_kits.adapters.adapter import Adapter, Destination, RuleShape
from federated_agent_kits.manifest import Kind, Scope
from federated_agent_kits.rules import APPLY_TO, EVERYTHING

#: The shared directory, which is also where opencode and Copilot in VS Code
#: write, and the two harness-specific ones a source may equally have used.
#: Each is a door a manifest may pick, because all three are directories this
#: harness reads and a repository that keeps its skills in `.github/` has a
#: reason to want them there.
SKILLS = ".agents/skills"
GITHUB_SKILLS = ".github/skills"
CLAUDE_SKILLS = ".claude/skills"
SKILL_DIRECTORIES: tuple[str, ...] = (SKILLS, GITHUB_SKILLS, CLAUDE_SKILLS)

#: One file both this harness and opencode read, and the default. Rules written
#: here are marker blocks in a file somebody else also writes in, which is the
#: third shape and the one `opencode.py` explains.
AGENTS_RULES = "AGENTS.md"

#: One file per rule, in a directory we own, committed. The first shape, and
#: what this adapter wrote into before `AGENTS.md` was the default.
RULES = ".github/instructions"
SUFFIX = ".instructions.md"

#: Declined until T13, and recorded because this is the harness that documents
#: the format best: `description` required, `name` defaulting to the filename,
#: `tools` and `mcp-servers` optional, and a 30,000-character cap on the prompt
#: that is the only hard size limit any harness states.
AGENTS = ".github/agents"
SUFFIX_AGENT = ".agent.md"
PROMPT_LIMIT = 30_000

#: The frontmatter the `.github/instructions` door needs, for the reason Copilot
#: in VS Code needs it: a `.instructions.md` file with neither `applyTo` nor
#: `description` waits to be attached by hand, and a rule nobody attaches is a
#: rule that never runs. The `AGENTS.md` door carries none, because a `---`
#: block inside somebody's prose is a horizontal rule.
FRONTMATTER = {APPLY_TO: EVERYTHING}

ADAPTER = Adapter(
    name="copilot-ci",
    summary="GitHub Copilot in CI, which reads only what the repository commits",
    has_a_machine=False,
    destinations={
        (Kind.SKILL, Scope.PROJECT): (
            Destination(write=SKILLS, read=SKILL_DIRECTORIES, variant="agents"),
            Destination(write=GITHUB_SKILLS, read=SKILL_DIRECTORIES, variant="github"),
            Destination(write=CLAUDE_SKILLS, read=SKILL_DIRECTORIES, variant="claude"),
        ),
        (Kind.RULE, Scope.PROJECT): (
            Destination(write=AGENTS_RULES, variant="agents-md"),
            Destination(
                write=RULES,
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
)

__all__ = ["ADAPTER"]
