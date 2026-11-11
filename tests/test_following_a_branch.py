"""Following a branch or a pull request, and leaving it once it has landed.

A pull request URL is asked about once, at `add` or `discover`, and what the
forge said is written into the manifest. Everything after that is git, which is
what most of this module tests: two local repositories standing in for a
forge, one upstream and one fork, reached under forge-shaped URLs through
`url.<base>.insteadOf` in this machine's git config. The forge itself is a
function returning what GitHub's API would have.

`insteadOf` is read from the global config, which the anonymous first attempt
deliberately does not see, so every source here classifies as private. That is
`cache.py`'s business and changes nothing below.
"""

from __future__ import annotations

import io
import json
import subprocess
import urllib.error
from dataclasses import dataclass
from email.message import Message
from pathlib import Path
from typing import Any

import pytest
from git_environment import FIXED_AUTHOR, git, local_remote

from federated_agent_kits import cache, discovering, editing, forges, listing, render, sources, subscribing
from federated_agent_kits import manifest as manifests
from federated_agent_kits.cli import build_parser, dispatch
from federated_agent_kits.exits import UsageError
from federated_agent_kits.manifest import Kind, Scope
from federated_agent_kits.reporting import SHORT

pytestmark = pytest.mark.unit

UPSTREAM = "https://forge.test/owner/kits"
FORK = "https://forge.test/fork/kits"
BRANCH = "feat/x"
FEATURE = f"{UPSTREAM}/tree/feat%2Fx"
PULL = f"{UPSTREAM}/pull/16"

LAYOUT = {"skills/writing/SKILL.md": "# writing\n", "rules/prose-style.md": "Present tense.\n"}


def run(repository: Path, *arguments: str) -> str:
    return git("-C", str(repository), *FIXED_AUTHOR, *arguments).stdout.strip()


def change(repository: Path, relative: str, text: str, message: str = "change") -> str:
    (repository / relative).parent.mkdir(parents=True, exist_ok=True)
    (repository / relative).write_text(text, encoding="utf-8")
    run(repository, "add", "-A")
    run(repository, "commit", "-qm", message)
    return run(repository, "rev-parse", "HEAD")


@dataclass(frozen=True)
class Forge:
    """An upstream with a feature branch, a fork of it, and a project subscribing to either."""

    upstream: Path
    fork: Path
    project: Path
    places: render.Directories

    def call(self, **flags: Any) -> subscribing.Call:
        return subscribing.Call(start=self.project, places=self.places, **flags)

    @property
    def manifest(self) -> Path:
        return self.project / ".akit.yaml"

    def read(self) -> manifests.Manifest:
        return manifests.read(self.manifest, scope=Scope.PROJECT)

    def keys(self) -> list[str]:
        return [entry.key for entry in self.read().subscriptions]


@pytest.fixture
def forge(tmp_path: Path) -> Forge:
    upstream = tmp_path / "upstream"
    local_remote(upstream, LAYOUT)
    run(upstream, "checkout", "-qb", BRANCH)
    change(upstream, "skills/writing/SKILL.md", "# writing, improved\n", "improve writing")
    run(upstream, "checkout", "-q", "main")
    fork = tmp_path / "fork"
    git("clone", "-q", str(upstream), str(fork))
    run(fork, "checkout", "-qb", "fork-feature", "main")
    change(fork, "skills/writing/SKILL.md", "# writing, from a fork\n", "fork writing")
    run(fork, "checkout", "-q", "main")
    (Path.home() / ".gitconfig").write_text(
        f'[url "{upstream.as_uri()}"]\n\tinsteadOf = {UPSTREAM}\n[url "{fork.as_uri()}"]\n\tinsteadOf = {FORK}\n',
        encoding="utf-8",
    )
    project = tmp_path / "project"
    (project / ".git").mkdir(parents=True)
    (project / ".akit.yaml").write_text("version: 1\n", encoding="utf-8")
    places = render.Directories(
        home=tmp_path / "home",
        user_manifest=tmp_path / "config" / "manifest.yaml",
        cache=tmp_path / "cache",
        state=tmp_path / "state",
    )
    return Forge(upstream=upstream, fork=fork, project=project, places=places)


