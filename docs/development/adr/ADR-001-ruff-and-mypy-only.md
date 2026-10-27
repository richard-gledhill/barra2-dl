# ADR-001: Style is enforced by ruff and mypy alone

Status: Accepted (recorded retroactively from `AGENTS.md`; the original reasoning was not written down)

## Context

The project previously used wemake-python-styleguide, flake8 and nitpick alongside ruff. They were removed and ruff
took over lint and format.

## Decision

Lint and formatting are enforced by `ruff` (`check` and `format`, configured only in `pyproject.toml`), with `mypy`
for types and `deptry` for dependencies, all run through `pre-commit` and `make check`.

## Consequences

- One config file and one tool for style.
- Docstrings are checked for presence and format only (ruff's `D` rules). There is no darglint equivalent verifying
  that `Args`/`Returns` match the real signature.
