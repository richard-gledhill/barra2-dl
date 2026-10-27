# ADR-002: One remote file per variable per month, downloads are idempotent

Status: Accepted (recorded retroactively from the code and `AGENTS.md`)

## Context

BARRA2 stores each variable and month as a separate remote file on the NCI THREDDS server, and the NetCDF Subset
Service returns one point time series per request. A multi-year, multi-variable download is many requests and can
fail part way.

## Decision

`point_data_urlfilenames` builds one `(url, filename)` pair per variable per month. `download_serial` and
`download_multithread` fetch them, skipping any file already in the cache folder. HTTP failures are logged and
printed, not raised. `merge_csvs_to_df` then outer-joins the cached CSVs on `BARRA2_INDEX`.

## Alternatives considered

- Request the whole period per variable in one call: not possible, the remote files are monthly.
- Raise on HTTP failure: would abort a long parallel run on one bad month.

## Consequences

- Re-running a script resumes rather than re-downloads.
- A failed month is silently absent from the cache until the next run, so callers should check the cache is complete.
- A partially written or empty file would be treated as complete (see the backlog item on validating recent files).
