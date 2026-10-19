"""What a stream is asked before anything colours a word or prints a mark.

The decision has four inputs - two environment variables, the terminal's own
`TERM`, and whether the stream is a terminal at all - and every one of them is a
bug somebody has hit in a real report: colour in a log file, no colour in CI,
and a `UnicodeEncodeError` on a Windows console that cannot encode a tick. Each
gets its own case here rather than being inferred from the report's output.
"""

from __future__ import annotations

import io

import pytest

from federated_agent_kits.styling import MARKS, Style, encodable, wanted

pytestmark = pytest.mark.unit


class Terminal(io.StringIO):
    """A stream that says it is a terminal, and encodes what that terminal encodes."""

    def __init__(self, encoding: str = "utf-8") -> None:
        super().__init__()
        self.given = encoding

    def isatty(self) -> bool:
        return True

    @property
    def encoding(self) -> str:
        return self.given

    @encoding.setter
    def encoding(self, value: str) -> None:
        self.given = value


class TestWhetherColourWasAskedFor:
    def test_a_pipe_gets_none(self):
        assert wanted(io.StringIO(), {}) is False

    def test_a_terminal_gets_it(self):
        assert wanted(Terminal(), {}) is True

    def test_no_color_wins_over_the_terminal(self):
        assert wanted(Terminal(), {"NO_COLOR": "1"}) is False

    def test_force_color_wins_over_the_pipe(self):
        assert wanted(io.StringIO(), {"FORCE_COLOR": "1"}) is True

    def test_no_color_wins_over_force_color(self):
        assert wanted(Terminal(), {"NO_COLOR": "1", "FORCE_COLOR": "1"}) is False

    def test_a_terminal_that_says_it_is_dumb_is_believed(self):
        assert wanted(Terminal(), {"TERM": "dumb"}) is False


class TestWhetherTheMarksCanBeWritten:
    def test_a_stream_holding_text_can_take_anything(self):
        assert encodable(io.StringIO(), MARKS[True][1]) is True

    def test_an_encoding_that_cannot_hold_them_declines(self):
        assert encodable(Terminal("ascii"), MARKS[True][1]) is False

    def test_an_encoding_nobody_has_heard_of_declines_rather_than_raising(self):
        assert encodable(Terminal("not-an-encoding"), MARKS[True][1]) is False

    def test_utf8_takes_them(self):
        assert encodable(Terminal("utf-8"), MARKS[True][1]) is True


class TestTheStyleAReportGets:
    def test_a_pipe_gets_neither_colour_nor_marks(self):
        style = Style.of(io.StringIO(), {})

        assert (style.colour, style.marks) == (False, False)
        assert style.mark(True) == "[x]"
        assert style.mark(False) == "[ ]"
        assert style.kit("akit") == "akit"

    def test_a_utf8_terminal_gets_both(self):
        style = Style.of(Terminal("utf-8"), {})

        assert (style.colour, style.marks) == (True, True)
        assert style.mark(True) == MARKS[True][1]
        assert style.harness("opencode").endswith("\033[0m")

    def test_a_terminal_that_cannot_encode_them_keeps_the_colour_and_drops_the_marks(self):
        style = Style.of(Terminal("ascii"), {})

        assert (style.colour, style.marks) == (True, False)
        assert "[x]" in style.mark(True)
        assert style.mark(True).startswith("\033[")

    def test_the_environment_is_read_when_nobody_passed_one(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("NO_COLOR", "1")

        assert Style.of(Terminal("utf-8")).colour is False

    def test_every_mark_is_three_columns_either_way(self):
        assert {len(plain) for plain, _ in MARKS.values()} == {3}

    def test_a_heading_is_underlined_to_the_length_of_its_own_words(self):
        assert Style.plain().heading("Harnesses", "=") == "Harnesses\n=========\n\n"

    def test_a_coloured_heading_is_underlined_to_the_same_length(self):
        underline = Style(colour=True, marks=True).heading("Harnesses", "=").splitlines()[1]

        assert underline == "========="
