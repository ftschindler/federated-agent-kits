"""The four commands that write a manifest, and the fetching only they are allowed.

A local repository served over `file://` throughout, which is how this project
tests cloning, pinning and following a branch without anybody's server. The
`cli` layer then runs the same four verbs as a subprocess; what it adds is the
exit codes and the entry point rather than more behaviour.
"""

from __future__ import annotations

import io
import json
import textwrap
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import pytest
from git_environment import FIXED_AUTHOR, git, local_remote

from federated_agent_kits import cache, render, subscribing
from federated_agent_kits import manifest as manifests
from federated_agent_kits.cache import CacheError, RefKind, UnreachableError
from federated_agent_kits.cli import build_parser, dispatch
from federated_agent_kits.exits import Exit, UsageError
from federated_agent_kits.manifest import Kind, Scope
from federated_agent_kits.sources import parse as parse_source
from federated_agent_kits.subscribing import AmbiguityError

pytestmark = pytest.mark.unit

SKILLS = Path(".agents") / "skills"

LAYOUT = {
    "skills/writing/SKILL.md": "# writing\n",
    "rules/prose-style.md": "Write in the present tense.\n",
    "rules/writing.md": "Reach for the writing skill.\n",
}


@dataclass(frozen=True)
class World:
    """One machine, one repository, and one source it can reach."""

    places: render.Directories
    project: Path
    remote: str
    remote_root: Path

    def call(self, **flags: object) -> subscribing.Call:
        return subscribing.Call(start=self.project, places=self.places, **flags)  # ty: ignore[invalid-argument-type]

    @property
    def manifest(self) -> Path:
        return self.project / ".akit.yaml"

    @property
    def written(self) -> str:
        return self.manifest.read_text(encoding="utf-8")

    def commit(self, changes: Mapping[str, str | None], message: str = "second") -> str:
        """Another commit upstream, which is what `update` is for."""
        for relative, text in changes.items():
            target = self.remote_root / relative
            if text is None:
                target.unlink()
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        git("-C", str(self.remote_root), "add", "-A")
        git("-C", str(self.remote_root), *FIXED_AUTHOR, "commit", "-qm", message)
        return git("-C", str(self.remote_root), "rev-parse", "HEAD").stdout.strip()


@pytest.fixture
def world(tmp_path: Path) -> World:
    home = tmp_path / "home"
    (home / ".config" / "opencode").mkdir(parents=True)
    project = tmp_path / "project"
    (project / ".git").mkdir(parents=True)
    (project / ".akit.yaml").write_text("version: 1\n", encoding="utf-8")
    remote_root = tmp_path / "remote"
    return World(
        places=render.Directories(
            home=home,
            user_manifest=tmp_path / "config" / "manifest.yaml",
            cache=tmp_path / "cache",
            state=tmp_path / "state",
        ),
        project=project,
        remote=local_remote(remote_root, LAYOUT),
        remote_root=remote_root,
    )


def subscriptions(path: Path, scope: Scope = Scope.PROJECT) -> dict[str, str | None]:
    found = manifests.read(path, scope=scope)
    return {f"{entry.kind.value}/{entry.rendered_name}": entry.pin for entry in found.subscriptions}


