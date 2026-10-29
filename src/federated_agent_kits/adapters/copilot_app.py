"""The GitHub Copilot app: a desktop client of GitHub's, driving a Copilot CLI.

GitHub's own name for it is the GitHub Copilot app. It reached technical
preview in May 2026 and general availability in June 2026, on macOS, Linux and
Windows, and it is a desktop application rather than an editor extension and
rather than the cloud agent.

**It is a third Copilot harness and not either of the two already here.** The id
is `copilot-app` for the reason `copilot_vscode.py` is not `vscode`: one product
ships several surfaces, they do not agree about paths, and a name claiming the
product would leave the next surface needing one that sounds like a subtype.
What it has in common with `copilot-vscode` is a machine, and what it has in
common with `copilot-ci` is its rule table; it is neither of them.

**What it reads was observed rather than inferred, on 2026-10-29.** The app runs
sessions through a Copilot CLI it bundles and launches as a server, and that CLI
ships `skill list` and `instruction list`, which report what a session would
actually load. Against a throwaway repository holding every candidate path at
once, all three skill directories came back as project skills, and `AGENTS.md`,
`.github/copilot-instructions.md` and `CLAUDE.md` came back as repository
instructions with `.github/instructions/*.instructions.md` beside them as
working-directory instructions. GitHub's own documentation is thinner than that
and warns that supported locations depend on the surface, which is why the
harness was asked instead.

**Rules are the same two doors as the other two Copilot harnesses**, defaulting
to `AGENTS.md` so that one block serves this harness, opencode and whichever of
the others a repository also renders for (DESIGN.md section 7).
`.github/instructions/` is the other, and the only one with room for an
`applyTo` glob. `.github/copilot-instructions.md` and `CLAUDE.md` are read and
are not doors, the same answer `copilot_ci.py` gives: a door is worth declaring
only where somebody would choose it.

**Your own rules go where `copilot-vscode` already sends them.** The app and the
CLI read `~/.copilot/instructions/`, and VS Code documents that directory as the
Copilot user location, so the two adapters write one file rather than a copy
each. There is no personal `AGENTS.md` in the discovery set, so that scope has
one destination and no choice to make.

**Skills decline one directory the editor takes.** The CLI names exactly two
personal locations, `~/.copilot/skills/` and `~/.agents/skills/`, so there is no
`~/.claude/skills/` door here even though `copilot_vscode.py` has one. Project
scope does read all three. Copying the editor's table wholesale would have
invented a path, which is question 1's silent failure rather than a tidy
symmetry.

**Agents are declined, as everywhere else.** GitHub documents custom agents as
usable in the app and gives no repository or home path for them there. The
`.github/agents/<name>.agent.md` format and its 30,000-character cap are
confirmed for other surfaces only, and `copilot_ci.py` is where that is written
down. T13 is where this gets filled in, by asking the app rather than by
assuming it matches.

**Question 7 is the one that needed the install.** Two of the places this app
leaves something cannot be used: `/usr/bin/github` and `/usr/lib/GitHub Copilot/`
sit outside a home directory, and `~/.cache/copilot-desktop-gh-<version>/`
carries a version in its name, which exact-path evidence cannot match.
`~/.copilot/` is shared with the CLI and with `copilot-vscode`, so it identifies
no single harness. That leaves the Tauri application directory, which is
app-specific on every platform and is what `evidence` declares. The Linux entry
was observed on this machine; the Windows one comes from a published teardown;
the macOS one is derived from the same application identifier and has not been
seen, which is recorded here rather than presented as a path somebody checked.

**Every path above is a snapshot** and will move.
"""

from __future__ import annotations

from federated_agent_kits.adapters.adapter import Adapter, Destination, RuleShape
from federated_agent_kits.manifest import Kind, Scope
from federated_agent_kits.rules import APPLY_TO, EVERYTHING

#: The shared directory first, because opencode and both other Copilot
#: harnesses read it, and the harness-specific ones a source may equally have
#: left a skill in. The personal list is two rather than three: the CLI names
#: `~/.copilot/skills/` and `~/.agents/skills/` and no Claude directory.
SKILLS = ".agents/skills"
GITHUB_SKILLS = ".github/skills"
COPILOT_SKILLS = ".copilot/skills"
CLAUDE_SKILLS = ".claude/skills"
PROJECT_SKILL_DIRECTORIES: tuple[str, ...] = (SKILLS, GITHUB_SKILLS, CLAUDE_SKILLS)
USER_SKILL_DIRECTORIES: tuple[str, ...] = (SKILLS, COPILOT_SKILLS)

#: The default door for a repository's rules: one file opencode reads too, so a
#: rule rendered for both is one block rather than two copies.
AGENTS_RULES = "AGENTS.md"

#: The other door, and the only scope-a-rule-to-paths one. The suffix is how
#: Copilot finds these, so it is not ours to choose.
PROJECT_RULES = ".github/instructions"
USER_RULES = ".copilot/instructions"
SUFFIX = ".instructions.md"

#: Declined until T13, and recorded so the research is not done twice. Neither
#: path nor cap is confirmed for this surface; both are what GitHub documents
#: for the editor and the cloud agent.
AGENTS = ".github/agents"
SUFFIX_AGENT = ".agent.md"
PROMPT_LIMIT = 30_000

#: What a rule needs to be read at all in a directory of ours. A
#: `.instructions.md` file with neither `applyTo` nor `description` waits to be
#: attached by hand, so the body alone is a rule that never loads. The
#: `AGENTS.md` door carries none, because a `---` block inside somebody's prose
#: is a horizontal rule.
FRONTMATTER = {APPLY_TO: EVERYTHING}

#: Question 7. The Tauri application directory, which is this app's and not the
#: CLI's and not the editor's, on each platform's answer. Linux was observed on
#: a machine running the app; Windows comes from a published teardown; macOS is
#: derived from the same application identifier and has not been seen.
EVIDENCE: tuple[str, ...] = (
    ".local/share/com.github.githubapp",
    "AppData/Roaming/com.github.githubapp",
    "Library/Application Support/com.github.githubapp",
)

ADAPTER = Adapter(
    name="copilot-app",
    summary="the GitHub Copilot app, on this machine",
    has_a_machine=True,
    destinations={
        (Kind.SKILL, Scope.USER): (
            Destination(write=SKILLS, read=USER_SKILL_DIRECTORIES, variant="agents"),
            Destination(write=COPILOT_SKILLS, read=USER_SKILL_DIRECTORIES, variant="copilot"),
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
