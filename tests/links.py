"""A symlink, on a machine that allows one, and the same question answered where it does not.

`akit` refuses to render a kit into a target that is a symlink (DESIGN.md
section 6), and the test for that wants a symlink. Creating one on Windows needs
a privilege a GitHub runner does not reliably have, which is the same fact
`.scripts/check_no_symlinks.py` exists for. Skipping the test there is not an
option either: the `unit` layer is gated at 100% branch coverage on both
operating systems, so a skip on one of them fails the build rather than
quietly reducing what was checked.

So `linked` makes a real link where it can and, where it cannot, makes
`Path.is_symlink` answer for that one path. The second is a narrow substitution:
`is_symlink` on the target is the entire question the renderer asks, and
everything the test then asserts - that nothing was written, that the
subscription carries a problem naming the path, that the record gained no entry
- is the real code doing the real thing.

`really_linked` is for the half that cannot be faked: that the files the link
points at are still there afterwards. That one is skipped where links are not
available, because there is nothing to point at.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def supported(tmp_path: Path) -> bool:
    """Whether this machine lets an unprivileged process make a symlink."""
    probe = tmp_path / "probe-link"
    try:
        probe.symlink_to(tmp_path)
    except OSError:
        return False
    probe.unlink()
    return True


def linked(path: Path, target: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Make `path` a symlink to `target`, or make it answer as one."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(target, target_is_directory=target.is_dir())
    except OSError:
        answer = Path.is_symlink
        monkeypatch.setattr(Path, "is_symlink", lambda self: self == path or answer(self))


def really_linked(path: Path, target: Path) -> None:
    """The same link, where a test needs the destination to exist and stay put."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.symlink_to(target, target_is_directory=target.is_dir())
    except OSError as error:
        pytest.skip(f"this machine does not allow a symlink to be made: {error}")


__all__ = ["linked", "really_linked", "supported"]