def answering(
    monkeypatch: pytest.MonkeyPatch,
    *,
    head: str = UPSTREAM,
    ref: str = BRANCH,
    state: str = "open",
    merged: bool = False,
) -> list[str]:
    """Make the forge answer for pull request 16, and record what it was asked."""
    asked: list[str] = []

    def answer(host: str, path: str) -> dict[str, Any]:
        asked.append(f"{host} {path}")
        return {
            "state": state,
            "merged": merged,
            "head": {"ref": ref, "repo": {"html_url": head}},
            "base": {"ref": "main", "repo": {"html_url": UPSTREAM}},
        }

    monkeypatch.setattr(forges, "ask", answer)
    return asked


def following(forge: Forge, monkeypatch: pytest.MonkeyPatch, **answer: Any) -> None:
    """Subscribe to pull request 16's `writing` skill, the way a person would."""
    answering(monkeypatch, **answer)
    subscribing.add(forge.call(), source=PULL, name="writing", kind=Kind.SKILL)


class TestReadingAKey:
    def test_a_pull_request_url_is_its_repository_and_a_number(self):
        key = sources.parse(f"{PULL}/files")

        assert key.url == UPSTREAM
        assert key.identity == "forge.test/owner/kits"
        assert key.pull == 16

    def test_a_pull_request_without_its_number_says_how_to_write_one(self):
        with pytest.raises(sources.SourceError, match="without its number"):
            sources.parse(f"{UPSTREAM}/pull/")

    def test_a_gitlab_merge_request_is_refused_with_the_url_to_use_instead(self):
        with pytest.raises(sources.SourceError, match="source branch instead"):
            sources.parse("https://gitlab.com/group/repo/-/merge_requests/3")

    def test_a_tree_path_keeps_every_reading_of_its_branch(self):
        key = sources.parse(f"{UPSTREAM}/tree/feat/x/skills")

        assert (key.ref, key.subdirectory) == ("feat", "x/skills")
        assert key.tree_branches() == ("feat/x/skills", "feat/x", "feat")

    def test_choosing_a_reading_spells_the_key_so_it_reads_that_way_again(self):
        chosen = sources.parse(f"{UPSTREAM}/tree/feat/x/skills").with_branch(BRANCH)

        assert chosen.raw == f"{FEATURE}/skills"
        again = sources.parse(chosen.raw)
        assert (again.ref, again.subdirectory, again.tree) == (BRANCH, "skills", None)

    def test_a_key_that_already_reads_one_way_can_be_restated(self):
        key = sources.parse(f"{UPSTREAM}/tree/main/skills").with_branch("main")

        assert key.tree_branches() == ()
        assert key.with_branch("main").raw == f"{UPSTREAM}/tree/main/skills"

    def test_a_branch_the_path_does_not_start_with_is_not_a_reading(self):
        with pytest.raises(ValueError, match="is not a reading"):
            sources.parse(f"{UPSTREAM}/tree/feat/x").with_branch("main")

    def test_a_key_at_a_branch_escapes_its_slashes(self):
        assert sources.at_branch(f"{UPSTREAM}/", BRANCH, "skills") == f"{FEATURE}/skills"


class TestAskingTheRemoteWhereABranchEnds:
    def test_the_longest_branch_the_remote_holds_wins(self, forge: Forge):
        settled = cache.settle(sources.parse(f"{UPSTREAM}/tree/feat/x/skills"))

        assert (settled.ref, settled.subdirectory) == (BRANCH, "skills")

    def test_a_remote_holding_none_of_them_leaves_the_first_reading(self, forge: Forge):
        key = sources.parse(f"{UPSTREAM}/tree/nope/x")

        assert cache.settle(key) is key

    def test_a_key_with_one_reading_is_not_asked_about(self):
        key = sources.parse(UPSTREAM)

        assert cache.settle(key) is key

    def test_a_full_ref_name_is_asked_about_as_written(self, forge: Forge):
        tip = run(forge.upstream, "rev-parse", BRANCH)

        fetched = cache.refresh(sources.parse(UPSTREAM), ref=f"refs/heads/{BRANCH}", cache_root=forge.places.cache)

        assert fetched.commit == tip

    def test_a_full_ref_the_remote_lacks_is_missing_rather_than_unreachable(self, forge: Forge):
        with pytest.raises(cache.MissingRefError, match="refs/pull/16/head"):
            cache.refresh(sources.parse(UPSTREAM), ref="refs/pull/16/head", cache_root=forge.places.cache)

    def test_a_pinned_key_whose_branch_is_gone_still_resolves_on_a_fresh_machine(self, forge: Forge):
        tip = run(forge.upstream, "rev-parse", BRANCH)
        run(forge.upstream, "merge", "-q", "--no-ff", BRANCH, "-m", "merge")
        run(forge.upstream, "branch", "-qD", BRANCH)

        resolved = cache.resolve(sources.parse(FEATURE), pin=tip, anchor=forge.project, cache_root=forge.places.cache)

        assert resolved.commit == tip


