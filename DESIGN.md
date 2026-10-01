# DESIGN - federated agent kits

**Status:** first draft, nothing implemented. This document is the **sole source of truth**
for the design. Change it here first.

**Date:** 2026-10-01

## 1. What we build

A way to keep the things that configure a coding agent in several git repositories at
different privacy tiers, subscribe to a subset of them, and render that subset into the
files each harness actually reads.

- Each **source** is an ordinary git repository holding kits. It does not know that this
  system exists, and it does not know about any other source.
- A **kit** is one shareable thing: a skill, a rule, or an agent definition.
- A **manifest** on your machine says which kits you want, from which sources, rendered at
  which scope. It is the only file that sees every source at once.
- **Rendering** writes harness-native files. Those files are generated and disposable.

Harnesses in scope on day one: opencode and VS Code. Claude Code comes free, because its
file conventions are a subset of what the other two need.

We do not build a registry, a marketplace or a runtime. We do not build a security
mechanism: access control is git remote permissions, and everything here is a guardrail that
prevents accidents, not attackers.

### Open questions

Detail in [§9](#9-open-questions). None of them blocks the first task.

| # | Question |
| --- | --- |
| 9.1 | Whether rule fragments need `applyTo` globs, or whether always-on is enough |
| 9.2 | Where a source's visibility ceiling is declared, in the source or the manifest |
| 9.3 | Whether rendered files are committed in a project, and who decides |
| 9.4 | How agent tool names map between harnesses, and what happens when they do not |
| 9.5 | Whether the manifest pins versions, and at what granularity |
| 9.6 | Whether `akit` grows a `sync` for sources it did not clone |

## 2. Invariants

These bound every decision below.

1. **The source file is the source.** A rendered file is generated and may be deleted at any
   time. Nothing is authored in two places, and no drift guard is needed between them.
2. **Render is idempotent and cheap.** It can run from a git hook or a shell startup, so a
   stale render is never a state anyone has to reason about.
3. **Install what is whole, compose what is a fragment.** Skills and agents arrive as
   complete files. Only rules are concatenated, and only where a harness cannot read a list.
4. **A refusal is hard.** Where policy says no, the tool fails with a message naming the fix.
   It never degrades to a partial render or a warning.
5. **Ship self-contained.** No post-install configuration, no assumption that a sibling tool
   is present, no cross-kit dependencies.
6. **The manifest is a guardrail, not a boundary.** A source stays safe when somebody
   bypasses this tool entirely.

## 3. The three kinds

What separates them is when they enter the model's context, not where they live.

| Kind | What it is | When it loads | Unit |
| --- | --- | --- | --- |
| Rule | prose added to the system prompt | every message | a fragment |
| Skill | a folder the model may open | when the model decides to | a folder |
| Agent | prompt plus model plus tool allow-list | when a session runs as it | a file |

A rule costs tokens on every turn, so it stays short. A skill costs only its description
until opened, so it can be long. An agent replaces the prompt rather than adding to it.

The common pattern that makes the three look entangled: a long skill plus a three-line rule
that names the trigger for reaching for it. Those are two kits, and the rule ships in the
same source as the skill it activates.

### Which kind carries what

Put a thing in the cheapest kind that still fires at the right moment.

- Shapes every reply and fits in thirty lines: rule.
- Long, or only relevant to one kind of task: skill.
- Needs a different model, a smaller tool set, or a prompt that contradicts the defaults:
  agent.

## 4. Where harnesses look

Both harnesses support all three kinds, at both repository and user scope. What differs is
whether the harness will read a **list** of locations or insists on a fixed path.

**opencode** reads a list, which is why federation is nearly free there.

| | Repository | User-wide |
| --- | --- | --- |
| Rules | `AGENTS.md`, walking up to the worktree root, plus `instructions` globs in `opencode.json` | `~/.config/opencode/AGENTS.md`, plus `instructions` in the global config |
| Skills | `.opencode/skills/`, `.claude/skills/`, `.agents/skills/` | the same three under `~` |
| Agents | `.opencode/agent/*.md` | `~/.config/opencode/agent/*.md` |

`instructions` takes files, globs and https URLs, and all of them are combined with whatever
`AGENTS.md` files were found.

**VS Code** mostly insists on fixed paths.

| | Repository | User-wide |
| --- | --- | --- |
| Rules | `.github/copilot-instructions.md`, `.github/instructions/*.instructions.md`, root `AGENTS.md` | profile data for the Local agent, `~/.copilot/instructions/` for Agent Host |
| Skills | `.claude/skills/`, where the harness supports it | varies by harness, and this is the weakest leg |
| Agents | `.github/agents/*.agent.md`, `.claude/agents/` | `~/.copilot/agents/`, or profile data |

`chat.instructionsFilesLocations` and its siblings do take external directories, including
absolute and `~` paths. The current documentation marks them deprecated and Local-agent only,
and neither Copilot Agent Host nor the cloud agent honours them. **So we do not build on
them.** Fixed-path output is the common denominator.

## 5. Sources and the manifest

### A source is an ordinary repository

No manifest inside it, no registration step, no knowledge of this tool. A source holds
`skills/<name>/SKILL.md`, `rules/<name>.md` and `agents/<name>.md`, and anything that follows
those conventions can be subscribed to. `ftschindler/agents-skills` already qualifies for the
skills third of that.

This is deliberate, and it is what "federated" means here. The cost is that a source cannot
declare anything about itself, which [§7](#7-policy) has to work around.

### Subscribe to an item, not to a repository

A source holds many kits and you will want some of them. The entry:

```yaml
- source: ftschindler/agents-skills
  kind: skill
  name: writing
  scope: global
  as: writing        # optional; resolves a collision
```

A glob in `name` covers "take everything of this kind from this source", which is what the
corporate source will want.

`as` is not decoration. opencode requires skill names to be unique across all six of its
search locations, so two sources both shipping `kb` is a real collision. Neither source can
resolve it, because neither knows the other exists. The manifest is the only place that can.

### Two manifests, one schema

| | Lists | Committed |
| --- | --- | --- |
| `$XDG_CONFIG_HOME/akit/kits.yaml` | what is true of you | no |
| `<repo>/.akit/kits.yaml` | what is true of that repository | yes |

The project manifest adds to the global one rather than replacing it, because a global
subscription is a fact about you that does not stop being true inside a repository. A project
entry naming the same item wins, which is how a repository pins something different without
you un-subscribing globally.

### Subscription and resolution are different questions

A committed manifest may not contain a single absolute path, because a colleague's checkout
is somewhere else. So:

- **Subscription** names a source as `ftschindler/agents-skills@v2`. It lives in either
  manifest.
- **Resolution** turns that name into a directory on this disk. It lives in the user
  manifest only, or defaults to a clone under `$XDG_CACHE_HOME`.

A colleague who clones a repository therefore needs no setup, and you still get live edits on
the sources you author yourself.

### Link what you author, copy what you consume

Both already happen by hand today and both are worth keeping.

| | When | Cost |
| --- | --- | --- |
| Symlink | you have the source checked out and edit it | nothing to sync, one file, and it breaks on a Windows clone |
| Copy plus hash | a pinned upstream you only read | an update is a diff you review |

The lockfile records which, along with the source revision, so `akit doctor` can say what is
stale.

## 6. Rendering

One renderer per kind per harness. They differ only in the last step.

**Skills** are installed by linking or copying `skills/<name>/` into the harness directory.
Six locations across two harnesses already agree on `skills/<name>/SKILL.md`, so there is no
translation to do.

**Rules** render three ways:

- opencode: nothing is written. The manifest contributes glob paths to `instructions`.
- VS Code: one `*.instructions.md` per fragment, into `.github/instructions/`, carrying the
  fragment's `applyTo` straight through. One file per fragment, so a fragment can be dropped
  without touching its neighbours.
- `AGENTS.md`-shaped targets: a single concatenation, each fragment wrapped in `BEGIN <id>`
  and `END <id>` markers, so hand-written text between blocks survives a re-render.

Rules are the only kind with an order, because two rules can contradict and something must
win. Manifest order decides it, and we are not looking for a cleverer answer.

**Agents** are the hard case. All three harnesses use markdown with frontmatter, which looks
encouraging until you read the keys:

| Harness | Location | Frontmatter |
| --- | --- | --- |
| opencode | `agent/*.md` | `model`, `tools`, `temperature`, `permission` |
| VS Code | `.github/agents/*.agent.md` | `description`, `tools`, `model`, `handoffs`, `mcp-servers` |
| Claude Code | `.claude/agents/*.md` | `name`, `description`, `tools`, `model` |

The body is portable. Tool names, model identifiers and the notion of what an agent is for
are not: an opencode subagent is delegated to by a lead, a VS Code custom agent is picked by
a human from a menu. The same body serves both only when it is written about the task rather
than about who called it.

So: one canonical file, a portable body, and a `harness:` map in the frontmatter holding the
per-target overrides. The adapter maps what it knows and **fails loudly on a tool name it
cannot map**, because a subagent quietly missing a tool fails later and further away.

## 7. Policy

The failure this prevents: a corporate rule rendered into a repository with a public remote.

**A source declares the furthest its kits may travel, and rendering past that is refused.**
This is `referenceable_by` from the knowledge bundles, pointed the other way: there it is an
inbound permission, here it is an outbound ceiling.

Where it is declared is [§9.2](#9-open-questions). A file in the source is the honest place,
because the ceiling is a fact about the source rather than about this machine. It costs the
"a source knows nothing about this tool" property from [§5](#5-sources-and-the-manifest), so
the fallback is a ceiling in the manifest entry, defaulting closed.

The check compares the ceiling against the render target's git remote. No remote means
private. A target it cannot classify is refused rather than assumed safe.

## 8. The CLI

```text
akit list                 # what is subscribed, where it renders, is it current
akit add <source> <name> --kind rule --scope global
akit render [scope]       # idempotent; safe from a git hook
akit update [name]        # re-pin copies and show the diff
akit doctor               # collisions, stale renders, policy violations
```

`render` being idempotent and cheap is what makes the rest trustworthy.

## 9. Open questions

**9.1 Do rule fragments need `applyTo`?** VS Code supports a glob that decides when a
fragment applies. opencode has no equivalent, so a fragment with `applyTo` renders as
always-on there. Carrying a field that only one harness honours may be worse than not having
it. Settled by writing the first ten real fragments and seeing whether any wants one.

**9.2 Where does the visibility ceiling live?** In the source, which breaks "a source knows
nothing", or in the manifest entry, which means every subscriber re-states it and one of them
gets it wrong. Settled before any corporate source is added.

**9.3 Are rendered files committed in a project?** Committed means a colleague who never
installs `akit` still gets the rules, which is the whole point for a team repository. It also
means a mis-subscription puts corporate prose into a public repository, so it interacts with
9.2. Likely per-repository, declared in the project manifest.

**9.4 How do agent tool names map?** A hand-maintained table that fails on an unknown name is
the stated plan. Whether that table is per-harness or per-agent is open, and we should not
invest here until three agents genuinely want to live in both places.

**9.5 Does the manifest pin versions?** A tag or commit per source is the obvious answer.
Whether an individual kit can pin separately from its source is open, and probably not worth
it.

**9.6 Does `akit` grow a `sync`?** For a source it cloned into the cache, updating is just a
fetch. For one you authored and symlinked, there is nothing to do. The question is whether a
third state exists that needs a command.

## 10. Rejected

**rulesync.** It renders to many harnesses from one `.rulesync/rules/` directory, which is
the rendering half of this. It is project-scoped, with no federation, no tiers and no
subscription, so it would sit underneath the manifest rather than replace it. Not worth the
dependency for a renderer we can write in a hundred lines.

**One manifest shared with `fkb`.** Knowledge bundles and kit sources answer different
questions, and merging the files means a colleague cloning a repository sees the path to your
private bundle.

**A field in each file declaring its privacy tier.** The repository a file lives in already
says it, and a field can disagree with the repository. One place or none.

**`AGENTS.md` as the unit of sharing.** It is the one filename every harness insists on
owning, which is why composing it is the problem rather than the solution.

## 11. Naming

The system covers three kinds, so a name mentioning only rules would be wrong within a month.
`federated-agents` reads as agents federating with each other, which is a different and noisy
topic.

The binary is `akit` and not `kit`, because KitOps ships a `kit` binary to `/usr/local/bin`
through Homebrew, aimed at the same AI audience, and its verbs are the ones we want:
`kit init`, `kit list`, `kit diff`. The clash would not be an install error but a reader
running the wrong tool from our documentation.
