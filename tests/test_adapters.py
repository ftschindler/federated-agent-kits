"""The adapter contract, parametrised over every registered adapter, plus detection.

The point of this file is that adding a harness means adding a file and a
registration line and nothing else (DESIGN.md section 3, rule 7). The way it
earns that is by being written against `ADAPTERS` rather than against
`opencode` and `copilot-vscode` by name: a fourth adapter is tested by existing, and
the specification a stranger writes one from: `docs/adding-an-adapter.md` says how
to answer the seven questions, and every assertion here holds for the pi adapter
somebody wrote from that page without touching this file.

The fixture adapter at the bottom is the half the registry cannot supply. Every
adapter shipped for 1.0 is a `POINTED` or `DIRECTORY` harness with a machine,
so shape three and the machineless case would otherwise be untested interface
until T6 and T8.
"""

from __future__ import annotations

from pathlib import Path

import pi_adapter
import pytest

from federated_agent_kits import adapters
from federated_agent_kits.adapters import Adapter, Destination, RuleShape
from federated_agent_kits.adapters.adapter import git_root
from federated_agent_kits.manifest import Kind, Scope

pytestmark = pytest.mark.unit

#: Every adapter the contract holds for: the registered ones, plus the pi
#: adapter written from `docs/adding-an-adapter.md` and registered nowhere. The
#: guide's claim is that a stranger can write one from it, and this is where
#: that claim is checked: the fixture meets the same assertions, unmodified,
#: that the shipped three do.
UNDER_CONTRACT: tuple[Adapter, ...] = (*adapters.ADAPTERS, pi_adapter.ADAPTER)

EVERY = pytest.mark.parametrize("adapter", UNDER_CONTRACT, ids=lambda adapter: adapter.name)
SHIPPED = pytest.mark.parametrize("adapter", adapters.ADAPTERS, ids=lambda adapter: adapter.name)
ON_A_MACHINE = pytest.mark.parametrize(
    "adapter",
    [adapter for adapter in UNDER_CONTRACT if adapter.has_a_machine],
    ids=lambda adapter: adapter.name,
)


class TestTheContractEveryAdapterKeeps:
    @EVERY
    def test_it_has_a_name_a_summary_and_a_rule_shape(self, adapter: Adapter):
        assert adapter.name
        assert adapter.summary
        assert adapter.rule_shape in set(RuleShape)

    @SHIPPED
    def test_a_shipped_adapter_is_registered_under_its_own_name(self, adapter: Adapter):
        assert adapters.BY_NAME[adapter.name] is adapter

    @EVERY
    def test_every_declared_path_is_relative_and_posix(self, adapter: Adapter):
        for offered in adapter.destinations.values():
            for destination in offered:
                for declared in destination.directories:
                    assert not Path(declared).is_absolute()
                    assert "\\" not in declared

    @EVERY
    def test_it_reads_everywhere_it_writes(self, adapter: Adapter):
        for offered in adapter.destinations.values():
            for destination in offered:
                assert destination.write is None or destination.write in destination.directories

    @EVERY
    def test_a_pointer_exists_exactly_when_the_shape_is_pointed(self, adapter: Adapter):
        assert bool(adapter.pointer) is (adapter.rule_shape is RuleShape.POINTED)

    @EVERY
    def test_a_harness_with_a_machine_says_how_to_find_it(self, adapter: Adapter):
        assert bool(adapter.evidence) is adapter.has_a_machine

    @EVERY
    def test_a_project_anchor_answers_nothing_where_there_is_no_project(self, adapter: Adapter, tmp_path: Path):
        """The half of question 6 that holds whatever the harness anchors on.

        An anchor that fell back to the directory it was asked about would make
        every directory on the disk a project, and a render outside a repository
        would write wherever it happened to be run. What the anchor then *finds*
        differs per harness - the git root for the shipped three, a `.pi`
        directory for pi - so that half is each adapter's own test.
        """
        assert adapter.anchor(tmp_path) is None

    @SHIPPED
    def test_a_shipped_adapter_anchors_on_the_worktree_root(self, adapter: Adapter, tmp_path: Path):
        (tmp_path / ".git").mkdir()

        assert adapter.anchor(tmp_path) == tmp_path


class TestDecliningAKindIsAnAnswer:
    @SHIPPED
    def test_every_adapter_shipped_for_now_declines_agents(self, adapter: Adapter):
        assert not adapter.takes(Kind.AGENT)
        assert Kind.AGENT not in adapter.kinds

    @EVERY
    def test_a_declined_kind_has_no_target_and_crashes_nothing(self, adapter: Adapter, tmp_path: Path):
        for scope in Scope:
            assert adapter.destination(Kind.AGENT, scope) is None
            assert adapter.target(Kind.AGENT, scope, "reviewer", tmp_path) is None

    @EVERY
    def test_the_agent_questions_are_carried_even_though_the_kind_is_declined(self, adapter: Adapter):
        assert adapter.agent_frontmatter == {}
        assert adapter.agent_tools == {}


