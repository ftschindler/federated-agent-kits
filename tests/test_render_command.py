"""`akit render` as a subprocess, in a fake home, against a real cloned source.

What this layer adds to the unit tests is the half they deliberately do not
touch: a source that was cloned rather than read where it sits, the entry point,
the exit codes, and the claim that those two kinds of source render to the same
bytes. Everything about *what* is written and *what may be deleted* is tested in
`test_render.py`, where it needs neither git nor a subprocess.
"""

from __future__ import annotations

import hashlib
import json
import textwrap
from dataclasses import dataclass
from pathlib import Path

import pytest
from fake_home import FakeHome
from git_environment import local_remote

from federated_agent_kits.exits import Exit

pytestmark = pytest.mark.cli

SKILLS = Path(".agents") / "skills"

#: `render` never fetches, so a machine it runs on has to have fetched already.
#: `akit add` is what does that from T7; until then the fixture does it, and
#: asks the package where this platform keeps the cache rather than writing the
#: Linux answer down as if it were the only one.
PREFETCH = textwrap.dedent(
    """
    import json, sys
    from pathlib import Path
    from federated_agent_kits import cache, manifest, record, sources

    cache.resolve(sources.parse(sys.argv[1]), anchor=Path(sys.argv[2]))
    print(json.dumps({
        "manifest": str(manifest.user_manifest_path()),
        "cache": str(cache.root()),
        "record": str(record.location()),
    }))
    """
)


@dataclass(frozen=True)
class Machine:
    """A fake machine that has already fetched one source, and where it keeps things."""

    home: FakeHome
    manifest: Path
    record: Path


def tree(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


LAYOUT = {
    "skills/writing/SKILL.md": "# writing\n",
    "skills/writing/references/style.md": "# style\n",
}


@pytest.fixture
def remote(tmp_path: Path) -> str:
    return local_remote(tmp_path / "remote", LAYOUT)


@pytest.fixture
def machine(fake_home: FakeHome, remote: str) -> Machine:
    """A machine with opencode installed and the source already in its cache."""
    (fake_home.root / ".config" / "opencode").mkdir(parents=True)
    done = fake_home.run_python("-c", PREFETCH, remote, str(fake_home.root))
    assert done.returncode == 0, done.stderr
    places = json.loads(done.stdout)
    return Machine(home=fake_home, manifest=Path(places["manifest"]), record=Path(places["record"]))


def repository(machine: Machine, name: str, source: str) -> Path:
    root = machine.home.root / name
    (root / ".git").mkdir(parents=True)
    (root / ".akit.yaml").write_text(f"version: 1\n\nskills:\n  {source}: [writing]\n", encoding="utf-8")
    return root


class TestRenderingFromASourceThatWasCloned:
    def test_it_writes_the_skill_and_says_so(self, machine: Machine, remote: str):
        project = repository(machine, "project", remote)

        done = machine.home.run("render", cwd=project)

        assert done.returncode == Exit.OK, done.stderr
        assert (project / SKILLS / "writing" / "SKILL.md").read_text(encoding="utf-8") == "# writing\n"
        assert "wrote" in done.stdout

    def test_it_ignores_what_it_wrote_so_nobody_commits_it(self, machine: Machine, remote: str):
        project = repository(machine, "project", remote)

        machine.home.run("render", cwd=project)

        assert ".agents/skills/" in (project / ".gitignore").read_text(encoding="utf-8")

    def test_a_second_run_is_a_proven_no_op(self, machine: Machine, remote: str):
        project = repository(machine, "project", remote)
        machine.home.run("render", cwd=project)
        before = tree(project / SKILLS)

        done = machine.home.run("render", cwd=project)

        assert tree(project / SKILLS) == before
        assert "Nothing changed" in done.stdout

    def test_the_record_lands_in_this_machines_state_directory(self, machine: Machine, remote: str):
        project = repository(machine, "project", remote)

        machine.home.run("render", cwd=project)

        written = json.loads(machine.record.read_text(encoding="utf-8"))
        assert [Path(entry["path"]).name for entry in written["written"]] == ["SKILL.md", "style.md"]

    def test_json_is_the_same_run_as_data(self, machine: Machine, remote: str):
        project = repository(machine, "project", remote)

        done = machine.home.run("render", "--json", cwd=project)

        assert json.loads(done.stdout)["subscriptions"][0]["name"] == "writing"


class TestASourceThatIsAlreadyHere:
    def test_a_path_source_and_a_cloned_one_render_to_the_same_bytes(
        self, machine: Machine, remote: str, tmp_path: Path
    ):
        nearby = tmp_path / "my-kits"
        for relative, text in LAYOUT.items():
            (nearby / relative).parent.mkdir(parents=True, exist_ok=True)
            (nearby / relative).write_text(text, encoding="utf-8")
        cloned = repository(machine, "cloned", remote)
        local = repository(machine, "local", str(nearby))

        machine.home.run("render", cwd=cloned)
        machine.home.run("render", cwd=local)

        assert tree(cloned / SKILLS) == tree(local / SKILLS)


class TestWhenItWillNotRun:
    def test_an_uncached_source_fails_saying_which_it_was(self, machine: Machine, tmp_path: Path):
        project = repository(machine, "project", "nobody/nothing")

        done = machine.home.run("render", cwd=project)

        assert done.returncode == Exit.ERROR
        assert "not in the cache" in done.stdout
        assert "does not fetch" in done.stdout

    def test_check_is_a_usage_error_naming_the_task_it_waits_for(self, machine: Machine, remote: str):
        project = repository(machine, "project", remote)

        done = machine.home.run("render", "--check", cwd=project)

        assert done.returncode == Exit.USAGE
        assert "T8" in done.stderr

    def test_a_harness_nobody_knows_is_a_usage_error_rather_than_a_silent_skip(self, machine: Machine, remote: str):
        project = repository(machine, "project", remote)

        done = machine.home.run("render", "--harness", "emacs", cwd=project)

        assert done.returncode == Exit.USAGE
        assert "emacs" in done.stderr


class TestAMachineWithNothingOnIt:
    def test_a_render_with_no_manifests_anywhere_says_so_and_succeeds(self, machine: Machine):
        loose = machine.home.root / "empty"
        loose.mkdir()

        done = machine.home.run("render", cwd=loose)

        assert done.returncode == Exit.OK, done.stderr
        assert "nothing subscribed here" in done.stdout
        assert "Nothing changed" in done.stdout

    def test_your_own_subscriptions_render_into_your_home(self, machine: Machine, remote: str):
        machine.manifest.parent.mkdir(parents=True, exist_ok=True)
        machine.manifest.write_text(f"version: 1\n\nskills:\n  {remote}: [writing]\n", encoding="utf-8")

        done = machine.home.run("render", "--global")

        assert done.returncode == Exit.OK, done.stderr
        assert (machine.home.root / SKILLS / "writing" / "SKILL.md").is_file()


class TestTheEntryPointAPersonActuallyTypes:
    def test_the_help_a_person_reaches_for_names_what_it_writes(self, machine: Machine):
        done = machine.home.run("render", "--help")

        assert done.returncode == Exit.OK
        assert "render record" in done.stdout or "hash" in done.stdout
        assert "Next:" in done.stdout
