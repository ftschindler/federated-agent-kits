"""Source classifications: machine state, strict where the record is lenient.

Split out of the render record when the record became one per scope root. A
classification is a fact about the cache and about a source key, so it belongs
to the machine rather than to a repository, and copying it into every
repository's record would be the same fact stored once per project.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from federated_agent_kits import privacy, record
from federated_agent_kits.cache import Privacy, Resolved
from federated_agent_kits.exits import Exit
from federated_agent_kits.sources import parse as parse_source

pytestmark = pytest.mark.unit


@pytest.fixture
def kits(tmp_path: Path) -> Path:
    path = tmp_path / "kits"
    path.mkdir()
    return path


def resolution(kits: Path, found: Privacy | None, *, fetched: bool) -> Resolved:
    return Resolved(source=parse_source(str(kits)), root=kits, commit=None, privacy=found, fetched=fetched)


class TestWhereItLives:
    def test_it_is_machine_state_beside_the_render_record(self, tmp_path: Path):
        assert privacy.location(tmp_path) == tmp_path / privacy.SOURCES
        assert privacy.location(tmp_path).parent == record.user_location(tmp_path).parent

    def test_a_machine_that_has_never_fetched_knows_nothing_rather_than_failing(self, tmp_path: Path):
        assert privacy.load(tmp_path) == {}


class TestRememberingWhatAFetchFound:
    def test_what_it_wrote_is_what_loads_back(self, tmp_path: Path):
        privacy.save({"acme/kits": Privacy.PRIVATE, "ftschindler/kits": Privacy.PUBLIC}, tmp_path)

        assert privacy.load(tmp_path) == {"acme/kits": Privacy.PRIVATE, "ftschindler/kits": Privacy.PUBLIC}

    def test_two_equal_sets_of_facts_are_one_file(self, tmp_path: Path):
        privacy.save({"b/kits": Privacy.PUBLIC, "a/kits": Privacy.PRIVATE}, tmp_path)
        first = privacy.location(tmp_path).read_text(encoding="utf-8")
        privacy.save({"a/kits": Privacy.PRIVATE, "b/kits": Privacy.PUBLIC}, tmp_path)

        assert privacy.location(tmp_path).read_text(encoding="utf-8") == first

    def test_the_first_write_creates_the_state_directory(self, tmp_path: Path):
        assert privacy.save({}, tmp_path / "never" / "existed").is_file()


class TestWhatAFetchTeaches:
    def test_a_resolution_that_went_to_the_network_is_remembered(self, kits: Path):
        learned = privacy.learned({}, [("acme/kits", resolution(kits, Privacy.PRIVATE, fetched=True))])

        assert learned == {"acme/kits": Privacy.PRIVATE}

    def test_a_resolution_that_did_not_leaves_what_was_already_known(self, kits: Path):
        known = {"acme/kits": Privacy.PUBLIC}

        learned = privacy.learned(known, [("acme/kits", resolution(kits, None, fetched=False))])

        assert learned == known

    def test_a_later_fetch_overrules_an_earlier_classification(self, kits: Path):
        known = {"acme/kits": Privacy.PUBLIC}

        learned = privacy.learned(known, [("acme/kits", resolution(kits, Privacy.PRIVATE, fetched=True))])

        assert learned == {"acme/kits": Privacy.PRIVATE}


class TestAFileThatCannotBeRead:
    """Refused rather than forgiven, which is the opposite of the record's answer.

    A stale explanation costs a file being left alone. A classification we
    cannot read costs the refusal in DESIGN.md section 8 being skipped, so this
    one stops the command.
    """

    @pytest.mark.parametrize(
        ("document", "says"),
        [
            ({"version": 99, "sources": {}}, "version 99"),
            ({"sources": {}}, "version None"),
            ({"version": 1, "sources": []}, "`sources` that is not an object"),
            ({"version": 1, "sources": {"acme/kits": "maybe"}}, "neither public nor private"),
        ],
    )
    def test_it_says_what_is_wrong_and_how_to_work_it_out_again(self, tmp_path: Path, document: object, says: str):
        privacy.location(tmp_path).parent.mkdir(parents=True, exist_ok=True)
        privacy.location(tmp_path).write_text(json.dumps(document), encoding="utf-8")

        with pytest.raises(privacy.ClassificationError) as raised:
            privacy.load(tmp_path)

        assert says in str(raised.value)
        assert "akit update" in str(raised.value)
        assert raised.value.exit_code is Exit.ERROR

    def test_one_that_is_not_json_names_the_line(self, tmp_path: Path):
        privacy.location(tmp_path).parent.mkdir(parents=True, exist_ok=True)
        privacy.location(tmp_path).write_text("{not json", encoding="utf-8")

        with pytest.raises(privacy.ClassificationError, match="not valid JSON"):
            privacy.load(tmp_path)

    def test_one_that_is_not_an_object(self, tmp_path: Path):
        privacy.location(tmp_path).parent.mkdir(parents=True, exist_ok=True)
        privacy.location(tmp_path).write_text("[]", encoding="utf-8")

        with pytest.raises(privacy.ClassificationError, match="not an object"):
            privacy.load(tmp_path)
