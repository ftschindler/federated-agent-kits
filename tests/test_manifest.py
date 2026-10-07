"""The manifest: every form in DESIGN.md section 6 read, every refusal, and the merge.

The round-trip is the test that matters most and is easiest to weaken by
accident. It asserts bytes rather than structure, over a corpus holding every
shape the design documents, because the thing being protected is somebody's
comments and key order rather than the data underneath them. A test that parsed
and compared dictionaries would pass while `akit add` silently reformatted the
file it was asked to add one line to.

The rejections get one test each, and each asserts the line number as well as
the refusal. A parser that says "this is wrong" without saying where is a parser
somebody works around by rewriting the file from scratch.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from federated_agent_kits.exits import Exit
from federated_agent_kits.manifest import (
    DEFAULT_HARNESSES,
    Kind,
    ManifestError,
    Scope,
    dump,
    find_project_manifest,
    load,
    merge,
    parse,
    read,
    user_manifest_path,
    worktree_root,
    write,
)

pytestmark = pytest.mark.unit

#: Every shape section 6 documents, in one file: both block styles, a wildcard,
#: a pin with its comment, a trailing comment on a block, and a blank line.
CORPUS = """version: 1

skills:
  owner/repo#9f2c1ab: [writing, caveman]   # frozen: v2
  acme/kits#4d7e08b: ["*"]                 # frozen: main, 2026-10-05

rules:                                     # order matters here, and nowhere else
- owner/repo#1c04f7e: prose-style          # frozen: v1
- acme/kits#4d7e08b: security-review       # frozen: main, 2026-10-05

agents:
  acme/kits#4d7e08b: [reviewer]            # frozen: main, 2026-10-05
"""

#: The second documented shape: a kit that needs more than its name.
RENAMED = """version: 1
harnesses: [detected, copilot-ci]

skills:
  owner/repo#9f2c1ab:    # frozen: v2
  - writing
  - name: kb
    as: upstream-kb      # this name is taken
