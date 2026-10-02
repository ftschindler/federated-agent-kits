# IMPLEMENTATION - federated-agent-kits

**Status:** the plan of record. [DESIGN.md](DESIGN.md) remains the sole source of truth for
*what* gets built; this document says *in which order*, and *when* each open question is
answered.

**Section references.** A `§N` link points at the matching section of [DESIGN.md](DESIGN.md).

This plan assumes nothing from this repository except [DESIGN.md](DESIGN.md) and this file.
A fresh session should be able to start here.

## Status

- [ ] **[T1](#t1---read-the-manifest-render-nothing)** - Read the manifest, render nothing
- [ ] **[T2](#t2---render-skills)** - Render skills
- [ ] **[T3](#t3---render-rules)** - Render rules
- [ ] **[T4](#t4---add-a-third-harness)** - Add a third harness, *proves the adapter claim*
- [ ] **[T5](#t5---ship-the-skill)** - Ship the skill
- [ ] **[T6](#t6---refuse-to-leak)** - Refuse to leak, *gates the first employer source*
- [ ] **[T7](#t7---render-agents)** - Render agents
- [ ] **[T8](#t8---iterate-on-what-use-earns)** - Iterate on what use earns, *open-ended*

## How to use it

**Answer an open question only when a task forces it.** Deciding early trades away the
information the work itself produces. Every task names which questions it settles and which
it must leave alone even when the answer looks obvious. Leaving one alone is not
procrastination; it is refusing to guess when the next task will know.

**Each task ships something usable.** T1 is useful on its own, T2 replaces a manual copy
step, and so on. No task exists only to prepare the next one.

**Keep a journal from T1.** `JOURNAL.md` beside this file, one dated line per incident, with
the actual paths and commands. Three rules make a fabricated entry obviously empty: record
what happened rather than what should be built, name the artefacts, and say what was done
instead. It is the evidence that decides [T8](#t8---iterate-on-what-use-earns).

## Before starting

A fresh session needs four things, two of which are not in this repository.

| What | Where | Why |
| --- | --- | --- |
| The design | [DESIGN.md](DESIGN.md) | Every schema, path and refusal is specified there |
| The `skills` CLI discovery rules | its npm README, section "Skill Discovery" | [§6](DESIGN.md#6-sources) follows them and does not restate the full list of directories |
| Harness documentation | opencode, VS Code, pi | [§4](DESIGN.md#4-where-each-harness-keeps-things) is a summary, not a substitute |
| The guard suite | this repository | `make bootstrap`, then `make check` |

Two constraints bind every task and are easy to breach without noticing. **Python only**, and
**Windows and Linux equally**, both spelled out in
[§10](DESIGN.md#10-windows-linux-python). The second is not satisfied by care: it is
satisfied by the CI matrix that [T1](#t1---read-the-manifest-render-nothing) adds.

## T1 - Read the manifest, render nothing

**Goal.** Say what you have subscribed to and where it is, before anything writes a file.

**Deliverable.** `akit list` and `akit link`, the manifest parser, the source resolver, the
kit discovery walk, and a CI matrix on `ubuntu-latest` and `windows-latest`.

**Specified by DESIGN.md.** Source forms and the directory walk
([§6](DESIGN.md#6-sources)), the manifest schema, the two files and their precedence
([§7](DESIGN.md#7-the-manifest)).

**Steps.**

- Parse both manifests. The user one in the per-platform config directory, the project one at
  `.akit/kits.yaml`, project adding to user and winning on a clash.
- Resolve a source key: shorthand, forge URL, git URL, subdirectory URL, local path, with an
  optional `#ref`. Clone into the platform cache when nothing says otherwise.
- Implement `akit link <source> <path>` and the machine-state file it writes to. Keep that
  file separate from the lockfile from the start; they answer different questions and one of
  them is shared.
- Walk the directories from [§6](DESIGN.md#6-sources), three levels, shallower shadowing
  deeper, for all three kinds.
- Report: each subscription, which source and ref it resolved to, which kit file, and whether
  two subscriptions collide on a name.
- Add the test workflow with both operating systems required.

**Done when.** `akit list` runs against a public source and a local path on both operating
systems, and reports a deliberate name collision.

**Settles.** The CI matrix half of [§10](DESIGN.md#10-windows-linux-python).

**Leave alone.** Every renderer. A tool that only reads is the one chance to get resolution
right without a file-writing bug on top of it.

## T2 - Render skills

**Goal.** Replace the manual copy. Skills first because they need no translation.

**Deliverable.** `akit render` for skills, `akit update`, `akit doctor`, and the lockfile.

**Specified by DESIGN.md.** Copy versus link ([§7](DESIGN.md#7-the-manifest)), what rendering
a skill means ([§8](DESIGN.md#8-rendering)), symlinks opt-in
([§10](DESIGN.md#10-windows-linux-python)).

**Steps.**

- Render into the harness directories for opencode and VS Code, plus `~/.agents/skills/`,
  which several harnesses read directly.
- Record in the lockfile what was written, from which source at which commit, by copy or by
  link.
- Make the second render a no-op. Prove it with a test that renders twice and compares the
  tree, not by inspection.
- `akit update` re-pins a copied kit and shows the diff.
- `akit doctor` reports collisions, a rendered file that no subscription explains, and a
  source that will not resolve.
- Handle `as` end to end: a renamed kit lands under the new name and the lockfile knows both.

**Done when.** A skill subscribed from a public source loads in a real opencode session on
both operating systems, and deleting the rendered tree then re-running `akit render` restores
it exactly.

**Leave alone.** Rules and agents. Also the question of whether linking is worth having
([§13](DESIGN.md#13-still-open)); build it for local sources only, and let the journal say
whether anybody uses it.

## T3 - Render rules

**Goal.** One rule, written once, reaching three differently-shaped harnesses.

**Deliverable.** The three rule renderers, the marker-block concatenation, and the first ten
real rules living in a source.

**Specified by DESIGN.md.** The three shapes and the ordering rule
([§8](DESIGN.md#8-rendering)), what each harness reads
([§4](DESIGN.md#4-where-each-harness-keeps-things)).

**Steps.**

- opencode: contribute paths to `instructions` in its config rather than writing a rule file.
  This edits a file the user owns, so touch one key and leave the rest byte-identical.
- VS Code: one `.instructions.md` per rule under `.github/instructions/`.
- `AGENTS.md` targets: one concatenation, each rule between `BEGIN <id>` and `END <id>`.
  The test that matters writes hand-authored prose between two blocks and checks it survives
  three renders.
- Honour manifest order, and prove it with a test over two rules that contradict.
- **Write ten real rules.** Not fixtures: the rules actually wanted on this machine. This is
  the only way [§13](DESIGN.md#13-still-open)'s `applyTo` question gets evidence instead of an
  opinion.

**Done when.** One rule renders to all three shapes, a hand-written paragraph between two
marker blocks survives, and the ten rules are in a source and rendered.

**Settles.** Whether rules need `applyTo`, from what the ten rules turned out to want.

**Leave alone.** Agents. Rules are where the ordering and merge-into-someone-elses-file
problems live, and they are enough for one task.

## T4 - Add a third harness

**Goal.** Find out whether "a harness is a file, not a branch" is true, while it is still
cheap to fix if it is not.

**Deliverable.** A pi adapter, and whatever refactor its absence of a clean seam demands.

**Specified by DESIGN.md.** The six questions and the worked pi answers
([§5](DESIGN.md#5-adding-a-harness)), invariant 6
([§3](DESIGN.md#3-rules-of-the-build)).

**Steps.**

- Answer the six questions for pi in code. Skills need no file written, rules take the
  concatenation, agents exist only behind a third-party package and the adapter declines them
  for now.
- Declining a kind is a first-class answer, so make sure it is: `akit list` says which kinds
  each harness takes, and nothing crashes on the one it does not.
- Count what the adapter touched. Anything outside its own file is a design bug, and fixing
  it is part of this task rather than a follow-up.

**Done when.** The pi adapter is one file, plus one line registering it, and the diff proves
it.

**Leave alone.** A fourth harness. One is the experiment; two is a habit before there is
evidence the shape holds.

## T5 - Ship the skill

**Goal.** A person who installs this and knows nothing gets a working setup, carried out
rather than described.

**Deliverable.** `skills/akit/SKILL.md`, its `references/`, a `VERSION` file, and the
five-line activation rule.

**Specified by DESIGN.md.** The three layers and the two rules that keep them apart
([§12](DESIGN.md#12-the-skill)).

**Steps.**

- Cover exactly the three situations: nothing is set up, something needs doing, a new release
  is out. Resist a fourth.
- **The skill may not cite this design.** It ships standalone, so every rule it relies on is
  in it or in its `references/`, never referred to by section number.
- **Deterministic behaviour stays in the CLI.** The skill says run `akit list`; it never
  describes the output, or there are two descriptions and one goes stale.
- Ship the activation rule as text the skill offers to place, and let it ask the agent where
  its own harness keeps user-level instructions rather than carrying a list of paths.
- Settle whether the CLI ships inside the skill ([§13](DESIGN.md#13-still-open)). The
  decision is forced here because the skill has to tell somebody how to run the thing.
- Decide how a cold-session test gets run. The sibling project builds a throwaway agent in a
  redirected `HOME` and drives it; port that or state the gap, because prose is what regresses
  and no unit test reads it.

**Done when.** Three cold-session tests pass, each from no prior context: a machine with no
manifest ends up with one and a rendered skill; "add the writing kit" results in the right
edit to the right file; and an agent asked what changed can say which files `akit render`
wrote.

**Settles.** Whether the CLI ships inside the skill.

**Leave alone.** Anything the three situations do not need. A skill that documents every flag
is a manual, and the CLI already has `--help`.

## T6 - Refuse to leak

**Goal.** Make it impossible to render an employer's rule into a repository with a public
remote.

**This task gates the first employer source.** Not an ordering preference. Until it is built,
subscribing to a private source is the one thing that can do real damage.

**Specified by DESIGN.md.** The ceiling and what the check reads
([§9](DESIGN.md#9-keeping-the-employers-kits-in)), refusals are hard
([§3](DESIGN.md#3-rules-of-the-build)).

**Steps.**

- Settle where the ceiling is declared, in the source or in the subscription
  ([§13](DESIGN.md#13-still-open)). Everything else here depends on it.
- Classify a render target from its git remote. No remote means private. Anything it cannot
  classify is refused, never assumed safe.
- Make the refusal hard: no partial render, no warning, and a message naming the fix.
- Settle whether rendered files are committed inside a project
  ([§13](DESIGN.md#13-still-open)), which this check is what makes safe either way.
- One test per row of the refusal table. The table is the whole product here, and an untested
  row is a row that is wrong.

**Done when.** A private source renders into a private repository, is refused into a public
one, and the test suite covers both directions plus the unclassifiable target.

**Settles.** Where the ceiling lives, and whether renders are committed.

## T7 - Render agents

**Goal.** One agent definition, two harnesses, with no silent loss.

**It waits.** Agents are the least portable kind and the least used. Three agents that
genuinely want to live in two harnesses is the trigger; fewer than that and this is a
translation layer maintained for nobody.

**Specified by DESIGN.md.** The canonical file, the `harness:` overrides, and the hard failure
on an unmappable tool ([§8](DESIGN.md#8-rendering)).

**Steps.**

- Translate the frontmatter per harness, body untouched.
- Build the tool-name table by hand. Decide then whether it is per harness or per agent
  ([§13](DESIGN.md#13-still-open)); writing three real agents is what answers it.
- **Stop the render on a tool name with no mapping.** A test asserts the failure, because the
  tempting bug is to drop it and carry on.
- Report a skill or MCP server an agent names and you have not subscribed to. Warn, never
  install.

**Done when.** One agent runs in opencode and in VS Code from one source file, and an
unmappable tool name fails the render with a message naming both spellings.

**Settles.** How tool names map.

## T8 - Iterate on what use earns

**Goal.** Keep discovering against a setup that is used rather than built. Open-ended by
construction: no completion date, and its first output is evidence rather than code.

**Steps.**

- Keep the journal running. The incidents that matter here are a render that surprised
  somebody, a kit that was edited in its rendered copy by mistake, a collision the rename did
  not solve, a source whose layout moved.
- Settle whether linking is worth having ([§13](DESIGN.md#13-still-open)) from whether anyone
  used it.
- Settle what a moved tag should report ([§13](DESIGN.md#13-still-open)), when one moves.
- Add a harness when somebody wants one, not before. Each addition is also a test of
  [T4](#t4---add-a-third-harness)'s claim, and the first one that needs a change outside its
  own file is worth writing down.
- Revisit MCP servers only on evidence ([§14](DESIGN.md#14-not-doing)). The entry that would
  move them is an agent that is useless without one, more than once.

**Done when.** Nothing, in the sense the other tasks mean it.

**Leave alone.** Anything the journal has not asked for. The failure mode of an open-ended
task is building the obvious thing.
