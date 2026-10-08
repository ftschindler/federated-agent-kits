"""Resolution: a key into a directory, with real git and no network.

This layer is `unit` and it runs git. The two are not in tension: every
repository here is built in the test's own `tmp_path` and cloned over a `file://`
URL, which is cloning, pinning, deepening and a credential-needing remote
without anybody's server. What needs a network is a repository shaped by
somebody else, and that is the `federation` layer.

The house is redirected for every test in this module, because resolution writes
into the platform cache directory and the one here must not be the developer's.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from git_environment import FIXED_AUTHOR, git, local_remote

from federated_agent_kits import cache, sources
from federated_agent_kits.cache import Privacy

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def house(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A home nothing of the developer's is reachable from, for in-process code.

    `fake_home.py` does this for a subprocess. The same redirection is needed
    here because these tests call `cache.resolve` directly, and `platformdirs`
    reads the environment of this process.
    """
    home = tmp_path / "home"
    home.mkdir()
    for variable in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(variable, str(home))
    for variable in ("XDG_CACHE_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME"):
        monkeypatch.setenv(variable, str(home / variable.lower()))
    for variable in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        monkeypatch.delenv(variable, raising=False)
    return home


@pytest.fixture
def cache_root(tmp_path: Path) -> Path:
    return tmp_path / "cache"


def a_source(tmp_path: Path, name: str = "kits", **files: str) -> str:
    layout = {"skills/writing/SKILL.md": "# writing"} if not files else {}
    for relative, text in files.items():
        layout[relative.replace("__", "/")] = text
    return local_remote(tmp_path / name, layout)


def commit(repository: Path, relative: str, text: str) -> str:
    (repository / relative).parent.mkdir(parents=True, exist_ok=True)
    (repository / relative).write_text(text, encoding="utf-8")
    git("-C", str(repository), "add", "-A")
    git("-C", str(repository), *FIXED_AUTHOR, "commit", "-qm", f"add {relative}")
    return git("-C", str(repository), "rev-parse", "HEAD").stdout.strip()


class TestWhereTheCacheIs:
    def test_it_is_the_platform_cache_directory_and_not_a_spelled_out_one(self, house: Path):
        assert cache.root().is_relative_to(house)

    def test_one_repository_written_two_ways_is_one_cache_entry(self, tmp_path: Path, cache_root: Path):
        url = a_source(tmp_path)

        first = cache.resolve(sources.parse(url), anchor=tmp_path, cache_root=cache_root)
        second = cache.resolve(sources.parse(f"{url}/"), anchor=tmp_path, cache_root=cache_root)

        assert first.root == second.root
        assert len(list(cache_root.iterdir())) == 1


class TestAPathIsAlreadyHere:
    def test_it_is_read_where_it_is_with_no_clone_and_no_commit(self, tmp_path: Path, cache_root: Path):
        (tmp_path / "repo" / "my-kits" / "skills").mkdir(parents=True)

        resolved = cache.resolve(sources.parse("./my-kits"), anchor=tmp_path / "repo", cache_root=cache_root)

        assert resolved.root == (tmp_path / "repo" / "my-kits").resolve()
        assert resolved.commit is None
        assert resolved.fetched is False
        assert not cache_root.exists()

    def test_its_privacy_is_the_repositorys_own_and_not_this_modules_answer(self, tmp_path: Path):
        (tmp_path / "kits").mkdir()

        assert cache.resolve(sources.parse("./kits"), anchor=tmp_path).privacy is None

    def test_a_path_that_is_not_there_says_where_it_looked(self, tmp_path: Path):
        with pytest.raises(cache.CacheError) as refusal:
            cache.resolve(sources.parse("./missing"), anchor=tmp_path)

        assert "there is no directory at" in str(refusal.value)


