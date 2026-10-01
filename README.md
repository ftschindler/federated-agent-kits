# federated-agent-kits

Share the things that configure a coding agent - skills, rules and agent definitions - across
several git repositories at different privacy tiers, and render the subset you subscribe to
into whatever your harness reads.

A **kit** is one such thing. A skill is a folder, a rule is a fragment of instructions, an
agent is a persona with a model and a tool list. They are different shapes, they come from
different repositories, and no repository knows which others you have. The one file that sees
them all at once is yours, on your machine.

**Status: design only.** [DESIGN.md](DESIGN.md) is the source of truth. There is no CLI yet.

## What to use it for

**Keep your own practice in one place and still use it everywhere.** A writing style, a
debugging workflow, a review agent. Subscribe once, render into opencode and VS Code.

**Share with a team without sharing everything.** The corporate repository holds the
corporate kits. The public one holds what you are happy to publish. Which tier a kit sits at
is decided by which repository it lives in, never by a field in a file.

**Pull in other people's kits without vendoring them by hand.** A subscription names a
source and an item. An update is a diff you read, not something that changed under you.

**Stop writing the same instructions into four files.** One rule fragment renders to
`AGENTS.md`, to `.github/instructions/`, and to an `instructions` glob in `opencode.json`.

Use something else if you want a registry, a marketplace, or a runtime that executes agents.
This writes files and then gets out of the way.

## How it will work

```text
akit add ftschindler/federated-agent-kits writing --scope global
akit render          # idempotent; safe to run from a git hook
akit doctor          # name collisions, stale renders, policy violations
```

Two manifests, one schema. A user-wide one lists what is true of you. A committed, per-repo
one lists what is true of that repository, so a colleague clones it and runs one command.

## How it is put together

- **The source file is the source.** Rendered files are generated and disposable. Nothing is
  edited in two places.
- **Install what is whole, compose what is a fragment.** Skills and agents are copied or
  linked. Only rules are concatenated, and only where the harness cannot read a list.
- **A source declares the furthest it may travel.** Rendering a corporate kit into a
  repository with a public remote is refused, not warned about.
- **It is a guardrail, not a security boundary.** The boundary is git remote permissions.
  This prevents accidents by people who already have access.

## License

[MIT](LICENSE).