class TestAdd:
    def test_it_writes_a_pin_and_a_comment_and_renders(self, world: World):
        outcome = subscribing.add(world.call(), source=world.remote, name="writing", kind=Kind.SKILL)

        assert outcome.exit_code == Exit.OK
        assert list(subscriptions(world.manifest)) == ["skills/writing"]
        assert "# frozen: main, " in world.written
        assert (world.project / SKILLS / "writing" / "SKILL.md").read_text(encoding="utf-8") == "# writing\n"

    def test_the_manifest_round_trips_after_it(self, world: World):
        subscribing.add(world.call(), source=world.remote, name="writing", kind=Kind.SKILL)
        before = world.written

        assert manifests.dump(manifests.read(world.manifest, scope=Scope.PROJECT)) == before

    def test_a_name_in_two_kinds_is_one_kit_and_both_arrive(self, world: World):
        subscribing.add(world.call(), source=world.remote, name="writing")

        assert list(subscriptions(world.manifest)) == ["skills/writing", "rules/writing"]

    def test_kind_narrows_it_to_one(self, world: World):
        subscribing.add(world.call(), source=world.remote, name="writing", kind=Kind.RULE)

        assert list(subscriptions(world.manifest)) == ["rules/writing"]

    def test_a_typo_fails_before_the_manifest_is_touched(self, world: World):
        before = world.written

        with pytest.raises(UsageError, match="It holds skills: writing"):
            subscribing.add(world.call(), source=world.remote, name="wrting")

        assert world.written == before

    def test_a_typo_under_kind_says_which_kind_it_looked_for(self, world: World):
        with pytest.raises(UsageError, match="as a agent"):
            subscribing.add(world.call(), source=world.remote, name="writing", kind=Kind.AGENT)

    def test_a_source_holding_nothing_says_that_instead(self, tmp_path: Path, world: World):
        empty = local_remote(tmp_path / "empty", {".gitignore": "nothing here\n"})

        with pytest.raises(UsageError, match="no skills, rules or agents at all"):
            subscribing.add(world.call(), source=empty, name="writing")

    def test_running_it_twice_changes_nothing(self, world: World):
        subscribing.add(world.call(), source=world.remote, name="writing", kind=Kind.SKILL)
        before = world.written

        outcome = subscribing.add(world.call(), source=world.remote, name="writing", kind=Kind.SKILL)

        assert world.written == before
        assert not outcome.changed
        assert "Already subscribed" in outcome.notes[0].text

    def test_a_name_taken_by_another_source_is_refused(self, tmp_path: Path, world: World):
        other = local_remote(tmp_path / "other", {"skills/writing/SKILL.md": "# theirs\n"})
        subscribing.add(world.call(), source=world.remote, name="writing", kind=Kind.SKILL)

        with pytest.raises(AmbiguityError, match="--as"):
            subscribing.add(world.call(), source=other, name="writing", kind=Kind.SKILL)

    def test_as_renames_it_and_both_names_are_kept(self, tmp_path: Path, world: World):
        other = local_remote(tmp_path / "other", {"skills/writing/SKILL.md": "# theirs\n"})
        subscribing.add(world.call(), source=world.remote, name="writing", kind=Kind.SKILL)

        subscribing.add(world.call(), source=other, name="writing", rename="their-writing", kind=Kind.SKILL)

        assert "skills/their-writing" in subscriptions(world.manifest)
        assert (world.project / SKILLS / "their-writing" / "SKILL.md").exists()

    def test_a_tag_is_frozen_without_a_date_because_it_does_not_move(self, world: World):
        git("-C", str(world.remote_root), "tag", "v2")

        subscribing.add(world.call(), source=f"{world.remote}#v2", name="writing", kind=Kind.SKILL)

        assert "# frozen: v2\n" in world.written

    def test_an_annotated_tag_pins_to_the_commit_rather_than_to_the_tag(self, world: World):
        git("-C", str(world.remote_root), *FIXED_AUTHOR, "tag", "-a", "v3", "-m", "three")
        head = git("-C", str(world.remote_root), "rev-parse", "HEAD").stdout.strip()

        subscribing.add(world.call(), source=f"{world.remote}#v3", name="writing", kind=Kind.SKILL)

        assert subscriptions(world.manifest)["skills/writing"] == head

    def test_a_commit_somebody_typed_is_used_as_it_stands(self, world: World):
        head = git("-C", str(world.remote_root), "rev-parse", "HEAD").stdout.strip()
        world.commit({"skills/writing/SKILL.md": "# writing, revised\n"})

        subscribing.add(world.call(), source=f"{world.remote}#{head}", name="writing", kind=Kind.SKILL)

        assert subscriptions(world.manifest)["skills/writing"] == head
        assert (world.project / SKILLS / "writing" / "SKILL.md").read_text(encoding="utf-8") == "# writing\n"

    def test_a_branch_nobody_has_says_so(self, world: World):
        with pytest.raises(CacheError, match="no branch or tag called `nope`"):
            subscribing.add(world.call(), source=f"{world.remote}#nope", name="writing")

    def test_a_path_source_is_read_where_it_is_and_has_no_pin(self, world: World):
        outcome = subscribing.add(world.call(), source=str(world.remote_root), name="writing", kind=Kind.SKILL)

        assert subscriptions(world.manifest)["skills/writing"] is None
        assert "the path it is read from" not in outcome.notes[0].text

    def test_a_path_source_cannot_be_pinned(self, world: World):
        with pytest.raises(UsageError, match="has no commit to pin"):
            subscribing.add(world.call(), source=f"{world.remote_root}#v2", name="writing")

    def test_a_path_source_added_twice_says_what_it_is_read_from(self, world: World):
        subscribing.add(world.call(), source=str(world.remote_root), name="writing", kind=Kind.SKILL)

        outcome = subscribing.add(world.call(), source=str(world.remote_root), name="writing", kind=Kind.SKILL)

        assert "the path it is read from" in outcome.notes[0].text

    def test_global_writes_your_own_manifest_and_creates_it(self, world: World):
        outcome = subscribing.add(world.call(only_global=True), source=world.remote, name="writing", kind=Kind.SKILL)

        assert outcome.created
        assert world.places.user_manifest is not None
        assert list(subscriptions(world.places.user_manifest, Scope.USER)) == ["skills/writing"]
        assert (world.places.home / SKILLS / "writing" / "SKILL.md").exists()


