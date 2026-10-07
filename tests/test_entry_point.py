"""The entry point, met the way a user meets it: a built wheel, run by `uvx`.

An import is not an entry point. `akit` reaches a colleague as `uvx akit render`
in a contributing guide or a pre-commit hook, and everything between the console
script and the module is configuration nothing else in this suite touches: the
`[project.scripts]` name, the packages hatchling puts in the wheel, and whether
the metadata the version is read from survives the build. All three fail at
install time and none fails in a test that imports.

This is the slowest test here, by a wide margin, which is why it is one test.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from federated_agent_kits.cli import version

pytestmark = pytest.mark.cli

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if shutil.which("uv") is None:  # pragma: no cover - CI and the Makefile both guarantee uv
        pytest.skip("uv is not on PATH")
    out = tmp_path_factory.mktemp("dist")
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(out), str(REPO_ROOT)],
        check=True,
        capture_output=True,
        text=True,
    )
    built = sorted(out.glob("*.whl"))
    assert len(built) == 1, f"expected one wheel, got {built}"
    return built[0]


def test_uvx_from_the_wheel_prints_the_frame(wheel: Path) -> None:
    result = subprocess.run(
        ["uvx", "--from", str(wheel), "akit", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "akit" in result.stdout
    assert "render" in result.stdout


def test_the_installed_version_is_the_one_pyproject_declares(wheel: Path) -> None:
    result = subprocess.run(
        ["uvx", "--from", str(wheel), "akit", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"akit {version()}"
