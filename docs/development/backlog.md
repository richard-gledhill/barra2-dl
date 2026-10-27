# Backlog

Deferred work and known bugs, not yet scheduled. Pick an item up by following the flow in
[README.md](README.md); remove it here when it ships. Known bugs are pinned by strict `xfail` tests, which will
fail loudly once the bug is fixed, so remove the `xfail` in the same change.

## Known bugs

| Item | Detail | Pinned by |
|---|---|---|
| `ua300m` unit typo | `BARRA2_WIND_VARS` has `('ua300m', 'va300m', '30m[unit="m s-1"]')`; the height should be `300m`. The third tuple field is not used by `convert.py` today. | `tests/test_globals.py::test_wind_vars_pairs_are_consistent[ua300m]` |
| Tuple bounds crash | `_generate_point_grid` validates a 4-tuple `(north, south, east, west)` as its docstring promises, then indexes it by key and raises `TypeError`. Unwired helper. | `tests/test_mapping.py::test_generate_point_grid_tuple` |
| `None_` filename prefix | `point_data_urlfilenames(..., fileout_prefix=None)` produces filenames starting `None_`. | `tests/test_download.py::test_point_data_urlfilenames_default_prefix` |
| `uas`/`vas` output name | `convert_wind_components` names the 10 m surface wind output `vs[unit="m s-1"]` (it slices the first two characters of `uas`). | `tests/test_convert.py::test_convert_wind_components_surface_wind_column_name` |

## Deferred features (from existing `Todo` notes)

- Gridded / bounding-box download and nearest-node workflow (`mapping.py` helpers, `LatLonBBox` constants in
  `globals.py`, grid netCDF output).
- Download only new data using the existing time range (`_list_timestamp_range`), with a validity check for files
  downloaded in the last three months.
- Default `fileout_prefix` and naming files by BARRA2 node.
- Additional output types beyond `csv_file`.
- Checks for mismatched or multiple suffixed columns in `_merge_suffix_columns`, and for missing `ua`/`va` pairs in
  `convert_wind_components`.

## Tooling and process (from the scratch-cookiecutter-uv template review)

- Set a coverage threshold (`fail_under`) now that coverage is 100%.
- Turn on `disallow_untyped_defs` in mypy, module by module.
- After the CI gate PR merges, update the `main` branch ruleset to require only `ci-ok`.
- Enable "Automatically delete head branches" in the repository settings.
- Add `tox.ini` with `tox-uv` for local multi-version runs (CI's matrix already covers this).
- Ruff niceties from the template: `fix = true`, explicit `target-version`, `format.preview`.
- Add the `pretty-format-json` pre-commit hook if JSON files are added.
- Add the template's `.claude/hooks/guard_docs.py` PreToolUse hook to enforce the development-docs paths and protect
  `conventions.md` and `constraints.md` from agent edits.
