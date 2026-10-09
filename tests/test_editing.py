"""Editing a manifest: which file gets written, and what survives the writing.

The round-trip property itself belongs to `test_manifest.py`, which owns the
reader. What this file owns is the other direction: an edit that has to leave
everything it did not mean to touch exactly as it found it, and the four
refusals that decide which file is edited at all.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from federated_agent_kits import editing
from federated_agent_kits import manifest as manifests
from federated_agent_kits.exits import UsageError
from federated_agent_kits.manifest import Kind, Scope

pytestmark = pytest.mark.unit

WRITTEN_BY_HAND = """\
version: 1

# The kits this repository expects.
skills:
  owner/repo#9f2c1ab:   # frozen: v2
  - writing
  - name: kb
    as: upstream-kb

  acme/kits#4d7e08b: solo   # frozen: main, 2026-10-05

rules:
- owner/repo#9f2c1ab: prose-style   # frozen: v2

harnesses: [detected]
"""


def parsed(text: str, path: Path | None = None) -> manifests.Manifest:
    return manifests.parse(textwrap.dedent(text), scope=Scope.PROJECT, path=path)


@pytest.fixture
def by_hand() -> manifests.Manifest:
    return parsed(WRITTEN_BY_HAND)


class TestChoosingTheFile:
    def test_the_repository_is_the_default(self, tmp_path: Path):
        (tmp_path / ".git").mkdir()
        (tmp_path / ".akit.yaml").write_text("version: 1\n", encoding="utf-8")

        chosen = editing.choose(tmp_path, user_path=tmp_path / "elsewhere.yaml")

        assert chosen.path == tmp_path / ".akit.yaml"
        assert chosen.scope is Scope.PROJECT
        assert chosen.existed

    def test_a_repository_without_a_manifest_names_the_two_ways_in(self, tmp_path: Path):
        (tmp_path / ".git").mkdir()

        with pytest.raises(UsageError, match="--project to create it"):
            editing.choose(tmp_path, user_path=tmp_path / "elsewhere.yaml")

    def test_project_creates_one_because_it_was_asked_outright(self, tmp_path: Path):
        (tmp_path / ".git").mkdir()

        chosen = editing.choose(tmp_path, only_project=True, user_path=tmp_path / "elsewhere.yaml")

        assert not chosen.existed
        assert chosen.manifest.subscriptions == ()
        assert not chosen.path.exists(), "choosing a file may not create it"

    def test_outside_a_repository_it_says_so(self, tmp_path: Path):
        with pytest.raises(UsageError, match="not inside a git repository"):
            editing.choose(tmp_path, only_project=True, user_path=tmp_path / "elsewhere.yaml")

    def test_global_takes_yours(self, tmp_path: Path):
        yours = tmp_path / "config" / "manifest.yaml"

        chosen = editing.choose(tmp_path, only_global=True, user_path=yours)

        assert chosen.path == yours
        assert chosen.scope is Scope.USER

    def test_both_flags_at_once_is_a_question(self, tmp_path: Path):
        with pytest.raises(UsageError, match="two different files"):
            editing.choose(tmp_path, only_global=True, only_project=True, user_path=tmp_path / "m.yaml")

    def test_a_named_file_is_read_where_it_is(self, tmp_path: Path):
        named = tmp_path / "somewhere" / "akit.yaml"
        named.parent.mkdir()
        named.write_text("version: 1\n", encoding="utf-8")

        chosen = editing.choose(tmp_path, named=named, user_path=tmp_path / "m.yaml")

        assert chosen.path == named
        assert chosen.scope is Scope.PROJECT

    def test_a_named_file_that_is_yours_keeps_your_scope(self, tmp_path: Path):
        yours = tmp_path / "config" / "manifest.yaml"

        chosen = editing.choose(tmp_path, named=yours, user_path=yours)

        assert chosen.scope is Scope.USER


class TestWritingASubscription:
    def test_it_lands_beside_the_key_that_is_already_there(self, by_hand: manifests.Manifest):
        after = editing.subscribe(by_hand, editing.Entry(kind=Kind.SKILL, key="owner/repo#9f2c1ab", name="debugging"))

        assert "- debugging" in manifests.dump(after)
        assert "# frozen: v2" in manifests.dump(after)
        assert [entry.name for entry in after.of_kind(Kind.SKILL)] == ["writing", "kb", "debugging", "solo"]

    def test_a_scalar_entry_becomes_a_list_rather_than_being_overwritten(self, by_hand: manifests.Manifest):
        after = editing.subscribe(by_hand, editing.Entry(kind=Kind.SKILL, key="acme/kits#4d7e08b", name="second"))

        names = [entry.name for entry in after.of_kind(Kind.SKILL)]
        assert names == ["writing", "kb", "solo", "second"]
        assert "# frozen: main, 2026-10-05" in manifests.dump(after)

    def test_a_new_key_carries_the_comment_it_was_given(self, by_hand: manifests.Manifest):
        after = editing.subscribe(
            by_hand,
            editing.Entry(kind=Kind.SKILL, key="third/party#abc1234", name="fkb", comment="frozen: v1"),
        )

        assert "third/party#abc1234: fkb  # frozen: v1" in manifests.dump(after)

    def test_a_rule_lands_in_the_list_and_keeps_its_order(self, by_hand: manifests.Manifest):
        after = editing.subscribe(by_hand, editing.Entry(kind=Kind.RULE, key="other/repo#1234567", name="second-rule"))

        assert [entry.name for entry in after.of_kind(Kind.RULE)] == ["prose-style", "second-rule"]

    def test_a_renamed_kit_is_written_as_the_mapping_it_has_to_be(self, by_hand: manifests.Manifest):
        after = editing.subscribe(
            by_hand,
            editing.Entry(kind=Kind.SKILL, key="owner/repo#9f2c1ab", name="kb", rename="their-kb"),
        )

        found = next(entry for entry in after.of_kind(Kind.SKILL) if entry.rename == "their-kb")
        assert found.name == "kb"

    def test_a_missing_kind_block_is_created_above_the_harness_list(self):
        after = editing.subscribe(
            parsed("version: 1\nharnesses: [detected]\n"),
            editing.Entry(kind=Kind.AGENT, key="owner/repo#9f2c1ab", name="reviewer"),
        )

        written = manifests.dump(after)
        assert written.index("agents:") < written.index("harnesses:")

    def test_a_manifest_with_nothing_in_it_grows_its_first_block(self):
        after = editing.subscribe(
            parsed("version: 1\n"),
            editing.Entry(kind=Kind.SKILL, key="owner/repo#9f2c1ab", name="writing"),
        )

        assert [entry.name for entry in after.of_kind(Kind.SKILL)] == ["writing"]

    def test_everything_else_in_the_file_is_untouched(self, by_hand: manifests.Manifest):
        after = manifests.dump(
            editing.subscribe(by_hand, editing.Entry(kind=Kind.SKILL, key="new/source#7654321", name="later"))
        )

        assert "# The kits this repository expects." in after
        assert "  - name: kb\n    as: upstream-kb\n" in after


class TestDroppingASubscription:
    def test_one_name_goes_and_its_neighbours_stay(self, by_hand: manifests.Manifest):
        wanted = next(entry for entry in by_hand.of_kind(Kind.SKILL) if entry.name == "writing")

        after = editing.unsubscribe(by_hand, wanted)

        assert [entry.name for entry in after.of_kind(Kind.SKILL)] == ["kb", "solo"]
        assert "# frozen: v2" in manifests.dump(after)

    def test_a_renamed_kit_is_found_by_what_it_was_called(self, by_hand: manifests.Manifest):
        wanted = next(entry for entry in by_hand.of_kind(Kind.SKILL) if entry.rename == "upstream-kb")

        after = editing.unsubscribe(by_hand, wanted)

        assert [entry.name for entry in after.of_kind(Kind.SKILL)] == ["writing", "solo"]

    def test_a_key_holding_nothing_goes_with_it(self, by_hand: manifests.Manifest):
        wanted = next(entry for entry in by_hand.of_kind(Kind.SKILL) if entry.name == "solo")

        after = manifests.dump(editing.unsubscribe(by_hand, wanted))

        assert "acme/kits" not in after

    def test_a_kind_block_holding_nothing_goes_too(self, by_hand: manifests.Manifest):
        wanted = next(iter(by_hand.of_kind(Kind.RULE)))

        after = manifests.dump(editing.unsubscribe(by_hand, wanted))

        assert "rules:" not in after

    def test_the_last_of_two_plain_names_is_written_back_as_a_scalar(self):
        found = parsed("version: 1\n\nskills:\n  owner/repo#9f2c1ab:\n  - writing\n  - fkb\n")
        wanted = next(entry for entry in found.of_kind(Kind.SKILL) if entry.name == "fkb")

        after = editing.unsubscribe(found, wanted)

        assert "owner/repo#9f2c1ab: writing" in manifests.dump(after)

    def test_a_key_whose_kits_all_go_goes_with_them(self, by_hand: manifests.Manifest):
        after = by_hand
        for name in ("writing", "kb"):
            wanted = next(entry for entry in after.of_kind(Kind.SKILL) if entry.name == name)
            after = editing.unsubscribe(after, wanted)

        assert [entry.name for entry in after.of_kind(Kind.SKILL)] == ["solo"]
        assert "owner/repo#9f2c1ab: prose-style" in manifests.dump(after), "the rules key is a different key"

    def test_a_rule_entry_leaving_empties_its_list_item(self):
        found = parsed("version: 1\n\nrules:\n- owner/repo#9f2c1ab:\n  - one\n  - two\n")
        first = next(entry for entry in found.of_kind(Kind.RULE) if entry.name == "one")

        after = editing.unsubscribe(found, first)

        assert [entry.name for entry in after.of_kind(Kind.RULE)] == ["two"]


class TestMovingAPin:
    def test_the_key_is_rewritten_where_it_stands(self, by_hand: manifests.Manifest):
        after = editing.repin(by_hand, kind=Kind.SKILL, key="owner/repo#9f2c1ab", pin="deadbee", comment="frozen: v3")

        written = manifests.dump(after)
        assert "owner/repo#deadbee:   # frozen: v3" in written
        assert written.index("owner/repo") < written.index("acme/kits"), "the order is the author's"
        assert "# The kits this repository expects." in written

    def test_a_rule_pin_moves_the_same_way(self, by_hand: manifests.Manifest):
        after = editing.repin(by_hand, kind=Kind.RULE, key="owner/repo#9f2c1ab", pin="deadbee")

        assert next(iter(after.of_kind(Kind.RULE))).pin == "deadbee"

    def test_the_blank_line_after_a_comment_survives(self, by_hand: manifests.Manifest):
        after = manifests.dump(
            editing.repin(by_hand, kind=Kind.SKILL, key="acme/kits#4d7e08b", pin="deadbee", comment="frozen: main")
        )

        assert "# frozen: main\n\nrules:" in after

    def test_moving_a_pin_to_where_it_already_is_changes_nothing(self, by_hand: manifests.Manifest):
        before = manifests.dump(by_hand)

        after = editing.repin(by_hand, kind=Kind.SKILL, key="owner/repo#9f2c1ab", pin="9f2c1ab")

        assert manifests.dump(after) == before


class TestTheHarnessList:
    def test_naming_one_writes_the_implied_list_out_first(self):
        after = editing.name_harness(parsed("version: 1\n"), "copilot-vscode")

        assert after.harnesses == ("detected", "copilot-vscode")

    def test_naming_one_twice_leaves_one(self, by_hand: manifests.Manifest):
        after = editing.name_harness(editing.name_harness(by_hand, "copilot-vscode"), "copilot-vscode")

        assert after.harnesses == ("detected", "copilot-vscode")

    def test_dropping_detected_is_how_a_repository_pins_the_list(self, by_hand: manifests.Manifest):
        after = editing.unname_harness(by_hand, "detected")

        assert after.harnesses == ()

    def test_dropping_from_an_implied_list_writes_it_out(self):
        after = editing.unname_harness(parsed("version: 1\n"), "detected")

        assert after.harnesses == ()

    def test_dropping_one_that_is_not_there_leaves_the_list(self, by_hand: manifests.Manifest):
        after = editing.unname_harness(by_hand, "copilot-vscode")

        assert after.harnesses == ("detected",)


def test_a_blank_manifest_is_the_version_and_nothing_else(tmp_path: Path):
    found = editing.blank(Scope.USER, tmp_path / "manifest.yaml")

    assert found.subscriptions == ()
    assert manifests.dump(found) == "version: 1\n"


class TestAddingBesideARenamedKit:
    """A second kit on a key whose first kit was written as a `{name:, as:}` mapping.

    The shape `akit add --as` leaves behind, which until now could not be added
    to: the mapping carried the comment that sat beside its key, kept carrying
    it into the list it was moved into, and came back out as one line that is
    not YAML. It failed on re-parse, so nothing was written and the manifest was
    left correct - which is why it survived to be found by hand rather than by a
    broken file.
    """

    def renamed(self, tmp_path: Path, kind: str, lead: str) -> manifests.Manifest:
        path = tmp_path / ".akit.yaml"
        path.write_text(
            f"version: 1\n\n{kind}:\n{lead}https://example.test/kits#abc:  # frozen: main\n"
            "    name: writing\n    as: felix-writing\n",
            encoding="utf-8",
        )
        return manifests.read(path, scope=Scope.PROJECT)

    @pytest.mark.parametrize(("kind", "lead"), [("skills", "  "), ("rules", "- ")])
    def test_a_second_kit_lands_beside_a_renamed_one_and_still_parses(self, tmp_path: Path, kind: str, lead: str):
        found = self.renamed(tmp_path, kind, lead)

        after = editing.subscribe(
            found,
            editing.Entry(
                kind=Kind.SKILL if kind == "skills" else Kind.RULE,
                key="https://example.test/kits#abc",
                name="agent-conduct",
                comment="frozen: main",
            ),
        )

        reparsed = manifests.parse(manifests.dump(after), scope=Scope.PROJECT)
        assert sorted(entry.name for entry in reparsed.subscriptions) == ["agent-conduct", "writing"]

    def test_the_rename_it_was_added_beside_survives(self, tmp_path: Path):
        found = self.renamed(tmp_path, "skills", "  ")

        after = editing.subscribe(
            found,
            editing.Entry(
                kind=Kind.SKILL, key="https://example.test/kits#abc", name="agent-conduct", comment="frozen: main"
            ),
        )

        reparsed = manifests.parse(manifests.dump(after), scope=Scope.PROJECT)
        writing = next(entry for entry in reparsed.subscriptions if entry.name == "writing")
        assert writing.rename == "felix-writing"

    def test_the_comment_is_not_duplicated_into_the_list(self, tmp_path: Path):
        found = self.renamed(tmp_path, "skills", "  ")

        after = editing.subscribe(
            found,
            editing.Entry(
                kind=Kind.SKILL, key="https://example.test/kits#abc", name="agent-conduct", comment="frozen: main"
            ),
        )

        assert manifests.dump(after).count("frozen: main") == 1