"""


def parsed(text: str, scope: Scope = Scope.PROJECT):
    return parse(text, scope=scope)


def refusal(text: str) -> ManifestError:
    with pytest.raises(ManifestError) as raised:
        parsed(text)
    return raised.value


class TestTheRoundTrip:
    @pytest.mark.parametrize("corpus", [CORPUS, RENAMED], ids=["documented", "renamed"])
    def test_an_unmodified_manifest_writes_back_byte_for_byte(self, corpus: str) -> None:
        assert dump(parsed(corpus)) == corpus

    def test_a_pin_keeps_the_comment_beside_it(self) -> None:
        # The comment is the human-readable name of the hash and nothing parses
        # it, which is the only safe thing to do with a comment.
        assert "# frozen: v2" in dump(parsed(CORPUS))

    def test_a_long_line_is_not_rewrapped(self) -> None:
        long = "version: 1\nskills:\n  owner/repo#9f2c1ab: [" + ", ".join(f"kit{n}" for n in range(40)) + "]\n"
        assert dump(parsed(long)) == long


class TestEditingInPlace:
    """What T7 leans on: changing one thing leaves everything else alone.

    Every other round-trip test here parses and dumps an untouched document,
    which proves the library can echo a file and not that it can edit one. The
    guarantee `akit add` and `akit remove` actually need is this one, so it is
    tested against a mutated document rather than assumed from the echo.

    The mutations are made on `document` directly because the API that will make
    them is T7's. What is being pinned down is the writer underneath it.
    """

    def content(self, text: str) -> list[str]:
        """The lines that carry something, with alignment padding collapsed.

        Column alignment is cosmetic and ruamel re-flows it when the line it is
        on changes width. What must survive is the content and the comment.
        """
        return [" ".join(line.split()) for line in text.splitlines() if line.strip()]

    def test_appending_a_kit_keeps_the_pin_comment(self) -> None:
        manifest = parsed(CORPUS)
        manifest.document["skills"]["owner/repo#9f2c1ab"].append("newkit")
        written = dump(manifest)
        assert "# frozen: v2" in written
        assert "[writing, caveman, newkit]" in written

    def test_appending_a_kit_leaves_every_other_line_alone(self) -> None:
        manifest = parsed(CORPUS)
        manifest.document["skills"]["owner/repo#9f2c1ab"].append("newkit")
        before = self.content(CORPUS)
        after = self.content(dump(manifest))
        changed = [(old, new) for old, new in zip(before, after, strict=True) if old != new]
        assert len(changed) == 1, f"one line should have changed, these did: {changed}"

    def test_removing_a_kit_leaves_its_neighbours_alone(self) -> None:
        manifest = parsed(CORPUS)
        manifest.document["skills"]["owner/repo#9f2c1ab"].remove("caveman")
        after = dump(manifest)
        assert "[writing]" in after
        assert "# frozen: v2" in after
        # The entry beneath it, comment and all, is byte-identical.
        assert '  acme/kits#4d7e08b: ["*"]                 # frozen: main, 2026-10-05' in after

    def test_a_new_source_key_keeps_every_line_that_was_already_there(self) -> None:
        manifest = parsed(CORPUS)
        manifest.document["skills"]["new/source#deadbee"] = ["thing"]
        after = self.content(dump(manifest))
        for line in self.content(CORPUS):
            assert line in after, f"adding a key lost: {line}"

    def test_a_new_source_key_moves_the_blank_line_that_followed_the_block(self) -> None:
        """A known sharp edge, pinned down here so T7 meets it as a decision.

        ruamel attaches the blank line separating two blocks to whatever now
        follows it, so inserting at the end of `skills:` puts the new key after
        that blank line and leaves `rules:` without its separator. No content is
        lost and the file still parses; what changes is somebody's spacing.

        Asserted rather than fixed because the insertion API that should decide
        where a new key goes belongs to T7, and a writer that silently
        reformatted to compensate would be the opposite of boring.
        """
        manifest = parsed(CORPUS)
        manifest.document["skills"]["new/source#deadbee"] = ["thing"]
        written = dump(manifest)
        assert "- thing\nrules:" in written, "the blank line before `rules:` should have moved"
        assert "\n\n  new/source#deadbee:" in written, "and should now sit above the new key"
        assert parse(written, scope=Scope.PROJECT).of_kind(Kind.SKILL)[-1].name == "thing"

    def test_an_edited_manifest_still_parses(self) -> None:
        # The whole point of writing it back is reading it again.
        manifest = parsed(CORPUS)
        manifest.document["skills"]["owner/repo#9f2c1ab"].append("newkit")
        reparsed = parse(dump(manifest), scope=Scope.PROJECT)
        assert [s.name for s in reparsed.of_kind(Kind.SKILL)] == ["writing", "caveman", "newkit", "*"]


class TestWhatItReads:
    def test_every_subscription_in_the_corpus(self) -> None:
        found = [(s.kind, s.source, s.pin, s.name) for s in parsed(CORPUS).subscriptions]
        assert found == [
            (Kind.SKILL, "owner/repo", "9f2c1ab", "writing"),
            (Kind.SKILL, "owner/repo", "9f2c1ab", "caveman"),
            (Kind.SKILL, "acme/kits", "4d7e08b", "*"),
            (Kind.RULE, "owner/repo", "1c04f7e", "prose-style"),
            (Kind.RULE, "acme/kits", "4d7e08b", "security-review"),
            (Kind.AGENT, "acme/kits", "4d7e08b", "reviewer"),
        ]

    def test_a_line_number_points_at_the_entry(self) -> None:
        assert [s.line for s in parsed(CORPUS).of_kind(Kind.RULE)] == [8, 9]

    def test_as_renames_the_kit_and_keeps_both_names(self) -> None:
        kb = parsed(RENAMED).subscriptions[1]
        assert (kb.name, kb.rename, kb.rendered_name) == ("kb", "upstream-kb", "upstream-kb")

    def test_a_kit_without_as_is_rendered_under_its_own_name(self) -> None:
        assert parsed(CORPUS).subscriptions[0].rendered_name == "writing"

    def test_a_wildcard_is_marked_as_one(self) -> None:
        assert [s.is_wildcard for s in parsed(CORPUS).of_kind(Kind.SKILL)] == [False, False, True]

    def test_the_key_is_given_back_as_it_was_written(self) -> None:
        assert parsed(CORPUS).subscriptions[0].key == "owner/repo#9f2c1ab"

    def test_a_source_with_no_pin_has_none(self) -> None:
        # A path source is read where it is, so there is no commit to pin.
        local = parsed("version: 1\nskills:\n  ../my-kits: [thing]\n").subscriptions[0]
        assert (local.pin, local.key) == (None, "../my-kits")

    def test_a_single_kit_may_be_written_without_a_list(self) -> None:
        assert parsed("version: 1\nrules:\n- a/b: prose\n").subscriptions[0].name == "prose"

    def test_a_single_kit_may_be_written_as_a_mapping(self) -> None:
        one = parsed("version: 1\nskills:\n  a/b:\n    name: kb\n    as: other\n").subscriptions[0]
        assert (one.name, one.rename) == ("kb", "other")

    def test_a_missing_kind_block_is_simply_absent(self) -> None:
        assert parsed("version: 1\nskills:\n  a/b: [x]\n").of_kind(Kind.AGENT) == ()

    def test_the_scope_is_carried_on_every_subscription(self) -> None:
        assert {s.scope for s in parsed(CORPUS, Scope.USER).subscriptions} == {Scope.USER}


class TestHarnesses:
    def test_an_absent_key_means_detected(self) -> None:
        assert parsed(CORPUS).harnesses == DEFAULT_HARNESSES

    def test_a_named_list_is_the_whole_answer(self) -> None:
        assert parsed(RENAMED).harnesses == ("detected", "copilot-ci")

    def test_a_scalar_is_refused(self) -> None:
        assert "not a list" in refusal("version: 1\nharnesses: detected\n").problem


class TestTheRefusals:
    """One per rejection, each asserting the line as well as the message.

    They are exit code 1 and not 3: the command was typed correctly and a file
    on disk is malformed, which is not the refusal DESIGN.md section 8 reserves
    the number for.
    """

    def test_a_malformed_manifest_is_not_a_refusal(self) -> None:
        assert refusal("version: 2\n").exit_code == Exit.ERROR

    def test_an_unknown_kind(self) -> None:
        error = refusal("version: 1\nprompts:\n  a/b: [x]\n")
        assert (error.line, "not a key a manifest has" in error.problem) == (2, True)

    def test_rules_written_as_a_mapping(self) -> None:
        # The spelling that silently loses the order deciding which rule wins.
        error = refusal("version: 1\nrules:\n  a/b: x\n")
        assert error.line == 2
        assert "has no order" in error.problem
        assert "order decides" in error.fix

    def test_skills_written_as_a_list(self) -> None:
        error = refusal("version: 1\nskills:\n- a/b: x\n")
        assert (error.line, "written as a list" in error.problem) == (2, True)

    def test_a_version_this_build_does_not_know(self) -> None:
        assert refusal("version: 2\n").line == 1

    def test_no_version_at_all(self) -> None:
        assert "no `version:` key" in refusal("skills:\n  a/b: [x]\n").problem

    def test_a_duplicate_name_within_one_scope(self) -> None:
        error = refusal("version: 1\nskills:\n  a/b: [writing]\n  c/d: [writing]\n")
        assert error.line == 4
        assert "subscribed to twice" in error.problem
        assert "line 3" in error.fix, "the fix should point at the other one"

    def test_a_rename_collides_with_a_plain_name(self) -> None:
        text = "version: 1\nskills:\n  a/b: [writing]\n  c/d:\n  - name: kb\n    as: writing\n"
        assert "subscribed to twice" in refusal(text).problem

    def test_the_same_name_under_two_kinds_is_not_a_duplicate(self) -> None:
        # A rule and a skill called `writing` land in different directories.
        assert len(parsed("version: 1\nskills:\n  a/b: [w]\nrules:\n- c/d: w\n").subscriptions) == 2

    def test_an_empty_file(self) -> None:
        assert "empty" in refusal("").problem

    def test_a_manifest_that_is_not_a_mapping(self) -> None:
        assert "not a mapping of keys" in refusal("- a\n- b\n").problem

    def test_something_that_is_not_yaml(self) -> None:
        assert "not valid YAML" in refusal("version: 1\nskills: [\n").problem

    def test_a_kit_that_is_neither_a_name_nor_a_mapping(self) -> None:
        assert "not a name or a mapping" in refusal("version: 1\nskills:\n  a/b: [3]\n").problem

    def test_a_subscription_that_is_a_number(self) -> None:
        assert "written as a number" in refusal("version: 1\nskills:\n  a/b: 7\n").problem

    def test_a_subscription_that_is_a_true_false_value(self) -> None:
        # `true` and not `yes`: ruamel reads YAML 1.2, where only the former is
        # a boolean and the latter is an ordinary string.
        assert "true/false" in refusal("version: 1\nskills:\n  a/b: [true]\n").problem

    def test_a_source_key_with_nothing_after_it(self) -> None:
        # The likeliest typo of them all: a key typed and the kits not yet.
        assert "empty" in refusal("version: 1\nskills:\n  a/b:\n").problem

    def test_a_manifest_that_is_a_bare_scalar(self) -> None:
        assert "not a mapping of keys" in refusal("just some text\n").problem

    def test_a_kit_mapping_with_an_unknown_key(self) -> None:
        error = refusal("version: 1\nskills:\n  a/b:\n  - name: kb\n    alias: x\n")
        assert "alias" in error.problem

    def test_a_kit_mapping_with_no_name(self) -> None:
        assert "no `name:`" in refusal("version: 1\nskills:\n  a/b:\n  - as: x\n").problem

    def test_a_rule_entry_naming_two_sources(self) -> None:
        assert "one source mapped to" in refusal("version: 1\nrules:\n- a/b: x\n  c/d: y\n").problem

    def test_a_rule_entry_that_is_a_bare_name(self) -> None:
        assert "one source mapped to" in refusal("version: 1\nrules:\n- prose-style\n").problem

    def test_every_refusal_carries_a_fix(self) -> None:
        # A check that says what is wrong and not what to do is a check people
        # work around by rewriting the file.
        for text in ("", "version: 2\n", "version: 1\nprompts: {}\n", "version: 1\nrules:\n  a/b: x\n"):
            assert refusal(text).fix.strip()


class TestNewlines:
    def test_crlf_in_lf_out(self, tmp_path: Path) -> None:
        """The one thing the round-trip deliberately does not preserve.

        A manifest edited on Windows arrives with CRLF. Writing it back that way
        would make every later one-line edit a whole-file diff in a repository
        whose `.gitattributes` says LF.
        """
        path = tmp_path / ".akit.yaml"
        path.write_bytes(CORPUS.replace("\n", "\r\n").encode("utf-8"))
        manifest = read(path, scope=Scope.PROJECT)
        write(manifest)
        assert b"\r\n" not in path.read_bytes()
        assert path.read_text(encoding="utf-8") == CORPUS

    def test_a_lone_carriage_return_is_also_normalised(self, tmp_path: Path) -> None:
        path = tmp_path / ".akit.yaml"
        path.write_bytes(b"version: 1\rskills:\r  a/b: [x]\r")
        assert read(path, scope=Scope.PROJECT).subscriptions[0].name == "x"


class TestWriting:
    def test_it_creates_the_directory_above_it(self, tmp_path: Path) -> None:
        target = tmp_path / "nested" / "deeper" / "manifest.yaml"
        write(parsed(CORPUS), target)
        assert target.read_text(encoding="utf-8") == CORPUS

    def test_it_writes_back_where_it_was_read_from(self, tmp_path: Path) -> None:
        path = tmp_path / ".akit.yaml"
        path.write_text(CORPUS, encoding="utf-8")
        write(read(path, scope=Scope.PROJECT))
        assert path.read_text(encoding="utf-8") == CORPUS


class TestFindingThem:
    def test_yours_is_at_a_fixed_place_nothing_searches_for(self) -> None:
        assert user_manifest_path().parts[-2:] == ("akit", "manifest.yaml")

    def test_the_walk_finds_the_manifest_beside_the_git_directory(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        (tmp_path / ".akit.yaml").write_text(CORPUS, encoding="utf-8")
        deep = tmp_path / "src" / "package"
        deep.mkdir(parents=True)
        assert find_project_manifest(deep) == tmp_path / ".akit.yaml"

    def test_a_git_file_is_a_root_too(self, tmp_path: Path) -> None:
        # What a worktree and a submodule have instead of a directory.
        (tmp_path / ".git").write_text("gitdir: /elsewhere\n", encoding="utf-8")
        assert worktree_root(tmp_path) == tmp_path

    def test_the_walk_stops_at_the_first_root(self, tmp_path: Path) -> None:
        """It cannot stray into the repository that contains this one.

        The outer repository has a manifest and the inner one does not, so a walk
        that kept going would return somebody else's file.
        """
        (tmp_path / ".git").mkdir()
        (tmp_path / ".akit.yaml").write_text(CORPUS, encoding="utf-8")
        inner = tmp_path / "vendor" / "other"
        (inner / ".git").mkdir(parents=True)
        assert worktree_root(inner) == inner
        assert find_project_manifest(inner) is None

    def test_no_repository_at_all_is_not_an_error(self, tmp_path: Path) -> None:
        assert worktree_root(tmp_path) is None
        assert find_project_manifest(tmp_path) is None

    def test_a_repository_without_a_manifest_is_not_an_error(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        assert find_project_manifest(tmp_path) is None


class TestTheMerge:
    """Both files as one sequence, with nothing resolved.

    The merge tags and concatenates. It does not suppress, because the two
    scopes render into two different directories and neither can overwrite the
    other, so there is no contest to settle here.
    """

    def user_and_project(self):
        user = parse("version: 1\nskills:\n  you/kits: [writing]\nrules:\n- you/kits: yours\n", scope=Scope.USER)
        project = parse(
            "version: 1\nskills:\n  them/kits: [writing]\nrules:\n- them/kits: theirs\n", scope=Scope.PROJECT
        )
        return user, project

    def test_a_name_in_both_scopes_survives_twice(self) -> None:
        merged = merge(*self.user_and_project())
        writing = [s for s in merged.of_kind(Kind.SKILL) if s.rendered_name == "writing"]
        assert [s.scope for s in writing] == [Scope.USER, Scope.PROJECT]

    def test_the_collision_is_reported_rather_than_resolved(self) -> None:
        collisions = merge(*self.user_and_project()).collisions()
        assert set(collisions) == {(Kind.SKILL, "writing")}
        assert [s.source for s in collisions[(Kind.SKILL, "writing")]] == ["you/kits", "them/kits"]

    def test_a_wildcard_is_not_a_collision(self) -> None:
        # It names no rendered kit yet; what it expands to is T3's answer.
        user = parse('version: 1\nskills:\n  you/kits: ["*"]\n', scope=Scope.USER)
        project = parse('version: 1\nskills:\n  them/kits: ["*"]\n', scope=Scope.PROJECT)
        assert merge(user, project).collisions() == {}

    def test_a_name_used_once_is_not_a_collision(self) -> None:
        user = parse("version: 1\nskills:\n  you/kits: [writing]\n", scope=Scope.USER)
        assert merge(user, None).collisions() == {}

    def test_your_rules_come_before_the_repositorys(self) -> None:
        # Order is the only thing that decides a contradiction, and a repository
        # gets the last word on its own ground.
        merged = merge(*self.user_and_project())
        assert [s.name for s in merged.of_kind(Kind.RULE)] == ["yours", "theirs"]

    def test_swapping_the_scopes_swaps_the_order(self) -> None:
        user, project = self.user_and_project()
        assert [s.name for s in merge(project, user).of_kind(Kind.RULE)] == ["theirs", "yours"]

    def test_either_scope_may_be_missing(self) -> None:
        user, project = self.user_and_project()
        assert len(merge(user, None).subscriptions) == 2
        assert len(merge(None, project).subscriptions) == 2
        assert merge(None, None).subscriptions == ()

    def test_harnesses_are_per_scope_and_never_merged(self) -> None:
        """A subscription renders into its own scope and no other.

        So the repository's list decides what the repository gets, and yours
        decides what your machine-level directories get. Merging them would let a
        repository turn on a harness for your whole machine.
        """
        user = parse("version: 1\nharnesses: [opencode]\n", scope=Scope.USER)
        project = parse("version: 1\nharnesses: [detected, copilot-ci]\n", scope=Scope.PROJECT)
        merged = merge(user, project)
        assert merged.harnesses(Scope.USER) == ("opencode",)
        assert merged.harnesses(Scope.PROJECT) == ("detected", "copilot-ci")

    def test_an_absent_manifest_still_answers_with_the_default(self) -> None:
        assert merge(None, None).harnesses(Scope.PROJECT) == DEFAULT_HARNESSES


class TestLoadingBoth:
    """Reading uses both, always, and a missing file is not an error."""

    def test_it_reads_the_two_files_from_a_working_directory(self, tmp_path: Path) -> None:
        yours = tmp_path / "config" / "manifest.yaml"
        yours.parent.mkdir()
        yours.write_text("version: 1\nskills:\n  you/kits: [yours]\n", encoding="utf-8")
        repository = tmp_path / "repo"
        (repository / ".git").mkdir(parents=True)
        (repository / ".akit.yaml").write_text("version: 1\nskills:\n  them/kits: [theirs]\n", encoding="utf-8")
        merged = load(repository, user_path=yours)
        assert [(s.scope, s.name) for s in merged.subscriptions] == [
            (Scope.USER, "yours"),
            (Scope.PROJECT, "theirs"),
        ]

    def test_a_machine_with_no_personal_manifest_is_ordinary(self, tmp_path: Path) -> None:
        repository = tmp_path / "repo"
        (repository / ".git").mkdir(parents=True)
        (repository / ".akit.yaml").write_text("version: 1\nskills:\n  them/kits: [theirs]\n", encoding="utf-8")
        merged = load(repository, user_path=tmp_path / "absent.yaml")
        assert merged.user is None
        assert [s.name for s in merged.subscriptions] == ["theirs"]

    def test_a_repository_with_no_manifest_is_ordinary(self, tmp_path: Path) -> None:
        yours = tmp_path / "manifest.yaml"
        yours.write_text("version: 1\nskills:\n  you/kits: [yours]\n", encoding="utf-8")
        merged = load(tmp_path, user_path=yours)
        assert merged.project is None
        assert [s.name for s in merged.subscriptions] == ["yours"]

    def test_neither_file_is_an_empty_answer_rather_than_a_failure(self, tmp_path: Path) -> None:
        merged = load(tmp_path, user_path=tmp_path / "absent.yaml")
        assert merged.subscriptions == ()
