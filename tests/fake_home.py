"""A fake home: a machine with nothing of yours inside it.

`akit` reads its manifest from a per-platform config directory, writes a render
record into a state directory, and clones sources into a cache directory. Every
one of those has a real location on a developer's machine, and the one in the
middle is the file that says which kits they actually use. A test that redirects
only `XDG_CONFIG_HOME` leaves a bug one missing variable away from rewriting it.

Everything here exists to make that unreachable: `HOME`, `USERPROFILE` and every
`XDG_*` point inside the given directory, so the fallback branch - the one that
reads `Path.home()` because no `XDG_*` was set - becomes something a test can
exercise on purpose rather than something it must avoid.

`USERPROFILE` is in that list because `Path.home()` reads `HOME` on Linux and
`USERPROFILE` on Windows. Redirecting only `HOME` would make the isolation hold
on one operating system and silently fail on the other, in exactly the test that
removes `XDG_CONFIG_HOME` to reach the fallback.

Ported from `federated-knowledge-skills`, with the skill-installation half
dropped: `akit` is a package on PyPI rather than a script inside a skill, so
there is nothing to install into the house. What replaces it is the choice of
how to invoke the CLI, which is the one thing this module does that its ancestor
did not: see `run`.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from git_environment import without_git_variables

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE = REPO_ROOT / "src"

#: Variables the house must be able to *remove*, not merely override. A house
#: that unsets `XDG_CONFIG_HOME` while the parent environment still has one would
#: test the fallback against the developer's own config directory.
#:
#: The two `WIN_PD_OVERRIDE_*` are the Windows half of the same sentence, and
#: they are not optional there. `platformdirs` finds `%APPDATA%` and
#: `%LOCALAPPDATA%` by asking the shell (`SHGetKnownFolderPath`) rather than by
#: reading the environment, and the shell answers from a per-process cache it
#: fills on the first call. So on Windows the first test to resolve one of those
#: directories decides where *every later test in that process* believes its home
#: is, whatever `USERPROFILE` says by then: the second test's record lands in the
#: first test's directory. These two variables are the documented way past that
#: cache - `platformdirs` reads them on every call, before it asks the shell -
#: which is why `pyproject.toml` floors `platformdirs` at the release that added
#: them.
REDIRECTED = (
    "HOME",
    "USERPROFILE",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "XDG_CACHE_HOME",
    "XDG_STATE_HOME",
    "WIN_PD_OVERRIDE_APPDATA",
    "WIN_PD_OVERRIDE_LOCAL_APPDATA",
)


@dataclass
class FakeHome:
    """One throwaway machine: a home directory and the environment that confines it."""

    root: Path

    @property
    def env(self) -> dict[str, str]:
        """The environment that makes this house the only one a subprocess can see.

        The `XDG_*` variables are set explicitly rather than left to the
        fallback, because that is how a real session on Linux runs. The test
        that cares about the fallback removes them with `env_without_xdg`.
        """
        home = str(self.root)
        return {
            "HOME": home,
            "USERPROFILE": home,
            "XDG_CONFIG_HOME": str(self.root / ".config"),
            "XDG_DATA_HOME": str(self.root / ".local" / "share"),
            "XDG_CACHE_HOME": str(self.root / ".cache"),
            "XDG_STATE_HOME": str(self.root / ".local" / "state"),
            "WIN_PD_OVERRIDE_APPDATA": str(self.root / "AppData" / "Roaming"),
            "WIN_PD_OVERRIDE_LOCAL_APPDATA": str(self.root / "AppData" / "Local"),
        }

    @property
    def env_without_xdg(self) -> dict[str, str]:
        """The same house with every `XDG_*` unset, to reach the `Path.home()` fallback.

        The `WIN_PD_OVERRIDE_*` pair stays: on Windows there is no `XDG_*`
        fallback to reach, and removing them would send the very test that
        exercises the fallback at the shell's cached answer instead.
        """
        return {key: value for key, value in self.env.items() if not key.startswith("XDG_")}

    def environment(self, env: dict[str, str] | None = None) -> dict[str, str]:
        """The parent environment, carried for `PATH`, with this house written over it.

        The parent is carried rather than built from scratch because a hand-built
        environment is enough on Linux and not on Windows. Then every variable
        that could lead out of the house is deleted first and reinstated only if
        the house sets it, or `env_without_xdg` would leave the developer's own
        `XDG_CONFIG_HOME` in place and silently test nothing.

        The `GIT_` namespace goes too: `akit` shells out to git, and a suite run
        from a pre-commit hook would otherwise operate on this repository.
        """
        chosen = self.env if env is None else env
        merged = without_git_variables(os.environ)
        merged = {key: value for key, value in merged.items() if key not in REDIRECTED}
        merged.update(chosen)
        return merged

    def run(
        self, *args: str, env: dict[str, str] | None = None, cwd: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        """Run `akit` inside this house, as a subprocess, the way a person meets it.

        `-m federated_agent_kits` against the source tree rather than an
        installed console script: this layer runs on every commit, and building
        and installing a wheel per test would make it slow enough to skip. That
        the entry point itself works is a separate, deliberate test
        (`test_entry_point.py`), because an import is not an entry point.

        `cwd` defaults to the house and is a parameter because several commands
        read the repository they were run in. It is still inside the house: a
        directory outside it would defeat the isolation this module is for.
        """
        return self.run_python("-m", "federated_agent_kits", *args, env=env, cwd=cwd)

    def run_python(
        self, *args: str, env: dict[str, str] | None = None, cwd: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        """Run this interpreter inside the house, with `src/` importable."""
        merged = self.environment(env)
        merged["PYTHONPATH"] = str(SOURCE)
        return subprocess.run(
            [sys.executable, *args],
            capture_output=True,
            text=True,
            check=False,
            env=merged,
            cwd=str(self.root if cwd is None else cwd),
        )


def build_fake_home(root: Path) -> FakeHome:
    """A new house, with the directories a fresh machine would already have."""
    root.mkdir(parents=True, exist_ok=True)
    (root / ".config").mkdir(parents=True, exist_ok=True)
    return FakeHome(root=root)


def confine(monkeypatch: pytest.MonkeyPatch, root: Path) -> FakeHome:
    """Move *this* process into a house at `root`, for the duration of one test.

    The one way the in-process redirection is done, so that a fixture cannot
    redirect half of it: every variable in `REDIRECTED` is removed before the
    house sets its own, and a house that names fewer of them than the developer's
    environment holds therefore leaves none of the developer's behind.
    """
    house = build_fake_home(root)
    for name in REDIRECTED:
        monkeypatch.delenv(name, raising=False)
    for name, value in house.env.items():
        monkeypatch.setenv(name, value)
    return house
