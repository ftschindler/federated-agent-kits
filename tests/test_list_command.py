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
    return re.sub(r"\b[0-9a-f]{40}\b", "<commit>", text)


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


class TestListInAFakeHome:
    def test_it_reads_the_whole_setup_and_says_so(
        self, machine: Places, repository: Path, remote: str, nearby: Path, tmp_path: Path
    ):
        result = listed(machine, repository)

        assert result.returncode == 0, result.stderr
        shown = fixed(
            result.stdout,
            {
                str(repository): "<repo>",
                str(machine.manifest): "<user-manifest>",
                str(machine.cache): "<cache>",
                str(machine.home.root): "<home>",
                str(nearby): "<my-kits>",
                remote: "<remote>",
                str(tmp_path / "gone"): "<gone>",
                str(tmp_path): "<tmp>",
            },
        )
        assert (
            shown
            == textwrap.dedent("""
            Your subscriptions (<user-manifest>)
              skills writing, from <my-kits>, unpinned
                read from <my-kits>
                writing, at skills/writing in the source
                  opencode: <home>/.agents/skills/writing (not rendered)

            This repository's subscriptions (<repo>/.akit.yaml)
              skills writing, from <remote>, at <commit>
                read from <cache>/<slug>
                writing, at skills/writing in the source
                  opencode: <repo>/.agents/skills/writing (not rendered)
              skills fkb as "knowledge", from <remote>, at <commit>
                read from <cache>/<slug>
                knowledge (found as fkb), at skills/fkb in the source
                  opencode: <repo>/.agents/skills/knowledge (not rendered)
              skills missing, from <gone>, unpinned
                problem: <gone>: there is no directory at <gone>
                    A path source is read where it is. Check the path, or subscribe to the repository instead.
              rules prose-style, from <remote>, at <commit>
                read from <cache>/<slug>
                prose-style, at rules/prose-style.md in the source
                  opencode: <repo>/AGENTS.md, as the "prose-style" block (not rendered)

            Harnesses
              opencode: detected on this machine
                takes skills and rules, and is rendering for your manifest and this repository
                reads rules in the order your manifest lists them
              copilot-vscode: not detected on this machine
                takes skills and rules, and is in no manifest's harness list
                promises no order between rules, so two that contradict are a coin toss
              emacs: named in a manifest, and no adapter answers to it
                named by this repository

            Name collisions
              skills "writing" is wanted by <my-kits> (your manifest) and <remote> (this repository)
                fix: subscribe to one of them with `--as <other-name>`
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
        assert "akit add" in result.stdout

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
        assert {entry["name"] for entry in payload["harnesses"]} == {"opencode", "copilot-vscode", "emacs"}
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
