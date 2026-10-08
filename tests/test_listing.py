"""`akit list`, as a survey: what it found, what it could not, and what it prints.

A path source rather than a clone throughout, so this stays in the `unit` layer
and needs neither git nor a network. What a path source costs is the pin and the
cache, and both of those are T3's and have their own tests; what is under test
here is the join between the manifests, the walk, the adapters and the record.

The fixture is a realistic setup rather than a minimal one, because almost every
interesting case in T4 is about two things being true at once: two scopes, two
harnesses, a collision, a source that is not there, and a kit that is not in the
source it was asked for.
"""

from __future__ import annotations

import argparse
import io
import json
import textwrap
from pathlib import Path

import pytest

from federated_agent_kits import listing, record
from federated_agent_kits.cli import dispatch
from federated_agent_kits.exits import Exit
from federated_agent_kits.manifest import Kind, Scope, Subscription

pytestmark = pytest.mark.unit


def build(root: Path, layout: dict[str, str]) -> Path:
    for relative, text in layout.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


@pytest.fixture
def kits(tmp_path: Path) -> Path:
    """A source holding one skill, one rule, and a second skill for the collision."""
    return build(
        tmp_path / "kits",
        {
            "skills/writing/SKILL.md": "# writing",
            "skills/writing/references/style.md": "# style",
            "skills/fkb/SKILL.md": "# fkb",
            "rules/prose-style.md": "# prose",
            "agents/reviewer.md": "# reviewer",
        },
    )


@pytest.fixture
def home(tmp_path: Path) -> Path:
    """A machine with opencode on it and no VS Code."""
    house = tmp_path / "home"
    (house / ".config" / "opencode").mkdir(parents=True)
    return house


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    return root


