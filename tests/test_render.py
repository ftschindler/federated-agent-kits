"""`akit render`: what it writes, what it refuses to delete, and what it does twice.

Every test here is about the second half of the sentence. Writing files is the
easy part and one test covers it; the rest of this file is the withdrawal table
from DESIGN.md section 10, one row at a time, plus the two cases that suspend
withdrawal altogether.

A path source throughout, so this stays in the `unit` layer and needs neither
git nor a network. That a `file://` source renders identically is a `cli` test,
because what differs between the two is resolution rather than rendering.
"""

from __future__ import annotations

import hashlib
import io
import json
import textwrap
from pathlib import Path

import pytest

from federated_agent_kits import adapters, ignore, privacy, record, render
from federated_agent_kits.adapters.adapter import Adapter, Destination, RuleShape
from federated_agent_kits.cache import Privacy
from federated_agent_kits.cli import build_parser, dispatch
from federated_agent_kits.exits import Exit, UsageError
from federated_agent_kits.manifest import Kind, Scope

pytestmark = pytest.mark.unit

SKILLS = Path(".agents") / "skills"


def build(root: Path, layout: dict[str, str]) -> Path:
    for relative, text in layout.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


def project_record(project: Path) -> record.Record:
    """What the repository's own record says, which is where a project render lands."""
    return record.load(record.project_location(project))


def user_record(places: render.Directories) -> record.Record:
    """What your machine's record says, which is the other half and never the same file."""
    return record.load(record.user_location(places.state))


def tree(root: Path) -> dict[str, str]:
    """Every file under a directory, by hash, which is what idempotence is about."""
    if not root.is_dir():
        return {}
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


@pytest.fixture
def kits(tmp_path: Path) -> Path:
    """A source with two skills, a rule and an agent, none of which it declared."""
    return build(
        tmp_path / "kits",
        {
            "skills/writing/SKILL.md": "# writing\n",
            "skills/writing/references/style.md": "# style\n",
            "skills/fkb/SKILL.md": "# fkb\n",
            "rules/prose-style.md": "# prose\n",
            "agents/reviewer.md": "# reviewer\n",
        },
    )


@pytest.fixture
def home(tmp_path: Path) -> Path:
    """A machine with both shipped harnesses installed, by their own evidence."""
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


