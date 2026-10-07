# IMPLEMENTATION - federated-agent-kits

**Status:** the plan of record. [DESIGN.md](DESIGN.md) remains the sole source of truth for
*what* gets built; this document says *in which order*, *what each piece has to prove*, and
*when* each open question is answered.

**Section references.** A `§N` link points at the matching section of [DESIGN.md](DESIGN.md).

This plan assumes nothing from this repository except [DESIGN.md](DESIGN.md) and this file. A
fresh session should be able to start at any unticked task and know what it owns.

**Two kinds and three harnesses ship with 1.0.** Skills and rules, into opencode, VS Code and
GitHub Copilot in CI. The first two harnesses are built in
[T4](#t4---adapters-detection-and-akit-list), the third in
[T8](#t8---the-machineless-harness-and-the-leak-refusal), and between them they cover both
halves of [§4](DESIGN.md#4-adding-a-harness): a harness with a machine and one without.

**Agents come after the release**, in [T13](#t13---agents). They are the kind that does not
travel: [§7](DESIGN.md#agents-are-the-hard-one) has every harness disagreeing about frontmatter
keys, tool names and what an agent is even for, while a kit is made of skills and rules almost
every time. Every adapter shipped in 1.0 therefore declines the agent kind, which
[§4](DESIGN.md#4-adding-a-harness) already calls a valid answer, and the CLI says so rather
than failing.

**A fourth harness is a guide rather than an adapter.** What makes "a harness is a file, not a
branch" useful is somebody else being able to write one, so
[T10](#t10---adding-an-adapter-documented) ships the how-to and the test that enforces it, with
pi as its worked example. Shipping a pi adapter this project does not use would be maintenance
with no user.

**The end state is a published package.** `federated-agent-kits` on PyPI, exposing one entry
point named `akit`, so that `uvx --from federated-agent-kits akit render` works in a fresh
clone with nothing installed
([§9](DESIGN.md#how-it-ships)). That is a contract, not a milestone: every task below either
builds a part of it or keeps it releasable.

## Status

- [x] **[T1](#t1---the-package-the-cli-frame-and-ci)** - The package, the CLI frame, and CI
- [x] **[T2](#t2---manifests)** - Manifests
- [x] **[T3](#t3---sources-resolution-cache-discovery)** - Sources: resolution, cache, discovery
- [ ] **[T4](#t4---adapters-detection-and-akit-list)** - Adapters, detection, and `akit list`
- [ ] **[T5](#t5---the-render-engine-and-skills)** - The render engine, and skills
- [ ] **[T6](#t6---rules)** - Rules
- [ ] **[T7](#t7---add-remove-update-harness)** - `add`, `remove`, `update`, `harness`
- [ ] **[T8](#t8---the-machineless-harness-and-the-leak-refusal)** - The machineless harness, and the leak refusal
- [ ] **[T9](#t9---doctor)** - `doctor`
- [ ] **[T10](#t10---adding-an-adapter-documented)** - Adding an adapter, documented
- [ ] **[T11](#t11---the-skill-and-the-rule)** - The skill, and the rule
- [ ] **[T12](#t12---publish-10)** - Publish 1.0
- [ ] **[T13](#t13---agents)** - Agents, *after 1.0*
- [ ] **[T14](#t14---iterate-on-what-use-earns)** - Iterate on what use earns, *open-ended*

## How to use it

**Build the whole package first, iterate afterwards.** An earlier version of this plan gated
each task on weeks of real use. That is the right habit for a tool somebody already depends
on and the wrong one for a tool that does not exist yet: it would leave a half-built CLI on
disk for a month. So T1 to T12 are written to be implemented in short order, each in its own
session, and the evidence that a task is done is its test suite rather than a fortnight of
usage. [T14](#t14---iterate-on-what-use-earns) is where usage gets to change things.

**One task is one session, and one pull request.** A task names what it owns, what it must
not touch, and the interfaces it leaves behind for the next one. A session that finds itself
editing another task's files has either found a design bug, which goes in the journal and into
[DESIGN.md](DESIGN.md), or has drifted.

**Order is a dependency graph, not a queue.** Each task names what it needs. T6, T9 and T10
are independent of each other once T5 exists, so they can run in any order or at once in
separate worktrees.

**The repository stays releasable from T1.** Every task ends with a green suite on both
operating systems and a version that can ship. A task that cannot be released on its own is
too large, and splitting it is part of doing it.

**Answer an open question only when a task forces it.** Every task names which of
[§12](DESIGN.md#12-still-open) it settles and which it must leave alone.

**Keep a journal from T1.** `JOURNAL.md` beside this file, one dated entry per incident, with
the actual paths, commands and output. Record what happened rather than what should be built,
name the artefacts, and say what was done instead. It is the evidence that
[T14](#t14---iterate-on-what-use-earns) runs on.

## Before starting

A fresh session needs five things, three of which are not in this repository.

| What | Where | Why |
| --- | --- | --- |
| The design | [DESIGN.md](DESIGN.md) | Every schema, path and refusal is specified there |
| The sibling project | `~/Projects/public/federated-knowledge-skills` | Its `tests/` carry the fake-home, git-environment and disposable-agent harnesses this project ports rather than reinvents, and its `.github/workflows/` carry the label-driven release this project copies |
| The `skills` CLI discovery rules | its npm README, section "Skill Discovery" | [§5](DESIGN.md#5-sources) follows them and does not restate the full list |
| Harness documentation | opencode, VS Code, pi, GitHub Copilot | [§4](DESIGN.md#4-adding-a-harness) is a snapshot, not a substitute, and every path in it will move |
| The guard suite | this repository | `make bootstrap`, then `make check` |

Two constraints bind every task and are easy to breach without noticing. **Python only**, and
**Windows and Linux equally**, both spelled out in [§9](DESIGN.md#9-windows-linux-python). The
second is not satisfied by care. It is satisfied by the CI matrix
[T1](#t1---the-package-the-cli-frame-and-ci) adds, which every later task keeps green.

## What every task delivers

These are not repeated under each task. A task is not done without them.

**Tests that could fail.** Every behaviour the task adds has a test that fails when the
behaviour is removed. Coverage is measured with branch coverage and the gate is 100% of
`src/`, with `# pragma: no cover` allowed only on a line that names why in the same comment.
A task that cannot reach the gate says so in the journal rather than lowering it.

**The four test layers**, each in its own marker so CI can run them as separate jobs:

| Marker | What it is | Needs |
| --- | --- | --- |
| `unit` | the library, in a `tmp_path`, no network | nothing |
| `cli` | `akit` as a subprocess in a fake home, against local `file://` sources | git |
| `federation` | the same commands against two real public repositories | network |
| `agent` | a disposable agent that reads the skill and types what it says | network, node |

The `cli` layer is where most of this project's tests live, because almost everything it does
is a file on disk and a process's exit code. Local git repositories over `file://` cover
cloning, pinning and private-looking sources without anybody's server
([T3](#t3---sources-resolution-cache-discovery)).

**Isolation that holds on both operating systems.** `HOME`, `USERPROFILE` and every `XDG_*`
point inside the test's own directory, so a bug cannot reach the developer's real config,
cache or state directory. Git gets the same treatment: no user config, no credential helper,
a fixed author. Both harnesses are ports of the sibling project's `fake_home.py` and
`git_environment.py`.

**Help text good enough that a skill needs almost nothing.** [§11](DESIGN.md#11-the-skill)
puts everything deterministic in the CLI, so the CLI has to carry it. The contract, enforced
by a test over every registered command in [T1](#t1---the-package-the-cli-frame-and-ci):

- one sentence saying what the command does, then a paragraph saying what it writes and what
  it never writes;
- at least one worked example, with real-looking arguments;
- every flag documented in one line, including what it refuses to do;
- a closing `Next:` line naming the command somebody usually runs after this one;
- `akit help <topic>` for the four things that are not commands: `manifest`, `sources`,
  `harnesses`, `privacy`.

**Output a person and a model can both read.** Every command prints what it did in full
sentences, grouped by scope, and takes `--json` for the same information as data. Nothing is
silent on success: a no-op says it was a no-op. Every refusal names the source, the target
and the command that fixes it ([§3](DESIGN.md#3-rules-of-the-build), rule 5).

**Windows-safe by construction.** `pathlib.Path` throughout, `encoding="utf-8"` stated out
loud, no symlink ever created, no shell, no `&&`, no assumption that `make` exists.

**Documentation that ships with the change.** `README.md` and the command's own help are part
of the diff, never a follow-up.

## T1 - The package, the CLI frame, and CI

**Goal.** `uvx --from federated-agent-kits akit --help` works from a clone, and everything a
later task writes lands in a
tested, released package.

**Needs.** Nothing.

**Deliverable.** The distribution, the CLI skeleton, the test harness, and three workflows.

**Build.**

- `pyproject.toml`: name `federated-agent-kits`, hatchling, `src/federated_agent_kits/`,
  `requires-python = ">=3.11"`, one console script `akit`. Dependencies kept to what the
  design forces: a YAML round-tripper that preserves comments ([§6](DESIGN.md#6-the-manifest))
  and the platform directory lookup. No lockfile of our own
  ([§9](DESIGN.md#9-windows-linux-python)).
- The CLI frame: `akit` with subcommands registered in one place, `--version`, `--json`,
  `--verbose`, and the help contract above. Argument parsing only; every verb prints "not
  implemented yet" and exits 2 until its task lands, and a test asserts that list shrinks to
  empty by [T12](#t12---publish-10).
- Exit codes, defined once and tested: 0 fine, 1 something is wrong, 2 usage, 3 a refusal
  ([§8](DESIGN.md#8-keeping-the-employers-kits-in)). A refusal is not a usage error and the
  caller has to be able to tell.
- `tests/fake_home.py` and `tests/git_environment.py`, ported from the sibling project.
- `tests/pytest.toml` with the four markers, and `.scripts/run-tests.py <marker>` so make, the
  hooks and CI share one code path on every platform.
- `tests.yml`: a job per marker across `ubuntu-latest` and `windows-latest`, plus a fixed-name
  `tests` job that fails unless every matrix job succeeded, which is the one branch protection
  requires.
- **The naming pattern every workflow follows**, because a required check is named after the
  job and a job whose name moves is a protection rule that silently stops protecting. A
  workflow's `name:` is one short noun, `Governance`, `Tests`, `Release`. A job's `name:` is an
  emoji, a space, and a lowercase description in brackets: `🩺 (run governance checks)`,
  `🛠 (Tests)`. The aggregate job's name is fixed and the matrix jobs' names are not, which is
  the whole reason the aggregate exists: a matrix job's check is named after the axis it ran
  on, so requiring one directly means editing the rule every time the matrix changes, and a
  job that stops being produced does not fail the rule, it stops being required.
- **Add `🛠 (Tests)` to the ruleset on `main` when that job first reports.** The ruleset exists
  and currently requires only `🩺 (run governance checks)`, because a required check that never
  reports blocks every merge. This is a by-hand, admin-only step and it is part of this task
  rather than a follow-up.
- `governance.yml` gains ruff and a strict type check over `src/` and `tests/`.
- `release.yml`, copied from the sibling and retargeted: exactly one of `major`, `minor`,
  `patch`, `no-release` on every pull request; on merge the bot writes the version, tags it,
  and publishes to PyPI with trusted publishing. The version lives in `pyproject.toml` and is
  readable at runtime from package metadata, so `akit --version` and the skill's `VERSION`
  file ([T11](#t11---the-skill-and-the-rule)) cannot disagree.
- **The release job needs a bypass actor, and nothing else does.** `main` requires a pull
  request, and this job pushes a version commit and a tag straight to it, so the token it is
  handed by default is refused: that token is deliberately not allowed to bypass rules, which
  is the right default everywhere except here. The arrangement, copied from the sibling, is a
  GitHub App installed on this repository holding `contents: write`, two secrets carrying its
  client id and private key, and an entry for the app in the ruleset's bypass list. The last
  of those is not a permission, is the one that gets forgotten, and without it the job pushes
  and is declined. All four steps are by hand, once, by somebody with admin, and they are part
  of this task: a release pipeline that cannot push is not a release pipeline.
- Publish at the end of this task. An unpublished package is an untested release pipeline,
  and the first real publish is the one that finds the misconfigured name, the missing
  classifier and the trusted-publisher mismatch. It found a fourth thing, which
  [JOURNAL.md](JOURNAL.md) records.
- **The rehearsal upload belongs on a pull request, not in the release.** An earlier draft of
  this bullet said TestPyPI and then PyPI, in the release job. Allowed to fail, such a step
  protects nothing, because its failure cannot stop the upload that follows it. Not allowed
  to fail, it blocks releases on an index that expires its projects. On a pull request it is
  free and it gates something: `rehearsal.yml` publishes `<next>.dev<run id>` to TestPyPI,
  installs it back from there and runs it, which is the only way to learn before merging
  whether an index will accept this package at all.
- **The release publishes last.** The upload is the only step that cannot be undone, so the
  version is written, built, checked, committed and tagged first, and published after. A
  failure then leaves a deletable tag and a version number still free, which is the cheaper
  of the two orphans available: there is no transaction across an index and a git remote.

**Tests.** The help contract over every registered command. `--version` matches the installed
metadata. Every exit code. The fake home cannot see the real `HOME` on either platform, with
the `XDG` fallback branch exercised on purpose. A `cli` test that installs the built wheel
into a throwaway environment and runs `akit --help` from it, so the entry point is tested as a
user meets it rather than as an import.

**Done when.** `uvx --from dist/*.whl akit --help` prints the frame on both operating systems,
CI is green, and `pip install federated-agent-kits==0.1.0` gets you an `akit` that says what
it cannot do yet.

**Settles.** The CI matrix half of [§9](DESIGN.md#9-windows-linux-python), and the release
mechanism for everything after it.

**Leave alone.** Every behaviour. This task is the floor the others stand on, and a verb
implemented here is a verb implemented without its tests.

## T2 - Manifests

**Goal.** The file people edit is read, written and round-tripped without losing a comment.

**Needs.** [T1](#t1---the-package-the-cli-frame-and-ci).

**Deliverable.** The manifest model, the two-scope reader, the comment-preserving writer, and
`akit help manifest`.

**Specified by DESIGN.md.** The schema, the mapping-versus-list asymmetry, `as:`, the
`harnesses:` key, the two files and their precedence, and how each is found
([§6](DESIGN.md#6-the-manifest)).

**Build.**

- Parse `version: 1`, the three kind blocks, a string or a mapping per entry, `as:`, and the
  `harnesses:` list. A key carries an optional `#<commit>`; the comment beside it is data to
  nobody and is preserved verbatim.
- Find the user manifest in the per-platform config directory, and the project one by walking
  up to the worktree root and looking beside its `.git`. The walk stops there, so it can never
  reach another repository or the user manifest.
- Merge: project adds to user, project wins on a clash, and the result remembers which scope
  each subscription came from, because [§10](DESIGN.md#10-commands) renders them to different
  places.
- Write with comments, key order and layout preserved. This is the only code that edits a file
  a person owns in place, and [T7](#t7---add-remove-update-harness) depends on it being
  boring.
- Rejections with a line number and a fix: an unknown kind, a duplicate name within a scope,
  `rules:` written as a mapping, a `version` we do not know.

**Tests.** A round-trip property test: parse then write an unmodified manifest and get the
same bytes, over a corpus that includes every form in [§6](DESIGN.md#6-the-manifest). A
written pin keeps its comment. Precedence in both directions. The walk refuses to leave the
worktree, including from a nested worktree and a submodule. Every rejection, one test each.
CRLF in, LF out, on both platforms.

**Done when.** The corpus round-trips byte for byte, and the merge reports its scopes.

**Leave alone.** Resolution. A manifest knows what you asked for and never where it is
([§6](DESIGN.md#where-a-source-actually-is)).

## T3 - Sources: resolution, cache, discovery

**Goal.** Turn a key into a directory on this disk, and find the parts inside it.

**Needs.** [T2](#t2---manifests).

**Deliverable.** The source resolver, the cache, the discovery walk, the privacy
classification, and `akit help sources`.

**Specified by DESIGN.md.** The five source forms, what is not a source, the directory walk
and its shadowing rule ([§5](DESIGN.md#5-sources)); where a source actually is and what a path
key means ([§6](DESIGN.md#where-a-source-actually-is)); how a source is known to be private
([§8](DESIGN.md#how-a-source-is-known-to-be-private)).

**Build.**

- Parse every key form: shorthand, forge URL, git URL, a URL into a subdirectory, and a path.
  One normalisation, so two spellings of one repository share one cache entry.
- Clone remotes into the platform cache directory, resolve a tag or branch to a commit, and
  check out a pinned commit. A path is read where it is, has no pin, and is never cached.
- Refuse a relative path that leaves the repository when the key is in a committed manifest,
  which is the check [§6](DESIGN.md#where-a-source-actually-is) wants in a hook.
- The walk: the fixed directories per kind, three levels deep, a shallower part shadowing a
  deeper one, plus the directories each adapter declares, which arrives as a parameter so
  [T4](#t4---adapters-detection-and-akit-list) can fill it in without touching this code.
- Classify each remote source as it is fetched: it needed credentials, or it cloned
  anonymously. A path takes the repository's own classification. The answer is only observable
  while fetching, so it is returned for the render record to keep
  ([§6](DESIGN.md#what-a-render-leaves-behind)).
- Subtract a supplied set of paths before reporting parts, which is how discovery avoids
  finding our own rendered output in a repository that is its own source
  ([§5](DESIGN.md#reading-is-not-writing)). The set is a parameter here and the render record
  fills it in [T5](#t5---the-render-engine-and-skills).

**Tests.** `unit` for key parsing, including the pairs that must normalise together and the
forms that are not sources at all. `cli` for cloning, over local repositories served as
`file://`, which is also how a credential-needing remote is simulated: a repository behind a
helper that always fails classifies as private, and the test asserts the classification rather
than the error. The walk gets a fixture repository with a part at each of the three levels, a
shadowing pair, and a part in a directory an adapter declared. The subtraction test shows a
rendered skill in `.agents/skills/` being ignored as an input. Offline behaviour: a cached
source resolves with the network refused, an uncached one fails saying which it was.

**Done when.** Every row of [§5](DESIGN.md#naming-one) resolves, the walk finds every part
in the fixture, and the privacy classification is right in both directions.

**Leave alone.** Writing anything outside the cache.

## T4 - Adapters, detection, and `akit list`

**Goal.** The seven questions become an interface, two harnesses answer it, and the first
useful command lands.

**Needs.** [T3](#t3---sources-resolution-cache-discovery).

**Deliverable.** The adapter interface, the opencode and VS Code adapters, harness detection,
`akit list`, and `akit help harnesses`.

**Specified by DESIGN.md.** The seven questions, declining a kind, a harness with or without a
machine, and the worked opencode and VS Code answers ([§4](DESIGN.md#4-adding-a-harness)); one
adapter per harness, rule 7 ([§3](DESIGN.md#3-rules-of-the-build)).

**Build.**

- One adapter per harness, one file each, with sections rather than a family of registries.
  It declares: read directories per kind, write directories per kind, which of the three rule
  shapes it is and what the pointer is if it is the second, the frontmatter keys and tool
  names for agents, how it computes a project anchor, how it is detected, and whether it has a
  machine at all. Declining a kind is a first-class answer and nothing may crash on it.
- **Every adapter declines agents for now**, and the interface still carries the agent
  questions so [T13](#t13---agents) fills them in rather than reshaping anything. Declining is
  the path that has to work anyway, so 1.0 exercises it in all three adapters instead of in a
  fixture.
- Detection by evidence on this disk, never by what a repository contains
  ([§4](DESIGN.md#4-adding-a-harness)).
- `akit list`: per subscription, the source, the pin, the parts found, where each part was or
  would be rendered, and whether it was rendered at all. Per harness, whether it is detected
  and which kinds it takes. Failures are reported per line rather than stopping the command,
  because this is what you run when something is already wrong. Nothing is fetched and nothing
  is written.
- Name collisions across sources are detected here, since this is the first place that sees
  every subscription at once.

**Tests.** An adapter contract test, parametrised over every registered adapter, so a new
adapter is tested by existing. Detection: present, absent, and present but in an unusual
place, with the home redirected. `list` against a fixture holding two sources, a local path, a
deliberate collision, an unrendered subscription and a source missing from the cache, with its
output snapshot-tested in both text and `--json`. A declined kind appears in `list` and
crashes nothing.

**Done when.** `akit list` describes a realistic setup correctly on both operating systems,
and the collision is named.

**Leave alone.** Every renderer. A tool that only reads is the one chance to get resolution
right without a file-writing bug on top of it.

## T5 - The render engine, and skills

**Goal.** Files on disk match the manifests, twice in a row, and nothing we did not write is
ever touched.

**Needs.** [T4](#t4---adapters-detection-and-akit-list).

**Deliverable.** `akit render` for skills, the render record, the `.gitignore` block,
withdrawal, `--prune`, and the scope and narrowing flags.

**Specified by DESIGN.md.** Rendering always copies, the render record and its exhaustiveness
([§6](DESIGN.md#what-a-render-leaves-behind)); one copy where the bytes agree
([§7](DESIGN.md#7-rendering)); the whole of [§10](DESIGN.md#render); the ignore block
([§6](DESIGN.md#what-a-repository-commits)); no symlinks
([§9](DESIGN.md#9-windows-linux-python)).

**Build.**

- Copy skills into `.agents/skills/`, once, for every harness that reads it. Never translate,
  never link.
- The render record in the state directory: every file written, every subscription and harness
  that explains it, and a hash of the copy. Explained by a set, not by one subscription.
- Withdrawal, exactly three outcomes: in the record and unexplained and matching, deleted and
  reported; in the record and the hash differs, left alone, named, pointed at `doctor`; not in
  the record, never touched.
- `--prune`, the one deletion we cannot prove is safe, acting only on what `doctor` would call
  a plausible orphan.
- The `.gitignore` marker block, rewritten whole each render, everything outside it untouched.
- Scopes: user subscriptions to machine-level directories, project subscriptions inside the
  repository, both by default, `--global` and `--project` to narrow. `--harness` and
  `--no-harness` narrow the expanded harness list, write nothing to a manifest, and delete
  nothing.
- `as:` end to end: the kit lands under the new name and the record knows both names.

**Tests.** The idempotence test compares the whole tree after two renders, by hash, rather
than by inspection. One test per row of the withdrawal table, including the edited-copy row,
which must survive three renders. A hand-written skill in `.agents/skills/` survives render,
withdrawal and `remove`. The ignore block preserves a user's own lines and their order, and a
directory that stops being rendered leaves the block. A shared skill survives one of its two
harnesses going out of scope and goes when the second does. Deleting the rendered tree and
re-rendering restores it byte for byte. Deleting the record leaves orphans that `--prune`
removes and nothing else does. `--no-harness` deletes nothing. A `file://` source and a path
source render identically.

**Done when.** A skill subscribed from a public source renders on both operating systems, a
second render is a proven no-op, and no test can get the engine to delete a file it did not
write.

**Leave alone.** Rules and agents. The record and the withdrawal rules are the product here.

## T6 - Rules

**Goal.** One rule, written once, reaching three differently shaped harnesses in the order the
manifest says.

**Needs.** [T5](#t5---the-render-engine-and-skills).

**Deliverable.** The three rule renderers, the marker-block writer, and the opencode pointer.

**Specified by DESIGN.md.** The three shapes, the ordering rule, and why the first is
preferred ([§7](DESIGN.md#rules-and-the-three-ways-a-harness-can-take-them)).

**Build.**

- Shape one, a directory we own: one file per rule, so removing one does not touch its
  neighbours. VS Code's `.github/instructions/*.instructions.md` is the worked case.
- Shape two, pointed once: write the pointer at setup, never at render, and touch exactly one
  key in a config a person owns, leaving the rest byte-identical. opencode's `instructions` is
  the worked case.
- Shape three, one shared file: each rule between `BEGIN <id>` and `END <id>`, everything
  between and around the blocks preserved.
- Honour manifest order, which is the only place order means anything.

**Tests.** A hand-authored paragraph between two marker blocks survives three renders, and so
does a block somebody reordered by hand being put back. Two contradicting rules render in
manifest order, and swapping the manifest swaps the output. The opencode config keeps its
comments, its key order and its unrelated keys. A rule removed from the manifest leaves shape
one as a deleted file and shape three as a closed-up file with its neighbours intact. A rule
whose id is not a safe filename is refused rather than sanitised.

**Done when.** One rule renders to all three shapes from one source file, and the marker-block
survival test passes on both operating systems.

**Settles.** Nothing yet. [§12](DESIGN.md#12-still-open)'s `applyTo` question needs ten real
rules, which is [T14](#t14---iterate-on-what-use-earns)'s business, so the renderer carries no
`applyTo` field and a rule that wants one is a journal entry.

**Leave alone.** Agents.

## T7 - `add`, `remove`, `update`, `harness`

**Goal.** Nobody has to hold the manifest format in their head.

**Needs.** [T6](#t6---rules) for a render worth triggering, and
[T2](#t2---manifests)'s writer.

**Deliverable.** The four manifest-writing commands.

**Specified by DESIGN.md.** [§10](DESIGN.md#add), [§10](DESIGN.md#remove),
[§10](DESIGN.md#update), [§10](DESIGN.md#harness-add-and-harness-remove), and the flag rules
in [§6](DESIGN.md#finding-them).

**Build.**

- `add`, in four steps and in order: resolve, check the kit is really there, write one line,
  render. A typo fails at step two with a list of what the source does hold.
- `remove`: drop the subscription, withdraw what it rendered by T5's rules, and refuse when
  two manifests subscribe to the name rather than guessing.
- `update`: fetch, re-find every part under the key by the same walk `add` used, move the pin
  for every name under the key or for none, print the diff of every part subscribed, then
  render. A part that moved is reported; a part that is gone stops that key and names the
  three ways out. A `"*"` lists what disappeared beside what changed.
- `harness add` and `harness remove`: edit the `harnesses:` list, keep `detected` where it is,
  render, and withdraw on removal. `detected` is a name like any other.
- The flags, everywhere: `--global`, `--project`, `--manifest <path>`, with the project
  manifest the default and an absent `.akit.yaml` an error naming `--global`.

**Tests.** `add` writes a pin and a comment, and the file round-trips. `add` of a missing kit
fails before writing anything, and the manifest is byte-identical afterwards. `update` across
a fixture repository with a second commit: a changed part, a moved part, a deleted part, and a
`"*"` subscription, with the pin unmoved in the deletion case and every other key free to move.
`remove` under an ambiguous name refuses. Every command is a no-op on its second run.
Offline: `add` of a cached source succeeds, of an uncached one fails saying which.

**Done when.** A kit can be added from a path, renamed with `as:`, updated across a real
commit and removed, with the manifest readable by hand at every step.

**Leave alone.** The leak refusal, which is the next task and which `add` and `harness add`
will both grow a call into.

## T8 - The machineless harness, and the leak refusal

**Goal.** Committed renders become possible and dangerous in the same task, so the refusal
lands with the thing it protects against.

**Needs.** [T7](#t7---add-remove-update-harness).

**Deliverable.** The GitHub Copilot in CI adapter, committed renders, `render --check`, the
refusal, and the hooks other repositories pin.

**Specified by DESIGN.md.** The harness with no machine
([§4](DESIGN.md#4-adding-a-harness)), what a repository commits
([§6](DESIGN.md#what-a-repository-commits)), the whole of
[§8](DESIGN.md#8-keeping-the-employers-kits-in), and `--check`
([§10](DESIGN.md#render)).

**Build.**

- The adapter: no detection, arrives only by being named, writes `.github/instructions/`,
  `.github/agents/` and the shared skills directory, all committed.
- The ignore block becomes the inverse of what is committed, computed rather than maintained,
  so naming the cloud agent takes the shared skills directory out of it and nobody keeps two
  lists in step by hand.
- Classify a target by its remotes: none means private, anonymously resolvable means public,
  anything else is refused rather than guessed at. This runs only where something is
  committed, which is what keeps an ordinary render offline forever.
- The refusal, both halves, hard, with no override and no `--force`: a private source's parts
  into a public target, per harness rather than per repository; and a private source named in
  a public target's committed manifest.
- `render --check`: the same walk, writing nothing, non-zero when a committed render is stale,
  judging only committed renders, and refusing the narrowing flags.
- `.pre-commit-hooks.yaml`, so other repositories pin this package by revision and get
  `render --check`, the leak refusal and the escaping-path check without installing anything.

**Tests.** One test per row of the refusal table, in both directions, plus the unreachable
remote. A private source renders fine into a private repository and into a laptop harness in a
public one, and is refused for the committed harness in that same repository. The refusal is
total: no file written, nothing half-done, exit code 3, message naming source and target. The
ignore block flips correctly when the cloud agent is added and removed. `--check` passes on a
fresh render, fails after an edit, and refuses `--no-harness`. The hooks are exercised as
hooks, in a throwaway repository, on both operating systems. And the first diff budget: this
adapter is the second one written, so a test asserts it needed no change outside its own file
and the line registering it, which is rule 7 of
[§3](DESIGN.md#3-rules-of-the-build) checked by CI rather than by somebody's memory.

**Done when.** The table is covered row by row, and a repository guarded by the hook cannot
commit a stale or leaking render.

**Settles.** Nothing open. This task implements a decided design, and the thing to resist is
inventing an override.

## T9 - `doctor`

**Goal.** One command that says what is wrong and which command fixes it.

**Needs.** [T5](#t5---the-render-engine-and-skills); every later task adds a check.

**Deliverable.** `akit doctor`, with one check per bullet in
[§10](DESIGN.md#doctor).

**Build.** Each check is a small, independently testable function returning a finding with a
fix. One bullet of [§10](DESIGN.md#doctor) waits: an agent naming an unsubscribed skill or MCP
server has nothing to report until agents render, so it lands with
[T13](#t13---agents). The command reads everything, changes nothing, goes near the network only in the one case
`render` does, and exits non-zero when it found something. `--json` carries the findings as
data, because the skill reads this more often than a person does.

**Tests.** One test per bullet, each constructing the broken state deliberately: two kits on
one name, an unexplained render, a hand-edited render caught by its hash, an orphan from a
lost record, a missing cache entry, a pin the cache does not hold, a committed manifest naming
an escaping path, a stale committed render, files in
place for a harness that is not reading them, a detected harness the list leaves out, a named
harness no adapter knows, and both `.gitignore` failures. A healthy setup reports nothing and
exits 0. A test asserts that every finding type names a command, so a check cannot ship as a
complaint with no fix.

**Done when.** Every bullet has a failing fixture and a passing fix.

**Leave alone.** Fixing anything. Changing nothing is what makes it safe to run when you do
not know what is going on.

## T10 - Adding an adapter, documented

**Goal.** Somebody who has never read this repository can add a harness, and the claim that
doing so is one file is checked rather than asserted.

**Needs.** [T8](#t8---the-machineless-harness-and-the-leak-refusal), which is where the second
and third adapters are written and where the interface stops being a guess.

**Deliverable.** `docs/adding-an-adapter.md`, the adapter contract test grown into the thing
that enforces it, and whatever refactor writing the guide exposes.

**Specified by DESIGN.md.** The seven questions, one adapter per harness, declining a kind,
and the harness-with-no-machine property ([§4](DESIGN.md#4-adding-a-harness)); rule 7
([§3](DESIGN.md#3-rules-of-the-build)).

**Build.**

- The guide is written against the three adapters that exist, question by question, saying for
  each what the answer looks like in code, which of the three existing adapters to copy, and
  what the wrong answer costs. [§4](DESIGN.md#4-adding-a-harness) argues *why* the seven
  questions are the right seven; this says *how* to answer them, and the two must not restate
  each other.
- It names the three places a new adapter touches and asserts there is no fourth: its own
  file, the line registering it, and the contract test that then picks it up for free.
- pi is the worked example in the guide, as a walk-through rather than as shipped code
  ([§4](DESIGN.md#what-pi-looks-like)). Writing one adapter for real and documenting it is how
  the guide stays honest without this project maintaining a harness nobody here uses. Its two
  awkward answers, a project anchor that is not the git root and a trust prompt `doctor` can
  only report, are the two cases the guide has to cover, because they are the ones a naive
  adapter gets wrong.
- Declining a kind is documented first-class, since every adapter shipped in 1.0 declines
  agents and a reader will otherwise assume all three kinds are mandatory.
- The adapter contract test becomes the specification: parametrised over every registered
  adapter, asserting every question is answered, that a declined kind crashes nothing, that
  read and write directories are separate lists, and that a project anchor is computed rather
  than assumed.

**Tests.** A fixture adapter written by following the guide and nothing else, registered only
in the test, which must pass the contract test unmodified. A diff budget over the real
adapters: a test that fails if any of them has code outside its own file and its registration
line. A docs test asserting every public name the guide mentions exists, so the guide cannot
go stale in silence.

**Done when.** A reader can add a harness from the guide alone, demonstrated by the fixture
adapter, and the diff budget passes.

**Leave alone.** Shipping a fourth adapter. The guide plus the fixture is the evidence; a
harness nobody here runs is maintenance with no user, and
[T14](#t14---iterate-on-what-use-earns) adds one when somebody wants it.

## T11 - The skill, and the rule

**Goal.** An agent asked to "set up my kits" carries it out rather than describing it.

**Needs.** [T9](#t9---doctor), so every command the skill names exists and `doctor` can
answer "what is wrong".

**Deliverable.** `skills/akit/SKILL.md`, its `references/`, a `VERSION` file, the five-line
activation rule, and the `agent` test layer.

**Specified by DESIGN.md.** The three layers, the three situations, and the two rules that
keep the layers apart ([§11](DESIGN.md#11-the-skill)).

**Build.**

- Exactly three situations: nothing is set up, something needs doing, a new release is out.
  Resist a fourth.
- The skill ships standalone and may not cite this design or [DESIGN.md](DESIGN.md) by section
  number. Everything it relies on is in it or in its `references/`.
- Anything deterministic stays in the CLI. The skill says run `akit list`; it never describes
  the output. This is what the help contract in
  [T1](#t1---the-package-the-cli-frame-and-ci) was for, and this task is where that investment
  gets spent: if the skill needs to explain a command, the command's help is wrong and the fix
  goes there.
- A skill never tells the model to open another skill.
- The activation rule is text the skill offers to place, asking the agent where its own
  harness keeps user-level instructions rather than carrying a list of paths.
- `VERSION` is written by the release job from the same number as the package, since a skill
  copied into a directory cannot tell how old it is any other way.
- The skill is subscribable from this repository, so the hand-placed first copy becomes a
  managed one.

**Tests.** The `agent` layer, ported from the sibling's disposable agent: a pinned harness in
a redirected home, driven from no prior context, on both operating systems. Three cold
sessions. A machine with no manifest ends up with one and a rendered skill. "Add the writing
kit" produces the right edit to the right file and nothing else. An agent asked what changed
can name the files `akit render` wrote. Plus a lint over the skill itself: it cites no section
number, mentions no path this project does not own, and every command it names exists in the
CLI, which is a test over `--help` rather than a grep.

**Done when.** Three cold-session tests pass on both operating systems, and the skill is
installed into a fresh home by `akit` itself.

**Settles.** Nothing. The CLI living outside the skill was settled in
[§9](DESIGN.md#how-it-ships), and this task is where that pays off.

**Leave alone.** Anything the three situations do not need. A skill that documents every flag
is a manual, and the CLI already has `--help`.

## T12 - Publish 1.0

**Goal.** The thing [§9](DESIGN.md#how-it-ships) promises, installed by somebody who has
never seen this repository.

**Needs.** Everything above. [T13](#t13---agents) is deliberately not in that list: 1.0 renders
skills and rules, and every adapter declines agents.

**Build.**

- A `uvx` smoke job in CI on both operating systems: from a clean runner with nothing
  installed, clone a fixture repository carrying an `.akit.yaml`, run
  `uvx --from federated-agent-kits akit render`, and
  assert the files a harness reads are in place. That is the exact sentence the README and
  every contributing guide make, so it is a test rather than a claim.
- README and `CONTRIBUTING.md` updated to the shipped reality, with the design and this plan
  demoted from "what will exist" to "why it is shaped this way".
- A compatibility statement: the `akit` entry point and the rendered file shapes are the
  contract, and changing either is a major ([§9](DESIGN.md#how-it-ships)).
- The "not implemented yet" list from T1 is empty, asserted by the test written then.
- Publish `1.0.0`.

**Done when.** `uvx --from federated-agent-kits akit render` works in a fresh clone on both
operating systems, in CI,
without this repository being present.

## T13 - Agents

**Goal.** One agent definition, two harnesses, with no silent loss.

**Needs.** [T12](#t12---publish-10). Agents come after the release deliberately. They are the
least portable kind and the least used: [§7](DESIGN.md#agents-are-the-hard-one) has four
harnesses disagreeing about frontmatter keys, tool names and what an agent is even for, while
skills and rules are what a kit is made of almost every time. Three agents that genuinely want
to live in two harnesses is the trigger; fewer than that and this is a translation layer
maintained for nobody.

**Also in scope.** The `doctor` check [T9](#t9---doctor) left out: an agent naming a skill or
an MCP server you have not subscribed to. It has nothing to report until agents render.

**Deliverable.** The agent renderer, the tool-name table, and the hard failure.

**Specified by DESIGN.md.** The canonical file, the `harness:` overrides, and the refusal on an
unmappable tool ([§7](DESIGN.md#agents-are-the-hard-one)).

**Build.** A portable body plus a `harness:` block of per-target overrides. Translate the
frontmatter per harness, body untouched. Build the tool-name table by hand and decide then
whether it is per harness or per agent. Stop the render on a tool name with no mapping. Report
a skill or an MCP server an agent names and you have not subscribed to, as a warning, and
install nothing ([§1](DESIGN.md#1-what-this-is), [§13](DESIGN.md#13-not-doing)).

**Tests.** One source file renders to opencode and VS Code with the right keys and the body
byte-identical. An unmappable tool name fails the render, names both spellings, and leaves no
file behind: the tempting bug is to drop it and carry on, so the test asserts the failure. A
`harness:` override wins over the portable value. The 30,000-character cap the cloud agent
documents is enforced with a message naming the limit. An agent naming an unsubscribed skill
warns and renders.

**Done when.** One agent file serves two harnesses, and every unmappable name is a refusal.

**Settles.** How tool names map ([§12](DESIGN.md#12-still-open)), from three real agents
rather than from an opinion.

## T14 - Iterate on what use earns

**Goal.** Keep discovering against a setup that is used rather than built. Open-ended by
construction: no completion date, and its first output is evidence rather than code.

**Steps.**

- Keep the journal running. The incidents that matter here are a render that surprised
  somebody, a rendered copy edited by mistake, a collision the rename did not solve, a source
  whose layout moved, a harness that changed its directories.
- **Write ten real rules**, the ones actually wanted on this machine, and see whether any of
  them wants an `applyTo` glob. That is the evidence
  [§12](DESIGN.md#12-still-open) asks for, and it cannot be gathered before the renderer
  exists.
- Add a harness when somebody wants one, not before, and write it from
  [T10](#t10---adding-an-adapter-documented)'s guide rather than from the existing adapters.
  Each addition tests both the claim and the guide, and the first one needing a change outside
  its own file, or a step the guide did not mention, is worth writing down.
- Revisit MCP servers only on evidence ([§13](DESIGN.md#13-not-doing)). The entry that would
  move them is an agent that is useless without one, more than once.

**Done when.** Nothing, in the sense the other tasks mean it.

**Leave alone.** Anything the journal has not asked for. The failure mode of an open-ended
task is building the obvious thing.
