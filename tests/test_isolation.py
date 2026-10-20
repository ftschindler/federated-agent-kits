"""The tests' own machine, which is the one thing no test is allowed to escape.

`akit` keeps three directories on a real machine: the manifest that says which
kits somebody uses, the record of what it rendered, and the cache of sources.
All three are found through `platformdirs`, which reads the environment, and a
test that patches `Path.home` without redirecting `XDG_STATE_HOME` reaches the
developer's rather than its own. That is not hypothetical: it overwrote a real
render record, and `akit doctor` then reported forty-four findings, every one of
them a path inside a `pytest` temporary directory.

A fixture is the fix and this is the lock on it. It asserts the three roots the
package resolves at import-time defaults, from inside an ordinary test, land
under this test's own directory. Anything that weakens `confined` fails here
rather than in somebody's home directory.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fake_home import FakeHome, confine

from federated_agent_kits import cache, manifest, record

pytestmark = pytest.mark.unit


class TestEveryDirectoryTheProcessWouldWriteTo:
    def test_the_render_record_is_inside_this_test(self, confined: FakeHome):
        assert record.root().is_relative_to(confined.root)

    def test_the_cache_is_inside_this_test(self, confined: FakeHome):
        assert cache.root().is_relative_to(confined.root)

    def test_the_global_manifest_is_inside_this_test(self, confined: FakeHome):
        assert manifest.user_manifest_path().is_relative_to(confined.root)

    def test_the_home_the_package_would_read_is_inside_this_test(self, confined: FakeHome):
        assert Path.home() == confined.root


class TestTheAnswerIsNotRememberedFromAnEarlierHome:
    """Asking twice, from two homes, and getting one answer is the Windows bug.

    The assertions above are each a single lookup, and a lookup that answers
    from something it resolved once and kept passes all of them: the first test
    in the process to ask gets its own directory and every later one gets that
    same directory back, whatever the environment says by then. Which test is
    first is alphabetical, so a cache here is invisible until somebody adds a
    file that sorts earlier (issue #38, where `test_cache.py` did).

    This asks twice in one test, from two houses, which is the shape that has no
    ordering to be lucky with.
    """

    def test_two_homes_in_one_process_are_two_answers(self, tmp_path: Path) -> None:
        answers = []
        for name in ("first", "second"):
            with pytest.MonkeyPatch.context() as patch:
                house = confine(patch, tmp_path / name)
                answers.append((house.root, record.root(), cache.root(), manifest.user_manifest_path()))

        for root, *directories in answers:
            assert all(directory.is_relative_to(root) for directory in directories), f"{directories} escaped {root}"
        assert answers[0][1:] != answers[1][1:]
