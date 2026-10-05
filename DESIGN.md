# DESIGN - federated agent kits

**Status:** first draft. Nothing is implemented. This document is the sole source of truth
for the design, so change it here first. [IMPLEMENTATION.md](IMPLEMENTATION.md) says in which
order it gets built.

**Date:** 2026-10-01

## 1. What this is

A tool and a skill for sharing **agent kits** portably: across machines, across operating
systems, and across harnesses.

A kit is an arbitrary composition of three parts. It may be a single skill. It may be a skill
with the rule that makes a model reach for it. It may be an agent, two skills it leans on and
a rule that sets the house style. What makes them one kit is that you want them together.

### The three parts

A **rule** is prose. The harness pastes it into the system prompt before every single
message. You pay for it on every turn, so a rule that runs to three pages is a bad rule.

A **skill** is a folder with instructions inside. The model sees only its one-line
description, and opens the folder when it judges the description matches. An unopened skill
costs almost nothing, so a skill can be long.

An **agent** is a prompt with a model and a list of tools attached. Starting a session as an
agent replaces the normal prompt rather than adding to it.

They go to three different places in a harness, which is why they are three parts rather than
one file. They are wanted together, which is why the thing you share is the composition.

### Why a composition and not a part

A long skill usually needs a short rule to go with it.

Nothing makes a model open a skill except its description. If the moment to reach for it is
not obvious from the description alone, the model never reaches. Three lines in the system
prompt naming the trigger fix that, and those three lines are a rule.

Sharing the skill alone therefore ships something that quietly never runs. The composition is
the unit because it is the smallest thing that works on the other machine.

