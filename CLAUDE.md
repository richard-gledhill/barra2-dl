# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`barra2-dl` is a Python library for bulk-downloading BARRA2 atmospheric reanalysis
point data (wind, temperature, etc.) from the Bureau of Meteorology's NCI THREDDS
server, then merging and converting it for wind resource / energy assessment use.
It's a data-download-and-transform pipeline, not a service: build URLs → download
CSVs in parallel → merge them → derive wind speed/direction from u/v components.

## Commands

Dependency management is via uv.

```bash
uv sync --all-groups     # install deps (run with `uv run <cmd>`)
make test                # lint + package check + unit tests (what CI runs first)
make lint                 # mypy barra2_dl tests; flake8 .; doc8 on docs (if installed)
make unit                 # uv run pytest
make package               # uv lock --check; uv pip check
```

Running things individually:

```bash
uv run pytest tests/test_download.py            # single test file
uv run pytest tests/test_download.py::test_name  # single test
uv run mypy barra2_dl tests                      # type check
uv run flake8 .                                  # wemake-python-styleguide + darglint lint
uv run ruff check --exit-non-zero-on-fix          # ruff lint (also run in CI, not in Makefile)
uv run ruff format --check --diff                 # ruff format check (also run in CI, not in Makefile)
```

Notes on test config (`setup.cfg` `[tool:pytest]`):
- `--doctest-modules` is enabled, so docstring doctests in `barra2_dl/*.py` are collected and run as tests too.
- Coverage flags are present but commented out — coverage is not enforced locally.
- `pytest-randomly` and `pytest-cov` are dev dependencies but not wired into default `addopts`.

CI (`.github/workflows/test.yml`) runs on Python 3.12–3.14 and additionally runs
`ruff check`, `ruff format --check`, and a `tests/test_integration.sh` script that
does not currently exist in the repo — expect that step to fail if triggered.

## Architecture

The package (`barra2_dl/`) is a thin, functional pipeline of independent modules
tied together only by `__init__.py` (`from . import convert, download, mapping, merge`).
There is no class-based orchestrator — callers (see `scripts/example_barra2_dl.py`
and the README example) chain these modules manually:

1. **`globals.py`** — static configuration: BARRA2 URL templates
   (`BARRA2_URL_AUS11_1HR`, `BARRA2_URL_AUST04_1HR`) with `.format()` placeholders
   for variable/year/month/lat/lon/time range; variable lists
   (`BARRA2_VAR_WIND_DEFAULT`, `BARRA2_VAR_WIND_50`); the `(ua, va, height)` tuples
   in `BARRA2_WIND_VARS` used later by `convert.py`; and `BARRA2_INDEX`, the join
   key columns (`time`, `station`, lat, lon) used by `merge.py`. Two datasets are
   supported: AUS-11 (BARRA-R2) and AUST-04 (BARRA-C2), each 1-hourly only.

2. **`download.py`** — turns a variable list + point + date range into
   `(url, filename)` pairs (`point_data_urlfilenames`), one URL per variable per
   month (BARRA2 stores each variable/month combination as a separate remote
   file), then fetches them via `download_serial` or `download_multithread`
   (thread pool sized `cpu_count() - 1`). Downloads are idempotent: an existing
   file on disk is skipped rather than re-fetched, so re-running a script resumes
   rather than re-downloads. HTTP failures are logged/printed, not raised.

3. **`merge.py`** — `merge_csvs_to_df` glob-reads all per-variable CSVs from a
   cache folder and outer-joins them on `BARRA2_INDEX` into one wide DataFrame,
   reconciling `_x`/`_y` suffix collisions from repeated joins
   (`_merge_suffix_columns`).

4. **`convert.py`** — post-processes the merged DataFrame: for each `(ua, va)`
   pair in `BARRA2_WIND_VARS` present as columns, derives wind speed (`v*`) and
   meteorological direction (`v*_phi_met`) from the u/v components and appends
   them as new columns (`convert_wind_components`).

5. **`mapping.py`** — geo helpers: `Latitude`/`Longitude` are `float` subclasses
   that validate range on construction (±90 / ±180); `LatLonPoint` and
   `LatLonBBox` are dataclasses built on top of them. `_generate_point_grid`,
   `_find_nearest_point`, and `_format_lat_lon` are draft/unused helpers (marked
   `Todo` in their docstrings) for a not-yet-implemented gridded/nearest-node
   workflow — don't assume they're wired into `download.py` yet.

End-to-end usage lives in `scripts/example_barra2_dl.py` (also as a Jupyter
notebook, `scripts/example_barra2_dl.ipynb`, via jupytext `#%%` cell markers):
build URLs → `download_multithread` into a cache dir → `merge_csvs_to_df` →
`convert_wind_components` → write output CSV.

## Conventions

- Requires Python ≥3.12; `download.py` uses 3.12+ `type` alias syntax
  (`type URLFilenamePair = tuple[str, str]`) and `match`/`case`.
- Style is enforced by `wemake-python-styleguide` (via flake8) plus `ruff` and
  `mypy --strict` (`setup.cfg`, `pyproject.toml`). Docstrings are Google-convention
  and checked by `darglint`; `--doctest-modules` means example code in docstrings
  must actually run.
- Private/internal helpers are prefixed `_` (e.g. `_download_file`,
  `_list_months`) and generally excluded from a module's `__all__`; public API
  surface of each module is declared explicitly via `__all__`.
- Logging: every module sets up `logger = logging.getLogger(__name__)` with a
  `NullHandler`, but user-facing progress messages are also duplicated to
  `sys.stdout.write` — match this dual pattern if adding output.
- `scripts/cache/` and `scripts/output/` hold example run artifacts (git-ignored
  working directories used by the example script), not source.