class TestAddWhenTheRemoteCannotBeReached:
    def test_a_cached_source_is_pinned_to_what_this_machine_has(self, world: World, monkeypatch: pytest.MonkeyPatch):
        subscribing.add(world.call(), source=world.remote, name="writing", kind=Kind.SKILL)
        pinned = subscriptions(world.manifest)["skills/writing"]
        monkeypatch.setattr(cache, "_ls_remote", _unreachable)

        outcome = subscribing.add(world.call(), source=world.remote, name="prose-style", kind=Kind.RULE)

        assert "frozen: the commit this machine already had" in world.written
        assert subscriptions(world.manifest)["rules/prose-style"] == pinned
        assert outcome.exit_code == Exit.OK

    def test_a_source_this_machine_has_never_had_fails_saying_which(self, tmp_path: Path, world: World):
        with pytest.raises(CacheError, match="could not be cloned"):
            subscribing.add(world.call(), source=(tmp_path / "nowhere").as_uri(), name="writing")

    def test_a_branch_that_is_not_there_is_not_a_reason_to_use_the_cached_commit(self, world: World):
        subscribing.add(world.call(), source=world.remote, name="writing", kind=Kind.SKILL)

        with pytest.raises(CacheError, match="no branch or tag called `nope`"):
            subscribing.add(world.call(), source=f"{world.remote}#nope", name="prose-style")


def _unreachable(source: object, destination: object, ref: object) -> tuple[str, RefKind, str]:
    raise UnreachableError(source, "unreachable", "Try again somewhere with wifi.")  # ty: ignore[invalid-argument-type]


