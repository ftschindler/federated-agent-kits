# DESIGN - federated agent kits

**Status:** first draft. Nothing is implemented. This document is the sole source of truth
for the design, so change it here first. [IMPLEMENTATION.md](IMPLEMENTATION.md) says in which
order it gets built.

**Date:** 2026-10-05

## 1. What this is

A tool and a skill for sharing **agent kits** portably: across machines, across operating
systems, and across harnesses.

A kit is an arbitrary composition of three parts. It may be a single skill. It may be a skill
with the rule that makes a model reach for it. It may be an agent, two skills it leans on and
a rule that sets the house style. What makes them one kit is that you want them together.

### The three parts

A **rule** is prose. The harness pastes it into the system prompt before every single
message. You pay for it on every turn, so keep it short.

A **skill** is a folder with instructions and optional supporting material (scripts or references)
inside. The model sees only its one-line description, and opens the folder when it judges the
description matches. An unopened skill costs almost nothing, so a skill can be long.

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
sources ([§6](#6-the-manifest)).

An agent can name skills it expects to be there. Those are not parts of it: they are a
dependency, and we do not chase dependencies. A named skill you have not subscribed to gets
you a warning from `akit doctor`, and nothing is installed that you did not ask for. An agent
naming an MCP server is treated the same way, and [§13](#13-not-doing) says why that is as
far as it goes.

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

## 4. Adding a harness

Write an adapter. An adapter answers seven questions, and nothing else in the system changes.

1. Where do skills go, and which directories does this harness also read them from?
2. How does it pick up rules: a directory we own, a directory it can be pointed at once, or
   one fixed file we have to share ([§7](#7-rendering))?
3. If it is the middle one, what is the pointer, and what writes it at setup?
4. Where do agents go, and what are the frontmatter keys called?
5. What are this harness's tools called?
6. Which directory does it treat as the project, and will it read what we put there?
7. How do I tell whether this harness is on this machine at all?

"This harness has no agents" is a valid answer to question 4. The adapter declines that kind
and the command says so.

**One adapter per harness, rather than one per job.** Detection, the directories a source may
keep a part in, and the rendering of each kind are three different jobs with three different
indexes, and splitting them into three families of file would be the obvious move. It is the
wrong one: all three change together whenever a harness moves a directory, so the thing that
varies together is the harness. That is rule 7, and it is why the adapter is one file with
sections rather than several files with a registry.

**Question 1 has two halves because reading and writing are different lists**
([§5](#5-sources)). Where we put a skill is where this harness looks for one. Where a *source*
may have left a skill is a wider set, and a repository that is its own source makes the
difference matter.

**Question 7 decides who gets rendered for**, and it is a question rather than a setting
because of rule 8: nothing to configure after install. A harness you use has left something
on this disk, `~/.config/opencode/`, `~/.pi/`, a VS Code profile, and the adapter knows
which thing to look for. Finding it is the same kind of evidence as
[§8](#8-keeping-the-employers-kits-in)'s clone test: observable at the moment it matters,
needing nobody's cooperation. [§10](#10-commands) says what `render` does with the answer.

**It asks about this machine and never about a repository.** A checkout holding
`.github/agents/` is suggestive, and inferring a harness from it is exactly what this must
not do: turning on a harness with no machine starts committing rendered rules, which
[§6](#6-the-manifest) argues has to be a line somebody wrote. What a repository contains is
discovery, and discovery never switches anything on.

"I am never here" is the valid answer for a harness with no machine, and it is why that kind
has to be named in a manifest instead.

**Question 6 is the one that silently renders into the wrong place.** We render a
repository's kits next to its `.akit.yaml`, at the git root. A harness that anchors somewhere
else never sees them, and nothing fails: the files exist, the agent just behaves as if they
do not. Three ways it diverges, all real:

- **A different anchor.** pi takes the nearest ancestor holding a `.pi` directory, which in a
  monorepo is a package rather than the repository.
- **A different idea of a project.** VS Code uses the open workspace, which can be several
  folders at once, or one subfolder of a repository.
- **A condition before reading.** pi ignores everything project-local until you have trusted
  the folder, so correctly placed files stay unread.

The first two the adapter resolves, by computing the harness's anchor rather than assuming
the git root. The third it cannot, so it reports: `akit doctor` says the files are in place
and this harness is not reading them yet.

**One property, not a question: some harnesses have no machine.** GitHub Copilot running in
CI is a harness by every test above. It reads instruction files, it has custom agents, it
answers all seven questions, though its answer to the seventh is that it is never here. What
it does not have is somewhere for `akit render` to run: it clones the repository and reads
what is in the clone.

So an adapter declares which it is. A harness with a machine is detected and gets files
rendered on demand and ignored by git. A harness without one cannot be detected by anything
running on your laptop, so it is named in the repository's manifest, and its files are
committed because for it the repository is the delivery mechanism
([§6](#6-the-manifest)).

**An adapter is where a harness's changes land.** When one moves its directories or replaces
its config key, the fix is that one file, not this design.

The four that follow are worked examples, and nothing else here may depend on a path in them.
**They are a snapshot of where each harness kept things when this was written**, and every one
of those paths will move.

### What opencode looks like

opencode reads a list, which makes rules the easy case. Its config takes an `instructions`
key of files, globs and even https URLs, and combines all of them with whatever `AGENTS.md`
files it found. So it is the second shape: pointed once at a directory we own, and never
edited again.

| opencode | Repository | User-wide |
| --- | --- | --- |
| Rules | `AGENTS.md` up to the worktree root, plus `instructions` globs | `~/.config/opencode/AGENTS.md`, plus `instructions` in the global config |
| Skills | `.opencode/skills/`, `.claude/skills/`, `.agents/skills/` | the same three under `~` |
| Agents | `.opencode/agent/*.md` | `~/.config/opencode/agent/*.md` |

Question 6 is cheap here: opencode walks up to the git worktree root, which is where
`.akit.yaml` already is.

### What VS Code looks like

VS Code insists on fixed paths, so everything is written where it looks.

| VS Code | Repository | User-wide |
| --- | --- | --- |
| Rules | `.github/copilot-instructions.md`, `.github/instructions/*.instructions.md`, root `AGENTS.md` | profile data for Local, `~/.copilot/instructions/` for Agent Host |
| Skills | `.claude/skills/`, where the harness supports it | varies, and this is the weak leg |
| Agents | `.github/agents/*.agent.md`, `.claude/agents/` | `~/.copilot/agents/`, or profile data |

There is a setting that would make it the second shape, and we are not using it.
`chat.instructionsFilesLocations` does take absolute and `~` paths. The documentation marks
it deprecated and says only the Local agent honours it, so neither Agent Host nor the cloud
agent would see anything we wrote there.

Question 6 is the awkward one. VS Code anchors on the open workspace, which is usually the
repository and sometimes one folder inside it, and sometimes several folders at once. An
`applyTo` glob resolves against that workspace root too, so a rule written for `src/**` stops
matching when somebody opens the subfolder instead.

### What pi looks like

pi is about as cheap as an adapter gets.

**Skills: nothing to write.** pi already reads `~/.agents/skills/` and `.agents/skills/`.
Its `settings.json` also takes a list of skill directories, absolute or `~`-relative.

**Rules: one fixed file, shared.** pi reads `~/.pi/agent/AGENTS.md` plus every `AGENTS.md`
walking up from the working directory, and joins them. Nothing can be pointed anywhere, so it
is the third shape and gets marker blocks, the same as Claude Code.

**Agents: only via a package.** The third-party `pi-agents` package puts them in
`~/.pi/agent/agents/*.md`, with `name`, `description`, `thinking`, `skills` and `tools`. An
adapter can support that and must not assume it is installed.

**Question 6 has two answers here, and both are awkward.** The project anchor is the nearest
ancestor holding a `.pi` directory, not the git root. And nothing project-local is read until
the folder is trusted, which is the condition `akit doctor` has to report rather than fix.

One more pi detail generalises. It deliberately does not require a skill's `name` to match
its directory, saying the rule is awkward for shared skill directories, which means a kit
renamed on subscription still loads there.

### What GitHub Copilot in CI looks like

The cloud agent runs on GitHub's infrastructure, clones one repository and works in it. It is
the harness with no machine, so **everything below has to be committed or it does not exist**.

**Skills: a directory we own, committed.** It reads `.github/skills/`, `.claude/skills/` and
`.agents/skills/`, each a directory of `<name>/SKILL.md`. A root-level `skills/` is not among
them, which matters for a repository that is its own source: its hand-written `skills/` is
not what the cloud agent reads, and the rendered copy in `.agents/skills/` is.

**Rules: a directory we own, committed.** `.github/instructions/` takes one
`*.instructions.md` per rule, with `applyTo` globs, and that is the shape we want everywhere.
It also reads `.github/copilot-instructions.md`, any `AGENTS.md` in the tree with the nearest
winning, and a root `CLAUDE.md` or `GEMINI.md`. We write to the directory and leave the rest
alone.

**Agents: `.github/agents/<name>.agent.md`, committed.** `description` is required, `name`
defaults to the filename, and `tools` and `mcp-servers` are optional. The prompt caps at
30,000 characters, which is the only hard size limit any harness documents.

Question 6 answers itself: the project is the checkout, and there is nothing else. Nested
`AGENTS.md` files are read nearest-first, so a monorepo can vary its rules by directory
without the adapter doing anything special.

**Two things it reads that we cannot touch.** Organisation-level instructions live in GitHub
settings, and MCP servers may be configured in repository settings rather than in a file.
Neither is in the repository, so neither is renderable, and both can contradict a rule we
wrote. `akit doctor` has no way to see them; the design's answer is to say so here rather
than to pretend the repository is the whole story.

## 5. Sources

A source is a git repository holding parts. Nothing is registered, nothing is declared, and a
source never learns that you subscribed. This is what "federated" means here, and it costs one
thing: a source cannot tell you anything about itself.
[§8](#8-keeping-the-employers-kits-in) is where that hurts.

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
| Skill | `SKILL.md` | the repository root, `skills/`, and its `.curated/`, `.experimental/` and `.system/` subdirectories |
| Rule | `*.md` | the repository root, `rules/` |
| Agent | `*.md` | the repository root, `agents/` |

Each kind then adds the directories harnesses already read for it, which every adapter
declares and nothing here enumerates.

So a repository holding one skill at its root is a source, and so is one holding sixty in
categories, and so is one that has never heard of any of this. The first of those is also a
kit, of one part, without anybody having decided so.

**Why those, for skills:** this is what `npx skills add` already accepts, which makes it what
repositories in the wild already look like. We follow the same convention and implement it
ourselves, because `skills` is node and [§9](#9-windows-linux-python) keeps node away from
anything a user runs. Following it rather than restating it is also why no harness directory
appears in that row: when the convention grows one, we grow one.

**Why those, for rules and agents:** no standard exists, so they mirror the skills layout.

### Reading is not writing

**The directories a source may keep a part in are not the directories we render into**, and
an adapter declares both ([§4](#4-adding-a-harness)).

They read as one list today because a harness reads what it writes. They stop being one list
the moment a repository is its own source: `akit render` writes a skill into
`.agents/skills/`, and discovery that treated that directory as a source would find our own
output and call it an input. A `"*"` subscription would then double on the second render.

So discovery subtracts what the render record says we wrote
([§6](#6-the-manifest)). The record is already the authoritative list of this tool's files,
and this is one more thing that follows from it. A record that has been deleted takes this
with it until the next render rebuilds one, which is the same gap [§6](#6-the-manifest)
describes for orphans and has the same answer: `akit doctor` reports, `akit render --prune`
acts.

Which directories exist at all is a property of the adapters shipped in the package, not of
this machine, so two people on one version of `akit` read a source identically
([§9](#9-windows-linux-python)).

## 6. The manifest

**A kit is assembled here, not found out there.** A source offers parts. Which of them belong
together is a judgement you make, and the manifest is where you make it. Even a repository
that ships a skill alongside its activation rule has nothing tying the two together, so both
get named either way.

So the file subscribes to parts, and a kit is what a set of subscriptions amounts to. Thirty
of them is a normal number, so the file is shaped to stay readable at that size.

```yaml
version: 1

skills:
  owner/repo#9f2c1ab: [writing, caveman]   # frozen: v2
  acme/kits#4d7e08b: ["*"]                 # frozen: main, 2026-10-05

rules:                                     # order matters here, and nowhere else
- owner/repo#1c04f7e: prose-style          # frozen: v1
- acme/kits#4d7e08b: security-review       # frozen: main, 2026-10-05

agents:
  acme/kits#4d7e08b: [reviewer]            # frozen: main, 2026-10-05
```

**Kind is the top level, because kind decides everything downstream.** It picks the renderer,
the directory, and whether order means anything. Grouping by it means no entry has to say
which kind it is, and the three blocks can be read one at a time.

**The key is the source, written out.** Any of the forms from [§5](#5-sources) goes there: the
shorthand above, a full forge URL, a git URL, or a local path. There is no table of
nicknames to look up, and nothing that can go out of sync with one.

**The key carries a commit, and the comment says what it was.** This is `.pre-commit-config`'s
habit, taken wholesale: the data is a hash, the human-readable name of it is a comment, and
`akit` writes both. The separator is `#` and not `@`, because `git@github.com:org/repo.git`
already has one of those.

A commit is immutable, so a pin cannot move under you, and nothing has to be recorded
elsewhere to make that true. Two blocks naming two commits of one repository are two
subscriptions, which is how the skills block sits on an older commit than the rules block.

You never type the hash. `akit add` resolves a tag or branch you name and writes the hash
with the comment; `akit update` moves both. The comment is for a reader and nothing parses
it, which is the only safe thing to do with a comment.

**Skills and agents are mappings, rules are a list.** That asymmetry is the point. Two skills
cannot disagree, so their order is noise. Two rules can, so the order you read down the page
is the order they are rendered in, and a YAML mapping would not promise that.

A `"*"` takes everything of that kind from that source. That is what you want from an
employer's repository and rarely from a public one.

### When a kit needs more than its name

Most do not. One that does becomes a mapping instead of a string:

```yaml
skills:
  owner/repo#9f2c1ab:    # frozen: v2
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

### Naming the harnesses, when detection is not enough

A repository's manifest may carry one more key, and most never do:

```yaml
version: 1
harnesses: [detected, copilot-ci]
```

**The list is the whole answer, and `detected` is a member of it.** That word expands to
every harness this machine has, by question 7 of [§4](#4-adding-a-harness). An absent key
means `[detected]`, which is the ordinary repository.

One key serves two needs, which is why it is a list of names rather than a pair of flags, and
why the detected set had to become a name you can write down.

**A harness with no machine can only arrive by being named.** Nothing on your laptop can tell
you that GitHub Copilot in CI is in use, because the machine that runs it is a GitHub runner
that will never run `akit`. Naming it is also the right ceremony: it is the largest leak
surface in [§8](#8-keeping-the-employers-kits-in), and turning it on moves a directory of
rendered rules into the repository's commits. That should be a line somebody wrote, not a
thing that happened.

**Naming one does not cost you the others**, and this is what `detected` is for. Turning on
the cloud agent is a statement about what gets committed, not about what the people working
on the repository have installed. A list reading `[detected, copilot-ci]` says both things at
once: commit what the cloud agent reads, and keep rendering for whatever each colleague
actually uses. `akit harness add copilot-ci` writes exactly that, keeping `detected` in
place.

**A named harness is rendered for unconditionally**, whether or not `detected` is in the list
and whether or not this machine has it. `akit harness add opencode` in a repository that
keeps `detected` therefore still means something: everybody gets opencode's files, including
the colleague who has not installed it. The list is the whole answer, so a name on it is an
answer and detection never overrules one.

**Dropping `detected` is how you pin instead.** A list of named harnesses and nothing else
means everybody working on the repository gets the same files regardless of what they have
installed. `akit harness remove detected` does it, and on a machine holding a harness the
list does not name, it withdraws what that harness had rendered, the same as removing any
other name ([§10](#10-commands)).

The pinned case has a cost, which is the reason it is not the default. A colleague whose
harness is not on the list gets nothing rendered for it, and nothing fails. `akit doctor`
reports that: a harness detected on this machine and excluded by the manifest is worth one
line, because the alternative is an agent that behaves as if the kits were never there.

This key is mostly for a repository, where it decides what gets committed. Your own manifest
may carry it, and the reason is the narrower one: nothing at user scope is committed, so
there is no machineless harness to name, and what a name buys you there is rendering for a
harness `detected` does not find.

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
true because you changed directory.

**Neither file overrules the other, because they never write to the same place.** Yours
renders into the machine-level harness directories and a repository's renders inside that
repository ([§10](#render)), so a name used in both produces two copies in two directories
and neither can overwrite the other. There is no precedence rule here, and an earlier draft
of this section claimed one.

What a shared name does produce is a harness holding two kits under one name, which opencode
refuses and pi resolves by keeping whichever it found first. So the collision is reported
rather than resolved: `akit list` names both subscriptions and both scopes, `akit doctor`
reports it with the fix, and the fix is `as:`, which is the thing the manifest is the only
place able to do ([§6](#when-a-kit-needs-more-than-its-name)).

**`akit add` refuses the collision it can see you making.** Typing `akit add` for a name you
already subscribe to fails before the manifest is touched, naming the other subscription and
`--as`, the same way it fails when the kit is not in the source ([§10](#add)). That is a
usage error and not a refusal in the sense of [§8](#8-keeping-the-employers-kits-in): there
is something to type instead, and reserving the refusal exit code for the cases with no
override is what keeps it worth reading.

A collision that arrives by cloning a repository, or by `update` moving a pin onto a source
that renamed something, is nobody-present and is not refused. `render` writes both copies and
says what it did. It runs from a git hook and does both scopes at once, so refusing would let
a repository you are only passing through stop your own kits from rendering, over a condition
that puts no file at risk.

**Rules are the one kind where reading the two files in order means anything**, since order
is what decides a contradiction ([§7](#rules-and-the-three-ways-a-harness-can-take-them)).
Yours come first and the repository's come after, so a repository that disagrees with you
about something gets the last word on its own ground. Within each file the order is the order
you wrote. This is the one place the two manifests form a single sequence, and it costs
nothing elsewhere: the other two kinds have no order to merge.

### Finding them

Yours is at a fixed place, looked up per platform. Nothing searches for it.

The repository's is found by walking up from the working directory to the worktree root,
stopping at the `.git` there, and looking for `.akit.yaml` beside it. Running a command from
a subdirectory is normal and has to work. The walk cannot stray into somebody else's
repository, because it stops at the first worktree root, and it cannot reach the user
manifest, which is in the config directory and never on that path.

**Reading uses both, always.** `render`, `list` and `doctor` work from the two together, with
each subscription acting on its own scope: yours on the machine-level harness directories, a
repository's inside that repository ([§10](#10-commands)).

**Writing picks one, and gets asked.** `add`, `remove` and `akit harness` write a manifest,
`render` never does, and the flags are git's: `--global` for yours, `--project` for the
repository's. The same two flags narrow the reading commands when you want one scope rather
than both.

**With neither flag, the repository's wins.** A repository with no `.akit.yaml` is an error
naming `--global`, rather than a quiet write to your personal file.

That default is chosen for how each mistake is discovered. A subscription that lands in the
repository by accident shows up in `git status` within seconds. One that lands in your
personal file by accident shows up when a colleague clones the repository and does not get
it, which may be weeks. Prefer the mistake that announces itself.

`--manifest <path>` writes to a file named outright, which is for scripts and tests rather
than for people.

### What a repository commits

**The manifest, and the renders for harnesses that have no machine.** Everything else
`akit render` writes is generated and ignored.

The ordinary case is ignore. A harness runs on your laptop, where `akit` also runs, so the
files it reads can be produced on demand.

**Rendering maintains the ignore rules, because forgetting one is how a laptop harness's
output gets committed.** Every render writes a marker block at the end of the repository's
`.gitignore`, holding one line per directory it wrote into and did not mean to commit:

```gitignore
# BEGIN akit
.agents/skills/
.opencode/agent/
# END akit
```

It is a file the user owns, so it gets the same treatment as the third shape in
[§7](#7-rendering): everything outside the markers survives untouched, and the block is
rewritten whole each time. A directory that stops being rendered leaves the block on the next
render, and a harness that becomes machineless-committed leaves it too, since those entries
are exactly the inverse of what gets committed. Nobody has to keep the two lists in step by
hand.

A line the user wrote themselves that already covers one of those directories is left where
it is, and duplicated inside the block, which costs nothing: git does not mind an entry twice.
Removing ours is then still safe.

**A directory with two readers is committed if either of them commits**, because git cannot
ignore a directory halfway. Skills share one directory ([§7](#7-rendering)), so naming the
cloud agent takes `.agents/skills/` out of the ignore block and puts the skills every other
harness was reading privately into the repository's history. That is the intended behaviour
rather than a side effect, and it is why [§8](#8-keeping-the-employers-kits-in) asks which
parts land somewhere a machineless harness reads rather than which parts it renders.

The workflow is clone, `uvx --from federated-agent-kits akit render`, work. A colleague who
has never run this tool sees
`.akit.yaml` and nothing else, which is the honest signal that a step is missing, and that
step is one command with no install in front of it
([§9](#9-windows-linux-python)).

**Two kinds of render have to be committed anyway.**

The first is marker blocks in a file the harness insists on reading and the user hand-wrote
the rest of. Those ride along with their host, which is committed for reasons that have
nothing to do with us.

The second is everything read by a harness with no machine, which is the case
[§4](#4-adding-a-harness) describes: GitHub Copilot in CI clones the repository and reads
what is there. Nobody runs `akit render` in that clone, so a file it is supposed to read and
that is not committed does not exist. Its three directories, `.github/instructions/`,
`.github/agents/` and the shared skills directory, stay out of the ignore block from the
moment the manifest names that harness.

That overlap is convenient rather than awkward. `.github/instructions/` and `.agents/skills/`
are also where harnesses on your laptop look, so one committed set serves both, and those
harnesses stop needing a render at all.

A repository that is its own source keeps the opposite habit for its inputs: `skills/` is
hand-written and committed, and the rendered copies of it follow the rules above.

**Anything committed can go stale**, which nothing ignored can. So `akit render --check`
exits non-zero when a render is out of date, as a pre-commit hook and in CI. It is the same
code path as `render`, writing nothing.

### Where a source actually is

A key names a source. **It does not say where that source is on this disk**, and the two
questions stay apart: `add` writes what you want, resolution works out where that is.
Cloning is not a step of any command; it is what resolution does when it meets a remote
source the cache does not hold.

So anything remote is cloned, into the platform cache directory, and that is the whole story
for a colleague who just wants it to work.

**A path as a key is a source that is already here.** Nothing is cloned, nothing is cached,
and rendering reads your working tree. There is no commit to pin, so such a subscription
carries no `#`, `update` skips it, and `list` says it is local. That is the right trade for a
source you are writing: the point is that an edit is visible to the next render.

A relative path resolves against the repository root, so it means the same on every machine
and belongs in a committed file. The case it is for is a repository that ships kits alongside
its own code: `.` as the key, a `skills/` directory holding what an agent needs in order to
work on *this* project.

An absolute path only ever makes sense in your own manifest, since nobody else's disk looks
like yours.

**A committed manifest may only name a path that stays inside the repository.** `.` and
`./kits` mean the same thing on every machine. `../my-kits` and `/home/me/kits` mean something
only on yours, and committing one breaks the repository for everybody else.

That is a check rather than a convention, and it belongs in a pre-commit hook this project
ships for other repositories to pin, the way the leak refusal does
([§8](#8-keeping-the-employers-kits-in)). `akit doctor` reports the same thing.

**To work on a source a committed manifest names**, edit the key to your checkout and do not
commit that line. `git status` shows the file is dirty, `git checkout --` undoes it, and the
hook above stops it reaching a commit. There is no separate override mechanism, because git
already is one.

**Writing a new kit therefore needs neither.** It has no remote yet, so you subscribe to
where it is: `akit add ~/kits/my-new-thing my-new-skill --global`. Your manifest now carries
an absolute path with no commit, rendering reads the working tree, and the loop is edit,
`akit render`, try it. When it is published, `akit remove` that subscription and `add` the
repository instead.

### Always copied

**Rendering copies, on every platform, from every kind of source.** The hash of what was
copied is recorded, which is what lets `akit doctor` spot a rendered file somebody has edited
by mistake, and what makes an update a diff you read.

The alternative was a symlink for a source you have checked out and edit, so the harness sees
an edit with no render in between. It bought one saved command, and cost a feature that
behaves differently on Windows, where a symlink needs developer mode or an elevated shell.

So editing a kit you author means running `akit render` afterwards. That makes render speed a
real requirement rather than a nicety: it is the inner loop of writing a kit, not just
something you run after changing the manifest.

### What a render leaves behind

The manifest already says which commit every subscription is on, so nothing has to be
recorded to make a setup reproducible. What does need recording is what this particular
machine wrote, and that is nobody else's business.

**The render record** lives in the state directory and is never committed. It names every
file a render produced, every subscription and harness that explains it, and a hash of the
copy.

**Explained by a set, not by one subscription.** A shared file has several harnesses wanting
identical bytes ([§7](#7-rendering)), so the record holds all of them and withdrawal deletes
only when none of them is in scope any more ([§10](#10-commands)).

**It is also the list of files this tool may delete, and the list is exhaustive.** A file not
in the record was not written by us, so no command touches it, whatever directory it is
sitting in and whatever it is called. Somebody's hand-written skill in `.agents/skills/` is
not our business, and the record is what makes that a fact rather than a promise.

That exhaustiveness has a second reader. Discovery subtracts the record before looking for
parts ([§5](#5-sources)), so a repository that is its own source never finds its own rendered
output and calls it an input.

Within the record the hash decides. One that still matches is a copy, and deleting a copy
destroys nothing. One that no longer matches is a rendered file somebody edited, which is the
only file in a rendered directory that contains anything, so it is reported and left where it
is ([§10](#10-commands)).

It also records how each remote source was classified when it was fetched
([§8](#8-keeping-the-employers-kits-in)), because needing credentials to clone is only
observable while cloning. A path is not fetched and does not need the record: it takes the
repository's own classification, which costs nothing to work out again.

It is a cache of facts about this disk, so deleting it costs one `akit render` and nothing
else. One thing does not come back: a file rendered before the record was deleted is now
unknown rather than unexplained, so nothing will clean it up on its own. `akit doctor`
reports what looks like an orphan and `akit render --prune` acts on it, which is the only
place this tool deletes a file it cannot prove it wrote.

**`render` never moves a pin.** Only `add` and `update` touch the pins, which is what makes
rendering safe to run from a hook: it can change files on disk, never what a kit contains.

## 7. Rendering

### One copy where the bytes agree, one per harness where they do not

**A render that produces identical bytes for several harnesses is written once. Everything
else is written per harness.** That is the whole rule, and which case a kind falls into is
decided by whether the render translates anything.

Skills are copied unchanged, so every harness wants the same file, and writing it four times
would mean four ignore lines and four withdrawal candidates for one subscription. They go to
`.agents/skills/`, which opencode, pi and the cloud agent all read directly.

Rules and agents are translated. The tables below show harnesses disagreeing about
frontmatter keys, tool names and what an agent is even for, so there is no shared shape to
write and these go to each harness's own directory.

The exception proves the rule rather than bending it. VS Code and the cloud agent both read
`.github/instructions/` in the same shape, so that render is shared for the same reason
skills are: the output is identical, not because the directory happens to have two readers.

Three things follow, all of them in [§6](#6-the-manifest). The render record explains a
shared file by every subscription and harness that wanted it, rather than by one. Withdrawal
deletes a shared file when no harness in scope explains it any more. And a shared directory
read by any harness that commits is committed, because git has no way to ignore a directory
halfway.

### Skills

Copied into `.agents/skills/` unchanged. Several locations across four harnesses already
agree on `skills/<name>/SKILL.md`, so there is nothing to translate.

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
markers and everything between blocks survives. It is committed whatever we do, because its
host is, which makes it one of the things [§8](#8-keeping-the-employers-kits-in) counts as
able to leak.

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

## 8. Keeping the employer's kits in

### What can actually leak

Whatever the repository commits, and [§6](#6-the-manifest) keeps that list short. In an
ordinary repository a skill copied into `.agents/skills/`, an agent file, anything a harness
on your laptop reads: all ignored, none pushed anywhere.

Three things are committed, and they are the whole risk.

**A marker block inside a file somebody else owns.** This is the third shape in
[§7](#7-rendering): a harness that reads exactly one fixed file, which is committed because
the user wrote the rest of it. The employer's prose is now in a public repository, and the
diff looks like every other diff.

**Everything a machineless harness reads.** Turning on GitHub Copilot in CI moves a whole
directory of rendered rules into the repository, by design. It is the largest surface here
and the easiest to forget, because committing those files is the correct behaviour rather
than a mistake.

**The project manifest.** `.akit.yaml` names its sources, and
`git@git.acme.example:team/unreleased-thing-kits.git` is information even to somebody who
cannot clone it.

### How a source is known to be private

Not by declaring it. [§5](#5-sources) says a source declares nothing, and almost every source
in the world predates this idea, so anything that needs a file in the repository is a rule
that applies to nobody.

**Cloning it is the test.** A source that needed credentials is private. A source that clones
anonymously is public.

This costs nothing, needs no cooperation, and is true at the moment it matters, which is when
the parts are fetched.

**A path inside the repository is as public as the repository.** It is the same files, in the
same commit, behind the same remote, so nothing has to be asserted and nothing has to be
cloned. That covers the case [§6](#6-the-manifest) designs for, a repository shipping kits
beside its own code with `.` as the key.

A path outside the repository can only appear in your own manifest, because a committed
manifest may not name one ([§6](#6-the-manifest)). Your manifest renders to machine-level
directories, which have no remote and so no target to leak into, and the question never gets
asked.

So a source is private or it is public, and there is no third state to decide what to do
with.

### How a target is known to be public

By its git remotes. No remote means private, since nothing can leave. A remote that resolves
anonymously means public. Anything else, including a remote that cannot be reached, is
refused rather than guessed at.

### The rule

**A private source's parts do not render into a public target, and a private source is not
named in a public target's committed manifest.** Both halves fail hard, with a message naming
the source and the target.

There is no override and no `--force`. The two refusals this leaves are the ones worth
keeping: a genuinely private source aimed at a public repository is the failure this section
exists for, and a remote that cannot be reached is transient, so the answer is to try again
when it resolves.

The check is per harness, not per repository, because a repository may render to five
harnesses and commit the output of only one. Rendering a private kit for a laptop harness in
a public repository is fine: nothing is committed. Rendering the same kit for a machineless
harness in that repository is the leak.

It asks which parts land somewhere a machineless harness reads, rather than which parts that
harness renders. Skills share one directory ([§7](#7-rendering)), so a kit rendered for
opencode in a repository that also names the cloud agent is committed by that fact alone.

**Which is also what keeps `render` offline.** A target is classified only when the manifest
names a machineless harness, and those exist only by being named in `.akit.yaml`
([§6](#6-the-manifest)). An ordinary repository never asks what its remotes are, so a render
on a train is the same render as yesterday's ([§10](#10-commands)), and the pre-commit hook
in [§9](#9-windows-linux-python) needs a network only in the repositories that commit
rendered files.

### What this is not

A guardrail, not a boundary. It judges a remote at the moment it runs, so it cannot help with
a repository made public next month, a file you copy by hand, or a colleague who already has
the credentials. What actually keeps your employer's kits in is that nobody else can clone
the source.

The failure it exists for is the ordinary one: you subscribed to something at work, you
turned on a harness that commits in a public repository, and nothing told you.

## 9. Windows, Linux, Python

**Windows and Linux are equal targets.** macOS should work and is not a priority.

That means, concretely:

- No `&&`, no pipes, no assuming `bash` exists. Two steps are two subprocess calls from
  Python.
- `pathlib.Path`, never a string with a slash in it.
- The config directory is looked up per platform, not spelled `~/.config`.
- Files are written with `encoding="utf-8"` stated out loud. Windows does not default to it.
- **No symlink is ever created.** Creating one on Windows needs developer mode or an elevated
  shell, so rendering copies instead ([§6](#6-the-manifest)). A symlink committed to a
  repository is worse still: a Windows clone writes it out as a text file containing a path,
  and whatever reads through it reads nonsense.
- Two kits whose names differ only in case collide. The filesystem may not tell them apart.

**CI runs the tests on `ubuntu-latest` and `windows-latest`, and both must pass.** There are
no tests yet, so that workflow does not exist yet. It lands with the first Python module. The
hygiene suite in `governance.yml` is the same on every platform and runs on Linux only.

**Python is the only language we write.** No TypeScript, no shell scripts, no Makefile recipe
doing real work. Every script carries its dependencies in a PEP 723 header and runs under
`uv run`, so there is no install step and no dependency lockfile of our own to go stale.

There is one exception, and it is deliberate. `.scripts/linkspector.mjs` is thirty lines of
node that pin a Chrome build and start a link checker. It runs inside a pre-commit hook,
never anywhere else, and nothing a user of `akit` touches depends on it.

### How it ships

**A package on PyPI, so `uvx --from federated-agent-kits akit render` works in a clone with
nothing installed first.**

That is a constraint rather than a packaging preference, and it comes from
[§6](#6-the-manifest). A repository's `.akit.yaml` says what an agent working on that
repository needs. The workflow is clone, render, work, and a colleague meets it on the day
they first touch the repository: they have the clone, they do not have `akit`, and the thing
standing between them and a working setup must be one command rather than an installation
they have to be talked through.

`uvx` is what makes that a single command on both target platforms. It fetches the package,
runs it in a throwaway environment and leaves nothing behind, so the honest instruction in a
contributing guide is one line and the honest instruction in a pre-commit hook is the same
line.

Three things follow.

**The package is the unit, not the repository.** `uvx --from federated-agent-kits akit`
resolves a published version, so
what a colleague runs is a release rather than whatever is on `main` this afternoon. A
rendered file's shape is therefore a thing that can be versioned and a change to it is a
release note.

The adapters ship inside it, which puts their directories on the same surface. Discovery is
the union of what they declare ([§5](#5-sources)), so adding one changes what a `"*"`
subscription resolves to, and it changes it on upgrade rather than on anybody's machine
drifting. Two people on one version read a source identically; that is the property worth
having, and the release note is what it costs.

**The CLI does not live inside the skill.** `fkb` puts its tool in `scripts/fkb`, which makes
installing the skill install the tool and is the right trade there. Here it is the wrong one:
a copy of the CLI inside a skills directory is a copy that `uvx` cannot resolve, cannot
update, and that a colleague with no skills directory yet cannot reach at all. The skill
assumes the CLI and says how to run it ([§11](#11-the-skill)).

**A pre-commit hook is the other caller, and it wants the same thing.** The hook this project
ships for `render --check` and for the leak refusal
([§8](#8-keeping-the-employers-kits-in)) names the published package and a version, exactly
as every other hook in this repository's own config does.

An entry point named `akit` is therefore part of the package's contract, and renaming it is a
breaking change for every hook config and every contributing guide that pinned it.

**The distribution and the command have different names, and every published instruction has
to carry both.** `uvx <name>` reads `<name>` as a distribution to resolve, not as a command to
find, and infers the command from it. So naming only the command asks the index for a
distribution called `akit`, which exists and is not this one. The correct spelling names the
distribution with `--from` and the command after it:

```sh
uvx --from federated-agent-kits akit render
```

The short spelling was in this document, in the README and in the implementation plan before
anybody ran it, which is the failure worth recording rather than the typo. It was wrong in the
one place being wrong costs the most, since the sentence it appears in is the one a colleague
copies on the day they first touch the repository, and what they would have got is an unrelated
package. Today that package ships no console script, so the instruction fails confusingly; it
is one release by its owner away from running somebody else's code instead. A guard in this
repository's pre-commit suite now fails on the short form anywhere in the tree, because this is
a mistake that reads correctly and is only caught by executing it.

Renaming the distribution to match the command would remove the flag and is not available:
`akit` on PyPI is taken by a real project rather than an abandoned squat. Adding a second
console script named after the distribution would also remove it, at the cost of two names to
document and keep in step, and `akit` is still what somebody types once it is installed. So
the flag stays, and `uv tool install federated-agent-kits` is what the daily user does instead.

## 10. Commands

```text
akit list                    # what you subscribed to, and where it is
akit add <source> <name>     # register a subscription, then render it; --global for yours
akit remove <name>           # drop a subscription, and the files it rendered
akit harness add <name>      # render for a harness by name, and commit what it reads
akit harness remove <name>   # stop, and withdraw what it rendered
akit render                  # make the harness files match the manifests, both scopes
akit update [name]           # fetch, move the pins, show what moved
akit doctor                  # what is wrong, and which command fixes it
```

**Two commands fetch, for different reasons.** `add` fetches a source this machine does not
have yet, and skips that when the cache already holds it at the ref asked for. `update`
fetches new commits for a source it does have. Nothing else fetches anything: `list`,
`render` and `doctor` work from the three kinds of file below, so a render on a train
produces exactly what it produced yesterday.

**One check resolves a remote without fetching**, which is the leak check asking whether this
repository is public. It runs only where something is committed, which means only in a
repository whose manifest names a harness with no machine
([§8](#8-keeping-the-employers-kits-in)). Ordinary repositories work offline forever.

Offline, `add` therefore works for a source you already have and fails cleanly for one you do
not, saying which it was.

Three kinds of file are involved throughout, all described in [§6](#6-the-manifest). The
**manifests** say what you want, each subscription naming the commit it is pinned to. The
**cache** holds a clone of each remote source. The **render record**, in the state directory,
says what this machine wrote where, with a hash per copy.

### `list`

**Shows what is subscribed and what state it is in.** Reads the manifests, the render record
and the disk; writes nothing and fetches nothing.

Per subscription it prints the source, the commit it is pinned to, the parts found there,
and where each part was rendered. A subscription that was never rendered says so, and so
does one whose source is missing from the cache.

Failures are reported per line rather than stopping the command, because this is what you run
when something is already wrong.

### `add`

**Registers a new subscription in a manifest, and installs it.** The only command that writes
a subscription, so the manifest's format is something you never have to hold in your head.

A call does four things, in order:

1. **Resolves the source.** A remote the cache does not hold is cloned now, which is the one
   place `add` needs a network, and a tag or branch you named is resolved to a commit. A path
   is simply read where it is, with no clone and no commit.
2. **Checks the kit is really there**, by the walk in [§5](#5-sources). A typo fails here,
   with a list of what the source does hold, rather than becoming a skill that silently never
   loads.
3. **Writes one line** into the repository's manifest, or into yours with `--global`
   ([§6](#6-the-manifest)). The line carries the commit; the comment after it carries the tag
   or branch you asked for.
4. **Renders**, so the kit is usable when the command returns.

It fails before step 3 if the subscription would break a rule: a name already taken by
another kit, or a private source being written into a committed manifest
([§8](#8-keeping-the-employers-kits-in)).

**`add` only ever adds a subscription.** Naming a harness is a different operation, with
different arguments and a different effect on the repository, so it has its own verb rather
than a flag on this one.

### `harness add` and `harness remove`

**Edit the manifest's `harnesses:` list, the way `add` and `remove` edit subscriptions.**
The same `--global` and `--project` flags decide which manifest, and the project one is the
default for the same reason ([§6](#6-the-manifest)).

`harness add` writes the name, leaves `detected` where it is, and renders. The harness is
then rendered for unconditionally, whether or not this machine has it, which is what makes
`akit harness add opencode` meaningful in a repository that already detects opencode: it
says every colleague gets those files, installed or not.

It exists because turning on a harness with no machine starts committing files, and a command
that says what that will do beats a key somebody guesses the spelling of. Its refusal is
[§8](#8-keeping-the-employers-kits-in)'s: a private source already subscribed in this
repository means the harness cannot be added until that subscription goes.

`harness remove` drops the name and withdraws what it rendered, by the rules below. Without
it the only way to turn the cloud agent off would be a hand edit that left a directory of
committed rules in the repository with nothing to explain them, still being read by the
harness you meant to stop using.

**`detected` is a name like any other here.** `akit harness remove detected` is how a
repository pins ([§6](#6-the-manifest)), and on a machine holding a harness the list does not
name, it withdraws that harness's files as any other removal would.

### `remove`

**Drops a subscription and deletes what it rendered.** The other half of `add`, and the same
flags decide which manifest is edited.

Deletion follows the same rule as a render's withdrawal, for the same reason: the render
record is the candidate list, a copy goes, and a rendered file somebody has since edited is
named rather than destroyed. `remove` is the more deliberate command of the two, but being
deliberate about dropping a subscription is not the same as being deliberate about throwing
away the one file in that directory with something of yours in it.

Naming a kit is enough. Where two manifests subscribe to one name, it refuses and asks which,
because guessing would silently change what a repository gives everybody else.

**Writing a kit is what this is for, more than tidying up.** A new kit starts subscribed from
a path on your disk, and ends up subscribed from a published repository. That swap is
`remove` then `add`, and keeping it two commands means the moment when neither is in place
cannot be mistaken for a working setup.

### `render`

**Makes the files on disk match the manifests. The only command that writes kit files.**

A call walks every subscription, and for each one copies its parts into every harness in
scope, translating where the harness needs it and writing once where several harnesses want
identical bytes ([§7](#7-rendering)). It then withdraws what nothing in scope explains any
more, rewrites the ignore block in the repository's `.gitignore`
([§6](#6-the-manifest)), and rewrites the render record.

**Withdrawal deletes copies, and only copies.** A kit you unsubscribed from, or renamed with
`as:`, leaves files behind, and leaving them there is not the safe option: a withdrawn rule
is text that keeps going into every prompt on every turn, and a kit that may no longer be
rendered into a public repository would keep sitting in one
([§8](#8-keeping-the-employers-kits-in)). Both failures are silent, which is why this is not
something to postpone until somebody runs `doctor`.

What makes it safe is that the render record is the whole candidate list
([§6](#6-the-manifest)), so there are three outcomes and not two:

| The file | What render does |
| --- | --- |
| In the record, hash matches, no subscription and harness in scope explains it | deletes it, and says so |
| In the record, hash differs | leaves it, names it, and points at `doctor` |
| Not in the record | nothing, ever |

The first row says "no subscription and harness" because a shared file has several of each
([§6](#6-the-manifest)). One copy of a skill serves opencode and pi, so it survives
unsubscribing from it for opencode alone, and goes when the last thing wanting it does.

The middle row is the one worth arguing about. A rendered file whose hash has drifted is the
only file in a rendered directory that contains something somebody wrote, and a render is a
routine command that may run from a git hook. Routine commands do not destroy the one
irreplaceable thing in the directory, even when it is there by mistake.

The third row is what protects anything hand-made. We never ask whether a file looks like one
of ours, because a skill you wrote by hand and a skill we copied look identical. We ask
whether we wrote it, and the record answers.

`--prune` is the opt-in that handles what withdrawal cannot: files rendered before the record
was lost, which are now unknown rather than unexplained. It deletes what `doctor` reports as
a plausible orphan, and it exists as a flag rather than a default because it is the one
deletion this tool cannot prove is safe.

**Which harnesses are in scope is one list, expanded then narrowed.**

The manifest's `harnesses:` key is that list, and defaults to `[detected]`
([§6](#6-the-manifest)). Expanding it replaces `detected` with every harness this machine
has, by question 7 of [§4](#4-adding-a-harness). That expansion is why there is nothing to
configure after install: you installed opencode, so opencode gets files. Every name beside it
is rendered for whether or not this machine has it, and a harness with no machine can only
arrive that way.

So a repository that names the cloud agent still renders for whatever each colleague has, as
long as `detected` is still in the list, and the only thing a name adds is that harness.

`--no-harness <name>` then drops one from the expanded list, repeatable, and it cannot add
one back. It is for the render you want now rather than the setup you keep, so it writes
nothing into a manifest: a harness you never want is `akit harness remove`, not a flag you
remember to type. `--harness <name>` is the opposite narrowing, and it is how you see what
one harness gets without reading the whole render.

**Narrowing means less than it sounds for a shared file.** Skills land in one directory that
several harnesses read ([§7](#7-rendering)), so `--no-harness opencode` does not stop that
directory being written while pi is still in scope. What it skips is everything written for
opencode alone.

Dropping a harness this way deletes nothing it rendered earlier. Those files become orphans
that `akit doctor` reports, because a flag meant to skip work should not quietly remove
files, and `--no-harness` on a bad day would otherwise be a delete command. Withdrawing them
on purpose is `akit harness remove`.

**A subscription renders into its own scope and no other.** Yours go to the machine-level
harness directories, the same ones whatever directory you are standing in. A repository's go
inside that repository. So running this in a repository writes in two places, and the
repository receives only what its own `.akit.yaml` asked for. Nothing personal of yours ends
up in somebody's project.

It does both by default because a kit you are writing is usually a global one, and you are
usually inside some repository while writing it. A render that skipped your own subscriptions
whenever you were in a project would mean editing a rule and not seeing it until you changed
directory. `--global` and `--project` narrow it when you want only one half, and the output
is grouped by scope so what went where is never a guess.

It uses the commits already in the cache. Nothing is fetched, so a render never changes what
a kit contains; only `update` does that.

**Running it twice changes nothing**, which is what makes it safe from a git hook, a shell
startup, or the end of another command. The half you did not come for is a no-op whenever
nothing changed.

`--check` performs the same walk and writes nothing, exiting non-zero if anything would have
changed. That is for the renders a repository commits ([§6](#6-the-manifest)), which are the
only ones that can go stale while looking fine.

**`--check` only ever judges committed renders, which is what keeps detection out of it.** A
CI runner has none of the harnesses on your laptop installed, so a check that considered
detected ones would call every repository stale forever. It does not have to: everything that
can go stale belongs to a harness named outright in the manifest rather than detected, and
that part of the list reads the same on every machine.

**So `--check` refuses the narrowing flags.** `--no-harness copilot-ci` excludes the only
harness committing anything, leaving a check with nothing to look at, which then passes. That
would happen inside a pre-commit hook, which is the one place a false pass costs something.

### `update`

**Fetches new commits for sources already here, moves the pins, and shows what moved.** The
only command that changes what a kit contains.

For each source, or just the named one, it fetches, works out the newest commit of whatever
the comment says the pin follows, and looks for every part subscribed under that key at the
new commit, by the same walk `add` used ([§5](#5-sources)). If they are all there it
rewrites the key and the comment, prints the diff of every part you subscribe to, then
renders.

**Finding them again is a step, not an assumption.** A subscription names a kit rather than a
path, so an upstream tidy-up that moves `skills/writing/` to `skills/prose/writing/` resolves
without anything happening, and `update` says the path moved because it is cheap to notice
and surprising to discover later. A kit that is *gone* is the case that matters, and upstream
deleting or renaming one is ordinary.

**A pin moves for every name under its key or for none of them.** The commit is a property of
the key, not of each name beneath it ([§6](#6-the-manifest)), so there is no such thing as
moving four of five names forward. A missing part therefore stops that key's update, leaving
the pin where it is, and leaves every other key free to move.

Nothing is rendered for a source whose pin did not move, so the failure costs nothing: you
keep exactly the kits you had this morning. That is also why this does not have to be solved
in a hurry.

**Resolving it is yours, and `update` says so rather than guessing.** It has no way to tell a
deletion from a rename, and the two want opposite things. Three ways out, and the message
names all three: `akit remove` the part that is gone, `akit add` the name it was renamed to,
or split it into a second subscription that keeps its own older commit, which the manifest
already allows since two blocks naming one repository at two commits are two subscriptions.

Writing that choice into the manifest is `add` and `remove`'s job, which keeps the rule from
[§6](#6-the-manifest) intact: `update` edits a pin, never a name. A command that dropped a
name on your behalf would delete a rule from every prompt your agents see, and one that added
a name would subscribe you to a kit you have never read. Neither is a thing to infer from a
rename somebody else made.

**A `"*"` subscription cannot hit this**, because whatever is there is what it asked for. The
cost moves into the diff instead: parts that disappeared upstream are listed beside parts
that changed, since a kit you were using vanishing is the one thing a wildcard can do to you
quietly.

**At a pinned commit this can never be wrong**, which is worth saying because it is what
makes the rest safe. `add` checked the part was there, and a commit is immutable, so the only
way a pinned part goes missing is the history being rewritten underneath it, and that is
already `akit doctor`'s "pinned to a commit the cache does not hold".

Rewriting a key means rewriting YAML somebody hand-wrote, so the writer preserves comments and
layout. Elsewhere this tool only ever replaces a block of its own inside a file a person owns,
the `.gitignore` markers and the third rule shape ([§6](#6-the-manifest),
[§7](#7-rendering)); here it edits their content in place, which is the reason the pin lives
in a comment rather than in a second file.

The diff is the point rather than a courtesy. A rule you have never read is text added to
every prompt your agents see, so an update to one is a change to how they behave.

### `doctor`

**Lists what is wrong and names the command that fixes each one.** Reads everything and
changes nothing.

It goes near a network in the one case `render` does, and for the same reason: a repository
whose manifest names a harness with no machine has a leak check to run, and that check asks
whether the repository is public ([§8](#8-keeping-the-employers-kits-in)). Everywhere else it
works from the manifests, the cache and the render record.

What it looks for:

- two kits rendering to one name;
- a rendered file that no subscription and harness in scope explains, where the next `render`
  will withdraw it;
- a rendered file edited by hand, caught by its hash in the render record, which is also the
  file `render` and `remove` refuse to delete until you say what you meant by it;
- a file that looks like a render nothing knows about, which is what a lost render record
  leaves behind, and what `render --prune` is for;
- a source that is missing from the cache, or pinned to a commit the cache does not hold;
- a committed manifest naming a path that leaves the repository, which is somebody's laptop
  written into a shared file;
- a committed render that is out of date, which is `render --check` by another name;
- an agent naming a skill or an MCP server you have not subscribed to
  ([§1](#1-what-this-is));
- files in place for a harness that is not reading them yet
  ([§4](#4-adding-a-harness));
- a harness detected on this machine that the manifest's `harnesses:` list leaves out, which
  is the one failure that looks exactly like success ([§6](#6-the-manifest));
- a harness named in the manifest that no adapter knows, which is a typo in a list nothing
  else validates;
- a rendered directory missing from the `.gitignore` block, or sitting in it while also being
  committed.

Changing nothing is what makes it the safe thing to run when you do not know what is going
on.

## 11. The skill

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

The CLI needs no such step, since it is a published package
([§9](#9-windows-linux-python)). So the two halves bootstrap independently: the skill is a
subscription like any other, and the tool it talks about is one `uvx` away whether or not the
skill was ever installed.

A skill that has been copied somewhere cannot tell how old it is, so it carries a `VERSION`
file. That is the only thing that survives being copied into a skills directory.

## 12. Still open

None of these blocks the first piece of work.

**Do rules need an `applyTo` glob?** VS Code has one, deciding when a rule applies. opencode
and pi have nothing like it, so such a rule would simply be always-on there. A field that one
harness out of four honours may be worse than no field. Write ten real rules and see whether
any of them wants it.

**How do tool names map between harnesses?** A table maintained by hand that fails on
anything unknown. Whether that table is per harness or per agent is open. Not worth deciding
until three agents genuinely want to live in two places.

## 13. Not doing

**rulesync** renders to many harnesses from one directory, which is the rendering half of
this. It is scoped to a single project, with no sources, no tiers and no subscriptions, so it
would sit underneath the manifest rather than replace it. It is also node, which
[§9](#9-windows-linux-python) rules out for anything a user has to run.

**Sharing a manifest with `fkb`** would mean a colleague cloning a repository can read the
path to your private knowledge bundle. Different question, different file.

**A privacy field in each part** can disagree with the repository it is sitting in. The
repository already answers it. One place or none.

**A committed lockfile**, holding the commit each subscription resolved to. That is what the
manifest's own keys carry instead, so the second file would restate the first and be able to
disagree with it. The cost is a YAML writer that preserves comments, which `.pre-commit-config`
has needed for years and which is a solved problem.

**A command that redirects a source to a local checkout.** It existed to let you work on a
source that a committed manifest names, without editing the key everybody shares. Editing the
key and not committing that line does the same job, and git already reports it, reverts it and
can refuse the commit. One fewer command, one fewer state file, and no override that is
invisible six weeks later.

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

## 14. The name

The system covers three kinds of kit, so a name mentioning only rules would be wrong within
a month. `federated-agents` reads as agents federating with each other, which is a different
and much noisier topic.

The command is `akit` rather than `kit` because KitOps already installs a `kit` binary to
`/usr/local/bin` through Homebrew. It serves the same AI audience and uses the verbs we want:
`kit init`, `kit list`, `kit diff`. The damage would not be a failed install. It would be
somebody running the wrong tool out of our own documentation.