def manifest_at(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    return path


def survey(repository: Path, home: Path, tmp_path: Path, user: str | None = None) -> listing.Inventory:
    user_path = tmp_path / "config" / "manifest.yaml"
    if user is not None:
        manifest_at(user_path, user)
    return listing.survey(
        repository,
        home=home,
        user_path=user_path,
        cache_root=tmp_path / "cache",
        state_root=tmp_path / "state",
    )


def printed(inventory: listing.Inventory) -> str:
    out = io.StringIO()
    listing.text(inventory, out)
    return out.getvalue()


class TestASubscriptionThatResolves:
    def test_it_names_the_source_the_part_and_where_each_harness_would_take_it(
        self, repository: Path, home: Path, kits: Path, tmp_path: Path
    ):
        manifest_at(repository / ".akit.yaml", f"version: 1\nskills:\n  {kits}: [writing]\n")

        inventory = survey(repository, home, tmp_path)

        (line,) = inventory.lines
        assert line.problem is None
        assert line.where == kits
        (found,) = line.found
        assert (found.name, found.relative) == ("writing", "skills/writing")
        assert [target.harness for target in found.targets] == ["opencode"]
        assert found.targets[0].path == repository / ".agents" / "skills" / "writing"

    def test_a_part_that_was_never_rendered_says_so(self, repository: Path, home: Path, kits: Path, tmp_path: Path):
        manifest_at(repository / ".akit.yaml", f"version: 1\nskills:\n  {kits}: [writing]\n")

        inventory = survey(repository, home, tmp_path)

        assert inventory.lines[0].found[0].targets[0].rendered is False
        assert "not rendered" in printed(inventory)

    def test_a_part_the_record_explains_is_rendered(self, repository: Path, home: Path, kits: Path, tmp_path: Path):
        manifest_at(repository / ".akit.yaml", f"version: 1\nskills:\n  {kits}: [writing]\n")
        written = repository / ".agents" / "skills" / "writing" / "SKILL.md"
        build(tmp_path / "state", {record.RECORD: ""})
        (tmp_path / "state" / record.RECORD).write_text(
            json.dumps({"version": 1, "written": [{"path": str(written), "digest": "sha256:0"}]}),
            encoding="utf-8",
        )

        inventory = survey(repository, home, tmp_path)

        assert inventory.lines[0].found[0].targets[0].rendered is True

    def test_a_rename_renders_under_the_new_name_and_remembers_the_old_one(
        self, repository: Path, home: Path, kits: Path, tmp_path: Path
    ):
        manifest_at(
            repository / ".akit.yaml",
            f"version: 1\nskills:\n  {kits}:\n    name: writing\n    as: house-style\n",
        )

        found = survey(repository, home, tmp_path).lines[0].found[0]

        assert (found.name, found.found_as) == ("house-style", "writing")
        assert found.targets[0].path.name == "house-style"

    def test_a_wildcard_lists_everything_of_that_kind(self, repository: Path, home: Path, kits: Path, tmp_path: Path):
        manifest_at(repository / ".akit.yaml", f'version: 1\nskills:\n  {kits}: ["*"]\n')

        found = survey(repository, home, tmp_path).lines[0].found

        assert sorted(part.name for part in found) == ["fkb", "writing"]

    def test_a_rule_lands_in_the_file_its_harness_shares_with_you(
        self, repository: Path, home: Path, kits: Path, tmp_path: Path
    ):
        manifest_at(repository / ".akit.yaml", f"version: 1\nrules:\n- {kits}: prose-style\n")

        target = survey(repository, home, tmp_path).lines[0].found[0].targets[0]

        assert target.path == repository / "AGENTS.md"

    def test_the_two_scopes_render_to_two_places(self, repository: Path, home: Path, kits: Path, tmp_path: Path):
        manifest_at(repository / ".akit.yaml", f"version: 1\nskills:\n  {kits}: [writing]\n")

        inventory = survey(repository, home, tmp_path, user=f"version: 1\nskills:\n  {kits}: [fkb]\n")

        mine = inventory.of_scope(Scope.USER)[0].found[0].targets[0].path
        theirs = inventory.of_scope(Scope.PROJECT)[0].found[0].targets[0].path
        assert mine == home / ".agents" / "skills" / "fkb"
        assert theirs == repository / ".agents" / "skills" / "writing"


class TestAKindNobodyTakes:
    def test_an_agent_subscription_resolves_and_lands_nowhere(
        self, repository: Path, home: Path, kits: Path, tmp_path: Path
    ):
        manifest_at(repository / ".akit.yaml", f"version: 1\nagents:\n  {kits}: [reviewer]\n")

        inventory = survey(repository, home, tmp_path)

        (found,) = inventory.lines[0].found
        assert found.name == "reviewer"
        assert found.targets == ()
        assert "no harness in this scope takes agents" in printed(inventory)


class TestFailuresAreLinesRatherThanAnEnding:
    def test_a_source_this_machine_does_not_have_is_one_line_and_the_rest_still_print(
        self, repository: Path, home: Path, kits: Path, tmp_path: Path
    ):
        missing = tmp_path / "not-here"
        manifest_at(
            repository / ".akit.yaml",
            f"version: 1\nskills:\n  {kits}: [writing]\n  {missing}: [other]\n",
        )

        inventory = survey(repository, home, tmp_path)

        good, bad = inventory.lines
        assert good.problem is None
        assert bad.problem is not None and str(missing) in bad.problem
        assert bad.where is None and bad.found == ()

    def test_a_kit_that_is_not_in_its_source_says_which_kit(
        self, repository: Path, home: Path, kits: Path, tmp_path: Path
    ):
        manifest_at(repository / ".akit.yaml", f"version: 1\nskills:\n  {kits}: [typo]\n")

        problem = survey(repository, home, tmp_path).lines[0].problem

        assert problem is not None and '"typo"' in problem

    def test_a_source_key_that_is_not_a_source_is_a_line_too(self, repository: Path, home: Path, tmp_path: Path):
        manifest_at(repository / ".akit.yaml", "version: 1\nskills:\n  https://x.test/a.zip: [writing]\n")

        assert survey(repository, home, tmp_path).lines[0].problem is not None

    def test_an_empty_source_is_reported_rather_than_silently_nothing(
        self, repository: Path, home: Path, tmp_path: Path
    ):
        empty = tmp_path / "empty"
        empty.mkdir()
        manifest_at(repository / ".akit.yaml", f'version: 1\nskills:\n  {empty}: ["*"]\n')

        problem = survey(repository, home, tmp_path).lines[0].problem

        assert problem is not None and "anything" in problem


class TestNameCollisions:
    def test_one_name_wanted_by_two_subscriptions_is_named_with_its_fix(
        self, repository: Path, home: Path, kits: Path, tmp_path: Path
    ):
        manifest_at(repository / ".akit.yaml", f"version: 1\nskills:\n  {kits}: [writing]\n")

        inventory = survey(repository, home, tmp_path, user=f"version: 1\nskills:\n  {kits}: [writing]\n")

        (collision,) = inventory.collisions
        assert (collision.kind, collision.name) == (Kind.SKILL, "writing")
        assert len(collision.wanted_by) == 2
        assert "--as" in printed(inventory)

    def test_a_setup_without_one_says_none(self, repository: Path, home: Path, kits: Path, tmp_path: Path):
        manifest_at(repository / ".akit.yaml", f"version: 1\nskills:\n  {kits}: [writing]\n")

        inventory = survey(repository, home, tmp_path)

        assert inventory.collisions == ()
        assert "none" in printed(inventory)


class TestTheHarnessReport:
    def test_a_detected_harness_and_an_absent_one_are_both_reported(self, repository: Path, home: Path, tmp_path: Path):
        manifest_at(repository / ".akit.yaml", "version: 1\n")

        inventory = survey(repository, home, tmp_path)

        by_name = {entry.name: entry for entry in inventory.harnesses}
        assert by_name["opencode"].detected is True
        assert by_name["copilot-vscode"].detected is False
        assert by_name["opencode"].kinds == (Kind.SKILL, Kind.RULE)

    def test_a_named_harness_renders_even_though_this_machine_lacks_it(
        self, repository: Path, home: Path, kits: Path, tmp_path: Path
    ):
        manifest_at(
            repository / ".akit.yaml",
            f"version: 1\nharnesses: [detected, copilot-vscode]\nskills:\n  {kits}: [writing]\n",
        )

        inventory = survey(repository, home, tmp_path)

        assert sorted(target.harness for target in inventory.lines[0].found[0].targets) == [
            "copilot-vscode",
            "opencode",
        ]

    def test_dropping_detected_pins_the_list(self, repository: Path, home: Path, kits: Path, tmp_path: Path):
        manifest_at(
            repository / ".akit.yaml",
            f"version: 1\nharnesses: [copilot-vscode]\nskills:\n  {kits}: [writing]\n",
        )

        inventory = survey(repository, home, tmp_path)

        assert [target.harness for target in inventory.lines[0].found[0].targets] == ["copilot-vscode"]
        by_name = {entry.name: entry for entry in inventory.harnesses}
        assert by_name["opencode"].detected is True
        assert by_name["opencode"].scopes == (Scope.USER,)

    def test_a_harness_no_adapter_knows_is_reported_rather_than_crashing(
        self, repository: Path, home: Path, tmp_path: Path
    ):
        manifest_at(repository / ".akit.yaml", "version: 1\nharnesses: [detected, emacs]\n")

        inventory = survey(repository, home, tmp_path)

        (unknown,) = [entry for entry in inventory.harnesses if not entry.known]
        assert unknown.name == "emacs"
        assert unknown.scopes == (Scope.PROJECT,)
        assert "no adapter answers to it" in printed(inventory)

    def test_a_harness_in_no_list_says_so(self, repository: Path, home: Path, tmp_path: Path):
        manifest_at(repository / ".akit.yaml", "version: 1\nharnesses: []\n")

        inventory = survey(repository, home, tmp_path, user="version: 1\nharnesses: []\n")

        assert "in no manifest's harness list" in printed(inventory)


class TestReadingIsNotWriting:
    def test_a_repository_that_is_its_own_source_does_not_find_its_own_output(
        self, repository: Path, home: Path, tmp_path: Path
    ):
        build(
            repository,
            {
                "skills/writing/SKILL.md": "# writing",
                ".agents/skills/writing/SKILL.md": "# writing",
            },
        )
        manifest_at(repository / ".akit.yaml", f'version: 1\nskills:\n  {repository}: ["*"]\n')
        (tmp_path / "state").mkdir(parents=True)
        (tmp_path / "state" / record.RECORD).write_text(
            json.dumps(
                {
                    "version": 1,
                    "written": [
                        {"path": str(repository / ".agents" / "skills" / "writing" / "SKILL.md"), "digest": "x"}
                    ],
                }
            ),
            encoding="utf-8",
        )

        found = survey(repository, home, tmp_path).lines[0].found

        assert [part.relative for part in found] == ["skills/writing"]


class TestAnEmptyMachine:
    def test_no_manifests_at_all_is_a_report_rather_than_an_error(self, repository: Path, home: Path, tmp_path: Path):
        inventory = survey(repository, home, tmp_path)

        assert inventory.lines == ()
        assert inventory.manifests == {Scope.USER: None, Scope.PROJECT: None}
        assert "nothing subscribed here" in printed(inventory)
        assert "no manifest found" in printed(inventory)

    def test_a_subscription_outside_a_repository_still_resolves_against_somewhere(
        self, home: Path, kits: Path, tmp_path: Path
    ):
        loose = tmp_path / "loose"
        loose.mkdir()

        inventory = survey(loose, home, tmp_path, user=f"version: 1\nskills:\n  {kits}: [writing]\n")

        assert inventory.lines[0].problem is None


class TestWhatThePinLineSays:
    def test_a_path_source_is_unpinned(self, repository: Path, home: Path, kits: Path, tmp_path: Path):
        manifest_at(repository / ".akit.yaml", f"version: 1\nskills:\n  {kits}: [writing]\n")

        assert "unpinned" in printed(survey(repository, home, tmp_path))


class TestTheSameAnswerAsData:
    def test_the_payload_carries_every_line_every_harness_and_every_collision(
        self, repository: Path, home: Path, kits: Path, tmp_path: Path
    ):
        manifest_at(repository / ".akit.yaml", f"version: 1\nskills:\n  {kits}: [writing]\n")

        payload = listing.payload(
            survey(repository, home, tmp_path, user=f"version: 1\nskills:\n  {kits}: [writing]\n")
        )

        assert json.dumps(payload)
        assert {entry["scope"] for entry in payload["subscriptions"]} == {"user", "project"}
        assert payload["subscriptions"][0]["parts"][0]["targets"][0]["harness"] == "opencode"
        assert payload["collisions"][0]["name"] == "writing"
        assert payload["manifests"]["project"] == str(repository / ".akit.yaml")

    def test_a_failed_line_carries_its_problem_and_no_parts(self, repository: Path, home: Path, tmp_path: Path):
        manifest_at(repository / ".akit.yaml", f"version: 1\nskills:\n  {tmp_path / 'gone'}: [writing]\n")

        payload = listing.payload(survey(repository, home, tmp_path))

        assert payload["subscriptions"][0]["problem"] is not None
        assert payload["subscriptions"][0]["parts"] == []
        assert payload["subscriptions"][0]["resolved_to"] is None


class TestTheReportForLinesNoPathSourceProduces:
    """A pin, a resolved commit, and a harness with no machine, built by hand.

    All three are real states `list` has to print and none of them is reachable
    from a path source, which has no pin and no commit, or from the two adapters
    shipped so far, which both have a machine. Constructing the report's input
    directly is what keeps the formatting of those three states tested before
    T8 brings the third one into the registry.
    """

    def line(self, **changed: object) -> listing.Line:
        fields: dict[str, object] = {
            "kind": Kind.SKILL,
            "source": "owner/repo",
            "pin": None,
            "name": "writing",
            "rename": None,
            "scope": Scope.PROJECT,
            "line": 3,
        }
        fields.update(changed)
        subscription = Subscription(**fields)
        return listing.Line(subscription=subscription, where=None, commit=None, found=(), problem=None)

    def printed(self, line: listing.Line, harnesses: tuple[listing.HarnessLine, ...] = ()) -> str:
        inventory = listing.Inventory(
            manifests={Scope.USER: None, Scope.PROJECT: None},
            lines=(line,),
            harnesses=harnesses,
            collisions=(),
        )
        out = io.StringIO()
        listing.text(inventory, out)
        return out.getvalue()

    def test_a_pinned_subscription_prints_its_pin(self):
        assert "pinned to 9f2c1ab" in self.printed(self.line(pin="9f2c1ab"))

    def test_an_unpinned_remote_prints_the_commit_it_resolved_to(self):
        resolved = listing.Line(
            subscription=self.line().subscription,
            where=Path("/cache/owner-repo"),
            commit="9f2c1ab",
            found=(),
            problem=None,
        )

        shown = self.printed(resolved)

        assert "at 9f2c1ab" in shown
        assert "read from" in shown

    def test_a_problem_is_printed_on_the_line_it_belongs_to(self):
        broken = listing.Line(
            subscription=self.line().subscription,
            where=None,
            commit=None,
            found=(),
            problem="this source is not in the cache",
        )

        assert "problem: this source is not in the cache" in self.printed(broken)

    def test_a_problem_that_carries_its_fix_stays_inside_its_own_line(self):
        refused = listing.Line(
            subscription=self.line().subscription,
            where=None,
            commit=None,
            found=(),
            problem="this source is not in the cache.\nRun `akit add` for it while online.",
        )

        shown = self.printed(refused).splitlines()

        assert "    problem: this source is not in the cache." in shown
        assert "      Run `akit add` for it while online." in shown

    def test_a_harness_with_no_machine_says_it_arrives_only_by_being_named(self):
        machineless = listing.HarnessLine(
            name="copilot-ci",
            summary="GitHub Copilot, in CI",
            known=True,
            detected=False,
            has_a_machine=False,
            kinds=(Kind.SKILL,),
            scopes=(Scope.PROJECT,),
        )

        assert "arrives only by being named" in self.printed(self.line(), (machineless,))

    def test_a_harness_that_takes_nothing_says_nothing_rather_than_an_empty_line(self):
        declines = listing.HarnessLine(
            name="fixture",
            summary="a harness that takes no kind at all",
            known=True,
            detected=True,
            has_a_machine=True,
            kinds=(),
            scopes=(),
        )

        assert "takes nothing" in self.printed(self.line(), (declines,))


class TestTheCommandItself:
    @pytest.fixture(autouse=True)
    def confined(self, repository: Path, home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(repository)
        monkeypatch.setattr(Path, "home", lambda: home)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
        monkeypatch.setenv("XDG_STATE_HOME", str(home / ".state"))
        monkeypatch.setenv("XDG_CACHE_HOME", str(home / ".cache"))

    def test_it_prints_the_report_and_succeeds(self):
        out = io.StringIO()

        assert listing.run(out, as_json=False) is Exit.OK
        assert "Harnesses" in out.getvalue()

    def test_json_is_json(self):
        out = io.StringIO()

        assert listing.run(out, as_json=True) is Exit.OK
        assert json.loads(out.getvalue())["harnesses"]

    def test_the_cli_reaches_it_rather_than_saying_it_is_not_implemented(self):
        out = io.StringIO()

        assert dispatch(argparse.Namespace(command="list", json=False), out) is Exit.OK
        assert "Harnesses" in out.getvalue()