class TestRemove:
    def test_it_drops_the_subscription_and_withdraws_the_file(self, world: World):
        subscribing.add(world.call(), source=world.remote, name="writing", kind=Kind.SKILL)

        outcome = subscribing.remove(world.call(), name="writing")

        assert subscriptions(world.manifest) == {}
        assert not (world.project / SKILLS / "writing").exists()
        assert outcome.exit_code == Exit.OK

    def test_both_halves_of_one_kit_go_together(self, world: World):
        subscribing.add(world.call(), source=world.remote, name="writing")

        subscribing.remove(world.call(), name="writing")

        assert subscriptions(world.manifest) == {}

    def test_kind_drops_one_half_and_leaves_the_other(self, world: World):
        subscribing.add(world.call(), source=world.remote, name="writing")

        subscribing.remove(world.call(), name="writing", kind=Kind.RULE)

        assert list(subscriptions(world.manifest)) == ["skills/writing"]

    def test_a_name_in_both_manifests_is_refused(self, world: World):
        subscribing.add(world.call(), source=world.remote, name="writing", kind=Kind.SKILL)
        subscribing.add(world.call(only_global=True), source=world.remote, name="writing", kind=Kind.SKILL)

        with pytest.raises(AmbiguityError, match="--global for yours"):
            subscribing.remove(world.call(), name="writing")

    def test_naming_the_file_settles_it(self, world: World):
        subscribing.add(world.call(), source=world.remote, name="writing", kind=Kind.SKILL)
        subscribing.add(world.call(only_global=True), source=world.remote, name="writing", kind=Kind.SKILL)

        subscribing.remove(world.call(only_project=True), name="writing")

        assert subscriptions(world.manifest) == {}
        assert world.places.user_manifest is not None
        assert list(subscriptions(world.places.user_manifest, Scope.USER)) == ["skills/writing"]

    def test_a_name_nobody_subscribed_to_says_to_look(self, world: World):
        with pytest.raises(UsageError, match="akit list"):
            subscribing.remove(world.call(), name="writing")

    def test_and_names_the_file_when_one_was_named(self, world: World):
        with pytest.raises(UsageError, match=r"in .*\.akit\.yaml"):
            subscribing.remove(world.call(only_project=True), name="writing")

    def test_a_hand_written_skill_in_the_way_is_left_alone(self, world: World):
        subscribing.add(world.call(), source=world.remote, name="writing", kind=Kind.SKILL)
        mine = world.project / SKILLS / "mine" / "SKILL.md"
        mine.parent.mkdir(parents=True)
        mine.write_text("# mine\n", encoding="utf-8")

        subscribing.remove(world.call(), name="writing")

        assert mine.read_text(encoding="utf-8") == "# mine\n"


class TestHarness:
    def test_naming_one_renders_for_it_installed_or_not(self, world: World):
        subscribing.add(world.call(), source=world.remote, name="prose-style", kind=Kind.RULE)

        outcome = subscribing.harness(world.call(), action="add", name="copilot-vscode")

        assert manifests.read(world.manifest, scope=Scope.PROJECT).harnesses == ("detected", "copilot-vscode")
        assert (world.project / ".github" / "instructions" / "prose-style.instructions.md").exists()
        assert outcome.changed

    def test_naming_it_twice_changes_nothing(self, world: World):
        subscribing.harness(world.call(), action="add", name="copilot-vscode")
        before = world.written

        outcome = subscribing.harness(world.call(), action="add", name="copilot-vscode")

        assert world.written == before
        assert not outcome.changed

    def test_removing_one_withdraws_what_it_rendered(self, world: World):
        subscribing.add(world.call(), source=world.remote, name="prose-style", kind=Kind.RULE)
        subscribing.harness(world.call(), action="add", name="copilot-vscode")

        subscribing.harness(world.call(), action="remove", name="copilot-vscode")

        assert not (world.project / ".github" / "instructions" / "prose-style.instructions.md").exists()
        assert (world.project / "AGENTS.md").exists(), "opencode is still in the list"

    def test_removing_one_that_is_not_named_changes_nothing(self, world: World):
        outcome = subscribing.harness(world.call(), action="remove", name="copilot-vscode")

        assert not outcome.changed
        assert "Not named" in outcome.notes[0].text

    def test_removing_detected_is_how_a_repository_pins_the_list(self, world: World):
        subscribing.add(world.call(), source=world.remote, name="writing", kind=Kind.SKILL)

        subscribing.harness(world.call(), action="remove", name="detected")

        assert manifests.read(world.manifest, scope=Scope.PROJECT).harnesses == ()
        assert not (world.project / SKILLS / "writing").exists()

    def test_a_harness_no_adapter_knows_is_a_usage_error(self, world: World):
        with pytest.raises(UsageError, match="Known harnesses"):
            subscribing.harness(world.call(), action="add", name="emacs")

    def test_but_a_misspelt_one_already_in_the_list_can_be_taken_out_again(self, world: World):
        """The fix `akit doctor` names for a typo, which has to actually run.

        Found by hand against the built wheel: `doctor` reports a harness no
        adapter answers to and says to remove it, and the remove was refused by
        the same check that stops you adding one.
        """
        world.manifest.write_text("version: 1\nharnesses: [detected, emacs]\n", encoding="utf-8")

        outcome = subscribing.harness(world.call(), action="remove", name="emacs")

        assert manifests.read(world.manifest, scope=Scope.PROJECT).harnesses == ("detected",)
        assert outcome.changed

    def test_removing_one_nobody_knows_and_nobody_named_is_still_a_usage_error(self, world: World):
        with pytest.raises(UsageError, match="Known harnesses"):
            subscribing.harness(world.call(), action="remove", name="emacs")


