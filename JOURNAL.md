# JOURNAL

One dated entry per incident, with the actual paths, commands and output. What happened,
rather than what should be built. This is the evidence
[T14](IMPLEMENTATION.md#t14---iterate-on-what-use-earns) runs on, so an entry that records a
surprise is worth more than one that records a plan.

## 2026-10-07 - A pytest config in a file that is not `pyproject.toml` wants `[pytest]`

[T1](IMPLEMENTATION.md#t1---the-package-the-cli-frame-and-ci) asks for `tests/pytest.toml`
with the four markers. Written as `[tool.pytest.ini_options]`, which is the spelling
`pyproject.toml` uses, it parses and applies nothing.

The first symptom was loud:

```text
TypeError: tests/pytest.toml: config option 'addopts' expects a list for type 'args',
got str: '--strict-markers'
```

which is just TOML: the values have to be lists. The second symptom was not loud at all.
After switching the table to `[tool.pytest.ini_options]`, every test run printed

```text
PytestUnknownMarkWarning: Unknown pytest.mark.unit - is this a typo?
```

while `--strict-markers`, which is in that same file and exists precisely to turn an unknown
marker into an error, said nothing. Both halves had stopped being read.

In a file that is not `pyproject.toml`, pytest looks in `[pytest]`. The whole config is
either applied or silently ignored, and the ignored case leaves a suite where a marker typo
selects nothing and passes. In a per-marker CI matrix that is a layer which stops being
tested without anybody being told.

The fix is the table name, plus an assertion in `tests/test_support_scripts.py` that
`tests/pytest.toml` contains `[pytest]` and `--strict-markers`, so the silent half cannot
come back silently.

## 2026-10-07 - `akit --json list` printed prose on Python 3.14

The global flags are attached to the subparsers through an argparse `parents=` parser, so
they work on either side of the verb. The documented way to stop a subparser writing its own
default over what the main parser already parsed is `default=argparse.SUPPRESS` on the
inherited copy, with the main parser supplying the real default through `set_defaults`.

On Python 3.14.7 that is not enough:

```text
$ PYTHONPATH=src python -c "from federated_agent_kits.cli import build_parser; \
    print(build_parser().parse_args(['--json','list']))"
Namespace(json=False, verbose=False, command='list')

$ ... parse_args(['list','--json'])
Namespace(json=True, verbose=False, command='list')
```

The flag worked after the verb and was discarded before it. The failure mode is the bad one:
a model asks for `--json`, gets a paragraph of English, and nothing errors.

`src/federated_agent_kits/cli.py` now builds the shared parent twice,
`global_flags(default=False)` for the main parser and
`global_flags(default=argparse.SUPPRESS)` for every subparser, so the subparser's result
genuinely has no attribute to copy. `tests/test_cli_frame.py` parametrises both orders for
both flags.

## 2026-10-07 - A flag with a `metavar` is not a switch

`commands.py` declares each flag as data and `cli.py` hands it to argparse. The first version
inferred `action="store_true"` from "the spec starts with a dash", which is true of
`--manifest PATH` as well:

```text
TypeError: _StoreTrueAction.__init__() got an unexpected keyword argument 'metavar'
```

Thirty-two tests failed at once, which is the good version of this bug. It crashes at parser
construction, so it cannot reach a user, but it only crashes for the commands that happen to
have such a flag: `--manifest` was the only one, and three of the eight commands have it.

`Argument.takes_no_value` now asks whether the declaration was given a `metavar`, `choices`
or `nargs`, and only then is a flag a switch.

## 2026-10-07 - The version guard refused the pull request that creates the version

`release.yml`'s `🏷 (the pull request says how big it is)` job refuses a pull request that
writes the version line, because the release job owns it. The first run of it, on the pull
request that adds `pyproject.toml`, said:

```text
##[error]pyproject.toml's version is written by the release job.
Label this pull request major, minor, patch or no-release instead.
```

which is correct about the rule and wrong about this diff. The line is not being rewritten,
it is arriving.

The sibling project hit the same thing at file granularity and answered it with
`git diff --diff-filter=MD`: modifications and deletions, never additions. The same reasoning
at line granularity is that a rewrite has a `-version = line and a first appearance does
not, so`.scripts/version.py` now looks for the removal rather than for either sign.

It is not an exception that has to be remembered, which was the point of the sibling's note
and is worth repeating: after this pull request the line exists on `main`, so every further
write to it removes something and is refused.

Three tests in `tests/test_support_scripts.py` build real repositories for it, because what
is being tested is a `git diff` and a fixture string would only test the regular expression
twice: a rewrite, a first appearance, and an unrelated edit to the same file.

## 2026-10-07 - The first publish failed on a metadata version, not on a publisher

The release job on the merge of #8 did everything it was supposed to and then would not
upload:

```text
Checking dist/federated_agent_kits-0.2.0-py3-none-any.whl:
ERROR InvalidDistribution: Invalid distribution metadata: '2.5' is not a valid metadata version
```

This is the failure T1 published `0.1.0` early to find, and it is worth recording that it
looked nothing like the failure that was expected. Everything the setup notes warn about
worked on the first try: the app minted a token, the bypass entry let the version commit and
the tag through to a protected `main`, and `uv build` produced both artefacts. What broke was
a number.

hatchling writes `Metadata-Version: 2.5`, because `license = "MIT"` with `license-files` is
PEP 639 and current hatchling emits the current spec. The upload action was pinned at
`v1.13.0`, which carries `twine==6.1.0` and `packaging==25.0`, and `packaging` 25.0 has

```python
_VALID_METADATA_VERSIONS = ["1.0", "1.1", "1.2", "2.1", "2.2", "2.3", "2.4"]
```

so the client refused the file before PyPI ever saw it. `v1.14.2` carries `twine==7.0.0` and
`packaging==26.2`, which knows `2.5`. PyPI itself runs `packaging==26.3`, so the server was
never the problem: checking that before bumping was the difference between a fix and a second
failed release.

A locally built wheel passes `uvx twine check` today, which is how this stayed invisible. The
check that mattered was the pinned one in the action, and nothing on a laptop runs it.

Dependabot would have fixed this on its own schedule, which is a thin kind of luck: the
pinned-and-frozen policy makes the lag visible as a diff rather than as an outage, and here
the outage arrived first because the pin was four months old on the day it was written.

**Left behind, and not cleaned up by the job.** `0.2.0` is committed and tagged on `main` and
is on neither index. The job commits and tags, then builds, then publishes, so a publish that
fails leaves a tag naming a version nobody can install. See the note in the pull request: the
ordering is a decision about what the pipeline promises, not a bug to quietly reverse.

TestPyPI failed separately, with `invalid-publisher`, because its pending publisher had not
been added yet. That step is `continue-on-error` precisely so a rehearsal index cannot block a
release, and it behaved as designed.

## 2026-10-07 - A rehearsal that cannot stop anything, and an ordering argument I got backwards

Two corrections in one sitting, and the second is to the first.

**The rehearsal step was incoherent.** Asked directly why publish to TestPyPI at all if the
step is allowed to fail, it does not survive the question: its failure cannot stop the upload
that follows, so what it produces is a red step inside a run that succeeded, which is the
kind of signal people learn to ignore. Removing `continue-on-error` does not rescue it,
because TestPyPI expires projects and a real gate there blocks releases on an index nobody
depends on. That is why the flag was added, and adding it is what hollowed the step out.

How it got there: [T1](IMPLEMENTATION.md#t1---the-package-the-cli-frame-and-ci) asked to
publish the first version "to TestPyPI and then to PyPI", which is sensible as a one-off dry
run. It became a permanent step in every release and was then defanged.

**Then I moved the upload before the commit and the tag, and that was wrong.** The reasoning
was that the morning's failure "burned a version number". It did not. `0.2.0` was refused, so
`0.2.0` was never consumed and is still free. What it actually cost was a tag to delete.

The principle that decides the order is that the irreversible step goes last. The upload is
the only one: PyPI has no delete-and-reuse, only yank. Writing a version, committing it,
tagging it and pushing are all revocable.

- Commit and tag, then publish: a refused upload leaves a deletable tag and a free number.
- Publish, then commit and tag: a declined push leaves PyPI holding a version this repository
  never recorded, permanently. And a push to `main` declined by the ruleset is exactly the
  failure the bypass list exists to prevent, which is to say it is the plausible one.

So the order is back to where it started, and what actually fixed the morning was
`twine check --strict` before anything is written, plus the action bump. There is no
transaction across an index and a git remote; something has to be the orphan, and a deletable
tag is a better orphan than an unpublishable version.

**Where the rehearsal went instead.** Onto pull requests, as `rehearsal.yml`, where it is
free and where it gates something. It publishes `<next>.dev<run id>` to TestPyPI, installs it
back from there, and runs `akit --version` and `akit --help` against what the index served.
What that catches and nothing else does is an index saying no: a classifier warehouse
dislikes, a licence expression it will not parse, a name that normalises onto an existing
project, a metadata version the upload path does not know. That last one is this morning,
caught before a merge instead of after a tag.

It is a separate workflow file rather than a job in `release.yml` because a trusted publisher
is matched on the filename. One file reaches TestPyPI on a pull request, one reaches PyPI on
a push to `main`, and a rehearsal that could authenticate as the release would not be one.

**The version could not carry a sha, which was the first instinct and is worth writing down.**
PEP 440 wants a number in a dev segment, so `0.2.1.dev6ec3cb1` does not parse at all. The
other spelling does parse and is refused on upload:

```python
# warehouse/forklift/metadata.py
if metadata.version.local:
    errors.append(InvalidMetadata("version", f"The use of local versions in '{metadata.version}' is not allowed."))
```

A run id is the better answer regardless. An index accepts a given version exactly once and
never again, even after a deletion, so a serial that changes when a workflow is re-run on an
unchanged commit is a requirement rather than a preference. The run id links to the run,
which names the sha, so what is lost is one click.

**What the rehearsal still does not prove.** TestPyPI does not mirror PyPI, so installing
from it needs PyPI as a second index, which means the dependency-resolution leg is not shaped
like the real thing. And a pull request from a fork cannot be given an OIDC token, so there
the job builds and checks and says in an annotation that it uploaded nothing. Both are stated
in the workflow rather than left to be discovered.

## 2026-10-08 - The invocation in the README resolved somebody else's package

Every document in this repository told a reader to run the CLI through uvx by naming only the
command. The distribution is `federated-agent-kits` and the command inside it is `akit`, and
uvx reads its first argument as a distribution rather than as a command. So the instruction
asked PyPI for a project called `akit`, which exists, is at version 0.0.1, is by `lqxnjk`, and
is described as "a Python package for intelligent information bagging system".

Nobody had run it. The whole of [T1](IMPLEMENTATION.md#t1---the-package-the-cli-frame-and-ci)
went by, including a real publish and a round trip through TestPyPI, with the wrong form in
the README the entire time. What it does today is:

```text
Package `akit` does not provide any executables.
```

That is the lucky outcome. The project ships no console script, so the instruction fails
confusingly instead of running. Its owner adding one would turn the first line of this
repository's README into third-party code execution on the machine of every colleague
following a contributing guide.

**CI was never wrong, which is why nothing caught it.** `.scripts/verify-published.py` has
always built `uvx --index ... --from federated-agent-kits==<version> akit --version`, because
it had to pin an exact version to verify a release, and pinning a version forces `--from`.
The release notes in `release.yml` were correct for the same reason.
`tests/test_entry_point.py` passes a built wheel to `--from`. So every automated path
exercised the correct spelling and every human-facing sentence carried the wrong one, which
is the shape of failure worth writing down: the tests were not weak, they were testing a
different invocation from the one being documented.

**The guard, and the version of it that did not work.** The first attempt distinguished an
instruction from a mention by markup: a fenced code block is something a reader copies, an
inline code span is something a sentence is talking about, so a document could explain the
mistake without committing it. Run against `main` it found the two fenced blocks in
`README.md` and nothing in `DESIGN.md` or `IMPLEMENTATION.md`, because their occurrences were
inline. One of them was:

> **A package on PyPI, so `uvx akit render` works in a clone with nothing installed first.**

which is inline, is a promise, and is the sentence that caused all of this. Markup does not
separate a warning from a claim. So the rule became literal with no opt-out, the three
passages that explain the mistake were reworded to describe it rather than spell it, and the
only exemptions are the guard and its own test, which have to contain the form in order to
catch it.

Made literal, it immediately found an eighth site nobody had counted: a comment in
`release.yml` saying which artefact uvx resolves. Seven had been found by reading.

**What was considered and rejected.** Leading with `uv tool install federated-agent-kits`
reads better at every call site and costs the promise in [§9](DESIGN.md#how-it-ships) that a
colleague needs no install step, which is load-bearing for the clone-render-work workflow.
Renaming the distribution to match the command is not available, because the name is taken by
a real project rather than an abandoned squat. A second console script named after the
distribution would make a bare invocation work, at the price of two names to keep in step
documentation-wide, and `akit` remains what anybody types once it is installed.

## 2026-10-08 - The manifest precedence rule had nothing to decide

[T2](IMPLEMENTATION.md#t2---manifests) asks the merge to make "project wins on a clash" true.
Writing it meant asking what winning does, and there was no answer that survived being
spelled out.

The case: your manifest subscribes to a skill called `writing` from one source, and the
repository you are standing in subscribes to a different `writing` from another. [§6](DESIGN.md#6-the-manifest)
said the repository wins, "which is how a repository pins something different without you
unsubscribing".

**Nothing is overwritten, because the two never write to the same path.**
[§10](DESIGN.md#render) says a subscription renders into its own scope and no other: yours
goes to the machine-level harness directories, the repository's goes inside the repository.
Two files, two directories. So there is no file for one to win over, and the only way to make
the repository "win" is to reach up and delete from your machine-level directory on the
strength of a repository you happen to be inside.

That was the option considered and rejected. It means your own kits change depending on which
directory you are standing in, two repositories that collide differently make them flap, and
a render in one repository withdraws something you wanted for another. For a command that
runs from a git hook, that is a lot of deletion bought with a sentence.

Refusing instead was the other candidate and is worse where it matters. A collision mostly
arrives by cloning a repository or by `update` moving a pin, so nobody typed it, and the first
command somebody runs is the one the README promises is the whole setup. A refusal is total,
so one colliding name in a repository you are passing through would also stop your own
unrelated kits from rendering. And the exit code would be wrong: [§8](DESIGN.md#8-keeping-the-employers-kits-in)
reserves a refusal for a legal command declined with no override, and a collision has an
override, which is `as:`.

**So the collision is reported and never resolved.** Both copies render, `list` and `doctor`
name it, and `add` refuses the one case where somebody is present and causing it, as a usage
error rather than a refusal. [§6](DESIGN.md#two-files-one-format) now says that instead, and
`merge` in `manifest.py` concatenates and tags rather than deciding anything. The one thing
the two files do form a single sequence for is rules, where order decides a contradiction, and
there yours come first so a repository gets the last word on its own ground.

**What the code kept from the argument.** `Merged.collisions()` reports rather than resolves,
and `Merged.harnesses(scope)` deliberately does not merge the two `harnesses:` lists: a
subscription renders into its own scope, so a repository that merged lists with yours could
turn on a harness for your whole machine.

**One thing the round-trip does not preserve, on purpose.** A manifest arriving with CRLF is
written back as LF. Preserving it would be the consistent answer and would make every later
one-line edit by `akit add` a whole-file diff, in a repository whose `.gitattributes` already
says LF.

## 2026-10-08 - The round-trip tests proved the wrong thing

[T2](IMPLEMENTATION.md#t2---manifests) says the writer is "the only code that edits a file a
person owns in place, and [T7](IMPLEMENTATION.md#t7---add-remove-update-harness) depends on it
being boring". The tests written for it all parsed a corpus and dumped it unchanged, asserting
the bytes came back identical. Every one passed, and together they proved that ruamel can echo
a file, which is not the property T7 needs. The property T7 needs is that changing one thing
leaves the other thirty lines alone, and nothing tested it.

Mutating the document and dumping it found three different behaviours:

**Appending a kit to an existing entry is boring**, which is the common case for `akit add`.
The pin's comment survives, every neighbour is untouched, and the only change is that the
column padding collapses because the line it sits on got wider:

```yaml
  owner/repo#9f2c1ab: [writing, caveman, newkit] # frozen: v2
  acme/kits#4d7e08b: ["*"]                 # frozen: main, 2026-10-05
```

**Removing one is boring too**, with the alignment and the comment both intact.

**Adding a new source key is not.** ruamel attaches the blank line between two blocks to
whatever follows it, so inserting at the end of `skills:` lands the new key after that blank
line and leaves `rules:` without its separator:

```yaml
  acme/kits#4d7e08b: ["*"]                 # frozen: main, 2026-10-05

  new/source#deadbee:
  - thing
rules:                                     # order matters here, and nowhere else
```

No content is lost, the file parses, and what moved is somebody's spacing. It is left as it
is rather than fixed, for two reasons. The API that decides where a new key goes is T7's, not
T2's, and a writer that reformatted to compensate would be exactly the opposite of boring.
`tests/test_manifest.py::TestEditingInPlace` pins all three behaviours down so T7 meets the
third as a decision rather than as a surprise in a diff.

The general lesson is cheaper than the specific one: a round-trip test over an unmodified
input is a test of the library you depend on, not of the thing you are building with it.

## 2026-10-08 - Walking the root three levels deep made every rule an agent

[T3](IMPLEMENTATION.md#t3---sources-resolution-cache-discovery) implements
[§5](DESIGN.md#finding-parts-inside-one): each kind has a fixed set of directories, "each of
those is walked up to three levels deep", and the repository root is one of them for all three
kinds. Written literally, that is wrong, and the test that caught it was the dullest one in the
file:

```text
>       assert names(discovery.parts(root, Kind.AGENT)) == ["reviewer"]
E       AssertionError: assert ['prose-style', 'reviewer'] == ['reviewer']
```

The fixture holds `agents/reviewer.md` and `rules/prose-style.md`. The root is a base directory
for agents, `rules/` is one level under the root, and a rule is a markdown file, so the rule was
an agent as well. The same walk would have made every markdown file within three levels of the
root a part of two kinds: `docs/`, `.github/ISSUE_TEMPLATE/`, a vendored dependency's
`CHANGELOG.md`.

What the root is in that list for is the other sentence in the same section: a repository
holding one skill at its root is a source, "and a kit, of one part, without anybody having
decided so". That needs one level, not three. So `discovery.ROOT_LEVELS` is 1 and the three
levels apply to the named directories, which is where a `<category>/<name>` layout actually
appears.

Two consequences worth stating. A repository's own `README.md` is a rule named `README`, which
follows from the convention and is harmless: a subscription names a kit, and nobody names that
one. And a skill directory at the root of a source ties with one under `skills/`, which the
earlier entry in the list wins, because `KIND_DIRECTORIES` is written root-first.

## 2026-10-08 - The `unit` layer had to be allowed to run git

The four markers say `unit` is "the library, in a tmp_path, no network, no subprocess". T3's
three modules are a key parser, a clone cache and a directory walk, and the middle one is git.
The coverage gate is 100% branch over `src/`, measured on the `unit` layer alone, because the
other layers run the same code inside a subprocess where coverage cannot see it. Those two
sentences cannot both hold: resolution would have been either uncovered or covered against a
faked git, and a faked git proves nothing about `--depth 1`, `--unshallow` or what a credential
helper does.

So `unit` now means "no network", and it builds its repositories in its own `tmp_path` and
clones them over `file://`. That covers cloning, pinning, deepening, the offline refusals and
the privacy classification, in the fast layer, with no server. `tests/pytest.toml`,
`CONTRIBUTING.md` and the `test_unit` make target say so, the last of them because the layer
now has a prerequisite it did not have yesterday.

What stayed in `cli` is the thing a subprocess is actually needed for: that a clone lands in
*this* machine's cache directory and nowhere else, which is decided by `platformdirs` reading
the environment of the process it is in.

## 2026-10-08 - Which clone is the test, and what it costs

[§8](DESIGN.md#how-a-source-is-known-to-be-private) says cloning is the test: a source that
needed credentials is private, one that clones anonymously is public. Git offers no flag that
answers this, so it is two attempts, and the order is a trade.

Anonymous first. The first attempt runs with `GIT_CONFIG_GLOBAL` and `GIT_CONFIG_SYSTEM` at the
null device, `credential.helper=` and `core.askPass=` on the command line, and
`GIT_TERMINAL_PROMPT=0`. If that works the source is public and nothing was wasted. If it fails
the same clone is tried again with the user's git as they configured it, and a source that then
succeeds is private. A private source therefore pays for one failed attempt, which dies during
the handshake before an object moves; the reverse order would have made every public source pay
for an extra round trip.

Every clone is `--depth 1 --no-tags`, because the cache exists to hold the parts a kit is made
of rather than the history they arrived with. A pin outside that one-commit window is fetched by
name, and the forges that decline to send a commit by name get asked for the whole history
instead.

That fall back has no fixture. Fetching a commit by name is allowed by every transport a test
can build on disk, including `file://`, even with `uploadpack.allowAnySHA1InWant` explicitly
off:

```text
$ git clone -q --depth 1 --no-tags file:///tmp/dp/src c2 && cd c2
$ git fetch --depth 1 --quiet origin $FIRST; echo "rc=$?"
rc=0
```

So the test that covers it replaces `cache._git` for one call, declines the first fetch the way
a forge would, and asserts the clone still ends up holding the pin. It simulates the answer
rather than the forge, and it says so in its own docstring.

## 2026-10-08 - The federation layer reads the branch under test, not `main`

T3 is where the `federation` marker gets its first tests. Two repositories, for two different
reasons: `federated-knowledge-skills` is a layout this project does not control, and this
repository is one it does, so `tests/fixtures/kit` can be asserted by name without the test
breaking when somebody else renames a directory.

Reading this repository at `main` would have asserted about the fixture kit as it was *before*
the pull request that adds it, which is the one version guaranteed not to contain the thing
being tested. GitHub builds a pull request's checks from a branch pushed to this same
repository, so the branch is there to be cloned: the test takes `GITHUB_HEAD_REF`, falls back to
whatever is checked out locally, and skips with a reason when that branch is not on the remote
yet. Locally, before a push, four tests skip. In CI they run.

It also turned out to be the only place the subdirectory form gets exercised against a real
forge. A `file://` URL has no forge layout, so `.../tree/main/skills/writing` is not read as a
subdirectory there and the `unit` test assembles the key directly instead.

## 2026-10-08 - A long cache directory name failed as `invalid index-pack output`

The first cache slug was the whole identity, slugified and cut to 48 characters from the left.
On Linux that is a readable directory name. On the Windows job, in the `cli` layer only, four
tests failed like this:

```text
federated_agent_kits.cache.CacheError: file:///C:/Users/runneradmin/AppData/Local/Temp/
pytest-of-runneradmin/pytest-0/test_a_source_is_cloned_into_t0/kits: this source could not
be cloned
  git said: fatal: fetch-pack: invalid index-pack output
```

Nothing in that message is about path lengths, and the layer it failed in was the clue. The
`unit` layer clones into a short `tmp_path` and passed on the same runner. The `cli` layer
clones into the platform cache directory *inside a fake home inside pytest's temporary
directory*, and then git writes `.git/objects/pack/tmp_pack_*` under a directory named after a
`file://` key that is itself a long Windows path. Past 260 characters, `index-pack` fails and
git reports it as output it could not parse.

The identity is hashed into the name anyway, so the readable half is only for somebody looking
at their own cache directory. It is now the *tail* of the identity rather than the head, capped
at 24 characters: `owner-repo-620c3a937ce8`, and `unreleased-thing-kits-0432fbcd388a` where the
owner does not fit. The host, which is the part every entry from one forge shares, is the part
worth losing.

The general lesson is the one the Windows job exists for. This is not a bug care would have
avoided, it is one a second operating system found, and it surfaced two layers away from where
it was made.

## 2026-10-08 - A test about the past that pinned a moving ref

Three tests failed on the branch for [T4](IMPLEMENTATION.md#t4---adapters-detection-and-akit-list)
before a line of T4 was written, and one of them had nothing to do with T4:

```text
FAILED tests/test_support_scripts.py::TestTheUvxInvocationGuard::
  test_it_would_have_caught_the_documents_it_was_written_for
AssertionError: README.md should have offended
```

The test runs `.scripts/check_uvx_invocation.py` against `git show main:README.md` and asserts
it finds the bare `uvx akit` form, which is the thing the guard was written to catch. It was
true when it was written, on a branch whose `main` still carried the offending sentences. Then
that branch merged, `main` stopped offending, and the test became an assertion that this
repository has never been fixed.

The failure mode is worth naming because it is quiet in the other direction: the test went red
on the next branch somebody opened, two tasks later, with a message about a document that
branch did not touch. A test about history has to name a commit that is already history, so it
now reads `cf2618e3`, the parent of the commit that added the guard. The documents at that
revision offend on nine lines between them, and they will offend on those nine lines forever.

## 2026-10-08 - Two decisions T4 made that DESIGN.md left to whoever got there first

**VS Code's user-wide skills directory.** [DESIGN.md](DESIGN.md#what-github-copilot-in-vs-code-looks-like) marks
this "varies, and this is the weak leg", which is accurate about the documentation and not an
answer an adapter can hold: a kit subscribed in your own manifest has to land *somewhere* or
user-scope subscriptions silently do nothing for anybody using VS Code. The adapter writes
`~/.claude/skills/`, which is the Claude-compatible directory the same harness already reads at
project scope, and lists `~/.copilot/skills/` and `~/.agents/skills/` beside it as read-only
candidates. If that is wrong it is one line in `src/federated_agent_kits/adapters/vscode.py`,
which is the only claim an adapter actually makes.

The cost is visible in `akit list` and is worth stating: opencode writes skills to
`.agents/skills/` and VS Code to `.claude/skills/`, so a machine with both gets two copies of
one skill. [DESIGN.md](DESIGN.md#one-copy-where-the-bytes-agree-one-per-harness-where-they-do-not)
permits that - one copy per harness where the directories do not agree - but
[T5](IMPLEMENTATION.md#t5---the-render-engine-and-skills) is written as though
`.agents/skills/` were the single destination, and it is not. The first evidence that VS Code
reads `.agents/skills/` collapses the two.

**The render record arrived half a task early.** `akit list` is specified to read the render
record, and nothing writes one until [T5](IMPLEMENTATION.md#t5---the-render-engine-and-skills).
The alternative was for `list` to decide "rendered" from whether the target path happens to
exist, which is a second and quieter definition of the word: it says yes to a skill somebody
copied in by hand, and the two definitions would disagree the first time that happened. So
`src/federated_agent_kits/record.py` ships with T4 holding the schema and the reader, T5 adds
the writer, and the fixtures in `tests/test_record.py` are the JSON written out by hand -
which is the point rather than a shortcut, since what two tasks have to agree on is the file.

## 2026-10-08 - The Windows job found a fixture that only knew where Linux keeps things

The `cli` layer's snapshot of `akit list` passed on Linux and failed on the Windows runner
twice over, and only one of the two was about separators.

The loud half was cosmetic. The snapshot was written with `/` in it and Windows prints
`<repo>\.agents\skills\writing`. `fixed()` now normalises separators wholesale before
comparing: what the snapshot is for is the report's sentences, and that a path is spelled with
backslashes is `pathlib`'s business and is asserted in the tests that compare paths.

The quiet half was a real bug in the fixture, and it is the one worth the entry:

```text
-   skills "writing" is wanted by <my-kits> (your manifest) and <remote> (this repository)
+   none
```

The user manifest had vanished, taking the collision and a whole subscription with it. The
fixture wrote it to `<home>/.config/akit/manifest.yaml`, which is where it lives on Linux.
`manifest.user_manifest_path()` asks `platformdirs` with `roaming=True`, so on Windows it is
under `%APPDATA%`, and the file the fixture wrote was simply never read. Nothing failed: the
command reported a machine with no personal manifest, which is an ordinary state.

This is the failure mode [DESIGN.md](DESIGN.md#9-windows-linux-python) names - the Linux answer
written down as if it were the only one - committed in a test rather than in `src/`, which is
the place it cannot be caught by the thing it is testing. The fixture now asks the package
where both the manifest and the cache go and uses the answer, so the test reads whatever the
platform decided.

## 2026-10-08 - The VS Code adapter was named after the editor, and read a year-old snapshot

Two corrections to yesterday's entry, both from review, and both because
[§4](DESIGN.md#4-adding-a-harness)'s worked examples are a snapshot that had aged without
anybody checking.

**It is `copilot-vscode`, not `vscode`.** The question that settled it was whether Copilot had
been absorbed into the editor far enough for the two to be synonyms. It has not. VS Code 1.116
stopped making new users install the Copilot extension, so a stock download has it, but it is
still an extension and still has to be signed in to. Meanwhile the editor hosts several other
agent harnesses that agree with Copilot about nothing: Cline reads `.cline/skills/`, Roo Code
`.roo/skills/`, the Claude Code extension `.claude/skills/`, and Amazon Q has
`.amazonq/rules/` and no skills at all. VS Code's own documentation now has a page about
"agent harnesses", plural. An adapter named `vscode` would have claimed the id for whichever
of those was written first and left the second needing a name that sounded like a subtype of
it.

**And `.claude/skills/` was the wrong directory.** Yesterday's entry recorded a decision to
write user-scope skills to `~/.claude/skills/` because DESIGN.md called the location "varies,
and this is the weak leg", and recorded the cost: two copies of every skill on a machine with
both harnesses. That cost was imaginary. Agent Skills arrived experimentally in VS Code 1.108
behind `chat.useAgentSkills` and went generally available in 1.109, and the documented
locations are `.agents/skills/`, `.github/skills/` and `.claude/skills/` at project scope and
`~/.agents/skills/`, `~/.copilot/skills/` and `~/.claude/skills/` personally. The first of each
is the directory opencode already writes. So the adapter writes `.agents/skills/` at both
scopes, one skill is one copy, and
[§7](DESIGN.md#one-copy-where-the-bytes-agree-one-per-harness-where-they-do-not)'s preference
for one copy is the ordinary case rather than a lucky one.

`tests/test_adapters.py` now asserts both halves directly: every shipped adapter puts a skill
in one place, and none of them puts a rule there.

DESIGN.md's VS Code section is rewritten rather than annotated, because it is explicitly a
snapshot and a snapshot that is known to be wrong is worse than no snapshot. T5's bullet in
IMPLEMENTATION.md goes back to the single directory it originally named.

There is a `chat.agentSkillsLocations` setting that would make skills the pointed shape, and
it is deprecated and honoured only by the Local agent - which is the same sentence, with the
same ending, as the one already written about `chat.instructionsFilesLocations`. Twice is a
pattern: a configurable path in this harness is a path Agent Host will not read.

**The lesson is about the snapshot, not about Copilot.** Both errors were in DESIGN.md before
they were in code, and T4 copied them faithfully. "Every path in §4 will move" is written in
two places in IMPLEMENTATION.md, and what neither said is that an adapter task has to go and
look. It now says so in "What every task delivers", so it binds every task rather than only
the one that writes the guide.

## 2026-10-08 - Rendering in one repository deleted another repository's files

[T5](IMPLEMENTATION.md#t5---the-render-engine-and-skills)'s withdrawal rule was written
against the scope a file belongs to, which is what the render record carries. The unit layer
agreed with it for twelve tests. The `cli` layer, which renders twice in two repositories in
one fake home, did not:

```text
E       AssertionError: assert {} == {'writing/SKILL.md': ...}
E         Right contains 2 more items
```

The empty side is the repository rendered *first*. Both checkouts are project scope, both
their rendered files were in the record, and the second render found the first one's files
sitting in the record with a scope it was rendering and nothing in *this* repository's
manifest explaining them. So it deleted them, reported the deletion in full sentences, and
exited 0.

The rule was right about scope and silent about place. A record is machine-wide and a render
happens somewhere: your home directory holds one set of directories, and every repository on
this disk holds its own. `render._territory` is the missing half - the directories this
particular run is responsible for, computed from every registered adapter anchored at this
render's roots - and withdrawal now needs a file to be inside it as well as in a scope it is
rendering.

Every registered adapter rather than the chosen ones, deliberately. Withdrawal has to reach
the files of a harness that has just left the `harnesses:` list, which is exactly the moment
the chosen list stops naming it, and that is what `akit harness remove` will be in
[T7](IMPLEMENTATION.md#t7---add-remove-update-harness).

**What found it was a layer, not a test.** Nothing in the unit layer renders twice in two
places, because a unit test builds the setup it is about and this bug needs two setups that
have nothing to do with each other. The `cli` layer gets that for free: one fake home, several
repositories in it, which is also what a laptop is.

## 2026-10-08 - The ignore block listed a directory that had stopped being rendered

A smaller correction from the same test run, and the first version of it read reasonably.
The `.gitignore` block was computed from the directories the adapters in scope declare, which
is a list that changes only when a harness is installed or named.

[DESIGN.md](DESIGN.md#what-a-repository-commits) asks for something else: "a directory that
stops being rendered leaves the block on the next render". An adapter-shaped list cannot do
that. It would go on ignoring `.agents/skills/` for as long as opencode was installed, whether
or not anything of ours had ever been in it, which makes the block a statement about this
machine rather than about this repository.

So the block is now computed from the render record: a directory is listed when something the
record explains is inside it. The two differ only in the case that matters, which is why the
first version passed every test except the one that withdrew everything and then looked.

## 2026-10-08 - opencode kept the key and stopped loading it

A question about a detail found a harness moving underneath the design, which is twice in
three days and the second entry of this kind.

The detail: what the adapter should do when somebody's `instructions` array holds explicit
paths and no glob. Checking opencode's documentation rather than answering from the design
settled it immediately, because the documented example is already a mixed array:

```json
{ "instructions": ["CONTRIBUTING.md", "docs/guidelines.md", ".cursor/rules/*.md"] }
```

So one glob of ours sits beside somebody's explicit paths, and nothing has to adapt. The same
page answered a question nobody had asked yet. From the [v2 config
docs](https://opencode.ai/v2/docs/config/):

> OpenCode accepts this field but does not load its entries; use `AGENTS.md` for instructions.

And from the [v2 instructions docs](https://opencode.ai/v2/docs/instructions/):

> The V2 config schema accepts an `instructions` array, but V2 does not currently resolve its
> files, glob patterns, or URLs.

[DESIGN.md](DESIGN.md#what-opencode-looks-like) had opencode as the second rule shape, pointed
once at `.opencode/instructions/` and never edited again, which was the pleasant answer and
the one [§7](DESIGN.md#rules-and-the-three-ways-a-harness-can-take-them) prefers. On v2 that
renders files, writes a config key, and produces an agent that never sees any of it. The
files are there, the command exits 0, and nothing fails.

`AGENTS.md` is read by v1 and v2 both, so opencode is now the third shape: one file shared
with the user, each rule between its own markers. [§4](DESIGN.md#what-opencode-looks-like) and
[§7](DESIGN.md#rules-and-the-three-ways-a-harness-can-take-them) are rewritten rather than
annotated, and `src/federated_agent_kits/adapters/opencode.py` with them, because a snapshot
known to be wrong is worse than no snapshot. The adapter contract test caught the change by
itself: it asserted every rule is a file named after the rule, which was an assertion that no
adapter is ever the third shape.

**Calibration, because the fix is not urgent in the way it reads.** The latest release is
`v1.18.35`, published two days ago, and there is no v2 tag. The pointed shape works for
everybody running opencode today. What it has is an expiry date and a silent failure at the
end of it.

Two things fell out of the same hour and are worth recording beside it.

**`.agents/skills/` survives.** v2's skill discovery lists `.agents/skills` and
`~/.agents/skills` as compatibility sources, so what T5 shipped is read by both versions. The
alarm was raised and is closed.

**A glob's expansion order is not defined.** opencode preserves the order of entries in the
`instructions` array, and the order of files matched by one pattern is whatever the glob
implementation returns. Rules are the one kind with an order
([§7](DESIGN.md#rules-and-the-three-ways-a-harness-can-take-them)), so wherever a harness
reads a directory of ours, manifest order has to be carried by the filenames. That is T6's to
settle and nothing in DESIGN.md says it yet.

**The standing lesson.** [IMPLEMENTATION.md](IMPLEMENTATION.md)'s "What every task delivers"
already says a task reads the harness's documentation before writing a path. Both times it
has been followed, it has paid for itself within the hour, and both times the trigger was
somebody asking an unrelated question rather than a scheduled check. That is the evidence
[T14](IMPLEMENTATION.md#t14---iterate-on-what-use-earns) wants for deciding whether this needs
a test that reads documentation rather than a habit that remembers to.

## 2026-10-08 - Copilot declines to promise an order, and ignores a rule with no frontmatter

Asking how manifest order survives a directory read produced two answers from one page of
Copilot's documentation, and the one nobody asked for is the expensive one.

On order, under "Resolve conflicting instructions":

> Applicable instruction sources are additive. Do not depend on a file order or precedence
> rule to resolve conflicts because discovery and merge behavior can differ by harness.

A numeric filename prefix is a bet against a sentence written to stop people making it. So
[§7](DESIGN.md#rules-and-the-three-ways-a-harness-can-take-them)'s promise is narrowed to what
it could always deliver: manifest order holds across the text we write, and a harness that
reads a directory decides the rest. `akit list` says which of the two each harness is, so
nobody learns it from behaviour.

Narrowing it costs less than it looks, because the wider promise was never true. Copilot
merges organisation, user and repository instructions additively, so even one file of ours is
one contribution among several we never see.

The finding nobody was looking for is what `.github/instructions/` actually is:

> If you omit both `description` and `applyTo`, attach the file manually when you want to use
> it.

Those are *targeted* instructions. A rule rendered there as a bare body is discovered, listed
in the customizations editor, and never loaded. T6 would have shipped a renderer whose output
was inert for one of the three harnesses, and every test would have passed, because the files
are exactly where the adapter says they go.

So every Copilot rule carries `applyTo: '**'`, and [§12](DESIGN.md#12-still-open)'s open
question is sharpened rather than answered: `applyTo` is not a field we may decline, it is the
switch that makes a rule always-on, and what is still open is whether any real rule wants a
glob narrower than everything.

**Three for three.** Every time this project has read a harness's documentation before writing
a path, it has found something that would have failed silently. opencode's `instructions` key,
Copilot's directory, and now Copilot's frontmatter. The pattern in all three is identical: the
files land where the adapter promised, the command exits 0, and the agent behaves as if
nothing was rendered.

## 2026-10-08 - One record for the machine was three bugs wearing a coat

The render record started as one file in the state directory covering everything `akit` had
written anywhere on this disk. Fixing a bug in it produced a check, then the check needed a
schema field to survive adapters moving their directories, and the second layer of repair is
what prompted the question that killed the design: is one record right at all?

It was not, and the evidence was already written down. Three separate problems, one cause.

**Two repositories rendering at once overwrote each other.** `record.save` writes the file
whole with no lock. Two pre-commit hooks in two checkouts is not an exotic case, it is the
headline use for `render`, and the loser's entries vanish while its files stay on disk. They
become orphans only `--prune` can reach, and `--prune` is the one deletion this tool cannot
prove is safe.

**A deleted repository left entries nothing could collect.** Withdrawal only runs in the root
an entry belongs to, so once that root is gone the entry is unreachable forever. The file
grew monotonically with every repository anybody had ever rendered in.

**A render in one repository could withdraw another's files.** That one shipped, and
[the entry above](#2026-10-08---rendering-in-one-repository-deleted-another-repositorys-files)
has it. Scope says which manifest, not which checkout, so from inside repository A every file
B rendered looked unexplained.

All three are the same sentence: a record entry belongs to a root, and the file had been
deliberately separated from the root it belonged to.

So there is one record per scope root now. Yours stays in the state directory. A repository's
moves inside the repository, at `.akit/render.json`, which gives it the lifetime of its
subject: delete the checkout and it goes, move the checkout and it moves. The containment
check and the anchor field that was going to shore it up both disappeared, because the record
you can open is the record you are responsible for.

**Two things fell out that are worth more than the fix.**

The source classifications had to leave. They record how private each remote source was when
it was fetched, which is a fact about the cache and about a source key, true however many
repositories subscribe to it. One record made that easy to overlook. N records make it either
the same fact stored once per project or one record being the odd one that also carries
machine state, so it now has its own file beside them, `sources.json`, with one job.

And the split broke a case the single record had been handling correctly without anybody
noticing. [DESIGN.md](DESIGN.md#two-files-one-format) said the two scopes never write to the
same place. For a home directory that is also a git repository, which is what dotfiles are,
that is false: the project anchor and your home directory are one directory, so both scopes
land in `~/.agents/skills/`. One entry with two explanations handled it. Two records each
claim the path and neither can see the other, so `akit render --global` would have deleted a
file the repository still wanted. Withdrawal now reads the sibling record before deleting
anything.

**The lesson is about which bugs are worth a redesign.** The first fix was a check, and it
worked. What it could not do was explain why the check was needed, and a check you cannot
derive from the shape of the data is usually a shape that is wrong. Three unrelated-looking
symptoms with one cause is the signal, and all three were visible before the redesign: two of
them had simply never been written down as problems.
