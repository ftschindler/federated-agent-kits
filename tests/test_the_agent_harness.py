"""The harness that explains an agent failure, tested where no agent is needed.

`disposable_agent.py` is only exercised by the `agent` layer, which wants the
network and node, so the slowest and least reproducible of the four layers is
the one whose diagnostic machinery nothing checks. That is the wrong way round:
a run there fails rarely, and when it does the transcript is all there is to
read.

Both behaviours below were a real Windows failure (#40), and both are cheap to
hold here. `parse` is a pure function over two strings, and whether a
`subprocess` call names its encoding is a fact about the source rather than
about a run, so neither test builds an agent or spawns anything.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from disposable_agent import OpencodeResult

pytestmark = pytest.mark.unit

HARNESS = Path(__file__).resolve().parent / "disposable_agent.py"

#: What a killed process returns for, which is the only return code `parse` is
#: ever handed a `None` stream with.
KILLED = -9


class TestParsingWhateverTheProcessSaid:
    """A diagnostic may not raise. It is what explains something that already did."""

    def test_a_none_stream_is_no_output_rather_than_an_error(self, tmp_path: Path) -> None:
        """The timeout branch kills the process and reads it again, which can hand back `None`.

        An assertion composing the transcript that explains its own failure then
        died in `splitlines`, and the `AttributeError` about a `NoneType`
        replaced the render failure it was about to describe.
        """
        result = OpencodeResult.parse(None, None, KILLED, tmp_path)

        assert result.stdout == ""
        assert result.stderr == ""
        assert result.events == []
        assert result.returncode == KILLED
        assert result.workdir == tmp_path

    def test_a_none_stream_still_builds_a_transcript(self, tmp_path: Path) -> None:
        """Tolerating `None` is only worth anything if what is read off it reads."""
        result = OpencodeResult.parse(None, None, KILLED, tmp_path)

        assert isinstance(result.text, str)

    def test_the_lines_that_are_events_survive_the_lines_that_are_not(self, tmp_path: Path) -> None:
        """Guards the tolerance against being bought by parsing nothing at all.

        opencode's `--format json` stream carries lines that are not JSON and
        lines that are truncated JSON, and a harness that dropped every line
        rather than those would pass the test above while reporting an empty
        run.
        """
        stdout = "\n".join(["warning: something on stderr-ish", '{"type": "text", "text": "hello"}', '{"truncated', ""])

        result = OpencodeResult.parse(stdout, "", 0, tmp_path)

        assert result.events == [{"type": "text", "text": "hello"}]


class TestReadingTheProcessAsUtf8:
    """`text=True` alone decodes with the locale codec, which on Windows is cp1252.

    opencode, npm and uv all emit UTF-8, so one byte outside cp1252 anywhere in
    a transcript raises mid-stream and takes the transcript with it. The comment
    in the harness says every call names its encoding; this is what holds it to
    that as calls are added.
    """

    @staticmethod
    def decoding_calls() -> list[ast.Call]:
        """Every `subprocess` call in the harness that asks for text rather than bytes."""
        tree = ast.parse(HARNESS.read_text(encoding="utf-8"), filename=str(HARNESS))
        return [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and any(
                keyword.arg == "text" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True
                for keyword in node.keywords
            )
        ]

    def test_there_are_calls_to_check(self) -> None:
        """So that a rename of the module under it fails here rather than passing empty."""
        assert self.decoding_calls()

    def test_every_one_of_them_names_utf_8(self) -> None:
        for call in self.decoding_calls():
            named = {
                keyword.arg: keyword.value.value for keyword in call.keywords if isinstance(keyword.value, ast.Constant)
            }
            assert named.get("encoding") == "utf-8", f"line {call.lineno} decodes with the locale codec"

    def test_every_one_of_them_says_what_an_undecodable_byte_costs(self) -> None:
        """`replace`, because a byte a harness cannot read should cost one character of a
        diagnostic rather than the diagnostic."""
        for call in self.decoding_calls():
            named = {
                keyword.arg: keyword.value.value for keyword in call.keywords if isinstance(keyword.value, ast.Constant)
            }
            assert named.get("errors") == "replace", f"line {call.lineno} leaves the error policy to the default"