class TestUpdate:
    def test_a_changed_part_moves_the_pin_and_shows_the_diff(self, world: World):
        subscribing.add(world.call(), source=world.remote, name="writing", kind=Kind.SKILL)
        was = subscriptions(world.manifest)["skills/writing"]
        head = world.commit({"skills/writing/SKILL.md": "# writing, revised\n"})

        outcome = subscribing.update(world.call())

        assert subscriptions(world.manifest)["skills/writing"] == head != was
        assert "# writing, revised" in outcome.diffs[0]
        assert (world.project / SKILLS / "writing" / "SKILL.md").read_text(encoding="utf-8") == "# writing, revised\n"

    def test_a_moved_part_is_reported_rather_than_acted_on(self, world: World):
        subscribing.add(world.call(), source=world.remote, name="writing", kind=Kind.SKILL)
        world.commit(
            {"skills/writing/SKILL.md": None, "skills/prose/writing/SKILL.md": "# writing\n"},
            message="tidy up",
        )

        outcome = subscribing.update(world.call())

        assert "moved from skills/writing to skills/prose/writing" in outcome.notes[0].text

    def test_a_deleted_part_stops_that_key_and_leaves_its_pin(self, world: World):
        subscribing.add(world.call(), source=world.remote, name="writing", kind=Kind.SKILL)
        subscribing.add(world.call(), source=world.remote, name="prose-style", kind=Kind.RULE)
        was = subscriptions(world.manifest)
        world.commit({"skills/writing/SKILL.md": None, "rules/prose-style.md": "Write shorter.\n"})

        outcome = subscribing.update(world.call())

        after = subscriptions(world.manifest)
        assert after["skills/writing"] == was["skills/writing"], "the stopped key stays where it was"
        assert after["rules/prose-style"] != was["rules/prose-style"], "every other key is free to move"
        assert "akit remove writing" in outcome.notes[0].text

    def test_a_wildcard_lists_what_disappeared_beside_what_changed(self, world: World):
        subscribing.add(world.call(), source=world.remote, name="*", kind=Kind.RULE)
        world.commit({"rules/writing.md": None, "rules/prose-style.md": "Write shorter.\n"})

        outcome = subscribing.update(world.call())

        assert "gone upstream: rules/writing.md" in outcome.notes[0].text
        assert subscriptions(world.manifest)["rules/*"] is not None

    def test_a_source_already_at_the_newest_commit_says_so(self, world: World):
        subscribing.add(world.call(), source=world.remote, name="writing", kind=Kind.SKILL)
        before = world.written

        outcome = subscribing.update(world.call())

        assert world.written == before
        assert not outcome.changed
        assert "already at the newest commit" in outcome.notes[0].text

    def test_a_path_source_has_no_pin_to_move(self, world: World):
        subscribing.add(world.call(), source=str(world.remote_root), name="writing", kind=Kind.SKILL)

        outcome = subscribing.update(world.call())

        assert "which has no pin" in outcome.notes[0].text
        assert not outcome.changed

    def test_one_name_updates_only_its_own_key(self, tmp_path: Path, world: World):
        other = local_remote(tmp_path / "other", {"skills/fkb/SKILL.md": "# fkb\n"})
        subscribing.add(world.call(), source=world.remote, name="writing", kind=Kind.SKILL)
        subscribing.add(world.call(), source=other, name="fkb", kind=Kind.SKILL)
        was = subscriptions(world.manifest)
        world.commit({"skills/writing/SKILL.md": "# writing, revised\n"})

        subscribing.update(world.call(), name="writing")

        after = subscriptions(world.manifest)
        assert after["skills/writing"] != was["skills/writing"]
        assert after["skills/fkb"] == was["skills/fkb"]

    def test_a_name_nobody_subscribed_to_says_to_look(self, world: World):
        with pytest.raises(UsageError, match="akit list"):
            subscribing.update(world.call(), name="writing")

    def test_a_pin_the_cache_lost_still_updates(self, world: World):
        subscribing.add(world.call(), source=world.remote, name="writing", kind=Kind.SKILL)
        world.commit({"skills/writing/SKILL.md": "# writing, revised\n"})
        hand_written = world.written.replace(subscriptions(world.manifest)["skills/writing"] or "", "0" * 40)
        world.manifest.write_text(hand_written, encoding="utf-8")

        outcome = subscribing.update(world.call())

        assert outcome.changed
        assert subscriptions(world.manifest)["skills/writing"] != "0" * 40

    def test_an_unpinned_key_is_pinned_by_the_first_update(self, world: World):
        world.manifest.write_text(
            textwrap.dedent(f"""\
                version: 1

                skills:
                  {world.remote}: writing
                """),
            encoding="utf-8",
        )

        outcome = subscribing.update(world.call())

        assert "moves from an unpinned key" in outcome.notes[0].text
        assert subscriptions(world.manifest)["skills/writing"] is not None


