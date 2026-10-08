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
from git_environment import FIXED_AUTHOR, git, local_remote
from ruamel.yaml import YAML

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
        "record": str(record.user_location()),
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
    "rules/prose-style.md": "Write in the present tense.\n",
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


def repository(machine: Machine, name: str, source: str, body: str | None = None) -> Path:
    root = machine.home.root / name
    (root / ".git").mkdir(parents=True)
    (root / ".akit.yaml").write_text(
        body if body is not None else f"version: 1\n\nskills:\n  {source}: [writing]\n", encoding="utf-8"
    )
    return root


def subscribed_to_the_rule(machine: Machine, name: str, source: str) -> Path:
    """A repository that names both shapes, so one rule has to reach both.

    `copilot-vscode` is named rather than detected because this fake home has
    only opencode installed, and naming a harness is how you render for one
    this machine does not have (DESIGN.md section 6).
    """
    return repository(
        machine,
        name,
        source,
        f"version: 1\nharnesses: [detected, copilot-vscode]\n\nrules:\n- {source}: prose-style\n",
    )


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

    def test_a_rule_reaches_both_shapes_from_one_source_file(self, machine: Machine, remote: str):
        """The claim T6 is for, through the entry point and a real clone."""
        project = subscribed_to_the_rule(machine, "project", remote)

        done = machine.home.run("render", cwd=project)

        assert done.returncode == Exit.OK, done.stderr
        copilot = project / ".github" / "instructions" / "prose-style.instructions.md"
        assert copilot.read_text(encoding="utf-8") == '---\napplyTo: "**"\n---\n\nWrite in the present tense.\n'
        assert (project / "AGENTS.md").read_text(encoding="utf-8") == (
            "<!-- BEGIN akit prose-style -->\nWrite in the present tense.\n<!-- END akit prose-style -->\n"
        )

    def test_a_rule_renders_the_same_on_a_second_run_and_keeps_your_own_prose(self, machine: Machine, remote: str):
        project = subscribed_to_the_rule(machine, "project", remote)
        machine.home.run("render", cwd=project)
        host = project / "AGENTS.md"
        host.write_text(f"# My own notes\n\n{host.read_text(encoding='utf-8')}", encoding="utf-8")
        before = host.read_text(encoding="utf-8")

        done = machine.home.run("render", cwd=project)

        assert "Nothing changed" in done.stdout
        assert host.read_text(encoding="utf-8") == before

    def test_the_file_we_share_is_never_ignored_and_the_directory_we_own_is(self, machine: Machine, remote: str):
        project = subscribed_to_the_rule(machine, "project", remote)

        machine.home.run("render", cwd=project)

        listed = (project / ".gitignore").read_text(encoding="utf-8")
        assert ".github/instructions/" in listed
        assert "AGENTS.md" not in listed

    def test_the_record_lands_inside_the_repository_it_describes(self, machine: Machine, remote: str):
        project = repository(machine, "project", remote)

        machine.home.run("render", cwd=project)

        written = json.loads((project / ".akit" / "render.json").read_text(encoding="utf-8"))
        assert [Path(entry["path"]).name for entry in written["written"]] == ["SKILL.md", "style.md"]
        assert not machine.record.exists()

    def test_the_repositorys_own_record_is_ignored_like_everything_else_we_write(self, machine: Machine, remote: str):
        project = repository(machine, "project", remote)

        machine.home.run("render", cwd=project)

        assert ".akit/" in (project / ".gitignore").read_text(encoding="utf-8")

    def test_json_is_the_same_run_as_data(self, machine: Machine, remote: str):
        project = repository(machine, "project", remote)

        done = machine.home.run("render", "--json", cwd=project)

        assert json.loads(done.stdout)["subscriptions"][0]["name"] == "writing"


