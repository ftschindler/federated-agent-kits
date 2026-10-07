"""The help contract, enforced over every registered command and topic at once.

DESIGN.md section 11 keeps everything deterministic in the CLI so the skill never
has to describe a command's output. That only holds if the help carries the
explanation, and "carries the explanation" is not something a reviewer reliably
checks on the fourteenth verb. So it is five assertions here, applied to
everything in the registry, and a new command passes them by being registered or
does not ship.
"""

from __future__ import annotations

import pytest

from federated_agent_kits.cli import build_frame, build_parser, format_description, format_epilog
from federated_agent_kits.commands import COMMANDS, TOPICS, TOPICS_BY_NAME, Command, Topic

pytestmark = pytest.mark.unit

A_PARAGRAPH = 160  # characters: shorter than this is a sentence wearing a paragraph's hat

#: A command that touches the disk says so with one of these; a command that does
#: not says "writes nothing" or "changes nothing", which these also catch.
PUTS_SOMETHING_ON_DISK = ("write", "copies", "edits", "removes", "deletes", "changes")


def subparser_help(name: str) -> str:
    """The help text argparse actually prints for one verb."""
    return build_frame()[1][name].format_help()


@pytest.mark.parametrize("command", COMMANDS, ids=lambda command: command.name)
def test_the_summary_is_one_sentence(command: Command) -> None:
    assert command.summary
    assert command.summary[0].isupper()
    assert ". " not in command.summary, "the summary is one sentence; the rest goes in `writes`"
    assert not command.summary.endswith("."), "the full stop is added where it is printed"


@pytest.mark.parametrize("command", COMMANDS, ids=lambda command: command.name)
def test_it_says_what_it_writes_and_what_it_never_writes(command: Command) -> None:
    said = command.writes.lower()
    assert len(command.writes) > A_PARAGRAPH
    assert any(verb in said for verb in PUTS_SOMETHING_ON_DISK), "say what lands on disk, or that nothing does"
    assert any(word in said for word in ("never", "nothing", "not")), (
        "a paragraph that only says what it writes leaves the dangerous half unsaid"
    )


@pytest.mark.parametrize("command", COMMANDS, ids=lambda command: command.name)
def test_there_is_at_least_one_worked_example(command: Command) -> None:
    assert command.examples
    for example in command.examples:
        assert example.startswith(f"akit {command.name}")
        assert "<" not in example, "a placeholder is not a worked example"


@pytest.mark.parametrize("command", COMMANDS, ids=lambda command: command.name)
def test_every_argument_is_documented_in_one_line(command: Command) -> None:
    for argument in command.arguments:
        assert argument.help, f"{argument.spec} has no help"
        assert "\n" not in argument.help
        assert argument.help[0].isupper()


@pytest.mark.parametrize("command", COMMANDS, ids=lambda command: command.name)
def test_it_names_the_command_you_usually_run_next(command: Command) -> None:
    assert command.following
    assert not command.following.endswith(".")
    assert f"Next: {command.following}" in format_epilog(command)


@pytest.mark.parametrize("command", COMMANDS, ids=lambda command: command.name)
def test_the_printed_help_carries_all_of_it(command: Command) -> None:
    printed = subparser_help(command.name)
    assert command.summary in printed
    assert "Next:" in printed
    for example in command.examples:
        assert example in printed
    for argument in command.arguments:
        assert argument.spec[0] in printed


def test_the_top_level_help_lists_every_command() -> None:
    printed = build_parser().format_help()
    for command in COMMANDS:
        assert command.name in printed


def test_the_description_leads_with_the_sentence() -> None:
    command = COMMANDS[0]
    assert format_description(command).startswith(f"{command.summary}.")


def test_command_names_are_unique() -> None:
    names = [command.name for command in COMMANDS]
    assert len(names) == len(set(names))


@pytest.mark.parametrize("topic", TOPICS, ids=lambda topic: topic.name)
def test_every_help_topic_is_a_page_rather_than_a_sentence(topic: Topic) -> None:
    assert (topic.summary and topic.summary[0].islower()) or topic.summary[0].isupper()
    assert "\n\n" in topic.body, "a topic that fits in one paragraph belongs in a command's help"
    assert topic.following
    for other in topic.see_also:
        assert other in TOPICS_BY_NAME


def test_the_four_topics_are_the_four_things_that_are_not_commands() -> None:
    # Four, named in T1 and in DESIGN.md section 11. A fifth is a design change
    # rather than a convenience, which is why this is an equality.
    assert sorted(TOPICS_BY_NAME) == ["harnesses", "manifest", "privacy", "sources"]
