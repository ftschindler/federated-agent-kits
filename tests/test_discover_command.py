"""`akit discover` as a subprocess, in a fake home, on a machine with an empty cache.

What this layer adds to `test_discovering.py` is the half that cannot be seen
in-process: the exit code a caller reads, and the claim the command's own help
makes about the cache. A `discover` is meant to leave the source on this disk,
so the test for that is a later command which never fetches answering from it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from fake_home import FakeHome
from git_environment import local_remote

from federated_agent_kits.exits import Exit

pytestmark = pytest.mark.cli

LAYOUT = {
    "skills/toolkit/writing/SKILL.md": "---\nname: writing\ndescription: How to write\n---\n\n# writing\n",
    "rules/prose-style.md": "Write in the present tense.\n",
}


@dataclass(frozen=True)
class Machine:
    """A fake machine with an empty cache, and a source it has never seen."""

    home: FakeHome
    project: Path
    remote: str

    def run(self, *args: str) -> tuple[int, str, str]:
        done = self.home.run(*args, cwd=self.project)
        return done.returncode, done.stdout, done.stderr


@pytest.fixture
def machine(fake_home: FakeHome, tmp_path: Path) -> Machine:
    (fake_home.root / ".config" / "opencode").mkdir(parents=True)
    project = fake_home.root / "project"
    (project / ".git").mkdir(parents=True)
    return Machine(home=fake_home, project=project, remote=local_remote(tmp_path / "remote", LAYOUT))


class TestAskingWhatASourceHolds:
    def test_it_lists_the_kinds_separately_and_succeeds(self, machine: Machine):
        code, printed, errors = machine.run("discover", machine.remote)

        assert code == Exit.OK, errors
        assert "Skills" in printed
        assert "- writing" in printed
        assert "Rules" in printed
        assert "- prose-style" in printed

    def test_it_writes_no_manifest(self, machine: Machine):
        machine.run("discover", machine.remote)

        assert not (machine.project / ".akit.yaml").exists()

    def test_json_carries_the_path_inside_the_source(self, machine: Machine):
        code, printed, errors = machine.run("discover", machine.remote, "--json")

        assert code == Exit.OK, errors
        found = {part["name"]: part for part in json.loads(printed)["parts"]}
        assert found["writing"]["path"] == "skills/toolkit/writing"
        assert found["writing"]["description"] == "How to write"
        assert json.loads(printed)["commit"] is not None

    def test_a_source_that_is_not_there_fails_rather_than_listing_nothing(self, machine: Machine, tmp_path: Path):
        code, _, errors = machine.run("discover", str(tmp_path / "nowhere"))

        assert code == Exit.ERROR
        assert "nowhere" in errors


class TestWhatItLeavesOnTheDisk:
    def test_the_source_is_in_the_cache_for_the_commands_that_never_fetch(self, machine: Machine):
        code, printed, errors = machine.run("discover", machine.remote, "--json")
        assert code == Exit.OK, errors
        commit = json.loads(printed)["commit"]
        (machine.project / ".akit.yaml").write_text(
            f"version: 1\nskills:\n  {machine.remote}#{commit}:\n  - writing\n", encoding="utf-8"
        )

        code, listed, errors = machine.run("list")

        assert code == Exit.OK, errors
        assert "writing" in listed
        assert "not in the cache" not in listed, "`list` fetches nothing, so this is what `discover` left behind"
