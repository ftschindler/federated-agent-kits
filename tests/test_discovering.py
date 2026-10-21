"""`akit discover`: the listing that used to be reachable only by lying to `add`.

The same local repository served over `file://` as `test_subscribing.py` uses,
because this verb fetches exactly as `add` does and the half worth testing is
what it says about what it found. The `cli` layer then runs it as a subprocess,
where what it adds is the exit code and the cache being on a real disk
afterwards.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from git_environment import local_remote

from federated_agent_kits import discovering, render
from federated_agent_kits.cli import build_parser, dispatch
from federated_agent_kits.exits import Exit, UsageError
from federated_agent_kits.manifest import Kind

pytestmark = pytest.mark.unit

LAYOUT = {
    "skills/writing/SKILL.md": "---\nname: writing\ndescription: How to write a sentence\n---\n\n# writing\n",
    "skills/fkb/SKILL.md": "# fkb, with no header at all\n",
    "rules/prose-style.md": "---\ndescription: Present tense,\n  always\n---\n\nWrite in the present tense.\n",
    "agents/reviewer.md": "Review it.\n",
}


@pytest.fixture
def places(tmp_path: Path) -> render.Directories:
    return render.Directories(
        home=tmp_path / "home",
        user_manifest=tmp_path / "config" / "manifest.yaml",
        cache=tmp_path / "cache",
        state=tmp_path / "state",
    )


@pytest.fixture
def remote(tmp_path: Path) -> str:
    return local_remote(tmp_path / "remote", LAYOUT)


def look(source: str, places: render.Directories, start: Path, **flags: object) -> discovering.Holding:
    return discovering.look(
        source,
        start=start,
        cache_root=places.cache,
        state_root=places.state,
        **flags,  # ty: ignore[invalid-argument-type]
    )


def printed(holding: discovering.Holding, *, verbose: bool = False) -> str:
    out = io.StringIO()
    discovering.text(holding, out, verbose=verbose)
    return out.getvalue()


class TestWhatItFinds:
    def test_it_lists_every_kind_the_source_holds(self, remote: str, places: render.Directories, tmp_path: Path):
        holding = look(remote, places, tmp_path)

        assert [(str(offer.kind), offer.name) for offer in holding.offers] == [
            ("skills", "fkb"),
            ("skills", "writing"),
            ("rules", "prose-style"),
            ("agents", "reviewer"),
        ]

    def test_kind_narrows_it_to_one(self, remote: str, places: render.Directories, tmp_path: Path):
        holding = look(remote, places, tmp_path, kind=Kind.RULE)

        assert [offer.name for offer in holding.offers] == ["prose-style"]

    def test_it_carries_the_path_inside_the_source(self, remote: str, places: render.Directories, tmp_path: Path):
        holding = look(remote, places, tmp_path)

        assert {offer.name: offer.relative for offer in holding.offers}["writing"] == "skills/writing"

    def test_it_reads_the_one_line_a_part_says_about_itself(
        self, remote: str, places: render.Directories, tmp_path: Path
    ):
        said = {offer.name: offer.description for offer in look(remote, places, tmp_path).offers}

        assert said["writing"] == "How to write a sentence"
        assert said["prose-style"] == "Present tense, always", "a folded line is one sentence again"
        assert said["fkb"] is None, "a part with no frontmatter describes itself with silence"
        assert said["reviewer"] is None

    def test_a_header_it_cannot_read_is_a_part_without_a_description(self, tmp_path: Path, places: render.Directories):
        broken = local_remote(tmp_path / "broken", {"rules/odd.md": "---\ndescription: [unclosed\n---\n\nbody\n"})

        assert look(broken, places, tmp_path).offers[0].description is None

    def test_a_description_that_is_not_a_line_is_not_read_as_one(self, tmp_path: Path, places: render.Directories):
        listed = local_remote(tmp_path / "listed", {"rules/odd.md": "---\ndescription:\n  - one\n  - two\n---\n\nb\n"})

        assert look(listed, places, tmp_path).offers[0].description is None

    def test_it_resolves_and_names_the_commit_it_listed(self, remote: str, places: render.Directories, tmp_path: Path):
        holding = look(remote, places, tmp_path)

        assert holding.resolved.commit is not None
        assert holding.resolved.ref == "main"

    def test_a_path_source_is_read_where_it_is_and_has_no_commit(
        self, remote: str, tmp_path: Path, places: render.Directories
    ):
        assert remote, "the fixture is what puts the repository at that path"

        holding = look(str(tmp_path / "remote"), places, tmp_path)

        assert holding.resolved.commit is None
        assert [offer.name for offer in holding.offers] == ["fkb", "writing", "prose-style", "reviewer"]

    def test_a_path_source_with_a_pin_says_there_is_nothing_to_pin(
        self, remote: str, tmp_path: Path, places: render.Directories
    ):
        assert remote, "the fixture is what puts the repository at that path"

        with pytest.raises(UsageError, match="no commit to pin"):
            look(f"{tmp_path / 'remote'}#v1", places, tmp_path)

    def test_the_cache_holds_the_source_afterwards(self, remote: str, places: render.Directories, tmp_path: Path):
        holding = look(remote, places, tmp_path)

        assert places.cache is not None
        assert holding.resolved.root.is_relative_to(places.cache)
        assert (holding.resolved.root / ".git").exists()


class TestWhatItPrints:
    def test_it_names_the_source_the_commit_and_each_kind(
        self, remote: str, places: render.Directories, tmp_path: Path
    ):
        report = printed(look(remote, places, tmp_path))

        assert "Skills" in report
        assert "Rules" in report
        assert "- writing" in report
        assert "(main)" in report

    def test_plainly_it_says_nothing_about_paths_or_descriptions(
        self, remote: str, places: render.Directories, tmp_path: Path
    ):
        report = printed(look(remote, places, tmp_path))

        assert "in the source" not in report
        assert "How to write a sentence" not in report

    def test_verbose_adds_where_each_part_is_and_what_it_is_for(
        self, remote: str, places: render.Directories, tmp_path: Path
    ):
        report = printed(look(remote, places, tmp_path), verbose=True)

        assert "at skills/writing in the source" in report
        assert "How to write a sentence" in report

    def test_the_closing_line_is_a_command_somebody_can_paste(
        self, remote: str, places: render.Directories, tmp_path: Path
    ):
        report = printed(look(remote, places, tmp_path))

        assert f"Next: akit add {remote} fkb" in report

    def test_a_source_holding_nothing_says_so_and_points_at_the_topic(self, tmp_path: Path, places: render.Directories):
        empty = local_remote(tmp_path / "empty", {"README.md": "nothing here\n"})

        report = printed(look(empty, places, tmp_path))

        assert discovering.NOTHING in report
        assert "akit help sources" in report

    def test_a_kind_that_is_not_there_says_which_kind_was_asked_for(self, tmp_path: Path, places: render.Directories):
        empty = local_remote(tmp_path / "empty", {"README.md": "nothing here\n"})

        assert "holds no agents" in printed(look(empty, places, tmp_path, kind=Kind.AGENT))

    def test_a_path_source_says_it_was_read_where_it_is(self, remote: str, tmp_path: Path, places: render.Directories):
        assert remote, "the fixture is what puts the repository at that path"

        assert "read where it is" in printed(look(str(tmp_path / "remote"), places, tmp_path))


class TestWhatAModelReads:
    def test_the_payload_carries_the_path_the_text_leaves_out(
        self, remote: str, places: render.Directories, tmp_path: Path
    ):
        payload = discovering.payload(look(remote, places, tmp_path))

        assert payload["source"] == remote
        assert payload["ref"] == "main"
        assert payload["kind"] is None
        assert {part["name"]: part["path"] for part in payload["parts"]}["prose-style"] == "rules/prose-style.md"

    def test_it_says_which_kind_it_was_narrowed_to(self, remote: str, places: render.Directories, tmp_path: Path):
        payload = discovering.payload(look(remote, places, tmp_path, kind=Kind.SKILL))

        assert payload["kind"] == "skills"
        assert [part["name"] for part in payload["parts"]] == ["fkb", "writing"]


class TestTheListingAddBorrows:
    def test_it_is_the_same_listing_a_typo_is_answered_with(
        self, remote: str, places: render.Directories, tmp_path: Path
    ):
        said = discovering.described(look(remote, places, tmp_path).offers)

        assert "It holds skills: fkb, writing" in said
        assert "It holds rules: prose-style" in said

    def test_a_source_holding_nothing_is_one_sentence(self, tmp_path: Path, places: render.Directories):
        empty = local_remote(tmp_path / "empty", {"README.md": "nothing here\n"})

        assert discovering.described(look(empty, places, tmp_path).offers).strip() == discovering.NOTHING


class TestTheVerb:
    def test_it_prints_the_report_and_succeeds(self, remote: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.chdir(tmp_path)
        out = io.StringIO()

        assert discovering.run(out, source=remote, as_json=False) is Exit.OK
        assert "- writing" in out.getvalue()

    def test_the_command_line_reaches_it(self, remote: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.chdir(tmp_path)
        out = io.StringIO()
        arguments = build_parser().parse_args(["discover", remote, "--kind", "rule", "--verbose"])

        assert dispatch(arguments, out) is Exit.OK
        assert "at rules/prose-style.md in the source" in out.getvalue()

    def test_json_is_the_same_answer_as_data(self, remote: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.chdir(tmp_path)
        out = io.StringIO()

        assert discovering.run(out, source=remote, as_json=True, kind=Kind.SKILL) is Exit.OK
        assert [part["name"] for part in json.loads(out.getvalue())["parts"]] == ["fkb", "writing"]
