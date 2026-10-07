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
