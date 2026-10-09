"""The guide, checked rather than asserted: one file, one line, and no third place.

`docs/adding-an-adapter.md` claims that adding a harness is a new module and a
line in `ADAPTERS`. Three things here are what keep that claim true rather than
hopeful.

The **diff budget** reads every module in `src/` and fails if one outside the
adapters package imports an adapter or branches on a harness name. That is rule
7 of DESIGN.md section 3, checked by CI rather than by somebody's memory: the
tempting special case is one `if adapter.name == "opencode"` in a renderer, and
the cost of it is that the next harness is no longer one file.

The **worked example** is `tests/pi_adapter.py`, a real harness written from the
guide and registered only in the suite. `test_adapters.py` runs the contract over
it unmodified; what is left here is pi's two awkward answers, the anchor that is
not the git root and the skills directory it already reads.

The **staleness check** reads the guide itself: every interface name it mentions
has to exist, every example has to parse, every keyword in an example has to be a
field, and every registered adapter has to appear in it. A guide that goes stale
in silence is worse than no guide, because it is read as current.
"""

from __future__ import annotations

import ast
import inspect
import re
from dataclasses import fields
from pathlib import Path

import pi_adapter
import pytest

from federated_agent_kits import adapters
from federated_agent_kits.adapters import ADAPTERS, Adapter, Destination, Pointer, RuleShape
from federated_agent_kits.adapters.adapter import git_root
from federated_agent_kits.manifest import Kind, Scope

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE = REPO_ROOT / "src" / "federated_agent_kits"
GUIDE = REPO_ROOT / "docs" / "adding-an-adapter.md"

#: The package every adapter lives in. A module inside it may name another
#: adapter; `__init__.py` has to, since registering them is its whole job.
ADAPTER_PACKAGE = SOURCE / "adapters"

#: Every name a harness is known by, which is what nothing outside the adapters
#: package may branch on.
HARNESS_NAMES = frozenset(adapter.name for adapter in ADAPTERS)

#: The modules a harness lives in, which is what nothing outside the registry
#: may import. The interface next to them, `adapters.adapter`, is imported
#: freely: a renderer that takes an `Adapter` is the whole point of there being
#: one.
ADAPTER_MODULES = frozenset(f"federated_agent_kits.adapters.{adapter.name.replace('-', '_')}" for adapter in ADAPTERS)


def modules_outside_the_adapters() -> list[Path]:
    """Every module in `src/` that is not an adapter or the registry."""
    return sorted(path for path in SOURCE.rglob("*.py") if ADAPTER_PACKAGE not in path.parents)


