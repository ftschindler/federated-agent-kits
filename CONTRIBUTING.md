# Contributing

## System requirements

[uv](https://docs.astral.sh/uv/), git, and node. Nothing else, on Linux, macOS or Windows.
Python is fetched by `uv`, and there is no virtual environment to create and no lockfile of
ours to keep in step.

## Bootstrap

```sh
make bootstrap   # install the pre-commit hooks into this clone
make check       # run the full guard suite over every file
make test        # the unit and cli layers
```

`make` is a convenience and not a dependency. Every target is one line, and on Windows that
line is what you run instead:

```sh
uv run .scripts/run-tests.py unit
```

## Tests

Four layers, each in its own marker, each a separate job in CI on both Linux and Windows.

| Marker | What it is | Needs |
| --- | --- | --- |
| `unit` | the library, in-process | nothing |
| `cli` | `akit` as a subprocess in a fake home | git |
| `federation` | the same commands against two real public repositories | network |
| `agent` | a disposable agent that reads the skill and types what it says | network, node |

The last two have no tests yet; they arrive with
[T3](IMPLEMENTATION.md#t3---sources-resolution-cache-discovery) and
[T11](IMPLEMENTATION.md#t11---the-skill-and-the-rule). Their jobs exist already so the matrix
does not change shape on the day they do.

**Branch coverage of `src/` is gated at 100%, on the `unit` layer only.** The other layers run
the same code through a subprocess, where coverage cannot see it, so gating them on a
percentage would be measuring the harness. A `# pragma: no cover` is allowed when the same
line says why.

**Every test runs in a fake home.** `HOME`, `USERPROFILE` and every `XDG_*` point inside the
test's own directory, and the whole `GIT_` namespace is removed, so a bug cannot reach your
real config, cache or state directory and a fixture commit cannot land in this repository's
history. See `tests/fake_home.py` and `tests/git_environment.py`.

## Releases

Every pull request carries exactly one of the labels `major`, `minor`, `patch` or
`no-release`, and CI refuses one that does not. The version lives in `pyproject.toml` and is
written by the release job on merge, never by hand: a hand-bumped version disagrees with its
tag the first time somebody forgets, and every concurrent pull request touches the same line.

The one-off setup behind that is in [docs/release-setup.md](docs/release-setup.md).

## Conventions

- Prose follows the house style: British English, no em dash (use `-`), no `...` character,
  no `---` thematic breaks. Two pre-commit hooks check the mechanical half.
- Filenames are lowercase with no whitespace. Convention filenames (`README.md`, `LICENSE`,
  `Makefile`, `DESIGN.md`) are exempt.
- Text files use LF line endings, enforced in three layers: `.gitattributes`,
  `.editorconfig`, and the `mixed-line-ending` hook.
- No symlinks are committed. A Windows clone turns one into a text file holding a path.
- Every hook repository is pinned to a frozen SHA. Upgrades arrive as Dependabot diffs.

## Before you commit

```sh
prek run --all-files
```

The same suite runs in CI on every pull request.

By contributing you agree that your work is licensed under the repository's
[MIT License](LICENSE).
