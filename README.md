# federated-agent-kits

A **kit** is a composition of three kinds of thing: **skills** your agent can open, **rules**
that go into every prompt, and **agent definitions** with their own model and tools. A kit may
be one skill, or a skill with the rule that makes a model reach for it, or an agent with
everything it leans on. What makes them one kit is that you want them together.

Kits accumulate in different places. Some you would publish, some belong to your employer,
some never leave your laptop. Meanwhile each harness wants them in its own directory, under
its own filename.

This subscribes you to the kits you want, from wherever they live, and writes them where each
harness looks.

**Status: it subscribes, it renders skills and rules into three harnesses, it refuses to
leak, it tells you what is wrong, and it ships the skill that drives it.** [DESIGN.md](DESIGN.md) is the source of truth for what
gets built, [IMPLEMENTATION.md](IMPLEMENTATION.md) for the order it gets built in. Every verb
works today: `akit add`, `akit remove`, `akit update`, `akit harness`, `akit list`,
`akit render` and `akit doctor`,
against both manifests, every source form and the opencode, GitHub Copilot in VS Code and
GitHub Copilot in CI adapters. A render copies the skills you
subscribed to into the directory every harness reads, writes each rule you subscribed to in
whichever shape its harness wants, maintains the `.gitignore` block, and deletes a rendered
copy only while its bytes are still the ones it wrote. Agents are the one kind still waiting,
in T13, so a subscription to one says which task it is waiting for.

**`akit doctor` is what you run when something is already wrong.** It reads the manifests,
the records and the files on disk, changes nothing, and names a command for every finding: two
kits rendering to one name, a copy you edited by hand, a render nothing subscribes to any
more, a source missing from the cache, a harness installed here that your manifest leaves
out, a `.gitignore` block that has drifted. It exits non-zero when it found something, and
`--json` carries the findings as data.

**One rule reaches three differently shaped harnesses.** Copilot reads a directory, so it gets
one file per rule, with the `applyTo` frontmatter without which it would never read them.
opencode reads one `AGENTS.md` that you write in too, so each rule goes between markers
inside it and everything you wrote around them survives every render. Unsubscribing takes the
block out and leaves the file. `akit list` says which harnesses read rules in the order your
manifest lists them and which promise no order at all.

## The harness that commits

GitHub Copilot in CI runs on GitHub's infrastructure. It clones your repository and reads
what is there, which means **nothing you do not commit exists as far as it is concerned**. So
it cannot be detected and arrives only by being named:

```sh
akit harness add copilot-ci
```

That one line changes what gets committed. The directories it reads leave the `.gitignore`
block, computed rather than maintained, so the skills every other harness was reading
privately go into the repository's history. That is the intended behaviour: a directory with
two readers is committed if either of them commits, because git cannot ignore a directory
halfway.

Two things follow, and both ship with it.

**A private kit cannot reach a public repository.** A source that needed credentials to clone
is private, and a repository whose remote resolves anonymously is public. A private source's
parts rendering into a public repository fails hard, naming the source and the target, with
no override and no `--force`. Private into private is the ordinary employer setup and renders
without a question being asked. Your repository is classified only when a private source is
about to be committed into it, so an ordinary render still needs no network.

**Anything committed can go stale.** `akit render --check` writes nothing and exits non-zero
when what the repository commits no longer matches its manifest. It is one hook away:

```yaml
- repo: https://github.com/ftschindler/federated-agent-kits
  rev: v0.7.0
  hooks:
  - id: akit-render-check
```

One hook rather than three, because the walk that finds a stale render is the walk that finds
a leak and the one that finds a committed manifest naming a path off somebody's laptop.

## What it is for

**Use your own practice everywhere.** Write a style guide or a debugging workflow once.
Subscribe to it on every machine, in every harness.

**Share with a team without sharing everything.** Which tier a kit belongs to is decided by
which repository it sits in. There is no field to get wrong, and a kit that may not be
published cannot be rendered into a public repository.

**Take other people's kits without copying them by hand.** A subscription names a source and
an item. An update arrives as a diff you read, not as something that changed under you.

**Stop writing the same instructions into four files.** One rule, written once, reaches every
harness you use, in whichever shape each of them wants it.

Use something else if you want a registry, a marketplace, or a runtime. This writes files and
gets out of the way.

## How it works

```text
akit add owner/repo writing      # this repository's manifest; --global for yours
akit list            # what you subscribed to, where it is, and where it would land
akit update          # fetch, move the pins, and show what moved
akit render          # safe to run from a git hook
akit render --check  # write nothing, fail if what you commit is out of date
akit doctor          # name collisions, stale renders, refusals
```

