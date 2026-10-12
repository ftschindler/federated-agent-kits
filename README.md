# federated-agent-kits

Subscribe to agent kits from wherever they live, and render them where each harness looks.

The instructions you give an agent accumulate in different places. Some you would publish,
some belong to your employer, some never leave your laptop. Meanwhile every harness wants them
in its own directory, under its own filename, in its own shape.

So one instruction becomes several copies in several files, and the copies drift.

`akit` keeps one line in a manifest instead. It fetches the kit from the git repository it
lives in, pins the commit, and writes the files each harness reads.

```sh
uvx --from federated-agent-kits akit list
```

That writes nothing, fetches nothing, and needs no install beyond
[uv](https://docs.astral.sh/uv/). It says which harnesses are on this machine, what you
subscribe to, and where each part landed.

**Alpha.** Everything below works today, on Linux and Windows, both running the full suite in
CI. Agent definitions are the one kind still being built, so a subscription to one says which
task it is waiting for. Expect the shape to hold and the edges to move.

## Adding kits

This repository is a source like any other, and the kit it holds is called `akit`: a skill
that teaches an agent to drive these commands, and the rule that makes a model reach for it.
Subscribing to it is the ordinary shape of every `akit add`:

```sh
uvx --from federated-agent-kits akit add --global ftschindler/federated-agent-kits akit
```

That resolves the source, checks the kit is really there, writes one line into your own
manifest, and renders. `akit list` then says where both parts landed, and one line undoes all
of it:

```sh
uvx --from federated-agent-kits akit remove --global akit
```

which deletes the copies it wrote and leaves anything you wrote yourself alone.

Every other subscription has the same two arguments, a source and a kit:

```sh
uvx --from federated-agent-kits akit add <source> <kit>
```

**A source is any git repository with a `skills/`, `rules/` or `agents/` directory.** It needs
no manifest, no registration and no permission, and it never learns that you subscribed. A
typo fails before the manifest is touched, listing what the source does hold, so a failure
here is a spelling to correct rather than a mess to clean up. `akit help sources` lists every
form the argument can take, including a path to a repository you are writing yourself.

**That includes anything you would install with `npx skills add`.** The skills.sh marketplace
is a git repository like any other, so a line translates directly, with `*` for every kit the
source holds:

```sh
npx skills add owner/repo
uvx --from federated-agent-kits akit add owner/repo '*'
```

Three things change in the translation: `akit` takes rules as well as skills, the subscription
is written down in a file you own rather than only on disk, and `akit update` brings changes
as a diff you read rather than as something that changed under you.

**The `--from` is not decoration.** The distribution is `federated-agent-kits` and the command
inside it is `akit`. `uvx` reads its first argument as a distribution, so naming only the
command asks PyPI for a project called `akit`, which belongs to somebody else. If you run this
daily and would rather type four words fewer, `uv tool install federated-agent-kits` puts
`akit` on your `PATH` for good.

`uv` is the one thing that has to be on the machine already, and `akit` will not install it
for you. Subscribing to a kit and putting a tool on somebody's machine are different acts.

## What it is for

**Use your own practice everywhere.** Write a style guide or a debugging workflow once.
Subscribe to it on every machine, in every harness.

**Share with a team without sharing everything.** Which tier a kit belongs to is decided by
which repository it sits in. There is no field to get wrong, and a kit that may not be
published cannot be rendered into a public repository.

**Take other people's kits without copying them by hand.** A subscription names a source and
an item, and an update arrives as a diff you read.

**Stop writing the same instructions into four files.** One rule, written once, reaches every
harness you use, in whichever shape each of them wants it.

Use something else if you want a registry, a marketplace or a runtime. This writes files and
gets out of the way.

## What a kit is

**A kit is a name, and the parts that name brings in.** A part is a skill your agent can open,
a rule that goes into every prompt, or an agent definition with its own model and tools.

**Most kits are one part.** A single skill is a kit. A single rule is a kit. Nothing has to be
bundled with anything, and a source that ships twenty unrelated skills is twenty kits you can
subscribe to one at a time.

Where a source does ship a skill and a rule under the same name, both arrive, because a skill
with the rule that makes a model reach for it is the thing you wanted. `--kind skill` narrows
that to one, and `akit remove <name>` drops whatever the name brought in.

**Two sources shipping a kit under one name is what `--as` is for.** Subscribing with `--as
upstream-kb` installs it under that name, and the name goes into the copied `SKILL.md` as well
as onto its directory, because that header rather than the directory is what most harnesses
treat as the skill's identity.

## The two scopes

Subscriptions live in two files with one format, and both can be in use on a machine at once.

| Scope | Flag | Where it lives | True for |
| --- | --- | --- | --- |
| Yours | `--global` | your platform's config directory | you, in every repository you open on this machine |
| This repository's | `--project`, the default | `.akit.yaml` beside the `.git` | everybody who clones it |

Neither overrules the other, because each renders into its own scope and the two never write
to the same place. A name used in both is two copies in two directories, which `akit list` and
`akit doctor` report rather than picking a winner between.

A committed `.akit.yaml` is what turns a fresh clone into a working setup in one line, in a
contributing guide or in a pre-commit hook:

```sh
uvx --from federated-agent-kits akit render
```

**That line needs nothing installed and no warm cache.** `akit render` reads a source this
machine already holds and clones one it has never seen, at the commit the manifest names. It
moves no pin and writes no manifest, so a colleague gets what the repository committed rather
than whatever `main` holds this afternoon. Once a source is cached it needs no network at all.

## The commands

```text
akit add <source> <name>   subscribe to one kit, and render it
akit remove <name>         drop one subscription, and delete what it rendered
akit update                fetch, move the pins, and show the diff
akit harness add <name>    start rendering for a harness by name
akit list                  what you subscribed to, and where it landed
akit render                make the files on disk match the manifests
akit render --check        write nothing, fail if what you commit is stale
akit doctor                what is wrong, and which command fixes it
```

**You never type a commit hash.** `akit add owner/repo#v2 writing` resolves the tag or branch
you named, writes the commit it resolved to, and leaves the name you asked for in a comment
beside it. `akit update` moves both and prints the diff of every part you subscribe to, so a
change to a rule your agents read arrives as something you saw rather than as something that
happened. A part that disappeared upstream stops that key and names the ways out, rather than
guessing between a deletion and a rename.

**`akit doctor` is what you run when something is already wrong.** It reads the manifests, the
render records and the files on disk, changes nothing, and names a command for every finding:
two kits rendering to one name, a copy you edited by hand, a render nothing subscribes to any
more, a source missing from the cache, a harness installed here that your manifest leaves out,
a `.gitignore` block that has drifted. It exits non-zero when it found something, and `--json`
carries the findings as data.

**Every command explains itself.** `akit <command> --help` says what the command writes and
what it never writes, with a worked example. `akit help manifest`, `akit help sources`, `akit
help harnesses` and `akit help privacy` cover the four things that are not commands. `--json`
works on all of them, which is usually what you want when a model is reading.

## The harnesses

opencode, GitHub Copilot in VS Code and GitHub Copilot in CI ship today. The first two are
detected by evidence on this disk, never by what a repository contains.

**One rule reaches three differently shaped harnesses.** Copilot reads a directory, so it gets
one file per rule, with the `applyTo` frontmatter without which it would never read them.
opencode reads one `AGENTS.md` that you write in too, so each rule goes between markers inside
it, and everything you wrote around them survives every render. Unsubscribing takes the block
out and leaves the file.

The two shapes differ in one way worth knowing about. A harness that reads one file reads the
rules in the order your manifest lists them, and a harness that reads a directory promises no
order at all, so two rules that contradict are a coin toss there. `akit list` says which of
the two each harness is, so nobody has to find out from behaviour.

**A new harness is one file.** An adapter answers seven questions about where that harness
keeps things and how to tell it is installed, and nothing else in the system changes. A test
enforces that rather than this paragraph asserting it: nothing outside an adapter may import
one or branch on a harness name.

## The harness that commits

GitHub Copilot in CI runs on GitHub's infrastructure. It clones your repository and reads what
is there, which means **nothing you do not commit exists as far as it is concerned**. So it
cannot be detected, and arrives only by being named:

```sh
uvx --from federated-agent-kits akit harness add copilot-ci
```

That one line changes what gets committed. The directories it reads leave the `.gitignore`
block, so the skills every other harness was reading privately go into the repository's
history. That is the intended behaviour: a directory with two readers is committed if either
of them commits, because git cannot ignore a directory halfway.

Two things follow, and both ship with it.

**A private kit cannot reach a public repository.** A source that needed credentials to clone
is private, and a repository whose remote resolves anonymously is public. A private source's
parts rendering into a public repository fails hard, naming the source and the target, with no
override and no `--force`. Private into private is the ordinary employer setup and renders
without a question being asked. Your repository is classified only when a private source is
about to be committed into it, so an ordinary render still needs no network.

**Anything committed can go stale.** `akit render --check` writes nothing and exits non-zero
when what the repository commits no longer matches its manifest. It is one hook away:

```yaml
- repo: https://github.com/ftschindler/federated-agent-kits
  rev: v0.12.0
  hooks:
  - id: akit-render-check
```

One hook rather than three, because the walk that finds a stale render is the walk that finds
a leak and the one that finds a committed manifest naming a path off somebody's laptop.

## What it promises

**The file you edit is the only copy.** Everything rendered is generated and disposable,
except what a harness with no machine reads, which has to be committed to exist at all. A
rendered copy is deleted only while its bytes are still the ones `akit` wrote, so a file you
edited by hand survives and gets named rather than overwritten.

**Windows and Linux are equally supported.** Both run the full suite in CI, and neither is the
afterthought.

**Python only.** No dependency lockfile of ours to go stale, and no install step for anyone
who only wants to work on a repository.

## Alpha testing

Please report what breaks, what reads badly, and what you expected a command to do that it did
not, at
[the issue tracker](https://github.com/ftschindler/federated-agent-kits/issues).
`akit doctor --json` and `akit list --json` are the two most useful things to paste.

## More

| | |
| --- | --- |
| [DESIGN.md](https://github.com/ftschindler/federated-agent-kits/blob/main/DESIGN.md) | what gets built, and why each decision went the way it did |
| [IMPLEMENTATION.md](https://github.com/ftschindler/federated-agent-kits/blob/main/IMPLEMENTATION.md) | the order it gets built in, and what is left |
| [docs/adding-an-adapter.md](https://github.com/ftschindler/federated-agent-kits/blob/main/docs/adding-an-adapter.md) | the seven questions a new harness answers, with a worked example |
| [CONTRIBUTING.md](https://github.com/ftschindler/federated-agent-kits/blob/main/CONTRIBUTING.md) | the test layers, the conventions, and how a release is cut |

## License

[MIT](https://github.com/ftschindler/federated-agent-kits/blob/main/LICENSE).