class TestWhereAPartWouldLand:
    @EVERY
    def test_a_skill_is_a_directory_under_the_written_one(self, adapter: Adapter, tmp_path: Path):
        destination = adapter.destination(Kind.SKILL, Scope.PROJECT)
        assert destination is not None and destination.write is not None

        target = adapter.target(Kind.SKILL, Scope.PROJECT, "writing", tmp_path)

        assert target == tmp_path.joinpath(*destination.write.split("/"), "writing")

    @EVERY
    def test_a_rule_is_a_file_named_after_it_unless_the_harness_shares_one(self, adapter: Adapter, tmp_path: Path):
        """Two answers, because the third rule shape has no file of its own.

        A shared-file harness answers with the host file, and which bytes inside
        it belong to this rule is the marker block's business rather than the
        path's (DESIGN.md section 7). Asserting one filename for every adapter
        would be asserting that no adapter is ever the third shape, which
        opencode now is.
        """
        destination = adapter.destination(Kind.RULE, Scope.PROJECT)
        assert destination is not None and destination.write is not None

        target = adapter.target(Kind.RULE, Scope.PROJECT, "prose-style", tmp_path)

        assert target is not None
        if adapter.shape(Kind.RULE, Scope.PROJECT) is RuleShape.SHARED_FILE:
            assert target == tmp_path.joinpath(*destination.write.split("/"))
        else:
            assert target.name == f"prose-style{adapter.suffix(Kind.RULE, Scope.PROJECT)}"

    def test_the_two_scopes_do_not_write_to_one_place(self, tmp_path: Path):
        for adapter in adapters.ADAPTERS:
            for kind in adapter.kinds:
                mine = adapter.target(kind, Scope.USER, "writing", tmp_path / "home")
                theirs = adapter.target(kind, Scope.PROJECT, "writing", tmp_path / "repo")
                assert mine != theirs

    def test_one_skill_wanted_by_both_harnesses_is_one_copy(self, tmp_path: Path):
        # The reason `copilot-vscode` writes `.agents/skills/` rather than its
        # own directory: Copilot reads the same one opencode does, so the bytes
        # and the path both agree and DESIGN.md section 7's preference for one
        # copy is the ordinary case rather than the lucky one. The cloud agent
        # reads it too, which is what makes naming that harness commit the
        # skills every other one was reading privately.
        for scope in Scope:
            written = {adapter.target(Kind.SKILL, scope, "writing", tmp_path) for adapter in adapters.ADAPTERS}

            assert written - {None} == {tmp_path / ".agents" / "skills" / "writing"}

    def test_a_rule_wanted_by_several_harnesses_is_not_one_copy(self, tmp_path: Path):
        # A rule is translated per harness, so the shape decides the path. The
        # three harnesses that read `AGENTS.md` agree on it by default, which is
        # the point of that default; the two Cursor harnesses agree on
        # `.cursor/rules/` because they read the same files from the same
        # checkout. Nothing lands in `.github/instructions/` unless a manifest
        # asks for it, which is what the next test is about.
        written = {adapter.target(Kind.RULE, Scope.PROJECT, "prose-style", tmp_path) for adapter in adapters.ADAPTERS}

        assert written == {
            tmp_path / "AGENTS.md",
            tmp_path / ".cursor" / "rules" / "prose-style.mdc",
        }

    def test_the_copilot_harnesses_both_offer_the_instructions_door(self, tmp_path: Path):
        # The cost of the default above: an `applyTo` glob exists only in the
        # first shape, so a rule that wants one has somewhere to go in both of
        # the harnesses that read that directory.
        chosen = {Kind.RULE: "instructions"}
        written = {
            adapters.BY_NAME[name].choosing(chosen).target(Kind.RULE, Scope.PROJECT, "prose-style", tmp_path)
            for name in ("copilot-vscode", "copilot-ci")
        }

        assert written == {tmp_path / ".github" / "instructions" / "prose-style.instructions.md"}


