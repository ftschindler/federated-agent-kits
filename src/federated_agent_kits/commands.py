"""Every command `akit` has, declared in one place, with the help it must carry.

DESIGN.md section 11 puts everything deterministic in the CLI so the skill does
not have to describe it, which only works if the help is good enough to be read
instead of the skill. That is a contract rather than an aspiration, so it is data
here and a test in `tests/test_help_contract.py` rather than prose somebody has
to remember while writing a new verb:

- one sentence saying what the command does;
- a paragraph saying what it writes and what it never writes;
- at least one worked example, with real-looking arguments;
- every flag and positional documented in one line, including what it refuses;
- a closing `Next:` line naming the command somebody usually runs after this one.

A verb whose task has not landed still carries all five. It has to: the help is
how somebody finds out the verb exists, and a placeholder that says nothing is
worse than no entry at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Argument:
    """One positional or one flag, and the single line that explains it."""

    spec: tuple[str, ...]
    """What argparse is handed: `("source",)` or `("--global",)`."""

    help: str
    """One line. For a flag that declines to do something, the line says so."""

    metavar: str | None = None
    action: str | None = None
    choices: tuple[str, ...] | None = None
    nargs: str | None = None
    dest: str | None = None

    @property
    def is_flag(self) -> bool:
        return self.spec[0].startswith("-")

    @property
    def takes_no_value(self) -> bool:
        """A flag is a switch unless it was given something that implies a value.

        Without this, `--manifest PATH` is handed to argparse as `store_true` and
        dies on the metavar it was also given, which is a crash at import time
        rather than a wrong answer - but only for the commands that have such a
        flag, so it is worth not relying on noticing.
        """
        return self.metavar is None and self.choices is None and self.nargs is None


@dataclass(frozen=True)
class Command:
    """One verb, with everything the help contract asks of it."""

    name: str
    summary: str
    """One sentence, no full stop needed, used as the one-line listing."""

    writes: str
    """A paragraph saying what lands on disk and what never does."""

    examples: tuple[str, ...]
    following: str
    """The `Next:` line: the command somebody usually runs after this one."""

    arguments: tuple[Argument, ...] = ()
    task: str | None = None
    """The implementation task this verb waits for, or `None` once it has landed."""

    @property
    def implemented(self) -> bool:
        return self.task is None


SCOPE_FLAGS: tuple[Argument, ...] = (
    Argument(("--global",), "Act on your own manifest instead of this repository's", dest="global_scope"),
    Argument(("--project",), "Act on this repository's manifest, which is the default"),
    Argument(("--manifest",), "Act on the manifest at this path, instead of finding one", metavar="PATH"),
)


COMMANDS: tuple[Command, ...] = (
    Command(
        name="list",
        summary="Show what you subscribed to, where it came from and where it was rendered",
        writes=(
            "Writes nothing at all and fetches nothing. It reads the two manifests, the "
            "render record and the files on disk, and reports a failure per line rather "
            "than stopping, because this is the command you run when something is already "
            "wrong. It never creates a cache entry for a source it cannot find, and it "
            "exits 0 even when a line reports a problem: `akit doctor` is the command that "
            "exits non-zero on a broken setup."
        ),
        examples=("akit list", "akit list --json"),
        arguments=(),
        following="akit render, to make the files on disk match what this listed",
    ),
    Command(
        name="add",
        summary="Subscribe to one kit from one source, and render it",
        writes=(
            "Writes one line into a manifest, pinned to the commit it resolved, and then "
            "renders. It clones the source into the cache if this machine does not have it "
            "yet. It never edits a manifest it was not pointed at, and it writes nothing at "
            "all if the kit is not in the source: a typo fails before the manifest is "
            "touched, listing what the source does hold."
        ),
        examples=(
            "akit add ftschindler/federated-knowledge-skills fkb",
            "akit add --global github.com/acme/kits writing --as house-style",
        ),
        arguments=(
            Argument(("source",), "The repository the kit lives in, as a shorthand, a URL or a path"),
            Argument(("name",), 'The kit to subscribe to, or "*" for every kit the source holds'),
            Argument(("--as",), "Render the kit under this name instead of its own", metavar="NAME", dest="rename"),
            Argument(("--kind",), "Only consider this kind of part", choices=("skill", "rule", "agent")),
            *SCOPE_FLAGS,
        ),
        following="akit list, to see what it rendered and where",
        task="T7",
    ),
    Command(
        name="remove",
        summary="Drop one subscription, and withdraw the files it rendered",
        writes=(
            "Removes one line from a manifest and deletes the files the render record says "
            "that subscription explains. A rendered copy you edited by hand is left alone "
            "and named. A file not in the record is never touched, so a skill you wrote "
            "yourself survives. It refuses rather than guessing when both manifests "
            "subscribe to the name."
        ),
        examples=("akit remove writing", "akit remove --global fkb"),
        arguments=(
            Argument(("name",), "The subscription to drop, by the name it is rendered under"),
            *SCOPE_FLAGS,
        ),
        following="akit doctor, to check nothing was left behind",
        task="T7",
    ),
    Command(
        name="harness",
        summary="Add or remove a harness by name, and render or withdraw for it",
        writes=(
            "Edits the `harnesses:` list in one manifest and then renders, or withdraws "
            "what that harness had rendered. It never edits a subscription, and removing a "
            "harness never deletes a file another harness still explains. `detected` is a "
            "name like any other and stays where it is."
        ),
        examples=("akit harness add copilot-ci", "akit harness remove vscode --global"),
        arguments=(
            Argument(
                ("action",),
                "Whether to start or stop rendering for the harness",
                metavar="action",
                choices=("add", "remove"),
            ),
            Argument(("name",), "The harness, by the name its adapter registers"),
            *SCOPE_FLAGS,
        ),
        following="akit render, to see the harness pick the files up",
        task="T7",
    ),
    Command(
        name="render",
        summary="Make the files each harness reads match what the manifests say",
        writes=(
            "Copies subscribed parts into the directories each harness reads, rewrites the "
            "`.gitignore` marker block whole, and records every file it wrote with a hash. "
            "It deletes only files that record explains and whose bytes still match, so "
            "anything you wrote or edited yourself survives. It fetches nothing, which is "
            "why a render on a train is yesterday's render."
        ),
        examples=("akit render", "akit render --check", "akit render --project --harness opencode"),
        arguments=(
            Argument(
                ("--check",), "Write nothing and exit non-zero if a committed render is stale", action="store_true"
            ),
            Argument(
                ("--prune",),
                "Also delete plausible orphans, which is the one deletion we cannot prove safe",
                action="store_true",
            ),
            Argument(
                ("--harness",),
                "Narrow to this harness; writes nothing to a manifest and deletes nothing",
                metavar="NAME",
                action="append",
            ),
            Argument(
                ("--no-harness",),
                "Exclude this harness; it deletes nothing, it only skips",
                metavar="NAME",
                action="append",
            ),
            Argument(
                ("--global",), "Only your own subscriptions, rendered to machine-level directories", dest="global_scope"
            ),
            Argument(("--project",), "Only this repository's subscriptions, rendered inside it"),
        ),
        following="akit doctor, if anything it reported looked wrong",
        task="T5",
    ),
    Command(
        name="update",
        summary="Fetch a source, move its pins, and show what moved",
        writes=(
            "Fetches new commits into the cache, rewrites the pin for every name under a "
            "key or for none of them, prints the diff of every part you subscribed to, and "
            "then renders. A part that disappeared stops that key and leaves its pin where "
            "it was, rather than silently rendering less than yesterday. It never moves the "
            "pin for some names under a key and not others, and it writes nothing at all "
            "when the fetch fails."
        ),
        examples=("akit update", "akit update fkb"),
        arguments=(
            Argument(("name",), "The subscription to update; all of them when omitted", nargs="?"),
            *SCOPE_FLAGS,
        ),
        following="akit list, to confirm the new pins",
        task="T7",
    ),
    Command(
        name="doctor",
        summary="Say what is wrong with this setup, and which command fixes it",
        writes=(
            "Changes nothing, ever, which is what makes it safe to run when you do not know "
            "what is going on. It reads the manifests, the render record and the disk, and "
            "goes near the network only in the one case `render` does. It exits non-zero "
            "when it found something, and every finding names a command."
        ),
        examples=("akit doctor", "akit doctor --json"),
        arguments=(),
        following="whichever command the findings named",
        task="T9",
    ),
    Command(
        name="help",
        summary="Explain one of the four things that are not commands",
        writes=(
            "Writes nothing and reads nothing but this package. The topics are the concepts "
            "a command's own help cannot carry: the manifest format, what counts as a "
            "source, how harnesses are named and detected, and what keeps a private kit out "
            "of a public repository."
        ),
        examples=("akit help manifest", "akit help privacy"),
        arguments=(
            Argument(
                ("topic",),
                "One of: manifest, sources, harnesses, privacy",
                metavar="topic",
                choices=("manifest", "sources", "harnesses", "privacy"),
            ),
        ),
        following="akit list, which is what most of these topics describe the input to",
    ),
)


BY_NAME: dict[str, Command] = {command.name: command for command in COMMANDS}


def unimplemented() -> list[str]:
    """The verbs that still exit 2. Empty by T12, asserted by a test written in T1."""
    return [command.name for command in COMMANDS if not command.implemented]


@dataclass(frozen=True)
class Topic:
    """One `akit help <topic>` page."""

    name: str
    summary: str
    body: str
    following: str
    see_also: tuple[str, ...] = field(default=())


TOPICS: tuple[Topic, ...] = (
    Topic(
        name="manifest",
        summary="The file you edit, and the two places it lives",
        body=(
            "A manifest says what you subscribed to and nothing about where a source is on\n"
            "this disk. There are two of them, in one format. Yours lives in your platform's\n"
            "config directory and says what is true of you on this machine. A project one,\n"
            "`.akit.yaml` beside a repository's `.git`, says what that repository expects, and\n"
            "is committed. The project one adds to yours; neither overrules the other, because\n"
            "each renders into its own scope and the two never write to the same place.\n"
            "\n"
            "So a name used in both is not a contest, it is two copies in two directories, and\n"
            "`akit list` and `akit doctor` report it rather than picking a winner. The fix is\n"
            "`as:`, which renders a kit under a different name. Rules are the one kind with an\n"
            "order: they are a list rather than a mapping, yours are read before a\n"
            "repository's, and that order is what decides which of two contradicting rules\n"
            "wins.\n"
            "\n"
            "Each entry is a source key mapped to the kits you want from it, and a key may\n"
            "carry a `#<commit>` pin. The file is yours: comments, key order and layout\n"
            "survive every command that writes it."
        ),
        following="akit list, which reads both manifests and tells you which scope each entry came from",
        see_also=("sources",),
    ),
    Topic(
        name="sources",
        summary="What a source is, and how parts are found inside one",
        body=(
            "A source is an ordinary git repository with `skills/`, `rules/` or `agents/` in\n"
            "it. It needs no manifest, no registration and no cooperation, and it never\n"
            "learns that you subscribed. A key names one in five forms: a forge shorthand, a\n"
            "forge URL, a git URL, a URL into a subdirectory, or a path on this disk.\n"
            "\n"
            "Parts are found by walking the fixed directories for each kind, three levels\n"
            "deep, plus whatever directories an installed adapter declares. A part nearer the\n"
            "top shadows a deeper one of the same name. The root of the source is read one\n"
            "level deep rather than three, so a repository that is one skill is a source and a\n"
            "repository's `rules/` does not also become its agents.\n"
            "\n"
            "A remote source is cloned into your platform's cache directory, shallow, the\n"
            "first time anything needs it, and every spelling of one repository shares that\n"
            "one entry. A pin is checked out there, and a commit the shallow clone does not\n"
            "hold is fetched when it is asked for. Only `akit add` and `akit update` fetch:\n"
            "everything else works from the cache, so a command run offline either answers\n"
            "from what this machine already has or says which source it was missing.\n"
            "\n"
            "A path source is read where it is and is never cloned, cached or pinned, which is\n"
            "what makes it the right key for a kit you are writing. A relative one resolves\n"
            "against the repository root, so it means the same on every machine, and a\n"
            "committed manifest may only name one that stays inside the repository.\n"
            "\n"
            "Cloning is also how a source is known to be private: the first attempt is made\n"
            "with your credentials taken away, and a source that needs them back is private\n"
            "from then on. See `akit help privacy` for what that classification is used for."
        ),
        following="akit add, which is how a source becomes a subscription",
        see_also=("manifest", "privacy"),
    ),
    Topic(
        name="harnesses",
        summary="How a harness is named, detected, and told apart from a source",
        body=(
            "A harness is a thing that reads kits: opencode, VS Code, a cloud agent running\n"
            "in CI. One adapter per harness answers where it keeps each kind, which shape it\n"
            "takes rules in, how a project anchor is computed, and how to tell it is\n"
            "installed. An adapter may decline a kind, and every adapter shipped today\n"
            "declines agents.\n"
            "\n"
            "Detection is by evidence on this disk, never by what a repository contains. When\n"
            "detection is not enough, name the harness in a manifest's `harnesses:` list.\n"
            "`detected` is a name like any other in that list, so naming one more harness\n"
            "does not turn the rest off."
        ),
        following="akit list, which reports every harness it detected and which kinds each takes",
        see_also=("privacy",),
    ),
    Topic(
        name="privacy",
        summary="What keeps your employer's kits out of a public repository",
        body=(
            "A source is private when fetching it needed credentials, which is observable\n"
            "only while fetching and is therefore recorded when it happens. A target is\n"
            "public when its remotes resolve anonymously; no remote means private, and\n"
            "anything else is refused rather than guessed at.\n"
            "\n"
            "A private source's parts do not render into a public target, and a private\n"
            "source is not named in a public target's committed manifest. Both fail hard,\n"
            "naming the source and the target, and there is no `--force`. The check is per\n"
            "harness, not per repository: rendering a private kit for a laptop harness in a\n"
            "public repository commits nothing and is fine.\n"
            "\n"
            "This is a guardrail, not a boundary. It judges a remote at the moment it runs,\n"
            "so it cannot help with a repository made public next month."
        ),
        following="akit doctor, which reports a committed render that would leak before you commit it",
        see_also=("harnesses",),
    ),
)

TOPICS_BY_NAME: dict[str, Topic] = {topic.name: topic for topic in TOPICS}
