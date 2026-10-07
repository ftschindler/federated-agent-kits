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
