"""Sequences, rather than states: what a repository looks like after several commands.

Every test in the rest of the suite builds a setup and asserts one thing about
it. This file builds a setup and then *changes it*, repeatedly, through the
entry point, because that is where the bugs have actually been.

JOURNAL.md has the tally. `update` could not follow a tag, which took an `add`
and then an `update`. A private source was never classified, which took an `add`
and then a read. A reorder reported no change, which took a render, a swap and a
render. `--check` called a fresh render stale, which took a render and then a
check. Every one was found by hand with a built wheel and none by the suite,
because the suite asserted answers to questions somebody had already asked and
each of these lives in the step between two of them.

So these are narratives. They are slower than the unit layer and they are not
trying to cover a branch: each one is a sequence somebody plausibly performs,
asserted at every step rather than only at the end.
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
INSTRUCTIONS = Path(".github") / "instructions"

#: A source shaped like a real kit: one skill, and the rule that makes a model
#: reach for it, naming the skill the way an author naturally would. The rule
#: uses the name twice, once backticked as a reference and once bare as an
#: ordinary verb, which is the sentence that makes rewriting prose impossible
#: and the note necessary (DESIGN.md section 7).
LAYOUT = {
    "skills/writing/SKILL.md": "---\nname: writing\ndescription: house prose style\n---\n\n# writing\n",
    "skills/writing/references/voice.md": "# voice\n",
    "rules/writing.md": "---\ndescription: the digest\n---\n\n**Load the `writing` skill** when writing a draft.\n",
}

WHERE = textwrap.dedent(
    """
    import json
    from pathlib import Path
    from federated_agent_kits import cache, manifest, record

    print(json.dumps({
        "manifest": str(manifest.user_manifest_path()),
        "cache": str(cache.root()),
        "record": str(record.user_location()),
    }))
    """
)


@dataclass(frozen=True)
class Machine:
    home: FakeHome
    manifest: Path


def tree(root: Path) -> dict[str, str]:
    if not root.is_dir():
        return {}
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


@pytest.fixture
def remote(tmp_path: Path) -> str:
    return local_remote(tmp_path / "remote", LAYOUT)


@pytest.fixture
def machine(fake_home: FakeHome) -> Machine:
    """A laptop with opencode and Copilot in VS Code on it, and no manifest yet."""
    (fake_home.root / ".config" / "opencode").mkdir(parents=True)
    (fake_home.root / ".vscode").mkdir(parents=True)
    done = fake_home.run_python("-c", WHERE)
    assert done.returncode == 0, done.stderr
    return Machine(home=fake_home, manifest=Path(json.loads(done.stdout)["manifest"]))


@pytest.fixture
def project(machine: Machine) -> Path:
    root = machine.home.root / "project"
    (root / ".git").mkdir(parents=True)
    (root / ".akit.yaml").write_text("version: 1\n", encoding="utf-8")
    return root


def identity(project: Path, directory: str) -> str:
    """What the copied `SKILL.md` says it is, which is what a harness goes by."""
    return (project / SKILLS / directory / "SKILL.md").read_text(encoding="utf-8")


def agents_md(project: Path) -> str:
    path = project / "AGENTS.md"
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def set_rename(project: Path, source: str, rename: str | None) -> None:
    """Rewrite the manifest the way somebody editing it by hand would.

    By hand rather than through a command, because there is no verb for changing
    an `as:`: `akit add` refuses a name already subscribed, so the manifest is
    the interface here and rule 1 of DESIGN.md section 3 says that is fine.
    """
    skill = "[writing]" if rename is None else f"\n  - name: writing\n    as: {rename}"
    rule = "writing" if rename is None else f"\n    name: writing\n    as: {rename}"
    (project / ".akit.yaml").write_text(
        f"version: 1\n\nskills:\n  {source}: {skill}\n\nrules:\n- {source}: {rule}\n", encoding="utf-8"
    )


class TestRenamingAKitBackAndForth:
    """none -> foo -> bar -> none, which is the whole of what `as:` can do."""

    def test_every_step_leaves_exactly_one_copy_under_the_right_name(
        self, machine: Machine, project: Path, remote: str
    ):
        assert machine.home.run("add", remote, "writing", "--project", cwd=project).returncode == Exit.OK
        assert sorted(path.name for path in (project / SKILLS).iterdir()) == ["writing"]

        for step in ("foo", "bar", None):
            set_rename(project, remote, step)
            done = machine.home.run("render", cwd=project)

            assert done.returncode == Exit.OK, done.stderr
            assert sorted(path.name for path in (project / SKILLS).iterdir()) == [step or "writing"]

    def test_the_identity_follows_the_directory_at_every_step(self, machine: Machine, project: Path, remote: str):
        machine.home.run("add", remote, "writing", "--project", cwd=project)

        for step in ("foo", "bar", None):
            set_rename(project, remote, step)
            machine.home.run("render", cwd=project)

            assert f"name: {step or 'writing'}" in identity(project, step or "writing")

    def test_the_marker_in_the_shared_file_follows_too(self, machine: Machine, project: Path, remote: str):
        machine.home.run("add", remote, "writing", "--project", cwd=project)

        for step in ("foo", "bar", None):
            set_rename(project, remote, step)
            machine.home.run("render", cwd=project)

            assert f"BEGIN akit {step or 'writing'}" in agents_md(project)
            assert agents_md(project).count("BEGIN akit") == (2 if step else 1)

    def test_each_step_settles_so_the_render_after_it_is_a_no_op(self, machine: Machine, project: Path, remote: str):
        machine.home.run("add", remote, "writing", "--project", cwd=project)

        for step in ("foo", "bar", None):
            set_rename(project, remote, step)
            machine.home.run("render", cwd=project)
            before = tree(project / SKILLS)

            done = machine.home.run("render", cwd=project)

            assert "Nothing changed" in done.stdout
            assert tree(project / SKILLS) == before

    def test_returning_to_the_original_name_restores_the_source_byte_for_byte(
        self, machine: Machine, project: Path, remote: str, tmp_path: Path
    ):
        machine.home.run("add", remote, "writing", "--project", cwd=project)
        first = tree(project / SKILLS)
        set_rename(project, remote, "foo")
        machine.home.run("render", cwd=project)

        set_rename(project, remote, None)
        machine.home.run("render", cwd=project)

        assert tree(project / SKILLS) == first


class TestTheNoteOverASequence:
    def test_it_arrives_with_the_rename_and_leaves_with_it(self, machine: Machine, project: Path, remote: str):
        machine.home.run("add", remote, "writing", "--project", cwd=project)
        assert "akit-renames" not in agents_md(project)

        set_rename(project, remote, "felix-writing")
        machine.home.run("render", cwd=project)
        assert "`writing` is installed as `felix-writing`" in agents_md(project)

        set_rename(project, remote, None)
        machine.home.run("render", cwd=project)
        assert "akit-renames" not in agents_md(project)

    def test_the_rule_it_explains_keeps_every_word_throughout(self, machine: Machine, project: Path, remote: str):
        machine.home.run("add", remote, "writing", "--project", cwd=project)

        for step in ("felix-writing", None):
            set_rename(project, remote, step)
            machine.home.run("render", cwd=project)

            assert "**Load the `writing` skill** when writing a draft." in agents_md(project)

    def test_prose_somebody_wrote_around_the_blocks_survives_the_whole_sequence(
        self, machine: Machine, project: Path, remote: str
    ):
        machine.home.run("add", remote, "writing", "--project", cwd=project)
        host = project / "AGENTS.md"
        host.write_text(f"# My own notes\n\nKeep this.\n\n{agents_md(project)}", encoding="utf-8")

        for step in ("felix-writing", "other", None):
            set_rename(project, remote, step)
            machine.home.run("render", cwd=project)

            assert "# My own notes" in agents_md(project)
            assert "Keep this." in agents_md(project)

    def test_a_directory_shaped_harness_gains_and_loses_the_file(self, machine: Machine, project: Path, remote: str):
        machine.home.run("add", remote, "writing", "--project", cwd=project)
        written = project / INSTRUCTIONS / "akit-renames.instructions.md"
        assert not written.exists()

        set_rename(project, remote, "felix-writing")
        machine.home.run("render", cwd=project)
        assert written.is_file()

        set_rename(project, remote, None)
        machine.home.run("render", cwd=project)
        assert not written.exists()


class TestEditingARenderedFileAndRenderingAgain:
    def test_the_edit_is_replaced_and_the_render_says_which_file(self, machine: Machine, project: Path, remote: str):
        machine.home.run("add", remote, "writing", "--project", cwd=project)
        copied = project / SKILLS / "writing" / "SKILL.md"
        copied.write_text("mine\n", encoding="utf-8")

        done = machine.home.run("render", cwd=project)

        assert done.returncode == Exit.OK, done.stderr
        assert "had been edited since it was rendered" in done.stdout
        assert str(copied) in done.stdout
        assert copied.read_text(encoding="utf-8").endswith("# writing\n")

    def test_and_the_render_after_that_is_quiet_again(self, machine: Machine, project: Path, remote: str):
        machine.home.run("add", remote, "writing", "--project", cwd=project)
        (project / SKILLS / "writing" / "SKILL.md").write_text("mine\n", encoding="utf-8")
        machine.home.run("render", cwd=project)

        done = machine.home.run("render", cwd=project)

        assert "Nothing changed" in done.stdout
        assert "had been edited" not in done.stdout

    def test_an_unsubscribed_edit_is_kept_rather_than_replaced(self, machine: Machine, project: Path, remote: str):
        """The other side of the same rule: withdrawal protects, refreshing does not."""
        machine.home.run("add", remote, "writing", "--project", cwd=project)
        copied = project / SKILLS / "writing" / "SKILL.md"
        copied.write_text("mine\n", encoding="utf-8")
        (project / ".akit.yaml").write_text("version: 1\n", encoding="utf-8")

        done = machine.home.run("render", cwd=project)

        assert copied.read_text(encoding="utf-8") == "mine\n"
        assert "has been edited since it was rendered" in done.stdout
