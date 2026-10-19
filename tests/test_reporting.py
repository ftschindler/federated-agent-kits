"""The shape rules every report shares, tested where they are decided.

Each of these is asserted somewhere in a verb's own snapshot too, which is the
point: this file is where a rule is pinned once, so that a verb's test failing
says the verb drifted rather than that the rule changed.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from federated_agent_kits import reporting
from federated_agent_kits.manifest import Scope
from federated_agent_kits.styling import Style

pytestmark = pytest.mark.unit


def printed(call) -> str:
    out = io.StringIO()
    call(out)
    return out.getvalue()


class TestWhereAHeadingSitsInTheHierarchy:
    def test_a_section_is_ruled_with_equals_and_a_group_with_dashes(self):
        plain = Style.plain()

        assert printed(lambda out: reporting.section("Harnesses", out, plain)) == "Harnesses\n=========\n\n"
        assert printed(lambda out: reporting.group("Skills", out, plain)) == "Skills\n------\n\n"

    def test_the_rule_is_as_long_as_the_heading_it_is_under(self):
        shown = printed(lambda out: reporting.section("Name collisions", out, Style.plain()))

        title, rule, _, _ = shown.split("\n")
        assert len(rule) == len(title)

    def test_no_caller_picks_a_rule_character(self):
        """The two levels are named, so a report cannot grow a third by accident."""
        assert reporting.SECTION != reporting.GROUP
        assert {reporting.SECTION, reporting.GROUP} == {"=", "-"}


class TestWhatTheTwoScopesAreCalled:
    def test_every_name_for_a_scope_uses_the_word_its_flag_uses(self):
        for scope, word in ((Scope.USER, "global"), (Scope.PROJECT, "project")):
            assert word in reporting.SCOPE_TITLE[scope].lower()
            assert word in reporting.SCOPE_NAMED[scope].lower()
            assert word in reporting.SCOPE_MANIFEST[scope].lower()

    def test_the_project_comes_first(self):
        assert reporting.ORDERING[0] is Scope.PROJECT

    def test_a_scope_with_no_manifest_names_the_file_that_is_not_there(self):
        assert "no .akit.yaml found" in reporting.scope_title(Scope.PROJECT, None)
        assert "no manifest.yaml found" in reporting.scope_title(Scope.USER, None)

    def test_a_scope_with_a_manifest_names_it(self):
        assert reporting.scope_title(Scope.USER, Path("/tmp/manifest.yaml")).endswith("(/tmp/manifest.yaml)")
        assert reporting.manifest_title(Scope.PROJECT, Path("/tmp/.akit.yaml")).endswith("(/tmp/.akit.yaml)")


class TestTheColumnOfMarks:
    def column(self, *names: str) -> reporting.Column:
        return reporting.Column.of(names, Style.plain())

    def test_a_mark_is_three_columns_so_a_block_of_them_reads_down(self):
        column = self.column("opencode", "copilot-ci")

        shown = printed(lambda out: column.marked("opencode", "here", out, present=True))
        absent = printed(lambda out: column.marked("copilot-ci", "there", out, present=False))

        assert shown.index("here") == absent.index("there")

    def test_the_names_line_up_whatever_their_lengths(self):
        column = self.column("a", "much-longer-name")

        short = printed(lambda out: column.marked("a", "says", out, present=True))
        long = printed(lambda out: column.marked("much-longer-name", "says", out, present=True))

        assert short.index("says") == long.index("says")

    def test_a_thing_with_no_machine_is_listed_rather_than_marked(self):
        column = self.column("copilot-ci")

        shown = printed(lambda out: column.listed("copilot-ci", "named in a manifest", out))

        assert shown.startswith("-   copilot-ci")
        assert "[x]" not in shown and "[ ]" not in shown

    def test_a_listed_line_keeps_the_column_the_marks_put_the_text_in(self):
        column = self.column("copilot-ci")

        marked = printed(lambda out: column.marked("copilot-ci", "says", out, present=True))
        listed = printed(lambda out: column.listed("copilot-ci", "says", out))

        assert marked.index("says") == listed.index("says")

    def test_padding_is_counted_before_the_colour_goes_on(self):
        """An escape sequence is zero columns on a terminal and several characters in a string."""
        column = reporting.Column.of(("a", "bbb"), Style(colour=True, marks=False))

        assert column.padded("a").endswith("  ")

    def test_an_empty_column_is_zero_wide_rather_than_an_error(self):
        assert reporting.width_of(()) == 0


class TestTheSentencesAReportIsMadeOf:
    @pytest.mark.parametrize(
        ("items", "expected"),
        [((), ""), (("a",), "a"), (("a", "b"), "a and b"), (("a", "b", "c"), "a, b and c")],
    )
    def test_a_list_reads_like_english(self, items: tuple[str, ...], expected: str):
        assert reporting.joined(items) == expected

    @pytest.mark.parametrize(("number", "expected"), [(0, "no files"), (1, "1 file"), (2, "2 files")])
    def test_a_count_reads_like_english(self, number: int, expected: str):
        assert reporting.counted(number, "file") == expected

    def test_a_sentence_that_arrived_with_newlines_keeps_them_under_one_indent(self):
        shown = printed(lambda out: reporting.wrapped("first", ("second", "third"), out))

        assert shown == "  first\n    second\n    third\n"

    def test_the_continuation_indents_from_wherever_the_first_line_was_put(self):
        shown = printed(lambda out: reporting.wrapped("first", ("second",), out, indent=""))

        assert shown == "first\n  second\n"
