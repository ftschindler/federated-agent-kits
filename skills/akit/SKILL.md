---
name: akit
description: >-
  Subscribe to agent kits - skills, rules and agent definitions - from wherever
  they live, and write them where each harness looks. Use when a machine or a
  repository has no kits set up yet, when somebody asks to add, update or remove
  a kit, when a harness is not reading the instructions it should, or when
  rendered files look out of date.
---

# akit

`akit` subscribes you to kits from ordinary git repositories and writes them
where each harness reads them. A kit is a skill, a rule, an agent definition, or
the ones you want together under one name.

Run it with no install:

```sh
uvx --from federated-agent-kits akit list
```

The `--from` is not decoration:

- the distribution is the PyPI package `federated-agent-kits`, built from the
  repository at <https://github.com/ftschindler/federated-agent-kits/>,
- the command inside it is `akit`, and
- `uvx` reads its first argument as a distribution name, so naming only the
  command asks the index for a different project.

`uvx` comes with `uv`, which is the one thing here that has to be on the machine
already. Where `uv --version` fails,
[references/install-requirements.md](references/install-requirements.md) says
what to offer; it is never installed without being asked for.

**Everything below writes `akit <command>` and means
`uvx --from federated-agent-kits akit <command>`.** The short form works only
where somebody has run `uv tool install federated-agent-kits`, which most people
have not. So check once, at the start of a session:

```sh
akit --version
```

Where that fails, put `uvx --from federated-agent-kits` in front of every `akit`
in this skill and its references. Where it answers, compare what it said with
the [VERSION](VERSION) file beside this skill, which is the release these
instructions were written for:

- **The same, or a patch or minor apart.** Use the short form.
- **The installed one is older by a major.** It is a different generation from
  these instructions, and the gap is silent: the command runs and means
  something else. Say so, use the long form for this session, which always
  resolves the published release, and offer
  `uv tool upgrade federated-agent-kits` as the fix.
- **The installed one is newer by a major.** This copy of the skill is the stale
  half. Say so, carry on with the short form, and run `akit update` afterwards,
  which brings the skill and its rule up to the release the tool came from.

**Every command explains itself, so read its help rather than guessing.** `akit
<command> --help` says what the command writes and what it never writes, with a
worked example. `akit help manifest`, `akit help sources`, `akit help harnesses`
and `akit help privacy` cover the four things that are not commands. `--json` on
any command gives you the same information as data, which is usually what you
want to read.

**Run the command rather than printing it for somebody to paste.** Everything
here writes a manifest line and renders files, both of which are reversible and
both of which somebody asked for. Two things are asked about first: a change to
what a repository commits, which is the harness with no machine below, and
installing `uv`, which is the reference above.

Three situations usually come up, and this skill only covers these three.

## Nothing is set up

Walk through [references/getting-started.md](references/getting-started.md). Its
first step runs without asking and leaves this kit subscribed to itself for this
person, which is what makes the rule arrive; the rest is the two scopes, where
kits come from, and the first render.

## Something needs doing

Run `akit list` first, always. It writes nothing, fetches nothing and reports a
failure per line, so it is safe when you do not yet know what is wrong.

Then pick the command by what the person asked for:

| They asked for | Command |
| --- | --- |
| to know what is in a repository before taking anything from it | `akit discover <source>` |
| a kit they do not have yet | `akit add <source> <name>` |
| a kit under a different name, because two sources ship one name | `akit add <source> <name> --as <other>` |
| a kit gone, and the files it wrote gone with it | `akit remove <name>` |
| newer versions of what they already subscribe to | `akit update` |
| a harness started or stopped being written for | `akit harness add <name>`, `akit harness remove <name>` |
| the files on disk to match the manifests again | `akit render` |

**When something is already wrong rather than missing, run `akit doctor`.** It
changes nothing, names a command for every finding, and exits non-zero when it
found something. It reports on the home directory as well as the project, so a
`~/.agents` kept as a git repository gets the same questions a project does:
what it ignores, what it commits, and which of the skills in it are the
person's own rather than renders. Carry out the command it names rather than editing a rendered
file: a copy you edit by hand is one `akit` refuses to touch again, which is a
finding of its own.

Two flags decide where a change lands, and getting them right matters.
`--global` means this person, on this machine. `--project` means this
repository, for everybody who clones it, and is the default. Ask which one they
meant when the request does not say.

Nothing needs an editor. Every command writes the manifest for you, and the
additive ones render afterwards, so there is no second step to remember.

**The two subtractive commands are the exception, deliberately.** `akit remove`
and `akit harness remove` delete what they dropped and write nothing else, so a
command that takes one thing away cannot put fifteen others on disk in passing.
If the manifest was behind, they say how far behind in their last line; `akit
render` is what catches it up, and running it is a decision for the person
rather than a side effect of the removal.

**Run `akit discover <source>` before subscribing to a source nobody here has used.** It
lists what the repository holds, by kind, writes nothing, and leaves the source
in the cache for the `akit add` that follows. It is what answers "which of these
do I want" without a subscription being made to find out: `--verbose` adds the
line each kit says about itself, and `--json` carries the path each one sits at
inside the repository, which is what says whether a plain `owner/repo` is enough
to reach it.

**A `*` has to be quoted.** `akit remove --kind rule '*'` is a subscription to
every rule a source holds; without the quotes the shell replaces it with the
contents of the current directory before `akit` sees anything. The same applies
to `akit add <source> '*'`.

## A new release is out

An upgrade asks nothing of a setup already on disk: the manifests and the
rendered files keep their shape, and `uvx` fetches the new version the next time
it runs. Run `akit render` once afterwards, then `akit doctor`, and carry out
whatever it names. A version that wants more than that says so in its own
release notes.

The copy of this skill on disk carries a [VERSION](VERSION) file beside it,
which is the only way it can tell how old it is. If it disagrees with
`akit --version` by more than a patch, and `akit list` does not show this kit as
subscribed, take the subscription out now: it is the last step of
[references/getting-started.md](references/getting-started.md), and from then on
`akit update` keeps both the skill and its rule current.

Next: `akit list`, which is the first command in every one of the three
situations above.
