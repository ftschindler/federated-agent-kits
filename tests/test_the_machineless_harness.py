"""The harness with no machine: what it commits, and what `render --check` judges.

Two behaviours land together here because they are the same fact seen twice.
Naming a harness `akit` can never run on moves a directory out of the
`.gitignore` block and into the repository, and anything committed can go stale
while looking fine. DESIGN.md section 4 for the harness, section 6 for the
ignore block, section 10 for the check.

A `file://` source throughout, warmed into the cache, because `render` never
fetches and a check that found nothing to compare would pass for the wrong
reason.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from git_environment import FIXED_AUTHOR, git, local_remote
from ruamel.yaml import YAML

from federated_agent_kits import cache, ignore, render, sources
from federated_agent_kits.cli import build_parser
from federated_agent_kits.exits import Exit, RefusalError
from federated_agent_kits.manifest import Scope

pytestmark = pytest.mark.unit

SKILLS = Path(".agents") / "skills"
INSTRUCTIONS = Path(".github") / "instructions"


@pytest.fixture(autouse=True)
def house(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    for variable in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(variable, str(home))
    for variable in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        monkeypatch.delenv(variable, raising=False)
    return home


@pytest.fixture
def home(tmp_path: Path) -> Path:
    root = tmp_path / "laptop"
    (root / ".config" / "opencode").mkdir(parents=True)
    (root / ".vscode").mkdir(parents=True)
    return root


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    git("-C", str(root), "init", "-q")
    return root


@pytest.fixture
def places(tmp_path: Path, home: Path) -> render.Directories:
    return render.Directories(
        home=home,
        user_manifest=tmp_path / "config" / "manifest.yaml",
        cache=tmp_path / "cache",
        state=tmp_path / "state",
    )


@pytest.fixture
def kits(tmp_path: Path) -> str:
    return local_remote(
        tmp_path / "kits",
        {"skills/writing/SKILL.md": "# writing\n", "rules/prose-style.md": "# prose\n"},
    )


def mine(places: render.Directories) -> Path:
    """Your own manifest, as a path rather than as one that might be absent."""
    assert places.user_manifest is not None
    return places.user_manifest


def subscribe(project: Path, places: render.Directories, kits: str, *, harnesses: str = "detected") -> Path:
    cache.resolve(sources.parse(kits), anchor=project, cache_root=places.cache)
    path = project / ".akit.yaml"
    path.write_text(
        f"version: 1\nharnesses: [{harnesses}]\n\nskills:\n  {kits}: [writing]\n\nrules:\n- {kits}: prose-style\n",
        encoding="utf-8",
    )
    return path


def block(project: Path) -> list[str]:
    path = project / ignore.GITIGNORE
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return lines[lines.index(ignore.BEGIN) + 1 : lines.index(ignore.END)] if ignore.BEGIN in lines else []


class TestTheHarnessArrivesOnlyByBeingNamed:
    def test_it_is_not_in_the_list_until_the_manifest_says_so(
        self, project: Path, places: render.Directories, kits: str
    ):
        subscribe(project, places, kits)

        outcome = render.render(project, places)

        assert "copilot-ci" not in outcome.harnesses[Scope.PROJECT]

    def test_naming_it_adds_it_without_turning_the_detected_ones_off(
        self, project: Path, places: render.Directories, kits: str
    ):
        subscribe(project, places, kits, harnesses="detected, copilot-ci")

        outcome = render.render(project, places)

        assert set(outcome.harnesses[Scope.PROJECT]) == {"opencode", "copilot-vscode", "copilot-ci"}

    def test_it_renders_nothing_into_your_own_machine_level_directories(
        self, project: Path, places: render.Directories, kits: str
    ):
        yours = mine(places)
        yours.parent.mkdir(parents=True, exist_ok=True)
        yours.write_text(f"version: 1\nharnesses: [copilot-ci]\n\nskills:\n  {kits}: [writing]\n", encoding="utf-8")
        cache.resolve(sources.parse(kits), anchor=project, cache_root=places.cache)

        render.render(project, places)

        assert not (places.home / SKILLS).exists()


class TestTheIgnoreBlockIsTheInverseOfWhatIsCommitted:
    def test_without_it_everything_rendered_here_is_ignored(self, project: Path, places: render.Directories, kits: str):
        subscribe(project, places, kits)

        render.render(project, places)

        assert block(project) == [".agents/skills/", ".akit/", ".github/instructions/"]

    def test_naming_it_takes_the_committed_directories_out(self, project: Path, places: render.Directories, kits: str):
        # A directory with two readers is committed if either of them commits,
        # because git cannot ignore a directory halfway. So the skills opencode
        # was reading privately go into the history, by design.
        subscribe(project, places, kits, harnesses="detected, copilot-ci")

        render.render(project, places)

        assert block(project) == [".akit/"]

    def test_the_record_stays_in_whatever_else_leaves(self, project: Path, places: render.Directories, kits: str):
        # It is the one entry that is not a rendered kit: machine state sitting
        # inside a repository several people share.
        subscribe(project, places, kits, harnesses="detected, copilot-ci")

        render.render(project, places)

        assert ".akit/" in block(project)

    def test_the_block_flips_back_when_the_harness_is_removed(
        self, project: Path, places: render.Directories, kits: str
    ):
        subscribe(project, places, kits, harnesses="detected, copilot-ci")
        render.render(project, places)

        subscribe(project, places, kits)
        render.render(project, places)

        assert block(project) == [".agents/skills/", ".akit/", ".github/instructions/"]

    def test_a_users_own_lines_survive_the_flip_in_their_own_order(
        self, project: Path, places: render.Directories, kits: str
    ):
        (project / ".gitignore").write_text("*.pyc\n.venv/\n", encoding="utf-8")
        subscribe(project, places, kits, harnesses="detected, copilot-ci")

        render.render(project, places)

        text = (project / ".gitignore").read_text(encoding="utf-8")
        assert text.startswith("*.pyc\n.venv/\n")


class TestWhatTheCloudAgentActuallyGets:
    def test_a_skill_lands_in_the_shared_directory_it_reads(self, project: Path, places: render.Directories, kits: str):
        subscribe(project, places, kits, harnesses="copilot-ci")

        render.render(project, places)

        assert (project / SKILLS / "writing" / "SKILL.md").read_text(encoding="utf-8") == "# writing\n"

    def test_a_rule_lands_as_a_file_of_ours_carrying_the_frontmatter_it_needs(
        self, project: Path, places: render.Directories, kits: str
    ):
        subscribe(project, places, kits, harnesses="copilot-ci")

        render.render(project, places)

        rendered = (project / INSTRUCTIONS / "prose-style.instructions.md").read_text(encoding="utf-8")
        assert 'applyTo: "**"' in rendered or "applyTo: '**'" in rendered
        assert "# prose\n" in rendered

    def test_one_copy_serves_it_and_the_laptop_harnesses_alike(
        self, project: Path, places: render.Directories, kits: str
    ):
        subscribe(project, places, kits, harnesses="detected, copilot-ci")

        outcome = render.render(project, places)

        skills = [place for entry in outcome.entries for place in entry.placements if place.region is None]
        shared = [place for place in skills if place.path.name == "writing"]
        assert len(shared) == 1
        assert sorted(shared[0].harnesses) == ["copilot-ci", "copilot-vscode", "opencode"]


class TestTheCheck:
    def test_a_repository_committing_nothing_has_nothing_to_judge(
        self, project: Path, places: render.Directories, kits: str
    ):
        subscribe(project, places, kits)

        outcome = render.render(project, places, render.COMMITTED, render.CHECKING)

        assert outcome.stale == ()
        assert outcome.exit_code is Exit.OK
        assert outcome.harnesses[Scope.PROJECT] == ()

    def test_detection_is_kept_out_of_it(self, project: Path, places: render.Directories, kits: str):
        # A CI runner has none of the harnesses on your laptop installed, so a
        # check that honoured detection would call every repository stale
        # forever. This machine has two of them and the check sees neither.
        subscribe(project, places, kits, harnesses="detected, copilot-ci")

        outcome = render.render(project, places, render.COMMITTED, render.CHECKING)

        assert outcome.harnesses[Scope.PROJECT] == ("copilot-ci",)

    def test_a_fresh_render_passes(self, project: Path, places: render.Directories, kits: str):
        subscribe(project, places, kits, harnesses="copilot-ci")
        render.render(project, places)

        outcome = render.render(project, places, render.COMMITTED, render.CHECKING)

        assert outcome.stale == ()
        assert outcome.exit_code is Exit.OK

    def test_an_edited_committed_file_fails_it(self, project: Path, places: render.Directories, kits: str):
        subscribe(project, places, kits, harnesses="copilot-ci")
        render.render(project, places)
        (project / SKILLS / "writing" / "SKILL.md").write_text("# edited by hand\n", encoding="utf-8")

        outcome = render.render(project, places, render.COMMITTED, render.CHECKING)

        assert outcome.stale
        assert outcome.exit_code is Exit.ERROR

    def test_a_missing_committed_file_fails_it(self, project: Path, places: render.Directories, kits: str):
        subscribe(project, places, kits, harnesses="copilot-ci")
        render.render(project, places)
        (project / INSTRUCTIONS / "prose-style.instructions.md").unlink()

        assert render.render(project, places, render.COMMITTED, render.CHECKING).exit_code is Exit.ERROR

    def test_a_stale_ignore_block_fails_it(self, project: Path, places: render.Directories, kits: str):
        """A block still listing the directory the cloud agent reads is a silent failure.

        The rendered files would be correct and absent from the repository at
        the same time, which is the shape of mistake the whole ignore-block
        mechanism exists to prevent.
        """
        subscribe(project, places, kits, harnesses="copilot-ci")
        render.render(project, places)
        (project / ".gitignore").write_text(
            f"{ignore.BEGIN}\n.agents/skills/\n.akit/\n{ignore.END}\n", encoding="utf-8"
        )

        outcome = render.render(project, places, render.COMMITTED, render.CHECKING)

        assert any("gitignore" in reason for reason in outcome.stale)

    def test_a_committed_file_nothing_subscribes_to_any_more_fails_it_without_deleting_it(
        self, project: Path, places: render.Directories, kits: str
    ):
        """It asks the disk rather than the render record, and does not act on the answer.

        A runner has no record, and a check keeps only the harnesses that
        commit, so the record's entries for every other harness would read as
        unexplained. The directories are ours and everything in them is
        committed, so a file in one the manifest no longer accounts for is
        stale whoever put it there.
        """
        subscribe(project, places, kits, harnesses="copilot-ci")
        render.render(project, places)
        (project / ".akit.yaml").write_text(
            f"version: 1\nharnesses: [copilot-ci]\n\nskills:\n  {kits}: [writing]\n", encoding="utf-8"
        )
        rendered = project / INSTRUCTIONS / "prose-style.instructions.md"

        outcome = render.render(project, places, render.COMMITTED, render.CHECKING)

        assert rendered in outcome.unexplained
        assert any("nothing subscribes to" in reason for reason in outcome.stale)
        assert rendered.is_file()

    def test_a_fresh_render_is_not_called_stale_by_the_harnesses_it_leaves_out(
        self, project: Path, places: render.Directories, kits: str
    ):
        # Found by hand, with the built wheel: the record carries entries for
        # opencode's AGENTS.md block too, and a check that judged withdrawal
        # from it called every freshly rendered repository out of date.
        subscribe(project, places, kits, harnesses="detected, copilot-ci")
        render.render(project, places)

        outcome = render.render(project, places, render.COMMITTED, render.CHECKING)

        assert outcome.stale == ()
        assert outcome.exit_code is Exit.OK

    def test_a_check_outside_any_repository_has_nothing_to_look_at(self, places: render.Directories, tmp_path: Path):
        loose = tmp_path / "not-a-repository"
        loose.mkdir()

        outcome = render.render(loose, places, render.COMMITTED, render.CHECKING)

        assert outcome.unexplained == ()
        assert outcome.stale == ()
        assert outcome.exit_code is Exit.OK

    def test_it_writes_nothing_at_all(self, project: Path, places: render.Directories, kits: str):
        subscribe(project, places, kits, harnesses="copilot-ci")

        render.render(project, places, render.COMMITTED, render.CHECKING)

        assert not (project / SKILLS).exists()
        assert not (project / INSTRUCTIONS).exists()
        assert not (project / ".akit").exists()
        assert not (project / ".gitignore").exists()

    def test_it_judges_a_committed_render_with_no_record_at_all(
        self, project: Path, places: render.Directories, kits: str
    ):
        """A CI runner has never rendered, so it has no record to read.

        Which is why the check recomputes rather than comparing against what we
        wrote last time, and why it is allowed to fetch: there is no cache on a
        fresh checkout either.
        """
        subscribe(project, places, kits, harnesses="copilot-ci")
        render.render(project, places)
        for found in (project / ".akit").rglob("*"):
            found.unlink()

        outcome = render.render(project, places, render.COMMITTED, render.CHECKING)

        assert outcome.stale == ()

    def test_it_fetches_what_the_cache_does_not_hold(
        self, project: Path, places: render.Directories, kits: str, tmp_path: Path
    ):
        subscribe(project, places, kits, harnesses="copilot-ci")
        render.render(project, places)
        cached = places.cache
        assert cached is not None
        for entry in sorted(cached.rglob("*"), key=lambda path: len(path.parts), reverse=True):
            entry.chmod(0o700)
            entry.rmdir() if entry.is_dir() else entry.unlink()

        outcome = render.render(project, places, render.COMMITTED, render.CHECKING)

        assert outcome.stale == ()
        assert outcome.problems == ()


class TestACommittedManifestThatNamesSomebodysLaptop:
    def test_an_escaping_path_is_refused(self, project: Path, places: render.Directories, tmp_path: Path):
        outside = tmp_path / "my-kits"
        (outside / "skills" / "writing").mkdir(parents=True)
        (outside / "skills" / "writing" / "SKILL.md").write_text("# writing\n", encoding="utf-8")
        (project / ".akit.yaml").write_text(f"version: 1\n\nskills:\n  {outside}: [writing]\n", encoding="utf-8")
        git("-C", str(project), "add", "-A")
        git("-C", str(project), *FIXED_AUTHOR, "commit", "-qm", "subscribe")

        with pytest.raises(RefusalError) as refused:
            render.render(project, places)

        assert str(outside) in str(refused.value)
        assert refused.value.exit_code is Exit.REFUSAL

    def test_the_same_path_in_an_uncommitted_manifest_is_how_you_write_a_kit(
        self, project: Path, places: render.Directories, tmp_path: Path
    ):
        outside = tmp_path / "my-kits"
        (outside / "skills" / "writing").mkdir(parents=True)
        (outside / "skills" / "writing" / "SKILL.md").write_text("# writing\n", encoding="utf-8")
        (project / ".akit.yaml").write_text(f"version: 1\n\nskills:\n  {outside}: [writing]\n", encoding="utf-8")

        assert render.render(project, places).exit_code is Exit.OK

    def test_a_path_that_stays_inside_is_fine_committed(self, project: Path, places: render.Directories):
        inside = project / "kits" / "skills" / "writing"
        inside.mkdir(parents=True)
        (inside / "SKILL.md").write_text("# writing\n", encoding="utf-8")
        (project / ".akit.yaml").write_text("version: 1\n\nskills:\n  ./kits: [writing]\n", encoding="utf-8")
        git("-C", str(project), "add", "-A")
        git("-C", str(project), *FIXED_AUTHOR, "commit", "-qm", "subscribe")

        assert render.render(project, places).exit_code is Exit.OK

    def test_the_check_refuses_it_too(self, project: Path, places: render.Directories, tmp_path: Path):
        outside = tmp_path / "my-kits"
        (outside / "skills" / "writing").mkdir(parents=True)
        (outside / "skills" / "writing" / "SKILL.md").write_text("# writing\n", encoding="utf-8")
        (project / ".akit.yaml").write_text(f"version: 1\n\nskills:\n  {outside}: [writing]\n", encoding="utf-8")
        git("-C", str(project), "add", "-A")
        git("-C", str(project), *FIXED_AUTHOR, "commit", "-qm", "subscribe")

        with pytest.raises(RefusalError):
            render.render(project, places, render.COMMITTED, render.CHECKING)


class TestTheVerdictAPersonReads:
    def report(self, project: Path, places: render.Directories) -> str:
        out = io.StringIO()
        render.verdict(render.render(project, places, render.COMMITTED, render.CHECKING), out)
        return out.getvalue()

    def test_nothing_to_check_says_what_would_make_it_check_something(
        self, project: Path, places: render.Directories, kits: str
    ):
        subscribe(project, places, kits)

        said = self.report(project, places)

        assert "names no harness whose renders it commits" in said
        assert "akit harness add <name>" in said
        assert "copilot-ci" in said

    def test_up_to_date_names_the_harness_it_judged(self, project: Path, places: render.Directories, kits: str):
        subscribe(project, places, kits, harnesses="copilot-ci")
        render.render(project, places)

        assert "Up to date" in self.report(project, places)

    def test_out_of_date_names_the_command_that_fixes_it(self, project: Path, places: render.Directories, kits: str):
        subscribe(project, places, kits, harnesses="copilot-ci")

        said = self.report(project, places)

        assert "Out of date" in said
        assert "akit render" in said


class TestTheHooksOtherRepositoriesPin:
    """`.pre-commit-hooks.yaml`, which is a promise to repositories we cannot see.

    What this repository owns is the declaration and the command it names.
    Installing the hook is pre-commit's business and needs a network and an
    install, so the layer below runs the same entry as a subprocess in a
    throwaway repository instead, which is what the hook does to it.
    """

    def declaration(self) -> dict:
        path = Path(__file__).parent.parent / ".pre-commit-hooks.yaml"
        return YAML(typ="safe").load(path.read_text(encoding="utf-8"))[0]

    def test_one_hook_covers_all_three_checks(self):
        assert self.declaration()["entry"] == "akit render --check"

    def test_it_runs_whether_or_not_a_rendered_file_is_in_the_commit(self):
        # A render goes stale when a pin moves, and the commit that moves it
        # does not touch a single rendered file.
        declared = self.declaration()
        assert declared["always_run"] is True
        assert declared["pass_filenames"] is False

    def test_the_command_it_names_is_one_this_build_has(self):
        verb, *flags = self.declaration()["entry"].removeprefix("akit ").split()
        parsed = build_parser().parse_args([verb, *flags])

        assert parsed.check is True


class TestTheSecondAdaptersDiffBudget:
    """Rule 7 of DESIGN.md section 3, checked rather than remembered.

    This adapter is the third one written and the first with no machine, so if
    "a harness is a file, not a branch" were going to break, it would break
    here. The engine may not know this harness exists: what it knows is that
    some harnesses have no machine, which is a field on the interface.

    Prose is not code and is left out of one of these assertions. `akit harness
    add copilot-ci` in a help example is the help contract's requirement for
    real-looking arguments, and a command's examples are read by people. No
    engine module names it at all.
    """

    ENGINE = (
        "render.py",
        "listing.py",
        "subscribing.py",
        "leaks.py",
        "targets.py",
        "ignore.py",
        "record.py",
        "rules.py",
        "discovery.py",
        "cache.py",
        "sources.py",
        "manifest.py",
    )

    def source(self) -> Path:
        return Path(__file__).parent.parent / "src" / "federated_agent_kits"

    def test_the_adapter_is_imported_in_exactly_one_place(self):
        importing = [
            path.relative_to(self.source()).as_posix()
            for path in sorted(self.source().rglob("*.py"))
            if "import copilot_ci" in path.read_text(encoding="utf-8")
        ]

        assert importing == ["adapters/__init__.py"]

    def test_no_engine_module_names_this_harness(self):
        naming = [name for name in self.ENGINE if "copilot-ci" in (self.source() / name).read_text(encoding="utf-8")]

        assert naming == []

    def test_the_engine_asks_the_interface_instead(self):
        # What replaces the branch: a field every adapter answers, so a fourth
        # machineless harness needs no change here either.
        assert "has_a_machine" in (self.source() / "adapters" / "__init__.py").read_text(encoding="utf-8")
        assert "machineless" in (self.source() / "render.py").read_text(encoding="utf-8")
