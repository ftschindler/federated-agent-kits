"""Shared fixtures: a throwaway machine, and a git environment with no outer repository.

The `cli` layer runs `akit` as a subprocess inside a fake home (see
`fake_home.py`), which is what makes a bug in it unable to reach the developer's
own config, cache or state directory. The `unit` layer imports the package
directly and needs none of this.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fake_home import FakeHome, build_fake_home


@pytest.fixture
def fake_home(tmp_path: Path) -> FakeHome:
    """A throwaway machine with nothing of the developer's in it."""
    return build_fake_home(tmp_path / "home")
