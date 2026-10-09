"""`akit doctor`: one deliberately broken state per check, and a healthy one.

Every test here builds the breakage on purpose rather than hoping for it, which
is what DESIGN.md section 10's list of checks asks for: a fixture per bullet, a
finding per fixture, and a healthy setup that reports nothing.

Two things are asserted everywhere rather than once. `report` below fails any
finding that does not name a command, so a check cannot ship as a complaint with
nothing to do next. And `doctor` is run against a snapshot of the whole tree, so
the command that is safe to run when you do not know what is going on stays safe.

A real git repository throughout, because four of the checks are about what a
repository commits and `git init` is cheaper than a second definition of the
word.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from git_environment import FIXED_AUTHOR, git, local_remote

from federated_agent_kits import adapters, cache, doctor, ignore, privacy, record, render, sources
from federated_agent_kits.adapters.adapter import Adapter, Destination, Pointer, RuleShape
from federated_agent_kits.cache import Privacy
from federated_agent_kits.cli import build_parser, dispatch
from federated_agent_kits.exits import Exit
from federated_agent_kits.manifest import Kind, Scope

pytestmark = pytest.mark.unit

SKILLS = Path(".agents") / "skills"
INSTRUCTIONS = Path(".github") / "instructions"

#: A commit no repository has, for the pin a cache cannot hold.
NOWHERE = "0" * 40


@pytest.fixture(autouse=True)
def house(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The developer's own home, out of reach of everything below."""
    home = tmp_path / "house"
    home.mkdir()
    for variable in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(variable, str(home))
    for variable in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        monkeypatch.delenv(variable, raising=False)
    return home


@pytest.fixture
def home(tmp_path: Path) -> Path:
    """A machine with both shipped harnesses installed, by their own evidence."""
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
def kits(tmp_path: Path) -> Path:
    """A path source, which is the cheapest thing a subscription can name."""
    root = tmp_path / "kits"
    (root / "skills" / "writing").mkdir(parents=True)
    (root / "skills" / "writing" / "SKILL.md").write_text("# writing\n", encoding="utf-8")
    (root / "rules").mkdir()
    (root / "rules" / "prose-style.md").write_text("# prose\n", encoding="utf-8")
    return root


def subscribe(project: Path, body: str) -> Path:
    path = project / ".akit.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def one_skill(project: Path, kits: Path, *, harnesses: str = "detected") -> Path:
    return subscribe(project, f"version: 1\nharnesses: [{harnesses}]\n\nskills:\n  {kits}: [writing]\n")


def report(project: Path, places: render.Directories) -> doctor.Report:
    """Run `doctor`, and refuse a finding that does not name a command.

    The contract DESIGN.md section 10 ends on, checked on every call rather than
    in one test: a check that found something has to say what to run next, and
    the cheapest way to keep that true is to make every assertion in this file
    depend on it.
    """
    found = doctor.examine(project, places)
    for finding in found.findings:
        assert "`" in finding.fix, f"{finding.check} does not name a command"
        assert "akit " in finding.fix or "git " in finding.fix, f"{finding.check} names no command"
    return found


def checks(found: doctor.Report) -> list[str]:
    return [finding.check for finding in found.findings]


