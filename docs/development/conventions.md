# Conventions

The judgement-based style guide for this project. Agents read it before writing code (see [AGENTS.md](../../AGENTS.md)).

`constraints.md` is the measured, enforced bar (lint, types, coverage). This file is the style guide that tools
can't check. A new rule belongs here if it is a judgement call, and in `constraints.md` if a tool enforces it.
Only the owner changes either file.

**Design**
- The package is a thin, functional pipeline of independent modules (`download` → `merge` → `convert`, with
  `mapping` for geo helpers), tied together only by `__init__.py`. Don't add a class-based orchestrator.
- Before adding a module, apply the deletion test: if removing it would just move one line into its callers,
  don't add it.
- Add a seam (a `Protocol` or swappable adapter) only where something actually varies. One implementation is not a seam.
- Draft helpers (`_generate_point_grid`, `_find_nearest_point`, `_format_lat_lon`) are unwired. Don't assume they are
  used by `download.py`.

**Code**
- Public API of each module is declared in `__all__`. Internal helpers are prefixed `_` and left out of it.
- Docstrings are Google style (`Args:`/`Returns:`/`Raises:`); `mkdocstrings` renders them. Doctest examples in
  docstrings must run, because `--doctest-modules` collects them.
- Use the [CONTEXT.md](../../CONTEXT.md) terms in code, docs and commits; add a term there when you introduce a
  domain concept.
- Every module sets `logger = logging.getLogger(__name__)` with a `NullHandler`. User-facing progress is also
  written to `sys.stdout.write`; match this dual pattern when adding output.
- HTTP failures are logged and printed, not raised. Downloads are idempotent: an existing file is skipped.
- Single quotes (enforced by `ruff format`), line length 120.
- `download.py` uses Python 3.12 syntax (`type` aliases, `match`/`case`); don't downgrade it.

**Module layout**
- Order a module like this, omitting what it doesn't have:
  1. Module docstring.
  2. Imports: standard library, third-party, local (`ruff` sorts them).
  3. `logger` setup, then module dunders (`__all__`). These go after the imports, unlike PEP 8, which puts them
     before; it matches `convert.py`.
  4. Constants and types: constants, type aliases, `Protocol`s and plain data models (dataclasses). Code further
     down uses them in signatures.
  5. Errors: custom exceptions.
  6. Public API: the functions and classes other modules import. High up, so a reader sees what the module offers
     first.
  7. Helpers: `_`-prefixed, module-private functions, kept last as implementation detail.
- Order matters only for names used at import time (constants, decorators, default arguments, class bodies): those
  must be defined above their use. A function body can call a helper defined below it.
- In a module of about 150+ lines with at least three of sections 4-7, wrap each in `# region <name>` ...
  `# endregion` (PyCharm and VS Code fold them), using exactly these names: `Constants and types`, `Errors`,
  `Public API`, `Helpers`. Shorter modules get no regions. Don't use `# ---` divider comments.
- A test file mirrors its module. It opens with a `Test helpers` region (shared constants, builders, fakes,
  fixtures; a helper used by one section stays in that section). Then come regions in the module's order with the
  module's names. Inside `Public API`, nest one region per function or class under test, or per behaviour when one
  class has many tests. If the module has no regions, use one top-level region per function, class or behaviour.
  Keep a decorator (`@pytest.mark.parametrize`) with its test, never a region marker between them. Package-level
  tests that don't mirror a module (`tests/test_package.py`) get no regions.

**Tests**
- Use `tmp_path`. No network in the default suite: fake `requests.get` and test through the public functions. Tests
  that need the real THREDDS server are skipped unless `BARRA2_LIVE=1`.
- Test files mirror their module (`tests/test_<module>.py`). Name tests `test_<subject>_<scenario>`, in the present
  tense.
- Parametrize with `pytest.mark.parametrize`. Pin a known bug as a strict `xfail` with a reason that names it; don't
  skip or delete the test.
- Tests must be order-independent: `pytest-randomly` shuffles them on every run.

**Git**
- Branches are `<type>/<short-description>` with a Conventional Commits type (`feat`, `fix`, `chore`, `docs`,
  `style`, `refactor`, `perf`, `test`, `build`, `ci`, `revert`); a workflow checks this, advisory only.
- `scripts/cache/` and `scripts/output/` hold example run artefacts and are git-ignored.
