"""`add`, `remove`, `update` and `harness` as a subprocess, in a fake home.

What this layer adds to `test_subscribing.py` is what that one cannot reach: the
exit codes a caller reads, the manifest as a file somebody opens afterwards, and
a source that was cloned rather than imported. Everything about which edit each
verb makes is tested in the unit layer, where it needs no subprocess.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from fake_home import FakeHome
from git_environment import FIXED_AUTHOR, git, local_remote

from federated_agent_kits.exits import Exit

pytestmark = pytest.mark.cli

SKILLS = Path(".agents") / "skills"

LAYOUT = {
    "skills/writing/SKILL.md": "# writing\n",
    "rules/prose-style.md": "Write in the present tense.\n",
}


@dataclass(frozen=True)
class Machine:
    """A fake machine with opencode installed, and a repository to run commands in."""

    home: FakeHome
    project: Path
    remote: str
    remote_root: Path

    def run(self, *args: str) -> tuple[int, str, str]:
        done = self.home.run(*args, cwd=self.project)
        return done.returncode, done.stdout, done.stderr

    @property
    def manifest(self) -> str:
        return (self.project / ".akit.yaml").read_text(encoding="utf-8")


@pytest.fixture
def machine(fake_home: FakeHome, tmp_path: Path) -> Machine:
    (fake_home.root / ".config" / "opencode").mkdir(parents=True)
    project = fake_home.root / "project"
    (project / ".git").mkdir(parents=True)
    (project / ".akit.yaml").write_text("version: 1\n", encoding="utf-8")
    remote_root = tmp_path / "remote"
    return Machine(
        home=fake_home,
        project=project,
        remote=local_remote(remote_root, LAYOUT),
        remote_root=remote_root,
    )


class TestTheRoundTripAPersonMakes:
    def test_a_kit_is_added_listed_updated_and_removed(self, machine: Machine):
        code, printed, errors = machine.run("add", machine.remote, "writing", "--kind", "skill")
        assert code == Exit.OK, errors
        assert "Subscribed" in printed
        assert (machine.project / SKILLS / "writing" / "SKILL.md").is_file()

        code, printed, errors = machine.run("list")
        assert code == Exit.OK, errors
        assert "writing" in printed

        (machine.remote_root / "skills" / "writing" / "SKILL.md").write_text("# writing, revised\n", encoding="utf-8")
        git("-C", str(machine.remote_root), "add", "-A")
        git("-C", str(machine.remote_root), *FIXED_AUTHOR, "commit", "-qm", "second")

        code, printed, errors = machine.run("update")
        assert code == Exit.OK, errors
        assert "# writing, revised" in printed
        assert (machine.project / SKILLS / "writing" / "SKILL.md").read_text(encoding="utf-8") == "# writing, revised\n"

        code, printed, errors = machine.run("remove", "writing")
        assert code == Exit.OK, errors
        assert not (machine.project / SKILLS / "writing").exists()
        assert "skills" not in machine.manifest

    def test_the_manifest_stays_a_file_somebody_can_read(self, machine: Machine):
        machine.run("add", machine.remote, "writing", "--kind", "skill")
        machine.run("harness", "add", "copilot-vscode")

        assert "harnesses: [detected, copilot-vscode]" in machine.manifest
        assert "# frozen: main, " in machine.manifest

    def test_every_command_is_a_no_op_on_its_second_run(self, machine: Machine):
        for argv in (
            ("add", machine.remote, "writing", "--kind", "skill"),
            ("harness", "add", "copilot-vscode"),
            ("update",),
            ("render",),
        ):
            machine.run(*argv)
            before = machine.manifest
            code, printed, errors = machine.run(*argv)

            assert code == Exit.OK, errors
            assert machine.manifest == before, f"{argv[0]} wrote something the second time"
            assert "Nothing changed" in printed or "already" in printed.lower()


class TestWhatTheExitCodeSays:
    def test_a_typo_is_a_usage_error_and_writes_nothing(self, machine: Machine):
        before = machine.manifest

        code, _, errors = machine.run("add", machine.remote, "wrting")

        assert code == Exit.USAGE
        assert "It holds skills: writing" in errors
        assert machine.manifest == before

    def test_a_name_in_both_manifests_asks_which(self, machine: Machine):
        machine.run("add", machine.remote, "writing", "--kind", "skill")
        machine.run("add", "--global", machine.remote, "writing", "--kind", "skill")

        code, _, errors = machine.run("remove", "writing")

        assert code == Exit.USAGE
        assert "--global for yours" in errors

    def test_a_repository_without_a_manifest_names_the_way_in(self, machine: Machine):
        (machine.project / ".akit.yaml").unlink()

        code, _, errors = machine.run("add", machine.remote, "writing")

        assert code == Exit.USAGE
        assert "--project to create it" in errors


class TestOffline:
    def test_add_of_a_cached_source_works_and_says_what_it_pinned(self, machine: Machine):
        machine.run("add", machine.remote, "writing", "--kind", "skill")
        for child in sorted(machine.remote_root.rglob("*"), key=lambda entry: len(entry.parts), reverse=True):
            child.chmod(0o700)
            child.rmdir() if child.is_dir() else child.unlink()
        machine.remote_root.rmdir()

        code, _, errors = machine.run("add", machine.remote, "prose-style", "--kind", "rule")

        assert code == Exit.OK, errors
        assert "frozen: the commit this machine already had" in machine.manifest

    def test_add_of_a_source_nobody_has_fails_saying_which(self, machine: Machine, tmp_path: Path):
        code, _, errors = machine.run("add", (tmp_path / "nowhere").as_uri(), "writing")

        assert code == Exit.ERROR
        assert "could not be cloned" in errors


def test_the_json_is_json_for_every_verb(machine: Machine):
    code, printed, errors = machine.run("--json", "add", machine.remote, "writing", "--kind", "skill")

    assert code == Exit.OK, errors
    payload = json.loads(printed)
    assert payload["command"] == "add"
    assert payload["render"]["subscriptions"][0]["name"] == "writing"
