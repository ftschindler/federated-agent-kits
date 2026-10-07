"""The walk: the fixed directories, three levels, shadowing, and our own output taken out.

No git and no network. A directory tree is all discovery has ever looked at, so
the fixtures here are directories.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from federated_agent_kits import discovery
from federated_agent_kits.manifest import Kind

pytestmark = pytest.mark.unit


def build(root: Path, layout: dict[str, str]) -> Path:
    for relative, text in layout.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


def names(found) -> list[str]:
    return sorted(part.name for part in found)


class TestWhereSkillsAreLookedFor:
    def test_a_repository_that_is_one_skill_is_a_source(self, tmp_path: Path):
        root = build(tmp_path / "writing", {"SKILL.md": "# writing"})

        found = discovery.parts(root, Kind.SKILL)

        assert [part.name for part in found] == ["writing"]
        assert found[0].path == root
        assert found[0].relative == "."

    def test_every_level_of_the_convention_resolves(self, tmp_path: Path):
        root = build(
            tmp_path / "repo",
            {
                "skills/one/SKILL.md": "a",
                "skills/category/two/SKILL.md": "b",
                "skills/category/deeper/three/SKILL.md": "c",
                "skills/.curated/four/SKILL.md": "d",
                "skills/.experimental/five/SKILL.md": "e",
                "skills/.system/six/SKILL.md": "f",
            },
        )

        assert names(discovery.parts(root, Kind.SKILL)) == ["five", "four", "one", "six", "three", "two"]

    def test_the_walk_has_a_bottom(self, tmp_path: Path):
        root = build(tmp_path / "repo", {"skills/a/b/c/toodeep/SKILL.md": "x"})

        assert discovery.parts(root, Kind.SKILL) == ()

    def test_a_directory_without_a_skill_file_is_not_a_skill(self, tmp_path: Path):
        root = build(tmp_path / "repo", {"skills/references/notes.md": "x"})

        assert discovery.parts(root, Kind.SKILL) == ()

    def test_a_skill_at_the_root_of_the_source_shadows_a_nested_one(self, tmp_path: Path):
        root = build(
            tmp_path / "repo",
            {"skills/writing/SKILL.md": "shallow", "skills/prose/writing/SKILL.md": "deep"},
        )

        found = discovery.parts(root, Kind.SKILL)

        assert [part.relative for part in found] == ["skills/writing"]

    def test_a_shadowed_part_does_not_stop_the_walk(self, tmp_path: Path):
        root = build(
            tmp_path / "repo",
            {
                "skills/writing/SKILL.md": "shallow",
                "skills/prose/writing/SKILL.md": "deep",
                "skills/prose/zzz-last/SKILL.md": "after the contest",
            },
        )

        assert names(discovery.parts(root, Kind.SKILL)) == ["writing", "zzz-last"]

    def test_a_tie_goes_to_the_directory_listed_first(self, tmp_path: Path):
        root = build(
            tmp_path / "repo",
            {
                "writing/SKILL.md": "at the root of the source",
                "skills/writing/SKILL.md": "under skills",
                "skills/zzz-last/SKILL.md": "after the contest",
            },
        )

        found = discovery.parts(root, Kind.SKILL)

        assert sorted(part.relative for part in found) == ["skills/zzz-last", "writing"]

    def test_a_vendored_dependency_is_not_a_source_of_kits(self, tmp_path: Path):
        root = build(tmp_path / "repo", {"node_modules/thing/SKILL.md": "x", ".venv/lib/SKILL.md": "y"})

        assert discovery.parts(root, Kind.SKILL) == ()


class TestWhereRulesAndAgentsAreLookedFor:
    def test_a_rule_is_a_markdown_file_and_its_stem_is_its_name(self, tmp_path: Path):
        root = build(tmp_path / "repo", {"rules/prose-style.md": "x", "rules/team/review.md": "y"})

        found = discovery.parts(root, Kind.RULE)

        assert names(found) == ["prose-style", "review"]
        assert found[0].path == root / "rules" / "prose-style.md"

    def test_an_agent_comes_from_its_own_directory(self, tmp_path: Path):
        root = build(tmp_path / "repo", {"agents/reviewer.md": "x", "rules/prose-style.md": "y"})

        assert names(discovery.parts(root, Kind.AGENT)) == ["reviewer"]

    def test_a_file_at_the_root_is_a_rule_because_the_convention_says_so(self, tmp_path: Path):
        root = build(tmp_path / "repo", {"README.md": "x"})

        assert names(discovery.parts(root, Kind.RULE)) == ["README"]

    def test_something_that_is_not_markdown_is_not_a_part(self, tmp_path: Path):
        root = build(tmp_path / "repo", {"rules/script.py": "x"})

        assert discovery.parts(root, Kind.RULE) == ()


class TestTheDirectoriesAnAdapterDeclares:
    def test_they_are_walked_as_well(self, tmp_path: Path):
        root = build(tmp_path / "repo", {".github/instructions/house.instructions.md": "x"})

        assert discovery.parts(root, Kind.RULE) == ()
        assert names(discovery.parts(root, Kind.RULE, extra_directories=[".github/instructions"])) == [
            "house.instructions"
        ]

    def test_one_that_is_not_there_is_not_an_error(self, tmp_path: Path):
        root = build(tmp_path / "repo", {"skills/one/SKILL.md": "a"})

        assert names(discovery.parts(root, Kind.SKILL, extra_directories=["nowhere/at/all"])) == ["one"]


class TestReadingIsNotWriting:
    def test_a_rendered_skill_is_not_an_input(self, tmp_path: Path):
        root = build(
            tmp_path / "repo",
            {"skills/mine/SKILL.md": "mine", ".agents/skills/theirs/SKILL.md": "rendered"},
        )
        declared = [".agents/skills"]

        both = discovery.parts(root, Kind.SKILL, extra_directories=declared)
        ours = discovery.parts(
            root,
            Kind.SKILL,
            extra_directories=declared,
            rendered=[root / ".agents" / "skills" / "theirs" / "SKILL.md"],
        )

        assert names(both) == ["mine", "theirs"]
        assert names(ours) == ["mine"]

    def test_a_rendered_rule_is_not_an_input(self, tmp_path: Path):
        root = build(tmp_path / "repo", {"rules/mine.md": "mine", "rules/rendered.md": "ours"})

        found = discovery.parts(root, Kind.RULE, rendered=[root / "rules" / "rendered.md"])

        assert names(found) == ["mine"]

    def test_a_hand_written_skill_in_the_rendered_directory_survives(self, tmp_path: Path):
        root = build(tmp_path / "repo", {".agents/skills/handwritten/SKILL.md": "mine"})

        found = discovery.parts(
            root,
            Kind.SKILL,
            extra_directories=[".agents/skills"],
            rendered=[root / ".agents" / "skills" / "something-else" / "SKILL.md"],
        )

        assert names(found) == ["handwritten"]


class TestWhatOneSubscriptionAsksFor:
    @pytest.fixture
    def source(self, tmp_path: Path) -> Path:
        return build(tmp_path / "repo", {"skills/one/SKILL.md": "a", "skills/two/SKILL.md": "b"})

    def test_a_wildcard_is_every_part_of_that_kind(self, source: Path):
        assert names(discovery.named(source, Kind.SKILL, "*")) == ["one", "two"]

    def test_a_name_is_one_part(self, source: Path):
        assert names(discovery.named(source, Kind.SKILL, "one")) == ["one"]

    def test_a_name_the_source_does_not_hold_is_empty_rather_than_an_error(self, source: Path):
        assert discovery.named(source, Kind.SKILL, "three") == ()
