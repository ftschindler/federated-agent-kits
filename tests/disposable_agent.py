"""A disposable agent: install skills into it, send it a message, throw it away.

`DisposableAgent` is a real agent you can talk to, built from scratch and owned by
the caller. Underneath it is a pinned opencode inside a redirected HOME, but a
test never needs to know that — it installs skills, calls `run()`, and reads the
transcript that comes back.

Nothing here touches the developer's real machine: HOME and all XDG_* point into
the given root directory, and the whole thing is deleted with it.

It knows nothing about which skills it installs. `install_skills` takes a
directory and copies whatever skill directories it finds, which is what let it
outlive the skills it was originally written for.

Shared by the pytest fixtures (tests/conftest.py) and the convenience script
(.scripts/disposable-agent.py) so there is exactly one definition of how one is
built.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from git_environment import without_git_variables

WINDOWS = sys.platform == "win32"

# npm ships as `npm.cmd` on Windows, and a .cmd is not an executable the OS can
# spawn directly: `subprocess` would raise FileNotFoundError on a machine where
# `npm --version` works fine in a terminal. Resolving through PATH asks the same
# question the shell does, and keeps `shell=True` (and its quoting) out of this.
NPM = shutil.which("npm") or "npm"
NPX = shutil.which("npx") or "npx"

# Pinned so the e2e behaviour is reproducible; bump deliberately like our other
# frozen tool versions.
OPENCODE_VERSION = "1.18.25"

# One allowance for every agent run. A run is an LLM driving tools, so its duration
# swings with the tool path it picks: tests that take ~60s locally have twice blown
# a 300s cap on a CI runner. A genuinely stuck run is caught by the job timeout.
AGENT_RUN_TIMEOUT = 600

REPO_ROOT = Path(__file__).resolve().parent.parent

# Where this repo's own skills live. Absent until the first one lands, which
# `install_skills` tolerates rather than failing on.
REPO_SKILLS_DIR = REPO_ROOT / "skills"

# The version the locally built wheel claims. The skill tells an agent to type
# `uvx --from federated-agent-kits akit`, which is the sentence under test, and
# left alone that sentence reaches PyPI and exercises whatever shipped last
# rather than this branch. Pointing uv at a directory of wheels is not enough on
# its own: a local build carries the same version as the published one, and a
# resolver handed two is free to take either. A version nothing will ever
# publish makes the local build the only answer, while the index stays reachable
# for the dependencies, which a `--no-index` would not.
LOCAL_WHEEL_VERSION = "99.0.0"

# What a wheel has to be built from. The build backend reads `pyproject.toml`
# and packages `src/`; the other two are named by it and a build fails without
# them. The tests are left out on purpose, so what the agent installs is what a
# user installs.
WHEEL_INPUTS = ("pyproject.toml", "src", "README.md", "LICENSE")

VERSION_LINE = re.compile(r'^version = "[^"]+"$', re.MULTILINE)

# Build artifacts that an install must never carry. A `.pyc` names the absolute
# path it was compiled from, which is a fact about the author's machine and has
# no business in somebody else's skills directory.
NOT_PART_OF_A_SKILL = ("__pycache__", "*.pyc", ".ruff_cache", ".pytest_cache")

UV = shutil.which("uv") or "uv"


def build_local_wheel(into: Path) -> Path:
    """Build this working tree as a wheel `uvx` will prefer over the published one.

    The tree is copied rather than built in place, because the one edit this
    needs - the version - is to a file a developer is probably looking at, and a
    test that rewrites `pyproject.toml` in the repository is a test that leaves
    a dirty working tree behind when it fails.
    """
    stage = into / "tree"
    stage.mkdir(parents=True, exist_ok=True)
    for name in WHEEL_INPUTS:
        source = REPO_ROOT / name
        if source.is_dir():
            shutil.copytree(
                source, stage / name, dirs_exist_ok=True, ignore=shutil.ignore_patterns(*NOT_PART_OF_A_SKILL)
            )
        else:
            shutil.copy2(source, stage / name)
    pyproject = stage / "pyproject.toml"
    pyproject.write_text(
        VERSION_LINE.sub(f'version = "{LOCAL_WHEEL_VERSION}"', pyproject.read_text(encoding="utf-8"), count=1),
        encoding="utf-8",
    )
    wheels = into / "wheels"
    subprocess.run(
        [UV, "build", "--wheel", "--out-dir", str(wheels), str(stage)],
        check=True,
        capture_output=True,
        text=True,
        timeout=300,
    )
    built = sorted(wheels.glob("federated_agent_kits-*.whl"))
    if not built:
        raise AssertionError(f"no wheel was built into {wheels}")
    return wheels


def have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


@dataclass
class OpencodeResult:
    events: list[dict]
    stdout: str
    stderr: str
    returncode: int
    workdir: Path

    @classmethod
    def parse(cls, stdout: str, stderr: str, rc: int, workdir: Path) -> OpencodeResult:
        events = []
        for raw in stdout.splitlines():
            line = raw.strip()
            if not line.startswith("{"):
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return cls(events=events, stdout=stdout, stderr=stderr, returncode=rc, workdir=workdir)

    @property
    def text(self) -> str:
        """Concatenated assistant text output across all events."""
        chunks = []
        for ev in self.events:
            part = ev.get("part", {})
            if ev.get("type") == "text" and "text" in part:
                chunks.append(part["text"])
        return "\n".join(chunks)


class OpencodeTimeoutError(AssertionError):
    """An `opencode run` that outlived its allowance, carrying its partial transcript."""


def _timeout_report(partial: OpencodeResult, timeout: int) -> str:
    return (
        f"opencode run exceeded {timeout}s and was killed.\n"
        f"--- assistant transcript so far ---\n{partial.text.strip() or '(none)'}\n"
        f"--- stderr ---\n{partial.stderr.strip() or '(empty)'}"
    )


@dataclass
class DisposableAgent:
    """A throwaway agent rooted at a temp HOME, with skills installed into it."""

    home: Path
    opencode_bin: Path
    env: dict[str, str] = field(default_factory=dict)

    @property
    def agents_skills(self) -> Path:
        return self.home / ".agents" / "skills"

    @property
    def work(self) -> Path:
        return self.home / "work"

    def install_skills(self, source: Path) -> list[str]:
        """Copy every skill directory under `source` into ~/.agents/skills.

        A skill is any subdirectory holding a SKILL.md, which is what the Agent
        Skills spec makes discoverable. Returns the names installed; a missing or
        empty `source` installs nothing and is not an error.

        Compiled Python is excluded, and not only for tidiness. A `.pyc` embeds
        the absolute path of the source it was built from, so copying one carries
        the developer's checkout into a home that is supposed to know nothing
        about it - and an agent that reads its own skill directory can then walk
        out of the sandbox into the repository under test. That happened: a test
        asked a question whose answer was seeded in a bundle, and got an answer
        about the test file instead.
        """
        self.agents_skills.mkdir(parents=True, exist_ok=True)
        if not source.is_dir():
            return []
        installed = []
        for skill in sorted(source.iterdir()):
            if not (skill / "SKILL.md").is_file():
                continue
            shutil.copytree(
                skill,
                self.agents_skills / skill.name,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns(*NOT_PART_OF_A_SKILL),
            )
            installed.append(skill.name)
        return installed

    def install_from_registry(self, repo: str) -> None:
        """Install a published skill set into ~/.agents/skills via skills.sh."""
        subprocess.run(
            [NPX, "--yes", "skills", "add", repo, "--skill", "*", "-a", "opencode", "-g", "-y", "--copy"],
            check=True,
            env=self.env,
            cwd=self.home,
            capture_output=True,
            text=True,
            timeout=300,
        )

    def run(self, message: str, *, cwd: Path | None = None, timeout: int = AGENT_RUN_TIMEOUT) -> OpencodeResult:
        """Drive `opencode run` non-interactively and capture parsed JSON events."""
        workdir = cwd or self.work
        workdir.mkdir(parents=True, exist_ok=True)
        # Restored deliberately, pointing where the process actually is: tools
        # that read `PWD` should see the sandbox rather than nothing at all.
        env = {**self.env, "PWD": str(workdir)}
        proc = subprocess.Popen(
            [str(self.opencode_bin), "run", "--format", "json", message],
            env=env,
            cwd=workdir,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
            raise OpencodeTimeoutError(
                _timeout_report(OpencodeResult.parse(stdout, stderr, -9, workdir), timeout)
            ) from None
        return OpencodeResult.parse(stdout, stderr, proc.returncode, workdir)

    @property
    def enter_command(self) -> str:
        """A copy-pasteable shell command that drops you into this agent's world.

        The redirected env vars are what make opencode see this agent's skills and
        config instead of the developer's real ones.
        """
        names = (
            "HOME",
            "USERPROFILE",
            "XDG_CONFIG_HOME",
            "XDG_DATA_HOME",
            "XDG_CACHE_HOME",
            "XDG_STATE_HOME",
        )
        if WINDOWS:
            # PowerShell, because `env VAR=... bash` is a POSIX sentence and the
            # hint is only useful if it can be pasted where it is printed.
            sets = "; ".join(f'$env:{k}="{self.env[k]}"' for k in names if k in self.env)
            return f'cd "{self.work}"; {sets}\n# opencode: {self.opencode_bin}'
        env_pairs = " ".join(f"{k}={shlex.quote(self.env[k])}" for k in names if k in self.env)
        oc = shlex.quote(str(self.opencode_bin))
        return f"cd {shlex.quote(str(self.work))} && env {env_pairs} PATH={shlex.quote(self.env.get('PATH', ''))} bash\n# opencode: {oc}"

    def enter_hint(self, *, reason: str) -> str:
        """A multi-line, human-friendly block explaining how to inspect this agent."""
        return (
            f"\n──────────────────────────────────────────────────────────────\n"
            f"{reason}\n"
            f"Disposable agent preserved at: {self.home}\n"
            f"Enter it for inspection with:\n\n"
            f"    {self.enter_command}\n\n"
            f"Inside, `opencode` sees the skills under {self.agents_skills}\n"
            f"or run the convenience script:  make agent\n"
            f"──────────────────────────────────────────────────────────────\n"
        )


# Variables that would point the agent back at the developer's real setup.
# Redirecting HOME and XDG_* is not enough on its own: `OPENCODE_CONFIG_DIR`
# overrides config lookup outright, so a developer who has one set silently
# re-attaches every "disposable" agent to their real profile — reading their
# models and plugins while looking for credentials in an empty fake home. The
# failure that surfaces is an opaque provider error, nowhere near the cause.
LEAKY_ENV_PREFIX = "OPENCODE"

# `PWD` and `OLDPWD` are inherited verbatim and name the directory pytest was
# started from, which is the repository under test. `subprocess` sets the child's
# working directory but never updates these, so they arrive stale and absolute -
# a signpost out of the sandbox, in an agent that is granted `external_directory`
# so it can load its own skills. An agent asked a question whose answer was
# seeded in a bundle followed that signpost to the test file and answered about
# the test instead, twice, before this was found.
LEAKY_ENV_VARS = ("PWD", "OLDPWD")

# The `GIT_` namespace is dropped by `_isolated_env` for the same reason, one
# step further out: when this suite is run from a git hook those variables name
# the repository being committed to, and an agent that is told to commit what it
# files would commit it there. See tests/git_environment.py.


def _isolated_env(home: Path, wheels: Path | None = None) -> dict[str, str]:
    """The developer's environment, minus anything that reaches back out of `home`."""
    env = {
        k: v
        for k, v in without_git_variables(os.environ).items()
        if not k.startswith(LEAKY_ENV_PREFIX) and k not in LEAKY_ENV_VARS and not k.startswith("UV_")
    }
    env.update(
        {
            "HOME": str(home),
            # What `Path.home()` reads on Windows; see tests/fake_home.py.
            "USERPROFILE": str(home),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "XDG_DATA_HOME": str(home / ".local" / "share"),
            "XDG_CACHE_HOME": str(home / ".cache"),
            "XDG_STATE_HOME": str(home / ".local" / "state"),
            # uv keeps its cache and its tools outside XDG on some platforms, so
            # an agent that installs `akit` would otherwise write into the
            # developer's own uv cache and leave it there after the test.
            "UV_CACHE_DIR": str(home / ".cache" / "uv"),
            "UV_TOOL_DIR": str(home / ".local" / "share" / "uv" / "tools"),
            "UV_TOOL_BIN_DIR": str(home / ".local" / "bin"),
        }
    )
    if wheels is not None:
        env["UV_FIND_LINKS"] = str(wheels)
    return env


