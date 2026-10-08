"""Who can read the repository being written into, which is half of the leak refusal.

The other half, how private a *source* is, lives in `test_cache.py` and is
learned by cloning. This is the same test pointed the other way, and the two
have to agree: a kit that needed credentials to arrive may not be committed
somewhere that needs none to read.

**Every remote here is a `file://` repository.** A local repository served that
way resolves anonymously and is therefore public, which is the whole public
branch. The private branch is simulated the way `test_cache.py` simulates it, by
a rewrite in the user's own git config: the source is reachable only when git is
allowed to read the configuration belonging to the person running it, which is
exactly what the anonymous probe takes away. That is the property DESIGN.md
section 8 classifies on, rather than the password prompt that produces it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
from git_environment import FIXED_AUTHOR, git, local_remote

from federated_agent_kits import targets
from federated_agent_kits.exits import Exit
from federated_agent_kits.targets import Publicity

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def house(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A home nothing of the developer's is reachable from, for in-process code."""
    home = tmp_path / "home"
    home.mkdir()
    for variable in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(variable, str(home))
    for variable in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        monkeypatch.delenv(variable, raising=False)
    return home


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    git("-C", str(root), "init", "-q")
    return root


def remote(root: Path, url: str, name: str = "origin") -> None:
    git("-C", str(root), "remote", "add", name, url)


def a_readable_repository(tmp_path: Path, name: str = "upstream") -> str:
    return local_remote(tmp_path / name, {"README.md": "# upstream\n"})


class TestARepositoryNothingCanLeaveIsPrivate:
    def test_no_remote_at_all_is_private_without_asking_anybody(self, repository: Path):
        found = targets.classify(repository)

        assert found.publicity is Publicity.PRIVATE
        assert found.remotes == ()
        assert found.is_public is False


class TestARemoteThatAnswersAnonymouslyIsPublic:
    def test_a_repository_anybody_can_read_is_public(self, tmp_path: Path, repository: Path):
        remote(repository, a_readable_repository(tmp_path))

        found = targets.classify(repository)

        assert found.publicity is Publicity.PUBLIC
        assert found.is_public is True

    def test_one_readable_remote_among_several_is_enough(self, tmp_path: Path, repository: Path):
        # git cannot ignore who can read a repository halfway either: a kit
        # committed here reaches whoever can read any one of its remotes.
        remote(repository, (tmp_path / "nowhere").as_uri(), name="broken")
        remote(repository, a_readable_repository(tmp_path), name="origin")

        assert targets.classify(repository).publicity is Publicity.PUBLIC


class TestARemoteThatNeedsCredentialsIsPrivate:
    def test_the_employers_repository_is_private_rather_than_refused(
        self, tmp_path: Path, repository: Path, house: Path
    ):
        """The case the whole section exists for, and the one an earlier DESIGN.md refused.

        A private kit rendered into the employer's other private repository has
        to work. Under the reading this replaces, a remote that answers only
        with credentials was neither public nor private and so was declined,
        which failed exactly the setup the refusal was built to support.
        """
        url = a_readable_repository(tmp_path)
        private = "https://git.acme.example/team/unreleased-thing"
        (house / ".gitconfig").write_text(f'[url "{url}"]\n\tinsteadOf = {private}\n', encoding="utf-8")
        remote(repository, private)

        found = targets.classify(repository)

        assert found.publicity is Publicity.PRIVATE
        assert found.is_public is False


class TestARemoteNobodyCanReachIsRefused:
    def test_it_is_a_failure_to_classify_rather_than_a_classification(self, tmp_path: Path, repository: Path):
        missing = (tmp_path / "nowhere").as_uri()
        remote(repository, missing)

        with pytest.raises(targets.UnreachableTargetError) as refused:
            targets.classify(repository)

        assert missing in str(refused.value)
        assert "cannot tell whether" in str(refused.value)

    def test_it_is_a_refusal_and_not_an_ordinary_failure(self, tmp_path: Path, repository: Path):
        remote(repository, (tmp_path / "nowhere").as_uri())

        with pytest.raises(targets.UnreachableTargetError) as refused:
            targets.classify(repository)

        assert refused.value.exit_code is Exit.REFUSAL

    def test_it_says_to_try_again_rather_than_offering_an_override(self, tmp_path: Path, repository: Path):
        remote(repository, (tmp_path / "nowhere").as_uri())

        with pytest.raises(targets.UnreachableTargetError) as refused:
            targets.classify(repository)

        assert "run the same command again" in str(refused.value)
        assert "--force" not in str(refused.value)


class TestWhetherGitActuallyHasTheFile:
    def test_a_file_nobody_committed_is_not_tracked(self, repository: Path):
        manifest = repository / ".akit.yaml"
        manifest.write_text("version: 1\n", encoding="utf-8")

        assert targets.tracked(manifest, root=repository) is False

    def test_a_committed_file_is(self, repository: Path):
        manifest = repository / ".akit.yaml"
        manifest.write_text("version: 1\n", encoding="utf-8")
        git("-C", str(repository), "add", "-A")
        git("-C", str(repository), *FIXED_AUTHOR, "commit", "-qm", "subscribe")

        assert targets.tracked(manifest, root=repository) is True

    def test_a_directory_that_is_not_a_repository_tracks_nothing(self, tmp_path: Path):
        loose = tmp_path / "loose"
        loose.mkdir()
        (loose / ".akit.yaml").write_text("version: 1\n", encoding="utf-8")

        assert targets.tracked(loose / ".akit.yaml", root=loose) is False


class TestARemoteThatHangs:
    def test_a_remote_that_never_answers_counts_as_unreachable(self, repository: Path, monkeypatch: pytest.MonkeyPatch):
        """A hook blocked on a hanging remote is worse than a hook that fails.

        Which is the one place in this package that passes git a timeout: a
        clone is as slow as the repository is big, and a probe is not.
        """
        remote(repository, "https://git.acme.example/team/never-answers")

        def hang(*arguments: str, **keywords: Any) -> subprocess.CompletedProcess[str]:
            if arguments and arguments[0] == "ls-remote":
                raise subprocess.TimeoutExpired(cmd="git", timeout=targets.TIMEOUT)
            return real(*arguments, **keywords)

        real = targets.cache.git
        monkeypatch.setattr(targets.cache, "git", hang)

        with pytest.raises(targets.UnreachableTargetError):
            targets.classify(repository)


class TestListingTheRemotes:
    def test_a_repository_with_no_remotes_lists_none(self, repository: Path):
        assert targets.remotes(repository) == ()

    def test_one_url_under_two_keys_is_one_remote(self, tmp_path: Path, repository: Path):
        url = a_readable_repository(tmp_path)
        remote(repository, url)
        git("-C", str(repository), "config", "remote.origin.pushurl", url)

        assert targets.remotes(repository) == (url,)


class TestItIsNeverRememberedBetweenRuns:
    def test_a_repository_that_gains_a_remote_is_classified_again(self, tmp_path: Path, repository: Path):
        # A repository made public last week with a cached "private" beside it
        # is a refusal that silently stops happening, which is the failure
        # DESIGN.md section 8 calls "nothing told you".
        assert targets.classify(repository).publicity is Publicity.PRIVATE

        remote(repository, a_readable_repository(tmp_path))

        assert targets.classify(repository).publicity is Publicity.PUBLIC
