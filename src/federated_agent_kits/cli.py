"""The `akit` command line: argument parsing, help, and exit codes. Nothing else.

This is the frame every later task hangs a verb on, and it deliberately does no
work. A verb implemented here would be a verb implemented without the tests its
own task writes, so each one parses its arguments, prints which task it is
waiting for, and exits 2.

The help is not a formality. DESIGN.md section 11 keeps everything deterministic
in the CLI so that the skill can say "run `akit list`" and never describe the
output; that only holds if the help carries the explanation, so the contract in
`commands.py` is data and `tests/test_help_contract.py` enforces it over every
registered command at once.
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
from collections.abc import Callable, Sequence
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as installed_version
from typing import Any, TextIO

from federated_agent_kits.commands import COMMANDS, TOPICS, TOPICS_BY_NAME, Argument, Command
from federated_agent_kits.exits import AkitError, Exit, NotImplementedYetError

DISTRIBUTION = "federated-agent-kits"
WIDTH = 88

PROLOGUE = """\
Subscribe to kits - skills, rules and agent definitions - from wherever they live, and
write them where each harness looks. A source is an ordinary git repository; the file you
edit is the only copy, and everything rendered is generated and disposable.
"""


def version() -> str:
    """What `--version` prints, read from the installed metadata rather than a constant.

    One number, in `pyproject.toml`, written by the release job. A constant here
    would be a second place to forget, and the skill's own `VERSION` file (T11)
    is written from the same number so the two cannot disagree.
    """
    try:
        return installed_version(DISTRIBUTION)
    except PackageNotFoundError:  # a source tree that was never installed
        return "0+unknown"


def wrap(text: str) -> str:
    return "\n".join(textwrap.fill(paragraph, WIDTH) for paragraph in text.split("\n\n"))


def format_description(command: Command) -> str:
    """One sentence, then the paragraph about what lands on disk."""
    return f"{command.summary}.\n\n{wrap(command.writes)}"


def format_epilog(command: Command) -> str:
    """The worked examples, then the `Next:` line."""
    examples = "\n".join(f"  {example}" for example in command.examples)
    return f"examples:\n{examples}\n\nNext: {command.following}"


def add_argument(parser: argparse.ArgumentParser, argument: Argument) -> None:
    """Hand one declared argument to argparse, carrying only the keys it was given."""
    options: dict[str, Any] = {"help": argument.help}
    if argument.metavar is not None:
        options["metavar"] = argument.metavar
    if argument.choices is not None:
        options["choices"] = argument.choices
    if argument.nargs is not None:
        options["nargs"] = argument.nargs
    if argument.dest is not None:
        options["dest"] = argument.dest
    if argument.action is not None:
        options["action"] = argument.action
    elif argument.is_flag and argument.takes_no_value:
        options["action"] = "store_true"
    parser.add_argument(*argument.spec, **options)


def global_flags(*, default: object) -> argparse.ArgumentParser:
    """The flags every command takes, usable before or after the verb.

    Built twice with different defaults, which is the whole point. The main
    parser's copy defaults to `False`, because something has to put the
    attribute on the namespace. The copy attached to each subparser defaults to
    `SUPPRESS`, so an unset flag leaves no attribute behind at all and the
    subparser's result cannot write `False` over the `True` the main parser
    already parsed. One shared parent with one default gets `akit --json list`
    wrong on at least one Python version, silently and in the direction that
    prints prose at a model.
    """
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument(
        "--json",
        action="store_true",
        default=default,
        help="Print the same information as data, for a model or a script to read",
    )
    parent.add_argument(
        "--verbose",
        action="store_true",
        default=default,
        help="Say more about each decision, including the ones that changed nothing",
    )
    return parent


def build_frame() -> tuple[argparse.ArgumentParser, dict[str, argparse.ArgumentParser]]:
    """The whole command line, assembled from the one registry in `commands.py`.

    The per-command parsers are handed back beside the main one because the help
    contract is tested against what argparse will actually print, and reaching
    into `parser._actions` to find them would be a test coupled to argparse's
    internals rather than to ours.
    """
    parser = argparse.ArgumentParser(
        prog="akit",
        description=wrap(PROLOGUE),
        epilog="Next: akit help manifest, for the file every one of these reads.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=[global_flags(default=False)],
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"akit {version()}",
        help="Print the version of federated-agent-kits this `akit` came from",
    )
    parser.set_defaults(command=None)
    inherited = global_flags(default=argparse.SUPPRESS)
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    per_command: dict[str, argparse.ArgumentParser] = {}
    for command in COMMANDS:
        subparser = subparsers.add_parser(
            command.name,
            help=command.summary,
            description=format_description(command),
            epilog=format_epilog(command),
            formatter_class=argparse.RawDescriptionHelpFormatter,
            parents=[inherited],
        )
        for argument in command.arguments:
            add_argument(subparser, argument)
        per_command[command.name] = subparser
    return parser, per_command


def build_parser() -> argparse.ArgumentParser:
    """The command line, for everything that does not need the parts separately."""
    return build_frame()[0]


def show_topic(name: str, as_json: bool, out: TextIO) -> Exit:
    """`akit help <topic>`: the four things that are not commands."""
    topic = TOPICS_BY_NAME[name]
    if as_json:
        payload = {
            "topic": topic.name,
            "summary": topic.summary,
            "body": topic.body,
            "next": topic.following,
            "see_also": list(topic.see_also),
        }
        print(json.dumps(payload, indent=2), file=out)
        return Exit.OK
    see_also = ", ".join(f"akit help {other}" for other in topic.see_also)
    print(f"{topic.name} - {topic.summary}\n", file=out)
    print(topic.body, file=out)
    if see_also:
        print(f"\nSee also: {see_also}", file=out)
    print(f"\nNext: {topic.following}", file=out)
    return Exit.OK


def dispatch(arguments: argparse.Namespace, out: TextIO) -> Exit:
    """Run the chosen verb, or say which task it is waiting for."""
    if arguments.command == "help":
        return show_topic(arguments.topic, arguments.json, out)
    command = next(entry for entry in COMMANDS if entry.name == arguments.command)
    raise NotImplementedYetError(command.name, command.task or "")


def main(
    argv: Sequence[str] | None = None,
    *,
    run_command: Callable[[argparse.Namespace, TextIO], Exit] = dispatch,
) -> int:
    """Parse, dispatch, and turn whatever came back into an exit code.

    `run_command` is injected so the mapping from an error to its number can be
    tested as itself. A refusal arriving here as a 1 is the bug this frame exists
    to make impossible, and it is not a bug any verb can be asked to prove alone.
    """
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.command is None:
        parser.print_help()
        return Exit.USAGE
    try:
        return run_command(arguments, sys.stdout)
    except AkitError as error:
        print(f"akit: {error}", file=sys.stderr)
        return error.exit_code


def run() -> None:  # pragma: no cover - the console-script shim, exercised as a subprocess
    raise SystemExit(main())


__all__ = ["TOPICS", "Exit", "build_frame", "build_parser", "main", "run", "version"]