class TestWhatTheyPrint:
    def test_the_text_carries_the_edit_the_diff_and_the_render(self, world: World):
        subscribing.add(world.call(), source=world.remote, name="writing", kind=Kind.SKILL)
        world.commit({"skills/writing/SKILL.md": "# writing, revised\n"})
        outcome = subscribing.update(world.call())
        out = io.StringIO()

        subscribing.report(outcome, out, as_json=False)

        printed = out.getvalue()
        assert "moves from" in printed
        assert "# writing, revised" in printed
        assert "wrote 1 file" in printed

    def test_the_json_carries_the_same_as_data(self, world: World):
        outcome = subscribing.add(world.call(), source=world.remote, name="writing", kind=Kind.SKILL)
        out = io.StringIO()

        subscribing.report(outcome, out, as_json=True)

        payload = json.loads(out.getvalue())
        assert payload["command"] == "add"
        assert payload["created"] is False
        assert payload["notes"][0]["status"] == "added"
        assert payload["render"]["changed_nothing"] is False

    def test_a_created_file_is_said_out_loud(self, world: World):
        outcome = subscribing.add(world.call(only_global=True), source=world.remote, name="writing", kind=Kind.SKILL)
        out = io.StringIO()

        subscribing.report(outcome, out, as_json=False)

        assert "Created " in out.getvalue()


class TestTheFetchingOnlyTheseCommandsDo:
    def test_a_branch_is_followed_to_its_newest_commit(self, world: World):
        head = world.commit({"skills/writing/SKILL.md": "# writing, revised\n"})

        fetched = cache.refresh(parse_source(world.remote), ref="main", cache_root=world.places.cache)

        assert fetched.commit == head
        assert fetched.kind is RefKind.BRANCH
        assert fetched.privacy is cache.Privacy.PUBLIC

    def test_the_default_branch_is_asked_for_rather_than_assumed(self, tmp_path: Path):
        root = tmp_path / "trunk"
        local_remote(root, {"skills/writing/SKILL.md": "# writing\n"})
        git("-C", str(root), "branch", "-m", "main", "trunk")

        fetched = cache.refresh(parse_source(root.as_uri()), cache_root=tmp_path / "cache")

        assert fetched.ref == "trunk"

    def test_a_second_refresh_does_not_reclassify_what_is_already_here(self, world: World):
        cache.refresh(parse_source(world.remote), cache_root=world.places.cache)

        again = cache.refresh(parse_source(world.remote), cache_root=world.places.cache)

        assert again.privacy is None, "the clone that classified it happened once"

    def test_a_remote_that_will_not_answer_names_the_command_to_try(self, tmp_path: Path):
        root = tmp_path / "gone"
        local_remote(root, {"skills/writing/SKILL.md": "# writing\n"})
        source = parse_source(root.as_uri())
        cache.refresh(source, cache_root=tmp_path / "cache")
        for child in sorted(root.rglob("*"), key=lambda entry: len(entry.parts), reverse=True):
            child.chmod(0o700)
            child.rmdir() if child.is_dir() else child.unlink()
        root.rmdir()

        with pytest.raises(UnreachableError, match="git ls-remote"):
            cache.refresh(source, cache_root=tmp_path / "cache")

        with pytest.raises(UnreachableError, match="git ls-remote"):
            cache.refresh(source, ref="main", cache_root=tmp_path / "cache")

    def test_a_source_with_no_commits_cannot_say_what_it_defaults_to(self, tmp_path: Path):
        root = tmp_path / "fresh"
        root.mkdir()
        git("init", "-q", "-b", "main", str(root))

        with pytest.raises(CacheError, match="did not say which branch"):
            cache.refresh(parse_source(root.as_uri()), cache_root=tmp_path / "cache")

    def test_a_diff_of_paths_that_did_not_change_is_empty(self, world: World):
        source = parse_source(world.remote)
        first = cache.refresh(source, cache_root=world.places.cache).commit
        second = world.commit({"rules/prose-style.md": "Write shorter.\n"})
        cache.refresh(source, cache_root=world.places.cache)

        assert cache.difference(source, first, second, ["skills"], cache_root=world.places.cache) == ""
        assert "Write shorter" in cache.difference(source, first, second, ["rules"], cache_root=world.places.cache)

    def test_a_diff_against_a_commit_nobody_has_says_nothing_rather_than_failing(self, world: World):
        source = parse_source(world.remote)
        cache.refresh(source, cache_root=world.places.cache)

        assert cache.difference(source, "0" * 40, "HEAD", ["skills"], cache_root=world.places.cache) == ""


