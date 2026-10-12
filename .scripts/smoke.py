#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""Install a built wheel with `uvx` and render a repository that has nothing.

Usage:
  smoke.py [wheel] [--keep]

The sentence this checks is the one the README makes and every contributing
guide repeats: clone a repository that carries an `.akit.yaml`, run one command,
and the files each harness reads are there. Nothing is installed first, nothing
is cached, and the kits come from a real public source over the network.

**The wheel is this working tree's, not the index's.** `uvx --from
federated-agent-kits` resolves to the last release, so a pull request running
the literal line would green-light code it never ran. Pointing `uvx` at a local
wheel keeps the invocation identical in every respect that can break and makes
the branch the thing under test. Named without an argument, it takes the one
wheel in `dist/`, because the shell a CI runner uses is PowerShell on half the
matrix and the two do not expand a glob the same way.

**The repository is built here rather than cloned.** What the claim needs is a
target with a committed manifest and an empty cache, and a repository on a forge
would add a second thing to keep in step for nothing. The source it subscribes
to is real and pinned, because that is the half the smoke cannot fake.

Everything happens inside a temporary directory, including `HOME`, so a bug here
cannot reach the config, cache or state directory of whoever runs it.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

#: A published, akit-shaped source, pinned so that editing it cannot turn this
#: red on an unrelated afternoon. `tests/test_support_scripts.py` asserts this
#: is the same source and commit the federation layer reads.
SOURCE = "ftschindler/agent-kits"
COMMIT = "e2c019f"
KIT = "writing"

#: `copilot-ci` has no machine, so it arrives by being named rather than by
#: being detected, which is what makes this assertable on a bare runner: a
#: harness that is detected would render nothing where nothing is installed.
HARNESS = "copilot-ci"

MANIFEST = f"""version: 1

skills:
  {SOURCE}#{COMMIT}:
  - {KIT}

rules:
- {SOURCE}#{COMMIT}:
  - {KIT}

harnesses:
- {HARNESS}
"""

#: What the harness reads, which is the only evidence that the render landed.
EXPECTED = (
    Path(".agents") / "skills" / KIT / "SKILL.md",
    Path(".github") / "instructions" / f"{KIT}.instructions.md",
)


def environment(home: Path) -> dict[str, str]:
    """A machine of its own: no config, no cache, no state, and no git identity."""
    env = {key: value for key, value in os.environ.items() if not key.startswith(("XDG_", "GIT_"))}
    env.update(
        {
            "HOME": str(home),
            "USERPROFILE": str(home),
            "GIT_CONFIG_GLOBAL": str(home / "gitconfig"),
            "GIT_CONFIG_SYSTEM": str(home / "gitconfig"),
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    for name in ("CACHE", "CONFIG", "DATA", "STATE"):
        env[f"XDG_{name}_HOME"] = str(home / name.lower())
    return env


def run(command: list[str], *, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    print(f"$ {' '.join(command)}", file=sys.stderr)
    done = subprocess.run(command, cwd=str(cwd), env=env, capture_output=True, text=True, check=False)
    print(done.stdout)
    if done.stderr:
        print(done.stderr, file=sys.stderr)
    return done


def prepare(root: Path, env: dict[str, str]) -> Path:
    """A repository holding nothing but the manifest a colleague would clone."""
    repository = root / "clone"
    repository.mkdir(parents=True)
    run(["git", "init", "--quiet", "-b", "main", "."], cwd=repository, env=env)
    (repository / ".akit.yaml").write_text(MANIFEST, encoding="utf-8")
    return repository


def smoke(wheel: Path, root: Path) -> int:
    home = root / "home"
    home.mkdir(parents=True)
    env = environment(home)
    repository = prepare(root, env)
    akit = ["uvx", "--from", str(wheel), "akit"]

    rendered = run([*akit, "render"], cwd=repository, env=env)
    if rendered.returncode != 0:
        return fail(f"`akit render` exited {rendered.returncode} in a clone with nothing cached")

    missing = [path for path in EXPECTED if not (repository / path).is_file()]
    if missing:
        return fail(
            "the render reported success and wrote nothing for: " + ", ".join(path.as_posix() for path in missing)
        )

    unchanged = (repository / ".akit.yaml").read_text(encoding="utf-8") == MANIFEST
    if not unchanged:
        return fail("the render edited the manifest the repository committed")

    checked = run([*akit, "render", "--check"], cwd=repository, env=env)
    if checked.returncode != 0:
        return fail(f"`akit render --check` called a fresh render stale, exiting {checked.returncode}")

    print("A clone with an empty cache rendered what the harness reads, and passed its own check.")
    return 0


def fail(message: str) -> int:
    print(f"::error::{message}", file=sys.stderr)
    return 1


DIST = Path(__file__).resolve().parent.parent / "dist"


def only_wheel() -> Path | None:
    """The one wheel in `dist/`, or nothing when there is not exactly one."""
    built = sorted(DIST.glob("*.whl"))
    return built[0] if len(built) == 1 else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("wheel", type=Path, nargs="?", help="the wheel to install; by default the one in dist/")
    parser.add_argument("--keep", action="store_true", help="leave the temporary machine on disk for inspection")
    arguments = parser.parse_args(argv)

    chosen = arguments.wheel if arguments.wheel is not None else only_wheel()
    if chosen is None:
        return fail(f"{DIST} does not hold exactly one wheel; run `uv build --wheel --out-dir dist` first")
    wheel = chosen.resolve()
    if not wheel.is_file():
        return fail(f"there is no wheel at {wheel}; run `uv build --wheel --out-dir dist` first")

    root = Path(tempfile.mkdtemp(prefix="akit-smoke-"))
    try:
        return smoke(wheel, root)
    finally:
        if arguments.keep:
            print(f"Left the temporary machine at {root}.", file=sys.stderr)
        else:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
