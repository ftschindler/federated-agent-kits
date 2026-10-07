"""Key parsing: the five forms, the spellings that are one repository, and what is not a source.

No network and no filesystem. A key says what it names, and where that is on
this disk is `test_cache.py`'s question.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from federated_agent_kits import sources
from federated_agent_kits.sources import SourceKind

pytestmark = pytest.mark.unit


class TestTheFiveForms:
    def test_a_shorthand_is_a_github_repository(self):
        key = sources.parse("owner/repo")

        assert key.kind is SourceKind.REMOTE
        assert key.url == "https://github.com/owner/repo"
        assert key.identity == "github.com/owner/repo"
        assert key.subdirectory is None

    def test_a_forge_url_keeps_its_host(self):
        key = sources.parse("https://gitlab.com/org/repo")

        assert key.url == "https://gitlab.com/org/repo"
        assert key.identity == "gitlab.com/org/repo"

    def test_an_azure_url_is_read_like_any_other(self):
        key = sources.parse("https://dev.azure.com/org/project/_git/repo")

        assert key.identity == "dev.azure.com/org/project/_git/repo"

    def test_an_scp_style_git_url_is_handed_to_git_as_written(self):
        key = sources.parse("git@github.com:org/repo.git")

        assert key.url == "git@github.com:org/repo.git"
        assert key.identity == "github.com/org/repo"

    def test_an_ssh_url_is_a_url(self):
        key = sources.parse("ssh://git@git.example.com/org/repo")

        assert key.url == "ssh://git@git.example.com/org/repo"
        assert key.identity == "git.example.com/org/repo"

    def test_a_url_into_a_subdirectory_selects_one_part(self):
        key = sources.parse("https://github.com/org/repo/tree/main/skills/writing")

        assert key.url == "https://github.com/org/repo"
        assert key.ref == "main"
        assert key.subdirectory == "skills/writing"

    def test_a_gitlab_subdirectory_url_drops_the_separator(self):
        key = sources.parse("https://gitlab.com/org/repo/-/tree/trunk/rules")

        assert key.url == "https://gitlab.com/org/repo"
        assert key.identity == "gitlab.com/org/repo"
        assert key.ref == "trunk"
        assert key.subdirectory == "rules"

    def test_a_tree_url_without_a_directory_is_the_whole_repository_at_a_ref(self):
        key = sources.parse("https://github.com/org/repo/tree/v2")

        assert key.ref == "v2"
        assert key.subdirectory is None

    @pytest.mark.parametrize("written", [".", "..", "./kits", "../my-kits", "~/kits", "/opt/kits", r"C:\kits"])
    def test_a_path_is_recognised_by_how_it_is_written(self, written):
        key = sources.parse(written)

        assert key.kind is SourceKind.PATH
        assert key.url == written

    def test_a_file_url_is_a_remote_this_machine_happens_to_hold(self):
        key = sources.parse("file:///srv/kits.git")

        assert key.kind is SourceKind.REMOTE
        assert key.identity == "file:///srv/kits.git"

    def test_surrounding_whitespace_is_not_part_of_a_key(self):
        assert sources.parse("  owner/repo \n").identity == "github.com/owner/repo"


class TestOneRepositoryWrittenSeveralWays:
    @pytest.mark.parametrize(
        "written",
        [
            "owner/repo",
            "https://github.com/owner/repo",
            "https://github.com/owner/repo.git",
            "https://github.com/owner/repo/",
            "https://GitHub.com/Owner/Repo",
            "git@github.com:owner/repo.git",
            "ssh://git@github.com/owner/repo.git",
            "https://github.com/owner/repo/tree/main/skills/writing",
        ],
    )
    def test_every_spelling_shares_one_cache_entry(self, written):
        assert sources.parse(written).identity == "github.com/owner/repo"
        assert sources.parse(written).cache_slug == sources.parse("owner/repo").cache_slug

    def test_two_different_repositories_do_not(self):
        assert sources.parse("owner/repo").cache_slug != sources.parse("owner/other").cache_slug

    def test_a_slug_is_recognisable_and_legal_on_windows(self):
        slug = sources.parse("git@git.example.com:team/unreleased-thing-kits.git").cache_slug

        assert slug.startswith("git.example.com-team-unreleased-thing-kits-")
        assert not set(slug) & set('<>:"/\\|?*')


class TestWhatIsNotASource:
    @pytest.mark.parametrize(
        ("written", "expected"),
        [
            ("https://example.com/kits/SKILL.md", "names a file"),
            ("https://example.com/kits/release.tar.gz", "names a file"),
            ("https://github.com/org/repo/blob/main/skills/writing/SKILL.md", "one file inside a repository"),
            ("https://github.com/org", "names no repository"),
            ("git@github.com:repo", "names no repository"),
            ("https://github.com/org/repo/tree/", "names no branch"),
            ("not a source at all", "is not a source"),
            ("", "is empty"),
        ],
    )
    def test_it_is_refused_with_something_to_write_instead(self, written, expected):
        with pytest.raises(sources.SourceError) as refusal:
            sources.parse(written)

        assert expected in str(refusal.value)
        assert refusal.value.fix


class TestWhereAPathActuallyIs:
    def test_a_relative_path_resolves_against_the_repository_root(self, tmp_path: Path):
        anchor = tmp_path / "repo"
        anchor.mkdir()

        assert sources.local_path(sources.parse("./kits"), anchor=anchor) == (anchor / "kits").resolve()

    def test_an_absolute_path_is_already_an_answer(self, tmp_path: Path):
        written = tmp_path / "kits"

        assert sources.local_path(sources.parse(str(written)), anchor=tmp_path / "elsewhere") == written

    def test_a_home_relative_path_is_expanded(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))

        assert sources.local_path(sources.parse("~/kits"), anchor=tmp_path) == tmp_path / "kits"

    @pytest.mark.parametrize(("written", "leaves"), [(".", False), ("./kits", False), ("../kits", True)])
    def test_a_committed_key_may_not_leave_the_repository(self, tmp_path: Path, written, leaves):
        anchor = tmp_path / "repo"
        anchor.mkdir()

        assert sources.escapes(sources.parse(written), anchor=anchor) is leaves

    def test_an_absolute_path_outside_the_repository_leaves_it(self, tmp_path: Path):
        anchor = tmp_path / "repo"
        anchor.mkdir()

        assert sources.escapes(sources.parse(str(tmp_path / "kits")), anchor=anchor) is True

    def test_a_remote_cannot_leave_a_repository_it_was_never_in(self, tmp_path: Path):
        assert sources.escapes(sources.parse("owner/repo"), anchor=tmp_path) is False