def parsed(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def imported_modules(tree: ast.Module) -> set[str]:
    """Every module name this file imports, however it spells the import."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return found


def branched_on(tree: ast.Module) -> set[str]:
    """Every string this file compares against or looks a mapping up by.

    A harness name in a docstring or in help text is prose, and `akit harness
    add copilot-ci` is an example somebody needs to read. A harness name in a
    comparison or a subscript is a special case, which is the thing the budget
    exists to catch.
    """
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            considered = [node.left, *node.comparators]
        elif isinstance(node, ast.Subscript):
            considered = [node.slice]
        elif isinstance(node, ast.Dict):
            considered = [key for key in node.keys if key is not None]
        else:
            continue
        found.update(
            element.value
            for element in considered
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        )
    return found


class TestTheDiffBudget:
    """Three places and no fourth, measured over the source rather than promised."""

    def test_nothing_outside_the_adapters_imports_one(self):
        offenders = {
            path.relative_to(REPO_ROOT).as_posix(): sorted(
                name for name in imported_modules(parsed(path)) if name in ADAPTER_MODULES
            )
            for path in modules_outside_the_adapters()
        }

        assert {path: names for path, names in offenders.items() if names} == {}

    def test_nothing_outside_the_adapters_branches_on_a_harness_name(self):
        offenders = {
            path.relative_to(REPO_ROOT).as_posix(): sorted(branched_on(parsed(path)) & HARNESS_NAMES)
            for path in modules_outside_the_adapters()
        }

        assert {path: names for path, names in offenders.items() if names} == {}

    def test_an_adapter_is_one_module_exporting_one_adapter(self):
        inside = sorted(path.name for path in ADAPTER_PACKAGE.glob("*.py"))

        assert inside == ["__init__.py", "adapter.py", "copilot_ci.py", "copilot_vscode.py", "opencode.py"]
        for adapter in ADAPTERS:
            module = parsed(ADAPTER_PACKAGE / f"{adapter.name.replace('-', '_')}.py")
            assigned = {
                target.id
                for node in ast.walk(module)
                if isinstance(node, ast.Assign)
                for target in node.targets
                if isinstance(target, ast.Name)
            }

            assert "ADAPTER" in assigned

    def test_the_budget_can_fail(self, tmp_path: Path):
        # The assertions above pass by finding nothing, which is also what they
        # would do if the search were broken. So the search is shown working on
        # a file written to breach it.
        written = tmp_path / "renderer.py"
        written.write_text(
            'from federated_agent_kits.adapters.opencode import ADAPTER\n\n\ndef go(name: str) -> bool:\n    return name == "opencode"\n',
            encoding="utf-8",
        )
        tree = parsed(written)

        assert "federated_agent_kits.adapters.opencode" in imported_modules(tree)
        assert branched_on(tree) & HARNESS_NAMES == {"opencode"}


class TestTheAdapterSomebodyWroteFromTheGuide:
    """pi's two awkward answers. The rest of its contract is in `test_adapters.py`."""

    def test_it_is_registered_nowhere(self):
        assert pi_adapter.ADAPTER.name not in adapters.BY_NAME
        assert pi_adapter.ADAPTER not in ADAPTERS

    def test_the_anchor_is_the_nearest_pi_directory_rather_than_the_git_root(self, tmp_path: Path):
        (tmp_path / ".git").mkdir()
        package = tmp_path / "packages" / "one"
        package.mkdir(parents=True)
        (package / ".pi").mkdir()

        assert pi_adapter.ADAPTER.anchor(package) == package
        assert git_root(package) == tmp_path

    def test_the_anchor_walks_up_and_gives_up_rather_than_answering_the_start(self, tmp_path: Path):
        (tmp_path / ".pi").mkdir()
        deep = tmp_path / "packages" / "one"
        deep.mkdir(parents=True)

        assert pi_adapter.ADAPTER.anchor(deep) == tmp_path
        assert pi_adapter.ADAPTER.anchor(Path(tmp_path.anchor)) is None

    def test_a_skill_lands_in_the_directory_every_harness_already_reads(self, tmp_path: Path):
        written = {
            adapter.target(Kind.SKILL, Scope.PROJECT, "writing", tmp_path)
            for adapter in (*ADAPTERS, pi_adapter.ADAPTER)
        }

        assert written == {tmp_path / ".agents" / "skills" / "writing"}

    def test_its_rules_are_the_shared_file_shape_at_both_scopes(self, tmp_path: Path):
        assert pi_adapter.ADAPTER.rule_shape is RuleShape.SHARED_FILE
        assert pi_adapter.ADAPTER.shares_the_file(Kind.RULE)
        assert pi_adapter.ADAPTER.region(Kind.RULE, "prose-style") == "prose-style"
        assert (
            pi_adapter.ADAPTER.target(Kind.RULE, Scope.USER, "prose-style", tmp_path)
            == tmp_path / ".pi" / "agent" / "AGENTS.md"
        )

    def test_it_declines_agents_like_everything_else_shipping_for_now(self):
        assert pi_adapter.ADAPTER.kinds == (Kind.SKILL, Kind.RULE)
        assert not pi_adapter.ADAPTER.takes(Kind.AGENT)


#: Where a name mentioned in the guide is looked up. A token whose first part is
#: not one of these is prose, a path or a shell command, and is nobody's to
#: resolve.
ROOTS = {
    "Adapter": Adapter,
    "adapter": Adapter,
    "Destination": Destination,
    "Pointer": Pointer,
    "RuleShape": RuleShape,
    "Kind": Kind,
    "Scope": Scope,
    "git_root": git_root,
    "nearest_pi_directory": pi_adapter.nearest_pi_directory,
    "ADAPTERS": ADAPTERS,
}

#: An inline code span, which is how the guide writes every name.
SPAN = re.compile(r"`([^`\n]+)`")

#: A dotted Python name, and nothing else: `.agents/skills` and `AGENTS.md` are
#: paths, `akit harness add` is a command, and neither is resolved.
NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")

FIELDS = {
    Adapter: {field.name for field in fields(Adapter)},
    Destination: {field.name for field in fields(Destination)},
    Pointer: {field.name for field in fields(Pointer)},
}


def mentioned_names() -> set[str]:
    text = GUIDE.read_text(encoding="utf-8")
    return {span for span in SPAN.findall(text) if NAME.match(span) and span.split(".")[0] in ROOTS}


def resolve(token: str) -> bool:
    """Whether this dotted name exists, counting a dataclass field as existing.

    A field with a `default_factory` is not a class attribute, so `getattr`
    alone would call `Adapter.pointer` a typo.
    """
    current = ROOTS[token.split(".", maxsplit=1)[0]]
    for part in token.split(".")[1:]:
        if isinstance(current, type) and part in FIELDS.get(current, set()):
            return True
        if not hasattr(current, part):
            return False
        current = getattr(current, part)
    return True


def code_blocks() -> list[str]:
    return re.findall(r"```python\n(.*?)```", GUIDE.read_text(encoding="utf-8"), flags=re.DOTALL)


class TestTheGuideCannotGoStaleInSilence:
    def test_every_interface_name_it_mentions_exists(self):
        mentioned = mentioned_names()

        assert "RuleShape.POINTED" in mentioned, "the guide stopped covering the shape with no renderer"
        assert sorted(token for token in mentioned if not resolve(token)) == []

    def test_every_example_parses(self):
        blocks = code_blocks()

        assert len(blocks) == 3
        for block in blocks:
            ast.parse(block)

    def test_every_keyword_in_an_example_is_a_real_field(self):
        written: dict[str, set[str]] = {"Adapter": set(), "Destination": set()}
        for block in code_blocks():
            for node in ast.walk(ast.parse(block)):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in written:
                    written[node.func.id].update(keyword.arg for keyword in node.keywords if keyword.arg is not None)

        assert written["Adapter"] and written["Destination"]
        assert written["Adapter"] <= FIELDS[Adapter]
        assert written["Destination"] <= FIELDS[Destination]

    def test_the_anchor_it_prints_is_the_one_the_fixture_runs(self):
        source = inspect.getsource(pi_adapter.nearest_pi_directory)

        assert source.strip() in GUIDE.read_text(encoding="utf-8")

    def test_it_names_every_adapter_a_reader_could_copy(self):
        text = GUIDE.read_text(encoding="utf-8")

        for adapter in ADAPTERS:
            assert f"`{adapter.name}`" in text
            assert f"{adapter.name.replace('-', '_')}.py" in text

    def test_it_says_which_kinds_are_declined(self):
        text = GUIDE.read_text(encoding="utf-8")

        assert "Kind.AGENT" in text
        assert adapters.kinds_taken(ADAPTERS) == (Kind.SKILL, Kind.RULE)
