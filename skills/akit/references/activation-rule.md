# The activation rule

The skill is only opened if something in the prompt says when to. That something
is this rule, and placing it is a one-off per machine.

## Where it goes

Every harness keeps user-level instructions somewhere different, and the paths
move. So ask the harness rather than guessing: in the harness being used right
now, where do always-on, user-level instructions live? That is the file this
text goes into. If the harness has no user-level place and only a per-repository
one, put it there and say so, because it then has to be placed again in the next
repository.

Append it to that file rather than replacing what is already in it, and leave
everything around it untouched.

## The text

```markdown
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
```

## Then stop placing it by hand

This repository ships that text as a rule of its own, so once `akit` is set up
the placement becomes a subscription like any other:

```sh
uvx --from federated-agent-kits akit add --global ftschindler/federated-agent-kits akit
```

That subscribes to the skill and the rule together, because they are one kit.
The hand-placed copy can then be deleted: `akit list` says where the managed one
landed.
