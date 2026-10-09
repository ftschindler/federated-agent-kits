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

The `--from` is not decoration. The distribution is `federated-agent-kits` and
the command inside it is `akit`, and `uvx` reads its first argument as a
distribution name.

**Every command explains itself, so read its help rather than guessing.** `akit
<command> --help` says what the command writes and what it never writes, with a
worked example. `akit help manifest`, `akit help sources`, `akit help harnesses`
and `akit help privacy` cover the four things that are not commands. `--json` on
any command gives you the same information as data, which is usually what you
want to read.

Three situations come up, and nothing here covers a fourth.

## Nothing is set up

Walk through [references/getting-started.md](references/getting-started.md). It
covers the one question you have to ask the person, which manifest their answer
means, and the first render.

Place the activation rule as well, once per machine:
[references/activation-rule.md](references/activation-rule.md).

## Something needs doing

Run `akit list` first, always. It writes nothing, fetches nothing and reports a
failure per line, so it is safe when you do not yet know what is wrong.

Then pick the command by what the person asked for:

| They asked for | Command |
| --- | --- |
| a kit they do not have yet | `akit add <source> <name>` |
| a kit under a different name, because two sources ship one name | `akit add <source> <name> --as <other>` |
| a kit gone, and the files it wrote gone with it | `akit remove <name>` |
| newer versions of what they already subscribe to | `akit update` |
| a harness started or stopped being written for | `akit harness add <name>`, `akit harness remove <name>` |
| the files on disk to match the manifests again | `akit render` |

**When something is already wrong rather than missing, run `akit doctor`.** It
changes nothing, names a command for every finding, and exits non-zero when it
found something. Carry out the command it names rather than editing a rendered
file: a copy you edit by hand is one `akit` refuses to touch again, which is a
finding of its own.

Two flags decide where a change lands, and getting them wrong is the common
mistake. `--global` means this person, on this machine. `--project` means this
repository, for everybody who clones it, and is the default. Ask which one they
meant when the request does not say.

Nothing needs an editor. Every command writes the manifest for you, and `akit`
renders afterwards, so there is no second step to remember.

## A new release is out

An upgrade asks nothing of a setup already on disk: the manifests and the
rendered files keep their shape, and `uvx` fetches the new version the next time
it runs. Run `akit render` once afterwards, then `akit doctor`, and carry out
whatever it names. A version that wants more than that says so in its own
release notes.

The copy of this skill on disk carries a `VERSION` file beside it, which is the
only way it can tell how old it is. If it disagrees with `akit --version` by more
than a patch, subscribe to it rather than leaving the hand-placed copy:

```sh
uvx --from federated-agent-kits akit add --global ftschindler/federated-agent-kits akit
```

That replaces the copy somebody placed by hand with a managed one, and `akit
update` keeps it current from then on.

Next: `akit list`, which is the first command in every one of the three
situations above.
