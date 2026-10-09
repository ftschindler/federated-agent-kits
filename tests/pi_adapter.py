"""pi, written from `docs/adding-an-adapter.md` and registered only here.

This is the evidence behind the guide's claim that a stranger can add a harness
from it. It is a real harness with two awkward answers, a project anchor that is
not the git root and a skills directory it already reads, and it is deliberately
not in `ADAPTERS`: an adapter for a harness nobody here runs is maintenance with
no user (DESIGN.md section 4, IMPLEMENTATION.md T10).

What keeps it honest is that `test_adapters.py` parametrises the contract over
this adapter alongside the shipped three, unmodified, and that
`test_adding_an_adapter.py` asserts every name the guide mentions still exists
and that its worked anchor is this function rather than a paraphrase of it.

**Every path is a snapshot**, taken from pi's documentation as DESIGN.md section
4 recorded it: `~/.agents/skills/` and `.agents/skills/` for skills,
`~/.pi/agent/AGENTS.md` plus every `AGENTS.md` walking up for rules, and
`~/.pi/agent/agents/*.md` for agents, which only exist with a third-party
package installed and are declined here like everywhere else in 1.0.
"""

from __future__ import annotations

from pathlib import Path

from federated_agent_kits.adapters.adapter import Adapter, Destination, RuleShape
from federated_agent_kits.manifest import Kind, Scope

#: The one directory pi reads skills from that every other harness here reads
#: too, so a skill two harnesses want stays one copy.
SKILLS = ".agents/skills"

#: Rules are the third shape: one `AGENTS.md`, shared with whoever else writes
#: in it, each rule between its own markers.
PROJECT_RULES = "AGENTS.md"
USER_RULES = ".pi/agent/AGENTS.md"


def nearest_pi_directory(start: Path) -> Path | None:
    """pi's project anchor: the nearest ancestor holding a `.pi` directory."""
    for directory in (start, *start.parents):
        if (directory / ".pi").is_dir():
            return directory
    return None


ADAPTER = Adapter(
    name="pi",
    summary="pi, on this machine",
    has_a_machine=True,
    destinations={
        (Kind.SKILL, Scope.USER): Destination(write=SKILLS, read=(SKILLS,)),
        (Kind.SKILL, Scope.PROJECT): Destination(write=SKILLS, read=(SKILLS,)),
        (Kind.RULE, Scope.USER): Destination(write=USER_RULES),
        (Kind.RULE, Scope.PROJECT): Destination(write=PROJECT_RULES),
    },
    rule_shape=RuleShape.SHARED_FILE,
    orders_rules=True,
    evidence=(".pi",),
    anchor=nearest_pi_directory,
)

__all__ = ["ADAPTER", "nearest_pi_directory"]