def subscribe(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    return path


@pytest.fixture
def one_skill(project: Path, kits: Path) -> Path:
    """The ordinary setup: this repository wants one skill from a path source."""
    return subscribe(
        project / ".akit.yaml",
        f"""
        version: 1

        skills:
          {kits}: [writing]
        """,
    )


class TestWhatARenderPutsOnDisk:
    def test_a_subscribed_skill_lands_where_both_harnesses_read_it(
        self, project: Path, places: render.Directories, one_skill: Path
    ):
        outcome = render.render(project, places)

        assert (project / SKILLS / "writing" / "SKILL.md").read_text(encoding="utf-8") == "# writing\n"
        assert (project / SKILLS / "writing" / "references" / "style.md").is_file()
        assert outcome.exit_code is Exit.OK

    def test_one_copy_serves_both_harnesses_rather_than_one_each(
        self, project: Path, places: render.Directories, one_skill: Path
    ):
        outcome = render.render(project, places)

        placements = [place for entry in outcome.entries for place in entry.placements]
        assert len(placements) == 1
        assert sorted(placements[0].harnesses) == ["copilot-vscode", "opencode"]

    def test_a_second_render_changes_nothing_at_all(self, project: Path, places: render.Directories, one_skill: Path):
        render.render(project, places)
        before = tree(project / SKILLS)

        outcome = render.render(project, places)

        assert tree(project / SKILLS) == before
        assert outcome.quiet
        assert outcome.written == 0

    def test_deleting_the_rendered_tree_restores_it_byte_for_byte(
        self, project: Path, places: render.Directories, one_skill: Path
    ):
        render.render(project, places)
        before = tree(project / SKILLS)
        for path in sorted((project / SKILLS).rglob("*"), key=lambda entry: -len(entry.parts)):
            path.rmdir() if path.is_dir() else path.unlink()

        render.render(project, places)

        assert tree(project / SKILLS) == before

    def test_a_renamed_kit_lands_under_the_new_name_and_the_record_knows_both(
        self, project: Path, places: render.Directories, kits: Path
    ):
        subscribe(
            project / ".akit.yaml",
            f"""
            version: 1

            skills:
              {kits}:
              - name: writing
                as: house-style
            """,
        )

        outcome = render.render(project, places)

        assert (project / SKILLS / "house-style" / "SKILL.md").is_file()
        assert not (project / SKILLS / "writing").exists()
        entry = outcome.entries[0]
        assert (entry.name, entry.found_as) == ("house-style", "writing")
        written = project_record(project).written[0]
        assert any(found.name == "house-style" for found in written.explanations)

    def test_your_subscriptions_land_in_your_home_and_a_repositorys_inside_it(
        self, project: Path, places: render.Directories, kits: Path, one_skill: Path
    ):
        assert places.user_manifest is not None
        subscribe(
            places.user_manifest,
            f"""
            version: 1

            skills:
              {kits}: [fkb]
            """,
        )

        render.render(project, places)

        assert (places.home / SKILLS / "fkb" / "SKILL.md").is_file()
        assert not (project / SKILLS / "fkb").exists()
        assert not (places.home / SKILLS / "writing").exists()


class TestTheKindThatIsNotRenderedYet:
    def test_an_agent_is_declined_by_every_adapter_and_crashes_nothing(
        self, project: Path, places: render.Directories, kits: Path
    ):
        subscribe(
            project / ".akit.yaml",
            f"""
            version: 1

            agents:
              {kits}: [reviewer]
            """,
        )

        outcome = render.render(project, places)

        assert "T13" in (outcome.entries[0].waiting or "")
        assert outcome.exit_code is Exit.OK


class TestWithdrawal:
    """One test per row of the table in DESIGN.md section 10, and then the edges."""

    def test_an_unsubscribed_kit_whose_copy_is_untouched_is_deleted(
        self, project: Path, places: render.Directories, kits: Path, one_skill: Path
    ):
        render.render(project, places)
        subscribe(project / ".akit.yaml", f"version: 1\n\nskills:\n  {kits}: [fkb]\n")

        outcome = render.render(project, places)

        assert not (project / SKILLS / "writing").exists()
        assert (project / SKILLS / "fkb" / "SKILL.md").is_file()
        assert [entry.action for entry in outcome.withdrawals] == ["deleted", "deleted"]

    def test_a_rendered_copy_somebody_edited_is_left_alone_and_named(
        self, project: Path, places: render.Directories, kits: Path, one_skill: Path
    ):
        render.render(project, places)
        edited = project / SKILLS / "writing" / "SKILL.md"
        edited.write_text("# writing, with my own paragraph\n", encoding="utf-8")
        subscribe(project / ".akit.yaml", f"version: 1\n\nskills:\n  {kits}: [fkb]\n")

        outcome = render.render(project, places)

        assert edited.read_text(encoding="utf-8") == "# writing, with my own paragraph\n"
        assert any(entry.action == "kept" and entry.path == edited.resolve() for entry in outcome.withdrawals)

    def test_an_edited_copy_survives_three_renders_rather_than_two(
        self, project: Path, places: render.Directories, kits: Path, one_skill: Path
    ):
        render.render(project, places)
        edited = project / SKILLS / "writing" / "SKILL.md"
        edited.write_text("# mine now\n", encoding="utf-8")
        subscribe(project / ".akit.yaml", f"version: 1\n\nskills:\n  {kits}: [fkb]\n")

        for _ in range(3):
            outcome = render.render(project, places)

        assert edited.read_text(encoding="utf-8") == "# mine now\n"
        assert any(entry.action == "kept" for entry in outcome.withdrawals)

    def test_a_hand_written_skill_is_never_touched_because_it_is_not_in_the_record(
        self, project: Path, places: render.Directories, kits: Path, one_skill: Path
    ):
        mine = project / SKILLS / "mine" / "SKILL.md"
        mine.parent.mkdir(parents=True)
        mine.write_text("# mine\n", encoding="utf-8")

        render.render(project, places)
        subscribe(project / ".akit.yaml", "version: 1\n")
        render.render(project, places)

        assert mine.read_text(encoding="utf-8") == "# mine\n"

    def test_a_file_already_gone_is_reported_and_stops_being_recorded(
        self, project: Path, places: render.Directories, kits: Path, one_skill: Path
    ):
        render.render(project, places)
        (project / SKILLS / "writing" / "references" / "style.md").unlink()
        subscribe(project / ".akit.yaml", "version: 1\n")

        outcome = render.render(project, places)

        assert sorted(entry.action for entry in outcome.withdrawals) == ["deleted", "gone"]
        assert project_record(project).written == ()

    def test_withdrawing_the_last_file_takes_the_empty_directory_with_it(
        self, project: Path, places: render.Directories, one_skill: Path
    ):
        render.render(project, places)
        subscribe(project / ".akit.yaml", "version: 1\n")

        render.render(project, places)

        assert not (project / SKILLS / "writing").exists()
        assert not (project / ".agents").exists()

    def test_a_shared_copy_survives_one_harness_leaving_and_goes_with_the_second(
        self, project: Path, places: render.Directories, kits: Path
    ):
        subscribe(project / ".akit.yaml", f"version: 1\nharnesses: [detected]\n\nskills:\n  {kits}: [writing]\n")
        render.render(project, places)
        copy = project / SKILLS / "writing" / "SKILL.md"

        subscribe(project / ".akit.yaml", f"version: 1\nharnesses: [opencode]\n\nskills:\n  {kits}: [writing]\n")
        render.render(project, places)
        assert copy.is_file()

        subscribe(project / ".akit.yaml", "version: 1\nharnesses: [opencode]\n")
        render.render(project, places)
        assert not copy.exists()

    def test_a_render_of_one_scope_never_withdraws_the_other_scopes_files(
        self, project: Path, places: render.Directories, kits: Path, one_skill: Path
    ):
        assert places.user_manifest is not None
        subscribe(places.user_manifest, f"version: 1\n\nskills:\n  {kits}: [fkb]\n")
        render.render(project, places)
        subscribe(places.user_manifest, "version: 1\n")

        render.render(project, places, render.Choices(scopes=(Scope.PROJECT,)))

        assert (places.home / SKILLS / "fkb" / "SKILL.md").is_file()
        assert (project / SKILLS / "writing" / "SKILL.md").is_file()


class TestWhenWithdrawalIsSuspended:
    def test_no_harness_skips_work_and_deletes_nothing(
        self, project: Path, places: render.Directories, kits: Path, one_skill: Path
    ):
        render.render(project, places)
        subscribe(project / ".akit.yaml", "version: 1\n")

        outcome = render.render(project, places, render.Choices(without=("opencode",)))

        assert (project / SKILLS / "writing" / "SKILL.md").is_file()
        assert outcome.withdrawals == ()
        assert outcome.suspended is not None

    def test_harness_narrows_to_one_and_still_deletes_nothing(
        self, project: Path, places: render.Directories, one_skill: Path
    ):
        outcome = render.render(project, places, render.Choices(only=("opencode",)))

        assert outcome.harnesses[Scope.PROJECT] == ("opencode",)
        assert (project / SKILLS / "writing" / "SKILL.md").is_file()
        assert outcome.suspended is not None

    def test_a_source_that_cannot_be_resolved_stops_every_deletion(
        self, project: Path, places: render.Directories, kits: Path, tmp_path: Path, one_skill: Path
    ):
        render.render(project, places)
        subscribe(project / ".akit.yaml", f"version: 1\n\nskills:\n  {tmp_path / 'gone'}: [writing]\n")

        outcome = render.render(project, places)

        assert (project / SKILLS / "writing" / "SKILL.md").is_file()
        assert outcome.suspended is not None
        assert outcome.exit_code is Exit.ERROR

    def test_a_kit_the_source_does_not_hold_is_a_problem_rather_than_a_crash(
        self, project: Path, places: render.Directories, kits: Path
    ):
        subscribe(project / ".akit.yaml", f"version: 1\n\nskills:\n  {kits}: [absent]\n")

        outcome = render.render(project, places)

        assert outcome.problems
        assert outcome.exit_code is Exit.ERROR


class TestPruning:
    def test_a_lost_record_leaves_orphans_that_only_prune_removes(
        self, project: Path, places: render.Directories, kits: Path, one_skill: Path
    ):
        render.render(project, places)
        record.project_location(project).unlink()
        subscribe(project / ".akit.yaml", "version: 1\n")

        render.render(project, places)
        assert (project / SKILLS / "writing" / "SKILL.md").is_file()

        outcome = render.render(project, places, render.Choices(prune=True))

        assert not (project / SKILLS / "writing").exists()
        assert outcome.pruned

    def test_pruning_leaves_what_the_record_still_explains(
        self, project: Path, places: render.Directories, one_skill: Path
    ):
        render.render(project, places)

        outcome = render.render(project, places, render.Choices(prune=True))

        assert (project / SKILLS / "writing" / "SKILL.md").is_file()
        assert outcome.pruned == ()

    def test_pruning_is_suspended_with_everything_else_when_a_flag_narrows(
        self, project: Path, places: render.Directories, one_skill: Path
    ):
        render.render(project, places)
        record.project_location(project).unlink()
        subscribe(project / ".akit.yaml", "version: 1\n")

        outcome = render.render(project, places, render.Choices(prune=True, only=("opencode",)))

        assert (project / SKILLS / "writing" / "SKILL.md").is_file()
        assert outcome.pruned == ()


class TestTheIgnoreBlock:
    def test_a_rendered_directory_is_listed_in_the_repositorys_gitignore(
        self, project: Path, places: render.Directories, one_skill: Path
    ):
        render.render(project, places)

        written = (project / ignore.GITIGNORE).read_text(encoding="utf-8")
        assert ".agents/skills/" in written
        assert written.startswith(ignore.BEGIN)

    def test_the_users_own_lines_and_their_order_survive(
        self, project: Path, places: render.Directories, one_skill: Path
    ):
        (project / ignore.GITIGNORE).write_text("*.pyc\n\n# mine\nbuild/\n", encoding="utf-8")

        render.render(project, places)
        render.render(project, places)

        written = (project / ignore.GITIGNORE).read_text(encoding="utf-8")
        assert written.splitlines()[:4] == ["*.pyc", "", "# mine", "build/"]

    def test_nothing_rendered_in_this_repository_leaves_no_block_behind(
        self, project: Path, places: render.Directories, one_skill: Path
    ):
        render.render(project, places)
        subscribe(project / ".akit.yaml", "version: 1\nharnesses: []\n")

        render.render(project, places)

        assert ignore.BEGIN not in (project / ignore.GITIGNORE).read_text(encoding="utf-8")

    def test_a_render_outside_any_repository_touches_no_gitignore(self, tmp_path: Path, places: render.Directories):
        loose = tmp_path / "loose"
        loose.mkdir()

        outcome = render.render(loose, places)

        assert outcome.ignored == ()
        assert not (loose / ignore.GITIGNORE).exists()


class TestTheRecordItWrites:
    def test_every_written_file_is_recorded_with_what_explains_it(
        self, project: Path, places: render.Directories, kits: Path, one_skill: Path
    ):
        render.render(project, places)

        written = project_record(project)
        assert len(written.written) == 2
        entry = next(found for found in written.written if found.path.name == "SKILL.md")
        assert entry.harnesses == frozenset({"opencode", "copilot-vscode"})
        assert entry.still_a_copy()
        explanation = entry.explanations[0]
        assert (explanation.kind, explanation.name) == (Kind.SKILL, "writing")

    def test_a_project_render_writes_nothing_into_your_own_record(
        self, project: Path, places: render.Directories, one_skill: Path
    ):
        render.render(project, places)

        assert user_record(places).written == ()
        assert record.user_location(places.state).exists() is False

    def test_a_render_leaves_the_source_classifications_alone(
        self, project: Path, places: render.Directories, one_skill: Path
    ):
        """They are machine state about the cache and no business of a render.

        `render` never fetches, so it never learns a classification, and the
        file lives beside the record rather than inside it precisely so that a
        render has nothing to carry forward and nothing to drop.
        """
        privacy.save({"acme/kits": Privacy.PRIVATE}, places.state)

        render.render(project, places)

        assert privacy.load(places.state) == {"acme/kits": Privacy.PRIVATE}


class TestTwoRepositoriesOnOneMachine:
    """The reason there are two records rather than one.

    A single machine-wide record made each of these a bug: the second render
    rewrote the first's entries, and a render in one repository could withdraw
    the other's files because scope says which manifest and not which checkout.
    """

    @pytest.fixture
    def second(self, tmp_path: Path, kits: Path) -> Path:
        root = tmp_path / "other"
        (root / ".git").mkdir(parents=True)
        subscribe(root / ".akit.yaml", f"version: 1\n\nskills:\n  {kits}: [fkb]\n")
        return root

    def test_each_repository_keeps_its_own_record(
        self, project: Path, places: render.Directories, second: Path, one_skill: Path
    ):
        render.render(project, places)
        render.render(second, places)

        assert [entry.path.name for entry in project_record(project).written] == ["SKILL.md", "style.md"]
        assert [entry.path.name for entry in project_record(second).written] == ["SKILL.md"]

    def test_rendering_in_one_does_not_withdraw_the_others_files(
        self, project: Path, places: render.Directories, second: Path, one_skill: Path
    ):
        render.render(project, places)

        outcome = render.render(second, places)

        assert (project / SKILLS / "writing" / "SKILL.md").is_file()
        assert outcome.withdrawals == ()

    def test_a_repository_that_is_deleted_takes_its_record_with_it(
        self, project: Path, places: render.Directories, second: Path, one_skill: Path
    ):
        render.render(second, places)
        assert record.project_location(second).is_file()

        for path in sorted(second.rglob("*"), key=lambda entry: -len(entry.parts)):
            path.rmdir() if path.is_dir() else path.unlink()
        second.rmdir()

        render.render(project, places)
        assert project_record(project).written


class TestAHomeDirectoryThatIsAlsoARepository:
    """Dotfiles, where the project anchor and the user root are one directory.

    DESIGN.md section 6 says the two scopes never write to the same place, and
    for this one repository that is not true: both land in `~/.agents/skills/`.
    One record handled it without anybody noticing, because one entry carried
    both explanations. Two records have to read each other.
    """

    @pytest.fixture
    def dotfiles(self, places: render.Directories, kits: Path) -> Path:
        (places.home / ".git").mkdir(parents=True)
        subscribe(places.home / ".akit.yaml", f"version: 1\n\nskills:\n  {kits}: [writing]\n")
        assert places.user_manifest is not None
        subscribe(places.user_manifest, f"version: 1\n\nskills:\n  {kits}: [writing]\n")
        return places.home

    def test_both_scopes_land_on_one_path_and_both_records_claim_it(self, dotfiles: Path, places: render.Directories):
        render.render(dotfiles, places)

        copy = dotfiles / SKILLS / "writing" / "SKILL.md"
        assert copy.is_file()
        assert copy.resolve() in project_record(dotfiles).paths
        assert copy.resolve() in user_record(places).paths

    def test_narrowing_to_one_scope_cannot_delete_what_the_other_still_wants(
        self, dotfiles: Path, places: render.Directories
    ):
        render.render(dotfiles, places)
        assert places.user_manifest is not None
        subscribe(places.user_manifest, "version: 1\n")

        render.render(dotfiles, places, render.Choices(scopes=(Scope.USER,)))

        assert (dotfiles / SKILLS / "writing" / "SKILL.md").is_file()

    def test_a_file_both_scopes_explain_is_counted_once(self, dotfiles: Path, places: render.Directories):
        """The per-line report has a placement per scope and the summary must not.

        Found by hand rather than by a test: the first dotfiles render said it
        wrote four files and there were two on disk.
        """
        outcome = render.render(dotfiles, places)

        assert outcome.written == len(tree(dotfiles / SKILLS))
        assert outcome.written == 2

    def test_the_file_goes_when_the_last_of_the_two_stops_wanting_it(self, dotfiles: Path, places: render.Directories):
        render.render(dotfiles, places)
        assert places.user_manifest is not None
        subscribe(places.user_manifest, "version: 1\n")
        subscribe(dotfiles / ".akit.yaml", "version: 1\n")

        render.render(dotfiles, places)

        assert not (dotfiles / SKILLS / "writing").exists()


class TestWhatTheFlagsMayNotDo:
    def test_a_harness_no_adapter_knows_is_a_usage_error_rather_than_a_silent_skip(
        self, project: Path, places: render.Directories, one_skill: Path
    ):
        with pytest.raises(UsageError) as refused:
            render.render(project, places, render.Choices(only=("emacs",)))

        assert "emacs" in str(refused.value)
        assert refused.value.exit_code is Exit.USAGE

    def test_a_harness_a_manifest_names_is_reported_rather_than_refused(
        self, project: Path, places: render.Directories, kits: Path
    ):
        subscribe(project / ".akit.yaml", f"version: 1\nharnesses: [detected, emacs]\n\nskills:\n  {kits}: [writing]\n")

        outcome = render.render(project, places)

        assert outcome.unknown == ("emacs",)
        assert (project / SKILLS / "writing" / "SKILL.md").is_file()

    @pytest.mark.parametrize(
        ("flags", "expected"),
        [
            ((False, False), (Scope.USER, Scope.PROJECT)),
            ((True, False), (Scope.USER,)),
            ((False, True), (Scope.PROJECT,)),
            ((True, True), (Scope.USER, Scope.PROJECT)),
        ],
    )
    def test_the_scope_flags_narrow_and_naming_both_is_the_default_spelled_out(
        self, flags: tuple[bool, bool], expected: tuple[Scope, ...]
    ):
        assert render.scopes_from(only_global=flags[0], only_project=flags[1]) == expected


#: A harness that takes rules and declines skills, which neither shipped adapter
#: does. Declining is a first-class answer (DESIGN.md section 4) and the path it
#: takes through the renderer is the one nothing else here exercises, so the
#: fixture adapter is how it gets tested rather than by waiting for T13.
PAPER = Adapter(
    name="paper",
    summary="a harness that takes no skills at all",
    has_a_machine=True,
    destinations={(Kind.RULE, Scope.PROJECT): Destination(write="paper/rules")},
    rule_shape=RuleShape.DIRECTORY,
    evidence=(".paper",),
)


@pytest.fixture
def only_paper(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(adapters, "ADAPTERS", (PAPER,))
    monkeypatch.setattr(adapters, "BY_NAME", {PAPER.name: PAPER})


class TestAHarnessThatDeclinesTheKind:
    def test_a_skill_nobody_takes_is_reported_and_nothing_is_written(
        self, project: Path, places: render.Directories, kits: Path, only_paper: None
    ):
        subscribe(project / ".akit.yaml", f"version: 1\nharnesses: [paper]\n\nskills:\n  {kits}: [writing]\n")

        outcome = render.render(project, places)

        assert outcome.entries[0].placements == ()
        assert outcome.entries[0].problem is None
        assert not (project / ".agents").exists()

    def test_a_rule_a_harness_takes_in_one_scope_and_not_the_other_lands_once(
        self, project: Path, places: render.Directories, kits: Path, only_paper: None
    ):
        """PAPER takes rules in a repository and nowhere else, which is a valid answer."""
        assert places.user_manifest is not None
        subscribe(places.user_manifest, f"version: 1\nharnesses: [paper]\n\nrules:\n- {kits}: prose-style\n")
        subscribe(project / ".akit.yaml", f"version: 1\nharnesses: [paper]\n\nrules:\n- {kits}: prose-style\n")

        outcome = render.render(project, places)

        assert [entry.placements for entry in outcome.entries if entry.subscription.scope is Scope.USER] == [()]
        assert (project / "paper" / "rules" / "prose-style.md").is_file()

    def test_a_harness_that_writes_no_kind_we_render_puts_nothing_in_the_ignore_block(
        self, project: Path, places: render.Directories, kits: Path, only_paper: None
    ):
        subscribe(project / ".akit.yaml", f"version: 1\nharnesses: [paper]\n\nskills:\n  {kits}: [writing]\n")

        outcome = render.render(project, places)

        assert outcome.ignored == ((project, (), False),)


class TestTwoSubscriptionsWantingOnePlace:
    def test_a_wildcard_meeting_a_rename_is_reported_and_the_first_copy_stands(
        self, project: Path, places: render.Directories, kits: Path, tmp_path: Path
    ):
        other = build(tmp_path / "other", {"skills/notes/SKILL.md": "# notes\n"})
        subscribe(
            project / ".akit.yaml",
            f"""
            version: 1

            skills:
              {kits}: ["*"]
              {other}:
              - name: notes
                as: writing
            """,
        )

        outcome = render.render(project, places)

        assert (project / SKILLS / "writing" / "SKILL.md").read_text(encoding="utf-8") == "# writing\n"
        assert any("different bytes" in (entry.problem or "") for entry in outcome.entries)
        assert outcome.exit_code is Exit.ERROR


class TestWhatIsCopiedOutOfASkill:
    def test_a_repository_inside_a_skill_is_not_part_of_the_kit(
        self, project: Path, places: render.Directories, kits: Path, one_skill: Path
    ):
        (kits / "skills" / "writing" / ".git").mkdir()
        (kits / "skills" / "writing" / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")

        render.render(project, places)

        assert not (project / SKILLS / "writing" / ".git").exists()

    def test_pruning_takes_a_loose_file_as_well_as_a_directory(
        self, project: Path, places: render.Directories, one_skill: Path
    ):
        render.render(project, places)
        loose = project / SKILLS / "stray.md"
        loose.write_text("# stray\n", encoding="utf-8")

        render.render(project, places, render.Choices(prune=True))

        assert not loose.exists()
        assert (project / SKILLS / "writing" / "SKILL.md").is_file()


class TestTheReport:
    def report(self, outcome: render.Outcome) -> str:
        out = io.StringIO()
        render.text(outcome, out)
        return out.getvalue()

    def test_a_first_render_says_what_it_wrote_and_where(
        self, project: Path, places: render.Directories, one_skill: Path
    ):
        printed = self.report(render.render(project, places))

        assert "wrote 2 files" in printed
        assert str(project / SKILLS / "writing") in printed
        assert "for opencode and copilot-vscode" in printed
        assert "Nothing changed" not in printed

    @pytest.mark.parametrize(("number", "expected"), [(0, "no files"), (1, "1 file"), (2, "2 files")])
    def test_a_count_is_written_as_english_rather_than_as_a_log_line(self, number: int, expected: str):
        assert render.counted(number, "file") == expected

    def test_a_no_op_says_it_was_a_no_op(self, project: Path, places: render.Directories, one_skill: Path):
        render.render(project, places)

        printed = self.report(render.render(project, places))

        assert "Nothing changed" in printed
        assert "already up to date" in printed
        assert "nothing: every rendered file is still explained" in printed

    def test_an_empty_scope_says_so_rather_than_printing_a_heading_and_nothing(
        self, project: Path, places: render.Directories, one_skill: Path
    ):
        assert "nothing subscribed here" in self.report(render.render(project, places))

    def test_every_withdrawal_outcome_names_the_file_and_the_edited_one_names_a_fix(
        self, project: Path, places: render.Directories, kits: Path, one_skill: Path
    ):
        render.render(project, places)
        (project / SKILLS / "writing" / "SKILL.md").write_text("# mine\n", encoding="utf-8")
        (project / SKILLS / "writing" / "references" / "style.md").unlink()
        subscribe(project / ".akit.yaml", "version: 1\n")

        printed = self.report(render.render(project, places))

        assert "was already gone" in printed
        assert "left" in printed
        assert "akit doctor" in printed

    def test_a_deleted_copy_says_that_nothing_explains_it_any_more(
        self, project: Path, places: render.Directories, one_skill: Path
    ):
        render.render(project, places)
        subscribe(project / ".akit.yaml", "version: 1\n")

        printed = self.report(render.render(project, places))

        assert "which nothing in scope explains any more" in printed
        assert str(project / SKILLS / "writing" / "SKILL.md") in printed

    def test_a_suspended_withdrawal_says_why(self, project: Path, places: render.Directories, one_skill: Path):
        printed = self.report(render.render(project, places, render.Choices(without=("opencode",))))

        assert "nothing: a narrowing flag was given" in printed

    def test_a_pruned_orphan_says_that_nothing_explained_it(
        self, project: Path, places: render.Directories, one_skill: Path
    ):
        render.render(project, places)
        (project / SKILLS / "stray.md").write_text("# stray\n", encoding="utf-8")

        printed = self.report(render.render(project, places, render.Choices(prune=True)))

        assert "pruned" in printed

    def test_a_kind_that_is_waiting_names_its_task(self, project: Path, places: render.Directories, kits: Path):
        subscribe(project / ".akit.yaml", f"version: 1\n\nagents:\n  {kits}: [reviewer]\n")

        assert "not rendered: every adapter declines agents" in self.report(render.render(project, places))

    def test_a_problem_is_printed_with_its_fix_on_its_own_line(
        self, project: Path, places: render.Directories, tmp_path: Path
    ):
        subscribe(project / ".akit.yaml", f"version: 1\n\nskills:\n  {tmp_path / 'gone'}: [writing]\n")

        printed = self.report(render.render(project, places))

        assert "problem:" in printed
        assert "A path source is read where it is" in printed

    def test_a_harness_no_adapter_knows_is_named_with_the_command_that_lists_them(
        self, project: Path, places: render.Directories, kits: Path
    ):
        subscribe(project / ".akit.yaml", f"version: 1\nharnesses: [detected, emacs]\n\nskills:\n  {kits}: [writing]\n")

        printed = self.report(render.render(project, places))

        assert '"emacs"' in printed
        assert "akit list" in printed

    def test_a_harness_list_narrowed_to_nothing_says_so(
        self, project: Path, places: render.Directories, kits: Path, only_paper: None
    ):
        subscribe(project / ".akit.yaml", f"version: 1\nharnesses: []\n\nskills:\n  {kits}: [writing]\n")

        assert "no harness in scope" in self.report(render.render(project, places))

    def test_the_ignore_line_says_whether_the_file_changed(
        self, project: Path, places: render.Directories, one_skill: Path
    ):
        assert "now lists .agents/skills/" in self.report(render.render(project, places))
        assert "already listed .agents/skills/" in self.report(render.render(project, places))


class TestTheSameThingAsData:
    def test_the_payload_carries_what_was_written_and_what_was_withdrawn(
        self, project: Path, places: render.Directories, one_skill: Path
    ):
        render.render(project, places)
        subscribe(project / ".akit.yaml", "version: 1\n")

        payload = render.payload(render.render(project, places))

        assert payload["changed_nothing"] is False
        assert payload["withdrawal_suspended"] is None
        assert {entry["action"] for entry in payload["withdrawn"]} == {"deleted"}
        assert payload["ignored"][0]["lists"] == []

    def test_the_payload_is_json(self, project: Path, places: render.Directories, one_skill: Path):
        payload = render.payload(render.render(project, places))

        assert json.loads(json.dumps(payload))["subscriptions"][0]["name"] == "writing"


class TestTheCommandLine:
    def run(self, *argv: str, home: Path, start: Path) -> tuple[Exit, str]:
        out = io.StringIO()
        parsed = build_parser().parse_args(["render", *argv])
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(Path, "cwd", staticmethod(lambda: start))
            patch.setattr(Path, "home", staticmethod(lambda: home))
            code = dispatch(parsed, out)
        return code, out.getvalue()

    def test_the_verb_renders_and_reports(self, project: Path, home: Path, one_skill: Path):
        code, printed = self.run(home=home, start=project)

        assert code is Exit.OK
        assert (project / SKILLS / "writing" / "SKILL.md").is_file()
        assert "wrote" in printed

    def test_json_is_the_same_run_as_data(self, project: Path, home: Path, one_skill: Path):
        code, printed = self.run("--json", home=home, start=project)

        assert code is Exit.OK
        assert json.loads(printed)["subscriptions"][0]["kind"] == "skills"

    def test_the_flags_reach_the_engine(self, project: Path, home: Path, one_skill: Path):
        code, printed = self.run("--project", "--harness", "opencode", home=home, start=project)

        assert code is Exit.OK
        assert "a narrowing flag was given" in printed

    def test_check_on_a_repository_that_commits_nothing_says_so(self, project: Path, home: Path, one_skill: Path):
        code, printed = self.run("--check", home=home, start=project)

        assert code is Exit.OK
        assert "names no harness whose renders it commits" in printed

    def test_check_as_json_is_the_same_verdict_as_data(self, project: Path, home: Path, one_skill: Path):
        code, printed = self.run("--check", "--json", home=home, start=project)

        assert code is Exit.OK
        assert json.loads(printed)["stale"] == []

    def test_check_refuses_the_narrowing_flags(self, project: Path, home: Path, one_skill: Path):
        with pytest.raises(UsageError) as raised:
            self.run("--check", "--no-harness", "opencode", home=home, start=project)

        assert "does not take --harness or --no-harness" in str(raised.value)
        assert raised.value.exit_code is Exit.USAGE


INSTRUCTIONS = Path(".github") / "instructions"


def agents_md(root: Path) -> str:
    path = root / "AGENTS.md"
    return path.read_text(encoding="utf-8") if path.is_file() else ""


@pytest.fixture
def two_rules(tmp_path: Path) -> Path:
    """A source holding two rules that contradict each other, which is why order exists."""
    return build(
        tmp_path / "opinions",
        {
            "rules/tabs.md": "Indent with tabs.\n",
            "rules/spaces.md": "Indent with spaces.\n",
        },
    )


class TestWhereARuleLands:
    """One source file, two shapes, because the harnesses disagree (DESIGN.md section 7)."""

    def test_a_directory_shaped_harness_gets_one_file_per_rule(
        self, project: Path, places: render.Directories, kits: Path
    ):
        subscribe(project / ".akit.yaml", f"version: 1\n\nrules:\n- {kits}: prose-style\n")

        render.render(project, places)

        assert (project / INSTRUCTIONS / "prose-style.instructions.md").is_file()

    def test_a_copilot_rule_carries_apply_to_and_the_body_it_was_given(
        self, project: Path, places: render.Directories, kits: Path
    ):
        subscribe(project / ".akit.yaml", f"version: 1\n\nrules:\n- {kits}: prose-style\n")

        render.render(project, places)

        rendered = (project / INSTRUCTIONS / "prose-style.instructions.md").read_text(encoding="utf-8")
        assert rendered == '---\napplyTo: "**"\n---\n\n# prose\n'

    def test_a_shared_file_harness_gets_a_block_in_a_file_it_did_not_have(
        self, project: Path, places: render.Directories, kits: Path
    ):
        subscribe(project / ".akit.yaml", f"version: 1\n\nrules:\n- {kits}: prose-style\n")

        render.render(project, places)

        assert agents_md(project) == "<!-- BEGIN akit prose-style -->\n# prose\n<!-- END akit prose-style -->\n"

    def test_the_two_scopes_write_two_different_shared_files(
        self, project: Path, places: render.Directories, kits: Path, tmp_path: Path
    ):
        assert places.user_manifest is not None
        subscribe(places.user_manifest, f"version: 1\n\nrules:\n- {kits}: prose-style\n")

        render.render(project, places)

        assert "akit prose-style" in agents_md(places.home / ".config" / "opencode")
        assert agents_md(project) == ""

    def test_a_rename_decides_both_the_filename_and_the_marker(
        self, project: Path, places: render.Directories, kits: Path
    ):
        subscribe(
            project / ".akit.yaml",
            f"""
            version: 1

            rules:
            - {kits}:
              - name: prose-style
                as: house-style
            """,
        )

        render.render(project, places)

        assert (project / INSTRUCTIONS / "house-style.instructions.md").is_file()
        assert "BEGIN akit house-style" in agents_md(project)

    def test_a_rule_whose_name_is_not_a_filename_is_refused_rather_than_sanitised(
        self, project: Path, places: render.Directories, tmp_path: Path
    ):
        source = build(tmp_path / "bad", {"rules/two words.md": "Body.\n"})
        subscribe(project / ".akit.yaml", f'version: 1\n\nrules:\n- {source}: "two words"\n')

        outcome = render.render(project, places)

        assert "not a name a rule can have" in (outcome.entries[0].problem or "")
        assert not (project / INSTRUCTIONS).exists()
        assert agents_md(project) == ""
        assert outcome.exit_code is Exit.ERROR


class TestTheOrderTwoRulesAreReadIn:
    """The one promise rules have, and exactly how far it reaches (DESIGN.md section 7)."""

    def manifest(self, project: Path, source: Path, first: str, second: str) -> None:
        subscribe(project / ".akit.yaml", f"version: 1\n\nrules:\n- {source}: [{first}, {second}]\n")

    def test_a_shared_file_gets_the_manifest_order(self, project: Path, places: render.Directories, two_rules: Path):
        self.manifest(project, two_rules, "tabs", "spaces")

        render.render(project, places)

        text = agents_md(project)
        assert text.index("BEGIN akit tabs") < text.index("BEGIN akit spaces")

    def test_swapping_the_manifest_swaps_the_output(self, project: Path, places: render.Directories, two_rules: Path):
        self.manifest(project, two_rules, "tabs", "spaces")
        render.render(project, places)

        self.manifest(project, two_rules, "spaces", "tabs")
        render.render(project, places)

        text = agents_md(project)
        assert text.index("BEGIN akit spaces") < text.index("BEGIN akit tabs")

    def test_a_reorder_is_reported_as_a_change_rather_than_as_nothing(
        self, project: Path, places: render.Directories, two_rules: Path
    ):
        """Every block keeps its bytes and the file is still rewritten."""
        self.manifest(project, two_rules, "tabs", "spaces")
        render.render(project, places)

        self.manifest(project, two_rules, "spaces", "tabs")
        outcome = render.render(project, places)

        assert not outcome.quiet
        assert outcome.blocks_written > 0

    def test_a_directory_shaped_harness_is_only_promised_that_both_arrived(
        self, project: Path, places: render.Directories, two_rules: Path
    ):
        self.manifest(project, two_rules, "tabs", "spaces")

        render.render(project, places)

        assert (project / INSTRUCTIONS / "tabs.instructions.md").is_file()
        assert (project / INSTRUCTIONS / "spaces.instructions.md").is_file()

    def test_nothing_is_prefixed_or_renamed_to_imply_an_order(
        self, project: Path, places: render.Directories, two_rules: Path
    ):
        self.manifest(project, two_rules, "tabs", "spaces")

        render.render(project, places)

        assert {path.name for path in (project / INSTRUCTIONS).iterdir()} == {
            "tabs.instructions.md",
            "spaces.instructions.md",
        }


class TestAFileWeShareWithTheUser:
    """Everything outside our markers is theirs, on every render and forever."""

    @pytest.fixture
    def rendered(self, project: Path, places: render.Directories, kits: Path) -> Path:
        subscribe(project / ".akit.yaml", f"version: 1\n\nrules:\n- {kits}: prose-style\n")
        render.render(project, places)
        return project / "AGENTS.md"

    def test_prose_written_around_our_block_survives_three_renders(
        self, project: Path, places: render.Directories, rendered: Path
    ):
        rendered.write_text(
            f"# Their own notes\n\n{rendered.read_text(encoding='utf-8')}\nA closing paragraph.\n",
            encoding="utf-8",
        )
        before = rendered.read_text(encoding="utf-8")

        for _ in range(3):
            render.render(project, places)

        assert rendered.read_text(encoding="utf-8") == before

    def test_a_second_render_changes_nothing_and_says_so(
        self, project: Path, places: render.Directories, rendered: Path
    ):
        outcome = render.render(project, places)

        assert outcome.quiet
        assert outcome.blocks_written == 0
        assert outcome.blocks_unchanged == 1

    def test_a_changed_source_rewrites_only_our_block(
        self, project: Path, places: render.Directories, rendered: Path, kits: Path
    ):
        rendered.write_text(f"Theirs.\n\n{rendered.read_text(encoding='utf-8')}", encoding="utf-8")
        (kits / "rules" / "prose-style.md").write_text("# prose, revised\n", encoding="utf-8")

        outcome = render.render(project, places)

        assert outcome.blocks_written == 1
        assert rendered.read_text(encoding="utf-8").startswith("Theirs.\n\n")
        assert "# prose, revised" in rendered.read_text(encoding="utf-8")

    def test_unsubscribing_takes_our_block_and_leaves_the_file(
        self, project: Path, places: render.Directories, rendered: Path
    ):
        rendered.write_text(f"Theirs.\n\n{rendered.read_text(encoding='utf-8')}", encoding="utf-8")
        subscribe(project / ".akit.yaml", "version: 1\n")

        outcome = render.render(project, places)

        assert rendered.read_text(encoding="utf-8") == "Theirs.\n"
        assert "prose-style" in [entry.region for entry in outcome.deleted]

    def test_a_block_somebody_edited_is_left_alone_and_pointed_at_doctor(
        self, project: Path, places: render.Directories, rendered: Path
    ):
        rendered.write_text(
            rendered.read_text(encoding="utf-8").replace("# prose", "# prose, and my own note"), encoding="utf-8"
        )
        subscribe(project / ".akit.yaml", "version: 1\n")

        outcome = render.render(project, places)

        assert "my own note" in rendered.read_text(encoding="utf-8")
        assert [entry.region for entry in outcome.withdrawals if entry.action == render.KEPT] == ["prose-style"]

    def test_a_host_file_somebody_deleted_is_reported_as_gone(
        self, project: Path, places: render.Directories, rendered: Path
    ):
        rendered.unlink()
        subscribe(project / ".akit.yaml", "version: 1\n")

        outcome = render.render(project, places)

        assert [entry.region for entry in outcome.withdrawals if entry.action == render.GONE] == ["prose-style"]

    def test_the_host_file_is_never_put_in_the_ignore_block(
        self, project: Path, places: render.Directories, rendered: Path
    ):
        listed = (project / ignore.GITIGNORE).read_text(encoding="utf-8")

        assert "AGENTS.md" not in listed
        assert ".github/instructions/" in listed

    def test_the_record_names_the_marker_beside_the_path(self, project: Path, rendered: Path):
        regions = {entry.region for entry in project_record(project).written}

        assert "prose-style" in regions

    def test_the_record_hashes_the_block_and_not_the_file(
        self, project: Path, places: render.Directories, rendered: Path
    ):
        rendered.write_text(f"A paragraph added later.\n\n{rendered.read_text(encoding='utf-8')}", encoding="utf-8")
        entry = next(found for found in project_record(project).written if found.region == "prose-style")

        assert entry.still_a_copy()


class TestOneRuleGoingToBothShapesAtOnce:
    def test_removing_it_deletes_the_file_and_closes_up_the_shared_one(
        self, project: Path, places: render.Directories, two_rules: Path
    ):
        subscribe(project / ".akit.yaml", f"version: 1\n\nrules:\n- {two_rules}: [tabs, spaces]\n")
        render.render(project, places)

        subscribe(project / ".akit.yaml", f"version: 1\n\nrules:\n- {two_rules}: [spaces]\n")
        render.render(project, places)

        assert not (project / INSTRUCTIONS / "tabs.instructions.md").exists()
        assert (project / INSTRUCTIONS / "spaces.instructions.md").is_file()
        text = agents_md(project)
        assert "akit tabs" not in text
        assert "BEGIN akit spaces" in text

    def test_rendering_it_twice_leaves_the_whole_tree_identical(
        self, project: Path, places: render.Directories, two_rules: Path
    ):
        subscribe(project / ".akit.yaml", f"version: 1\n\nrules:\n- {two_rules}: [tabs, spaces]\n")
        render.render(project, places)
        before = tree(project)

        render.render(project, places)

        assert tree(project) == before

    def test_two_subscriptions_wanting_one_marker_is_a_collision_rather_than_a_winner(
        self, project: Path, places: render.Directories, two_rules: Path, tmp_path: Path
    ):
        """A wildcard cannot know what it will match, so the manifest could not refuse this."""
        other = build(tmp_path / "other", {"rules/tabs.md": "Indent with something else entirely.\n"})
        subscribe(project / ".akit.yaml", f'version: 1\n\nrules:\n- {two_rules}: ["*"]\n- {other}: [tabs]\n')

        outcome = render.render(project, places)

        assert any("already wants different bytes" in (entry.problem or "") for entry in outcome.entries)
        assert "Indent with tabs." in agents_md(project)


class TestHowARuleInASharedFileIsReported:
    @pytest.fixture
    def rendered(self, project: Path, places: render.Directories, kits: Path) -> Path:
        subscribe(project / ".akit.yaml", f"version: 1\n\nrules:\n- {kits}: prose-style\n")
        render.render(project, places)
        return project / "AGENTS.md"

    def report(self, outcome: render.Outcome) -> str:
        out = io.StringIO()
        render.text(outcome, out)
        return out.getvalue()

    def test_a_block_that_was_written_names_the_marker_and_the_file(
        self, project: Path, places: render.Directories, kits: Path
    ):
        subscribe(project / ".akit.yaml", f"version: 1\n\nrules:\n- {kits}: prose-style\n")

        printed = self.report(render.render(project, places))

        assert 'wrote the "prose-style" block in' in printed

    def test_a_block_already_in_place_says_so_rather_than_claiming_a_write(
        self, project: Path, places: render.Directories, rendered: Path
    ):
        printed = self.report(render.render(project, places))

        assert 'already up to date: the "prose-style" block in' in printed

    def test_a_withdrawn_block_is_named_as_a_block_and_not_as_a_file(
        self, project: Path, places: render.Directories, rendered: Path
    ):
        subscribe(project / ".akit.yaml", "version: 1\n")

        printed = self.report(render.render(project, places))

        assert 'deleted the "prose-style" block in' in printed

    def test_the_data_carries_the_marker_beside_the_path(
        self, project: Path, places: render.Directories, rendered: Path
    ):
        subscribe(project / ".akit.yaml", "version: 1\n")

        payload = render.payload(render.render(project, places))

        assert "prose-style" in [entry["region"] for entry in payload["withdrawn"]]