class TestTheCommandLine:
    """The four verbs through the parser they are actually typed at."""

    def run(self, world: World, *argv: str, monkeypatch: pytest.MonkeyPatch) -> tuple[Exit, str]:
        out = io.StringIO()
        monkeypatch.setattr(Path, "cwd", staticmethod(lambda: world.project))
        monkeypatch.setattr(Path, "home", staticmethod(lambda: world.places.home))
        for name, place in (
            ("XDG_CONFIG_HOME", "config"),
            ("XDG_CACHE_HOME", "cache"),
            ("XDG_STATE_HOME", "state"),
            ("XDG_DATA_HOME", "data"),
        ):
            monkeypatch.setenv(name, str(world.places.home.parent / place))
        return dispatch(build_parser().parse_args(list(argv)), out), out.getvalue()

    def test_add_reaches_the_verb_with_its_flags(self, world: World, monkeypatch: pytest.MonkeyPatch):
        code, printed = self.run(
            world, "add", world.remote, "writing", "--kind", "skill", "--as", "house-style", monkeypatch=monkeypatch
        )

        assert code is Exit.OK
        assert "skills/house-style" in subscriptions(world.manifest)
        assert "Subscribed" in printed

    def test_remove_reaches_the_verb(self, world: World, monkeypatch: pytest.MonkeyPatch):
        self.run(world, "add", world.remote, "writing", "--kind", "skill", monkeypatch=monkeypatch)

        code, printed = self.run(world, "remove", "writing", monkeypatch=monkeypatch)

        assert code is Exit.OK
        assert subscriptions(world.manifest) == {}
        assert "Unsubscribed" in printed

    def test_harness_reaches_the_verb(self, world: World, monkeypatch: pytest.MonkeyPatch):
        code, printed = self.run(world, "harness", "add", "copilot-vscode", monkeypatch=monkeypatch)

        assert code is Exit.OK
        assert "copilot-vscode" in printed

    def test_update_reaches_the_verb_and_json_is_the_same_run_as_data(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ):
        self.run(world, "add", world.remote, "writing", "--kind", "skill", monkeypatch=monkeypatch)
        world.commit({"skills/writing/SKILL.md": "# writing, revised\n"})

        code, printed = self.run(world, "--json", "update", monkeypatch=monkeypatch)

        assert code is Exit.OK
        assert json.loads(printed)["notes"][0]["status"] == "moved"

    def test_a_manifest_named_outright_is_the_one_edited(
        self, world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        named = tmp_path / "named.yaml"
        named.write_text("version: 1\n", encoding="utf-8")

        code, _ = self.run(
            world, "add", "--manifest", str(named), world.remote, "writing", "--kind", "skill", monkeypatch=monkeypatch
        )

        assert code is Exit.OK
        assert list(subscriptions(named)) == ["skills/writing"]
        assert subscriptions(world.manifest) == {}
