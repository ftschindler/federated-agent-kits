"""Which build this is, and where the manifest schema that matches it is published.

The schema is published and not used. A manifest is read by the parser in
`manifest.py`, whose refusals name a line and a fix, and a second validator
would be a second, worse-worded answer to the same mistakes. What the schema is
for is everything that happens before `akit` runs: an editor underlining a typo
as it is made, and a `check-jsonschema` hook failing a pull request that commits
one.

**The URL names a tag rather than a branch.** A `$schema` line somebody pastes
into a file they own should not change meaning overnight, and the schema a build
publishes is the format that build reads. A source tree that was never installed
has no version to name, so it points at `main`: the alternative is a URL with
`v0+unknown` in it, which is a 404 shaped like a version.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as installed_version

DISTRIBUTION = "federated-agent-kits"

#: What `version()` answers in a source tree that was never installed.
UNRELEASED = "0+unknown"

REPOSITORY = "https://raw.githubusercontent.com/ftschindler/federated-agent-kits"

#: Where the schema sits inside the repository, at whichever revision is named.
SCHEMA_FILE = "schema/akit-manifest.schema.json"

#: The comment yaml-language-server reads, which is how an editor finds a schema
#: for a file whose name it has never heard of.
DIRECTIVE = "# yaml-language-server: $schema="


def version() -> str:
    """What `--version` prints, read from the installed metadata rather than a constant.

    One number, in `pyproject.toml`, written by the release job. A constant here
    would be a second place to forget, and the skill's own `VERSION` file is
    written from the same number so the two cannot disagree.
    """
    try:
        return installed_version(DISTRIBUTION)
    except PackageNotFoundError:  # a source tree that was never installed
        return UNRELEASED


def revision() -> str:
    """The tag this build's schema is published under, or `main` when there is none."""
    release = version()
    return "main" if release == UNRELEASED else f"v{release}"


def url() -> str:
    """The schema this build reads, at a revision that will not move under anybody."""
    return f"{REPOSITORY}/{revision()}/{SCHEMA_FILE}"


def header() -> str:
    """The line that points an editor at the schema, written into manifests `akit` creates.

    Into those only. Every other write goes through a round-tripper whose whole
    job is to give back the file it was handed, and a tool that edited a line
    nobody asked it to edit would be the thing that rule exists to prevent.
    """
    return f"{DIRECTIVE}{url()}"


__all__ = [
    "DIRECTIVE",
    "DISTRIBUTION",
    "REPOSITORY",
    "SCHEMA_FILE",
    "UNRELEASED",
    "header",
    "revision",
    "url",
    "version",
]
