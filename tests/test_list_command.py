"""`akit list` as a subprocess, in a fake home, against a realistic broken setup.

The fixture is the one T4 asks for: two sources, one of them a local path, a
deliberate collision across the two scopes, a subscription nothing has rendered,
and a source the cache does not hold. Everything a person would be looking at
when they ran this command because something was already wrong.

The output is snapshot-tested with the tmp paths taken out, in both shapes.
A snapshot is the right test for a report: what it is for is being read, so the
thing worth pinning is the whole of what it says rather than six substrings that
all still pass after the layout turns to noise.
"""

from __future__ import annotations

import json
import re
import subprocess
import textwrap
from dataclasses import dataclass
from pathlib import Path

import pytest
from fake_home import FakeHome
from git_environment import local_remote

pytestmark = pytest.mark.cli


@dataclass(frozen=True)
class Places:
    """A fake machine, and the two per-platform directories it actually uses."""

    home: FakeHome
    manifest: Path
    cache: Path


#: Enough to put the source in the cache, which `add` will do from T7. Until
#: then `list` has to be given a machine that has already fetched something,
#: because a `list` that fetched would be the bug this command is defined
#: against. It also reports the two per-platform directories, because a fixture
#: that spelled `~/.config/akit` would be writing the Linux answer down as if it
#: were the only one: on Windows the manifest is under `%APPDATA%` and the cache
#: under `%LOCALAPPDATA%`, and the test would silently stop reading either.
PREFETCH = textwrap.dedent(
    """
    import json, sys
    from pathlib import Path
    from federated_agent_kits import cache, manifest, sources

    cache.resolve(sources.parse(sys.argv[1]), anchor=Path(sys.argv[2]))
    print(json.dumps({
        "manifest": str(manifest.user_manifest_path()),
        "cache": str(cache.root()),
    }))
    """
)


def fixed(text: str, replacements: dict[str, str]) -> str:
    """Every path that changes per run, replaced by what it is.

    Separators are normalised last and wholesale. What this snapshot is for is
    the report's shape and its sentences; that a path on Windows is spelled with
    backslashes is `pathlib`'s business and is asserted where it belongs, in the
    tests that compare paths rather than prose.
    """
    for actual, name in sorted(replacements.items(), key=lambda pair: -len(pair[0])):
        text = text.replace(actual, name)
        text = text.replace(str(Path(actual)), name)
    text = text.replace("\\", "/")
    text = re.sub(r"(<cache>/)[A-Za-z0-9._-]+", r"\1<slug>", text)
    text = re.sub(r"\b[0-9a-f]{7,40}\b", "<commit>", text)
    return underlined(text)


def underlined(text: str) -> str:
    """Every heading's rule, back to the length of the heading as it now reads.

    A heading carries the path to a manifest and a rule as long as the heading,
    so taking a tmp path out of one shortens the title and leaves the rule
    measuring a directory name nobody will ever see again. The rule is the
    report's, and what it is for is matching the line above it.
    """
    lines = text.splitlines()
    for index, line in enumerate(lines[1:], start=1):
        if line and set(line) <= {"=", "-"}:
            lines[index] = line[0] * len(lines[index - 1])
    return "\n".join(lines) + "\n"


@pytest.fixture
def remote(tmp_path: Path) -> str:
    return local_remote(
        tmp_path / "remote",
        {
            "skills/writing/SKILL.md": "# writing",
            "skills/fkb/SKILL.md": "# fkb",
            "rules/prose-style.md": "# prose",
        },
    )


@pytest.fixture
def nearby(tmp_path: Path) -> Path:
    path = tmp_path / "my-kits"
    (path / "skills" / "writing" / "references").mkdir(parents=True)
    (path / "skills" / "writing" / "SKILL.md").write_text("# mine", encoding="utf-8")
    return path


