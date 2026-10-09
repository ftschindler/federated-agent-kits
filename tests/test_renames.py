"""The rename note, the identity a rename rewrites, and the edit a render replaces.

Three behaviours that arrived together because they are one question asked three
times: what does `as:` actually change?

**The identity.** Renaming the directory and leaving `name: writing` in the
copied `SKILL.md` renamed nothing anywhere it mattered, which is the bug
JOURNAL.md records and the first class below pins down.

**The reference.** A rule from the same source still names the kit the way its
author wrote it, so a rename leaves a sentence pointing at a skill that is not
there. The note is what answers that, and the tests here are about when it
appears and when it goes rather than about its wording.

**The edit.** A rendered file something still explains is refreshed from its
source, so an edit to one is replaced rather than kept. That was always true and
was always silent, and the last class is about it being said out loud.

A path source throughout, so this is the `unit` layer: nothing here needs git or
a network, because what is being tested is what gets written rather than how a
source was found.
"""

from __future__ import annotations

import io
import textwrap
from pathlib import Path

import pytest

from federated_agent_kits import adapters, record, renames, render, rules, skills
from federated_agent_kits.adapters.adapter import Adapter, Destination, RuleShape
from federated_agent_kits.exits import Exit
from federated_agent_kits.manifest import Kind, Scope
from federated_agent_kits.renames import Rename

pytestmark = pytest.mark.unit

SKILLS = Path(".agents") / "skills"

#: A rule that names its kit the way a real one does: backticked, beside the
#: word "skill", and with the same token used as an ordinary verb on the same
#: line. Taken from a rule in the wild, because the thing that makes this hard
#: is that both readings are idiomatic.
REFERRING_RULE = "---\ndescription: house style\n---\n\n**Load the `writing` skill** when writing a draft.\n"


def build(root: Path, layout: dict[str, str]) -> Path:
    for relative, text in layout.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


