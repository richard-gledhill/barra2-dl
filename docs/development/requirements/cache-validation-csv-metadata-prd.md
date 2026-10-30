Status: Draft

# RFC-007: Cache validation and csv metadata header

| | |
|---|---|
| Raised by | The [package structure review](package-structure-review-prd.md) (5.1), 2026-10-31 |
| Depends on | [RFC-003 netCDF output](netcdf-output-prd.md) (Done): its Dataset attributes are what the csv header mirrors |
| Goes before | [RFC-005 GUI](gui-prd.md). Both change `download._download_file`; this RFC lands first so RFC-005's retries build on it |
| Related | [ADR-002](../adr/ADR-002-per-variable-month-idempotent-downloads.md) (idempotent downloads), [roadmap](wind-engineering-roadmap-prd.md#4-rfc-roadmap), RFC-006 (export to wind software) |
| Drafted | 2026-10-31, updated the same day with the owner's decisions (section 8) |

## 1. Summary

Two changes, both about knowing where a file's data came from:

1. **Cache validation (bug fix).** A cached file is reused only if its contents match the request. Today a file is
   reused if one with the same name exists, and point and `average4` filenames don't contain the location. So a
   site that moves but keeps its name gets the old location's data, with no error. The check reads the location the
   server already writes into every cached file, so filenames don't change and cache files are never edited. A file
   that doesn't match, or can't be read, fails the download run before anything is merged, and the error says how to
   fix it (decision 1).
2. **csv metadata header.** Output csv files open with a short header block that mirrors the netCDF attributes:
   source, domain, frequency, node selection, dataset versions, the requested point, the actual node, its elevation
   (`orog`), the time zone and the download date. Windographer detects and strips a header block like this on import,
   and reads the latitude, longitude and elevation from it.

The header doesn't fix the bug: cache files are the server's responses, and adding a header to them would mean
rewriting them (RFC-005 3.2, defect 3). The two changes go in one RFC because both are about provenance and both
must land before the GUI, which makes moving a site a single drag.

## 2. Motivation

- **Silent wrong data.** `point_data_urlfilenames` names files
  `<prefix>_<domain>_<freq>[_average4]_<var>_<start>_<end>.<ext>`. The prefix is the site name. If a user changes a
  site's coordinates and reruns, every month already cached is skipped and merged as if it were the new location.
  The merge only fails ("more than one node") when months from both locations are present. In a GUI this is the
  normal workflow: drag the pin, run again.
- **Half-written files.** ADR-002 notes that a partly written or empty file is treated as complete. The same content
  check catches these.
- **csv outputs lose their provenance.** The netCDF output carries the node, `orog`, dataset versions and licence as
  attributes (RFC-003). A csv written from the same Dataset carries only the node coordinates, in every row. An
  energy-yield reviewer handed the csv can't tell the requested point, the node distance or the dataset version.

## 3. What the cached files already hold

Checked on the test fixtures (`tests/data/`, built from the live server by `scripts/build_test_fixtures.py`):

| Cached file | Requested location | Actual node |
|---|---|---|
| Point csv (`accept=csv_file`), also fixed fields such as `orog` | `station` column, every row: `GridPointRequestedAt[23.550S_133.400E]` (3 decimals) | `latitude`/`longitude` columns |
| Point netCDF (`accept=netcdf4`) | `station_description` and `station_id`: the same string | `latitude`/`longitude` coordinates |
| Grid netCDF (`average4`, area) | Not recorded; the request box is in the URL | `lat`/`lon` axes and `geospatial_lat_min` ... `_max` attributes |

## 4. Goals and non-goals

**Goals**
- G1. A cached file is skipped only if it can be read and matches the request: for a point, the requested location it
  records equals the request to the 3 decimals NCSS writes; for an `average4` grid, the four nodes around the
  requested point are inside its `lat`/`lon` axes; for an area, it covers the box.
- G2. A file that fails the check, because it records another location or can't be read, is never reused or
  overwritten. The download run checks every cached file before it makes any request, and if any fail it raises one
  error listing each failing file with the cached and requested locations, and saying to rename the site or delete
  those files. Nothing is downloaded, and nothing is merged from a stale cache (decisions 1-3, 9).
- G3. Writes are atomic (temporary name, then rename) and an empty 200 response is a failure, so a killed run can't
  leave a file that the next run trusts. Moved here from the RFC-005 SPEC because it is the same function
  (decision 7).
- G4. Filenames, cache layout and cache contents don't change. Existing caches stay valid where they match.
- G5. Output csv files from the netCDF route (`dataset_to_frames`) can be written with a metadata header that mirrors
  the Dataset attributes. A library reader returns the frame and the header as a dict.
- G6. The header imports cleanly into Windographer: it is detected and stripped, and the latitude, longitude and
  elevation are read from it.

**Non-goals**
- Windographer-native column names (`WS50`, `WS50_SD`), a units row, or other wind-software formats. Those are
  RFC-006.
- Headers on the cached files.
- A cache manifest or database. The files describe themselves; a second record could disagree with them.
- A header on the csv route (`merge_csvs_to_df` → `convert_wind_components`, the csv example). It stays the raw,
  step-by-step route (decision 6).
- Replacing mismatched files automatically, an overwrite flag, or a clear-cache helper. Recovery is by the error
  message; RFC-005 may add a GUI action later (decision 3).

## 5. Proposed design

### 5.1 Cache validation

`download_serial` and `download_multithread` check the cache first, before any request. Each URL already holds its
request (`latitude=`, `longitude=`, or `north=` ... `west=`), so the check parses it from there:

```text
check, before any request (_check_cache(urlfilenames, folder_path)):
  for each pair whose file exists: _cached_file_matches(path, url)?
    yes -> fine
    no  -> log and print the mismatch, add it to the list
  list not empty -> raise CacheMismatchError listing them; nothing is downloaded
then download as today: existing files (all checked) are skipped, missing ones fetched
```

- **Checking first, then raising once.** HTTP failures stay logged and printed, not raised (ADR-002). A cache
  mismatch is different: the stale file stays on disk, so if the run carried on, the merge would read it. Checking
  before any request also keeps the site's cache from becoming a mix of old-location and new-location files, which
  would happen if the run downloaded first and the user then renamed the site. `CacheMismatchError` is a
  `ValueError`, in a new `Errors` region of `download.py`, exported. Its message lists every failing file and, per
  file, the location it holds and the one requested, or "can't be read", and ends with: rename the site (the
  filename prefix) or delete these files, then run again. RFC-005's `run_site` catches it and fails the site.
- **`_download_file` keeps its signature** and still skips an existing file, which by then has passed the check.
  The check reads metadata only, so it is fast even for a large cache.
- **Files written before this RFC** that are empty or truncated fail the same way; atomic writes (G3) stop new ones
  appearing.

- **Point csv:** read the first data row only; parse the `station` value `GridPointRequestedAt[<lat><N|S>_<lon><E|W>]`
  and compare with the URL's latitude and longitude rounded to 3 decimals.
- **Point netCDF:** read `station_description` (no data loaded) and compare the same way.
- **`average4` grid:** the file's `lat` and `lon` axes must bracket the requested point (the existing
  `mapping.bracket_index`). Within that, the merge picks the four surrounding nodes from whatever grid is cached, so a
  small move inside the grid gives the right answer without a new download.