**You never type a commit hash.** `akit add owner/repo#v2 writing` resolves the tag or branch
you named, writes the commit it resolved to, and leaves the name you asked for in the comment
beside it. `akit update` moves both and prints the diff of every part you subscribe to, so a
change to a rule your agents read arrives as something you saw rather than something that
happened. A part that disappeared upstream stops that key and names the three ways out
instead of guessing between a deletion and a rename.

**A name is a kit, not a file.** `akit add owner/repo writing` takes the skill called
`writing` and the rule called `writing` if the source has both, because a skill with the rule
that makes a model reach for it is the thing you wanted. `--kind skill` narrows it, and
`akit remove writing` drops whatever that name brought in.

**Two sources shipping a kit with the same name is what `as:` is for.** Subscribing with
`as: upstream-kb` installs it under that name, and the name goes into the copied `SKILL.md`
as well as onto its directory, because that header rather than the directory is what most
harnesses treat as the skill's identity. Renaming one and not the other produces a skill
Copilot declines to load and a collision opencode still has.

A rename leaves one loose end, and it gets written down rather than papered over. A rule from
the same source still names the kit the way its author wrote it, and that reference is prose.
One line of a real rule carries both readings:

> **Load the `writing` skill** when writing anything longer than a reply

The first is a reference and the second is a verb, so nothing may rewrite it. Instead, where
a rule does name a renamed kit, a short `akit-renames` rule is rendered beside it saying which
name the kit is installed under. No rename, or no rule mentioning one, and nothing is written
at all.

Every command explains itself, because the agent-facing skill is deliberately thin: it says
run `akit list` and never describes the output. So `akit <command> --help` is the
documentation, and `akit help manifest`, `akit help sources`, `akit help harnesses` and
`akit help privacy` cover the four things that are not commands.

## The skill it ships

An agent asked to "set up my kits" has nowhere to look, so this repository is a source like
any other and the kit it holds is called `akit`: the skill under `skills/akit/`, and the
five-line rule beside it in `rules/` that tells a model when to open it.

```sh
uvx --from federated-agent-kits akit add --global ftschindler/federated-agent-kits akit
```

The skill covers three situations and no more: nothing is set up, something needs doing, a
new release is out. It names commands and never describes their output, so there is one
description of what `akit list` prints rather than two that can disagree. A copy carries a
`VERSION` file, written by the release job from the same number as the package, because a
skill copied into a skills directory cannot tell how old it is any other way.

The first copy is placed by hand, or by whatever skill installer you already use, and the
command above turns it into a managed one. A test drives a real agent through all three
situations on both operating systems, which is how an instruction that only parses in one
shell gets caught.

```sh
uvx --from federated-agent-kits akit --help
```

**The `--from` is not decoration.** The distribution is `federated-agent-kits` and the command
it installs is `akit`, and `uvx` reads its first argument as a distribution rather than as a
command. Naming only the command therefore asks the index for a project called `akit`, which
belongs to somebody else. `--from` names the distribution and `akit` names the command inside
it. If you run this daily and would rather type four words fewer, `uv tool install
federated-agent-kits` puts `akit` on your `PATH` for good.

A source is an ordinary git repository with `skills/`, `rules/` or `agents/` in it. It needs
no manifest and no registration, and it never learns that you subscribed.

Your subscriptions live in two files with one format. A personal one says what is true of
you. A committed one in a repository says what that repository expects, so a colleague clones
it and runs one command:

```text
uvx --from federated-agent-kits akit render
```

**Nothing to install first.** `federated-agent-kits` ships on PyPI, so the step between a
fresh clone and a working set of kits is that one line, in a contributing guide or in a
pre-commit hook.

## What it promises

**Windows and Linux are equal.** Both are tested in CI, and neither is the afterthought.

**Python only**, shipped as a package you run with `uvx`. No dependency lockfile of ours to
go stale, and no install step for anyone who just wants to work on a repository.

**A new harness is one file.** opencode, GitHub Copilot in VS Code and GitHub Copilot in CI
ship today. An adapter answers seven questions about where that harness keeps things and how
to tell it is installed, and nothing else in the system changes. A test enforces that rather
than this paragraph asserting it: nothing outside an adapter may import one or branch on a
harness name. [docs/adding-an-adapter.md](docs/adding-an-adapter.md) says how to answer the
seven questions, with pi as the worked example, and
[DESIGN.md](DESIGN.md#4-adding-a-harness) says why those are the seven.

**The file you edit is the only copy.** Everything rendered is generated and disposable,
except what a harness with no machine reads, which has to be committed to exist at all.

## License

[MIT](LICENSE).
