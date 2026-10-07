.DEFAULT_GOAL := help

## Show available targets
help:
	@grep -B1 '^[a-z][a-z_-]*:' $(MAKEFILE_LIST) \
		| grep -A1 '^##' \
		| awk '/^##/{d=substr($$0,4)} /^[a-z]/{split($$0,a,":"); printf "  %-20s %s\n", a[1], d}'

# Fail early with an actionable message when a required tool is missing, rather
# than letting a recipe die halfway with a cryptic "command not found". Each
# target lists the binaries it assumes as `guard-<tool>` order-only prereqs.
guard-%:
	@command -v $* >/dev/null 2>&1 || { \
		printf 'error: required tool %s not found on PATH.\n' '$*' >&2; \
		printf 'See CONTRIBUTING.md > System requirements for how to install it.\n' >&2; \
		exit 1; \
	}

## Run every test layer that does not need an API key
test: test_unit test_cli

# Each layer is one call into .scripts/run-tests.py, which composes the `uv`
# invocation in Python. Doing it here would make `make` and a POSIX shell
# prerequisites of running the tests at all, and the script runs the same on
# Windows, where make usually is not installed.

## Test the library in-process; this is the layer the coverage gate applies to
test_unit: | guard-uv
	uv run .scripts/run-tests.py unit

## Test `akit` as a subprocess in a fake home (needs git)
test_cli: | guard-git guard-uv
	uv run .scripts/run-tests.py cli

## Test `akit` against two real public repositories (needs network)
test_federation: | guard-git guard-uv
	uv run .scripts/run-tests.py federation

## Test the skill by driving a disposable agent (slow, needs network + node)
test_agent: | guard-node guard-uv
	uv run .scripts/run-tests.py agent

## Build the wheel and the sdist into dist/
build: | guard-uv
	uv build --out-dir dist

## Run the full pre-commit guard suite against all files
check: | guard-uvx
	uvx prek run --all-files

## Install the pre-commit hooks into this clone
bootstrap: | guard-git guard-uvx
	uvx prek install

.PHONY: help test test_unit test_cli test_federation test_agent build check bootstrap
