"""The CLI frame: parsing, dispatch, the four exit codes, and `--version`.

These run in-process, which is what makes them the layer that has to reach every
line of `src/`. The same surface is exercised as a subprocess in
`test_cli_frame_as_a_subprocess.py`, and as an installed console script in
`test_entry_point.py`; neither of those can be measured by coverage, and neither
can inject an error to see which number comes back.
"""

from __future__ import annotations

import argparse
import io
import json
from importlib.metadata import PackageNotFoundError

import pytest

from federated_agent_kits import cli, commands
from federated_agent_kits.cli import build_parser, dispatch, main, show_topic, version
from federated_agent_kits.commands import COMMANDS, unimplemented
from federated_agent_kits.exits import AkitError, Exit, NotImplementedYetError, RefusalError, UsageError

pytestmark = pytest.mark.unit


def parse(*argv: str) -> argparse.Namespace:
    return build_parser().parse_args(list(argv))


class TestExitCodes:
    """Four numbers, and the distinction the middle two carry.

    A refusal is not a usage error. A hook that sees 3 knows a private kit was
    aimed at a public repository and that there is no flag to get past it; a hook
    that sees 2 knows somebody typed the command wrong. Collapsing them would
    make the first indistinguishable from a typo.
    """

    def test_they_are_the_four_the_design_names(self) -> None:
        assert (Exit.OK, Exit.ERROR, Exit.USAGE, Exit.REFUSAL) == (0, 1, 2, 3)

    def test_a_plain_failure_is_one(self) -> None:
        assert self.code_for(AkitError("the source will not clone")) == Exit.ERROR

    def test_a_usage_error_is_two(self) -> None:
        assert self.code_for(UsageError("no such scope")) == Exit.USAGE

    def test_a_refusal_is_three(self) -> None:
        assert self.code_for(RefusalError("private source into a public target")) == Exit.REFUSAL

    def test_a_verb_that_has_not_landed_is_a_usage_error(self) -> None:
        assert NotImplementedYetError("render", "T5").exit_code == Exit.USAGE

    @staticmethod
    def code_for(error: Exception) -> int:
        def raising(_arguments: argparse.Namespace, _out: object) -> Exit:
            raise error

        return main(["list"], run_command=raising)

    def test_the_message_reaches_stderr(self, capsys: pytest.CaptureFixture[str]) -> None:
        self.code_for(RefusalError("acme/kits is private; this repository is public"))
        assert "acme/kits is private" in capsys.readouterr().err

    def test_success_is_zero(self) -> None:
        assert main(["help", "manifest"]) == Exit.OK


