# Plan: cache validation and csv metadata header (RFC-007)

Requirement: [RFC-007](../../../requirements/cache-validation-csv-metadata-prd.md). It goes before
[RFC-005](../../../requirements/gui-prd.md), whose SPEC, plan and todo are parked in
[`parked/2026-10-gui/`](../../parked/2026-10-gui/SPEC.md) and resume when this ships.

Spec: [SPEC.md](SPEC.md), written and approved 2026-10-31. One PR (`fix/cache-validation-csv-header`), branched from an up-to-date `main`, passing `make check`,
`make test` and `make docs-test`.

## Steps

Each step test-first.

1. **SPEC.** Done: Windographer pages read, `SPEC.md` written and approved.
2. **Cache validation.** `CacheMismatchError`, `_cached_file_problem(path, url)` for point csv, point netCDF,
   `average4` and area grids, and `_check_cache` over every cached file before any request (RFC-007 decision 9);
   tests from `tests/data/` with `requests.get` faked.
3. **Atomic write and empty responses** in `_download_file`; tests.
4. **csv header.** `write_csv` and `read_csv` with the header built from the Dataset attributes; `average4` average
   and node files; tests.
5. **Examples and docs.** The netCDF example pair (`.py` and `.ipynb` in step; the csv example stays raw), `docs/how-to-use.md`, `CONTEXT.md`
   (**Metadata header**, **Cache mismatch**), README line. ADR-003 refining ADR-002. The changelog is generated from
   commits.
6. **Verification.** Live test of `GridPointRequestedAt[...]` (`BARRA2_LIVE=1`); `make check`, `make test`,
   `make docs-test`; the owner's manual Windographer import.

Risks: NCSS changing the `GridPointRequestedAt` string (the live test watches it); a slow rerun over a large cache
(one metadata read per file; measure on a year of data); notebooks reformatting unrelated cells on jupytext sync.

## Next

Archive this plan into `archive/2026-NN-cache-validation/`, set RFC-007 to Done, then move the parked RFC-005 files
back into `plan/` and update them as their parked note says.
