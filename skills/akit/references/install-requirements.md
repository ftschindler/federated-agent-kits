# What has to be on the machine already

One thing: `uv`. Everything else arrives when a command runs.

`uvx` is part of `uv`, so the first command may fail with "command not found"
rather than with anything about kits. Check before concluding anything else
is wrong:

```sh
uv --version
```

## Where it is missing, offer to install it

Putting a tool on somebody's machine is not a kit subscription, so do not
install `uv` unless you are asked to. Say that `uv` is missing, state clearly
that `uv` is required for this skill to work, and offer to install it.

If the user declines, restate clearly that the skill does not work without `uv`
and stop. Otherwise:

1. Prefer the **platform's package manager**. On Windows that is usually
   `winget`, on macOS `brew`, and on Linux whichever one the distribution uses.
   Work out the platform, check which of them are actually on the machine, and
   ask the user which of the working ones to use. If that package manager does
   not carry `uv`, which is common on Linux, or the install fails for any other
   reason, including lacking privileges, say plainly why it failed and go on to
   the second option, noting that it is the one Astral supports officially.
2. Install `uv` using **Astral's install script**, documented at
   `https://docs.astral.sh/uv/`. It installs into the person's own home rather
   than system-wide, which is why it needs no administrator and touches nothing
   shared.

On Windows, `uv` and `uvx` only appear in a new shell, never in the one that
installed them. On everything else they appear once the shell picks up the
directory the installer wrote into, which usually means a new shell as well.

If the install does not work, or `uv --version` still answers with nothing
sensible, say so and restate that the skill does not work without `uv`. Ask the
user whether to stop or to keep trying.

Once it answers, carry on where you left off. Nothing else here needs anything
installed: `uvx` fetches `akit` on first use and keeps it in a cache.