- **Area grid:** the box is in the filename already; check the `geospatial_*` bounds cover it, as a guard against
  partial files.
- **Precision.** NCSS writes the requested point to 3 decimals (about 100 m). A move smaller than that reuses the
  file. Two requests that round alike almost always share a nearest node; the edge case is pinned in a test and
  noted in the docs.
- **Cost.** One small read per cached file on a rerun: the first line of a csv, or netCDF metadata. Far less than the
  request it saves.
- **Limit.** One site name is cached at one location at a time. Moving a site means renaming it or deleting its
  cached files, which the error says. RFC-005's project file already requires unique names; the docs say to give
  each site, and each location, its own name.

### 5.2 csv metadata header

**Where Windographer stands.** Its [raw data files](https://support.ul-renewables.com/windographer/articles-raw-data-files.htm)
guide (last updated 2022-10-13) describes a file with a header block, then the column names, then a units row, then
the data. Windographer finds the column-name row and the first data row itself, works out the time step, and reads
the latitude, longitude and elevation from the header. The page doesn't give a syntax for the header lines. The
[import guide](https://support.ul-renewables.com/windographer/articles-importing-raw-data-files.htm) adds the time
zone to what it tries to detect, reads blank cells as missing, and assumes by default that a timestamp marks the
start of the time step. The WIS-file and Configure Dataset pages, which may say more, were not read; check them while
writing the SPEC.

**Proposed layout.** Two-column `key,value` lines in the same delimiter as the data, a blank line, then the column
row exactly as today. No units row: units stay in the column names (`ua50m[unit="m s-1"]`), so existing readers and
pandas still work, and a units row is RFC-006's to decide.

```text
File,barra2-dl output
Source,"BARRA2 BARRA-R2 reanalysis, Bureau of Meteorology, via NCI THREDDS"
Domain,AUS-11
Time step,1hr
Node selection,nearest
Latitude,-23.54
Longitude,133.36
Elevation,747.6
Elevation units,m
Requested latitude,-23.553
Requested longitude,133.396
Distance to node,3.94
Distance units,km
Time zone,UTC
Time stamp,"instantaneous at the stamp; time-mean variables (pr, rsds) are stamped mid-step"
Dataset versions,"ua50m v20240516; tas v20240516; ..."
Downloaded,2026-10-31
Created by,barra2-dl 0.3.1
License,"CC BY 4.0, Bureau of Meteorology"
References,http://www.bom.gov.au/research/publications/researchreports/BRR-067.pdf
Header lines,22

time,station,latitude[unit="degrees_north"],longitude[unit="degrees_east"],ua50m[unit="m s-1"],...
```

- Keys and values come from the Dataset (`merge._global_attrs` and the coordinates), so the csv and netCDF headers
  can't drift apart. Key names follow Windographer's words (Latitude, Longitude, Elevation, Time zone) where it has
  them.
- `Latitude`, `Longitude` and `Elevation` describe the series in the file: the node for `nearest` and for each
  `nodeN` file of `average4`; the requested point for the `average4` average (as in the netCDF), with `Elevation`
  the weighted mean of the four nodes' `orog` and the four nodes listed as `Node 1` ... `Node 4` lines (lat, lon,
  distance, weight, `orog`).
- `Header lines` is the count up to and including the blank line, so tools without detection can be told how many
  rows to skip, and `pandas.read_csv(path, skiprows=n)` works.
- Values that contain the delimiter are quoted, so the header is valid csv.

**API (indicative; names settled in the SPEC):**

| Function | Module | Does |
|---|---|---|
| `write_csv(ds, folder, prefix, *, header=True) -> list[Path]` | `merge.py` | Writes each frame of `dataset_to_frames(ds)` with its header, named as the netCDF example names them today |
| `read_csv(path) -> tuple[pd.DataFrame, dict[str, str]]` | `merge.py` | Reads a file written by `write_csv`, with or without a header |

The header is on by default (decision 5). The netCDF example's csv cell and `docs/how-to-use.md` switch to
`write_csv`; the csv example stays as it is (decision 6). RFC-005's `run_site` uses `write_csv` for its csv outputs.

## 6. Testing

- **Cache, point csv and netCDF:** a cached fixture for the same request is skipped (no `requests.get` call); for a
  request 0.1° away the run raises `CacheMismatchError` naming the file and both locations, the file is unchanged,
  and `requests.get` is never called; a request differing only beyond 3 decimals is skipped.
- **Cache, grids:** an `average4` file is reused when the point moves inside the grid and fails when it moves out;
  an area file whose bounds don't cover the box fails.
- **Cache, broken files:** an empty file, a truncated csv and a non-netCDF `.nc` each fail as "can't be read".
- **Failing run:** with one mismatched file among several cached and several missing, one error lists only the
  failing file, no request is made, and no file in the folder changes.
- **Atomic write:** a write that fails part way leaves no file under the final name; an empty 200 writes nothing.
- **Header:** `write_csv` then `read_csv` round-trips the frame and the header; the header values equal the
  Dataset's attributes; `skiprows=Header lines` reads the same frame with plain pandas; `header=False` writes the file
  as today; each `average4` file carries its own node's position and `orog`.
- **Windographer (manual, once):** the owner imports a nearest-node and an `average4` file and confirms the header is
  stripped and the latitude, longitude, elevation and time step are picked up. Recorded in the PR.
- **Live** (`BARRA2_LIVE=1`): one point request confirms NCSS still writes `GridPointRequestedAt[...]` in both
  formats.

## 7. Rollout

One PR, before RFC-005 slice 1:
1. `_cached_file_matches`, `CacheMismatchError` and the failure path in the download functions; atomic write and
   empty-response failure; tests.
2. `write_csv`, `read_csv` and the header; tests.
3. The netCDF example pair (kept in step), `docs/how-to-use.md` (cache reuse rule, what to do on a mismatch, header
   layout), `CONTEXT.md` (**Metadata header**), changelog.
4. ADR-003: a cached file is reused only if its contents match the request, and a run with a mismatched or unreadable
   file fails before any request; refines ADR-002.
5. Manual Windographer check.

## 8. Decisions

Decided by the owner on 2026-10-31:

1. **Mismatch:** a cached file for another location fails; it is not re-downloaded or replaced (G2, 5.1).
2. **Unreadable cached files** (empty, truncated, not netCDF) fail the same way.
3. **Recovery** is by the error message only: rename the site or delete the listed files. No clear-cache helper or
   overwrite flag in this RFC; RFC-005 may add a GUI action.
4. **Header syntax:** `key,value` csv lines, a blank line, then the column row (5.2).
5. **Header on by default**, with `header=False` to turn it off.
6. **The csv route stays raw:** no header on `merge_csvs_to_df` output or in the csv example.
7. **Field list:** all 21 lines in 5.2, plus the `Node 1` ... `Node 4` lines for an `average4` average.
8. **Atomic write and empty-response failure** move from the RFC-005 SPEC into this RFC (G3).

9. **Stopping a run:** the download functions check every cached file before any request and raise one
   `CacheMismatchError` listing the failures, so nothing is downloaded and nothing is merged from a stale file
   (5.1). Rejected: raising after downloading the other files (leaves a mixed cache), leaving the check to the merge
   (the csv route would be unprotected), and per-file results alone (today's scripts ignore them).
