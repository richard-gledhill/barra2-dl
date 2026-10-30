Status: Draft

# Package structure review before RFC-005: core and interface layers

| | |
|---|---|
| Reviewed | 2026-10-31, against `main` at `be784c0` and the uncommitted RFC-005 plan (`plan/SPEC.md`, `plan.md`, `todo.md`) |
| Questions | 1. Should `src/` be refactored into a `core` module holding the runtime code and a `gui` module that is purely an interface layer? 2. Would that suit a future CLI or API better? |
| Taken up in | [RFC-007](cache-validation-csv-metadata-prd.md) (finding 5.1, the cache location) and [RFC-005](gui-prd.md) 5.7 and section 9 (the rest), 2026-10-31 |
| Relates to | [RFC-005](gui-prd.md) (GUI and engine), the deferred CLI in the [roadmap](wind-engineering-roadmap-prd.md#31-cli-deferred) and the [backlog](../backlog.md) |

## 1. Summary

- **Yes to the separation, no to a `core` folder.** The top-level `barra2_dl` package already *is* the core: five
  functional modules with no interface code in them. Moving them into `barra2_dl/core/` would add a path segment and
  break every `barra2_dl.download` / `barra2_dl.globals` import in the README, the docs, both example pairs, the
  mkdocstrings page and the tests (37 references in the README and user docs alone), without creating any boundary
  that doesn't exist today. It fails the deletion test in [conventions.md](../conventions.md).
- **The boundary that matters is the dependency direction, plus the engine.** Keep the domain modules at the top
  level, add `project.py` as the engine (as RFC-005 already plans), put the GUI in `barra2_dl/gui/` behind the `gui`
  extra, and later the CLI in `barra2_dl/cli.py`. Interfaces import only public API; nothing in the core imports an
  interface. Enforce this with a test, not a folder name.
- **This is better for a CLI or API, and the gain comes from `project.py`.** With a shared engine the CLI is about
  100 lines of `argparse`, and an HTTP API (a non-goal today) would be a thin job wrapper. Without one, each interface
  would rebuild the pipeline, which is the atl3b fork's main defect.
- **Seven changes to slice 1 make the engine fit all three interfaces** (section 5). The most important is that the
  cache filenames for `nearest` and `average4` don't encode the location, so a GUI user who moves a site and reruns
  with the same name silently gets the old location's data (5.1).

## 2. What the code looks like today

| Module | Lines | Role | Imports from the package |
|---|---|---|---|
| `globals.py` | 155 | Configuration: URL templates, inventory (`BARRA2_VARS`), presets, domains, frequencies, node selections | none |
| `mapping.py` | 292 | Geo types (`LatLonPoint`, `LatLonBBox`), distance and weights; draft unwired helpers | none |
| `download.py` | 618 | URL building (pure), version lookup, serial and threaded fetch | `globals`, `mapping` |
| `merge.py` | 902 | csv and netCDF merge into DataFrame or CF Dataset; Dataset to frames | `globals`, `mapping`, `convert` |
| `convert.py` | 226 | Wind speed and direction, unit conversion | `globals` |

The dependency graph is acyclic and points one way (`globals` ← `mapping` ← `download`/`merge`/`convert`). There is
no class-based orchestrator, no global mutable state beyond the import-time inventory, and no UI concern in any
module except the `sys.stdout.write` progress lines (14 in all, 10 of them in `download.py`).

What's missing for an interface layer is the layer between the building blocks and a caller. Today the example
script is that layer: it builds the URLs, downloads, resolves versions, reconstructs the fixed-field filename
(`fixed_name`), the merge pattern and the output filenames by hand, and writes the files. Any GUI or CLI would have
to repeat all of that. RFC-005 slice 1 (`project.py`, `run_site`) is exactly the fix.

## 3. Options

| | A. Top-level core + interface subpackages (recommended) | B. `barra2_dl/core/` + `barra2_dl/gui/` | C. Separate distributions (`barra2-dl`, `barra2-dl-gui`, uv workspace) |
|---|---|---|---|
| Layout | `barra2_dl/{globals,mapping,download,merge,convert,project}.py`, `barra2_dl/gui/`, later `barra2_dl/cli.py` | All runtime modules moved under `core/` | Two packages, two `pyproject.toml`, the GUI depending on the library |
| Public imports | Unchanged | All change (or re-exported twice, giving two import paths for every name) | Unchanged for the library |
| Boundary | Dependency rule + test + `gui` extra | Folder name; the dependency rule and test are still needed | Hard: the library can't import the GUI |
| Dependencies | Toolkit only in `[gui]` extra | Same | Toolkit only in the GUI package |
| Cost | None beyond RFC-005's plan | Moves 5 modules, rewrites docs, scripts, notebooks, tests, mkdocstrings; churns git blame | Second release pipeline, version pinning between the two, CI for both |
| Fits conventions | Yes ("thin, functional pipeline of independent modules tied together by `__init__.py`") | Adds a layer the deletion test removes | Overkill for one maintainer and one GUI |

**Recommendation: A.** Revisit C only if the GUI needs its own release cadence, or the toolkit's dependency pins
start to conflict with the library's (for example a Streamlit release that caps `numpy` or `pandas`). The `gui` extra
gives the same install-time isolation until then.

B would be worth it only if the top level filled up with interface modules and a reader could no longer tell the
library from the front ends. With one `gui/` subpackage and one `cli.py`, that doesn't happen.

## 4. Proposed layering

```text
interfaces   scripts/ + notebooks     barra2_dl/gui/ ([gui] extra)     barra2_dl/cli.py (later)     HTTP API (non-goal)
                    \                         |                              |                          /
engine                         barra2_dl/project.py: Settings, Site, Project, validate, load_project,
                               plan_site, run_site, SiteResult, run summary
                                              |
library                download.py      merge.py      convert.py      mapping.py (nearest_nodes)
                                              |
config                                   globals.py
```

```text
src/barra2_dl/
    __init__.py      exports convert, download, mapping, merge, project (not gui or cli)
    globals.py
    mapping.py
    download.py
    merge.py
    convert.py
    project.py       the engine, RFC-005 slice 1
    gui/             RFC-005 slice 4; entry point barra2-dl-gui = "barra2_dl.gui:main"
        __init__.py  main(): starts the toolkit
        app.py       toolkit code only
    cli.py           later; entry point barra2-dl = "barra2_dl.cli:main"
```

**Rules**

1. An interface imports only names in a module's `__all__` (and `globals` constants). No `_` helpers.
2. No module outside `gui/` imports `barra2_dl.gui` or a GUI toolkit; `import barra2_dl` works without the `gui`
   extra installed.
3. Anything two interfaces would both need lives in the engine or library, not in `gui/`. That includes turning
   input into `Settings`/`Site`, validation, mast-list CSV import, output naming, and the download preview. `gui/`
   holds only widgets, layout, state and threading for its toolkit.
4. The engine reports through return values, callbacks and logging. Interfaces decide what the user sees.

**Enforcement, without a new dependency** (`import-linter` would be a new dev dependency and need the owner's
approval):

- A test in `tests/test_package.py` that runs `import barra2_dl` in a subprocess and asserts no `barra2_dl.gui`,
  `barra2_dl.cli` or toolkit module is in `sys.modules`.
- A test that parses `gui/` and `cli.py` with `ast` and asserts every `from barra2_dl.<module> import <name>` names
  a member of that module's `__all__`, and that no core module imports `barra2_dl.gui` or `barra2_dl.cli`.

### 4.1 Fit for each interface

| Interface | Needs from the engine | With layer A |
|---|---|---|
| GUI | Settings from a form, live validation per field, node preview, download preview, background run with progress and cancel, a result to display | All in `project.py` / `mapping.py`; `gui/` is toolkit code and a smoke test |
| CLI | Settings from flags or a TOML file, `--dry-run`, quiet/verbose output, exit codes, Ctrl-C | About 100 lines: `argparse` → `site_from_dict` → `run_site`; Ctrl-C sets the cancel event; exit code from `SiteResult.status` |
| Python API (scripts, notebooks) | The library as now, plus one call per site | `run_site` in a loop; the step-by-step cells still show what's underneath |
| HTTP API (non-goal) | Validation errors as data, long runs as jobs, results as JSON | Problems map to a 422 body, `run_site` runs in a worker with the cancel event, the run summary JSON is the response. The job store is API-layer work. If an HTTP API ever matters, note in the toolkit ADR that NiceGUI runs on FastAPI and could share a server, and Streamlit can't |

## 5. Changes recommended to slice 1 (engine)

These are review findings against the current SPEC. None changes an RFC-005 decision; each is for the owner to
accept before the SPEC is updated.

### 5.1 Put the location in the cache key (bug risk, highest priority)

`point_data_urlfilenames` names files `<prefix>_<domain>_<freq>[_average4]_<var>_<start>_<end>.<ext>`, with no
latitude or longitude. Downloads are idempotent, so an existing file is skipped. In the GUI the prefix is the site
name, so a user who drags a site's pin and reruns gets the cached months from the old location, merged without error
(the merge only fails if *both* locations' months are present, as "more than one node"). Area files don't have this
problem because the box is in the name.

Options:
- (a) Add the rounded requested location to point and `average4` filenames, as areas already do. Simple and
  visible; changes cache names, so existing caches are re-downloaded once (acceptable before 1.0; note it in the
  changelog).
- (b) `run_site` uses a per-site cache subfolder keyed by a hash of the location and settings. Hides the names; the
  RFC already liked per-node cache folders (3.3).
- (c) `run_site` checks the merged node against the requested point and fails the site if it's further than one grid
  spacing. A safety net, not a fix; worth adding with (a) or (b).

Proposed: (a) plus (c).

### 5.2 Split parsing from validation, and make problems structured

The SPEC has `load_project(path)` validate everything and raise `ProjectError` with `.problems: list[str]`. A GUI
form, CLI flags and an API body all need the same validation without a file. Proposed:

- `project_from_dict(data, base_dir)` and `site_from_dict(data, settings)`: build the dataclasses from plain data.
  `load_project(path)` becomes `tomllib.load` + `project_from_dict`, so a form, flags and a file share one code path.
- `validate(settings, site) -> list[Problem]`, public, with `Problem(site: str | None, key: str, message: str)`.
  The GUI marks the field named by `key` as the user types and disables invalid combinations (RFC G3); the CLI
  prints them; an API returns them as JSON. `ProjectError.problems` holds the same `Problem`s.

### 5.3 One source for the choices

The GUI's dropdowns and the CLI's `choices=` must come from the library, not be retyped. `BARRA2_FREQS`,
`BARRA2_PRESETS` and `BARRA2_NODE_SELECTIONS` already exist; add the output formats (`csv`, `netcdf`) as a constant
beside them, and `Literal` type aliases for node selection, format and the `FileResult`/`SiteResult` statuses, so mypy
catches a misspelt `'averge4'` in interface code.

### 5.4 A public download preview

`plan_site(site, settings) -> list[URLFilenamePair]` (or the count and which are already cached). URL building is
pure, so it costs nothing. The CLI's `--dry-run` needs it, and the GUI can show "this run downloads 1,240 files,
310 already cached" before the user starts. It passes the deletion test: two callers.

### 5.5 Who writes to stdout

The conventions require every user-facing progress message to be written to `sys.stdout` as well as logged. Inside
the engine that becomes a problem: a GUI worker thread prints one line per file to the server console, and a CLI
can't offer `--quiet`. RFC-005's progress callback already covers the GUI's needs.

This touches [conventions.md](../conventions.md), which only the owner changes. Options for the owner:
- keep the dual pattern in the library functions, and have `run_site` and interfaces rely on the callback (stdout
  noise in the GUI console is tolerated);
- amend the convention so that the library and engine log only, and interfaces (example scripts, CLI) write to stdout
  or attach a logging handler;
- add a `verbose` argument to the download functions, defaulting to today's behaviour.

### 5.6 Results as the contract between engine and interfaces

`SiteResult` and the run summary should serialise through one function (the summary writer), so the GUI's
end-of-run view, the CLI's exit code and any API response read the same structure. `schema_version` is already in
the SPEC; keep it, because the summary becomes a public format the moment a second interface reads it.

### 5.7 Smaller items

- `mapping.py` and `globals.py` have no `__all__`, against the conventions, and `test_package.py` checks only
  `convert`, `download` and `merge`. The boundary test in section 4 relies on `__all__`, so add them (and `project`)
  in slice 1 or 2.
- `merge` functions type folders as `str`; accept `str | Path`, since `Settings.cache` will be a `Path`.
- `run_site` will run on a GUI worker thread and start its own download pool. That's fine; record in the SPEC that it
  holds no module-level state, so two sites can't share anything by accident, and that cancel is the only
  cross-thread signal. For Streamlit, keeping the worker thread and `threading.Event` in session state across reruns
  is a spike criterion (RFC 5.2).
- `project.py` will hold dataclasses, TOML parsing, validation, the run and the summary. If it grows past about
  600-800 lines (`merge.py` is 902), split the summary writer or the validation into their own module then, not
  before.

## 6. Effect on the plan

- No change to the slice order. The structure in section 4 is what RFC-005 7.4 already says
  (`src/barra2_dl/gui/` calling only public API); this review makes the rule explicit and testable.
- Slice 1 grows by 5.1-5.6 and the `__all__` additions; the SPEC's "Changes" and "Tests" sections need updating once
  the owner decides.
- Slice 4 gains the two boundary tests.
- The deferred CLI stays deferred; with 5.2-5.4 in place its backlog estimate (about 100 lines) holds.
- An ADR is worth writing once decided: "Interfaces are thin layers over a top-level library and `project.py`
  engine" (ADR-003), so a later contributor doesn't reopen the `core/` question.

## 7. Decisions for the owner

1. Layout A (top-level core, `gui/` subpackage, later `cli.py`), not a `core/` folder or a separate distribution.
2. Location in the cache key: (a) filenames, (b) per-site folders, or (c) a check only; proposed (a) + (c).
3. Structured `Problem`s and the `project_from_dict` / `site_from_dict` / `validate` split (5.2).
4. A public `plan_site` download preview (5.4).
5. The stdout convention inside the engine (5.5); a `conventions.md` change if you choose the second option.
6. The two boundary tests, using the standard library rather than `import-linter`.
7. ADR-003 recording the layering.
