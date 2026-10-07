"""The four answers `akit` can give an exit code, and the errors that produce them.

Defined once, here, because the distinction that matters is between a usage error
and a refusal. A usage error means the command was typed wrong and the fix is to
type it differently. A refusal means the command was understood, was legal, and
was declined on purpose: a private source aimed at a public repository is the
case DESIGN.md section 8 exists for, and it has no `--force`. A caller - a hook,
a CI job, the skill - has to be able to tell those two apart without reading the
message, so they are different numbers rather than different prose.

`1` is everything else that went wrong: a source that will not clone, a manifest
that will not parse, a file that will not be written. `0` is a success, including
a success that did nothing.
"""

from __future__ import annotations

from enum import IntEnum


class Exit(IntEnum):
    """What `akit` returns to whatever started it."""

    OK = 0
    """It worked. A no-op says it was a no-op and still returns this."""

    ERROR = 1
    """Something is wrong: the world did not cooperate, or a file is malformed."""

    USAGE = 2
    """The command was typed wrong. Includes a verb that has not landed yet."""

    REFUSAL = 3
    """The command was understood and declined on purpose. There is no override."""


class AkitError(Exception):
    """An error that knows which exit code it is.

    Carrying the code on the exception rather than at the raise site means a
    refusal raised three frames down cannot arrive at the top as a generic
    failure, which is the bug this class is shaped to prevent.
    """

    exit_code: Exit = Exit.ERROR


class UsageError(AkitError):
    """The command was typed wrong."""

    exit_code = Exit.USAGE


class RefusalError(AkitError):
    """A legal command, declined on purpose.

    Every refusal names the source, the target and the command that fixes it
    (DESIGN.md section 3, rule 5). That is the message's job, not this class's,
    but nothing else in the codebase may raise this without one.
    """

    exit_code = Exit.REFUSAL


class NotImplementedYetError(UsageError):
    """A verb that is registered but whose task has not landed.

    A usage error rather than a failure: from where the caller stands the command
    does not do anything yet, and the fix is to run a different one. The list of
    these shrinks to empty by T12, and a test asserts it.
    """

    def __init__(self, command: str, task: str) -> None:
        super().__init__(
            f"akit {command} is not implemented yet; it lands with {task}.\n"
            f"Run `akit --help` to see what this build can already do."
        )