def subscribe(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    return path


@pytest.fixture
def kits(tmp_path: Path) -> Path:
    """A source whose rule names its own skill, which is what makes it a kit."""
    return build(
        tmp_path / "kits",
        {
            "skills/writing/SKILL.md": "---\nname: writing\ndescription: prose\n---\n\n# writing\n",
            "skills/writing/references/style.md": "# style\n",
            "rules/writing.md": REFERRING_RULE,
            "rules/unrelated.md": "---\ndescription: other\n---\n\nNothing to do with it.\n",
        },
    )


@pytest.fixture
def home(tmp_path: Path) -> Path:
    root = tmp_path / "home"
    (root / ".config" / "opencode").mkdir(parents=True)
    (root / ".vscode").mkdir(parents=True)
    return root


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    return root


@pytest.fixture
def places(tmp_path: Path, home: Path) -> render.Directories:
    return render.Directories(
        home=home,
        user_manifest=tmp_path / "config" / "manifest.yaml",
        cache=tmp_path / "cache",
        state=tmp_path / "state",
    )


def manifest_with(project: Path, kits: Path, *, rename: str | None, rule: bool = True) -> Path:
    """The repository subscribing to the skill, renamed or not, and to its rule."""
    skill = f'["{rename and "*"}"]' if False else ""
    entry = "[writing]" if rename is None else f"\n  - name: writing\n    as: {rename}"
    body = f"version: 1\n\nskills:\n  {kits}: {entry}\n"
    if rule:
        rule_entry = "writing" if rename is None else f"\n    name: writing\n    as: {rename}"
        body += f"\nrules:\n- {kits}: {rule_entry}\n"
    return subscribe(project / ".akit.yaml", body + skill)


def agents_md(project: Path) -> str:
    return (project / "AGENTS.md").read_text(encoding="utf-8")


class TestASkillsIdentityFollowsItsRename:
    """DESIGN.md section 7: the frontmatter name is what a skill *is*."""

    def test_a_renamed_skill_carries_the_name_it_is_installed_under(
        self, project: Path, places: render.Directories, kits: Path
    ):
        manifest_with(project, kits, rename="felix-writing", rule=False)

        render.render(project, places)

        copied = (project / SKILLS / "felix-writing" / "SKILL.md").read_text(encoding="utf-8")
        assert "name: felix-writing" in copied
        assert "name: writing" not in copied

    def test_everything_else_the_author_wrote_survives_the_rewrite(
        self, project: Path, places: render.Directories, kits: Path
    ):
        manifest_with(project, kits, rename="felix-writing", rule=False)

        render.render(project, places)

        copied = (project / SKILLS / "felix-writing" / "SKILL.md").read_text(encoding="utf-8")
        assert "description: prose" in copied
        assert copied.endswith("# writing\n")

    def test_a_skill_nobody_renamed_is_copied_byte_for_byte(
        self, project: Path, places: render.Directories, kits: Path
    ):
        manifest_with(project, kits, rename=None, rule=False)

        render.render(project, places)

        assert (project / SKILLS / "writing" / "SKILL.md").read_bytes() == (
            kits / "skills" / "writing" / "SKILL.md"
        ).read_bytes()

    def test_the_files_a_skill_leans_on_are_never_rewritten(
        self, project: Path, places: render.Directories, kits: Path
    ):
        manifest_with(project, kits, rename="felix-writing", rule=False)

        render.render(project, places)

        assert (project / SKILLS / "felix-writing" / "references" / "style.md").read_bytes() == (
            kits / "skills" / "writing" / "references" / "style.md"
        ).read_bytes()

    def test_rewriting_the_identity_stays_idempotent(self, project: Path, places: render.Directories, kits: Path):
        manifest_with(project, kits, rename="felix-writing", rule=False)
        render.render(project, places)

        again = render.render(project, places)

        assert again.quiet

    def test_a_skill_with_no_frontmatter_is_left_exactly_as_it_was(self, tmp_path: Path):
        data = b"# writing\n\nNo header at all.\n"

        assert skills.as_copied(data, name="renamed") == data

    def test_a_skill_whose_header_is_not_yaml_is_refused_by_name(self):
        with pytest.raises(skills.SkillError, match='the skill "renamed"'):
            skills.as_copied(b"---\nkey: [unclosed\n---\n\nBody.\n", name="renamed")


class TestWhenARenameIsWrittenDown:
    """The note, which exists only where a rule would otherwise be wrong."""

    def test_a_rule_naming_a_renamed_kit_gets_the_note(self, project: Path, places: render.Directories, kits: Path):
        manifest_with(project, kits, rename="felix-writing")

        render.render(project, places)

        assert "BEGIN akit akit-renames" in agents_md(project)
        assert "`writing` is installed as `felix-writing`" in agents_md(project)

    def test_no_rename_means_no_note(self, project: Path, places: render.Directories, kits: Path):
        manifest_with(project, kits, rename=None)

        render.render(project, places)

        assert "akit-renames" not in agents_md(project)

    def test_a_rename_no_rule_refers_to_writes_nothing(self, project: Path, places: render.Directories, kits: Path):
        subscribe(
            project / ".akit.yaml",
            f"""
            version: 1

            skills:
              {kits}:
              - name: writing
                as: felix-writing

            rules:
            - {kits}: unrelated
            """,
        )

        render.render(project, places)

        assert "akit-renames" not in agents_md(project)

    def test_the_note_goes_when_the_rename_does(self, project: Path, places: render.Directories, kits: Path):
        manifest_with(project, kits, rename="felix-writing")
        render.render(project, places)
        manifest_with(project, kits, rename=None)

        outcome = render.render(project, places)

        assert "akit-renames" not in agents_md(project)
        assert any(entry.region == "akit-renames" and entry.action == "deleted" for entry in outcome.withdrawals)

    def test_the_host_file_keeps_its_other_blocks_when_the_note_goes(
        self, project: Path, places: render.Directories, kits: Path
    ):
        manifest_with(project, kits, rename="felix-writing")
        render.render(project, places)
        manifest_with(project, kits, rename=None)

        render.render(project, places)

        assert "BEGIN akit writing" in agents_md(project)
        assert "Load the `writing` skill" in agents_md(project)

    def test_the_note_is_idempotent(self, project: Path, places: render.Directories, kits: Path):
        manifest_with(project, kits, rename="felix-writing")
        render.render(project, places)

        again = render.render(project, places)

        assert again.quiet

    def test_the_record_explains_the_note_so_nothing_has_to_guess(
        self, project: Path, places: render.Directories, kits: Path
    ):
        manifest_with(project, kits, rename="felix-writing")

        render.render(project, places)

        found = record.load(record.project_location(project))
        assert found.holds(project / "AGENTS.md", "akit-renames")

    def test_a_directory_shaped_harness_gets_the_note_as_a_file(
        self, project: Path, places: render.Directories, kits: Path
    ):
        manifest_with(project, kits, rename="felix-writing")

        render.render(project, places)

        written = project / ".github" / "instructions" / "akit-renames.instructions.md"
        assert written.is_file()
        assert "applyTo" in written.read_text(encoding="utf-8")


class TestWhatCountsAsNamingAKit:
    """The search, which is deliberately loose in one direction and not the other."""

    @pytest.mark.parametrize(
        "body",
        [
            "Load the `writing` skill.",
            "Load the writing skill.",
            "See writing, which is the house style.",
            "writing",
        ],
    )
    def test_a_whole_word_counts_backticked_or_bare(self, body: str):
        found = renames.referenced(
            [Rename(source="s", original="writing", rendered="felix-writing")], "s", body.encode()
        )

        assert found

    @pytest.mark.parametrize("body", ["Try rewriting it.", "See writings.", "writing-style is different."])
    def test_a_name_inside_another_word_does_not(self, body: str):
        found = renames.referenced(
            [Rename(source="s", original="writing", rendered="felix-writing")], "s", body.encode()
        )

        assert not found

    def test_a_rule_from_another_source_is_talking_about_something_else(self):
        found = renames.referenced(
            [Rename(source="theirs", original="writing", rendered="felix-writing")],
            "mine",
            b"Load the `writing` skill.",
        )

        assert not found

    def test_the_frontmatter_is_not_searched(self):
        found = renames.referenced(
            [Rename(source="s", original="writing", rendered="felix-writing")],
            "s",
            b"---\nname: writing\n---\n\nNothing in the body.\n",
        )

        assert not found

    def test_the_note_is_ordered_by_the_name_a_rule_will_say(self):
        one = renames.note(
            [
                Rename(source="s", original="zebra", rendered="z2"),
                Rename(source="s", original="apple", rendered="a2"),
            ]
        )
        other = renames.note(
            [
                Rename(source="s", original="apple", rendered="a2"),
                Rename(source="s", original="zebra", rendered="z2"),
            ]
        )

        assert one == other
        assert one.index(b"apple") < one.index(b"zebra")


class TestTheReservedId:
    def test_a_subscription_may_not_take_the_name_the_note_uses(self):
        with pytest.raises(rules.RuleError, match="`akit` writes its own rules under"):
            rules.check_name("akit-renames")

    def test_the_renderer_may(self):
        rules.check_name("akit-renames", ours=True)

    def test_the_refusal_names_the_way_out(self):
        with pytest.raises(rules.RuleError, match="as: <another-name>"):
            rules.as_block(b"body\n", name="akit-renames")


class TestReplacingAnEditIsSaidOutLoud:
    """DESIGN.md section 10: an explained file is refreshed, and that is reported."""

    def test_an_edited_copy_that_is_still_subscribed_is_overwritten(
        self, project: Path, places: render.Directories, kits: Path
    ):
        manifest_with(project, kits, rename=None, rule=False)
        render.render(project, places)
        copied = project / SKILLS / "writing" / "SKILL.md"
        copied.write_text("mine\n", encoding="utf-8")

        render.render(project, places)

        assert copied.read_bytes() == (kits / "skills" / "writing" / "SKILL.md").read_bytes()

    def test_and_the_render_names_it_rather_than_counting_it(
        self, project: Path, places: render.Directories, kits: Path
    ):
        manifest_with(project, kits, rename=None, rule=False)
        render.render(project, places)
        copied = project / SKILLS / "writing" / "SKILL.md"
        copied.write_text("mine\n", encoding="utf-8")

        outcome = render.render(project, places)

        assert (copied.resolve(), None) in outcome.replaced

    def test_an_edited_block_is_named_too(self, project: Path, places: render.Directories, kits: Path):
        manifest_with(project, kits, rename=None)
        render.render(project, places)
        host = project / "AGENTS.md"
        host.write_text(agents_md(project).replace("Load the `writing` skill", "mine"), encoding="utf-8")

        outcome = render.render(project, places)

        assert (host.resolve(), "writing") in outcome.replaced

    def test_a_deleted_copy_is_a_restore_and_not_a_replacement(
        self, project: Path, places: render.Directories, kits: Path
    ):
        manifest_with(project, kits, rename=None, rule=False)
        render.render(project, places)
        (project / SKILLS / "writing" / "SKILL.md").unlink()

        outcome = render.render(project, places)

        assert not outcome.replaced
        assert (project / SKILLS / "writing" / "SKILL.md").is_file()

    def test_an_untouched_render_replaces_nothing(self, project: Path, places: render.Directories, kits: Path):
        manifest_with(project, kits, rename=None, rule=False)
        render.render(project, places)

        outcome = render.render(project, places)

        assert not outcome.replaced

    def test_an_ordinary_update_from_a_changed_source_is_not_a_replacement(
        self, project: Path, places: render.Directories, kits: Path
    ):
        manifest_with(project, kits, rename=None, rule=False)
        render.render(project, places)
        (kits / "skills" / "writing" / "SKILL.md").write_text("# rewritten upstream\n", encoding="utf-8")

        outcome = render.render(project, places)

        assert not outcome.replaced
        assert outcome.written

    def test_the_report_says_so_in_sentences(self, project: Path, places: render.Directories, kits: Path):
        manifest_with(project, kits, rename=None, rule=False)
        render.render(project, places)
        (project / SKILLS / "writing" / "SKILL.md").write_text("mine\n", encoding="utf-8")

        out = io.StringIO()
        render.text(render.render(project, places), out)

        printed = out.getvalue()
        assert "had been edited since it was rendered" in printed
        assert "subscribe to a kit of your own" in printed


class TestTheNoteTravelsWithItsSourcesPrivacy:
    def test_the_note_is_explained_by_the_source_it_describes(
        self, project: Path, places: render.Directories, kits: Path
    ):
        manifest_with(project, kits, rename="felix-writing")

        render.render(project, places)

        found = record.load(record.project_location(project))
        entry = next(written for written in found.written if written.region == "akit-renames")
        assert any(explained.source == str(kits) for explained in entry.explanations)
        assert all(explained.kind is Kind.RULE for explained in entry.explanations)


class TestTheNoteInEveryScope:
    def test_a_user_scope_rename_puts_the_note_in_the_user_scope(
        self, project: Path, places: render.Directories, kits: Path, home: Path
    ):
        assert places.user_manifest is not None
        subscribe(
            places.user_manifest,
            f"""
            version: 1

            skills:
              {kits}:
              - name: writing
                as: felix-writing

            rules:
            - {kits}:
                name: writing
                as: felix-writing
            """,
        )

        render.render(project, places, render.Choices(scopes=(Scope.USER,)))

        assert "akit-renames" in (home / ".config" / "opencode" / "AGENTS.md").read_text(encoding="utf-8")


#: A harness that takes skills and declines rules, which is the mirror image of
#: `test_render.py`'s fixture and the one shape that makes a rename note
#: impossible to place. Declining a kind is a first-class answer (DESIGN.md
#: section 4), so the note has to arrive at "nowhere to put this" and say
#: nothing rather than crash.
PAPER = Adapter(
    name="paper",
    summary="a harness that takes no rules at all",
    has_a_machine=True,
    destinations={(Kind.SKILL, Scope.PROJECT): Destination(write=".agents/skills")},
    rule_shape=RuleShape.DIRECTORY,
    evidence=(".paper",),
)


class TestAHarnessWithNowhereToPutTheNote:
    @pytest.fixture
    def only_paper(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(adapters, "ADAPTERS", (PAPER,))
        monkeypatch.setattr(adapters, "BY_NAME", {PAPER.name: PAPER})

    def test_a_rename_nobody_can_be_told_about_writes_no_note_and_crashes_nothing(
        self, project: Path, places: render.Directories, kits: Path, home: Path, only_paper: None
    ):
        (home / ".paper").mkdir(parents=True, exist_ok=True)
        (project / ".paper").mkdir(parents=True, exist_ok=True)
        manifest_with(project, kits, rename="felix-writing")

        outcome = render.render(project, places)

        assert outcome.exit_code is Exit.OK
        assert not (project / "AGENTS.md").exists()
        assert all(entry.name != "akit-renames" for entry in outcome.entries)
        assert (project / SKILLS / "felix-writing" / "SKILL.md").is_file()
