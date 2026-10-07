"""The fake home holds, on both operating systems, including the fallback branch.

This is the test that protects the developer's own config directory from every
other test. `akit` reads a manifest out of a per-platform config directory, and
the fallback when no `XDG_*` variable is set is `Path.home()`, which reads `HOME`
on Linux and `USERPROFILE` on Windows. Redirecting one of those makes the
isolation hold on one platform and fail silently on the other, in exactly the
test that removes `XDG_CONFIG_HOME` on purpose.

So the fallback is exercised here rather than avoided, and what it is asked is
not "did you survive" but "where did you land".
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fake_home import FakeHome

pytestmark = pytest.mark.cli

WHERE_IT_LOOKS = (
    "import os, pathlib, platformdirs;"
    "print(pathlib.Path.home());"
    "print(platformdirs.user_config_dir('akit'));"
    "print(platformdirs.user_cache_dir('akit'));"
    "print(platformdirs.user_state_dir('akit'));"
    "print(os.environ.get('XDG_CONFIG_HOME', '<unset>'))"
)


def locations(home: FakeHome, env: dict[str, str]) -> list[str]:
    result = home.run_python("-c", WHERE_IT_LOOKS, env=env)
    assert result.returncode == 0, result.stderr
    return result.stdout.splitlines()


def test_every_directory_akit_uses_is_inside_the_house(fake_home: FakeHome) -> None:
    home, config, cache, state, xdg = locations(fake_home, fake_home.env)
    root = str(fake_home.root)
    assert home == root
    assert config.startswith(root)
    assert cache.startswith(root)
    assert state.startswith(root)
    assert xdg != "<unset>"


def test_the_fallback_branch_lands_inside_the_house_too(fake_home: FakeHome, monkeypatch: pytest.MonkeyPatch) -> None:
    """With no `XDG_*` set at all, the lookup falls back to `Path.home()`.

    The parent environment is given a real-looking `XDG_CONFIG_HOME` first, so
    this fails rather than passes by accident if the house ever stops *removing*
    variables and merely stops setting them.
    """
    monkeypatch.setenv("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    home, config, cache, state, xdg = locations(fake_home, fake_home.env_without_xdg)
    root = str(fake_home.root)
    assert xdg == "<unset>"
    assert home == root
    for directory in (config, cache, state):
        assert directory.startswith(root), "the fallback reached outside the fake home"


def test_the_house_cannot_see_the_real_home(fake_home: FakeHome) -> None:
    real = str(Path.home())
    home, *_ = locations(fake_home, fake_home.env)
    assert home != real


def test_git_variables_from_an_outer_repository_are_gone(fake_home: FakeHome, monkeypatch: pytest.MonkeyPatch) -> None:
    """A suite run from a pre-commit hook starts inside somebody's commit."""
    monkeypatch.setenv("GIT_DIR", str(Path.cwd() / ".git"))
    monkeypatch.setenv("GIT_INDEX_FILE", str(Path.cwd() / ".git" / "index"))
    result = fake_home.run_python("-c", "import os; print([k for k in os.environ if k.startswith('GIT_')])")
    assert result.stdout.strip() == "[]"
