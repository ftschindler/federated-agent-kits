"""The walk for `.akit.yaml`, against repository shapes git actually produces.

`tests/test_manifest.py` covers the walk with hand-made `.git` entries, which is
enough for the logic and proves nothing about the assumption underneath it: that
a submodule and a linked worktree carry `.git` as a *file* rather than a
directory, and that both therefore stop the walk. That assumption is about git's
behaviour, so it is tested against git.

What it protects is one sentence of DESIGN.md section 6: the walk cannot stray
into somebody else's repository. The failure it exists to catch is silent. A walk
that treated a submodule as an ordinary directory would climb out of it, find
the superproject's `.akit.yaml`, and render the outer repository's kits while
somebody worked inside the inner one.

Marked `cli` rather than `unit` because it needs the git binary, which is what
that marker gates on, even though it calls the library in process.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from git_environment import FIXED_AUTHOR, git

from federated_agent_kits.manifest import find_project_manifest, worktree_root

pytestmark = pytest.mark.cli

MANIFEST = "version: 1\nskills:\n  owner/repo: [outer]\n"


def repository(path: Path, *, manifest: str | None = None) -> Path:
    """A real repository with one commit, and optionally a manifest beside its `.git`."""
    path.mkdir(parents=True, exist_ok=True)
    (path / "README.md").write_text("seed\n", encoding="utf-8")
    if manifest is not None:
        (path / ".akit.yaml").write_text(manifest, encoding="utf-8")
    git("init", "-q", "-b", "main", str(path))
    git("-C", str(path), "add", "-A")
    git("-C", str(path), *FIXED_AUTHOR, "commit", "-qm", "initial")
    return path


def test_the_walk_finds_the_manifest_from_a_deep_subdirectory(tmp_path: Path) -> None:
    outer = repository(tmp_path / "project", manifest=MANIFEST)
    deep = outer / "src" / "package" / "inner"
    deep.mkdir(parents=True)
    assert find_project_manifest(deep) == outer / ".akit.yaml"


def test_a_submodule_carries_git_as_a_file_and_stops_the_walk(tmp_path: Path) -> None:
    """The shape the whole walk rests on, confirmed against git rather than assumed."""
    inner = repository(tmp_path / "inner")
    outer = repository(tmp_path / "outer", manifest=MANIFEST)
    git(
        "-C",
        str(outer),
        # Modern git refuses a `file://` submodule unless told to allow it.
        # Nothing here reaches a network, which is the point of the fixture.
        "-c",
        "protocol.file.allow=always",
        *FIXED_AUTHOR,
        "submodule",
        "add",
        "-q",
        inner.as_uri(),
        "vendor/inner",
    )
    nested = outer / "vendor" / "inner"
    assert (nested / ".git").is_file(), "a submodule's .git is a file, not a directory"
    assert worktree_root(nested) == nested
    assert find_project_manifest(nested) is None, "the walk climbed out of the submodule"


def test_a_linked_worktree_stops_the_walk_too(tmp_path: Path) -> None:
    source = repository(tmp_path / "source", manifest=MANIFEST)
    linked = tmp_path / "linked"
    git("-C", str(source), *FIXED_AUTHOR, "worktree", "add", "-q", str(linked), "-b", "side")
    assert (linked / ".git").is_file(), "a linked worktree's .git is a file"
    assert worktree_root(linked) == linked
    # The manifest was committed, so the worktree has its own copy. The point is
    # that this is the worktree's own file rather than one found by climbing.
    assert find_project_manifest(linked) == linked / ".akit.yaml"


def test_a_worktree_without_the_manifest_does_not_borrow_its_sources(tmp_path: Path) -> None:
    source = repository(tmp_path / "source", manifest=MANIFEST)
    linked = tmp_path / "linked"
    git("-C", str(source), *FIXED_AUTHOR, "worktree", "add", "-q", str(linked), "-b", "side")
    (linked / ".akit.yaml").unlink()
    assert find_project_manifest(linked) is None


def test_a_repository_inside_a_repository_stops_at_the_inner_one(tmp_path: Path) -> None:
    outer = repository(tmp_path / "outer", manifest=MANIFEST)
    inner = repository(outer / "vendor" / "other")
    assert worktree_root(inner) == inner
    assert find_project_manifest(inner) is None
