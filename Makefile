SHELL:=/usr/bin/env bash

.PHONY: install
install:
	uv sync --all-groups
	uv run pre-commit install

.PHONY: lint
lint:
	uv run mypy src/barra2_dl tests
	uv run flake8 .
	if uv run command -v doc8 > /dev/null 2>&1; then uv run doc8 -q docs; fi

.PHONY: unit
unit:
	uv run pytest

.PHONY: package
package:
	uv lock --check
	uv pip check

.PHONY: test
test: lint package unit
