"""Rules, one source file at a time: the frontmatter, the markers, and the names.

This file is the machinery on its own, in memory, with no manifest and no disk.
What a render does with it is `test_render.py`; what it is allowed to do to
somebody's `AGENTS.md` is here, because the host file is prose a person wrote
and every one of these cases is a way of damaging it.

The marker tests all run the same text through `weave` more than once. A
renderer that is right on the first pass and wrong on the second is the
expensive kind of wrong: the damage arrives on an ordinary command somebody
runs from a git hook, long after the change that caused it.
"""

from __future__ import annotations

import pytest

from federated_agent_kits import rules
from federated_agent_kits.rules import Block, RuleError

pytestmark = pytest.mark.unit


def woven(text: str, blocks: list[Block], remove: tuple[str, ...] = ()) -> str:
    """One pass, and then a second over its own output, which must not differ."""
    once = rules.weave(text, blocks, remove=remove)
    assert rules.weave(once, blocks, remove=remove) == once
    return once


class TestReadingOneRuleFile:
    def test_a_file_with_no_frontmatter_is_all_body(self):
        document = rules.parse(b"Name a test after the behaviour.\n", name="style")

        assert document.front is None
        assert document.body == "Name a test after the behaviour.\n"

    def test_frontmatter_is_taken_off_the_body_and_kept(self):
        document = rules.parse(b"---\ndescription: how we name tests\n---\n\nBody.\n", name="style")

        assert document.front is not None
        assert document.front["description"] == "how we name tests"
        assert document.body == "Body.\n"

    def test_an_opening_rule_that_never_closes_is_a_body_and_not_an_error(self):
        document = rules.parse(b"---\nthis is prose, under a horizontal rule\n", name="style")

        assert document.front is None
        assert document.body.startswith("---\n")

    def test_an_empty_frontmatter_block_is_no_keys_rather_than_a_refusal(self):
        document = rules.parse(b"---\n---\nBody.\n", name="style")

        assert document.front is not None
        assert len(document.front) == 0

    def test_a_body_of_only_whitespace_is_empty(self):
        assert rules.parse(b"\n\n  \n", name="style").body == ""

    def test_crlf_arrives_as_lf_so_two_machines_agree_on_the_bytes(self):
        assert rules.parse(b"---\r\nk: v\r\n---\r\n\r\nBody.\r\n", name="style").body == "Body.\n"

    def test_frontmatter_that_is_not_valid_yaml_is_refused_with_a_way_out(self):
        with pytest.raises(RuleError, match="not valid YAML"):
            rules.parse(b"---\nkey: [unclosed\n---\n\nBody.\n", name="style")

    def test_frontmatter_that_is_not_a_mapping_is_refused(self):
        with pytest.raises(RuleError, match="not a mapping of keys"):
            rules.parse(b"---\n- one\n- two\n---\n\nBody.\n", name="style")


class TestRenderingOneRuleForAHarness:
    def test_a_harness_needing_no_keys_gets_the_body_and_nothing_else(self):
        rendered = rules.as_file(b"---\ndescription: d\n---\n\nBody.\n", name="style")

        assert rendered == b"Body.\n"

    def test_a_copilot_rule_carries_apply_to_everything(self):
        rendered = rules.as_file(b"Body.\n", name="style", keys={rules.APPLY_TO: rules.EVERYTHING})

        assert rendered.decode("utf-8") == '---\napplyTo: "**"\n---\n\nBody.\n'

    def test_the_body_arrives_byte_for_byte_under_the_frontmatter_we_added(self):
        source = b"One.\n\n  indented\n\nTwo.\n"

        rendered = rules.as_file(source, name="style", keys={rules.APPLY_TO: rules.EVERYTHING})

        assert rendered.endswith(source)

    def test_a_description_the_author_wrote_survives_and_apply_to_does_not(self):
        source = b"---\ndescription: how we name tests\napplyTo: src/**\n---\n\nBody.\n"

        rendered = rules.as_file(source, name="style", keys={rules.APPLY_TO: rules.EVERYTHING}).decode("utf-8")

        assert "description: how we name tests" in rendered
        assert 'applyTo: "**"' in rendered
        assert "src/**" not in rendered

    def test_a_block_for_a_shared_file_is_the_body_without_the_frontmatter(self):
        assert rules.as_block(b"---\ndescription: d\n---\n\nBody.\n", name="style") == b"Body."


class TestNamesARuleMayNotHave:
    @pytest.mark.parametrize("name", ["two words", "nested/name", "-leading", ".hidden", "trailing.", "", "a\tb"])
    def test_a_name_that_is_not_a_filename_and_a_marker_is_refused(self, name: str):
        with pytest.raises(RuleError, match="not a name a rule can have"):
            rules.check_name(name)

    @pytest.mark.parametrize("name", ["aux", "CON", "com1", "nul.md"])
    def test_a_name_windows_will_not_give_a_file_is_refused_on_both_platforms(self, name: str):
        with pytest.raises(RuleError, match="Windows will not give a file"):
            rules.check_name(name)

    def test_the_refusal_offers_as_rather_than_renaming_it_for_you(self):
        with pytest.raises(RuleError, match="as: <another-name>"):
            rules.check_name("two words")

    @pytest.mark.parametrize("name", ["style", "prose-style", "a.b_c", "r2"])
    def test_an_ordinary_name_is_allowed(self, name: str):
        rules.check_name(name)

    def test_rendering_refuses_the_same_names(self):
        with pytest.raises(RuleError):
            rules.as_file(b"Body.\n", name="two words")
        with pytest.raises(RuleError):
            rules.as_block(b"Body.\n", name="two words")