class TestHistory:
    def test_a_commit_in_a_clone_that_is_whole_already_is_answered_without_fetching(self, forge: Forge):
        key = sources.parse(UPSTREAM)
        first = run(forge.upstream, "rev-list", "--max-parents=0", "main")
        tip = cache.refresh(key, cache_root=forge.places.cache).commit

        assert cache.contains(key, first, tip, cache_root=forge.places.cache)
        assert cache.contains(key, first, tip, cache_root=forge.places.cache)

    def test_a_commit_nobody_has_is_not_contained(self, forge: Forge):
        key = sources.parse(UPSTREAM)
        tip = cache.refresh(key, cache_root=forge.places.cache).commit

        assert not cache.contains(key, "0" * 40, tip, cache_root=forge.places.cache)

    def test_a_public_remote_is_asked_where_a_branch_ends_without_credentials(self, forge: Forge):
        url = forge.upstream.as_uri()
        key = sources.SourceKey(
            raw=f"{UPSTREAM}/tree/feat/x/skills",
            kind=sources.SourceKind.REMOTE,
            url=url,
            identity=url,
            ref="feat",
            subdirectory="x/skills",
            tree="feat/x/skills",
        )

        assert cache.settle(key).ref == BRANCH


class TestAskingTheForge:
    def test_gh_is_asked_first_with_the_host_the_url_named(self, monkeypatch: pytest.MonkeyPatch):
        seen: list[list[str]] = []

        def gh(arguments: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
            seen.append(arguments)
            return subprocess.CompletedProcess(arguments, 0, stdout='{"state": "open"}', stderr="")

        monkeypatch.setattr(forges.shutil, "which", lambda _: "/usr/bin/gh")
        monkeypatch.setattr(forges.subprocess, "run", gh)

        assert forges.ask("github.com", "repos/o/r/pulls/1") == {"state": "open"}
        assert seen == [["gh", "api", "--hostname", "github.com", "repos/o/r/pulls/1"]]

    def test_https_answers_when_gh_cannot_and_carries_a_token(self, monkeypatch: pytest.MonkeyPatch):
        sent: list[Any] = []

        def urlopen(request: Any, timeout: float) -> io.BytesIO:
            sent.append(request)
            return io.BytesIO(b'{"state": "closed"}')

        monkeypatch.setattr(forges.shutil, "which", lambda _: "/usr/bin/gh")
        monkeypatch.setattr(
            forges.subprocess, "run", lambda arguments, **_: subprocess.CompletedProcess(arguments, 1, "", "no")
        )
        monkeypatch.setattr(forges.urllib.request, "urlopen", urlopen)
        monkeypatch.setenv("GITHUB_TOKEN", "secret")

        assert forges.ask("git.example.com", "repos/o/r/pulls/1") == {"state": "closed"}
        assert sent[0].full_url == "https://git.example.com/api/v3/repos/o/r/pulls/1"
        assert sent[0].get_header("Authorization") == "Bearer secret"

    def test_nothing_answering_is_none_rather_than_a_guess(self, monkeypatch: pytest.MonkeyPatch):
        def refused(request: Any, timeout: float) -> None:
            raise urllib.error.URLError("offline")

        monkeypatch.setattr(forges.shutil, "which", lambda _: None)
        monkeypatch.setattr(forges.urllib.request, "urlopen", refused)
        for name in forges.TOKENS:
            monkeypatch.delenv(name, raising=False)

        assert forges.ask("github.com", "repos/o/r/pulls/1") is None

    def test_a_404_from_gh_and_from_https_is_not_found_rather_than_unanswered(self, monkeypatch: pytest.MonkeyPatch):
        def not_found(request: Any, timeout: float) -> None:
            raise urllib.error.HTTPError(request.full_url, 404, "Not Found", Message(), None)

        monkeypatch.setattr(forges.shutil, "which", lambda _: "/usr/bin/gh")
        monkeypatch.setattr(
            forges.subprocess,
            "run",
            lambda arguments, **_: subprocess.CompletedProcess(arguments, 1, "", "gh: Not Found (HTTP 404)"),
        )
        monkeypatch.setattr(forges.urllib.request, "urlopen", not_found)

        assert forges.ask("github.com", "repos/o/r/pulls/1") == forges.NOT_FOUND

    def test_a_404_over_https_alone_is_still_not_found(self, monkeypatch: pytest.MonkeyPatch):
        def not_found(request: Any, timeout: float) -> None:
            raise urllib.error.HTTPError(request.full_url, 404, "Not Found", Message(), None)

        monkeypatch.setattr(forges.shutil, "which", lambda _: None)
        monkeypatch.setattr(forges.urllib.request, "urlopen", not_found)

        assert forges.ask("github.com", "repos/o/r/pulls/1") == forges.NOT_FOUND

    def test_other_http_errors_are_unanswered(self, monkeypatch: pytest.MonkeyPatch):
        def unavailable(request: Any, timeout: float) -> None:
            raise urllib.error.HTTPError(request.full_url, 503, "Unavailable", Message(), None)

        monkeypatch.setattr(forges.shutil, "which", lambda _: None)
        monkeypatch.setattr(forges.urllib.request, "urlopen", unavailable)

        assert forges.ask("github.com", "repos/o/r/pulls/1") is None

    def test_a_pull_request_becomes_its_branch_and_its_target(self, monkeypatch: pytest.MonkeyPatch):
        asked = answering(monkeypatch, head=FORK, ref="fork-feature")

        found = forges.pull_request(sources.parse(PULL))

        assert asked == ["forge.test repos/owner/kits/pulls/16"]
        assert found == forges.PullRequest(
            name="owner/kits#16",
            head=f"{FORK}/tree/fork-feature",
            target=f"{UPSTREAM}/tree/main",
            merged=False,
            open=True,
        )

    def test_a_forge_that_cannot_be_asked_names_the_git_only_way_round(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(forges, "ask", lambda host, path: None)

        with pytest.raises(forges.ForgeError, match="#refs/pull/16/head"):
            forges.pull_request(sources.parse(PULL))

    def test_a_pull_request_the_forge_cannot_find_points_at_the_account_asking(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(forges, "ask", lambda host, path: forges.NOT_FOUND)

        with pytest.raises(forges.ForgeError, match="gh auth switch") as raised:
            forges.pull_request(sources.parse(PULL))
        assert "#refs/pull/16/head" in str(raised.value)

    def test_a_branch_whose_fork_was_deleted_cannot_be_followed(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(forges, "ask", lambda host, path: {"head": {"ref": "x", "repo": None}})

        with pytest.raises(forges.ForgeError, match="has been deleted"):
            forges.pull_request(sources.parse(PULL))


class TestDiscoveringAPullRequest:
    def test_it_reads_the_branch_and_says_where_it_merges(self, forge: Forge, monkeypatch: pytest.MonkeyPatch):
        answering(monkeypatch)
        holding = discovering.look(PULL, start=forge.project, cache_root=forge.places.cache)
        out = io.StringIO()

        discovering.text(holding, out)

        assert holding.followed == FEATURE
        assert "pull request owner/kits#16, following" in out.getvalue()
        assert f"merges into {UPSTREAM}/tree/main" in out.getvalue()
        assert discovering.payload(holding)["pull_request"] == "owner/kits#16"
        assert f"akit add {PULL} writing" in out.getvalue()

    def test_a_merged_one_names_where_it_landed(self, monkeypatch: pytest.MonkeyPatch):
        answering(monkeypatch, state="closed", merged=True)

        with pytest.raises(UsageError, match=f"akit add {UPSTREAM}/tree/main <kit>"):
            discovering.named(PULL)

    def test_a_closed_one_names_its_branch(self, monkeypatch: pytest.MonkeyPatch):
        answering(monkeypatch, state="closed")

        with pytest.raises(UsageError, match=f"akit discover {FEATURE}"):
            discovering.named(PULL)


class TestAddingAPullRequest:
    def test_the_manifest_records_the_branch_the_pull_request_and_its_target(
        self, forge: Forge, monkeypatch: pytest.MonkeyPatch
    ):
        following(forge, monkeypatch)
        found = forge.read()

        assert forge.keys() == [f"{FEATURE}#{run(forge.upstream, 'rev-parse', BRANCH)}"]
        assert found.origin(FEATURE) == manifests.Origin(
            pull_request="owner/kits#16", merges_into=f"{UPSTREAM}/tree/main"
        )
        assert "version: 2" in forge.manifest.read_text(encoding="utf-8")

    def test_list_names_the_pull_request(self, forge: Forge, monkeypatch: pytest.MonkeyPatch):
        following(forge, monkeypatch)
        found = listing.survey(
            forge.project,
            home=forge.places.home,
            user_path=forge.places.user_manifest,
            cache_root=forge.places.cache,
            state_root=forge.places.state,
        )
        out = io.StringIO()

        listing.text(found, out)

        assert f"pull request owner/kits#16, merging into {UPSTREAM}/tree/main" in out.getvalue()
        assert listing.payload(found)["subscriptions"][0]["pull_request"] == "owner/kits#16"

    def test_removing_the_last_kit_forgets_the_source(self, forge: Forge, monkeypatch: pytest.MonkeyPatch):
        following(forge, monkeypatch)

        subscribing.remove(forge.call(), name="writing")

        assert forge.read().origins == {}
        assert "sources:" not in forge.manifest.read_text(encoding="utf-8")


class TestUpdatingABranchThatIsStillThere:
    def test_it_follows_the_branch_like_any_other(self, forge: Forge, monkeypatch: pytest.MonkeyPatch):
        following(forge, monkeypatch)
        run(forge.upstream, "checkout", "-q", BRANCH)
        tip = change(forge.upstream, "skills/writing/SKILL.md", "# writing, again\n")

        subscribing.update(forge.call())

        assert forge.keys() == [f"{FEATURE}#{tip}"]
        assert forge.read().origin(FEATURE).pull_request == "owner/kits#16"


class TestUpdatingABranchThatWasMerged:
    def test_a_merge_commit_moves_it_to_the_target(self, forge: Forge, monkeypatch: pytest.MonkeyPatch):
        following(forge, monkeypatch)
        run(forge.upstream, "merge", "-q", "--no-ff", BRANCH, "-m", "merge")
        run(forge.upstream, "branch", "-qD", BRANCH)
        tip = run(forge.upstream, "rev-parse", "main")

        outcome = subscribing.update(forge.call())

        assert forge.keys() == [f"{UPSTREAM}/tree/main#{tip}"]
        assert forge.read().origins == {}
        assert outcome.moved[0].onto == f"{UPSTREAM}/tree/main"
        out = io.StringIO()
        subscribing.text(outcome, out)
        assert "Now following another branch" in out.getvalue()
        assert "owner/kits#16 was merged into main" in out.getvalue()
        assert outcome.moved[0].heading.endswith(f"on {UPSTREAM}/tree/main")
        assert subscribing.payload(outcome)["moved"][0]["onto"] == f"{UPSTREAM}/tree/main"

    def test_a_squash_is_recognised_by_its_content(self, forge: Forge, monkeypatch: pytest.MonkeyPatch):
        following(forge, monkeypatch)
        run(forge.upstream, "merge", "-q", "--squash", BRANCH)
        run(forge.upstream, "commit", "-qm", "squashed")
        run(forge.upstream, "branch", "-qD", BRANCH)
        tip = run(forge.upstream, "rev-parse", "main")

        outcome = subscribing.update(forge.call())

        assert "identical at the tip of main" in outcome.notes[0].text

        assert forge.keys() == [f"{UPSTREAM}/tree/main#{tip}"]

    def test_a_squash_from_a_fork_is_recognised_across_the_two(self, forge: Forge, monkeypatch: pytest.MonkeyPatch):
        following(forge, monkeypatch, head=FORK, ref="fork-feature")
        (forge.upstream / "skills/writing/SKILL.md").write_text("# writing, from a fork\n", encoding="utf-8")
        tip = change(forge.upstream, "rules/prose-style.md", "Present tense.\n", "squashed from the fork")
        run(forge.fork, "branch", "-qD", "fork-feature")

        subscribing.update(forge.call())

        assert forge.keys() == [f"{UPSTREAM}/tree/main#{tip}"]


class TestUpdatingABranchThatCannotBeFollowed:
    def test_a_kit_that_landed_somewhere_else_in_the_tree_stops(self, forge: Forge, monkeypatch: pytest.MonkeyPatch):
        following(forge, monkeypatch)
        run(forge.upstream, "rm", "-rq", "skills")
        tip_text = run(forge.upstream, "show", f"{BRANCH}:skills/writing/SKILL.md")
        change(forge.upstream, ".agents/skills/writing/SKILL.md", f"{tip_text}\n", "squashed, moved")
        run(forge.upstream, "branch", "-qD", BRANCH)

        outcome = subscribing.update(forge.call())

        assert outcome.notes[0].data["status"] == "stopped"

    def test_changed_content_stops_with_every_way_on(self, forge: Forge, monkeypatch: pytest.MonkeyPatch):
        following(forge, monkeypatch)
        before = forge.manifest.read_text(encoding="utf-8")
        pin = forge.keys()[0].rpartition("#")[2]
        run(forge.upstream, "branch", "-qD", BRANCH)
        out = io.StringIO()

        outcome = subscribing.update(forge.call())
        subscribing.text(outcome, out)

        said = out.getvalue()
        assert forge.manifest.read_text(encoding="utf-8") == before
        assert f"used to track the branch `{BRANCH}` (pull request owner/kits#16), which is now deleted" in said
        assert f"could not confirm its kits landed in main of {UPSTREAM}" in said
        assert "akit update writing --to main" in said
        assert "akit remove writing" in said
        assert f"leave it pinned at {pin[:SHORT]}" in said
        assert outcome.notes[0].data["reason"] == "branch deleted"

    def test_a_target_branch_that_is_gone_too_stops(self, forge: Forge, monkeypatch: pytest.MonkeyPatch):
        following(forge, monkeypatch)
        run(forge.upstream, "checkout", "-qb", "trunk")
        run(forge.upstream, "branch", "-qD", "main", BRANCH)

        outcome = subscribing.update(forge.call())

        assert outcome.notes[0].data["status"] == "stopped"

    def test_a_pin_the_cache_lost_cannot_be_compared_and_stops(self, forge: Forge, monkeypatch: pytest.MonkeyPatch):
        following(forge, monkeypatch, head=FORK, ref="fork-feature")
        run(forge.fork, "branch", "-qD", "fork-feature")
        clone = cache.location(sources.parse(f"{FORK}/tree/fork-feature"), cache_root=forge.places.cache)
        cache._discard(clone)

        outcome = subscribing.update(forge.call())

        assert outcome.notes[0].data["status"] == "stopped"

    def test_a_branch_with_nothing_said_about_it_stops_saying_so(self, forge: Forge):
        tip = run(forge.upstream, "rev-parse", BRANCH)
        forge.manifest.write_text(f"version: 1\nskills:\n  {FEATURE}#{tip}: writing\n", encoding="utf-8")
        run(forge.upstream, "branch", "-qD", BRANCH)

        outcome = subscribing.update(forge.call())

        assert "nothing in the manifest says where it went" in outcome.notes[0].text
        assert "--to <branch>" in outcome.notes[0].text

    def test_a_default_branch_that_vanished_is_still_an_error(self, forge: Forge, monkeypatch: pytest.MonkeyPatch):
        forge.manifest.write_text(f"version: 1\nskills:\n  {UPSTREAM}: writing\n", encoding="utf-8")

        def gone(source: sources.SourceKey, **_: Any) -> None:
            raise cache.MissingRefError(source, "main")

        monkeypatch.setattr(cache, "refresh", gone)

        with pytest.raises(cache.MissingRefError):
            subscribing.update(forge.call())


class TestMovingOnPurpose:
    def test_to_moves_it_whether_or_not_the_branch_is_there(self, forge: Forge, monkeypatch: pytest.MonkeyPatch):
        following(forge, monkeypatch)
        tip = run(forge.upstream, "rev-parse", "main")

        subscribing.update(forge.call(), name="writing", to="main")

        assert forge.keys() == [f"{UPSTREAM}/tree/main#{tip}"]
        assert forge.read().origins == {}

    def test_a_key_from_no_pull_request_moves_within_its_own_repository(self, forge: Forge):
        tip = run(forge.upstream, "rev-parse", BRANCH)
        forge.manifest.write_text(f"version: 1\nskills:\n  {UPSTREAM}#{tip}: writing\n", encoding="utf-8")

        subscribing.update(forge.call(), name="writing", to=BRANCH)

        assert forge.keys() == [f"{FEATURE}#{tip}"]

    def test_a_branch_without_the_kit_stops_rather_than_moving(self, forge: Forge, monkeypatch: pytest.MonkeyPatch):
        following(forge, monkeypatch)
        run(forge.upstream, "checkout", "-qb", "bare", "main")
        run(forge.upstream, "rm", "-rq", "skills")
        run(forge.upstream, "commit", "-qm", "no skills")

        outcome = subscribing.update(forge.call(), name="writing", to="bare")

        assert outcome.notes[0].data["status"] == "stopped"

    def test_it_needs_a_name(self, forge: Forge):
        with pytest.raises(UsageError, match="akit update <name> --to main"):
            subscribing.update(forge.call(), to="main")

    def test_a_key_with_no_forge_layout_cannot_take_a_branch(self, forge: Forge, tmp_path: Path):
        remote = local_remote(tmp_path / "plain", LAYOUT)
        forge.manifest.write_text(f"version: 1\nskills:\n  {remote}: writing\n", encoding="utf-8")

        with pytest.raises(UsageError, match="is not a forge URL"):
            subscribing.update(forge.call(), name="writing", to="main")

    def test_the_command_line_hands_it_through(self, forge: Forge, monkeypatch: pytest.MonkeyPatch):
        seen: dict[str, Any] = {}
        monkeypatch.setattr(subscribing, "update", lambda call, **given: seen.update(given))
        monkeypatch.setattr(subscribing, "report", lambda *_, **__: 0)

        dispatch(build_parser().parse_args(["update", "writing", "--to", "main"]), io.StringIO())

        assert seen["to"] == "main"
        assert seen["name"] == "writing"


class TestTheManifestAboutASource:
    def test_a_long_key_is_written_as_a_key(self):
        long = f"{UPSTREAM}/tree/{'dependabot%2F' * 12}x#{'a' * 40}"
        found = manifests.parse("version: 1\n", scope=Scope.PROJECT)

        written = manifests.dump(editing.subscribe(found, editing.Entry(kind=Kind.SKILL, key=long, name="x")))

        assert f"  {long}: x\n" in written

    def test_a_scope_with_no_file_says_nothing(self):
        merged = manifests.merge(None, None)
        entry = manifests.Subscription(
            kind=Kind.SKILL, source="o/r", pin=None, name="x", rename=None, scope=Scope.USER, line=1
        )

        assert merged.origin(entry) == manifests.Origin()

    def test_describing_a_source_twice_replaces_what_was_said(self):
        found = manifests.parse("version: 1\nharnesses: [detected]\n", scope=Scope.PROJECT)
        found = editing.describe_source(found, "o/r", manifests.Origin(pull_request="o/r#1"))
        found = editing.describe_source(found, "o/r", manifests.Origin(merges_into="o/r/tree/main"))

        assert found.origins == {"o/r": manifests.Origin(merges_into="o/r/tree/main")}
        assert manifests.dump(found).index("sources:") < manifests.dump(found).index("harnesses:")

    def test_forgetting_one_source_keeps_the_others(self):
        found = manifests.parse("version: 1\n", scope=Scope.PROJECT)
        for source in ("a/b", "c/d"):
            found = editing.describe_source(found, source, manifests.Origin(pull_request=f"{source}#1"))

        assert list(editing.forget_source(found, "a/b").origins) == ["c/d"]

    def test_forgetting_a_source_nothing_said_anything_about_changes_nothing(self):
        found = manifests.parse("version: 1\n", scope=Scope.PROJECT)

        assert editing.forget_source(found, "o/r") is found

    def test_the_json_of_an_add_says_what_it_follows(self, forge: Forge, monkeypatch: pytest.MonkeyPatch):
        answering(monkeypatch)
        outcome = subscribing.add(forge.call(), source=PULL, name="writing", kind=Kind.SKILL)
        out = io.StringIO()

        subscribing.report(outcome, out, as_json=True)

        notes = json.loads(out.getvalue())["notes"]
        assert notes[-1]["merges_into"] == f"{UPSTREAM}/tree/main"
