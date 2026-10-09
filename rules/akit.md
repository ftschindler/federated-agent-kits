---
name: akit
description: >-
  That `akit` manages the skills, rules and agent definitions on this machine,
  and when to reach for it.
---

# Agent kits

The skills, rules and agent definitions here are subscribed to with `akit`, and
every rendered copy is disposable: edit the source repository or the manifest,
never the copy.

**Load the `akit` skill** when a machine or a repository has no kits set up yet,
when somebody asks to add, update or remove one, or when a harness is not
reading the instructions it should.

`uvx --from federated-agent-kits akit list` says what is subscribed to and where
it landed, and `uvx --from federated-agent-kits akit doctor` says what is wrong
and which command fixes it. Both write nothing.
