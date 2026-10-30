# SPEC: cache validation and csv metadata header (RFC-007)

Requirement: [RFC-007](../requirements/cache-validation-csv-metadata-prd.md); its decisions are in section 8 and are
not reopened here. Style and gates: [conventions.md](../conventions.md), [constraints.md](../constraints.md).

## Scope

All of RFC-007 in one PR (`fix/cache-validation-csv-header`): the cache check before any request, atomic writes and
empty-response failure, and the csv metadata header with its writer and reader, plus tests, the netCDF example, docs
and ADR-003.

Out of scope: retries, per-file results, worker count and progress/cancel (RFC-005, parked); Windographer-native
column names, a units row and WIS files (RFC-006); any change to the csv route (`merge_csvs_to_df`, the csv example).

## Findings from the Windographer pages

Read on 2026-10-31: [raw data files](https://support.ul-renewables.com/windographer/articles-raw-data-files.htm),
[importing raw data files](https://support.ul-renewables.com/windographer/articles-importing-raw-data-files.htm),
[WIS file](https://support.ul-renewables.com/windographer/def-WIS-file.htm) and
[Configure Dataset](https://support.ul-renewables.com/windographer/dlg-revise-configure-dataset.htm).

- Windographer finds the header block, the column-name row and the first data row by itself, and says it reads the
  latitude, longitude and elevation "from the file header". None of the pages gives a syntax or key names for those
  header lines, or the sign convention or time-zone format.
- A WIS file is an XML sidecar (`<datafile>.wis`) that can set the time zone, the time stamp meaning and column
  properties, overriding what Windographer detects. It doesn't list latitude, longitude or elevation. Writing one is
  RFC-006 work.
- Blank cells and cells with letters are read as missing, so the text `station` column is ignored.
- By default Windographer takes a timestamp as the start of the time step.

So the header uses Windographer's own words where it has them (Latitude, Longitude, Elevation, Time zone), in
decimal degrees with south and west negative and elevation in metres, and the manual import check (Acceptance)
settles whether Windographer reads them. If it doesn't, the layout stays: the header is still the provenance record,
and RFC-006 can add a WIS file.

## Changes

### `download.py`

**`CacheMismatchError(ValueError)`**, in a new `# region Errors` after `Constants and types`, exported.
`problems: list[tuple[str, str]]` holds `(filename, reason)` pairs. The message lists each one and ends: "Rename the
site (the filename prefix) or delete these files from <folder>, then run again."

**`_check_cache(urlfilenames, folder_path) -> None`**, called first by `download_serial` and `download_multithread`,
before any request and before the thread pool starts. For each pair whose file exists it calls
`_cached_file_problem`; each problem is logged and printed (the dual pattern); if there are any, it raises one
`CacheMismatchError`. A missing folder has no files to check; `_download_file` still raises `FileNotFoundError` for it.

**`_cached_file_problem(path, url) -> str | None`** (the RFC's `_cached_file_matches`, returning the reason so the
error can say it). `None` means the file matches. The request is parsed from the URL query with `urllib.parse`:

| Request in the URL | File | Check | Reason on failure |
|---|---|---|---|
| `latitude`, `longitude` and `accept=csv_file` | Point csv, including fixed fields | Read the first two lines only (`csv` module). Parse the `station` value `GridPointRequestedAt[<lat><N\|S>_<lon><E\|W>]`; S and W negative | `holds <lat>, <lon>; requested <lat>, <lon>` |
| `latitude`, `longitude` and `accept=netcdf4` | Point netCDF | Open lazily with xarray, parse `station_description` the same way | as above |
| `north` ... `west` and `_average4_` in the filename | `average4` grid | The requested point is the box centre. `mapping.bracket_index` on the file's `lat` and `lon` axes succeeds for it | `its nodes don't surround <lat>, <lon>` |
| `north` ... `west`, any other grid | Area grid | `geospatial_lat_min <= south`, `geospatial_lat_max >= north`, and the same for lon | `doesn't cover the box` |
| No location (not a BARRA2 NCSS URL) | any | Not checked | |

- **Point match:** each coordinate within 0.0005° of the request (the 3 decimals NCSS writes, allowing for its
  rounding), after normalising longitudes to -180 to 180, since AUS-11 reaches 207.39° E.
- **Unreadable:** an empty file, a csv without a data row or a `GridPointRequestedAt[...]` value, a `.nc` xarray can't
  open, or one missing the expected variable or axes, gives `can't be read`.
- xarray is already a runtime dependency; `download.py` imports it, so `deptry` stays clean.

**`_download_file`** keeps its signature and its skip of an existing file (already checked by then). It now:
- treats a 200 with an empty body as a failure: logged and printed with the reason, nothing written;
- writes to `<file_name>.part` in the same folder and renames it with `Path.replace`, so the final name only ever
  holds a complete response. A `.part` left by a killed run is overwritten next time, and no merge pattern matches it
  (they end in `.csv` or `.nc`).

**ADR-002 behaviour kept:** HTTP failures are still logged and printed, not raised; `CacheMismatchError` is the only
new exception, and it is raised before any request.

### `merge.py`

**`write_csv(ds, folder, prefix, *, header=True) -> list[Path]`**, exported. Writes each frame of
`dataset_to_frames(ds)` to `<folder>/<prefix>_<domain>_<freq>_<frame>_<first>_<last>.csv`, the names the netCDF example
uses today, with `<first>` and `<last>` the dates (`%Y%m%d`) of the first and last `time`. Returns the paths in frame
order. An area Dataset raises the `ValueError` of `dataset_to_frames`. With `header=False` the file is exactly what
`frame.to_csv(path, index=False)` writes today.

**`read_csv(path) -> tuple[pd.DataFrame, dict[str, str]]`**, exported. If the first field of the first line is `time`
there is no header and the dict is empty. Otherwise it reads `key,value` lines with the `csv` module up to the blank
line, then the frame with `pd.read_csv(path, skiprows=<that count>)`.

**`_csv_header(ds, frame_name) -> list[tuple[str, str]]`**, a helper. Lines in this order, every key always written
(empty value when unknown, so the layout is stable):

| Key | Value, from the Dataset |
|---|---|
| `File` | `barra2-dl output` |
| `Source` | `ds.attrs['source']` |
| `Domain` | `ds.attrs['domain']` |
| `Time step` | `ds.attrs['freq']` |
| `Node selection` | `ds.attrs['node_selection']` |
| `Latitude`, `Longitude` | The frame's series: `lat`/`lon` for `nearest` and the `average4` average (the requested site, as in the netCDF); `node_lat`/`node_lon[k]` for `nodeN` |
| `Elevation` | `ds.attrs['orog']` for `nearest` and the average (the weighted node mean); `node_orog[k]` for `nodeN` |
| `Elevation units` | `m` |
| `Requested latitude`, `Requested longitude` | `requested_lat`, `requested_lon` |
| `Distance to node` | `mapping.distance_km` from the requested point to `lat`/`lon` for `nearest`; `node_distance[k]` for `nodeN`; empty for the average |
| `Distance units` | `km` |
| `Time zone` | `UTC` |
| `Time stamp` | `instantaneous at the stamp; time-mean variables (pr, rsds) are stamped mid-step` |
| `Dataset versions` | `ds.attrs['barra2_version']` |
| `Downloaded` | `ds.attrs['downloaded']` |
| `Created by` | `barra2-dl <version>` (`importlib.metadata`) |
| `License` | `ds.attrs['license']` |
| `References` | `ds.attrs['references']` |
| `Node 1` ... `Node 4` | `average4` average only: `lat <..>; lon <..>; distance <..> km; weight <..>; orog <..> m` |
| `Header lines` | The number of lines up to and including the blank line: 22, or 26 for the average |

Numbers are written with `repr` of the float, as the netCDF holds them. Values are quoted by the `csv` module only
when they need it.

## Tests

Regions follow the conventions: `test_download.py` gains `CacheMismatchError` under `Errors`, and `_check_cache` and
`_cached_file_problem` under `Helpers`; `test_merge.py` gains `write_csv` and `read_csv` under `Public API`. Fixtures
come from `tests/data/`, copied into `tmp_path` under the names `point_data_urlfilenames` and
`area_data_urlfilenames` give them; `requests.get` is faked with the existing `fake_get`.

**Cache check**
- Point csv and point netCDF (parametrised): the request the fixture was made for (-23.55, 133.40) is skipped and
  `fake_get` stays empty; a request 0.0004° away is skipped; one 0.1° away raises `CacheMismatchError` naming the
  file and both locations, `fake_get` stays empty and the file's bytes are unchanged.
- Fixed field (`fixture_AUS-11_fx_orog.csv`): checked like a point.
- `average4` grid: a point moved inside the grid's nodes (-23.60, 133.40) is skipped; one outside (-23.70) fails.
- Area grid: a box inside the file's `geospatial_*` bounds passes; a wider one fails.
- Unreadable (parametrised): an empty file, a csv with only a column row, and a `.nc` holding `b'not netcdf'` each
  fail as `can't be read`.
- One mismatched file among several cached and several missing: one error lists only that file, no request is
  made, and no file in the folder changes; both `download_serial` and `download_multithread`.
- A URL without a location (the existing `example.test` URLs) isn't checked; the existing offline tests still pass
  unchanged.
- Southern and western hemispheres and a longitude above 180 parse correctly (`_cached_file_problem` on small
  hand-written csv files).

**Writes**
- A 200 with an empty body writes nothing and is printed as a failure.
- A write that raises part way (patched `Path.write_bytes`) leaves no file under the final name.
- A successful download leaves no `.part` file.

**Header**
- `write_csv` then `read_csv` round-trips each frame (equal to `dataset_to_frames`) and the header, for the nearest
  node and for `average4` from the fixtures.
- Header values equal the Dataset's attributes and coordinates; the nearest node's `Distance to node` equals
  `distance_km`; each `nodeN` file has its node's position, distance and `orog`; the average has the four `Node`
  lines and 26 header lines, the nearest node 22.
- `pd.read_csv(path, skiprows=int(header['Header lines']))` gives the same frame as `read_csv`.
- `header=False` writes byte-for-byte what `frame.to_csv(path, index=False)` writes; `read_csv` reads it with an
  empty dict.
- An area Dataset raises `ValueError`.

**Live** (`BARRA2_LIVE=1`): point requests in `csv_file` and `netcdf4` at (-23.55, 133.40) and at a longitude above
180 on AUS-11, each parsed by `_cached_file_problem` as matching; this pins the `GridPointRequestedAt` format.

## Examples and docs

- `scripts/example_barra2_dl_netcdf.py` and its notebook (kept in step): the "Write csv" cell uses
  `barra2_dl.merge.write_csv(ds, output_dir, fileout_prefix)`. The csv example is unchanged.
- `docs/how-to-use.md`: a "Re-running and the cache" section (what is checked, the error and what to do: rename the
  site or delete the listed files); the four-node-average "csv output" paragraph uses `write_csv`; a "csv metadata
  header" section with the layout and how to read it (`read_csv`, or `skiprows` in pandas or other software), and the
  note that Windographer strips it. "Output 2: csv" says the csv route writes no header and points to `write_csv`.
- `CONTEXT.md`: **Metadata header** (the `key,value` block at the top of an output csv) and **Cache mismatch**.
- `README.md`: one line on `write_csv`.
- `modules.md` renders `merge` and `download` already; nothing to add.
- ADR-003 `ADR-003-cached-files-must-match-the-request.md`, refining ADR-002; ADR README table row.
- The changelog is generated from Conventional Commits, so it isn't edited by hand.

## Acceptance

- Every test above exists and passes; coverage stays at 100%.
- `make check`, `make test`, `make docs-test` and the live tests pass, with no suppression added.
- The example netCDF pair runs end to end in a scratch folder, twice (the second run makes no request), and a third
  time with the point moved, which stops with `CacheMismatchError` before any request.
- The owner imports a nearest-node file and an `average4` average file into Windographer and records in the PR
  whether the header is stripped and the latitude, longitude, elevation, time step and time zone are picked up.

## Decisions

Details the RFC left to the SPEC, all approved by the owner on 2026-10-31:

1. **Reason, not a boolean:** `_cached_file_problem` returns why a file fails, so the error can say it.
2. **URLs without a location aren't checked**, so callers passing their own URLs keep today's behaviour.
3. **Match tolerance:** 0.0005° per coordinate, with longitudes normalised.
4. **`average4` uses the box centre** as the requested point; it is the site, as `point_data_urlfilenames` builds the
   box around it.
5. **Every header key is always written**, empty when unknown (for example `Elevation` without an `orog` file).
6. **`Dataset versions` is the Dataset's `barra2_version`** (the distinct versions, as the netCDF records them), not a
   per-variable list as the RFC's example showed; per-variable versions stay in the netCDF variable attributes.
7. **Output dates come from the Dataset's time range**, so `write_csv` needs no start and end arguments.
8. **`write_csv` and `read_csv` go in `merge.py`**, beside `dataset_to_frames`, as the RFC says. `merge.py` grows past
   1,000 lines; splitting it is left to the backlog.
9. **The temporary name is `<file_name>.part`** in the cache folder, so the rename stays on one file system.
