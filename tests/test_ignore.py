"""The `.gitignore` block: ours rewritten whole, everybody else's left exactly alone.

The block is computed from what a render wrote, so the interesting tests are
not about which directories end up in it. They are about the file around it,
which is a file somebody owns and mostly wrote by hand.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from federated_agent_kits import ignore

pytestmark = pytest.mark.unit


class TestWhatTheBlockHolds:
    def test_a_block_is_the_markers_and_the_directories_between_them(self):
        assert ignore.block([".agents/skills/"]) == [ignore.BEGIN, ".agents/skills/", ignore.END]

    def test_nothing_to_ignore_is_no_block_rather_than_an_empty_one(self):
        assert ignore.block([]) == []

    def test_a_directory_named_twice_is_listed_once(self):
        assert ignore.block([".agents/skills/", ".agents/skills/"]).count(".agents/skills/") == 1


class TestWhatSurvivesARewrite:
    def test_the_users_own_lines_keep_their_order_and_their_blank_lines(self):
        before = "*.pyc\n\n# mine\nbuild/\n"

        after = ignore.rewrite(before, [".agents/skills/"])

        assert after.splitlines()[:4] == ["*.pyc", "", "# mine", "build/"]
        assert ignore.BEGIN in after

    def test_the_block_goes_back_where_somebody_moved_it(self):
        before = f"# top\n{ignore.BEGIN}\nold/\n{ignore.END}\n# bottom\n"

        after = ignore.rewrite(before, [".agents/skills/"])

        assert after.splitlines() == ["# top", ignore.BEGIN, ".agents/skills/", ignore.END, "# bottom"]

    def test_an_unterminated_block_takes_the_rest_of_the_file_rather_than_growing_a_second_one(self):
        before = f"# mine\n{ignore.BEGIN}\nold/\n"

        after = ignore.rewrite(before, [".agents/skills/"])

        assert after.count(ignore.BEGIN) == 1
        assert after.splitlines()[0] == "# mine"

    def test_a_file_that_was_only_ours_becomes_empty_rather_than_a_pair_of_comments(self):
        before = f"{ignore.BEGIN}\n.agents/skills/\n{ignore.END}\n"

        assert ignore.rewrite(before, []) == ""

    def test_a_file_with_no_final_newline_gets_one_and_keeps_its_line(self):
        after = ignore.rewrite("*.pyc", [".agents/skills/"])

        assert after.startswith("*.pyc\n")
        assert after.endswith(f"{ignore.END}\n")

    def test_taking_our_block_out_does_not_leave_the_blank_line_that_separated_it(self):
        before = f"*.pyc\n\n{ignore.BEGIN}\n.agents/skills/\n{ignore.END}\n"

        assert ignore.rewrite(before, []) == "*.pyc\n"

    def test_rewriting_is_idempotent(self):
        once = ignore.rewrite("*.pyc\n", [".agents/skills/"])

        assert ignore.rewrite(once, [".agents/skills/"]) == once


class TestTheFileOnDisk:
    def test_a_repository_with_nothing_to_ignore_and_no_gitignore_gets_no_file(self, tmp_path: Path):
        changed = ignore.maintain(tmp_path, [])

        assert not changed
        assert not (tmp_path / ignore.GITIGNORE).exists()

    def test_a_second_call_reports_that_it_changed_nothing(self, tmp_path: Path):
        assert ignore.maintain(tmp_path, [".agents/skills/"])
        assert not ignore.maintain(tmp_path, [".agents/skills/"])

    def test_a_file_written_on_windows_is_read_and_written_back_with_one_newline(self, tmp_path: Path):
        (tmp_path / ignore.GITIGNORE).write_bytes(b"*.pyc\r\n")

        ignore.maintain(tmp_path, [".agents/skills/"])

        assert b"\r\n" not in (tmp_path / ignore.GITIGNORE).read_bytes()