class TestCloningIsTheTest:
    def test_a_source_that_clones_anonymously_is_public(self, tmp_path: Path, cache_root: Path):
        url = a_source(tmp_path)

        resolved = cache.resolve(sources.parse(url), anchor=tmp_path, cache_root=cache_root)

        assert resolved.privacy is Privacy.PUBLIC
        assert resolved.fetched is True
        assert (resolved.root / "skills" / "writing" / "SKILL.md").is_file()

    def test_a_source_that_needs_the_users_git_configuration_is_private(
        self, tmp_path: Path, cache_root: Path, house: Path
    ):
        """A rewrite in the user's own config is what makes this source reachable.

        A `file://` repository cannot ask for a password, so what is simulated is
        the property that matters rather than the mechanism: this source resolves
        only when git is allowed to read the configuration belonging to the
        person running it, which is exactly what the anonymous attempt takes
        away.
        """
        url = a_source(tmp_path)
        private = "https://git.acme.example/team/unreleased-thing-kits"
        (house / ".gitconfig").write_text(f'[url "{url}"]\n\tinsteadOf = {private}\n', encoding="utf-8")

        resolved = cache.resolve(sources.parse(private), anchor=tmp_path, cache_root=cache_root)

        assert resolved.privacy is Privacy.PRIVATE
        assert (resolved.root / "skills" / "writing" / "SKILL.md").is_file()

    def test_a_private_source_can_still_be_asked_what_its_branch_points_at(
        self, tmp_path: Path, cache_root: Path, house: Path
    ):
        """Found by hand with the built wheel, and the reason `_over_the_network` exists.

        A private source is one that needed credentials to clone, so every
        question put to the same remote afterwards needs them too. `refresh`
        clones and then asks `ls-remote` which branch is the default, and asking
        that anonymously fails for exactly the sources the clone just proved are
        private. `akit add` then fell back to the cached commit and dropped the
        classification on the floor, leaving the leak refusal with nothing to go
        on (DESIGN.md section 8).
        """
        url = a_source(tmp_path)
        private = "https://git.acme.example/team/unreleased-thing-kits"
        (house / ".gitconfig").write_text(f'[url "{url}"]\n\tinsteadOf = {private}\n', encoding="utf-8")

        fetched = cache.refresh(sources.parse(private), cache_root=cache_root)

        assert fetched.privacy is Privacy.PRIVATE
        assert fetched.commit

    def test_a_private_source_can_be_deepened_past_its_pin(self, tmp_path: Path, cache_root: Path, house: Path):
        # The same fix, on the other call that talks to the remote: a pin older
        # than the one-commit window is fetched by name, and a private source
        # needs credentials to do it.
        url = a_source(tmp_path, "history")
        first = commit(tmp_path / "history", "skills/writing/SKILL.md", "# one\n")
        commit(tmp_path / "history", "skills/writing/SKILL.md", "# two\n")
        private = "https://git.acme.example/team/with-history"
        (house / ".gitconfig").write_text(f'[url "{url}"]\n\tinsteadOf = {private}\n', encoding="utf-8")

        resolved = cache.resolve(sources.parse(private), pin=first, anchor=tmp_path, cache_root=cache_root)

        assert resolved.commit == first

    def test_a_source_nobody_can_reach_is_an_error_rather_than_a_classification(self, tmp_path: Path, cache_root: Path):
        missing = (tmp_path / "nowhere").as_uri()

        with pytest.raises(cache.CacheError) as refusal:
            cache.resolve(sources.parse(missing), anchor=tmp_path, cache_root=cache_root)

        assert "could not be cloned" in str(refusal.value)
        assert "git said:" in str(refusal.value)
        assert not list(cache_root.iterdir())

    def test_a_cached_source_is_not_classified_again(self, tmp_path: Path, cache_root: Path):
        url = a_source(tmp_path)
        cache.resolve(sources.parse(url), anchor=tmp_path, cache_root=cache_root)

        again = cache.resolve(sources.parse(url), anchor=tmp_path, cache_root=cache_root)

        assert again.fetched is False
        assert again.privacy is None


