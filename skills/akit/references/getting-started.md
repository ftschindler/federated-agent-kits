# Nothing is set up

A machine or a repository with no kits at all. Four steps, and only the first
needs the person.

## 1. Ask which of the two files this belongs in

There is one question, and it is not a technical one: **is this true of this
person, or of this repository?**

- True of the person, on every repository they open: their own manifest, which
  `--global` names. A style guide they always want, a debugging workflow they
  wrote.
- True of the repository, for everybody who clones it: the repository's
  manifest, `.akit.yaml` at its root, which is the default. The kits a
  contributor needs to work on this code.

Ask when the request does not say. Writing the wrong one is not dangerous, but
it does put somebody's personal taste into a colleague's checkout.

## 2. Find out where the kits they want live

A source is an ordinary git repository with `skills/`, `rules/` or `agents/` in
it. It needs no registration and never learns that somebody subscribed. `akit
help sources` lists every form a source can be written in, including a local
path for a repository they are writing themselves.

If they have no source in mind yet, say so and stop. Subscribing to nothing is a
manifest with no lines in it, which helps nobody.

## 3. Subscribe, which also renders

```sh
uvx --from federated-agent-kits akit add ftschindler/agent-kits writing
```

`akit add` resolves the source, checks the kit is really there, writes one line
and renders. A typo fails before the manifest is touched and lists what the
source does hold, so a failure here is a spelling to correct rather than a mess
to clean up.

Add `--global` for the person's own manifest. Add `--as <name>` when two sources
ship a kit under one name.

Repeat for each kit they want. Then run `akit list` and tell them what it
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

## Then place the activation rule

A skill nobody opens does nothing. [activation-rule.md](activation-rule.md) has
the text and where to put it.
