# Constraints

The measured, tool-enforced quality bar for this project. Read it before writing code. The judgement-based style
guide is [conventions.md](conventions.md); a rule a tool checks belongs here.

Only the owner changes this file. Never weaken it to make a change pass.

## Gates

A change is done only when both pass on a clean tree:

- `make check`: `uv lock --locked`, `pre-commit run -a` (file hygiene, `ruff check`, `ruff format`),
  `mypy src/barra2_dl tests`, `deptry src` and `uv pip check`.
- `make test`: `pytest --doctest-modules --cov --cov-report=term-missing` (coverage is reported, not enforced).

CI runs these as the `quality` and `tests-and-type-check` jobs, plus `check-docs` (`mkdocs build -s`). The `ci-ok`
job aggregates them and is the only check the branch ruleset should require.

## Supported versions

Python 3.12, 3.13 and 3.14, all exercised by the CI matrix. `requires-python` is `>=3.12,<4`.

## Type checking

mypy is configured in `pyproject.toml`: `check_untyped_defs`, `disallow_any_unimported`, `no_implicit_optional`,
`warn_return_any`, `warn_unused_ignores`, `show_error_codes`. `disallow_untyped_defs` is off; see the backlog.

## Lint and security

`ruff` config lives only in the root `pyproject.toml`: line length 120, single quotes, Google docstring convention.
Rule families: `A`, `B`, `C4`, `C90`, `D`, `E`, `F`, `I`, `N`, `PGH`, `RUF`, `S`, `SIM`, `T10`, `TRY`, `UP`, `W`,
`YTT`. `S101` is allowed in `tests/`.

## Dependencies

Runtime dependencies are only what the library imports. Tooling, type stubs and notebook kernels live in the `dev`
group, and documentation tooling in `docs`. `deptry src` must be clean without ignores.

## Never silence a check

- Fix the code, not the check.
- No `# type: ignore`, `# noqa`, `SKIP=` or `--no-verify`, and no loosening the mypy, deptry, ruff or pre-commit
  config, unless the owner asks for it.
- Never skip, delete or weaken a test. A known bug is pinned as a strict `xfail` naming its backlog entry, not
  skipped.
- Add or update tests for any behaviour you change.

## Coverage

Coverage is measured with `pytest-cov` (`[tool.coverage.*]` in `pyproject.toml`, branch coverage on `src`) and is
100% today. TODO: no threshold is enforced yet. Set one (for example `fail_under = 100` under
`[tool.coverage.report]`) and record it here.