def _write_opencode_config(home: Path) -> None:
    """Let the agent reach its own home outside its working directory.

    `opencode run` is non-interactive, so any permission prompt is auto-rejected.
    Skills live in `~/.agents/skills`, outside the workdir, so without this every
    run dies on an `external_directory` prompt before the skill can do — or refuse
    — anything. A real user grants this once interactively; here we grant it up
    front.
    """
    config_dir = home / ".config" / "opencode"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "opencode.json").write_text(
        json.dumps(
            {
                "$schema": "https://opencode.ai/config.json",
                "permission": {"external_directory": "allow"},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def build_disposable_agent(
    root: Path,
    *,
    skills_dir: Path | None = REPO_SKILLS_DIR,
    wheels: Path | None = None,
) -> DisposableAgent:
    """Build a disposable agent under `root`: install opencode, then the given skills.

    `root` must be a directory the caller owns; everything lives under `root/home`.
    `skills_dir` defaults to this repo's own skills and may be absent. `wheels` is
    a directory of locally built wheels the agent's `uvx` prefers, which is how a
    test exercises this branch's `akit` rather than the last release.
    """
    home = root / "home"
    home.mkdir(parents=True, exist_ok=True)
    env = _isolated_env(home, wheels)

    npm_prefix = home / ".npm"
    npm_prefix.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [NPM, "install", f"opencode-ai@{OPENCODE_VERSION}", "--prefix", str(npm_prefix)],
        check=True,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    # The npm package pulls a per-platform binary; locate the real executable,
    # not the shim beside it, and prefer the non-baseline build. On Windows the
    # binary carries the `.exe` the shebang-less loader needs.
    pattern = "node_modules/opencode-*/bin/opencode.exe" if WINDOWS else "node_modules/opencode-*/bin/opencode"
    candidates = sorted(npm_prefix.glob(pattern))
    binaries = [c for c in candidates if c.is_file() and "baseline" not in c.parent.parent.name]
    opencode_bin = binaries[0] if binaries else candidates[0]

    _write_opencode_config(home)

    agent = DisposableAgent(home=home, opencode_bin=opencode_bin, env=env)
    if skills_dir is not None:
        agent.install_skills(skills_dir)
    agent.work.mkdir(parents=True, exist_ok=True)
    return agent
