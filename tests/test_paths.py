"""What a path means when this tool writes it down.

Two functions and a decision each. `located` is the one that caused an incident:
resolving a render target through a symlink recorded somebody's git working tree
as a file `akit` owned, and the next withdrawal deleted 23 files inside it. The
tests below are mostly about the difference between answering "where does this
lead" and "what is this called", which is invisible until a link is involved.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from links import really_linked

from federated_agent_kits.paths import located, under

pytestmark = pytest.mark.unit


class TestLocating:
    def test_a_relative_path_becomes_an_absolute_one(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.chdir(tmp_path)

        assert located(Path("skills") / "writing") == Path.cwd() / "skills" / "writing"

    def test_a_path_that_climbs_is_tidied(self, tmp_path: Path):
        assert located(tmp_path / "skills" / ".." / "rules") == tmp_path / "rules"

    def test_one_that_is_already_tidy_is_unchanged(self, tmp_path: Path):
        assert located(tmp_path / "skills") == tmp_path / "skills"

    def test_a_link_is_not_followed_to_wherever_it_leads(self, tmp_path: Path):
        elsewhere = tmp_path / "checkout"
        elsewhere.mkdir()
        link = tmp_path / "linked"
        really_linked(link, elsewhere)

        assert located(link / "SKILL.md") == link / "SKILL.md"
        assert located(link / "SKILL.md") != elsewhere / "SKILL.md"


class TestBelongingToARoot:
    def test_a_path_inside_the_root_belongs_to_it(self, tmp_path: Path):
        assert under(tmp_path / "skills" / "writing", (tmp_path,))

    def test_the_root_itself_belongs_to_it(self, tmp_path: Path):
        assert under(tmp_path, (tmp_path,))

    def test_a_path_outside_every_root_belongs_to_none_of_them(self, tmp_path: Path):
        assert not under(tmp_path / "a" / "x", (tmp_path / "b", tmp_path / "c"))

    def test_any_one_root_is_enough(self, tmp_path: Path):
        assert under(tmp_path / "b" / "x", (tmp_path / "a", tmp_path / "b"))

    def test_naming_no_root_at_all_asks_nothing(self, tmp_path: Path):
        assert under(tmp_path / "anywhere", ())

    def test_a_sibling_whose_name_starts_the_same_is_not_inside(self, tmp_path: Path):
        assert not under(tmp_path / "skills-mine", (tmp_path / "skills",))