class TestDetection:
    def test_a_harness_that_left_nothing_here_is_not_detected(self, tmp_path: Path):
        assert adapters.detected(tmp_path) == ()

    @ON_A_MACHINE
    def test_the_obvious_evidence_is_enough(self, adapter: Adapter, tmp_path: Path):
        tmp_path.joinpath(*adapter.evidence[0].split("/")).mkdir(parents=True)

        assert adapter.detected(tmp_path)

    @ON_A_MACHINE
    def test_an_unusual_place_is_enough_too(self, adapter: Adapter, tmp_path: Path):
        tmp_path.joinpath(*adapter.evidence[-1].split("/")).mkdir(parents=True)

        assert adapter.detected(tmp_path)

    def test_a_harness_with_no_machine_is_never_detected(self, tmp_path: Path):
        for adapter in adapters.ADAPTERS:
            if adapter.has_a_machine:
                continue
            for kind in adapter.kinds:
                destination = adapter.destination(kind, Scope.PROJECT)
                assert destination is not None
                assert destination.write is not None
                tmp_path.joinpath(*destination.write.split("/")).mkdir(parents=True, exist_ok=True)

            assert not adapter.detected(tmp_path)
            assert adapter.evidence == ()

    def test_detection_never_asks_what_a_repository_contains(self, tmp_path: Path):
        for directory in (".github/instructions", ".agents/skills", ".opencode", ".vscode"):
            tmp_path.joinpath("repo", *directory.split("/")).mkdir(parents=True)

        assert adapters.detected(tmp_path / "home") == ()


class TestTheHarnessList:
    def test_detected_expands_to_whatever_this_machine_has(self, tmp_path: Path):
        (tmp_path / ".vscode").mkdir()

        chosen, unknown, _ = adapters.expand(["detected"], tmp_path)

        assert [adapter.name for adapter in chosen] == ["copilot-vscode"]
        assert unknown == ()

    def test_a_named_harness_arrives_whether_or_not_this_machine_has_it(self, tmp_path: Path):
        chosen, unknown, _ = adapters.expand(["opencode"], tmp_path)

        assert [adapter.name for adapter in chosen] == ["opencode"]
        assert not adapters.BY_NAME["opencode"].detected(tmp_path)
        assert unknown == ()

    def test_naming_one_does_not_cost_you_the_others(self, tmp_path: Path):
        (tmp_path / ".vscode").mkdir()

        chosen, _, _ = adapters.expand(["detected", "opencode"], tmp_path)

        assert sorted(adapter.name for adapter in chosen) == ["copilot-vscode", "opencode"]

    def test_a_harness_both_named_and_detected_is_one_harness(self, tmp_path: Path):
        (tmp_path / ".vscode").mkdir()

        chosen, _, _ = adapters.expand(["detected", "copilot-vscode", "copilot-vscode"], tmp_path)

        assert [adapter.name for adapter in chosen] == ["copilot-vscode"]

    def test_a_name_no_adapter_answers_to_comes_back_rather_than_raising(self, tmp_path: Path):
        chosen, unknown, _ = adapters.expand(["opencode", "emacs", "emacs"], tmp_path)

        assert [adapter.name for adapter in chosen] == ["opencode"]
        assert unknown == ("emacs",)

    def test_an_empty_list_renders_for_nobody(self, tmp_path: Path):
        assert adapters.expand([], tmp_path) == ((), (), ())


