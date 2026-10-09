# Adding an adapter

A harness is a thing that reads kits: opencode on your laptop, GitHub Copilot in VS Code,
GitHub Copilot in CI, pi. Teaching this tool about one is a file in
`src/federated_agent_kits/adapters/` and a line in the tuple that registers it. There is no
third place, and a test fails if a change reaches one.

This page says how to answer the seven questions.
[DESIGN.md](../DESIGN.md#4-adding-a-harness) says why those are the seven, and the two do not
repeat each other: read this one with an adapter open beside it.

## Start by copying the nearest one

Three adapters ship, and between them they cover every answer anybody has needed so far.

| Copy | When your harness | File |
| --- | --- | --- |
| `copilot-vscode` | is installed on this machine and reads rules from a directory of its own | [`copilot_vscode.py`](../src/federated_agent_kits/adapters/copilot_vscode.py) |
| `opencode` | is installed on this machine and reads rules from an `AGENTS.md` you also write in | [`opencode.py`](../src/federated_agent_kits/adapters/opencode.py) |
| `copilot-ci` | runs somewhere else and only ever sees what the repository commits | [`copilot_ci.py`](../src/federated_agent_kits/adapters/copilot_ci.py) |

Each is one `Adapter` value with a docstring saying where its paths came from. The value is
frozen and nothing in it is computed at import time, so an adapter is read as a table rather
than as code.

```python
from federated_agent_kits.adapters.adapter import Adapter, Destination, RuleShape
from federated_agent_kits.manifest import Kind, Scope

ADAPTER = Adapter(
    name="pi",
    summary="pi, on this machine",
    has_a_machine=True,
    destinations={
        (Kind.SKILL, Scope.USER): Destination(write=".agents/skills", read=(".agents/skills",)),
        (Kind.SKILL, Scope.PROJECT): Destination(write=".agents/skills", read=(".agents/skills",)),
        (Kind.RULE, Scope.USER): Destination(write=".pi/agent/AGENTS.md"),
        (Kind.RULE, Scope.PROJECT): Destination(write="AGENTS.md"),
    },
    rule_shape=RuleShape.SHARED_FILE,
    orders_rules=True,
    evidence=(".pi",),
    anchor=nearest_pi_directory,
)
```

That is pi, which is the worked example throughout this page. It is not shipped: an adapter
for a harness nobody here runs is maintenance with no user. It is written out in full in
[`tests/pi_adapter.py`](../tests/pi_adapter.py), registered only in the test suite, and the
contract test runs over it alongside the three shipped adapters. Writing one adapter for real
is what keeps the paragraphs below true.

## Question 1: where do skills go, and where are they read from

Two lists, in one `Destination` per scope. `write` is the single directory a rendered skill
lands in. `read` is every directory a *source repository* may have left one in, which is
wider.

**Write where the other harnesses write, if your harness reads that directory at all.**
`.agents/skills/` is read by all three shipped adapters and by pi, so a skill two harnesses
want is one copy on disk rather than two. Choosing a private directory when the shared one
would have worked doubles the bytes and doubles what a withdrawal has to get right.

The second list is what the discovery walk is told about. A repository that keeps its skills
in `.claude/skills/` is a source for your harness as much as for anybody else's, and a
directory left out of `read` is a kit this tool cannot see.

Every path is relative to the scope's base directory, which is a home directory for
`Scope.USER` and the project anchor for `Scope.PROJECT`. Separators are always `/`, including
for the Windows answer: these are declarations, and `Path.joinpath` turns one into a path at
the moment it is used.

## Question 2: which of the three rule shapes it is

`RuleShape.DIRECTORY` is a directory we own, one file per rule. Rendering writes a file,
withdrawing deletes it, and a neighbouring rule is never touched. Copilot is this shape, and
it is the one to want.

`RuleShape.SHARED_FILE` is one fixed file we have to share, each rule between its own
markers. opencode and pi are this shape, because the file they read is an `AGENTS.md` that a
person writes prose into. Everything outside our markers survives every render, which the
renderer already does; what your adapter supplies is the path of the host file in `write`.

`RuleShape.POINTED` is a directory we own that the harness has to be pointed at once, by one
key in a config somebody owns. **No adapter shipping today answers this way and there is no
renderer behind it.** The enum member and the `Pointer` dataclass are in the interface, and
the first person to add a harness that wants pointing writes the code that edits that config.
Budget for that rather than discovering it: it is a second in-place editor of a file a person
owns, with the same care `AGENTS.md` gets.

Two fields travel with the first shape. `rule_suffix` is what the harness insists a rule file
is called, `.instructions.md` for Copilot and `.md` by default. `rule_frontmatter` is the
keys every rule rendered for this harness carries whatever its source said; Copilot's
`applyTo` is there because a `.instructions.md` file without it is discovered, listed, and
never loaded.

`orders_rules` says whether the harness reads our rules in the order the manifest lists them.
True for a shared file, because the blocks are ours and sequential. False for a directory,
unless the harness documents an order. `akit list` prints which it is, so an honest `False`
costs a word of output and a hopeful `True` costs somebody an afternoon.

## Question 3: the pointer, if it is the middle shape

Skip it unless `rule_shape` is `RuleShape.POINTED`. A `Pointer` names a `config` file
relative to the scope's base directory and the one `key` inside it that holds the directory
we own. It is written at setup and never at render.

A pointer is never withdrawn. `akit harness remove` names the file and the key you would have
to edit, and `akit doctor` reports a pointer aimed at a directory that is not there. We
delete files we created and we do not edit a file we only added a line to.

## Question 4: agents, and declining a kind

**Every adapter shipped today declines agents, and declining is an answer rather than a gap.**
A kind with no `(kind, scope)` entry in `destinations` is declined: `adapter.takes` is False,
`adapter.target` returns `None`, the kind is absent from `adapter.kinds`, and the CLI says so
instead of failing. Nothing anywhere may crash on it, which is why all three adapters exercise
that path rather than a fixture doing it.

So leave `agent_frontmatter` and `agent_tools` empty, and leave `(Kind.AGENT, ...)` out of
`destinations`. [T13](../IMPLEMENTATION.md#t13---agents) fills them in once three real agents
have said what the tool-name table should contain. Write the path your harness keeps agents
in into the module docstring, the way `copilot_ci.py` records
`.github/agents/<name>.agent.md` and its 30,000-character cap: that is the research not being
done twice.

Declining is also the right answer for a kind your harness has nowhere to put in one scope
only. A `Destination(write=None, read=(...))` takes nothing and still tells discovery where a
source may have left one.

## Question 5: tool names

Empty until agents render. `agent_tools` maps our name for a tool to this harness's.

## Question 6: the project anchor

**This is the question that renders into the wrong place without failing.** `anchor` is a
function from a directory to the directory this harness treats as the project, or `None`.
The default, `git_root`, walks up to the worktree root, which is where `.akit.yaml` already
is, and is right for opencode and for both Copilot harnesses.

It is a function rather than something the caller computes because pi disagrees: pi anchors
on the nearest ancestor holding a `.pi` directory, which in a monorepo is a package rather
than the repository. An adapter that took the git root there would write files pi never
reads, and nothing would fail. The files are present, the agent behaves as if they are not.

```python
def nearest_pi_directory(start: Path) -> Path | None:
    """pi's project anchor: the nearest ancestor holding a `.pi` directory."""
    for directory in (start, *start.parents):
        if (directory / ".pi").is_dir():
            return directory
    return None
```

Answer `None` when there is no project here. Returning the starting directory as a fallback
means every directory on the disk is a project, and a render outside a repository then writes
wherever it was run.

Some harnesses add a condition your adapter cannot resolve. pi ignores everything
project-local until you have trusted the folder, so correctly placed files stay unread. That
is `akit doctor`'s to report rather than the adapter's to fix.

## Question 7: how to tell the harness is on this machine

`evidence` is a tuple of paths under a home directory, any one of which means this harness
has run here. Detection is evidence on this disk and never configuration, and never what a
repository contains: a checkout holding `.github/agents/` says nothing about this machine,
and inferring a harness from one starts committing rendered files nobody asked for.

**List every platform's answer, not the one you are typing on.** opencode declares six paths
because `~/.config/opencode` is the Linux answer written down as if it were the only one.
A harness that goes undetected renders nothing and fails nothing, which is the expensive half
of being wrong; a harness detected and unused costs a directory nobody reads.

Err towards detecting. `copilot-vscode` looks for VS Code rather than for a signed-in Copilot
session, because a signed-in session is not something this machine can be asked about.

## The property that is not a question: whether the harness has a machine

`has_a_machine=False` is for a harness `akit render` can never run on. It is never detected,
whatever is in `evidence`, so it arrives only by being named in a manifest:
`akit harness add <name>`. Everything written for it is committed, because the repository is
how it is delivered.

That one flag moves the directories out of the `.gitignore` block, brings the harness under
`render --check`, and brings the leak refusal into play: a private source's kit cannot land
in a committed spot in a public repository. None of that is in your file. It follows from the
flag.

## Registering it, and the three places

Add the module, then one line in
[`adapters/__init__.py`](../src/federated_agent_kits/adapters/__init__.py):

```python
ADAPTERS: tuple[Adapter, ...] = (opencode.ADAPTER, copilot_vscode.ADAPTER, copilot_ci.ADAPTER, pi.ADAPTER)
```

The third place is the contract test, which picks the new adapter up for free because it is
parametrised over `ADAPTERS`. There is no fourth. `test_adding_an_adapter.py` reads every
module in `src/` and fails if one of them imports an adapter module or branches on a harness
name, so a special case written anywhere else is a failing suite rather than something
noticed in review.

## What the contract test checks

Run `make test_unit` and read
[`tests/test_adapters.py`](../tests/test_adapters.py) when it fails. The assertions, in the
order they usually bite:

- every declared path is relative and uses `/`;
- the directory you write to is also one you read from, because a harness that writes
  somewhere it does not read never sees its own kits;
- a pointer exists exactly when the shape is `POINTED`;
- a harness with a machine declares evidence, and one without declares none;
- the anchor answers `None` in a directory that is not a project;
- a declined kind has no target and crashes nothing;
- both scopes do not write to one place.

Write the adapter from this page, register it in the tuple, and that suite is the review.