@pytest.fixture
def repository(fake_home: FakeHome, remote: str, nearby: Path, tmp_path: Path) -> Path:
    """A clone with a manifest naming four things, two of which cannot work."""
    root = fake_home.root / "work" / "project"
    (root / ".git").mkdir(parents=True)
    (root / ".akit.yaml").write_text(
        textwrap.dedent(f"""
            version: 1
            harnesses: [detected, emacs]

            skills:
              {remote}:
              - writing
              - name: fkb
                as: knowledge
              {tmp_path / "gone"}: [missing]

            rules:
            - {remote}: prose-style
            """).lstrip(),
        encoding="utf-8",
    )
    return root


@pytest.fixture
def machine(fake_home: FakeHome, remote: str, nearby: Path, repository: Path) -> Places:
    """opencode installed, the remote already in the cache, and a user manifest."""
    (fake_home.root / ".config" / "opencode").mkdir(parents=True)
    prefetched = fake_home.run_python("-c", PREFETCH, remote, str(repository))
    assert prefetched.returncode == 0, prefetched.stderr
    reported = json.loads(prefetched.stdout)
    user_manifest = Path(reported["manifest"])
    user_manifest.parent.mkdir(parents=True, exist_ok=True)
    user_manifest.write_text(f"version: 1\nskills:\n  {nearby}: [writing]\n", encoding="utf-8")
    return Places(home=fake_home, manifest=user_manifest, cache=Path(reported["cache"]))


