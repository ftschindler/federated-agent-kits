---
name: akit-fixture
description: A kit that exists so the federation layer has a real remote source to read.
---

# akit-fixture

This is not a skill anybody is meant to use. It is the part the `federation`
test layer subscribes to when it reads this repository over the network, so that
the layer has a source whose shape this project controls alongside the one it
does not.

The real skill, the one an agent asked to "set up my kits" reads, arrives in T11
and lives in `skills/` rather than here. A link to the plan is deliberately not
in this file: the kit is cloned on its own, into a directory that has no
repository around it, so a relative link out of it would resolve to nothing.

## What a test asserts about it

That discovery finds it by name, that its `references/` travel with it, and that
the repository it came from classified as public.
