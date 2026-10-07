"""`akit` as a process: the exit codes a hook actually sees, and the help it prints.

The in-process tests can inject an error and watch the number come back. They
cannot catch an entry point that imports a module missing from the wheel, a
`print` that dies on a Windows console's encoding, or a verb that parses in a
test and raises on the way to `stdout`. This layer runs the real thing, inside a
fake home, and reads what came out.
"""

from __future__ import annotations

import json

import pytest
from fake_home import FakeHome

from federated_agent_kits.cli import version
from federated_agent_kits.commands import unimplemented
from federated_agent_kits.exits import Exit

pytestmark = pytest.mark.cli


def test_help_prints_the_frame(fake_home: FakeHome) -> None:
    result = fake_home.run("--help")
    assert result.returncode == Exit.OK
    assert "akit" in result.stdout
    for verb in ("list", "add", "render", "doctor", "help"):
        assert verb in result.stdout


def test_version_matches_the_installed_metadata(fake_home: FakeHome) -> None:
    result = fake_home.run("--version")
    assert result.returncode == Exit.OK
    assert result.stdout.strip() == f"akit {version()}"


def test_no_arguments_prints_the_help_and_exits_two(fake_home: FakeHome) -> None:
    result = fake_home.run()
    assert result.returncode == Exit.USAGE
    assert "<command>" in result.stdout


@pytest.mark.parametrize("verb", unimplemented())
def test_every_unlanded_verb_says_so_and_exits_two(fake_home: FakeHome, verb: str) -> None:
    result = fake_home.run(verb, *_arguments_for(verb))
    assert result.returncode == Exit.USAGE, result.stderr
    assert "not implemented yet" in result.stderr
    assert result.stdout == ""


def _arguments_for(verb: str) -> tuple[str, ...]:
    """The smallest legal invocation of a verb, so parsing is not what fails."""
    return {
        "add": ("acme/kits", "writing"),
        "remove": ("writing",),
        "harness": ("add", "opencode"),
    }.get(verb, ())


def test_an_unknown_verb_exits_two(fake_home: FakeHome) -> None:
    result = fake_home.run("summon")
    assert result.returncode == Exit.USAGE
    assert "summon" in result.stderr


@pytest.mark.parametrize("topic", ["manifest", "sources", "harnesses", "privacy"])
def test_each_help_topic_prints(fake_home: FakeHome, topic: str) -> None:
    result = fake_home.run("help", topic)
    assert result.returncode == Exit.OK
    assert result.stdout.startswith(topic)
    assert "Next:" in result.stdout


def test_a_help_topic_as_json_is_json(fake_home: FakeHome) -> None:
    result = fake_home.run("help", "sources", "--json")
    assert result.returncode == Exit.OK
    assert json.loads(result.stdout)["topic"] == "sources"


def test_nothing_was_written_into_the_house(fake_home: FakeHome) -> None:
    """A frame that only parses may not leave a file behind."""
    before = sorted(path.relative_to(fake_home.root) for path in fake_home.root.rglob("*"))
    for argv in (("--help",), ("help", "manifest"), ("list",), ("render",)):
        fake_home.run(*argv)
    after = sorted(path.relative_to(fake_home.root) for path in fake_home.root.rglob("*"))
    assert before == after
