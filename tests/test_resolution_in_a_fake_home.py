"""Resolution inside a fake home, as a subprocess, the way a user's machine meets it.

The `unit` layer covers what resolution decides. What it cannot cover is where
the answers land on a real machine, because that is decided by `platformdirs`
reading the environment of the process it is in. So this layer runs the library
in a subprocess inside a throwaway home and asserts that nothing arrived outside
it.

There is no verb to drive yet: `akit list` is the first command that resolves
anything and it lands with T4. Until then the subprocess is handed the library
directly, which tests the same property for the same reason.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest
from fake_home import FakeHome
from git_environment import local_remote

pytestmark = pytest.mark.cli

PROGRAM = textwrap.dedent(
    """
    import json, sys
    from pathlib import Path
    from federated_agent_kits import cache, discovery, sources
    from federated_agent_kits.manifest import Kind

    key = sources.parse(sys.argv[1])
    resolved = cache.resolve(key, anchor=Path(sys.argv[2]))
    found = discovery.parts(resolved.root, Kind.SKILL)
    print(json.dumps({
        "root": str(resolved.root),
        "cache": str(cache.root()),
        "commit": resolved.commit,
        "privacy": None if resolved.privacy is None else str(resolved.privacy),
        "fetched": resolved.fetched,
        "parts": sorted(part.name for part in found),
    }))
    """
)


def resolve_in(home: FakeHome, key: str, anchor: Path) -> dict:
    result = home.run_python("-c", PROGRAM, key, str(anchor))
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.fixture
def source(tmp_path: Path) -> str:
    return local_remote(
        tmp_path / "kits",
        {
            "skills/writing/SKILL.md": "# writing",
            "skills/writing/references/style.md": "# style",
            "rules/prose-style.md": "# prose",
        },
    )


class TestAMachineOfSomebodyElses:
    def test_a_source_is_cloned_into_this_machines_cache_and_nowhere_else(
        self, fake_home: FakeHome, source: str, tmp_path: Path
    ):
        answer = resolve_in(fake_home, source, tmp_path)

        assert Path(answer["cache"]).is_relative_to(fake_home.root)
        assert Path(answer["root"]).is_relative_to(fake_home.root)
        assert answer["privacy"] == "public"
        assert answer["parts"] == ["writing"]

    def test_what_the_skill_leans_on_travels_with_it(self, fake_home: FakeHome, source: str, tmp_path: Path):
        answer = resolve_in(fake_home, source, tmp_path)

        assert (Path(answer["root"]) / "skills" / "writing" / "references" / "style.md").is_file()

    def test_a_second_resolution_uses_the_clone_it_already_made(self, fake_home: FakeHome, source: str, tmp_path: Path):
        first = resolve_in(fake_home, source, tmp_path)
        second = resolve_in(fake_home, source, tmp_path)

        assert second["fetched"] is False
        assert second["commit"] == first["commit"]

    def test_a_path_source_is_read_where_it_is(self, fake_home: FakeHome, tmp_path: Path):
        kits = tmp_path / "project" / "kits" / "skills" / "mine"
        kits.mkdir(parents=True)
        (kits / "SKILL.md").write_text("# mine", encoding="utf-8")

        answer = resolve_in(fake_home, "./kits", tmp_path / "project")

        assert Path(answer["root"]) == (tmp_path / "project" / "kits").resolve()
        assert answer["commit"] is None
        assert answer["parts"] == ["mine"]

    def test_a_file_source_and_a_path_source_offer_the_same_parts(
        self, fake_home: FakeHome, source: str, tmp_path: Path
    ):
        over_the_wire = resolve_in(fake_home, source, tmp_path)
        on_this_disk = resolve_in(fake_home, str(tmp_path / "kits"), tmp_path)

        assert over_the_wire["parts"] == on_this_disk["parts"]

    def test_a_source_that_cannot_be_cloned_fails_with_something_to_do_about_it(
        self, fake_home: FakeHome, tmp_path: Path
    ):
        missing = (tmp_path / "nowhere").as_uri()

        result = fake_home.run_python("-c", PROGRAM, missing, str(tmp_path))

        assert result.returncode != 0
        assert "could not be cloned" in result.stderr
