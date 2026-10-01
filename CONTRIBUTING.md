# Contributing

## System requirements

[uv](https://docs.astral.sh/uv/), git, and node. Nothing else, on Linux, macOS or Windows.

## Bootstrap

```sh
make bootstrap   # install the pre-commit hooks into this clone
make check       # run the full guard suite over every file
```

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
