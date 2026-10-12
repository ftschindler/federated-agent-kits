#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""Install a version from an index and check it actually runs.

Usage:
  verify-published.py <version> <index-url>

A publish step that is green means an index accepted the bytes. It does not mean
anybody can install them, and it does not mean what they install works. This
closes that gap for the rehearsal upload: resolve the exact version from the
index it was just pushed to, in a throwaway environment, and run the entry point
a user would run.

Two things make this less trivial than it reads.

An upload is not resolvable the instant it is accepted. The index has to publish
it, which usually takes seconds and occasionally takes longer, so a single
attempt is a race that passes on a laptop and fails one morning in CI. Hence the
retry, with a cap rather than a wait forever.

TestPyPI does not mirror PyPI, so a package whose dependencies live on PyPI
cannot be installed from TestPyPI alone. Both indexes are passed, with the
rehearsal index first and `unsafe-best-match` so that the one holding our
version wins while the dependencies still resolve. This is the one respect in
which the rehearsal is not shaped like the real thing, and it is worth knowing
rather than hiding.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time

PYPI = "https://pypi.org/simple/"
#: Roughly two minutes of waiting. The first budget was a minute and was spent
#: in full, once, on an upload the index had accepted and not yet published.
ATTEMPTS = 12
PAUSE_SECONDS = 10


def run(version: str, index: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    command = [
        "uvx",
        "--index",
        index,
        "--index",
        PYPI,
        # Without this, uv stops at the first index that has the package name at
        # all, which for a rehearsal index is the wrong one for the
        # dependencies and the right one for us.
        "--index-strategy",
        "unsafe-best-match",
        # uv caches an index's answer, including the answer "this version is not
        # here". Without this the retry loop asks the cache eleven times and
        # learns nothing after the first miss, which looks exactly like an index
        # that never caught up.
        "--refresh-package",
        "federated-agent-kits",
        "--from",
        f"federated-agent-kits=={version}",
        "akit",
        *arguments,
    ]
    print(" ".join(command), file=sys.stderr)
    return subprocess.run(command, capture_output=True, text=True, check=False)


def wait_for(version: str, index: str) -> subprocess.CompletedProcess[str]:
    """Resolve and run `akit --version`, retrying while the index catches up."""
    result = run(version, index, "--version")
    for attempt in range(2, ATTEMPTS + 1):
        if result.returncode == 0:
            return result
        print(
            f"verify-published: attempt {attempt - 1} did not resolve {version} yet; waiting {PAUSE_SECONDS}s.",
            file=sys.stderr,
        )
        time.sleep(PAUSE_SECONDS)
        result = run(version, index, "--version")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("version", help="the exact version to install, such as 0.2.1.dev123")
    parser.add_argument("index", help="the index to install it from")
    arguments = parser.parse_args(argv)

    installed = wait_for(arguments.version, arguments.index)
    if installed.returncode != 0:
        print(installed.stdout, file=sys.stderr)
        print(installed.stderr, file=sys.stderr)
        return fail(f"{arguments.version} never became installable from {arguments.index}")

    reported = installed.stdout.strip()
    if reported != f"akit {arguments.version}":
        return fail(f"installed {arguments.version} but it calls itself {reported!r}")
    print(f"Installed {arguments.version} from {arguments.index}, and it agrees: {reported}.")

    helped = run(arguments.version, arguments.index, "--help")
    if helped.returncode != 0:
        print(helped.stderr, file=sys.stderr)
        return fail("the installed entry point cannot print its own help")
    if "akit help manifest" not in helped.stdout:
        return fail("the installed help is not the help this repository builds")
    print("The entry point runs and prints the frame.")
    return 0


def fail(message: str) -> int:
    print(f"::error::{message}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
