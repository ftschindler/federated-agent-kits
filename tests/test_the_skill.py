"""The skill this repository ships, and the rule that makes a model open it.

Two kinds of test, in two layers, and they fail for different reasons.

The lint below is the `unit` layer: it reads `skills/akit/` and `rules/akit.md`
as text and asserts the properties a reader cannot check by eye. The one that
matters most is that every command the skill names exists, asked of the command
registry rather than of a grep, because a skill naming a command that was
renamed is a skill that sends an agent to an exit code 2.

The install test is the `cli` layer: this repository is a source like any other,
so `akit add` pointed at it has to find the skill and the rule under one name
and render both. That is the step that turns the hand-placed first copy into a
managed one, and nothing else in the suite exercises a source whose kit is the
tool's own.

The third kind lives in `test_cold_sessions.py`, where a real agent reads the
skill and types what it says.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fake_home import FakeHome

from federated_agent_kits import commands, frontmatter
from federated_agent_kits.exits import Exit

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL = REPO_ROOT / "skills" / "akit" / "SKILL.md"
REFERENCES = SKILL.parent / "references"
VERSION_FILE = SKILL.parent / "VERSION"
RULE = REPO_ROOT / "rules" / "akit.md"

FENCE = re.compile(r"^\s{0,3}(?:```|~~~)")
CODE_SPAN = re.compile(r"`([^`]+)`")

#: An invocation, wherever one is written: `akit list` in a sentence, or a line
#: of a shell block. Only the first word after the command is taken, which is
#: what makes `akit help manifest` checked as a topic rather than passing
#: because `help` exists.
INVOCATION = re.compile(r"\bakit (?P<command>[a-z][a-z-]*)(?: (?P<argument>[a-z][a-z-]*))?")

#: Paths belonging to a harness rather than to this project. The skill may not
#: name one: they move, this project cannot know which harness is being used,
#: and a skill that lists them is a second copy of the adapters' answer that
#: nobody will update. Where a path is needed, the skill asks the harness.
FOREIGN_PATHS = (
    "AGENTS.md",
    ".github/instructions",
    ".github/copilot-instructions.md",
    ".claude",
    ".cursor",
    ".opencode",
    ".amazonq",
    "opencode.json",
)

#: A skill may run a command and may never tell the model to open another skill:
#: prose calling prose through a language model is not control flow. The rule is
#: the one place that sentence belongs, so the check runs over prose only - the
#: activation reference quotes the rule, fences and all, and quoting it is not
#: doing it.
OPENS_A_SKILL = re.compile(r"(load|open|read|use) the [`\w-]+ skill", re.IGNORECASE)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def prose_and_code(text: str) -> tuple[str, list[str]]:
    """Split a markdown file into what it says and what it tells you to type.

    Fenced blocks and code spans are the second; everything else is the first.
    Two of the checks below apply to one half only, and running either over the
    whole file is how a lint starts flagging its own worked examples.
    """
    prose: list[str] = []
    code: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            code.append(line)
            continue
        code.extend(CODE_SPAN.findall(line))
        prose.append(CODE_SPAN.sub(" ", line))
    return "\n".join(prose), code


SKILL_TEXT = read(SKILL)
EVERYTHING = {SKILL: SKILL_TEXT, **{path: read(path) for path in sorted(REFERENCES.glob("*.md"))}}


def invocations(text: str) -> list[re.Match[str]]:
    _, code = prose_and_code(text)
    return [found for line in code for found in INVOCATION.finditer(line)]


@pytest.mark.unit
class TestTheSkillIsStandalone:
    """It ships on its own, into a home that has none of this repository in it."""

    def test_it_is_discoverable_as_a_skill(self) -> None:
        document = frontmatter.parse(SKILL.read_bytes())
        assert document.front is not None, "the skill has no frontmatter, so no harness can index it"
        assert document.front.get("name") == "akit"
        assert document.front.get("description"), "a skill with no description is never opened"
        assert document.body.strip()

    def test_it_cites_nothing_the_reader_does_not_have(self) -> None:
        for path, text in EVERYTHING.items():
            for forbidden in ("DESIGN.md", "IMPLEMENTATION.md", "JOURNAL.md", "\u00a7"):
                assert forbidden not in text, f"{path.name} cites {forbidden}, which a copied skill cannot follow"
            assert not re.search(r"\bsection \d", text, re.IGNORECASE), f"{path.name} cites a section number"

    def test_it_names_no_path_this_project_does_not_own(self) -> None:
        for path, text in EVERYTHING.items():
            for foreign in FOREIGN_PATHS:
                assert foreign not in text, (
                    f"{path.name} names {foreign}, a path belonging to a harness. "
                    "Ask the harness where its instructions live instead."
                )

    def test_it_never_tells_the_model_to_open_another_skill(self) -> None:
        for path, text in EVERYTHING.items():
            found = OPENS_A_SKILL.search(prose_and_code(text)[0])
            assert found is None, f"{path.name} reaches for another skill: {found.group(0)}"

    def test_every_reference_it_links_to_is_there(self) -> None:
        linked = set(re.findall(r"\]\((references/[a-z0-9-]+\.md)\)", SKILL_TEXT))
        assert linked, "the skill links to none of its references, so they are dead weight"
        for relative in sorted(linked):
            assert (SKILL.parent / relative).is_file(), f"the skill links to {relative}, which is not there"
        for reference in EVERYTHING:
            if reference != SKILL:
                assert f"references/{reference.name}" in SKILL_TEXT, f"{reference.name} is linked from nowhere"


@pytest.mark.unit
class TestEveryCommandItNamesExists:
    """Asked of the command registry rather than of a grep, so a rename fails here."""

    def test_the_commands(self) -> None:
        for path, text in EVERYTHING.items():
            for found in invocations(text):
                command = found.group("command")
                assert command in commands.BY_NAME, (
                    f"{path.name} names `akit {command}`, which the CLI does not register"
                )

    def test_the_help_topics(self) -> None:
        topics = {
            found.group("argument")
            for text in EVERYTHING.values()
            for found in invocations(text)
            if found.group("command") == "help" and found.group("argument")
        }
        assert topics, "the skill never points at `akit help`, which is where the four concepts live"
        for topic in sorted(topics):
            assert topic in commands.TOPICS_BY_NAME, f"`akit help {topic}` is not a topic"

    def test_it_points_at_every_topic_there_is(self) -> None:
        """All four, because a concept nobody is sent to is a concept nobody reads."""
        named = {
            found.group("argument")
            for text in EVERYTHING.values()
            for found in invocations(text)
            if found.group("command") == "help"
        }
        assert set(commands.TOPICS_BY_NAME) <= named


@pytest.mark.unit
class TestTheRuleAndTheSkillAgree:
    """The rule is offered by the skill and shipped beside it, in one wording."""

    def test_the_rule_declares_what_it_is_for(self) -> None:
        document = frontmatter.parse(RULE.read_bytes())
        assert document.front is not None and document.front.get("name") == "akit"
        assert document.front.get("description")
        assert document.body.strip()

    def test_the_text_the_skill_offers_is_the_rule_it_ships(self) -> None:
        """Two copies of five lines drift, and the drift is invisible to a reader.

        The reference offers the text to paste into a harness that has no
        subscription yet; `rules/akit.md` is the same text, subscribed to. They
        have to say the same thing, or placing it by hand and subscribing to it
        install two different rules under one name.
        """
        reference = read(REFERENCES / "activation-rule.md")
        offered = re.search(r"```markdown\n(?P<text>.*?)```", reference, re.S)
        assert offered is not None, "the activation reference offers no text to place"
        assert offered.group("text").strip() == frontmatter.parse(RULE.read_bytes()).body.strip()


@pytest.mark.unit
def test_the_version_beside_the_skill_is_the_package_version() -> None:
    """A copied skill cannot tell how old it is any other way.

    Both are written by the release job, in one commit, from one number. This is
    the test that fails when somebody edits one of them by hand.
    """
    declared = re.search(r'^version = "(?P<version>[^"]+)"$', read(REPO_ROOT / "pyproject.toml"), re.M)
    assert declared is not None
    assert read(VERSION_FILE).strip() == declared.group("version")


@pytest.mark.cli
def test_akit_installs_its_own_skill_into_a_fresh_home(fake_home: FakeHome) -> None:
    """The hand-placed first copy becomes a managed one, from this repository.

    A path source rather than a clone, because what is under test is that this
    repository is shaped the way the discovery walk expects: the skill and the
    rule carry one name, so one `add` takes both.

    The harness is named rather than detected, because a fake home has no
    harness installed in it and detection is `test_adapters.py`'s subject.
    """
    named = fake_home.run("harness", "add", "--global", "opencode")
    assert named.returncode == Exit.OK, named.stderr

    added = fake_home.run("add", "--global", str(REPO_ROOT), "akit")
    assert added.returncode == Exit.OK, added.stderr

    skill = fake_home.root / ".agents" / "skills" / "akit" / "SKILL.md"
    assert skill.is_file(), added.stdout
    assert "name: akit" in read(skill)
    assert (skill.parent / "references" / "activation-rule.md").is_file(), "the references did not travel with it"
    assert (skill.parent / "VERSION").is_file(), "a copied skill with no VERSION cannot tell how old it is"

    listed = fake_home.run("list")
    assert listed.returncode == Exit.OK, listed.stderr
    assert "akit" in listed.stdout
    assert "rules akit" in listed.stdout, "the rule did not come with the skill, so the kit arrived in halves"
