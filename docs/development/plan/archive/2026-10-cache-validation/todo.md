# Todo: cache validation and csv metadata header (RFC-007)

## RFC-007 (shipped in #143) (`fix/cache-validation-csv-header`)
- [x] Owner decisions on RFC-007 section 8 (2026-10-31)
- [x] Read Windographer WIS and Configure Dataset pages; write `SPEC.md` (2026-10-31)
- [x] Owner approves the SPEC's decisions (2026-10-31)
- [x] `CacheMismatchError`, `_cached_file_problem`, `_check_cache` before any request; tests
- [x] Atomic write and empty-response failure; tests
- [x] `write_csv` / `read_csv` with metadata header; tests
- [x] netCDF example pair, how-to-use, `CONTEXT.md`, README, ADR-003
- [x] Live test; `make check`, `make test`, `make docs-test`
- [ ] Manual Windographer import (owner): moved to the backlog; record in `testing/manual-checks.md`
- [x] PR (#143)

## Then: RFC-005 (parked in `plan/parked/2026-10-gui/`)
- [x] Archive RFC-007 plan
- [ ] Move RFC-005 files back; apply their parked note; resume slice 1