class TestWritingIntoAFileSomebodyElseOwns:
    def test_a_block_goes_in_at_the_end_of_a_file_that_had_none(self):
        woven_text = woven("Their own notes.\n", [Block(id="style", body="Ours.\n")])

        assert woven_text == "Their own notes.\n\n<!-- BEGIN akit style -->\nOurs.\n<!-- END akit style -->\n"

    def test_an_empty_file_gets_the_block_and_nothing_before_it(self):
        assert woven("", [Block(id="style", body="Ours.\n")]).startswith("<!-- BEGIN akit style -->")

    def test_a_paragraph_between_two_blocks_survives_three_renders(self):
        blocks = [Block(id="first", body="One.\n"), Block(id="second", body="Two.\n")]
        start = (
            "<!-- BEGIN akit first -->\nOne.\n<!-- END akit first -->\n\n"
            "Theirs, written by hand.\n\n"
            "<!-- BEGIN akit second -->\nTwo.\n<!-- END akit second -->\n"
        )

        text = start
        for _ in range(3):
            text = rules.weave(text, blocks)

        assert text == start
        assert "Theirs, written by hand." in text

    def test_a_block_somebody_reordered_by_hand_is_put_back(self):
        blocks = [Block(id="first", body="One.\n"), Block(id="second", body="Two.\n")]
        swapped = (
            "<!-- BEGIN akit second -->\nTwo.\n<!-- END akit second -->\n\n"
            "Theirs.\n\n"
            "<!-- BEGIN akit first -->\nOne.\n<!-- END akit first -->\n"
        )

        text = woven(swapped, blocks)

        assert text.index("BEGIN akit first") < text.index("BEGIN akit second")
        assert "Theirs." in text

    def test_a_block_we_did_not_plan_is_left_exactly_where_it_is(self):
        theirs = "<!-- BEGIN akit someone-elses -->\nNot ours.\n<!-- END akit someone-elses -->\n"

        text = woven(theirs, [Block(id="style", body="Ours.\n")])

        assert theirs in text

    def test_a_removed_block_closes_up_and_leaves_its_neighbours(self):
        start = (
            "Top.\n\n"
            "<!-- BEGIN akit first -->\nOne.\n<!-- END akit first -->\n\n"
            "<!-- BEGIN akit second -->\nTwo.\n<!-- END akit second -->\n"
        )

        text = woven(start, [Block(id="second", body="Two.\n")], remove=("first",))

        assert "akit first" not in text
        assert "<!-- BEGIN akit second -->\nTwo.\n<!-- END akit second -->\n" in text
        assert text.startswith("Top.\n\n")

    def test_removing_the_last_block_leaves_the_host_rather_than_emptying_it(self):
        start = "Their notes.\n\n<!-- BEGIN akit style -->\nOurs.\n<!-- END akit style -->\n"

        assert woven(start, [], remove=("style",)) == "Their notes.\n"

    def test_a_file_that_was_only_ours_becomes_empty_and_is_still_a_file(self):
        start = "<!-- BEGIN akit style -->\nOurs.\n<!-- END akit style -->\n"

        assert woven(start, [], remove=("style",)) == ""

    def test_a_block_whose_end_marker_was_deleted_is_repaired_rather_than_doubled(self):
        start = "Top.\n\n<!-- BEGIN akit style -->\nHalf a block.\n"

        text = woven(start, [Block(id="style", body="Ours.\n")])

        assert text.count("BEGIN akit style") == 1
        assert "Half a block." not in text

    def test_a_block_with_no_body_is_written_and_read_back_as_nothing(self):
        text = woven("", [Block(id="style", body="")])

        assert rules.blocks_in(text) == {"style": ""}

    def test_the_blocks_already_there_are_what_a_hash_is_taken_of(self):
        text = "Theirs.\n\n<!-- BEGIN akit style -->\nOurs.\n<!-- END akit style -->\n\nMore of theirs.\n"

        assert rules.blocks_in(text) == {"style": "Ours."}

    def test_a_marker_without_our_name_in_it_is_somebody_elses_tool(self):
        assert rules.blocks_in("<!-- BEGIN other style -->\nx\n<!-- END other style -->\n") == {}

    def test_more_blocks_than_slots_appends_the_rest_in_order(self):
        start = "<!-- BEGIN akit first -->\nOne.\n<!-- END akit first -->\n"

        text = woven(start, [Block(id="first", body="One.\n"), Block(id="second", body="Two.\n")])

        assert text.index("BEGIN akit first") < text.index("BEGIN akit second")

    def test_fewer_blocks_than_slots_drops_the_spare_slot(self):
        start = (
            "<!-- BEGIN akit first -->\nOne.\n<!-- END akit first -->\n\n"
            "<!-- BEGIN akit first -->\nOne again.\n<!-- END akit first -->\n"
        )

        text = woven(start, [Block(id="first", body="One.\n")])

        assert text.count("BEGIN akit first") == 1

    def test_a_file_that_never_ended_in_a_newline_still_gets_one(self):
        text = woven("Their note, unterminated.", [Block(id="style", body="Ours.\n")])

        assert text.startswith("Their note, unterminated.\n\n")
        assert text.endswith("<!-- END akit style -->\n")

    def test_blank_lines_at_the_end_of_a_host_file_are_not_left_to_accumulate(self):
        text = woven("Theirs.\n\n\n\n", [])

        assert text == "Theirs.\n"
