# Backlog

Deferred work and known bugs, not yet scheduled. Pick an item up by following the flow in
[README.md](README.md); remove it here when it ships. Known bugs are pinned by strict `xfail` tests, which will
fail loudly once the bug is fixed, so remove the `xfail` in the same change.

## Known bugs

| Item | Detail | Pinned by |
|---|---|---|
| `None_` filename prefix | `point_data_urlfilenames(..., fileout_prefix=None)` produces filenames starting `None_`. | `tests/test_download.py::test_point_data_urlfilenames_default_prefix` |

## Manual checks owed

- Windographer import of a nearest-node and an `average4` csv with the metadata header (RFC-007 acceptance). Follow
  [`testing/manual-checks.md`](testing/manual-checks.md) and record the result in its table. If Windographer doesn't
  read the location, time step or time zone, take it to RFC-006.

## Deferred features (from existing `Todo` notes)

- Reuse a covering file for a `nearest_nodes` lookup of a nearby point (today each distinct point has its own pair of
  small files in `<cache>/nodes`).
- Download only new data using the existing time range (`_list_timestamp_range`), with a validity check for files
  downloaded in the last three months.
- Default `fileout_prefix` and naming files by BARRA2 node.
- Checks for mismatched or multiple suffixed columns in `_merge_suffix_columns`, and for missing `ua`/`va` pairs in
  `convert_wind_components`.

## Deferred features (from the RFC roadmap)

- Command-line tool (`barra2-dl point …`, `barra2-dl run project.toml`), from the dropped RFC-004. The design notes
  are in the roadmap's section 3.1: `argparse`, subcommands, `--dry-run` and exit codes. Build it on RFC-005's engine
  (`run_site`, `load_project`) if users need headless or scheduled runs, for example on NCI Gadi.

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
