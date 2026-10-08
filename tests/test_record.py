"""The render record: one per scope root, read, written, and every way a bad one is bad.

The fixtures are the JSON a render produces, written by hand. That is the point
rather than a shortcut: this is the file format `list`, `render` and `doctor` all
have to agree on, and a test that built it through the writer would only prove
the writer agrees with itself.

What this file is mostly about is that there are two of them. Yours is machine
state in the state directory; a repository's lives inside the repository. A test
that only ever opened one would pass against the single-machine record this
replaced, which is the design that let a render in one repository delete
another's files.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from federated_agent_kits import record
from federated_agent_kits.exits import Exit
from federated_agent_kits.manifest import Kind, Scope

pytestmark = pytest.mark.unit


def write(path: Path, document: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def one(path: Path, *paths: Path) -> Path:
    return write(
        path,
        {
            "version": record.SUPPORTED_VERSION,
            "written": [
                {
                    "path": str(written),
                    "digest": "sha256:0",
                    "explained_by": ["skills|acme/kits|writing"],
                    "harnesses": ["opencode"],
                }
                for written in paths
            ],
        },
    )


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    return root


class TestWhereTheRecordsLive:
    def test_yours_is_machine_state_in_the_state_directory(self, tmp_path: Path):
        assert record.user_location(tmp_path) == tmp_path / record.RECORD

    def test_a_repositorys_is_inside_the_repository(self, worktree: Path):
        assert record.project_location(worktree) == worktree / record.DIRECTORY / record.RECORD

    def test_standing_in_a_repository_puts_both_in_play(self, worktree: Path, tmp_path: Path):
        found = record.locations(worktree, state_root=tmp_path / "state")

        assert set(found) == {Scope.USER, Scope.PROJECT}
        assert found[Scope.PROJECT].is_relative_to(worktree)

    def test_standing_outside_one_leaves_only_yours(self, tmp_path: Path):
        loose = tmp_path / "loose"
        loose.mkdir()

        assert set(record.locations(loose, state_root=tmp_path / "state")) == {Scope.USER}

    def test_the_state_directory_is_looked_up_per_platform(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))

        assert record.root().name == record.APPLICATION
        assert record.user_location().name == record.RECORD


class TestARootThatHasNeverBeenRenderedInto:
    def test_an_absent_record_is_an_empty_record_rather_than_an_error(self, tmp_path: Path):
        loaded = record.load(tmp_path / record.RECORD)

        assert loaded.written == ()
        assert loaded.path is None
        assert loaded.paths == frozenset()

    def test_nothing_is_explained_by_an_empty_record(self, tmp_path: Path):
        assert not record.load(tmp_path / record.RECORD).holds(tmp_path / ".agents" / "skills" / "writing")


class TestWhatTheRecordExplains:
    def test_a_file_it_names_is_explained(self, tmp_path: Path):
        rendered = tmp_path / ".github" / "instructions" / "prose-style.instructions.md"
        path = one(tmp_path / "state" / record.RECORD, rendered)

        assert record.load(path).holds(rendered)

    def test_a_directory_holding_a_file_it_names_is_explained(self, tmp_path: Path):
        skill = tmp_path / ".agents" / "skills" / "writing"
        path = one(tmp_path / "state" / record.RECORD, skill / "SKILL.md")

        assert record.load(path).holds(skill)

    def test_a_file_nobody_wrote_is_not_explained(self, tmp_path: Path):
        path = one(tmp_path / "state" / record.RECORD, tmp_path / ".agents" / "skills" / "writing" / "SKILL.md")

        assert not record.load(path).holds(tmp_path / ".agents" / "skills" / "mine")

    def test_what_it_wrote_comes_back_resolved_for_discovery_to_subtract(self, tmp_path: Path):
        skill = tmp_path / ".agents" / "skills" / "writing" / "SKILL.md"
        path = one(tmp_path / "state" / record.RECORD, skill)

        assert record.load(path).paths == frozenset({skill.resolve()})

    def test_the_explanations_survive_the_round_trip(self, tmp_path: Path):
        path = one(tmp_path / "state" / record.RECORD, tmp_path / "a.md")

        entry = record.load(path).written[0]

        assert entry.explained_by == frozenset({"skills|acme/kits|writing"})
        assert entry.harnesses == frozenset({"opencode"})
        assert entry.digest == "sha256:0"


class TestBothRecordsAtOnce:
    """What `akit list` and discovery read, which is the disk rather than one root."""

    def test_a_reader_sees_what_either_root_wrote(self, worktree: Path, tmp_path: Path):
        state = tmp_path / "state"
        mine = tmp_path / "home" / ".agents" / "skills" / "fkb" / "SKILL.md"
        theirs = worktree / ".agents" / "skills" / "writing" / "SKILL.md"
        one(state / record.RECORD, mine)
        one(record.project_location(worktree), theirs)

        both = record.load_all(worktree, state_root=state)

        assert both.paths == {mine.resolve(), theirs.resolve()}
        assert both.holds(mine.parent)
        assert both.holds(theirs.parent)

    def test_each_root_is_still_available_on_its_own(self, worktree: Path, tmp_path: Path):
        one(record.project_location(worktree), worktree / "a.md")

        both = record.load_all(worktree, state_root=tmp_path / "state")

        assert both.of(Scope.USER).written == ()
        assert len(both.of(Scope.PROJECT).written) == 1

    def test_a_scope_with_no_record_answers_empty_rather_than_raising(self, tmp_path: Path):
        loose = tmp_path / "loose"
        loose.mkdir()

        both = record.load_all(loose, state_root=tmp_path / "state")

        assert both.of(Scope.PROJECT).written == ()


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
        path = write(tmp_path / record.RECORD, document)

        with pytest.raises(record.RecordError) as raised:
            record.load(path)

        assert says in str(raised.value)
        assert "akit render" in str(raised.value)
        assert raised.value.exit_code is Exit.ERROR

    def test_a_record_that_is_not_json_names_the_line(self, tmp_path: Path):
        path = tmp_path / record.RECORD
        path.write_text("{not json", encoding="utf-8")

        with pytest.raises(record.RecordError, match="not valid JSON"):
            record.load(path)

    def test_a_record_that_is_not_an_object(self, tmp_path: Path):
        path = write(tmp_path / record.RECORD, [])

        with pytest.raises(record.RecordError, match="not an object"):
            record.load(path)


class TestAnExplanation:
    def test_it_is_one_string_that_gives_its_parts_back(self):
        explanation = record.Explanation(kind=Kind.SKILL, source="acme/kits", name="house-style")

        assert record.Explanation.parse(str(explanation)) == explanation

    def test_it_does_not_carry_a_scope_because_the_file_it_is_in_says_so(self):
        explanation = record.Explanation(kind=Kind.SKILL, source="acme/kits", name="writing")

        assert str(explanation).count(record.SEPARATOR) == record.PARTS - 1
        assert "project" not in str(explanation)

    @pytest.mark.parametrize(
        "text",
        ["skills:writing", "skills|acme/kits", "project|skills|acme/kits|writing", "songs|acme/kits|writing"],
    )
    def test_one_this_build_cannot_read_explains_nothing_rather_than_refusing(self, text: str):
        assert record.Explanation.parse(text) is None

    def test_an_unreadable_explanation_leaves_the_entry_with_none(self, tmp_path: Path):
        path = write(
            tmp_path / record.RECORD,
            {
                "version": 1,
                "written": [{"path": str(tmp_path / "a.md"), "digest": "0", "explained_by": ["nonsense"]}],
            },
        )

        assert record.load(path).written[0].explanations == ()


class TestWritingARecord:
    def test_what_it_wrote_is_what_loads_back(self, tmp_path: Path):
        rendered = tmp_path / ".agents" / "skills" / "writing" / "SKILL.md"
        explanation = str(record.Explanation(kind=Kind.SKILL, source="acme/kits", name="writing"))
        written = record.Written(
            path=rendered,
            digest=record.digest(b"# writing\n"),
            explained_by=frozenset({explanation}),
            harnesses=frozenset({"opencode"}),
        )
        path = tmp_path / "state" / record.RECORD

        record.save(record.Record(path=None, written=(written,)), path)

        assert record.load(path).written == (written,)

    def test_two_equal_records_are_the_same_file_whatever_order_they_were_built_in(self, tmp_path: Path):
        entries = [
            record.Written(path=tmp_path / name, digest="0", explained_by=frozenset({"b", "a"}))
            for name in ("b.md", "a.md")
        ]

        first = record.payload(record.Record(path=None, written=tuple(entries)))
        second = record.payload(record.Record(path=None, written=tuple(reversed(entries))))

        assert first == second
        assert [entry["path"] for entry in first["written"]] == [str(tmp_path / "a.md"), str(tmp_path / "b.md")]

    def test_a_first_render_creates_the_directory_above_it(self, tmp_path: Path):
        written = record.save(
            record.Record(path=None, written=(record.Written(path=tmp_path / "a.md", digest="0"),)),
            tmp_path / "never" / "existed" / record.RECORD,
        )

        assert written is not None
        assert written.is_file()

    def test_a_record_with_nothing_in_it_is_no_file_rather_than_an_empty_one(self, tmp_path: Path):
        path = tmp_path / "state" / record.RECORD

        assert record.save(record.Record(path=None), path) is None
        assert not path.exists()

    def test_a_record_that_empties_takes_its_file_and_our_directory_with_it(self, worktree: Path):
        path = record.project_location(worktree)
        record.save(record.Record(path=None, written=(record.Written(path=worktree / "a.md", digest="0"),)), path)
        assert path.is_file()

        record.save(record.Record(path=None), path)

        assert not path.exists()
        assert not (worktree / record.DIRECTORY).exists()

    def test_emptying_a_record_leaves_anything_else_in_that_directory_alone(self, worktree: Path):
        path = record.project_location(worktree)
        path.parent.mkdir(parents=True)
        (path.parent / "notes.txt").write_text("mine\n", encoding="utf-8")

        record.save(record.Record(path=None), path)

        assert (path.parent / "notes.txt").is_file()


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
