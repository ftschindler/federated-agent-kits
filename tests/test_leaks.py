"""The refusal that keeps the employer's kits in, row by row.

DESIGN.md section 8 is a table with two halves and this file is one test per
row of it. What makes each row a row is the combination of three facts: how
private the source is, whether the spot it lands in gets committed, and who can
read the repository. Only one of the eight combinations is a refusal, and the
value of the other seven is that they are not.

**The target is classified by its remotes and the source by how it was
fetched**, so both are simulated the way `test_cache.py` and `test_targets.py`
simulate them: a `file://` repository is public, and this machine's recorded
classification says what a fetch found. Writing the classification down directly
rather than fetching is deliberate: what is under test here is the rule, and the
learning of it has its own tests next door.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from git_environment import FIXED_AUTHOR, git, local_remote

from federated_agent_kits import cache, privacy, render, sources, subscribing
from federated_agent_kits.cache import Privacy
from federated_agent_kits.exits import Exit
from federated_agent_kits.leaks import LeakError
from federated_agent_kits.manifest import Kind
from federated_agent_kits.targets import UnreachableTargetError

pytestmark = pytest.mark.unit

SKILLS = Path(".agents") / "skills"
INSTRUCTIONS = Path(".github") / "instructions"


@pytest.fixture(autouse=True)
def house(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    for variable in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(variable, str(home))
    for variable in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        monkeypatch.delenv(variable, raising=False)
    return home


@pytest.fixture
def kits(tmp_path: Path) -> str:
    """A remote source holding one skill and one rule, standing in for the employer's.

    A remote rather than a path, because a path has no classification of its
    own: it is as public as the repository it sits in, which is why it can never
    be the private half of a leak (DESIGN.md section 8). `file://` keeps this in
    the `unit` layer while still being a source that was fetched.
    """
    return local_remote(
        tmp_path / "employer-kits",
        {
            "skills/house-style/SKILL.md": "# house style\n",
            "rules/house-style.md": "# never say seamless\n",
        },
    )


@pytest.fixture
def home(tmp_path: Path) -> Path:
    """A laptop with opencode and Copilot in VS Code on it."""
    root = tmp_path / "laptop"
    (root / ".config" / "opencode").mkdir(parents=True)
    (root / ".vscode").mkdir(parents=True)
    return root


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    git("-C", str(root), "init", "-q")
    return root


@pytest.fixture
def places(tmp_path: Path, home: Path) -> render.Directories:
    return render.Directories(
        home=home,
        user_manifest=tmp_path / "config" / "manifest.yaml",
        cache=tmp_path / "cache",
        state=tmp_path / "state",
    )


def reachable_only_by_you(house: Path, url: str) -> str:
    """A source that clones for you and for nobody anonymous, as `add` would meet it.

    The same simulation `test_cache.py` uses, because a `file://` repository
    cannot ask for a password: a rewrite in the user's own git config makes this
    URL resolve only when git is allowed to read the configuration belonging to
    the person running it, which is exactly what the anonymous attempt takes
    away. So `akit add` classifies it private by fetching it, rather than by
    being told.
    """
    private = "https://git.acme.example/team/unreleased-thing-kits"
    (house / ".gitconfig").write_text(f'[url "{url}"]\n\tinsteadOf = {private}\n', encoding="utf-8")
    return private


def mine(places: render.Directories) -> Path:
    """Your own manifest, as a path rather than as a path that might be absent.

    `Directories` lets every one of its roots default to the platform answer,
    and these fixtures always name one, so this is the narrowing rather than a
    check for something that can happen.
    """
    assert places.user_manifest is not None
    return places.user_manifest


def make_public(repository: Path, tmp_path: Path) -> None:
    """Give it a remote anybody can read, which is what makes a target public."""
    git("-C", str(repository), "remote", "add", "origin", local_remote(tmp_path / "upstream", {"README.md": "#\n"}))


def classify(places: render.Directories, source: str, found: Privacy) -> None:
    """What this machine learned when it fetched that source, written down."""
    privacy.save({source: found}, places.state)


def subscribe(
    project: Path, places: render.Directories, kits: str, *, kind: str = "skills", harnesses: str = "detected"
) -> Path:
    """One subscription, written the way each kind's schema wants it.

    Skills take a mapping and rules take a list, which is not a style choice:
    the order of rules is what the manifest promises and a mapping has none.

    The source is warmed into the cache here too, because `render` never
    fetches: an unresolved subscription reports a problem and plans no spots,
    and a refusal with nothing planned would pass for the wrong reason.
    """
    cache.resolve(sources.parse(kits), anchor=project, cache_root=places.cache)
    body = f"  {kits}: [house-style]" if kind == "skills" else f"- {kits}: house-style"
    path = project / ".akit.yaml"
    path.write_text(f"version: 1\nharnesses: [{harnesses}]\n\n{kind}:\n{body}\n", encoding="utf-8")
    return path


class TestWhatIsNotALeak:
    def test_a_public_source_into_a_public_repository_renders(
        self, project: Path, places: render.Directories, kits: str, tmp_path: Path
    ):
        make_public(project, tmp_path)
        subscribe(project, places, kits, harnesses="detected, copilot-ci")
        classify(places, kits, Privacy.PUBLIC)

        outcome = render.render(project, places)

        assert (project / SKILLS / "house-style" / "SKILL.md").is_file()
        assert outcome.exit_code is Exit.OK

    def test_a_private_source_into_a_private_repository_renders(
        self, project: Path, places: render.Directories, kits: str
    ):
        # The case the section exists to support rather than to prevent: the
        # employer's kit, committed into the employer's other repository.
        subscribe(project, places, kits, harnesses="detected, copilot-ci")
        classify(places, kits, Privacy.PRIVATE)

        outcome = render.render(project, places)

        assert (project / SKILLS / "house-style" / "SKILL.md").is_file()
        assert outcome.exit_code is Exit.OK

    def test_a_private_skill_for_a_laptop_harness_in_a_public_repository_renders(
        self, project: Path, places: render.Directories, kits: str, tmp_path: Path
    ):
        # Per harness, not per repository. Nothing here is committed: the
        # skills directory is in the ignore block for as long as every harness
        # reading it runs on somebody's machine.
        make_public(project, tmp_path)
        subscribe(project, places, kits)
        classify(places, kits, Privacy.PRIVATE)

        outcome = render.render(project, places)

        assert (project / SKILLS / "house-style" / "SKILL.md").is_file()
        assert outcome.exit_code is Exit.OK
        assert ".agents/skills/" in (project / ".gitignore").read_text(encoding="utf-8")

    def test_a_private_source_rendered_only_to_your_own_machine_is_never_asked_about(
        self, project: Path, places: render.Directories, kits: str, tmp_path: Path
    ):
        make_public(project, tmp_path)
        cache.resolve(sources.parse(kits), anchor=project, cache_root=places.cache)
        yours = mine(places)
        yours.parent.mkdir(parents=True, exist_ok=True)
        yours.write_text(f"version: 1\n\nskills:\n  {kits}: [house-style]\n", encoding="utf-8")
        classify(places, kits, Privacy.PRIVATE)

        outcome = render.render(project, places)

        assert (places.home / SKILLS / "house-style" / "SKILL.md").is_file()
        assert outcome.exit_code is Exit.OK


class TestWhatIsALeak:
    @pytest.fixture
    def leaking(self, project: Path, places: render.Directories, kits: str, tmp_path: Path) -> Path:
        make_public(project, tmp_path)
        subscribe(project, places, kits, harnesses="detected, copilot-ci")
        classify(places, kits, Privacy.PRIVATE)
        return project

    def test_a_private_skill_into_a_repository_that_commits_it_is_refused(
        self, leaking: Path, places: render.Directories
    ):
        with pytest.raises(LeakError) as refused:
            render.render(leaking, places)

        assert refused.value.exit_code is Exit.REFUSAL

    def test_the_message_names_the_source_and_the_target(self, leaking: Path, places: render.Directories, kits: str):
        with pytest.raises(LeakError) as refused:
            render.render(leaking, places)

        said = str(refused.value)
        assert str(kits) in said
        assert str(leaking) in said

    def test_there_is_no_override(self, leaking: Path, places: render.Directories):
        with pytest.raises(LeakError) as refused:
            render.render(leaking, places)

        assert "--force" not in str(refused.value)
        assert "harness remove" in str(refused.value)

    def test_the_refusal_is_total_and_nothing_is_half_written(self, leaking: Path, places: render.Directories):
        with pytest.raises(LeakError):
            render.render(leaking, places)

        assert not (leaking / SKILLS).exists()
        assert not (leaking / INSTRUCTIONS).exists()
        assert not (leaking / ".akit").exists()

    def test_a_private_rule_in_somebodys_own_file_is_refused_without_the_cloud_agent(
        self, project: Path, places: render.Directories, kits: str, tmp_path: Path
    ):
        """`AGENTS.md` is committed for reasons that have nothing to do with us.

        Which makes a block of the employer's prose inside it the first of the
        three things DESIGN.md section 8 says can actually leak, whether or not
        a machineless harness is named.
        """
        make_public(project, tmp_path)
        subscribe(project, places, kits, kind="rules")
        classify(places, kits, Privacy.PRIVATE)

        with pytest.raises(LeakError) as refused:
            render.render(project, places)

        assert "AGENTS.md" in str(refused.value)
        assert not (project / "AGENTS.md").exists()

    def test_a_source_nobody_classified_is_refused_in_the_dangerous_position(
        self, project: Path, places: render.Directories, kits: str, tmp_path: Path
    ):
        # Guessing "public" for a source this machine has no answer about is
        # exactly the guess the section forbids.
        make_public(project, tmp_path)
        subscribe(project, places, kits, harnesses="detected, copilot-ci")

        with pytest.raises(LeakError) as refused:
            render.render(project, places)

        assert "never classified" in str(refused.value)
        assert "akit update" in str(refused.value)

    def test_an_unclassified_source_is_nothing_at_all_anywhere_else(
        self, project: Path, places: render.Directories, kits: str, tmp_path: Path
    ):
        make_public(project, tmp_path)
        subscribe(project, places, kits)

        assert render.render(project, places).exit_code is Exit.OK


class TestTheOtherHalf:
    """The URL on its own, in a file the repository pushes.

    `git@git.acme.example:team/unreleased-thing.git` tells a reader the project
    exists, who is building it and roughly what it is for, whether or not they
    can clone it. So the second half of the rule is about the manifest rather
    than about anything it rendered.
    """

    def test_a_private_source_named_in_a_committed_manifest_is_refused(
        self, project: Path, places: render.Directories, kits: str, tmp_path: Path
    ):
        make_public(project, tmp_path)
        manifest = subscribe(project, places, kits)
        classify(places, kits, Privacy.PRIVATE)
        git("-C", str(project), "add", "-A")
        git("-C", str(project), *FIXED_AUTHOR, "commit", "-qm", "subscribe")

        with pytest.raises(LeakError) as refused:
            render.render(project, places)

        assert str(manifest) in str(refused.value)
        assert "--global" in str(refused.value)

    def test_the_same_manifest_uncommitted_is_nobody_elses_business(
        self, project: Path, places: render.Directories, kits: str, tmp_path: Path
    ):
        make_public(project, tmp_path)
        subscribe(project, places, kits)
        classify(places, kits, Privacy.PRIVATE)

        assert render.render(project, places).exit_code is Exit.OK


class TestTheCommandsThatCanCreateOne:
    """`add` and `harness add` are where a leak is introduced, so they refuse too.

    The render that follows each of them is what notices, which means the line
    has already been written when the refusal is raised. So the manifest is put
    back, and what the caller sees is the file it had and exit code 3.
    """

    def call(self, project: Path, places: render.Directories) -> subscribing.Call:
        return subscribing.Call(start=project, places=places, only_project=True)

    def test_naming_a_committing_harness_beside_a_private_source_is_refused(
        self, project: Path, places: render.Directories, kits: str, tmp_path: Path
    ):
        make_public(project, tmp_path)
        manifest = subscribe(project, places, kits)
        classify(places, kits, Privacy.PRIVATE)
        before = manifest.read_bytes()

        with pytest.raises(LeakError):
            subscribing.harness(self.call(project, places), action="add", name="copilot-ci")

        assert manifest.read_bytes() == before

    def test_adding_a_private_source_to_a_committing_repository_is_refused(
        self, project: Path, places: render.Directories, kits: str, house: Path, tmp_path: Path
    ):
        make_public(project, tmp_path)
        manifest = project / ".akit.yaml"
        manifest.write_text("version: 1\nharnesses: [copilot-ci]\n", encoding="utf-8")
        before = manifest.read_bytes()

        with pytest.raises(LeakError):
            subscribing.add(self.call(project, places), source=reachable_only_by_you(house, kits), name="house-style")

        assert manifest.read_bytes() == before
        assert not (project / SKILLS).exists()

    def test_a_manifest_the_command_would_have_created_is_not_left_behind(
        self, project: Path, places: render.Directories, kits: str, house: Path, tmp_path: Path
    ):
        make_public(project, tmp_path)
        (project / "AGENTS.md").write_text("# house\n", encoding="utf-8")

        with pytest.raises(LeakError):
            subscribing.add(
                self.call(project, places),
                source=reachable_only_by_you(house, kits),
                name="house-style",
                kind=Kind.RULE,
            )

        assert not (project / ".akit.yaml").exists()

    def test_the_same_add_into_a_private_repository_goes_through(
        self, project: Path, places: render.Directories, kits: str
    ):
        classify(places, kits, Privacy.PRIVATE)

        outcome = subscribing.add(self.call(project, places), source=kits, name="house-style")

        assert outcome.changed is True
        assert (project / ".akit.yaml").is_file()


class TestARemoteNobodyCanReach:
    def test_it_stops_the_render_rather_than_being_guessed_at(
        self, project: Path, places: render.Directories, kits: str, tmp_path: Path
    ):
        git("-C", str(project), "remote", "add", "origin", (tmp_path / "nowhere").as_uri())
        subscribe(project, places, kits, harnesses="detected, copilot-ci")
        classify(places, kits, Privacy.PRIVATE)

        with pytest.raises(UnreachableTargetError):
            render.render(project, places)

        assert not (project / SKILLS).exists()

    def test_a_public_source_never_asks_the_unreachable_question(
        self, project: Path, places: render.Directories, kits: str, tmp_path: Path
    ):
        # Classification is lazy, which is what keeps an ordinary render
        # offline: every source public means there is nothing to lose and no
        # question worth a network call.
        git("-C", str(project), "remote", "add", "origin", (tmp_path / "nowhere").as_uri())
        subscribe(project, places, kits, harnesses="detected, copilot-ci")
        classify(places, kits, Privacy.PUBLIC)

        assert render.render(project, places).exit_code is Exit.OK


class TestTheNoteLeaksLikeWhatItExplains:
    """DESIGN.md section 7: derived text leaks the same as copied text.

    The rename note names a kit and is written from a private source's contents,
    so a repository anybody can read must not commit one. It is not a separate
    rule: the note is recorded as wanted by the subscription that explains it,
    so the ordinary refusal reaches it. These two tests are what make that a
    fact rather than a happy accident of how the note is attributed.
    """

    @pytest.fixture
    def referring_kits(self, tmp_path: Path) -> str:
        """The employer's source, whose rule names the skill beside it."""
        return local_remote(
            tmp_path / "employer-kits",
            {
                "skills/house-style/SKILL.md": "---\nname: house-style\n---\n\n# house style\n",
                "rules/house-style.md": "---\ndescription: d\n---\n\nLoad the `house-style` skill.\n",
            },
        )

    def subscribe_renamed(self, project: Path, places: render.Directories, kits: str, harnesses: str) -> None:
        cache.resolve(sources.parse(kits), anchor=project, cache_root=places.cache)
        (project / ".akit.yaml").write_text(
            f"version: 1\nharnesses: [{harnesses}]\n\n"
            f"skills:\n  {kits}:\n  - name: house-style\n    as: acme-house-style\n\n"
            f"rules:\n- {kits}:\n    name: house-style\n    as: acme-house-style\n",
            encoding="utf-8",
        )

    def test_the_note_for_a_private_kit_is_refused_into_a_public_repository(
        self, project: Path, places: render.Directories, referring_kits: str, tmp_path: Path
    ):
        make_public(project, tmp_path)
        self.subscribe_renamed(project, places, referring_kits, "detected, copilot-ci")
        classify(places, referring_kits, Privacy.PRIVATE)

        with pytest.raises(LeakError):
            render.render(project, places)

        assert not (project / ".github" / "instructions" / "akit-renames.instructions.md").exists()

    def test_the_same_note_renders_into_the_employers_own_repository(
        self, project: Path, places: render.Directories, referring_kits: str
    ):
        self.subscribe_renamed(project, places, referring_kits, "detected, copilot-ci")
        classify(places, referring_kits, Privacy.PRIVATE)

        outcome = render.render(project, places)

        written = project / ".github" / "instructions" / "akit-renames.instructions.md"
        assert outcome.exit_code is Exit.OK
        assert "`house-style` is installed as `acme-house-style`" in written.read_text(encoding="utf-8")