**You compose it, the source does not.** Almost nothing out there ships a kit, and a
repository holding a skill beside its rule has no way to say the two belong together. So the
composition lives in your manifest, which is also the only place that can compose across two
sources ([§7](#7-the-manifest)).

An agent can name skills it expects to be there. Those are not parts of it: they are a
dependency, and we do not chase dependencies. A named skill you have not subscribed to gets
you a warning from `akit doctor`, and nothing is installed that you did not ask for. An agent
naming an MCP server is treated the same way, and section 14 says why that is as far as it
goes.

### What it takes to move one

A kit is the thing being shared. These six words are the machinery that shares it, and each
one exists for a different part of "portable, federated, across harnesses".

| Word | What it is | What it buys |
| --- | --- | --- |
| **Harness** | the program that runs the model | the thing portability is *across*: opencode, VS Code, pi, Claude Code |
| **Source** | a git repository holding kits | federation: many repositories, at whatever privacy tier each one has |
| **Subscription** | a line saying you want one kit from one source | choice, made per machine rather than per source |
| **Manifest** | the file your subscriptions live in | the one place that sees every source at once, which is where anything cross-source has to happen |
| **Adapter** | the code that knows one harness's conventions | a new harness being a file rather than a rewrite |
| **Render** | writing a kit into the files a harness reads | the crossing itself, from how a source stores a kit to how a harness wants it |

## 2. What this does

You have kits in several git repositories, and more often you have loose parts. A repository
holding one skill at its root. A gist-shaped repository somebody published once. A team
repository with forty skills and no rules at all. None of it was authored as a kit, because
nothing out there knows the word.

**A lone part is a kit with one part, and it takes no ceremony to become one.** Nothing is
added to the repository, nothing is declared, and the author is never asked. Composition is
what this tool reads, not what a source has to provide.

You want subsets of all that, in multiple harnesses, on multiple operating systems on
different machines. So: you write down what you want, and run one command that puts the files
where each harness looks.

Three things follow from that sentence.

**A source is an ordinary repository.** It holds parts in conventional directories and knows
nothing else. It does not know this tool exists, it does not know which other sources you
have, and it need never have heard the word kit.

**The manifest is the only thing that sees everything.** It lives on your machine. It is
where anything needing knowledge of two sources at once has to happen. It can be tracked
like any other dotfile.

**Rendered files are disposable.** Delete any of them and re-run the command. Nothing you
wrote by hand lives in one.

We are not building a registry, a marketplace, or anything that runs an agent. We are not
building a security mechanism either: what actually stops a colleague reading your employer's
kits is that they cannot clone the repository.

## 3. Rules of the build

1. **The file you edit is the only copy.** Everything else is generated from it.
2. **Rendering twice changes nothing.** So it can run from a git hook, and a stale render is
   never a state anyone has to think about.
3. **Whole things get installed, fragments get composed.** A skill and an agent arrive
   complete. Only rules are stitched together, and only where a harness cannot read a list.
4. **We write only files we own.** A render creates and overwrites files in directories this
   tool manages. The one exception is a harness that reads a single fixed file, which is
   shared with whatever the user wrote in it, and then we touch only our own marker blocks.
5. **A refusal is a refusal.** When policy says no, the command fails and names the fix. It
   never writes half the files and warns.
6. **Python, on Windows and Linux equally.**
7. **A harness is a file, not a branch.** Adding one touches nothing else, and where a harness
   keeps things is its adapter's business rather than this document's.
8. **Nothing to configure after install.** No sibling tool assumed, no kit depending on
   another kit.
9. **This is a guardrail.** Every source stays just as safe when somebody ignores this tool
   entirely.

## 4. Where each harness keeps things, today

> **A snapshot, not a contract.** Every path below is where one harness happened to keep
> things when this was written, and each will move. The authority is the adapter
> ([§5](#5-adding-a-harness)); nothing else in this design may depend on a path from this
> section.

Harnesses differ in one way that matters more than all the others: whether they will read a
**list** of locations, or insist on one fixed path.

opencode reads a list. Its config takes an `instructions` key of files, globs and even https
URLs, and combines all of them with whatever `AGENTS.md` files it found. So it is the second
shape in [§8](#8-rendering): pointed once at a directory we own, and never edited again.

| opencode | Repository | User-wide |
| --- | --- | --- |
| Rules | `AGENTS.md` up to the worktree root, plus `instructions` globs | `~/.config/opencode/AGENTS.md`, plus `instructions` in the global config |
| Skills | `.opencode/skills/`, `.claude/skills/`, `.agents/skills/` | the same three under `~` |
| Agents | `.opencode/agent/*.md` | `~/.config/opencode/agent/*.md` |

VS Code insists on fixed paths.

| VS Code | Repository | User-wide |
| --- | --- | --- |
| Rules | `.github/copilot-instructions.md`, `.github/instructions/*.instructions.md`, root `AGENTS.md` | profile data for Local, `~/.copilot/instructions/` for Agent Host |
| Skills | `.claude/skills/`, where the harness supports it | varies, and this is the weak leg |
| Agents | `.github/agents/*.agent.md`, `.claude/agents/` | `~/.copilot/agents/`, or profile data |

There is a setting that would let VS Code read external directories, and we are not using it.
`chat.instructionsFilesLocations` does take absolute and `~` paths. The documentation marks
it deprecated and says only the Local agent honours it, so neither Agent Host nor the cloud
agent would see anything we wrote there. Writing to the fixed paths is what all three read.

## 5. Adding a harness

Write an adapter. An adapter answers six questions and nothing else in the system changes.

1. Where do skills go, for the whole machine and for one repository?
2. How does it pick up rules: a directory we own, a directory it can be pointed at once, or
   one fixed file we have to share ([§8](#8-rendering))?
3. If it is the middle one, what is the pointer, and what writes it at setup?
4. Where do agents go, and what are the frontmatter keys called?
5. What are this harness's tools called?
6. What counts as "this repository" here?

"This harness has no agents" is a valid answer to question 4. The adapter declines that kind
and the command says so.

**An adapter is also where a harness's changes land.** When one moves its directories or
replaces its config key, the fix is that file and the snapshot in
[§4](#4-where-each-harness-keeps-things-today), not the design.

### What pi looks like

pi is about as cheap as an adapter gets, which makes it a good first worked example.

**Skills: nothing to write.** pi already reads `~/.agents/skills/` and `.agents/skills/`.
Its `settings.json` also takes a list of skill directories, absolute or `~`-relative.

**Rules: one fixed file, shared.** pi reads `~/.pi/agent/AGENTS.md` plus every `AGENTS.md`
walking up from the working directory, and joins them. Nothing can be pointed anywhere, so it
is the third shape and gets marker blocks, the same as Claude Code.

**Agents: only via a package.** The third-party `pi-agents` package puts them in
`~/.pi/agent/agents/*.md`, with `name`, `description`, `thinking`, `skills` and `tools`. An
adapter can support that and must not assume it is installed.

Two details from pi generalise. It deliberately does not require a skill's `name` to match
its directory, saying the rule is awkward for shared skill directories, which means a kit
renamed on subscription still loads there. And it refuses to read anything project-local
until you have trusted the folder, which is an answer to question 6 that opencode has no
equivalent of.

## 6. Sources

A source is a git repository holding parts. Nothing is registered, nothing is declared, and a
source never learns that you subscribed. This is what "federated" means here, and it costs one
thing: a source cannot tell you anything about itself. Section 9 is where that hurts.

**Almost every source in the world predates this idea**, which is the case the rules below are
written for. A repository with one skill in it was never going to add a manifest for our
benefit, and it does not have to.

### Naming one

Any of these is a source:

| Form | Example |
| --- | --- |
| GitHub shorthand | `owner/repo` |
| A forge URL: GitHub, GitLab, Azure Repos | `https://github.com/org/repo` |
| Any git URL | `git@github.com:org/repo.git`, `ssh://git@git.example.com/org/repo` |
| A URL into a subdirectory, selecting one part | `https://github.com/org/repo/tree/main/skills/writing` |
| A local path | `../my-kits` |

Private repositories need nothing extra. Git's configured authentication is what gets used,
and no credential is read, printed or carried by us.

A bare `SKILL.md` or an archive at some URL is not a source. The manifest records which
revision you have, an archive has no revision, and updating one would mean fetching it again
and hoping.

### Finding parts inside one

Every kind of part is found the same way, by looking in a fixed set of directories inside the
source. Each of those is walked up to three levels deep, so `<dir>/<name>/`,
`<dir>/<category>/<name>/` and one category deeper all resolve. A part found higher up
shadows anything nested beneath it.

| Kind | Looked for | Looked for in |
| --- | --- | --- |
| Skill | `SKILL.md` | the repository root, `skills/`, `skills/.curated/`, `skills/.experimental/`, `skills/.system/`, and the harness directories such as `.claude/skills/` and `.agents/skills/` |
| Rule | `*.md` | the repository root, `rules/`, `.github/instructions/` |
| Agent | `*.md` | the repository root, `agents/`, `.github/agents/`, `.claude/agents/`, `.opencode/agent/` |

So a repository holding one skill at its root is a source, and so is one holding sixty in
categories, and so is one that has never heard of any of this. The first of those is also a
kit, of one part, without anybody having decided so.

**Why those, for skills:** this is what `npx skills add` already accepts, which makes it what
repositories in the wild already look like. We follow the same rules and implement them
ourselves, because `skills` is node and section 10 keeps node away from anything a user runs.

**Why those, for rules and agents:** no standard exists, so they mirror the skills layout and
add the directories harnesses already read.

## 7. The manifest

**A kit is assembled here, not found out there.** A source offers parts. Which of them belong
together is a judgement you make, and the manifest is where you make it. Even a repository
that ships a skill alongside its activation rule has nothing tying the two together, so both
get named either way.

So the file subscribes to parts, and a kit is what a set of subscriptions amounts to. Thirty
of them is a normal number, so the file is shaped to stay readable at that size.

```yaml
version: 1

skills:
  owner/repo#v2: [writing, caveman]
  acme/kits:     ["*"]

rules:                 # order matters here, and nowhere else
- owner/repo#v1: prose-style
- acme/kits: security-review

agents:
  acme/kits#2026.3: [reviewer, release-manager]
```

**Kind is the top level, because kind decides everything downstream.** It picks the renderer,
the directory, and whether order means anything. Grouping by it means no entry has to say
which kind it is, and the three blocks can be read one at a time.

**The key is the source, written out.** Any of the forms from section 6 goes there: the
shorthand above, a full forge URL, a git URL, or a local path. There is no table of
nicknames to look up, and nothing that can go out of sync with one.

**`#ref` pins, and it pins per line.** `owner/repo#v2` and `owner/repo#v1` are two different
sources as far as the file is concerned, so the skills block can sit on a tag the rules block
has not moved to yet. A key with no `#` tracks the default branch. The separator is `#` and
not `@`, because `git@github.com:org/repo.git` already has one of those.

**Skills and agents are mappings, rules are a list.** That asymmetry is the point. Two skills
cannot disagree, so their order is noise. Two rules can, so the order you read down the page
is the order they are rendered in, and a YAML mapping would not promise that.

A `"*"` takes everything of that kind from that source. That is what you want from an
employer's repository and rarely from a public one.

### When a kit needs more than its name

Most do not. One that does becomes a mapping instead of a string:

```yaml
skills:
  owner/repo#v2:
  - writing
  - name: kb
    as: upstream-kb      # this name is taken
```

**`as` exists because two sources will eventually both ship a kit called `kb`.** opencode
demands skill names be unique across all six places it looks. pi keeps whichever it found
first and warns you. Neither source can fix this, because neither knows the other exists. The
manifest is the only place that can.

At thirty entries the file is for editing and `akit list` is for reading. The file never
grows a column of rendered paths or resolved commits, because those are answers the tool
computes.

### Two files, one format

One manifest holds what is true of you, and lives in the per-platform user config directory.
It is not shared.

The other holds what is true of one repository, is committed, and sits at `.akit.yaml` in its
root. One file, so no directory: `.akit/` would hold a single thing forever, and a top-level
dotfile is visible to anyone looking at the repository rather than hidden one level down.
Someone clones the repository, runs one command, and has what it expects.

**Which file a subscription is in is what decides its scope.** Yours renders everywhere.
A repository's renders inside that repository. There is no `scope:` key, because there is no
third answer.

The project file adds to yours rather than replacing it. Your subscriptions do not stop being
true because you changed directory. Where both name the same kit, the repository wins, which
is how a repository pins something different without you unsubscribing.

### What a repository commits

**The manifest, never the renders.** `.akit.yaml` is the source of truth; everything
`akit render` writes into the repository is generated, and generated files are ignored.

```gitignore
.github/instructions/
.claude/skills/
.agents/skills/
```

A repository that is its own source keeps the opposite habit: `skills/` is hand-written and
committed, and the rendered copies of it are not.

The workflow is clone, `akit render`, work. A colleague who has not installed the tool sees
`.akit.yaml` and nothing else, which is the honest signal that a step is missing.

**One class of render cannot be ignored**: marker blocks in a file the harness insists on
reading and the user hand-wrote the rest of. Those ride along with their host, which is
committed for reasons that have nothing to do with us.

That makes those files able to go stale, which nothing else here can. So `akit render
--check` exits non-zero when a render is out of date, as a pre-commit hook and in CI. It is
the same code path as `render`, writing nothing.

### Where a source actually is

A key names a source. It does not say where that source is on this disk, and an **absolute**
path in a committed file is always wrong: your colleague keeps it elsewhere, and on Windows
it is not even that shape of path.

So anything found by cloning is cloned, into the platform cache directory, and that is the
whole story for a colleague who just wants it to work.

**A relative path is a different thing, and it belongs in a committed file.** It resolves
against the repository root, so it means the same on every machine. The case it is for is a
repository that ships kits alongside its own code: a `skills/` directory holding what an
agent needs in order to work on *this* project. The source key is `.`, the parts are found by
the usual walk, and nothing is cloned or cached because the working tree is already there.

An absolute path as a key is the exception, and only ever in your own file. Use it for a
source you are writing rather than consuming.

When you need both at once, which is a project subscribing to `owner/repo` that you also
happen to be the author of, `akit link owner/repo ../my-kits` points this machine at your
checkout. It redirects where a source is read from, and has nothing to do with symlinks. That
goes in machine state beside the lockfile, never in either manifest, because it is true of one
laptop and nothing else.

### Always copied

**Rendering copies, on every platform, from every kind of source.** The hash of what was
copied goes in the lockfile, which is what lets `akit doctor` spot a rendered file somebody
has edited by mistake, and what makes an update a diff you read.

The alternative was a symlink for a source you have checked out and edit, so the harness sees
an edit with no render in between. It bought one saved command, and cost a feature that
behaves differently on Windows, where a symlink needs developer mode or an elevated shell.

So editing a kit you author means running `akit render` afterwards. That makes render speed a
real requirement rather than a nicety: it is the inner loop of writing a kit, not just
something you run after changing the manifest.

## 8. Rendering

Skills are copied into the harness directory unchanged. Several locations across four
harnesses already agree on `skills/<name>/SKILL.md`, so there is nothing to translate.

### Rules, and the three ways a harness can take them

Harnesses differ here more than anywhere else, and they will keep changing. So the design
names the three shapes a harness can have, and leaves which shape each one is to its adapter.

| Shape | What we render | What setup costs |
| --- | --- | --- |
| It reads a directory we can own | one file per rule, into that directory | nothing |
| It reads a directory, once pointed at one | one file per rule, into a directory we own | one line in its config, written once |
| It reads one fixed file, shared with the user | marker blocks inside that file | nothing |

**Prefer the first shape, accept the second, and treat the third as the fallback.** One file
per rule means removing a rule does not touch its neighbours, and a directory we own means a
render is never a merge.

The second shape exists because a harness that can be pointed somewhere lets our files stay
out of a file the user already owns. **That pointer is setup, not rendering.** It is written
once, by `akit` or by hand, and never rewritten, so no render has to preserve somebody's
comments or key order.

The third shape is the one that costs. A harness that reads exactly one file means sharing it
with whatever the user wrote there, so each rule sits between `BEGIN <id>` and `END <id>`
markers and everything between blocks survives. It is also the only render that can end up
committed, which is why [§9](#9-keeping-the-employers-kits-in) is mostly about it.

Rules are the only kind with an order. Two rules can contradict each other and something has
to win. The order they appear in the manifest decides it, and we are not looking for a
cleverer answer than that.

### Agents are the hard one

Every harness stores an agent as markdown with frontmatter. That looks like portability until
you read the keys.

| Harness | Location | Frontmatter |
| --- | --- | --- |
| opencode | `agent/*.md` | `model`, `tools`, `temperature`, `permission` |
| VS Code | `.github/agents/*.agent.md` | `description`, `tools`, `model`, `handoffs`, `mcp-servers` |
| Claude Code | `.claude/agents/*.md` | `name`, `description`, `tools`, `model` |
| pi, via `pi-agents` | `~/.pi/agent/agents/*.md` | `name`, `description`, `thinking`, `skills`, `tools` |

The prose body travels. The tool names, the model identifiers and the keys do not.

Neither does the idea of what an agent is for. An opencode subagent is handed work by a lead
agent. A VS Code custom agent is chosen by a person from a menu. One body serves both only
when it describes the task rather than who asked.

So an agent is one file: a portable body, plus a `harness:` block of per-target overrides.
The adapter translates what it knows. **A tool name it cannot translate stops the render.**
Dropping it quietly would produce an agent that fails later, somewhere else, for no visible
reason.

## 9. Keeping the employer's kits in

### What can actually leak

Almost nothing, because [§7](#7-the-manifest) says a repository commits no renders. A skill
copied into `.claude/skills/`, an agent file, a VS Code `.instructions.md`: all ignored, none
pushed anywhere.

Two things are committed, and they are the whole risk.

**A marker block inside a file somebody else owns.** This is the third shape in
[§8](#8-rendering): a harness that reads exactly one fixed file, which is committed because
the user wrote the rest of it. The employer's prose is now in a public repository, and the
diff looks like every other diff.

**The project manifest.** `.akit.yaml` names its sources, and
`git@git.acme.example:team/unreleased-thing-kits.git` is information even to somebody who
cannot clone it.

### How a source is known to be private

Not by declaring it. [§6](#6-sources) says a source declares nothing, and almost every source
in the world predates this idea, so anything that needs a file in the repository is a rule
that applies to nobody.

**Cloning it is the test.** A source that needed credentials is private. A source that clones
anonymously is public. A local path is unknown, and unknown is treated as private.

This costs nothing, needs no cooperation, and is true at the moment it matters, which is when
the parts are fetched. It is also occasionally wrong in the safe direction: a public
repository behind an authenticating proxy is treated as private, and the cost of that is a
refusal you override once.

### How a target is known to be public

By its git remotes. No remote means private, since nothing can leave. A remote that resolves
anonymously means public. Anything else, including a remote that cannot be reached, is
refused rather than guessed at.

### The rule

**A private source's parts do not render into a public target, and a private source is not
named in a public target's committed manifest.** Both halves fail hard, with a message naming
the source, the target and the override.

The override lives in your own manifest, never in the project one, because an override
committed into the public repository is the leak it was guarding against.

### What this is not

A guardrail, not a boundary. It reads a remote at render time, so it cannot help with a
repository made public next month, a file you copy by hand, or a colleague who already has
the credentials. What actually keeps your employer's kits in is that nobody else can clone
the source.

The failure it exists for is the ordinary one: you subscribed to something at work, you ran
`akit render` in a public repository, and nothing told you.

## 10. Windows, Linux, Python

**Windows and Linux are equal targets.** macOS should work and is not a priority.

That means, concretely:

- No `&&`, no pipes, no assuming `bash` exists. Two steps are two subprocess calls from
  Python.
- `pathlib.Path`, never a string with a slash in it.
- The config directory is looked up per platform, not spelled `~/.config`.
- Files are written with `encoding="utf-8"` stated out loud. Windows does not default to it.
- **No symlink is ever created.** Creating one on Windows needs developer mode or an elevated
  shell, so rendering copies instead ([§7](#7-the-manifest)). A symlink committed to a
  repository is worse still: a Windows clone writes it out as a text file containing a path,
  and whatever reads through it reads nonsense.
- Two kits whose names differ only in case collide. The filesystem may not tell them apart.

**CI runs the tests on `ubuntu-latest` and `windows-latest`, and both must pass.** There are
no tests yet, so that workflow does not exist yet. It lands with the first Python module. The
hygiene suite in `governance.yml` is the same on every platform and runs on Linux only.

**Python is the only language we write.** No TypeScript, no shell scripts, no Makefile recipe
doing real work. Every script carries its dependencies in a PEP 723 header and runs under
`uv run`, so there is no install step and no lockfile to go stale.

There is one exception, and it is deliberate. `.scripts/linkspector.mjs` is twenty lines of
node that pin a Chrome build and start a link checker. It runs inside a pre-commit hook,
never anywhere else, and nothing a user of `akit` touches depends on it.

## 11. Commands

```text
akit list                 # what you subscribed to, where it renders, whether it is current
akit add <source> <name> --kind rule      # -p writes the project file instead of yours
akit link <source> <path> # read this source from a local checkout instead of a clone
akit render               # --check writes nothing and fails when stale
akit update [name]        # re-pin what was copied, show the diff
akit doctor               # collisions, stale renders, refusals
```

`render` doing nothing when nothing changed is what makes the other four safe to trust.

## 12. The skill

Nobody reads this document before their first run, and an agent asked to "set up my kits"
has nowhere to look. So the tool ships a skill.

Three layers, each doing one job.

| Layer | Carries | Loaded |
| --- | --- | --- |
| A rule, about five lines | that `akit` is here, and when to reach for it | every message |
| The `akit` skill | getting started, which command for what, how to update | when the model opens it |
| The `akit` CLI | everything that has to be correct rather than persuasive | when it is run |

The skill covers three situations and no more. **Nothing is set up**, which means proposing
where sources live, writing the first manifest and rendering once. **Something needs doing**,
which means picking the right command and explaining what it just did. **A new release is
out**, which means what the upgrade asks of a setup already on disk.

Two rules keep the layers from bleeding into each other, and both were paid for in `fkb`.

**Anything deterministic lives in the CLI, never in prose.** The skill says run `akit list`.
It does not describe what the output looks like, because then there are two descriptions and
one of them goes stale.

**A skill may run a command. A skill never tells the model to open another skill.** Prose
calling prose through a language model is not control flow.

The five-line rule is the part that cannot be skipped. A skill nobody opens does nothing, and
what makes a model open this one is a sentence in the prompt saying when to.

### It bootstraps itself, once

The first copy of the skill is installed by hand, or by whatever skill installer you already
use. After that `akit` can subscribe you to its own skill from this repository, and the copy
you placed by hand becomes a managed one.

A skill that has been copied somewhere cannot tell how old it is, so it carries a `VERSION`
file. That is the only thing that survives being copied into a skills directory.

## 13. Still open

None of these blocks the first piece of work.

**Do rules need an `applyTo` glob?** VS Code has one, deciding when a rule applies. opencode
and pi have nothing like it, so such a rule would simply be always-on there. A field that one
harness out of four honours may be worse than no field. Write ten real rules and see whether
any of them wants it.

**How do tool names map between harnesses?** A table maintained by hand that fails on
anything unknown. Whether that table is per harness or per agent is open. Not worth deciding
until three agents genuinely want to live in two places.

**What does a pin mean when a source moves a tag?** `#v2` resolves to a commit, which the
lockfile records. If upstream re-points `v2` somewhere else, the next `akit update` sees a
different commit under the same name. Whether that is reported differently from an ordinary
update is open.

**Does the CLI ship inside the skill?** `fkb` puts it there, as `scripts/fkb`, so installing
the skill installs the tool and there is no second step. The alternative is a package on PyPI
and a skill that assumes it. The first is one artefact and no install; the second updates
without touching a skills directory.

**What happens when a source's layout changes under you?** A kit found at `skills/writing/`
today may be at `skills/prose/writing/` after an upstream tidy-up. The subscription names a
kit, not a path, so it still resolves. Whether that silent move is worth reporting on the
next `akit update` is open.

## 14. Not doing

**rulesync** renders to many harnesses from one directory, which is the rendering half of
this. It is scoped to a single project, with no sources, no tiers and no subscriptions, so it
would sit underneath the manifest rather than replace it. It is also node, which section 10
rules out for anything a user has to run.

**Sharing a manifest with `fkb`** would mean a colleague cloning a repository can read the
path to your private knowledge bundle. Different question, different file.

**A privacy field in each part** can disagree with the repository it is sitting in. The
repository already answers it. One place or none.

**Symlinked renders**, so that editing a source you author skips the render. One saved
command, against a feature that needs developer mode on Windows and a second code path
everywhere. `akit render` is the inner loop instead, and it has to be quick.

**A kit declaration inside a source**, saying which parts belong together. Almost no source
in the world would carry one, so the tool would need the manifest route anyway and this would
be a second way of expressing the same thing. It also moves a judgement to the publisher that
belongs to the subscriber: which parts you want together is a fact about your setup.

**Sharing whole `AGENTS.md` files** is the problem rather than the solution. It is the one
filename every harness insists on owning.

**One flat list of subscriptions** reads fine at five entries and badly at thirty. Every line
repeats which source and which kind it is, so the eye has to parse each one to find out what
it is looking at.

**Grouping by source instead of by kind** names each repository once, which is the thing it
has going for it. It then scatters the rules across the file, and rules are the one kind with
an order, so the order would stop being visible anywhere.

**A `sources:` block defining each repository once**, with the subscriptions referring to it
by nickname. It saves a little typing and costs two things. Every key becomes a lookup
somewhere else in the file, and the same repository can no longer sit at two versions in two
blocks without inventing two nicknames for one repository.

**MCP servers are not a fourth kind of kit.** The three we have are markdown you copy from
one place to another. An MCP server is a process: a command, its arguments, environment
variables, and usually a token. Rendering a file with a secret in it is a different risk from
rendering a file with advice in it, and it would be the only part of this tool that could
leak a credential.

They also land differently. No harness keeps one file per server. opencode has an `mcp` key
in its config, VS Code has a `.vscode/mcp.json` and an `mcp-servers` list in agent
frontmatter. Supporting them means merging into a file somebody else owns and edits, which
ends "rendered files are disposable" on the first attempt.

What we do instead costs nothing: an agent may name a server it expects, exactly as it names
skills, and `akit doctor` tells you whether you have it. Nothing is configured on your
behalf, and no secret passes through this tool.

## 15. The name

The system covers three kinds of kit, so a name mentioning only rules would be wrong within
a month. `federated-agents` reads as agents federating with each other, which is a different
and much noisier topic.

The command is `akit` rather than `kit` because KitOps already installs a `kit` binary to
`/usr/local/bin` through Homebrew. It serves the same AI audience and uses the verbs we want:
`kit init`, `kit list`, `kit diff`. The damage would not be a failed install. It would be
somebody running the wrong tool out of our own documentation.