class TestPins:
    @pytest.fixture
    def history(self, tmp_path: Path) -> tuple[str, str, str]:
        url = a_source(tmp_path)
        repository = tmp_path / "kits"
        first = git("-C", str(repository), "rev-parse", "HEAD").stdout.strip()
        second = commit(repository, "skills/caveman/SKILL.md", "# caveman")
        return url, first, second

    def test_an_unpinned_source_arrives_at_its_default_branch(self, history, tmp_path: Path, cache_root: Path):
        url, _, second = history

        resolved = cache.resolve(sources.parse(url), anchor=tmp_path, cache_root=cache_root)

        assert resolved.commit == second

    def test_a_pin_outside_the_shallow_window_is_fetched(self, history, tmp_path: Path, cache_root: Path):
        url, first, _ = history

        resolved = cache.resolve(sources.parse(url), pin=first, anchor=tmp_path, cache_root=cache_root)

        assert resolved.commit == first
        assert not (resolved.root / "skills" / "caveman").exists()

    def test_a_pin_is_fetched_by_name_where_the_forge_allows_it(self, history, tmp_path: Path, cache_root: Path):
        url, first, _ = history
        git("-C", str(tmp_path / "kits"), "config", "uploadpack.allowAnySHA1InWant", "true")

        resolved = cache.resolve(sources.parse(url), pin=first, anchor=tmp_path, cache_root=cache_root)

        assert resolved.commit == first

    def test_a_forge_that_declines_to_send_one_commit_gets_asked_for_all_of_them(
        self, history, tmp_path: Path, cache_root: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """The fall back, simulated at the one seam that can produce it.

        Fetching a commit by name is allowed by every transport this suite can
        build a fixture on, including `file://`, so the forges that decline it
        cannot be reproduced with a repository on disk. What can be reproduced
        is their answer, which is what the fall back reacts to: the by-name
        fetch fails, and the clone still ends up holding the pin.

        Both attempts at it are declined, because a request that talks to the
        remote is tried anonymously and then with credentials. A forge that
        will not send one commit will not send it either way, and declining only
        the first would be answering the second question instead.
        """
        url, first, _ = history
        real = cache.git
        declined: list[str] = []

        def decline_every_fetch_by_name(*arguments: str, **keywords):
            if arguments[0] == "fetch" and "--depth" in arguments:
                declined.append(arguments[0])
                return subprocess.CompletedProcess(args=list(arguments), returncode=1, stdout="", stderr="no")
            return real(*arguments, **keywords)

        monkeypatch.setattr(cache, "git", decline_every_fetch_by_name)

        resolved = cache.resolve(sources.parse(url), pin=first, anchor=tmp_path, cache_root=cache_root)

        assert declined == ["fetch", "fetch"]
        assert resolved.commit == first

    def test_a_pin_the_source_no_longer_holds_says_how_to_move_it(self, history, tmp_path: Path, cache_root: Path):
        url, _, _ = history
        gone = "0" * 40

        with pytest.raises(cache.CacheError) as refusal:
            cache.resolve(sources.parse(url), pin=gone, anchor=tmp_path, cache_root=cache_root)

        assert "does not hold the commit" in str(refusal.value)
        assert "akit update" in str(refusal.value)

    def test_a_cached_pin_costs_nothing(self, history, tmp_path: Path, cache_root: Path):
        url, first, _ = history
        cache.resolve(sources.parse(url), pin=first, anchor=tmp_path, cache_root=cache_root)

        again = cache.resolve(sources.parse(url), pin=first, anchor=tmp_path, cache_root=cache_root, offline=True)

        assert again.commit == first
        assert again.fetched is False


class TestOffline:
    def test_a_cached_source_resolves_with_the_network_refused(self, tmp_path: Path, cache_root: Path):
        url = a_source(tmp_path)
        cache.resolve(sources.parse(url), anchor=tmp_path, cache_root=cache_root)

        assert cache.resolve(sources.parse(url), anchor=tmp_path, cache_root=cache_root, offline=True).fetched is False

    def test_an_uncached_one_fails_saying_which_it_was(self, tmp_path: Path, cache_root: Path):
        url = a_source(tmp_path)

        with pytest.raises(cache.CacheError) as refusal:
            cache.resolve(sources.parse(url), anchor=tmp_path, cache_root=cache_root, offline=True)

        assert url in str(refusal.value)
        assert "not in the cache" in str(refusal.value)
        assert "while online" in str(refusal.value)

    def test_a_pin_the_cache_does_not_hold_says_so_rather_than_saying_nothing(self, tmp_path: Path, cache_root: Path):
        url = a_source(tmp_path)
        cache.resolve(sources.parse(url), anchor=tmp_path, cache_root=cache_root)
        later = commit(tmp_path / "kits", "skills/caveman/SKILL.md", "# caveman")

        with pytest.raises(cache.CacheError) as refusal:
            cache.resolve(sources.parse(url), pin=later, anchor=tmp_path, cache_root=cache_root, offline=True)

        assert f"does not hold the commit {later}" in str(refusal.value)


def selecting(url: str, subdirectory: str, ref: str | None = None) -> sources.SourceKey:
    """What `.../tree/<ref>/<directory>` parses to, built here rather than parsed.

    A `file://` URL has no forge layout to read - the whole path is the
    repository - so the key a subdirectory URL produces is assembled directly.
    That it is produced correctly is `test_sources.py`'s question, and this
    module's is what resolution then does with it.
    """
    return sources.SourceKey(
        raw=url, kind=sources.SourceKind.REMOTE, url=url, identity=url, ref=ref, subdirectory=subdirectory
    )


class TestAUrlIntoASubdirectory:
    def test_it_resolves_to_the_directory_it_named(self, tmp_path: Path, cache_root: Path):
        url = a_source(tmp_path)
        key = selecting(url, "skills/writing", ref="main")

        resolved = cache.resolve(key, anchor=tmp_path, cache_root=cache_root)

        assert resolved.root.name == "writing"
        assert (resolved.root / "SKILL.md").is_file()

    def test_a_directory_the_source_does_not_have_is_refused(self, tmp_path: Path, cache_root: Path):
        url = a_source(tmp_path)
        key = selecting(url, "skills/missing")

        with pytest.raises(cache.CacheError) as refusal:
            cache.resolve(key, anchor=tmp_path, cache_root=cache_root)

        assert "has no `skills/missing` in it" in str(refusal.value)

    def test_a_path_source_can_name_one_too(self, tmp_path: Path):
        (tmp_path / "kits" / "skills" / "writing").mkdir(parents=True)
        key = sources.parse("./kits")
        chosen = sources.SourceKey(
            raw=key.raw, kind=key.kind, url=key.url, identity=key.identity, subdirectory="skills/writing"
        )

        assert cache.resolve(chosen, anchor=tmp_path).root.name == "writing"


class TestTakingAFailedCloneAway:
    def test_a_clone_left_behind_does_not_stop_the_second_attempt(self, tmp_path: Path):
        half = tmp_path / "half"
        (half / "objects" / "pack").mkdir(parents=True)
        (half / "objects" / "pack" / "a.pack").write_text("x", encoding="utf-8")
        (half / "objects" / "pack" / "a.pack").chmod(0o400)

        cache._discard(half)

        assert not half.exists()

    def test_a_directory_that_is_not_there_is_not_an_error(self, tmp_path: Path):
        cache._discard(tmp_path / "never-existed")


class TestTheOuterRepositoryIsNotReachable:
    def test_no_git_variable_survives_into_a_clone(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.setenv("GIT_DIR", str(tmp_path / "somebody-elses.git"))

        url = a_source(tmp_path)
        resolved = cache.resolve(sources.parse(url), anchor=tmp_path, cache_root=tmp_path / "cache")

        assert (resolved.root / ".git").exists()

    def test_a_clone_does_not_go_through_a_shell(self, tmp_path: Path, cache_root: Path):
        url = a_source(tmp_path)

        with pytest.raises(subprocess.SubprocessError):
            cache.git("not-a-git-command-at-all", anonymous=True, cwd=tmp_path / "kits")

        assert cache.resolve(sources.parse(url), anchor=tmp_path, cache_root=cache_root).fetched is True
