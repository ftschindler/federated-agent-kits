"""The render record, read: an absent one, a good one, and every way a bad one is bad.

Nothing writes a record yet - that is T5 - so the fixtures here are the JSON a
render will produce. Writing them by hand is the point rather than a shortcut:
this is the file format two tasks have to agree on, and a test that built it
through the writer would only prove the writer agrees with itself.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from federated_agent_kits import record
from federated_agent_kits.cache import Privacy
from federated_agent_kits.exits import Exit
from federated_agent_kits.manifest import Kind, Scope

pytestmark = pytest.mark.unit


def write(root: Path, document: object) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / record.RECORD
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def one(root: Path, *paths: Path) -> Path:
    return write(
        root,
        {
            "version": record.SUPPORTED_VERSION,
            "written": [
                {
                    "path": str(path),
                    "digest": "sha256:0",
                    "explained_by": ["skills:writing"],
                    "harnesses": ["opencode"],
                }
                for path in paths
            ],
        },
    )


class TestAMachineThatHasNeverRendered:
    def test_an_absent_record_is_an_empty_record_rather_than_an_error(self, tmp_path: Path):
        loaded = record.load(tmp_path)

        assert loaded.written == ()
        assert loaded.path is None
        assert loaded.paths == frozenset()

    def test_nothing_is_explained_by_an_empty_record(self, tmp_path: Path):
        assert not record.load(tmp_path).holds(tmp_path / ".agents" / "skills" / "writing")


class TestWhatTheRecordExplains:
    def test_a_file_it_names_is_explained(self, tmp_path: Path):
        rendered = tmp_path / ".github" / "instructions" / "prose-style.instructions.md"
        one(tmp_path / "state", rendered)

        assert record.load(tmp_path / "state").holds(rendered)

    def test_a_directory_holding_a_file_it_names_is_explained(self, tmp_path: Path):
        skill = tmp_path / ".agents" / "skills" / "writing"
        one(tmp_path / "state", skill / "SKILL.md")

        assert record.load(tmp_path / "state").holds(skill)

    def test_a_file_nobody_wrote_is_not_explained(self, tmp_path: Path):
        one(tmp_path / "state", tmp_path / ".agents" / "skills" / "writing" / "SKILL.md")

        assert not record.load(tmp_path / "state").holds(tmp_path / ".agents" / "skills" / "mine")

    def test_what_it_wrote_comes_back_resolved_for_discovery_to_subtract(self, tmp_path: Path):
        skill = tmp_path / ".agents" / "skills" / "writing" / "SKILL.md"
        one(tmp_path / "state", skill)

        assert record.load(tmp_path / "state").paths == frozenset({skill.resolve()})

    def test_the_explanations_survive_the_round_trip(self, tmp_path: Path):
        one(tmp_path / "state", tmp_path / "a.md")

        entry = record.load(tmp_path / "state").written[0]

        assert entry.explained_by == frozenset({"skills:writing"})
        assert entry.harnesses == frozenset({"opencode"})
        assert entry.digest == "sha256:0"


class TestARecordThatCannotBeRead:
    @pytest.mark.parametrize(
        ("document", "says"),
        [
            ({"version": 99, "written": []}, "version 99"),
            ({"written": []}, "version None"),
            ({"version": 1, "written": {}}, "`written` that is not a list"),
            ({"version": 1, "written": ["a.md"]}, "entry that is not a written file"),
            ({"version": 1, "written": [{"path": "a.md"}]}, "entry that is not a written file"),
        ],
    )
    def test_it_says_what_is_wrong_and_that_rendering_again_fixes_it(self, tmp_path: Path, document: object, says: str):
        write(tmp_path, document)

        with pytest.raises(record.RecordError) as raised:
            record.load(tmp_path)

        assert says in str(raised.value)
        assert "akit render" in str(raised.value)
        assert raised.value.exit_code is Exit.ERROR

    def test_a_record_that_is_not_json_names_the_line(self, tmp_path: Path):
        tmp_path.joinpath(record.RECORD).write_text("{not json", encoding="utf-8")

        with pytest.raises(record.RecordError) as raised:
            record.load(tmp_path)

        assert "not valid JSON" in str(raised.value)

    def test_a_record_that_is_not_an_object(self, tmp_path: Path):
        write(tmp_path, [])

        with pytest.raises(record.RecordError, match="not an object"):
            record.load(tmp_path)


class TestWhereItLives:
    def test_the_state_directory_is_looked_up_per_platform(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))

        assert record.root().name == record.APPLICATION
        assert record.location().name == record.RECORD


class TestAnExplanation:
    def test_it_is_one_string_that_gives_its_parts_back(self):
        explanation = record.Explanation(scope=Scope.PROJECT, kind=Kind.SKILL, source="acme/kits", name="house-style")

        assert record.Explanation.parse(str(explanation)) == explanation

    @pytest.mark.parametrize(
        "text",
        ["skills:writing", "project|skills|acme/kits", "nowhere|skills|acme/kits|writing", "project|songs|a|b"],
    )
    def test_one_this_build_cannot_read_explains_nothing_rather_than_refusing(self, text: str):
        assert record.Explanation.parse(text) is None

    def test_an_unreadable_explanation_puts_a_file_in_no_scope_at_all(self, tmp_path: Path):
        one(tmp_path / "state", tmp_path / "a.md")

        assert record.load(tmp_path / "state").written[0].scopes == frozenset()


class TestWritingTheRecord:
    def test_what_it_wrote_is_what_loads_back(self, tmp_path: Path):
        rendered = tmp_path / ".agents" / "skills" / "writing" / "SKILL.md"
        explanation = str(record.Explanation(scope=Scope.USER, kind=Kind.SKILL, source="acme/kits", name="writing"))
        written = record.Written(
            path=rendered,
            digest=record.digest(b"# writing\n"),
            explained_by=frozenset({explanation}),
            harnesses=frozenset({"opencode"}),
        )

        record.save(record.Record(path=None, written=(written,), sources={"acme/kits": Privacy.PRIVATE}), tmp_path)
        loaded = record.load(tmp_path)

        assert loaded.written == (written,)
        assert loaded.sources == {"acme/kits": Privacy.PRIVATE}

    def test_two_equal_records_are_the_same_file_whatever_order_they_were_built_in(self, tmp_path: Path):
        entries = [
            record.Written(path=tmp_path / name, digest="0", explained_by=frozenset({"b", "a"}))
            for name in ("b.md", "a.md")
        ]

        first = record.payload(record.Record(path=None, written=tuple(entries)))
        second = record.payload(record.Record(path=None, written=tuple(reversed(entries))))

        assert first == second
        assert [entry["path"] for entry in first["written"]] == [str(tmp_path / "a.md"), str(tmp_path / "b.md")]

    def test_a_first_render_creates_the_state_directory(self, tmp_path: Path):
        written = record.save(record.Record(path=None), tmp_path / "never" / "existed")

        assert written.is_file()

    @pytest.mark.parametrize(
        ("document", "says"),
        [
            ({"version": 1, "written": [], "sources": []}, "`sources` that is not an object"),
            ({"version": 1, "written": [], "sources": {"acme/kits": "maybe"}}, "neither public nor private"),
        ],
    )
    def test_a_classification_it_cannot_read_is_refused_rather_than_forgiven(
        self, tmp_path: Path, document: object, says: str
    ):
        write(tmp_path, document)

        with pytest.raises(record.RecordError, match=says):
            record.load(tmp_path)


class TestWhetherACopyIsStillACopy:
    def test_the_bytes_we_wrote_are_still_a_copy(self, tmp_path: Path):
        rendered = tmp_path / "SKILL.md"
        rendered.write_bytes(b"# writing\n")

        entry = record.Written(path=rendered, digest=record.digest(b"# writing\n"))

        assert entry.still_a_copy()

    def test_bytes_somebody_edited_are_not(self, tmp_path: Path):
        rendered = tmp_path / "SKILL.md"
        rendered.write_bytes(b"# mine now\n")

        assert not record.Written(path=rendered, digest=record.digest(b"# writing\n")).still_a_copy()

    def test_a_file_that_is_gone_hashes_to_nothing_rather_than_raising(self, tmp_path: Path):
        assert record.digest_of(tmp_path / "absent.md") is None
