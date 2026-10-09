"""The same resolution against two real repositories, over the network.

Two, because the two kinds of failure are different. `federated-knowledge-skills`
is a repository this project does not control, which is where a layout nobody
agreed on gets tested: a source that never heard of `akit` and is read anyway.
This repository is the one it does control, so the parts it holds can be
asserted by name without a test that breaks when somebody else renames a
directory.

**This repository is read at the branch under test, not at `main`.** A test that
read `main` would assert about the fixture kit as it was before this pull
request, which is the one version of it that cannot have the change being
tested in it. GitHub builds a pull request's checks from a branch that is pushed
to this same repository, so the branch is there to be cloned. Outside CI, in a
clone whose branch has never been pushed, there is nothing to read and the test
says so rather than failing.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from git_environment import outside_any_repository

from federated_agent_kits import cache, discovery, sources
from federated_agent_kits.cache import Privacy
from federated_agent_kits.manifest import Kind

pytestmark = pytest.mark.federation

REPO_ROOT = Path(__file__).resolve().parent.parent

SIBLING = "ftschindler/federated-knowledge-skills"
OURS = "ftschindler/federated-agent-kits"

#: A third kind of source, and the one the other two could not be. The sibling
#: is a layout nobody agreed on; this repository is one we control but can only
#: read at the branch under test, which is why it needs the ref dance above.
#: `agent-kits` is a real, stable, deliberately akit-shaped source that is not
#: this repository, so it is readable at a fixed commit from any branch.
KITS = "ftschindler/agent-kits"

#: Pinned, because a federation test reading a moving branch asserts about a
#: repository somebody may edit this afternoon. There are no tags on it yet, so
#: the commit is the pin; a tag replaces this the day one exists.
KITS_COMMIT = "e2c019f"

#: Where this repository keeps the kit the federation layer subscribes to. It is
#: not `skills/`, which belongs to the real skill T11 ships, so the subscription
#: is a URL into a subdirectory - which is the form that otherwise only gets
#: tested against a `file://` URL that has no forge layout to read.
FIXTURE_KIT = "tests/fixtures/kit"


@pytest.fixture(autouse=True)
def house(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    for variable in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(variable, str(home))
    for variable in ("XDG_CACHE_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME"):
        monkeypatch.setenv(variable, str(home / variable.lower()))


@pytest.fixture
def cache_root(tmp_path: Path) -> Path:
    return tmp_path / "cache"


def branch_under_test() -> str:
    """The branch CI is building, or whatever is checked out here."""
    named = os.environ.get("GITHUB_HEAD_REF")
    if named:
        return named
    head = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=str(REPO_ROOT),
        env=outside_any_repository(),
        capture_output=True,
        text=True,
        check=True,
    )
    return head.stdout.strip()


def on_the_remote(url: str, branch: str) -> bool:
    listed = subprocess.run(
        ["git", "ls-remote", "--heads", url, branch],
        env=outside_any_repository(GIT_TERMINAL_PROMPT="0"),
        capture_output=True,
        text=True,
        check=False,
    )
    return listed.returncode == 0 and bool(listed.stdout.strip())


class TestASourceThisProjectDoesNotControl:
    def test_it_clones_anonymously_and_is_therefore_public(self, tmp_path: Path, cache_root: Path):
        resolved = cache.resolve(sources.parse(SIBLING), anchor=tmp_path, cache_root=cache_root)

        assert resolved.privacy is Privacy.PUBLIC
        assert resolved.commit

    def test_a_repository_that_never_heard_of_akit_still_offers_parts(self, tmp_path: Path, cache_root: Path):
        resolved = cache.resolve(sources.parse(SIBLING), anchor=tmp_path, cache_root=cache_root)

        found = discovery.parts(resolved.root, Kind.SKILL)

        assert found, "the sibling project holds skills and the walk should find them"
        assert all((part.path / discovery.SKILL_FILE).is_file() for part in found)

    def test_the_shorthand_and_the_url_are_one_cache_entry(self, tmp_path: Path, cache_root: Path):
        first = cache.resolve(sources.parse(SIBLING), anchor=tmp_path, cache_root=cache_root)
        second = cache.resolve(
            sources.parse(f"https://github.com/{SIBLING}.git"), anchor=tmp_path, cache_root=cache_root
        )

        assert first.root == second.root
        assert second.fetched is False


class TestThisRepositoryAsASource:
    @pytest.fixture
    def key(self) -> sources.SourceKey:
        branch = branch_under_test()
        url = f"https://github.com/{OURS}"
        if not on_the_remote(url, branch):
            pytest.skip(f"{branch} is not on the remote yet; push it and this layer has something to read")
        parsed = sources.parse(f"{url}/tree/{branch}/{FIXTURE_KIT}")
        assert parsed.ref == branch
        return parsed

    def test_the_fixture_kit_is_found_by_name(self, key: sources.SourceKey, tmp_path: Path, cache_root: Path):
        resolved = cache.resolve(key, anchor=tmp_path, cache_root=cache_root)

        found = discovery.named(resolved.root, Kind.SKILL, "akit-fixture")

        assert [part.name for part in found] == ["akit-fixture"]

    def test_what_the_skill_leans_on_came_with_it(self, key: sources.SourceKey, tmp_path: Path, cache_root: Path):
        resolved = cache.resolve(key, anchor=tmp_path, cache_root=cache_root)

        (part,) = discovery.named(resolved.root, Kind.SKILL, "akit-fixture")

        assert (part.path / "references" / "notes.md").is_file()

    def test_a_rule_is_found_in_the_same_source(self, key: sources.SourceKey, tmp_path: Path, cache_root: Path):
        resolved = cache.resolve(key, anchor=tmp_path, cache_root=cache_root)

        assert [part.name for part in discovery.parts(resolved.root, Kind.RULE)] == ["fixture-rule"]

    def test_a_public_repository_classifies_as_public(self, key: sources.SourceKey, tmp_path: Path, cache_root: Path):
        assert cache.resolve(key, anchor=tmp_path, cache_root=cache_root).privacy is Privacy.PUBLIC


class TestARealKitShapedSource:
    """`agent-kits`, which is what a source looks like when somebody meant it to be one.

    Everything else in this layer reads a repository that either never heard of
    `akit` or exists to be a fixture. This one is neither: it is a published kit
    somebody uses, pinned to a commit so that editing it does not turn this
    suite red on an unrelated afternoon.
    """

    @pytest.fixture
    def resolved(self, tmp_path: Path, cache_root: Path) -> Path:
        key = sources.parse(KITS)
        return cache.resolve(key, pin=KITS_COMMIT, anchor=tmp_path, cache_root=cache_root).root

    def test_one_name_gives_a_skill_and_a_rule(self, resolved: Path):
        """What `akit add writing` takes, and why T7 settled that a name is a kit."""
        assert [part.name for part in discovery.named(resolved, Kind.SKILL, "writing")] == ["writing"]
        assert [part.name for part in discovery.named(resolved, Kind.RULE, "writing")] == ["writing"]

    def test_the_skill_declares_the_name_its_directory_has(self, resolved: Path):
        """The identity a rename has to rewrite, in a source that was authored properly."""
        (part,) = discovery.named(resolved, Kind.SKILL, "writing")

        assert "name: writing" in (part.path / "SKILL.md").read_text(encoding="utf-8")

    def test_the_rule_names_the_skill_beside_it(self, resolved: Path):
        """The real-world sentence the rename note exists for (DESIGN.md section 7).

        Asserted against a published repository rather than a fixture, because
        the claim is about what authors actually write, and a fixture that says
        what the renderer wants to hear proves nothing about that.
        """
        (part,) = discovery.named(resolved, Kind.RULE, "writing")

        assert "`writing` skill" in part.path.read_text(encoding="utf-8")

    def test_it_holds_more_than_one_rule_so_order_means_something(self, resolved: Path):
        assert len(discovery.parts(resolved, Kind.RULE)) > 1

    def test_it_classifies_as_public(self, tmp_path: Path, cache_root: Path):
        found = cache.resolve(sources.parse(KITS), pin=KITS_COMMIT, anchor=tmp_path, cache_root=cache_root)

        assert found.privacy is Privacy.PUBLIC