def listed(machine: Places, repository: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return machine.home.run("list", *extra, cwd=repository)


@pytest.fixture
def names(machine: Places, repository: Path, remote: str, nearby: Path, tmp_path: Path) -> dict[str, str]:
    """Every path this setup's report carries that changes from run to run."""
    return {
        str(repository): "<repo>",
        str(machine.manifest): "<user-manifest>",
        str(machine.cache): "<cache>",
        str(machine.home.root): "<home>",
        str(nearby): "<my-kits>",
        remote: "<remote>",
        str(tmp_path / "gone"): "<gone>",
        str(tmp_path): "<tmp>",
    }


class TestListInAFakeHome:
    def test_it_reads_the_whole_setup_and_says_so(self, machine: Places, repository: Path, names: dict[str, str]):
        result = listed(machine, repository)

        assert result.returncode == 0, result.stderr
        shown = fixed(result.stdout, names)
        assert (
            shown
            == textwrap.dedent("""
            Project subscriptions (<repo>/.akit.yaml)
            =========================================

            From <remote>, at <commit>:
              read from <cache>/<slug>
            - skill writing
              [ ] opencode  <repo>/.agents/skills/writing (not rendered)
            - skill knowledge (fkb, from skills/fkb)
              [ ] opencode  <repo>/.agents/skills/knowledge (not rendered)
            - rule prose-style
              [ ] opencode  "prose-style" block in <repo>/AGENTS.md (not rendered)

            From <gone>, unpinned:
            - skill missing
              problem: <gone>: there is no directory at <gone>
                  A path source is read where it is. Check the path, or subscribe to the repository instead.

            Global subscriptions (<user-manifest>)
            ======================================

            From <my-kits>, unpinned:
              read from <my-kits>
            - skill writing
              [ ] opencode  <home>/.agents/skills/writing (not rendered)

            Harnesses
            =========

            [x] opencode        detected on this machine
                takes skills and rules, and is rendering for the global manifest and this repository's manifest
                reads rules in the order the manifest lists them
            [ ] copilot-vscode  not detected on this machine
                takes skills and rules, and is in no manifest's harness list
                promises no order between rules, so two that contradict are a coin toss
            [ ] emacs           named in a manifest, and no adapter answers to it
                named by this repository's manifest

            Harnesses with no machine
            -------------------------

            - copilot-ci      takes skills and rules, and needs listing by name in a repository manifest

            Name collisions
            ===============

            skills "writing" is wanted by <my-kits> (the global manifest) and <remote> (this repository's manifest)
              fix: subscribe to one of them with `--as <other-name>`
            """).lstrip()
        )

    def test_by_kind_puts_the_skills_together_and_the_rules_after_them(
        self, machine: Places, repository: Path, names: dict[str, str]
    ):
        result = listed(machine, repository, "--by-kind")

        assert result.returncode == 0, result.stderr
        shown = fixed(result.stdout, names)
        assert (
            shown.split("Harnesses")[0]
            == textwrap.dedent("""
            Project subscriptions (<repo>/.akit.yaml)
            =========================================

            Skills
            ------

            - writing, from <remote>, at <commit>
              [ ] opencode  <repo>/.agents/skills/writing (not rendered)
            - knowledge (fkb, from skills/fkb), from <remote>, at <commit>
              [ ] opencode  <repo>/.agents/skills/knowledge (not rendered)
            - missing, from <gone>, unpinned
              problem: <gone>: there is no directory at <gone>
                  A path source is read where it is. Check the path, or subscribe to the repository instead.

            Rules
            -----

            - prose-style, from <remote>, at <commit>
              [ ] opencode  "prose-style" block in <repo>/AGENTS.md (not rendered)

            Global subscriptions (<user-manifest>)
            ======================================

            Skills
            ------

            - writing, from <my-kits>, unpinned
              [ ] opencode  <home>/.agents/skills/writing (not rendered)

            """).lstrip()
        )

    def test_global_reports_one_scope_and_still_reports_the_harnesses(
        self, machine: Places, repository: Path, names: dict[str, str]
    ):
        result = listed(machine, repository, "--global")

        assert result.returncode == 0, result.stderr
        shown = fixed(result.stdout, names)
        assert (
            shown.split("Harnesses")[0]
            == textwrap.dedent("""
            Global subscriptions (<user-manifest>)
            ======================================

            From <my-kits>, unpinned:
              read from <my-kits>
            - skill writing
              [ ] opencode  <home>/.agents/skills/writing (not rendered)

            """).lstrip()
        )

    def test_nothing_was_written_and_nothing_was_fetched(self, machine: Places, repository: Path, tmp_path: Path):
        root = machine.home.root
        before = sorted(path.relative_to(root) for path in root.rglob("*"))

        assert listed(machine, repository).returncode == 0

        assert sorted(path.relative_to(root) for path in root.rglob("*")) == before

    def test_a_source_the_cache_does_not_hold_is_a_line_rather_than_an_ending(
        self, machine: Places, repository: Path, tmp_path: Path
    ):
        elsewhere = local_remote(tmp_path / "second", {"skills/other/SKILL.md": "# other"})
        repository.joinpath(".akit.yaml").write_text(f"version: 1\nskills:\n  {elsewhere}: [other]\n", encoding="utf-8")

        result = listed(machine, repository)

        assert result.returncode == 0
        assert "not in the cache" in result.stdout
        assert "akit render" in result.stdout

    def test_the_same_answer_as_data(self, machine: Places, repository: Path):
        result = listed(machine, repository, "--json")

        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert [entry["name"] for entry in payload["subscriptions"]] == [
            "writing",
            "writing",
            "fkb",
            "missing",
            "prose-style",
        ]
        assert payload["collisions"][0]["name"] == "writing"
        assert {entry["name"] for entry in payload["harnesses"]} == {
            "opencode",
            "copilot-vscode",
            "copilot-ci",
            "emacs",
        }
        assert all(
            not target["rendered"]
            for entry in payload["subscriptions"]
            for part in entry["parts"]
            for target in part["targets"]
        )

    def test_a_declined_kind_appears_and_crashes_nothing(self, machine: Places, repository: Path, nearby: Path):
        (nearby / "agents").mkdir()
        (nearby / "agents" / "reviewer.md").write_text("# reviewer", encoding="utf-8")
        repository.joinpath(".akit.yaml").write_text(f"version: 1\nagents:\n  {nearby}: [reviewer]\n", encoding="utf-8")

        result = listed(machine, repository)

        assert result.returncode == 0, result.stderr
        assert "no harness in this scope takes agents" in result.stdout