def tree(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): record.digest(path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def commit(project: Path, message: str = "commit") -> None:
    git("-C", str(project), "add", "-A")
    git("-C", str(project), *FIXED_AUTHOR, "commit", "-qm", message)


class TestASetupWithNothingWrongWithIt:
    def test_a_freshly_rendered_repository_reports_nothing(self, project: Path, places: render.Directories, kits: Path):
        one_skill(project, kits)
        render.render(project, places)

        found = report(project, places)

        assert found.findings == ()
        assert found.exit_code is Exit.OK

    def test_it_changes_nothing_on_disk(self, project: Path, places: render.Directories, kits: Path):
        one_skill(project, kits)
        render.render(project, places)
        (project / SKILLS / "writing" / "SKILL.md").write_text("# edited\n", encoding="utf-8")
        before = {"project": tree(project), "home": tree(places.home), "state": tree(places.state or project)}

        report(project, places)

        assert {"project": tree(project), "home": tree(places.home), "state": tree(places.state or project)} == before

    def test_outside_a_repository_it_reports_on_your_home(self, places: render.Directories, tmp_path: Path):
        loose = tmp_path / "not-a-repository"
        loose.mkdir()

        found = report(loose, places)

        assert found.where == places.home
        assert found.exit_code is Exit.OK


class TestWhatTheManifestsSay:
    def test_two_kits_on_one_name_are_reported_with_the_fix(
        self, project: Path, places: render.Directories, kits: Path, tmp_path: Path
    ):
        yours = places.user_manifest
        assert yours is not None
        yours.parent.mkdir(parents=True)
        yours.write_text(f"version: 1\n\nskills:\n  {kits}: [writing]\n", encoding="utf-8")
        one_skill(project, kits)

        found = report(project, places)

        assert "collision" in checks(found)
        collision = next(entry for entry in found.findings if entry.check == "collision")
        assert '"writing"' in collision.what
        assert "--as" in collision.fix

    def test_a_harness_no_adapter_knows_is_a_typo_nothing_else_validates(
        self, project: Path, places: render.Directories, kits: Path
    ):
        one_skill(project, kits, harnesses="detected, emacs")

        found = report(project, places)

        assert "unknown-harness" in checks(found)
        assert "akit harness remove emacs" in next(
            entry.fix for entry in found.findings if entry.check == "unknown-harness"
        )

    def test_a_harness_on_this_machine_that_the_list_leaves_out_is_worth_a_line(
        self, project: Path, places: render.Directories, kits: Path
    ):
        one_skill(project, kits, harnesses="copilot-vscode")

        found = report(project, places)

        assert "harness-left-out" in checks(found)
        assert any("opencode" in entry.what for entry in found.findings if entry.check == "harness-left-out")

    def test_kits_in_place_for_a_harness_this_machine_does_not_have(
        self, project: Path, places: render.Directories, kits: Path, tmp_path: Path
    ):
        bare = render.Directories(
            home=tmp_path / "bare", user_manifest=places.user_manifest, cache=places.cache, state=places.state
        )
        (bare.home / ".config" / "opencode").mkdir(parents=True)
        one_skill(project, kits, harnesses="detected, copilot-vscode")
        render.render(project, bare)

        found = report(project, bare)

        assert "harness-not-here" in checks(found)
        assert any("copilot-vscode" in entry.what for entry in found.findings)

    def test_a_manifest_this_build_cannot_read_is_a_finding_rather_than_a_traceback(
        self, project: Path, places: render.Directories
    ):
        subscribe(project, "version: 1\n\nskills:\n  - this is not a mapping\n")

        found = report(project, places)

        assert checks(found) == ["unreadable"]
        assert found.exit_code is Exit.ERROR


class TestASubscriptionThatCannotBeRendered:
    def test_a_source_this_machine_does_not_have(self, project: Path, places: render.Directories, tmp_path: Path):
        subscribe(project, f"version: 1\n\nskills:\n  {tmp_path / 'gone'}: [writing]\n")

        found = report(project, places)

        assert "subscription" in checks(found)
        entry = next(found for found in found.findings if found.check == "subscription")
        assert "there is no directory at" in entry.what
        assert "akit update writing" in entry.fix

    def test_a_pin_the_cache_does_not_hold(self, project: Path, places: render.Directories, tmp_path: Path):
        remote = local_remote(tmp_path / "remote", {"skills/writing/SKILL.md": "# writing\n"})
        cache.resolve(sources.parse(remote), anchor=project, cache_root=places.cache)
        subscribe(project, f"version: 1\n\nskills:\n  {remote}#{NOWHERE}: [writing]\n")

        found = report(project, places)

        assert "subscription" in checks(found)
        assert any(NOWHERE in entry.what for entry in found.findings)

    def test_nothing_is_called_unexplained_while_something_is_unresolved(
        self, project: Path, places: render.Directories, kits: Path, tmp_path: Path
    ):
        """The reason `render` suspends withdrawal, asked of the report instead.

        A candidate list short by one source explains fewer files than the
        manifest does, and every file the missing source would have explained
        would read as about to be withdrawn.
        """
        one_skill(project, kits)
        render.render(project, places)
        subscribe(project, f"version: 1\n\nskills:\n  {tmp_path / 'gone'}: [writing]\n")

        found = report(project, places)

        assert "unexplained" not in checks(found)
        assert "subscription" in checks(found)


class TestWhatIsActuallyOnDisk:
    def test_a_rendered_copy_somebody_edited_is_caught_by_its_hash(
        self, project: Path, places: render.Directories, kits: Path
    ):
        one_skill(project, kits)
        render.render(project, places)
        (project / SKILLS / "writing" / "SKILL.md").write_text("# mine now\n", encoding="utf-8")

        found = report(project, places)

        assert "edited" in checks(found)
        assert "akit render" in next(entry.fix for entry in found.findings if entry.check == "edited")

    def test_a_render_nothing_subscribes_to_any_more(self, project: Path, places: render.Directories, kits: Path):
        one_skill(project, kits)
        render.render(project, places)
        subscribe(project, "version: 1\n")

        found = report(project, places)

        assert "unexplained" in checks(found)
        assert (project / SKILLS / "writing" / "SKILL.md").is_file()

    def test_a_lost_record_leaves_what_looks_like_an_orphan(
        self, project: Path, places: render.Directories, kits: Path
    ):
        one_skill(project, kits)
        render.render(project, places)
        record.project_location(project).unlink()
        subscribe(project, "version: 1\n")

        found = report(project, places)

        assert "orphan" in checks(found)
        assert "--prune" in next(entry.fix for entry in found.findings if entry.check == "orphan")

    def test_a_skill_the_manifest_still_explains_is_not_an_orphan(
        self, project: Path, places: render.Directories, kits: Path
    ):
        one_skill(project, kits)
        render.render(project, places)

        assert "orphan" not in checks(report(project, places))

    def test_a_repository_keeping_a_record_no_manifest_explains(
        self, project: Path, places: render.Directories, kits: Path
    ):
        one_skill(project, kits)
        render.render(project, places)
        (project / ".akit.yaml").unlink()

        found = report(project, places)

        assert "abandoned-record" in checks(found)
        assert "akit render" in next(entry.fix for entry in found.findings if entry.check == "abandoned-record")


class TestAHarnessPointedAtADirectory:
    """The shape no adapter ships for 1.0, checked against the interface instead.

    T6 deferred the pointed renderer and left `RuleShape.POINTED` and `Pointer`
    in place, and a pointer this tool wrote is never withdrawn. So the one thing
    `doctor` owes that shape is this: say when the key is aimed at nothing.
    """

    @pytest.fixture
    def pointy(self, monkeypatch: pytest.MonkeyPatch) -> Adapter:
        adapter = Adapter(
            name="pointy",
            summary="a harness that has to be pointed at the directory it reads",
            has_a_machine=True,
            destinations={(Kind.RULE, Scope.PROJECT): Destination(write="kits/rules")},
            rule_shape=RuleShape.POINTED,
            pointer={Scope.PROJECT: Pointer(config="pointy.json", key="rules")},
        )
        monkeypatch.setattr(adapters, "ADAPTERS", (*adapters.ADAPTERS, adapter))
        return adapter

    def test_a_pointer_aimed_at_nothing_is_reported(
        self, project: Path, places: render.Directories, kits: Path, pointy: Adapter
    ):
        one_skill(project, kits)
        (project / "pointy.json").write_text(json.dumps({"rules": "kits/rules"}), encoding="utf-8")

        found = report(project, places)

        assert "dangling-pointer" in checks(found)
        assert "pointy.json" in next(entry.fix for entry in found.findings if entry.check == "dangling-pointer")

    def test_a_pointer_aimed_at_a_directory_that_is_there_is_not(
        self, project: Path, places: render.Directories, kits: Path, pointy: Adapter
    ):
        one_skill(project, kits)
        (project / "kits" / "rules").mkdir(parents=True)
        (project / "pointy.json").write_text(json.dumps({"rules": ["kits/rules"]}), encoding="utf-8")

        assert "dangling-pointer" not in checks(report(project, places))

    @pytest.mark.parametrize(
        "config", ["", "not json at all", json.dumps(["kits/rules"]), json.dumps({"rules": 7}), json.dumps({})]
    )
    def test_a_config_that_points_nowhere_is_not_a_dangling_pointer(
        self, project: Path, places: render.Directories, kits: Path, pointy: Adapter, config: str
    ):
        one_skill(project, kits)
        (project / "pointy.json").write_text(config, encoding="utf-8")

        assert "dangling-pointer" not in checks(report(project, places))

    def test_no_config_at_all_is_not_one_either(
        self, project: Path, places: render.Directories, kits: Path, pointy: Adapter
    ):
        one_skill(project, kits)

        assert "dangling-pointer" not in checks(report(project, places))


class TestWhatTheRepositoryCommits:
    def test_a_committed_manifest_naming_somebodys_laptop(self, project: Path, places: render.Directories, kits: Path):
        one_skill(project, kits)
        commit(project, "subscribe")

        found = report(project, places)

        assert "escaping-path" in checks(found)
        assert "--global" in next(entry.fix for entry in found.findings if entry.check == "escaping-path")

    def test_a_stale_committed_render(self, project: Path, places: render.Directories, kits: Path):
        one_skill(project, kits, harnesses="detected, copilot-ci")
        render.render(project, places)
        (kits / "skills" / "writing" / "SKILL.md").write_text("# moved on\n", encoding="utf-8")

        found = report(project, places)

        assert "stale" in checks(found)
        assert "akit render" in next(entry.fix for entry in found.findings if entry.check == "stale")

    def test_a_private_kit_about_to_be_committed_into_a_public_repository_is_reported_not_raised(
        self, project: Path, places: render.Directories, tmp_path: Path
    ):
        """The refusal `render` raises, arriving here as a line with a fix under it.

        A remote rather than a path source, because a path is as public as the
        repository it sits in and can never be the private half of a leak.
        """
        remote = local_remote(tmp_path / "private", {"skills/writing/SKILL.md": "# writing\n"})
        cache.resolve(sources.parse(remote), anchor=project, cache_root=places.cache)
        git("-C", str(project), "remote", "add", "origin", local_remote(tmp_path / "upstream", {"README.md": "#\n"}))
        subscribe(project, f"version: 1\nharnesses: [detected, copilot-ci]\n\nskills:\n  {remote}: [writing]\n")
        privacy.save({remote: Privacy.PRIVATE}, places.state)

        found = report(project, places)

        assert "refused" in checks(found)
        assert "akit harness remove copilot-ci" in next(
            entry.fix for entry in found.findings if entry.check == "refused"
        )

    def test_a_check_that_cannot_run_is_a_finding_rather_than_a_crash(
        self, project: Path, places: render.Directories, kits: Path
    ):
        one_skill(project, kits, harnesses="detected, copilot-ci")
        render.render(project, places)
        privacy.location(places.state).write_text("{", encoding="utf-8")

        found = report(project, places)

        assert "committed-render" in checks(found)
        assert "akit render --check" in next(entry.fix for entry in found.findings if entry.check == "committed-render")

    def test_a_repository_that_commits_nothing_is_asked_nothing(
        self, project: Path, places: render.Directories, kits: Path
    ):
        """The check that may fetch, skipped where there is nothing to be stale.

        A repository naming no machineless harness commits no render, so an
        ordinary `doctor` stays as offline as an ordinary `render`.
        """
        one_skill(project, kits)
        render.render(project, places)
        git("-C", str(project), "remote", "add", "origin", "https://unreachable.example/nothing.git")

        found = report(project, places)

        assert "stale" not in checks(found)
        assert "refused" not in checks(found)

    def test_a_rendered_directory_missing_from_the_ignore_block(
        self, project: Path, places: render.Directories, kits: Path
    ):
        one_skill(project, kits)
        render.render(project, places)
        (project / ignore.GITIGNORE).write_text("build/\n", encoding="utf-8")

        found = report(project, places)

        assert "ignore-block" in checks(found)
        assert "akit render" in next(entry.fix for entry in found.findings if entry.check == "ignore-block")

    def test_a_repository_that_commits_says_a_stale_block_once_rather_than_twice(
        self, project: Path, places: render.Directories, kits: Path
    ):
        one_skill(project, kits, harnesses="detected, copilot-ci")
        render.render(project, places)
        (project / ignore.GITIGNORE).write_text("build/\n", encoding="utf-8")

        found = report(project, places)

        assert "ignore-block" not in checks(found)
        assert any(ignore.GITIGNORE in entry.what for entry in found.findings if entry.check == "stale")

    def test_a_directory_that_is_ignored_and_committed_at_the_same_time(
        self, project: Path, places: render.Directories, kits: Path
    ):
        one_skill(project, kits)
        render.render(project, places)
        git("-C", str(project), "add", "-A", "-f")
        git("-C", str(project), *FIXED_AUTHOR, "commit", "-qm", "commit the lot")

        found = report(project, places)

        assert "ignored-and-committed" in checks(found)
        assert "git rm -r --cached" in next(
            entry.fix for entry in found.findings if entry.check == "ignored-and-committed"
        )


class TestTheReportItself:
    def test_a_healthy_setup_says_so_and_names_where_it_looked(
        self, project: Path, places: render.Directories, kits: Path
    ):
        one_skill(project, kits)
        render.render(project, places)
        out = io.StringIO()

        doctor.text(report(project, places), out)

        printed = out.getvalue()
        assert "Nothing to report" in printed
        assert str(project) in printed

    def test_every_finding_is_printed_with_its_fix_under_it(
        self, project: Path, places: render.Directories, kits: Path
    ):
        one_skill(project, kits, harnesses="copilot-vscode, emacs")
        out = io.StringIO()

        found = report(project, places)
        doctor.text(found, out)

        printed = out.getvalue()
        assert f"Found {len(found.findings)} things" in printed
        assert printed.count("fix: ") == len(found.findings)

    def test_one_finding_is_one_thing(self, project: Path, places: render.Directories, kits: Path):
        one_skill(project, kits, harnesses="detected, emacs")
        out = io.StringIO()

        doctor.text(report(project, places), out)

        assert "Found 1 thing\n" in out.getvalue()

    def test_a_finding_that_takes_several_lines_keeps_the_rest_of_them(self, project: Path, places: render.Directories):
        subscribe(project, "version: 1\n\nskills:\n  - this is not a mapping\n")
        out = io.StringIO()

        found = report(project, places)
        doctor.text(found, out)

        assert len(found.findings[0].what.splitlines()) > 1
        assert "only rules have an order" in out.getvalue()
        assert len(out.getvalue().splitlines()) > len(found.findings) + 4

    def test_the_same_answer_as_data(self, project: Path, places: render.Directories, kits: Path):
        one_skill(project, kits, harnesses="detected, emacs")

        payload = doctor.payload(report(project, places))

        assert payload["healthy"] is False
        assert payload["where"] == str(project)
        assert [entry["check"] for entry in payload["findings"]] == ["unknown-harness"]


class TestTheCommand:
    """The verb as the frame dispatches it, with the real per-platform directories.

    Everything above hands `examine` a `Directories` with every root inside a
    `tmp_path`. This is the other half: the command as somebody types it, which
    looks its own home up and is only safe because the fake house redirects it.
    """

    def arguments(self, *extra: str):
        return build_parser().parse_args(["doctor", *extra])

    def test_a_setup_with_nothing_in_it_exits_zero(self, project: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.chdir(project)
        out = io.StringIO()

        assert dispatch(self.arguments(), out) is Exit.OK
        assert "Nothing to report" in out.getvalue()

    def test_a_broken_setup_exits_one_and_can_answer_as_data(
        self, project: Path, kits: Path, monkeypatch: pytest.MonkeyPatch
    ):
        one_skill(project, kits, harnesses="emacs")
        monkeypatch.chdir(project)
        out = io.StringIO()

        assert dispatch(self.arguments("--json"), out) is Exit.ERROR
        assert json.loads(out.getvalue())["findings"][0]["check"] == "unknown-harness"