class TestChoosingBetweenTheDestinationsAHarnessOffers:
    """DESIGN.md section 6: a manifest picks a door, and the adapter is what knows the doors."""

    def test_a_harness_with_one_destination_offers_no_choice(self):
        assert adapters.BY_NAME["opencode"].variants(Kind.RULE) == ()

    def test_a_harness_with_several_names_them_default_first(self):
        assert adapters.BY_NAME["copilot-ci"].variants(Kind.RULE) == ("agents-md", "instructions")

    def test_choosing_nothing_is_the_adapter_untouched(self, tmp_path: Path):
        adapter = adapters.BY_NAME["copilot-ci"]

        assert adapter.choosing({}) is adapter

    def test_choosing_one_puts_it_first_and_carries_its_shape(self, tmp_path: Path):
        chosen = adapters.BY_NAME["copilot-ci"].choosing({Kind.RULE: "instructions"})

        assert chosen.shape(Kind.RULE, Scope.PROJECT) is RuleShape.DIRECTORY
        assert chosen.suffix(Kind.RULE, Scope.PROJECT) == ".instructions.md"
        assert chosen.frontmatter(Kind.RULE, Scope.PROJECT) != {}
        assert chosen.orders(Kind.RULE, Scope.PROJECT) is False
        assert chosen.region(Kind.RULE, Scope.PROJECT, "prose-style") is None

    def test_the_default_is_the_shared_file_and_keeps_the_order_promise(self):
        adapter = adapters.BY_NAME["copilot-ci"]

        assert adapter.shape(Kind.RULE, Scope.PROJECT) is RuleShape.SHARED_FILE
        assert adapter.orders(Kind.RULE, Scope.PROJECT) is True
        assert adapter.region(Kind.RULE, Scope.PROJECT, "prose-style") == "prose-style"

    def test_a_choice_that_only_one_scope_has_leaves_the_other_on_its_default(self, tmp_path: Path):
        """`variants` is a union across scopes, so a name may be missing from one of them.

        Copilot in VS Code keeps user skills in `.copilot/skills` and a project's
        in `.github/skills`, and neither name means anything in the other scope.
        """
        chosen = adapters.BY_NAME["copilot-vscode"].choosing({Kind.SKILL: "github"})

        assert chosen.target(Kind.SKILL, Scope.PROJECT, "writing", tmp_path) == tmp_path / ".github/skills/writing"
        assert chosen.target(Kind.SKILL, Scope.USER, "writing", tmp_path) == tmp_path / ".agents/skills/writing"

    def test_the_doors_not_chosen_are_still_read_from(self):
        """Choosing where to write narrows nothing about where a source may have left a kit."""
        chosen = adapters.BY_NAME["copilot-ci"].choosing({Kind.SKILL: "github"})
        offered = chosen.offers(Kind.SKILL, Scope.PROJECT)

        assert offered[0].variant == "github"
        assert sorted(door.variant for door in offered) == ["agents", "claude", "github"]

    def test_a_name_no_adapter_offers_comes_back_rather_than_being_guessed_at(self, tmp_path: Path):
        chosen, unknown, unoffered = adapters.expand(["copilot-ci"], tmp_path, {"copilot-ci": {Kind.RULE: "nonsense"}})

        assert unknown == ()
        assert [str(door) for door in unoffered] == ['copilot-ci sends rules through "nonsense"']
        assert chosen[0].shape(Kind.RULE, Scope.PROJECT) is RuleShape.SHARED_FILE

    def test_a_door_named_for_a_harness_that_is_not_in_the_list_is_nobody_s_business(self, tmp_path: Path):
        _, _, unoffered = adapters.expand(["opencode"], tmp_path, {"copilot-ci": {Kind.RULE: "nonsense"}})

        assert unoffered == ()

    def test_every_offered_door_is_named_and_named_once(self):
        """The contract that makes a choice writable: no two doors share a name, and none is blank."""
        for adapter in adapters.ADAPTERS:
            for offered in adapter.destinations.values():
                names = [door.variant for door in offered]
                assert len(offered) == 1 or all(names)
                assert len(names) == len(set(names))


class TestWhatDiscoveryIsTold:
    def test_the_directories_of_every_adapter_are_offered_not_only_the_detected_ones(self):
        declared = adapters.source_directories(Kind.SKILL)

        assert ".agents/skills" in declared
        assert ".claude/skills" in declared
        assert ".opencode/skills" in declared

    def test_a_directory_two_adapters_both_read_is_offered_once(self):
        declared = adapters.source_directories(Kind.SKILL)

        assert len(declared) == len(set(declared))

    def test_a_declined_kind_contributes_nothing(self):
        assert adapters.source_directories(Kind.AGENT) == ()

    def test_the_union_of_kinds_is_in_the_order_kind_declares_them(self):
        assert adapters.kinds_taken(adapters.ADAPTERS) == (Kind.SKILL, Kind.RULE)

    def test_no_adapters_take_nothing(self):
        assert adapters.kinds_taken(()) == ()


#: The two answers the shipped adapters do not give: rules as one shared file,
#: and a harness that is never on this machine. Registered only here, which is
#: also the shape T10's "write one from the guide" test takes.
SHARED = Adapter(
    name="fixture-shared",
    summary="a harness that takes rules as marker blocks in one file it does not own",
    has_a_machine=False,
    destinations={(Kind.RULE, Scope.PROJECT): (Destination(write="AGENTS.md"),)},
    rule_shape=RuleShape.SHARED_FILE,
)


class TestTheAnswersNoShippedAdapterGives:
    def test_a_shared_file_harness_answers_with_the_file(self, tmp_path: Path):
        assert SHARED.target(Kind.RULE, Scope.PROJECT, "prose-style", tmp_path) == tmp_path / "AGENTS.md"

    def test_a_harness_with_no_machine_is_never_detected(self, tmp_path: Path):
        tmp_path.joinpath("AGENTS.md").write_text("", encoding="utf-8")

        assert not SHARED.detected(tmp_path)

    def test_a_kind_it_takes_in_one_scope_only(self, tmp_path: Path):
        assert SHARED.takes(Kind.RULE)
        assert SHARED.target(Kind.RULE, Scope.USER, "prose-style", tmp_path) is None

    def test_a_destination_that_receives_nothing_still_lists_what_it_reads(self):
        destination = Destination(write=None, read=(".agents/skills",))

        assert destination.directories == (".agents/skills",)

    def test_the_default_anchor_is_the_worktree_root(self, tmp_path: Path):
        (tmp_path / ".git").mkdir()
        (tmp_path / "package").mkdir()

        assert git_root(tmp_path / "package") == tmp_path