class TestVersion:
    def test_it_comes_from_the_installed_metadata(self) -> None:
        assert version()

    def test_a_source_tree_that_was_never_installed_says_so(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def missing(_name: str) -> str:
            raise PackageNotFoundError(_name)

        monkeypatch.setattr(cli, "installed_version", missing)
        assert version() == "0+unknown"

    def test_the_flag_prints_it(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as raised:
            build_parser().parse_args(["--version"])
        assert raised.value.code == 0
        assert capsys.readouterr().out.strip() == f"akit {version()}"


class TestGlobalFlags:
    """`--json` and `--verbose` work on either side of the verb.

    The subparser copies default to `SUPPRESS`, so an unset flag leaves the main
    parser's answer alone. Without that, `akit --json list` would quietly print
    text, which is the kind of bug that is noticed by a model and not by a
    person.
    """

    @pytest.mark.parametrize("argv", [["--json", "list"], ["list", "--json"]])
    def test_json_is_accepted_before_or_after_the_verb(self, argv: list[str]) -> None:
        assert parse(*argv).json is True

    @pytest.mark.parametrize("argv", [["--verbose", "doctor"], ["doctor", "--verbose"]])
    def test_verbose_is_accepted_before_or_after_the_verb(self, argv: list[str]) -> None:
        assert parse(*argv).verbose is True

    def test_they_are_off_by_default(self) -> None:
        arguments = parse("list")
        assert (arguments.json, arguments.verbose) == (False, False)


class TestParsing:
    def test_no_command_prints_the_help_and_is_a_usage_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main([]) == Exit.USAGE
        assert "akit" in capsys.readouterr().out

    def test_an_unknown_command_is_a_usage_error(self) -> None:
        with pytest.raises(SystemExit) as raised:
            parse("summon")
        assert raised.value.code == Exit.USAGE

    def test_a_flag_that_takes_a_value_keeps_it(self) -> None:
        assert parse("add", "acme/kits", "writing", "--as", "house-style").rename == "house-style"

    def test_a_repeatable_flag_collects(self) -> None:
        assert parse("render", "--harness", "opencode", "--harness", "vscode").harness == ["opencode", "vscode"]

    def test_a_choice_outside_the_list_is_refused(self) -> None:
        with pytest.raises(SystemExit) as raised:
            parse("harness", "sideways", "opencode")
        assert raised.value.code == Exit.USAGE

    def test_an_optional_positional_may_be_omitted(self) -> None:
        assert parse("update").name is None

    def test_global_does_not_shadow_the_builtin(self) -> None:
        # `--global` cannot be an attribute name, so it is spelled `global_scope`
        # on the namespace. A test, because the rename is invisible at the call
        # site and silently returns `False` if a later command forgets it.
        assert parse("add", "acme/kits", "writing", "--global").global_scope is True


class TestHelpTopics:
    def test_a_topic_prints_its_body_and_its_next_line(self) -> None:
        out = io.StringIO()
        assert show_topic("manifest", as_json=False, out=out) == Exit.OK
        printed = out.getvalue()
        assert ".akit.yaml" in printed
        assert printed.rstrip().startswith("manifest - ")
        assert "Next:" in printed
        assert "See also: akit help sources" in printed

    def test_json_carries_the_same_information_as_data(self) -> None:
        out = io.StringIO()
        assert show_topic("privacy", as_json=True, out=out) == Exit.OK
        payload = json.loads(out.getvalue())
        assert payload["topic"] == "privacy"
        assert payload["see_also"] == ["harnesses"]
        assert "no `--force`" in payload["body"]

    def test_a_topic_with_no_see_also_prints_no_see_also_line(self) -> None:
        # None of the four is alone today; the branch still has to be reachable,
        # so it is reached rather than left as an untested `if`.
        lonely = commands.Topic(name="x", summary="s", body="a\n\nb", following="akit list")
        out = io.StringIO()
        with pytest.MonkeyPatch.context() as patch:
            patch.setitem(commands.TOPICS_BY_NAME, "x", lonely)
            assert show_topic("x", as_json=False, out=out) == Exit.OK
        assert "See also:" not in out.getvalue()

    def test_an_unknown_topic_is_a_usage_error(self) -> None:
        with pytest.raises(SystemExit) as raised:
            parse("help", "telepathy")
        assert raised.value.code == Exit.USAGE


class TestNotImplementedYet:
    """Every verb parses, and then says which task it is waiting for.

    The list below is the whole of what T1 ships: a frame. T12 replaces the
    expected value with an empty list, and until then any verb arriving or
    leaving has to be a deliberate edit to this line.
    """

    def test_the_list_is_exactly_what_has_not_landed(self) -> None:
        assert unimplemented() == ["list", "add", "remove", "harness", "render", "update", "doctor"]

    def test_help_is_the_one_verb_that_works(self) -> None:
        assert [command.name for command in COMMANDS if command.implemented] == ["help"]

    @pytest.mark.parametrize("name", unimplemented())
    def test_each_one_names_its_task(self, name: str) -> None:
        with pytest.raises(NotImplementedYetError) as raised:
            dispatch(argparse.Namespace(command=name), io.StringIO())
        message = str(raised.value)
        assert name in message
        assert "not implemented yet" in message
        assert "T" in message
