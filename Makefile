SHELL:=/usr/bin/env bash

.PHONY: install
install:
	uv sync --all-groups
	uv run pre-commit install

.PHONY: lint
lint:
	uv run pre-commit run -a
	uv run mypy src/barra2_dl tests
	uv run deptry src

.PHONY: unit
unit:
	uv run pytest

.PHONY: package
package:
	uv lock --check
	uv pip check

.PHONY: test
test: lint package unit

.PHONY: docs-test
docs-test: ## Test if documentation can be built without warnings or errors
	uv run mkdocs build -s

.PHONY: docs
docs: ## Build and serve the documentation
	uv run mkdocs serve
