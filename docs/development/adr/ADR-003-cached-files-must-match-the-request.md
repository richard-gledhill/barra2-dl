# ADR-003: Cached files must match the request

Status: Accepted (refines [ADR-002](ADR-002-per-variable-month-idempotent-downloads.md); RFC-007)

## Context

ADR-002 skips any file already in the cache folder. Point and `average4` filenames hold the site name but not its
coordinates, so a site that moves but keeps its name reuses the old location's data with no error. ADR-002 also notes
that a partly written or empty file is treated as complete. Every cached file does record where it came from: point
csv and netCDF files hold `GridPointRequestedAt[<lat>_<lon>]`, grids hold their `lat`/`lon` axes and bounds.

## Decision

Before any request, `download_serial` and `download_multithread` check every cached file against its url
(`_check_cache`). A point must have been requested at the same location (within 0.0005°, longitudes compared on -180 to
180), an `average4` grid must have nodes around the box centre, an area grid must cover the box, and a file that can't be
read fails. If any file fails, one `CacheMismatchError` lists them all, saying to rename the site or delete the files,
and nothing is downloaded. Urls with no location are not checked. Writes go to `<name>.part` and are renamed, and an
empty 200 response is a failure, so the final name only holds a complete response.

HTTP failures are still logged and printed, not raised (ADR-002). `CacheMismatchError` is the only new exception, and it
is raised before any request.

## Alternatives considered

- Put the coordinates in the filename: changes every cache name and strands existing caches.
- Rewrite or overwrite a mismatched file: loses data the user may want, and surprises them. The user decides.
- A manifest or database beside the cache: a second record that can disagree with the files, which already describe
  themselves.
- Skip the check for speed: it reads one line of each csv or the metadata of each netCDF; the risk is a slow re-run over a
  very large cache, which is measured rather than assumed.

## Consequences

- Moving a site without renaming it fails fast and says how to fix it.
- Existing caches stay valid where they match; filenames and cache contents don't change.
- A re-run over a large cache opens each cached file once.
- If NCSS changes the `GridPointRequestedAt` format, files read as unreadable; the live test pins the format.