class TestTwoRepositoriesInOneHome:
    """The case the split exists for, in the layer that caught it.

    Nothing in the unit layer renders twice in two unrelated places, because a
    unit test builds the setup it is about. One fake home with two checkouts in
    it is also what a laptop is, which is why the machine-wide record's fault
    showed up here first.
    """

    def test_neither_repository_can_reach_the_others_record(self, machine: Machine, remote: str):
        first = repository(machine, "first", remote)
        second = repository(machine, "second", remote)

        machine.home.run("render", cwd=first)
        done = machine.home.run("render", cwd=second)

        assert done.returncode == Exit.OK, done.stderr
        assert (first / SKILLS / "writing" / "SKILL.md").is_file()
        assert (second / SKILLS / "writing" / "SKILL.md").is_file()
        assert (first / ".akit" / "render.json").is_file()
        assert (second / ".akit" / "render.json").is_file()

    def test_unsubscribing_in_one_withdraws_only_its_own_copy(self, machine: Machine, remote: str):
        first = repository(machine, "first", remote)
        second = repository(machine, "second", remote)
        machine.home.run("render", cwd=first)
        machine.home.run("render", cwd=second)

        (second / ".akit.yaml").write_text("version: 1\n", encoding="utf-8")
        done = machine.home.run("render", cwd=second)

        assert done.returncode == Exit.OK, done.stderr
        assert not (second / SKILLS / "writing").exists()
        assert (first / SKILLS / "writing" / "SKILL.md").is_file()


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

    def test_check_on_a_repository_that_commits_nothing_passes_and_says_why(self, machine: Machine, remote: str):
        project = repository(machine, "project", remote)

        done = machine.home.run("render", "--check", cwd=project)

        assert done.returncode == Exit.OK
        assert "names no harness whose renders it commits" in done.stdout

    def test_check_refuses_the_narrowing_flags_rather_than_passing_on_nothing(self, machine: Machine, remote: str):
        project = repository(machine, "project", remote)

        done = machine.home.run("render", "--check", "--no-harness", "opencode", cwd=project)

        assert done.returncode == Exit.USAGE
        assert "does not take --harness or --no-harness" in done.stderr

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


def a_real_repository(machine: Machine, name: str, source: str, body: str) -> Path:
    """A repository git actually knows about, which the committed checks need.

    The `repository` helper above makes a bare `.git` directory, which is enough
    for everything that only walks up looking for one. Deciding whether a
    manifest is committed, or who can read this repository, is git's answer
    rather than a directory's.
    """
    root = machine.home.root / name
    root.mkdir(parents=True)
    git("-C", str(root), "init", "-q")
    (root / ".akit.yaml").write_text(body, encoding="utf-8")
    return root


class TestTheCheckAHookRuns:
    """`akit render --check`, run the way `.pre-commit-hooks.yaml` runs it.

    Installing the hook is pre-commit's business and needs a network and an
    install of its own. What this repository owns is the entry, so the entry is
    what gets run, as a subprocess, in a throwaway repository.
    """

    def entry(self) -> list[str]:
        declared = YAML(typ="safe").load(
            (Path(__file__).parent.parent / ".pre-commit-hooks.yaml").read_text(encoding="utf-8")
        )
        return declared[0]["entry"].removeprefix("akit ").split()

    def test_it_passes_on_a_fresh_render_of_a_committing_repository(self, machine: Machine, remote: str):
        project = a_real_repository(
            machine, "project", remote, f"version: 1\nharnesses: [copilot-ci]\n\nskills:\n  {remote}: [writing]\n"
        )
        assert machine.home.run("render", cwd=project).returncode == Exit.OK

        done = machine.home.run(*self.entry(), cwd=project)

        assert done.returncode == Exit.OK, done.stderr
        assert "Up to date" in done.stdout

    def test_it_fails_after_somebody_edits_a_committed_file(self, machine: Machine, remote: str):
        project = a_real_repository(
            machine, "project", remote, f"version: 1\nharnesses: [copilot-ci]\n\nskills:\n  {remote}: [writing]\n"
        )
        machine.home.run("render", cwd=project)
        (project / SKILLS / "writing" / "SKILL.md").write_text("# edited\n", encoding="utf-8")

        done = machine.home.run(*self.entry(), cwd=project)

        assert done.returncode == Exit.ERROR
        assert "Out of date" in done.stdout
        assert "akit render" in done.stdout

    def test_it_refuses_a_committed_manifest_naming_somebodys_laptop(self, machine: Machine, remote: str):
        outside = machine.home.root / "my-kits"
        (outside / "skills" / "writing").mkdir(parents=True)
        (outside / "skills" / "writing" / "SKILL.md").write_text("# writing\n", encoding="utf-8")
        project = a_real_repository(machine, "project", remote, f"version: 1\n\nskills:\n  {outside}: [writing]\n")
        git("-C", str(project), "add", "-A")
        git("-C", str(project), *FIXED_AUTHOR, "commit", "-qm", "subscribe")

        done = machine.home.run(*self.entry(), cwd=project)

        assert done.returncode == Exit.REFUSAL
        assert str(outside) in done.stderr

    def test_a_repository_committing_nothing_is_not_called_stale(self, machine: Machine, remote: str):
        project = a_real_repository(machine, "project", remote, f"version: 1\n\nskills:\n  {remote}: [writing]\n")

        done = machine.home.run(*self.entry(), cwd=project)

        assert done.returncode == Exit.OK, done.stderr
