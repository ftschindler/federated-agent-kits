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

## Run the full pre-commit guard suite against all files
check: | guard-uvx
	uvx prek run --all-files

## Install the pre-commit hooks into this clone
bootstrap: | guard-git guard-uvx
	uvx prek install

.PHONY: help check bootstrap
