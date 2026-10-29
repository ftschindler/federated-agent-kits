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

**A source is any git repository that keeps skills, rules or agent definitions in it.** It
needs no manifest, no registration and no permission, and it never learns that you subscribed.
`akit` looks in all the standard places each kind is kept, several levels down, plus wherever
an installed harness keeps its own, so a repository laid out the way its ecosystem lays them
out needs nothing doing to it. `akit help sources` is the full account, and it also lists
every form the source argument takes, including a path to a repository you are writing
yourself.

**Both arguments are required, and a wrong one costs nothing.** A kit that is not in the
source fails before the manifest is touched, listing what the source does hold, so a typo is a
spelling to correct rather than a mess to clean up. `*` in place of a name subscribes to every
kit the source holds.

**To see that listing before choosing a name, ask for it.** `akit discover <source>` names
every kit a source holds, by kind, and writes no manifest:

```sh
uvx --from federated-agent-kits akit discover ftschindler/federated-agent-kits
```

It is the one read-only command that fetches, and that is deliberate: it clones the source
into the same cache everything else reads, so the `akit add` you run next needs no network.
`--verbose` adds what each kit says it is for, and `--json` carries the path each one sits at
inside the repository.

**The `--from` is not decoration.** The distribution is `federated-agent-kits` and the command
inside it is `akit`. `uvx` reads its first argument as a distribution, so naming only the
command asks PyPI for a project called `akit`, which belongs to somebody else. If you run this
daily and would rather type four words fewer, `uv tool install federated-agent-kits` puts
`akit` on your `PATH` for good.

`uv` is the one thing that has to be on the machine already, and `akit` will not install it
for you. Subscribing to a kit and putting a tool on somebody's machine are different acts.

## Coming from `npx skills`

The skills.sh marketplace lists git repositories containing skills, which is what a source
already is. So anything installable with `npx skills add` is installable here, and a line
translates directly:

```sh
npx skills add owner/repo
uvx --from federated-agent-kits akit add owner/repo '*'
```

Three things change in the translation. `akit` takes rules and agent definitions as well as
skills. The subscription is written down in a file you own, so it can be committed, reviewed
and moved to another machine. And `akit update` brings a change as a diff you read, rather
than as something that changed under you.

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
| Global | `--global` | your platform's config directory | you, in every project you open on this machine |
| Project | `--project`, the default | `.akit.yaml` beside the `.git` | everybody who clones that repository |

Those two words are what every flag, heading and sentence calls them. **Global** means for
you on this machine; **project** means for the repository the command is run in.

Neither overrules the other, because each renders into its own scope and the two never write
to the same place. A name used in both is two copies in two directories, which `akit list` and
`akit doctor` report rather than picking a winner between.

A committed `.akit.yaml` is what turns a fresh clone into a working setup in one line, in a
contributing guide or in a pre-commit hook:

```sh
uvx --from federated-agent-kits akit render
```

**That line needs nothing installed beforehand.** `akit render` fetches whatever it does not
already have, at the commit the manifest names. It moves no pin and writes no manifest, so a
colleague gets what the repository committed rather than whatever `main` holds this afternoon.

**A manifest is the only file you edit.** Everything rendered from one is generated and
disposable, and `akit` deletes a rendered copy only while its bytes are still the ones it
wrote, so anything you changed by hand survives and gets named rather than overwritten.

### Validating one

**The manifest format is published as a JSON Schema**, so an editor underlines a mistake as
you make it and a pre-commit hook fails a commit that carries one. A manifest `akit` creates
is written with the line that points an editor at it:

```yaml
# yaml-language-server: $schema=https://raw.githubusercontent.com/ftschindler/federated-agent-kits/v0.21.0/schema/akit-manifest.schema.json
version: 1
```

and a file you started by hand takes the same line. The URL names a tag rather than a branch,
so what it means does not change overnight: a release publishes the schema for the format that
release reads.

Checking a committed `.akit.yaml` without an editor is one more hook:

```yaml
- repo: https://github.com/python-jsonschema/check-jsonschema
  rev: 0.38.2
  hooks:
  - id: check-jsonschema
    files: ^\.akit\.yaml$
    args:
    - --schemafile
    - https://raw.githubusercontent.com/ftschindler/federated-agent-kits/v0.21.0/schema/akit-manifest.schema.json
```

**The schema sees one file and nothing beyond it.** Whether a source exists, whether a kit is
really in it, whether a pin resolves and whether two subscriptions render to one name are
questions about something other than this file, and `akit doctor` is what answers them. `akit`
itself never reads the schema either: it has its own reader, and what that refuses it refuses
with a line and a fix.

## The commands

