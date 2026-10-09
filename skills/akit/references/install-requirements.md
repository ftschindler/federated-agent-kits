# What has to be on the machine already

One thing: `uv`. Everything else arrives when a command runs.

`uvx` is part of `uv`, so the first command fails with "command not found"
rather than with anything about kits. Check it before concluding anything else
is wrong:

```sh
uv --version
```

## Where it is missing, offer rather than install

Putting a tool on somebody's machine is not a kit subscription. On a shared or
managed machine it is somebody else's decision, and on anybody's machine it is
software they did not ask for. So say that `uv` is missing, give the two ways
out, and run neither until they have picked one.

- **The platform's package manager**, on a machine whose software is managed by
  one. Ask which one rather than guessing from the operating system: more than
  one is often installed, and the one that is right here is the one everything
  else on this machine came from.
- **Astral's install script**, documented at `https://docs.astral.sh/uv/`,
  everywhere else. It installs into the person's own home rather than
  system-wide, which is why it needs no administrator and touches nothing shared.

Once it answers, carry on where you left off. Nothing else here needs anything
installed: `uvx` fetches `akit` on first use and keeps it in a cache.
