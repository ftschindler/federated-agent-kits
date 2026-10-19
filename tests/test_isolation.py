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
from fake_home import FakeHome

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
