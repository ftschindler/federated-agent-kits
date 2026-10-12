"""Shared fixtures: a throwaway machine, a git environment, and a disposable agent.

The `cli` layer runs `akit` as a subprocess inside a fake home (see
`fake_home.py`), which is what makes a bug in it unable to reach the developer's
own config, cache or state directory. The `unit` layer imports the package
directly and needs none of this.

The `agent` layer goes one further and builds a real agent (see
`disposable_agent.py`): a pinned opencode in a redirected home, with this
repository's skills installed into it the way a person installs one, and a
locally built wheel its `uvx` resolves instead of the published release. On
failure the agent is preserved and a command to enter its world is printed, so a
run can be inspected by hand.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from disposable_agent import REPO_SKILLS_DIR, DisposableAgent, build_disposable_agent, build_local_wheel
from fake_home import FakeHome, build_fake_home


@pytest.fixture
def fake_home(tmp_path: Path) -> FakeHome:
    """A throwaway machine with nothing of the developer's in it."""
    return build_fake_home(tmp_path / "home")


@pytest.fixture(scope="session")
def local_wheels(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """This working tree, built once per session as a wheel `uvx` can install."""
    return build_local_wheel(tmp_path_factory.mktemp("wheels"))


class AgentFactory:
    """Builds agents and remembers them, so a failing test can be pointed at one."""

    def __init__(self, root: Path, wheels: Path) -> None:
        self.root = root
        self.wheels = wheels
        self.built: list[DisposableAgent] = []

    def __call__(self, skills_dir: Path | None = REPO_SKILLS_DIR) -> DisposableAgent:
        agent = build_disposable_agent(
            self.root / f"agent{len(self.built)}",
            skills_dir=skills_dir,
            wheels=self.wheels,
        )
        self.built.append(agent)
        return agent


@pytest.fixture
def agent_factory(tmp_path: Path, local_wheels: Path) -> AgentFactory:
    """Build a disposable agent, with this repository's kits installed by default.

    A factory rather than one fixture per shape, because the three cold sessions
    differ in what is on disk before the agent is spoken to rather than in how
    the agent is built.
    """
    return AgentFactory(tmp_path, local_wheels)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """On failure of a test that used a disposable agent, print how to enter it."""
    outcome = yield
    report = outcome.get_result()
    if report.when != "call" or not report.failed:
        return
    funcargs = getattr(item, "funcargs", {}) or {}
    factory = funcargs.get("agent_factory")
    for agent in factory.built if isinstance(factory, AgentFactory) else []:
        report.sections.append(
            (
                "Disposable agent (inspect it)",
                agent.enter_hint(reason=f"Test {item.name!r} failed."),
            )
        )
        break
