"""Three cold sessions: a real agent reads the skill and types what it says.

This is the only layer that meets the skill the way a person does. Nothing here
asserts wording, because the model picks its own; what is asserted is the file
on disk afterwards and the manifest it was written into, which is the part a
sentence that only parses in one shell gets wrong.

Each session starts from no prior context, with the skill installed into a
disposable agent's home and a locally built `akit` its `uvx` resolves. The
source is a git repository the test builds, so a session needs the network for
the model and for nothing else.

Run on failure: the agent is preserved and the command to enter it is printed by
the hook in `conftest.py`.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from conftest import AgentFactory
from disposable_agent import DisposableAgent, OpencodeResult
from git_environment import FIXED_AUTHOR, git

pytestmark = pytest.mark.agent

SKILLS = Path(".agents") / "skills"

#: Deliberately not a name any model would produce by chance, and deliberately
#: mundane in what it asks for: a test whose phrase sounds like a secret
#: measures safety training rather than skill discovery.
KIT = "house-style"


def build_source(root: Path) -> Path:
    """A git repository holding one kit: a skill and the rule under one name."""
    source = root / "kits"
    (source / "skills" / KIT).mkdir(parents=True)
    (source / "rules").mkdir(parents=True)
    (source / "skills" / KIT / "SKILL.md").write_text(
        textwrap.dedent(f"""\
        ---
        name: {KIT}
        description: >-
          The house prose style. Use when writing or revising anything a person
          reads.
        ---

        # House style

        Short sentences. No exclamation marks.
        """),
        encoding="utf-8",
    )
    (source / "rules" / f"{KIT}.md").write_text(
        textwrap.dedent(f"""\
        ---
        name: {KIT}
        description: The house prose style, as a digest that applies to every reply.
        ---

        # House style

        Short sentences, and no exclamation marks, in every reply.
        """),
        encoding="utf-8",
    )
    git("init", "--initial-branch=main", cwd=source)
    git("add", ".", cwd=source)
    git(*FIXED_AUTHOR, "commit", "-m", "One kit", cwd=source)
    return source


def workspace(agent: DisposableAgent) -> Path:
    """A git repository for the agent to be standing in, which is the usual case."""
    work = agent.work
    work.mkdir(parents=True, exist_ok=True)
    git("init", "--initial-branch=main", cwd=work)
    return work


def transcript(result: OpencodeResult) -> str:
    return result.text.strip() or "(empty)"


def test_a_machine_with_no_manifest_ends_up_with_one_and_a_rendered_skill(
    agent_factory: AgentFactory,
    tmp_path: Path,
) -> None:
    """The first of the three situations: nothing is set up."""
    agent = agent_factory()
    source = build_source(tmp_path / "source")
    work = workspace(agent)

    result = agent.run(
        f"Set up my agent kits in this repository. Subscribe to the {KIT} kit from the "
        f"repository at {source}, for this repository rather than for me personally.",
        cwd=work,
    )

    assert result.returncode == 0, f"opencode exited {result.returncode}\n{result.stderr}"
    manifest = work / ".akit.yaml"
    assert manifest.is_file(), f"no manifest was written\n--- transcript ---\n{transcript(result)}"
    assert KIT in manifest.read_text(encoding="utf-8")
    rendered = work / SKILLS / KIT / "SKILL.md"
    assert rendered.is_file(), f"the kit was subscribed to but never rendered\n--- transcript ---\n{transcript(result)}"


def test_adding_a_kit_edits_the_right_file_and_nothing_else(agent_factory: AgentFactory, tmp_path: Path) -> None:
    """The second situation, with the scope said out loud: this person, not this repository.

    The failure this catches is the common one rather than an exotic one. Both
    manifests take the same line, so an agent that writes the wrong one produces
    a working setup that is working in the wrong place, and nothing says so.
    """
    agent = agent_factory()
    source = build_source(tmp_path / "source")
    work = workspace(agent)

    result = agent.run(
        f"Add the {KIT} kit from the repository at {source} for me personally, on this machine, "
        "rather than for this repository.",
        cwd=work,
    )

    assert result.returncode == 0, f"opencode exited {result.returncode}\n{result.stderr}"
    assert not (work / ".akit.yaml").exists(), (
        f"a personal subscription was written into the repository\n--- transcript ---\n{transcript(result)}"
    )
    manifests = [path for path in agent.home.rglob("manifest.yaml") if ".npm" not in path.parts]
    written = [path for path in manifests if KIT in path.read_text(encoding="utf-8")]
    assert written, f"no manifest under the home names the kit\n--- transcript ---\n{transcript(result)}"
    assert (agent.home / SKILLS / KIT / "SKILL.md").is_file(), (
        f"the kit was not rendered into this machine's skills directory\n--- transcript ---\n{transcript(result)}"
    )


def test_an_agent_can_say_which_files_a_render_wrote(agent_factory: AgentFactory, tmp_path: Path) -> None:
    """The third situation: a setup already on disk, and a question about it.

    It is asked of a session that did not do the render, so the only way to the
    answer is `akit list` rather than a memory of having written the files.
    """
    agent = agent_factory()
    source = build_source(tmp_path / "source")
    work = workspace(agent)
    installed = agent.run(
        f"Subscribe this repository to the {KIT} kit from the repository at {source}.",
        cwd=work,
    )
    assert installed.returncode == 0, installed.stderr
    rendered = work / SKILLS / KIT / "SKILL.md"
    assert rendered.is_file(), f"the setup step did not render\n--- transcript ---\n{transcript(installed)}"

    asked = agent.run("Which files did akit write into this repository, and where did they come from?", cwd=work)

    assert asked.returncode == 0, f"opencode exited {asked.returncode}\n{asked.stderr}"
    answer = asked.text
    assert KIT in answer, f"the answer never names the kit\n--- transcript ---\n{transcript(asked)}"
    assert "skills" in answer.lower(), (
        f"the answer never names where the kit landed\n--- transcript ---\n{transcript(asked)}"
    )
