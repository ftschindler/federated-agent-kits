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

**Status: design only.** [DESIGN.md](DESIGN.md) is the source of truth for what gets built,
[IMPLEMENTATION.md](IMPLEMENTATION.md) for the order it gets built in. There is no CLI yet.

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

## How it will work

```text
akit add owner/repo writing      # -p writes the repository's file instead of yours
akit render          # safe to run from a git hook
akit doctor          # name collisions, stale renders, refusals
```

A source is an ordinary git repository with `skills/`, `rules/` or `agents/` in it. It needs
no manifest and no registration, and it never learns that you subscribed.

Your subscriptions live in two files with one format. A personal one says what is true of
you. A committed one in a repository says what that repository expects, so a colleague clones
it and runs one command.

## What it promises

**Windows and Linux are equal.** Both are tested in CI, and neither is the afterthought.

**Python only.** Scripts carry their dependencies inline and run under `uv`, so there is
nothing to install and no lockfile to go stale.

**A new harness is one file.** opencode and VS Code come first. An adapter answers six
questions about where that harness keeps things, and nothing else in the system changes.
[DESIGN.md](DESIGN.md#4-adding-a-harness) works pi through as an example.

**The file you edit is the only copy.** Everything rendered is generated and disposable.

## License

[MIT](LICENSE).
