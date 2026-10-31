# ADR-004: Library first, with interfaces beside it and one engine path

Status: Accepted (RFC-005, section 9 answers of 2026-10-31)

## Context

RFC-005 adds a GUI, and a command-line tool and an HTTP API are possible later. Each would otherwise rebuild the
download, merge and output pipeline, which was the main defect of the fork the feature was raised in. The
[package structure review](../requirements/package-structure-review-prd.md) asked whether `src/` should be split into a
`core` module and a `gui` module that is purely an interface layer.

## Decision

- **Layout.** The top-level package is the core. Interfaces are subpackages or modules beside it: `gui/` (the `gui`
  extra, entry point `barra2-dl-gui`) and later `cli.py`. No `core/` folder, because moving the library would change
  every public import without adding a boundary. A separate `barra2-dl-gui` distribution is revisited only if a
  toolkit's dependency pins conflict with the library's.
- **One engine path.** `project.py` is the engine. `project_from_dict`, `site_from_dict`, `load_project` and a form all
  build the same `Settings` and `Site` dataclasses; `validate` returns `Problem`s as data; `plan_site` previews a run;
  `run_site` runs it; `site_result_to_dict` is the one serialiser of the result and the run summary. Choices come from
  the library (`BARRA2_FREQS`, `BARRA2_PRESETS`, `BARRA2_NODE_SELECTIONS`, `BARRA2_OUTPUT_FORMATS`,
  `BARRA2_DOWNLOAD_FORMATS`, and `Literal` aliases), never retyped in an interface.
- **Rules**, each checked by a standard-library test in `tests/test_package.py`:
  1. An interface imports only names a module lists in `__all__`, plus constants from `globals`. `mapping` and `globals`
     gain `__all__` for this.
  2. No library or engine module imports `barra2_dl.gui`, `barra2_dl.cli` or a GUI toolkit, so `import barra2_dl`
     works without the extra.
  3. Anything two interfaces would need lives in the engine or library: building settings from input, validation,
     output naming, the download preview. `gui/` holds only widgets, layout, state and threading.
  4. The engine reports through return values, the progress callback and logging; interfaces decide what the user sees.

## Alternatives considered

- A `core/` folder: churn in every import for no new boundary.
- A separate GUI distribution now: two release trains for one author, and no dependency conflict to justify it yet.
- `import-linter` for the rules: a new dev dependency for four checks the standard library can make.
- A class-based orchestrator: the conventions keep the package functional, and `run_site` passes the deletion test as a
  function.

## Consequences

- The deferred CLI is about 100 lines: `argparse` to `site_from_dict` to `run_site`, Ctrl-C setting the cancel event,
  the exit code from `SiteResult.status`.
- Console output stays the dual pattern (log and print) for now; from a GUI worker thread it adds server-console noise,
  so the GUI relies on the progress callback, and the convention is revisited when the GUI skeleton is built.
- An HTTP API remains a non-goal. If wanted, it wraps `run_site` in a job runner, and the toolkit ADR notes that NiceGUI
  runs on FastAPI and Streamlit cannot share a server.
