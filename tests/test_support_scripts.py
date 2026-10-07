"""The two scripts CI runs: the version arithmetic, and the test invocation.

Neither is in `src/`, so neither is under the coverage gate, and both are the
kind of code whose first failure happens in a release. Loaded by path because
their file names are not identifiers, which is deliberate: they are commands, not
modules, and `uv run .scripts/version.py next minor` answers the question on a
laptop without a CI run to see it.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
from git_environment import FIXED_AUTHOR, git

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / ".scripts"


def load(name: str) -> ModuleType:
    path = SCRIPTS / name
    spec = importlib.util.spec_from_file_location(path.stem.replace("-", "_"), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


version = load("version.py")
run_tests = load("run-tests.py")
verify_published = load("verify-published.py")


class TestNextVersion:
    @pytest.mark.parametrize(
        ("current", "level", "expected"),
        [
            ("0.1.0", "patch", "0.1.1"),
            ("0.1.0", "minor", "0.2.0"),
            # Zeroed, always. 0.4.2 major is 1.0.0, never 1.4.2: the mistake is
            # invisible in the tag and permanent in the history.
            ("0.4.2", "major", "1.0.0"),
            ("1.9.9", "major", "2.0.0"),
        ],
    )
    def test_it_bumps_the_right_part(self, current: str, level: str, expected: str) -> None:
        assert version.next_version(current, level) == expected

    def test_something_that_is_not_a_version_is_refused(self) -> None:
        with pytest.raises(SystemExit):
            version.next_version("v1.2", "patch")


class TestTheRehearsalVersion:
    """What a pull request uploads to TestPyPI, and why it cannot carry a sha.

    PEP 440 wants a number in a dev segment. The other spelling that would carry
    a sha, `0.2.1+g6ec3cb1`, parses and is refused by both indexes, because
    warehouse forbids local versions outright. Both halves are asserted here so
    that the next person to reach for a sha finds the reason rather than the
    rule.
    """

    def test_it_is_the_version_this_change_would_release(self) -> None:
        assert version.dev_version("0.2.0", "patch", "37611306651") == "0.2.1.dev37611306651"
        assert version.dev_version("0.2.0", "minor", "7") == "0.3.0.dev7"

    def test_a_sha_is_refused_with_the_reason(self) -> None:
        with pytest.raises(SystemExit) as raised:
            version.dev_version("0.2.0", "patch", "6ec3cb1")
        assert "number" in str(raised.value)

    def test_a_dev_version_may_be_written(self) -> None:
        sample = '[project]\nversion = "0.2.0"\n'
        assert 'version = "0.2.1.dev9"' in version.replace_version(sample, "0.2.1.dev9")

    def test_a_local_version_may_not_be(self) -> None:
        # Not a style preference: warehouse rejects it, so writing one would
        # build an artefact no index will take.
        with pytest.raises(SystemExit):
            version.replace_version('[project]\nversion = "0.2.0"\n', "0.2.1+g6ec3cb1")


class TestVerifyPublished:
    def captured(self, monkeypatch: pytest.MonkeyPatch) -> list[str]:
        """The command `run` would have executed, without executing it."""
        seen: list[str] = []

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        def record(command: list[str], **_options: object) -> Result:
            seen.extend(command)
            return Result()

        monkeypatch.setattr(verify_published.subprocess, "run", record)
        verify_published.run("0.2.1.dev9", "https://test.pypi.org/simple/", "--version")
        return seen

    def test_it_pins_the_exact_version(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert "federated-agent-kits==0.2.1.dev9" in self.captured(monkeypatch)

    def test_it_asks_the_rehearsal_index_first(self, monkeypatch: pytest.MonkeyPatch) -> None:
        command = self.captured(monkeypatch)
        indexes = [command[position + 1] for position, item in enumerate(command) if item == "--index"]
        assert indexes == ["https://test.pypi.org/simple/", verify_published.PYPI]

    def test_it_runs_the_entry_point_rather_than_importing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        command = self.captured(monkeypatch)
        assert command[-2:] == ["akit", "--version"]

    def test_both_indexes_are_offered_because_testpypi_does_not_mirror(self) -> None:
        source = (SCRIPTS / "verify-published.py").read_text(encoding="utf-8")
        assert "unsafe-best-match" in source
        assert "does not mirror" in source

    def test_it_retries_while_the_index_catches_up(self, monkeypatch: pytest.MonkeyPatch) -> None:
        attempts = []

        class Result:
            def __init__(self, code: int) -> None:
                self.returncode = code
                self.stdout = ""
                self.stderr = ""

        def flaky(_version: str, _index: str, *_arguments: str) -> Result:
            attempts.append(1)
            return Result(1 if len(attempts) < 3 else 0)

        monkeypatch.setattr(verify_published, "run", flaky)
        monkeypatch.setattr(verify_published.time, "sleep", lambda _seconds: None)
        assert verify_published.wait_for("0.2.1.dev9", "https://test.pypi.org/simple/").returncode == 0
        assert len(attempts) == 3

    def test_it_gives_up_rather_than_waiting_forever(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class Result:
            returncode = 1
            stdout = ""
            stderr = ""

        monkeypatch.setattr(verify_published, "run", lambda *_args: Result())
        monkeypatch.setattr(verify_published.time, "sleep", lambda _seconds: None)
        assert verify_published.wait_for("0.2.1.dev9", "x").returncode == 1

    def test_a_package_that_misreports_its_own_version_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # The failure this exists for: the index served something, it installed,
        # and it is not what was uploaded.
        class Result:
            returncode = 0
            stdout = "akit 0.1.0\n"
            stderr = ""

        monkeypatch.setattr(verify_published, "wait_for", lambda *_args: Result())
        assert verify_published.main(["0.2.1.dev9", "https://test.pypi.org/simple/"]) == 1


class TestTheVersionLine:
    SAMPLE = '[project]\nname = "x"\nversion = "0.1.0"\nrequires-python = ">=3.11"\n'

    def test_it_reads_the_project_version(self) -> None:
        assert version.read_version(self.SAMPLE) == "0.1.0"

    def test_it_writes_it_back_and_changes_nothing_else(self) -> None:
        written = version.replace_version(self.SAMPLE, "0.2.0")
        assert written == self.SAMPLE.replace("0.1.0", "0.2.0")
        assert 'requires-python = ">=3.11"' in written

    def test_it_refuses_a_version_that_is_not_one(self) -> None:
        with pytest.raises(SystemExit):
            version.replace_version(self.SAMPLE, "0.2")

    def test_a_file_with_no_version_line_is_an_error(self) -> None:
        with pytest.raises(SystemExit):
            version.read_version('[project]\nname = "x"\n')

    def test_this_repository_declares_one(self) -> None:
        assert version.read_version(version.PYPROJECT.read_text(encoding="utf-8"))


class TestTheVersionGuard:
    """A rewrite is refused; the line arriving for the first time is not.

    Both halves run against a real repository, because the thing being tested is
    a `git diff` and a fixture string would be testing the regular expression
    twice.
    """

    def diff_of(self, tmp_path: Path, base: str | None, head: str, monkeypatch: pytest.MonkeyPatch) -> bool:
        repository = tmp_path / "repo"
        repository.mkdir()
        pyproject = repository / "pyproject.toml"
        git("init", "-q", "-b", "main", str(repository))
        (repository / "README.md").write_text("seed\n", encoding="utf-8")
        if base is not None:
            pyproject.write_text(base, encoding="utf-8")
        git("-C", str(repository), "add", "-A")
        git("-C", str(repository), *FIXED_AUTHOR, "commit", "-qm", "base")
        git("-C", str(repository), "checkout", "-q", "-b", "change")
        pyproject.write_text(head, encoding="utf-8")
        git("-C", str(repository), "add", "-A")
        git("-C", str(repository), *FIXED_AUTHOR, "commit", "-qm", "change")
        monkeypatch.setattr(version, "PYPROJECT", pyproject)
        monkeypatch.setattr(version, "REPO_ROOT", repository)
        return version.version_changed("main", "change")

    def test_a_rewritten_version_is_caught(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        before = '[project]\nname = "x"\nversion = "0.1.0"\n'
        assert self.diff_of(tmp_path, before, before.replace("0.1.0", "0.2.0"), monkeypatch) is True

    def test_the_line_arriving_for_the_first_time_is_not(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # The pull request that creates pyproject.toml. It can only happen once:
        # afterwards the line is on the base branch and any further write to it
        # removes something.
        assert self.diff_of(tmp_path, None, '[project]\nname = "x"\nversion = "0.1.0"\n', monkeypatch) is False

    def test_an_unrelated_edit_to_the_same_file_is_allowed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        before = '[project]\nname = "x"\nversion = "0.1.0"\n'
        after = before + 'description = "y"\n'
        assert self.diff_of(tmp_path, before, after, monkeypatch) is False


class TestRunTests:
    def test_it_only_measures_coverage_on_the_layer_that_can_be_measured(self) -> None:
        # The other layers run `akit` as a subprocess, where coverage cannot see
        # it. Gating them on a percentage would measure the harness.
        assert "--cov" in run_tests.command_for("unit", [])
        assert "--cov" not in run_tests.command_for("cli", [])

    def test_every_marker_is_runnable(self) -> None:
        for marker in run_tests.MARKERS:
            assert run_tests.command_for(marker, [])[-1] == "-v"

    def test_the_markers_match_the_pytest_config(self) -> None:
        declared = (REPO_ROOT / "tests" / "pytest.toml").read_text(encoding="utf-8")
        # The table name, because the wrong one parses fine and applies nothing.
        assert "[pytest]" in declared
        assert "--strict-markers" in declared
        for marker in run_tests.MARKERS:
            assert f"{marker}:" in declared

    def test_an_unknown_marker_is_refused(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "run-tests.py"), "everything"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode != 0
        assert "everything" in result.stderr