```text
akit discover <source>     list what a source holds, without subscribing to any of it
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

**It asks the same questions of your home directory.** A `~/.agents` you keep as a git
repository, to share between machines or to back up, is a repository `akit` renders into, so
it is told what it is ignoring and what it is committing. The block there is reported rather
than written, because the file belongs to a repository you never pointed this tool at, and
`akit render --global --gitignore` is what writes it once you want it. The same knowledge
answers a question `doctor` could not answer before: a skill the repository tracks was
written by somebody and has a history, so it is yours sitting where renders go rather than a
render nothing remembers, and the two get different advice.

**Every command explains itself.** `akit <command> --help` says what the command writes and
what it never writes, with a worked example. `akit help manifest`, `akit help sources`, `akit
help harnesses` and `akit help privacy` cover the four things that are not commands. `--json`
works on all of them, which is usually what you want when a model is reading.

## The harnesses

**You subscribe to a kit once, and never say anything about a harness.** The manifest records
what you want, not where it goes, and every harness on the machine gets the kit in the shape
it reads. Install a second harness and the next `akit render` writes everything you already
subscribe to into it as well.

Harnesses come in two kinds, and the difference decides what ends up in your repository.

**One kind runs on your machine**, and `akit` finds it by evidence on this disk. What it
renders is yours alone, so it stays out of the project: the `.gitignore` block covers it,
and nobody you share the repository with sees it.

**The other kind has no machine.** It runs on somebody else's infrastructure and reads what
your repository commits, so there is nothing on this disk to detect and it arrives only by
being named. From then on what it reads is committed, which the next section is about.

Five adapters ship today:

| Harness | Kind | Takes |
| --- | --- | --- |
| opencode | on this machine | skills, rules |
| GitHub Copilot in VS Code | on this machine | skills, rules |
| Cursor, on this machine | on this machine | skills, rules |
| GitHub Copilot in CI | no machine, so named | skills, rules |
| Cursor's cloud agents | no machine, so named | skills, rules |

Copilot and Cursor are each two rows, because each ships an editor you render on and a cloud
agent you cannot, and that difference decides everything else about where their files go.

`akit list` reports which of them it found, for the machine it runs on. Detection is always by
evidence on this disk, never by what a repository contains.

**Where a harness reads a kind from several places, you pick.** Most do not, and a bare name
in the list takes the default. Where there is a choice, the entry says so, and `akit list`
names the alternatives:

```sh
uvx --from federated-agent-kits akit harness add copilot-ci --rules instructions
```

which writes `harnesses: [detected, {copilot-ci: {rules: instructions}}]`. Running it again
with another name moves what that harness rendered, rather than leaving two copies behind.

**Both Copilot harnesses take rules through `AGENTS.md` by default**, which opencode reads as
well, so a repository rendering for all three writes each rule once instead of three times.
`--rules instructions` is what to pick when a rule should apply to some paths and not others,
because the `applyTo` glob that scopes it exists only in `.github/instructions/`.

Rules differ in shape between harnesses, and `akit` absorbs that. Where a harness reads a
directory of rules, each rule is a file of ours, with whatever frontmatter that harness needs
to read it at all. Where it reads one file you also write in, such as opencode's `AGENTS.md`,
`akit` manages the individual blocks inside it and leaves everything you wrote around them
alone, every render. Unsubscribing takes a block out and leaves the file.

**A new harness is one file.** An adapter answers seven questions about where that harness
keeps each kind, which shape it takes rules in, and how to tell it is installed. Nothing else
in the system changes, and a test enforces that rather than this paragraph asserting it:
nothing outside an adapter may import one or branch on a harness name.
[docs/adding-an-adapter.md](https://github.com/ftschindler/federated-agent-kits/blob/main/docs/adding-an-adapter.md)
walks the seven questions with a worked example, and a pull request adding one is welcome.

## The harness that commits

GitHub Copilot in CI and Cursor's cloud agents are the harnesses with no machine. Each runs
on somebody else's infrastructure, clones your repository and reads what is there, which
means **nothing you do not commit exists as far as either is concerned**. Naming one is one
line:

```sh
uvx --from federated-agent-kits akit harness add copilot-ci
```

That one line changes what gets committed. The directories it reads leave the `.gitignore`
block, so the skills every other harness was reading privately go into the repository's
history. That is the intended behaviour: a directory with two readers is committed if either
of them commits, because git cannot ignore a directory halfway.

Its rules go to `AGENTS.md`, which opencode reads as well, so one block serves both rather
than each getting a copy. `--rules instructions` sends them to `.github/instructions/`
instead, one file per rule with an `applyTo` glob, which is what to pick when a rule should
apply to some paths and not others.

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
