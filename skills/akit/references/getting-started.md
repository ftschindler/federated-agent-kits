# Nothing is set up

A machine or a repository with no federated agent kits at all. The first step
is the same every time and needs nobody's input; everything after it is a
conversation.

If `uv --version` fails, start at
[install-requirements.md](install-requirements.md) and come back.

## 1. Subscribe to this kit, globally, before anything else

Run these two, in this order, without asking:

```sh
uvx --from federated-agent-kits akit add --global ftschindler/federated-agent-kits akit
uvx --from federated-agent-kits akit list
```

The first takes the skill and the five-line rule beside it, because they carry
one name and are one kit. The rule is the half that matters: a skill nobody
opens does nothing, and what makes a model open this one is a sentence in the
prompt saying when to. The second says where both landed.

This is done rather than offered because reading this page means the person
already wanted the skill, and because a copy placed by hand is one nothing
updates and nothing can remove. It leaves a working global setup, with the skill
and the rule managed like any other kit.

**Then report it, in three parts:** that `akit` is now subscribed to itself for
this person on this machine, which files `akit list` says it wrote, and how to
undo it:

```sh
uvx --from federated-agent-kits akit remove --global akit
```

That drops the subscription and deletes the copies it wrote, leaving anything
the person wrote themselves alone. Say that line out loud rather than waiting to
be asked for it: a setup step somebody cannot reverse is one they did not really
consent to.

A copy of this skill placed by hand somewhere else is now a second one. Say so,
and delete it once they agree.

## 2. Say where kits can live, and ask what they have in mind

There are two scopes, and the difference is not technical:

- **User-wide**, which `--global` names: true of this person, on every
  repository they open. A style guide they always want, a debugging workflow
  they wrote. Step 1 used this one.
- **Per-repository**, which is the default: true of the repository, for
  everybody who clones it. The kits a contributor needs to work on this code,
  committed in `.akit.yaml` at its root.

Say both, then ask which they have in mind and which kits, if any, they already
know they want. Where the answer names neither, stop here: the setup works, and
subscribing to nothing is a manifest with no lines in it.

## 3. Where kits come from

**Any git repository with `skills/` or `rules/` in it is a source.** It needs no
manifest, no registration and no permission, and it never learns that somebody
subscribed. `akit help sources` lists every form a key can take, including a
local path for a repository the person is writing themselves.

**The skills.sh marketplace is one of those repositories.** Anything installable
with `npx skills add <repo>` is installable here, and this is a drop-in
replacement for that command with two differences worth saying: the subscription
is written down in a file the person owns, and `akit update` brings changes as a
diff they read rather than as something that changed under them.

Then subscribe, which also renders:

```sh
uvx --from federated-agent-kits akit add <source> <name>
```

`akit add` resolves the source, checks the kit is really there, writes one line
and renders. A typo fails before the manifest is touched and lists what the
source does hold, so a failure here is a spelling to correct rather than a mess
to clean up. Add `--global` for the person's own manifest, and `--as <name>`
when two sources ship a kit under one name.

Repeat for each kit they want, then run `akit list` and tell them what it
reports: which kits, from where, rendered to which files.

## 4. Check the harnesses

`akit list` also says which harnesses it detected on this machine and which
kinds each one takes. A harness that is installed but not listed, or listed but
not installed, is what `akit doctor` reports with the command that fixes it.

One harness is never detected, because it has no machine to detect: GitHub
Copilot running in CI reads what the repository commits. It arrives only by
being named.

```sh
uvx --from federated-agent-kits akit harness add copilot-ci
```

That changes what the repository commits, so say so before running it. `akit
help privacy` covers what cannot be committed, which is anything from a source
that needed credentials to clone.
