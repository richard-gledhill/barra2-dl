# SPEC: GUI for wind resource assessment (RFC-005), starting with the engine

Requirement: [RFC-005](../requirements/gui-prd.md); its decisions are in section 8 and are not reopened here.
Style and gates: [conventions.md](../conventions.md), [constraints.md](../constraints.md).

## Slice status

- Slice 1 (the engine) shipped in #147.
- Slice 1b (research) is done and reviewed: see "Slice 1b addendum" for the owner's decisions.
- Slice 2 (node lookup, chosen nodes) has its addendum, "Slice 2 addendum" at the end, awaiting owner review.

## Scope

Resumed 2026-10-31 after [RFC-007](../requirements/cache-validation-csv-metadata-prd.md) shipped (#143). RFC-007 already
did the cache check (`_check_cache`, `CacheMismatchError`), the atomic `.part` write and the empty-response failure in
`download.py`, and the csv metadata header (`merge.write_csv`). Slice 1 builds on them and adds the RFC-005 5.7 engine
additions, which the owner approved on 2026-10-31 with the answers to RFC section 9 (see "Decisions").

RFC-005 in six slices, one PR each (section 7 of the RFC). **This SPEC details slice 1.** Slices 2-6 are outlined in
[plan.md](plan.md) and get their own SPEC addendum before they start.

Slice 1 is the engine: `project.py` (`load_project`, `run_site`), retries, per-file results, progress and cancel, and
the run summary, with tests, an example project file and an example-script cell.

Out of scope for slice 1: node lookup (`nearest_nodes`), the toolkit spikes, any GUI code, the command-line tool, and
changes to `mapping.py` other than its `__all__`.

## Changes

### `download.py`

- New `FileResult` (frozen dataclass, in `Constants and types`, exported): `filename`, `status`
  (`downloaded` | `skipped` | `failed` | `cancelled`), `status_code` (`int | None`), `attempts` (`int`), `error`
  (`str | None`).
- `_download_file` returns a `FileResult` (`skipped` for a file already in the cache) and retries timeouts, connection errors and HTTP 5xx up to 3 times after the
  first attempt, sleeping 1, 2 and 4 s (`_RETRY_DELAYS`). Other 4xx (404 included) are not retried. Failures are
  logged and printed, never raised. A missing cache folder still raises `FileNotFoundError`.
- Already done by RFC-007 and kept: a 200 with an empty body is a failure and is not written, and files are written to
  `<name>.part` and renamed. The retry loop wraps the request and the write; an empty body is retried like a 5xx.
- `_check_cache` still runs first in `download_serial` and `download_multithread`, before any request or pool, and a
  `CacheMismatchError` still propagates to the caller of these functions, with no results.
- `download_serial(urlfilenames, folder_path, *, progress=None, cancel=None) -> list[FileResult]` and
  `download_multithread(urlfilenames, folder_path, *, workers=4, progress=None, cancel=None) -> list[FileResult]`. The
  fixed pool of 4 replaces `cpu_count() - 1` (RFC decision 11). Callers that ignore the return value are unaffected.
- `progress(done, total, result)` is called once per file, from the calling thread. `cancel` is a `threading.Event`:
  once set, no new request starts, files not yet attempted come back as `cancelled`, and in-flight requests finish.
  Results come back in input order.
- `_report` (RFC-007) stays the one place that logs and prints a progress message.

### `project.py` (new, exported from `__init__.py`)

```python
@dataclass(frozen=True)
class Settings:   # defaults from the earlier RFCs
    domain: str = 'AUS-11'; freq: str = '1hr'; preset: str = 'wind+density'
    node_selection: str = 'nearest'; format: str = 'csv'; download: str = 'netcdf4'   # or 'csv', point sites only
    start: date; end: date                      # required in a project file
    cache: Path = Path('cache'); out: Path = Path('output'); workers: int = 4

@dataclass(frozen=True)
class Site:
    name: str
    point: LatLonPoint | None = None            # exactly one of point / bbox
    bbox: LatLonBBox | None = None
    overrides: dict[str, object] = {}           # any Settings key but cache/out/workers... see below

@dataclass(frozen=True)
class Project:  settings: Settings; sites: list[Site]; path: Path | None

@dataclass(frozen=True)
class SiteResult:
    site: str; status: str                      # ok | partial | failed | cancelled
    outputs: list[Path]; summary_path: Path
    files: list[FileResult]; missing: list[str]; error: str | None

class ProjectError(ValueError):                 # .problems: list[Problem], one per fault

@dataclass(frozen=True)
class Problem:  site: str | None; key: str; message: str
```

From RFC-005 5.7 (approved, section 9 item 2), so a form, flags and a file share one path:

- `project_from_dict(data, base_dir) -> Project` and `site_from_dict(data, settings) -> Site` build the dataclasses
  from plain data; `load_project(path)` is `tomllib` plus `project_from_dict`.
- `validate(settings, site) -> list[Problem]`, public; `ProjectError.problems` holds the same `Problem`s.
- `plan_site(site, settings) -> SitePlan` lists the files a run would download and which are already cached, using
  RFC-007's `_cached_file_problem` so a mismatch shows in the plan before the run.
- `site_result_to_dict(result) -> dict` is the one serialiser of `SiteResult` and the run summary, so the GUI, a later
  CLI and any API read the same structure.
- The choices come from the library: `BARRA2_FREQS`, `BARRA2_PRESETS`, `BARRA2_NODE_SELECTIONS`, a new
  `BARRA2_OUTPUT_FORMATS = ('csv', 'netcdf')` in `globals`, and `Literal` aliases `NodeSelection`, `OutputFormat`,
  `FileStatus` and `SiteStatus`. `globals.py` and `mapping.py` gain `__all__`.

- `load_project(path) -> Project` reads TOML with `tomllib`. `[settings]` and `[[site]]` only; unknown tables and keys
  are errors. Relative `cache` and `out` resolve against the file's folder. `start` and `end` accept a quoted ISO date
  or a TOML date. A site may override `domain`, `freq`, `preset`, `node_selection`, `format`, `start` and `end`; `cache`,
  `out` and `workers` are project-wide.
- Validation collects every problem and raises one `ProjectError` whose message lists each with its site and key. It
  checks: unknown keys; types; duplicate or filename-unsafe site names (`[A-Za-z0-9._-]+`, the name becomes the file
  prefix); lat/lon range; a box with `north > south` and `east > west`; both or neither of point and box;
  domain/freq (`BARRA2_FREQS`), the preset at that frequency (`preset_variables`), `node_selection` and `format`
  values; `start <= end`; `workers >= 1`. A box site is an `area` download unless it names another selection (an error);
  a point site with `area` is an error; `area` with `csv` is an error; `download = "csv"` is an error unless the site
  is a point with `nearest` and `format = "csv"` (RFC decision 13). Every message says what to change.
- `run_site(site, settings, progress=None, cancel=None) -> SiteResult` validates the effective settings again (the GUI
  builds the dataclasses without a file), creates the cache and output folders, and then:
  1. builds the URLs (`point_data_urlfilenames` or `area_data_urlfilenames`) as **netCDF4 by default**; a point site
     with `download = "csv"` builds csv URLs and takes the csv route in steps 3 and 4;
  2. downloads with `download_multithread`;
  3. resolves variable versions, merges with `merge_netcdf_to_dataset` (csv route: `merge_csvs_to_df`, then
     `convert_wind_components`; units are left as they are);
  4. writes `<name>_<domain>_<freq>_<selection>_<start>_<end>.nc`, or for `csv` `merge.write_csv(ds, out, name)`: the
     frames of `dataset_to_frames` as `<name>_<domain>_<freq>_<frame>_<start>_<end>.csv`, each with the metadata
     header (RFC-007); csv route: `merge.write_df_csv`, which writes the same header and file name;
  5. writes `<name>_run_summary.json` beside them.
- A `CacheMismatchError` from the download (a moved site that kept its name) is a site-level failure: `failed`, with
  the error's message in `error` and the failing files in `missing`; nothing is downloaded or overwritten (RFC-007).
- A site-level failure (no files, merge error, site outside the grid) returns `status='failed'` with `error`; it does
  not raise, so a caller's loop over sites carries on (RFC decision 12). Only invalid settings raise, before any
  request. Failed months still merge: the output is written with `status='partial'` and the gaps are in `missing`
  (entries like `ua50m 2023-02`). A cancelled site writes no output, only a summary with `status='cancelled'`.
- No `run_project` function: with `run_site` not raising, the loop is three lines and the deletion test fails.
- Units are not converted (`convert_units` stays opt-in); the Dataset keeps BARRA2 SI units.

### Run summary (`<name>_run_summary.json`)

`schema_version`, `status`, `error`, `inputs` (site and effective settings), `package_version`, `started` and `finished`
(UTC), `variable_versions`, `files` (name, status, status code, attempts), `missing`, `outputs`, and `nodes`: for each
node the requested latitude/longitude, the actual ones returned by NCSS, the distance in km and `orog` (an area lists the
count and the `orog` range). Written for every outcome, including failure and cancel.

### Tests

`tests/test_download.py` gains regions for retries, `FileResult`, progress, cancel and workers (the existing
`cpu_count` test is replaced, because the behaviour changes). `tests/test_project.py` mirrors `project.py`. `tests/test_package.py` gains the boundary tests of RFC 5.7 using only
the standard library: interfaces import only names in a module's `__all__` (plus `globals` constants); no library or
engine module imports `barra2_dl.gui`, `barra2_dl.cli` or a toolkit; and `import barra2_dl` works without the `gui`
extra.
`requests.get` is faked and `time.sleep` is patched; `run_site` tests reuse `tests/data/` (the fake serves fixture
bytes by variable, written to the paths RFC-007's cache check reads) and patch `project.preset_variables` to the fixture's variables. Live tests (`BARRA2_LIVE=1`): one
month of `run_site` for AUS-11 1hr, AUST-04 1hr and AUST-04 20min (`wind` preset).

### Examples and docs

- `scripts/example_project.toml`: the RFC 5.5 file with a one-month range, so it runs in a minute.
- A cell in `scripts/example_barra2_dl_netcdf.py` and its notebook (kept in step with jupytext) that loads the file and
  loops over the sites with `run_site`. The step-by-step cells stay.
- ADR-004 records the layering (top-level library, `gui/` and later `cli.py` beside it; rules 1-4 of RFC 5.7).
- `docs/how-to-use.md`: a "Project file" section. `CONTEXT.md`: **Project file**, **Site**, **Run summary**. README
  one-liner. `modules.md` if it lists modules by hand. No new dependency; `tomllib` is standard library.

## Acceptance

- Every test in RFC-005 section 6 for the project file, `run_site`, retries, and progress/cancel exists and passes.
- `make check`, `make test`, `make docs-test`, the live tests, and an end-to-end `run_site` over the example project
  in a scratch folder all pass, with no suppression added.
- Both example pairs are in step.

## Open design questions, reviewed during the build

Two user scenarios shape slices 2b-5. They are reviewed with the owner at the slice named, each time with a short
options note in that slice's SPEC addendum, before code is written. Slice 1 doesn't depend on the answers; its
`Site` and `Settings` classes can take new optional fields later without breaking callers.

**Scenarios**
- **Existing masts:** point-specific data for long-term correlation. Per mast: `nearest` or `average4`, keeping the
  node series so the analyst can test which correlates best.
- **Points without a mast:** the user wants BARRA2 data at one or more points to run their own analyses. The points
  may be proposed mast locations, representative points or turbine locations. Per point the user chooses one of:
  the nearest node; one or more specific nodes picked from the surrounding ones (seen on the map with distances and
  `orog`); or the four-node average of the point. Several points are several sites.
- **Greenfield site:** no mast and no chosen points, so the site is characterised from a boundary: all its nodes, or
  one site average.

| Question | Options | Reviewed at |
|---|---|---|
| Default output for a boundary | All nodes in or overlapping the polygon (area); a weighted site mean; both | Slice 2b |
| Site mean (new library work beyond RFC-003) | None, left to the analyst; an optional extra series, weighted by cell overlap with the polygon, using the hybrid method of `average4` | Slice 2b |
| Polygon smaller than one grid cell | `average4` at the centroid (proposed); nearest node to the centroid; error | Slice 2b |
| Node inclusion rule | Cell overlaps polygon (as NCSS returns); node point inside polygon | Slice 2b |
| Choosing specific nodes for a point (new; `nearest`, `average4` and `area` cover only nearest, the four around, and a box) | A node selection `nodes` taking node lat/lon or the index (1-4) from `nearest_nodes`; picking from the map only; a project-file key `nodes = [...]`; none, using a small area download | Slice 2 (library) and slice 4-5 (GUI) |
| Output when several nodes are chosen | One file per node; one file with a `node` dimension, as `average4` has; and whether an average is also offered | Slice 2 |
| Several points for one site (turbines) | Each a separate site (now); a site group sharing one cached download | Slice 2b, with slice 5 import |
| Starting modes in the GUI | "Met mast" and "Greenfield site" presets of the defaults above; none | Slice 4 |
| Boundary file types | GeoJSON and KML (standard library); shapefile (needs a dependency, owner approval) | Slice 2b |
| Mast heights and timestamp alignment | Left to the analyst's tool; a note in the docs; a helper | Slice 6 (docs) |

Each outcome is recorded in the addendum, and an ADR if it outlives the work.

### Resolved

Decided by the owner on 2026-10-31, and checked against the live server the same day:

- **Node layer in the GUI is optional.** The user can switch on a layer showing the BARRA2 nodes. It covers only the
  site location, or the area, plus a reasonable margin, so a map never draws the whole grid. Slice 5.
- **Node lookup uses the server only.** `nearest_nodes` and the node layer take their nodes from a small
  bounding-box request to NCSS (the `orog` fixed field, cached), never from a stored file, in line with RFC-005 5.1.
- **No node data files in `src/`.** The AUS-11 node list, `BOM_BARRA2_AUS11_latlon.csv`, was moved to
  [`docs/development/references/`](../references/README.md) as reference material. It is not packaged in wheels or
  tagged releases, and neither the package nor the tests read it.
- **Both grids are rectilinear** (checked 2026-10-31 from the fixed `orog` file of each domain, over OPeNDAP):

  | Domain | Latitudes | Longitudes | Nodes | Spacing | Extent |
  |---|---|---|---|---|---|
  | AUS-11 | 646 | 1,082 | 698,972 | 0.11° exactly, both axes | lat -57.97 to 12.98, lon 88.48 to 207.39 |
  | AUST-04 | 1,018 | 1,298 | 1,321,364 | 0.04° exactly, both axes | lat -45.69 to -5.01, lon 108.02 to 159.90 |

  Each has one-dimensional, strictly increasing `lat` and `lon` axes with a constant step. The AUS-11 axes match
  the reference CSV's. The node count equals latitudes × longitudes for both. No AUST-04 reference file has been made.
  `BARRA2_GRID_SPACING` (0.11 and 0.04) is confirmed.

### Research to resolve them

A research task runs after slice 1 merges and before the slice 2b addendum is written. It is time-boxed and ends in a
short note, `docs/development/research/reanalysis-site-data.md`, with sources and a recommendation for each question
above. The owner reviews the note; it doesn't change a requirements doc.

1. **Practice for mast correlation.** How MCP guidance and validation studies choose reanalysis nodes: nearest versus
   a few surrounding nodes versus a distance-weighted mean, and whether to correlate each node or the mean. Include
   the CSIRO validation behind RFC-005 decision 8 (the link returned 404; find the current URL) and any BARRA2 wind
   validation.
2. **Practice for greenfield sites.** How resource assessments characterise a site from reanalysis: representative
   points, a farm-area mean, or per-turbine nodes; how averaging changes the wind-speed distribution and extremes; how
   to treat nodes at different `orog`.
3. **Averaging method.** Whether the hybrid method of `average4` (scalar-mean speed, vector-mean direction) and
   inverse-distance weights suit an area mean, and what weights (cell overlap, distance, equal) the literature uses.
4. **NCSS behaviour (tested against the live server).** Which nodes a bounding box returns (cell overlap or node
   inside), what a box smaller than one cell returns, and whether a polygon's bounding box can be requested once and
   shared between sites. The result is pinned as test fixtures from `scripts/build_test_fixtures.py`.
5. **File formats.** What users have: GeoJSON, KML, shapefile, GeoPackage; which of these the standard library can
   read; the size and licence of `pyshp` if a shapefile reader is wanted.
6. **Point and node selection.** How users choose nodes for a proposed mast or point: nearest versus a specific
   node (such as the best-matched `orog` or surface type) versus the four-node average; whether `sftlf` (land
   fraction) or `orog` should be shown to guide the choice; whether a chosen node can be a node other than the four
   around the point.
7. **Mast data conventions.** Timestamp conventions and time zone (UTC or local) of logged mast data, and the heights
   typically measured, to decide what alignment guidance the docs give.

Findings that contradict an RFC-005 decision are reported to the owner and don't change the RFC.

## Decisions

Approved by the owner on 2026-10-31, as answers to RFC-005 section 9 and the questions below:

A. **Layout (section 9, 1):** top-level library with `gui/` and later `cli.py` beside it; no `core/` folder.
B. **Engine additions (2):** the 5.7 list above, all in slice 1.
C. **Console output (3):** keep the current dual pattern (RFC-007's `_report`) for now and rely on the progress
   callback in the GUI; revisit at slice 4. The convention is the owner's to change.
D. **Boundary tests (4):** standard library, not `import-linter`.
E. **ADR (5):** ADR-004, written in this slice.
F. **Cache mismatch in the GUI (7):** `run_site` reports it as a failed site. The GUI shows the error and offers a
   rename, and never deletes files for the user; detail at slice 4.

1. **Download route is a setting.** The default is the netCDF4 download for every route. A point site can switch to the
   csv download (`download = "csv"`), which runs the csv route end to end and writes csv only (RFC decision 13). The
   csv route's cache is the csv example's `.csv` files, so it reuses them.
2. **`cancelled` as a fourth `FileResult` status** (RFC decision 14).
3. **Retry arithmetic.** "Up to 3 times with back-off 1, 2, 4 s" is read as 3 retries (4 attempts in all).
4. **Atomic writes and empty-response failure** were done by RFC-007 (#143); slice 1 only adds retries around them.
5. **Example cell goes in the netCDF example only**, since the csv example is the step-by-step route.
6. **RFC-005 is `Accepted`** (2026-10-31).

## Slice 1b addendum: research (`docs/reanalysis-site-data-research`)

Written 2026-10-31, when slice 1b started.

**Scope.** The seven research tasks listed under "Research to resolve them", ending in one note,
`docs/development/research/reanalysis-site-data.md`, with sources and a recommendation per question. No library or
`src/` change.

**Method.** Short web searches and page reads for tasks 1, 2, 3, 5, 6 and 7. Task 4 (NCSS behaviour) is tested against the
live server, and the result is pinned as fixtures: `scripts/build_test_fixtures.py` gains `save_node_boxes`, which
downloads the `orog` grid for six boxes into `tests/data/ncss_box_*.nc`, and `tests/test_ncss_nodes.py` checks the node
rule against them offline. Claims from search summaries, and anything from my own knowledge of a standard, are marked in the
note. Findings that contradict an RFC-005 decision are reported to the owner, not applied.

**Output.** The note, the new `docs/development/research/` folder with its README, the fixtures and the test.

**Acceptance.** The seven questions each have a recommendation or a stated gap; the live findings are reproducible from
the fixture builder and pinned by tests; `make check`, `make test` and `make docs-test` pass; the owner has reviewed the
note. The slice 2b addendum is written only after that review.

**Not in scope.** Choosing the answers: the table of open questions stays open until the owner decides, slice by slice.

**Owner decisions after the note (2026-10-31).** These resolve rows of the design table above for slice 2b; nothing else in the
table is decided yet.

| Question | Decision |
|---|---|
| Default output for a boundary | All nodes whose cell overlaps the polygon, one series each, plus an opt-in site mean |
| Site mean | An opt-in extra series, weighted by each cell's overlap with the polygon, using the hybrid method |
| Polygon smaller than one grid cell | The node whose cell holds the centroid (`average4` at the centroid stays an option) |
| Node inclusion rule | The cell overlaps the polygon, as NCSS returns it |
| Boundary file types | GeoJSON and KML with the standard library; no shapefile and no `pyshp` in v1 |

## Slice 2 addendum: node lookup and chosen nodes (`feat/nearest-nodes`)

Written 2026-10-31, when slice 2 started. **Status: awaiting owner review. No library code or tests until it is
approved.** It settles the two rows of the design table marked "Slice 2" (choosing specific nodes for a point, and the
output when several are chosen) and does not reopen RFC-005 section 8, the section 9 answers or the slice 1b decisions.

**Scope.** `mapping.nearest_nodes(point, domain, n=4) -> list[GridNode]`; a `nodes` node selection that downloads and
writes chosen nodes; the draft helpers in `mapping.py` finished or deleted. Out of scope: polygons and the area-weighted
mean (slice 2b), the GUI map and the node layer (slice 5; it may reuse the lookup's internals, see "Not in scope"), and
any change to `nearest`, `average4` or `area` behaviour.

### Proposed decisions (for the owner)

| # | Question | Proposal |
|---|---|---|
| A | How a user names chosen nodes | Exact latitude and longitude, copied from `nearest_nodes`, never an index and never computed. The project file key is `nodes = [[lat, lon], ...]` on a point site. |
| B | Is `nodes` a setting or implied by the geometry? | Implied, like the box that makes an area: a point site with `nodes` is a `nodes` download. `nodes` is not a `node_selection` setting value; validation says what to give instead. |
| C | Output layout | The `average4` layout: a `node` dimension, `<var>_node` variables, one csv per node through `merge.write_csv`. The mean is opt-in (`node_mean = true`), by the hybrid method with inverse-distance weights among the chosen nodes. |
| D | Download | One bounding-box request per variable-month covering the chosen nodes, as `average4` and `area` do; the chosen nodes are picked client-side. |
| E | Draft helpers | Delete all three, with their tests (needs the owner's approval, see below). |
| F | `nearest_nodes` and the cache | Optional `cache=` folder; fixed-field files go in `<cache>/nodes/`; no `cache` means nothing is written. |

### `GridNode` and `nearest_nodes` (`mapping.py`)

```python
@dataclass(frozen=True)
class GridNode:
    lat: float          # exact grid latitude as served, degrees north
    lon: float          # exact grid longitude as served, degrees east
    distance_km: float  # great-circle distance from the point (mapping.distance_km)
    orog: float         # surface altitude, m
    sftlf: float        # land fraction of the cell, percent (0 to 100)

def nearest_nodes(point, domain='AUS-11', n=4, *, cache=None) -> list[GridNode]
class NodeLookupError(RuntimeError)   # the server could not give the nodes
```

`point` is a `LatLonPoint`; `cache` is `str | Path | None`. `domain` has a default only because the project default is
AUS-11; the RFC signature `(point, domain, n=4)` is kept. `__all__` gains `GridNode`, `NodeLookupError` and
`nearest_nodes`.

- Nodes come from the server only (RFC-005 5.1; decision of 2026-10-31): two small NCSS bounding-box requests, for the
  fixed fields `orog` and `sftlf`, using `BARRA2_URL_FX_BBOX`. `lat` and `lon` are the response's axis values, never
  `origin + k * spacing`. A node is identified by those values; `GridNode` carries no index.
- Result: the `n` nodes of the block returned, nearest first by great-circle distance (ties broken by latitude, then
  longitude, so the order is stable). `n` is 1 to 9, since the box returns at most a 3 x 3 block; otherwise
  `ValueError`. Fewer than `n` come back only at the edge of the domain. For `n = 4` these are normally, but not always,
  the four that surround the point (`average4` always averages the four that surround it): where a longitude step is
  shorter in km than a latitude step, a node on the far side can rank fourth. The docstring says so.
- An unknown domain is a `ValueError` listing `BARRA2_DOMAINS`. A point outside the domain (HTTP 400, or an empty
  response) or a failed download is a `NodeLookupError` carrying the file result's error.

**Request box (options).** The brief is to reuse the `average4` box (point ± one `BARRA2_GRID_SPACING`). NCSS returns
every node whose cell overlaps the box, so that box returns the 3 x 3 block around the cell holding the point
(`tests/test_ncss_nodes.py`), with one exception: a point exactly on a cell boundary puts the box edges exactly on cell
edges, where north and east count and south and west do not, so the block is 4 wide on one side only. Round coordinates
such as 133.415 (a boundary on AUS-11) make this plausible.

| Option | Effect |
|---|---|
| a. Exact `average4` box | Same request as `average4`. A boundary point gives an asymmetric 3 or 4 wide block; harmless for `n <= 4`, but for `n >= 7` the result depends on the edge rule. |
| b. `average4` box shrunk by 1% of the spacing on every side (**recommended**) | The block is always the 3 x 3 or smaller around the cell holding the point. The four bracket nodes are always inside (each is at most one spacing away, and a cell overlaps while its node is within 1.5 spacings). A boundary point gives the 2 nodes it sits between on that axis. The degenerate point moves to a non-round value (133.4161 on AUS-11). |

`average4` is left as it is: its cache files and tests are unchanged. Both options round the box to 6 decimals, as
`point_data_urlfilenames` does.

**Caching and RFC-007.**
- Files are `<cache>/nodes/<domain>_fx_<var>_n<N>_s<S>_e<E>_w<W>.nc`, box at 4 decimals. A subfolder, because a site name
  may be any `[A-Za-z0-9._-]+` and a lookup prefix in the cache folder itself could clash with a site called the same. The
  `nodes` subfolder is created if `cache` exists; a missing `cache` raises `FileNotFoundError`, as downloads do.
- The files are fetched with `download.download_serial` (retries, atomic `.part` write, the empty-response failure), so
  RFC-007's check runs unchanged: before any request `download._cached_file_problem` compares the file's extent
  (`geospatial_*`) with the box in the url, and a file that does not cover it or cannot be read raises
  `CacheMismatchError`, which `nearest_nodes` lets propagate (the message names the files). Nothing is deleted for the
  user. The lookup files are derived data and a stale one could safely be removed, but one rule for every cache file is
  simpler.
- A rerun for the same point makes no request. A different point in the same cell has a different box and so its own
  pair of small files; reuse of a covering file is not built (a ~2 KB file per pin is not worth the logic) and goes to
  the backlog.
- `cache=None` uses a temporary folder, deleted after the call, so a library call writes nothing unasked. The engine and
  the GUI pass `settings.cache`.
- The lookup files are not shared with a site's own `fx` file (that one carries the site name and the `average4` box).

**Import cycle (options).** `download.py` imports `LatLonBBox` and `bracket_index` from `mapping.py`, so `mapping`
cannot import `download` at the top.

| Option | Cost |
|---|---|
| a. Function-level `from barra2_dl.download import ...` inside `nearest_nodes` (**recommended**) | One local import with a comment; the retries, atomic write and cache check are reused, not copied. The ranking is a separate pure function, tested without any request. |
| b. Fetch with a small `requests.get` of its own in `mapping.py` | No cycle, but the retry and cache logic would be duplicated. |
| c. Move the fetch into `download.py` and call it from `mapping` | Same cycle. |

### Chosen nodes: the `nodes` selection

**Naming.** A user picks nodes from `nearest_nodes` (or the GUI preview, which shows the same list) and writes their
`lat` and `lon`. An index (1 to 4) is rejected: it depends on the lookup's order and on `n`. A project file reads:

```toml
[[site]]
name = "mast-b"
lat = -23.55                 # the site the nodes are measured from (required)
lon = 133.37
nodes = [[-23.54, 133.36], [-23.43, 133.36]]   # exact node values, copied from nearest_nodes
node_mean = true             # optional: also write the inverse-distance mean of these nodes
```

For one node, a `nearest` site at the node's own coordinates already gives that node's series. `nodes` is for several
nodes of one site from one download, laid out for comparison.

**`project.py`.**
- `Site` gains `nodes: list[LatLonPoint] | None = None` and `node_mean: bool = False` (geometry and output choice of one
  site, not settings; slice 2b's opt-in mean reuses `node_mean`). `site_from_dict` accepts the keys `nodes` (a list of
  `[lat, lon]` pairs) and `node_mean` (a bool); the unknown-key message lists them.
- `_selection(site, settings)`: `area` for a box, `nodes` for a site with `nodes`, else `settings.node_selection`.
  `globals.BARRA2_NODE_SELECTIONS` becomes `('nearest', 'average4', 'area', 'nodes')` and `NodeSelection` gains
  `'nodes'`; `merge_netcdf_to_dataset` already validates against the constant.
- `validate` adds the following, each with the site and the key and a message that says what to change:

  | Key | When | Message |
  |---|---|---|
  | `nodes` | not a list of `[lat, lon]` number pairs, or a pair out of range | `Give each node as [lat, lon] in degrees, copied from nearest_nodes.` |
  | `nodes` | empty, or more than 9 | `Give 1 to 9 nodes: the 3 x 3 block around the site is the most nearest_nodes returns.` |
  | `nodes` | a repeated node | `Node 2 repeats node 1.` |
  | `nodes` | site has a box | `Nodes belong to a point site; remove nodes, or use lat and lon.` |
  | `lat/lon` | `nodes` without a point | `A site with nodes also needs lat and lon: the site the distances are measured from.` |
  | `nodes` | a node more than 1.5 grid spacings from the point, in latitude or longitude, in the effective domain | `Node 2 is too far from the site (more than 1.5 grid spacings). Choose from nearest_nodes.` |
  | `node_selection` | a site override of `nodes` or `area`, or a settings value of either | The existing message, extended: `Use nearest or average4; a box site is an area and a site with nodes is a nodes download, automatically.` |
  | `node_selection` | an override other than `nodes` on a site that has `nodes` | `A site with nodes is a nodes download; remove node_selection.` |
  | `node_mean` | set on a site without `nodes` | `node_mean applies to a site with nodes.` |
  | `download` | `nodes` with `download = "csv"` | The existing csv-download message (the csv route is nearest-node only). |

  `validate` stays offline. Whether a named node is a grid node cannot be settled by arithmetic (RFC 5.1), so that is
  checked against the server's response in `run_site` (below). Range, count, repeats and the 1.5-spacing check use only
  the point, the named values and `BARRA2_GRID_SPACING`.
- `download.nodes_data_urlfilenames(nodes, barra2_vars, start, end, prefix, *, domain, freq)` builds the pairs (public,
  beside `area_data_urlfilenames`, netCDF4 only). The box is the nodes' bounding box widened by a quarter of the spacing
  on each side (midway between a node and its cell edge, so off the cell edges), which returns exactly the block between
  the chosen nodes. The filename tag is `nodes_n<N>_s<S>_e<E>_w<W>` (4 decimals), so a different choice has its own cache
  files, and `_cached_file_problem`'s coverage check applies as for an area. `_urlfilenames` calls it for a `nodes`
  site; `plan_site` needs no change.
- `run_site` for a `nodes` site downloads as above, calls `merge_netcdf_to_dataset(..., node_selection='nodes',
  nodes=..., node_mean=...)`, then writes with `write_csv` (one file per node, plus the mean) or one `.nc`. The fixed
  `orog` grid is read as for `average4`.
  - **Each named node must be a node of the response.** It is matched to a returned `(lat, lon)` within `1e-4` degrees
    (spacing is at least 0.04, so no two nodes are confused). No match fails the site: `<lat>, <lon> is not a node of
    AUS-11. The nodes near it: ... Use nearest_nodes.` (the nearest returned nodes, from the response). The cache keeps
    the files.
  - `_location_problem` takes its limit as a parameter: one spacing for `average4` (unchanged), 1.5 for `nodes`, since a
    node in the 3 x 3 block can be that far from the point.
- Summary: `inputs` gains `nodes` (the named pairs) and `node_mean` for a nodes site, with `selection = "nodes"`. `nodes`
  entries are as for `average4` (requested and actual position, `distance_km`, `orog`), in the order the user gave, with
  `weight` null when there is no mean and a 1-based `node` that matches the file name `node<k>`. `node` is additive, so
  `schema_version` stays 1.

**`merge.py`.**
- `merge_netcdf_to_dataset(..., node_selection='nodes', nodes=list[LatLonPoint], node_mean=False)`; `nodes` is required
  for `nodes` and `ValueError` otherwise. Grid files carry `_nodes_` in their name, so `_data_files` filters them as it
  does `_average4_` and `_area_`.
- The Dataset has the `average4` shape: the `node` dimension (in the user's order), `node_lat`, `node_lon`,
  `node_distance`, `node_orog` and `<var>_node` variables. With `node_mean` it also has the main variables (the hybrid
  mean, `node_weight`, `cell_methods` labelled as `average4` does) and `lat`/`lon` are the requested site. Without it
  there are no main variables and no `node_weight`. `attrs['node_selection']` is `nodes`.
- `dataset_to_frames` skips the main frame when there are no main variables, so the frames are `node1` to `nodeN`, plus
  `nodes` (the mean) when `node_mean`. File names follow: `<name>_<domain>_<freq>_node<k>_<dates>.csv` and
  `<name>_<domain>_<freq>_nodes_<dates>.csv`; the netCDF is `<name>_<domain>_<freq>_nodes_<dates>.nc`. `_csv_header` gives
  the mean frame its `Node k` lines as for `average4` and omits the weight when there is none.
- The inverse-distance mean among the chosen nodes reuses `_average_series` and `inverse_distance_weights`. With the four
  surrounding nodes it equals `average4` exactly (a test).

**Options considered for the output.**

| Option | Verdict |
|---|---|
| One file per node, no shared Dataset | Rejected: the node files and the netCDF would not share a layout with `average4`, and the metadata header code is written for the node dimension. |
| `average4` layout with the mean always on | Rejected: the research note (question 6) and the owner's boundary decision make the mean opt-in. |
| `average4` layout, mean opt-in (**proposed**) | Reuses the layout, writers and header; a mean costs one flag. |

### The draft helpers in `mapping.py`

`_generate_point_grid`, `_find_nearest_point` and `_format_lat_lon` are unwired, and the first two are the arithmetic the
RFC rules out (a grid built from a start and a resolution, and a nearest point searched in it). `_find_nearest_point` is
replaced by `nearest_nodes` (RFC-005 5.1 says so). `_format_lat_lon` was meant for file names by node; the `nodes`
selection names files `node<k>`, with the node in the header and the summary, and naming by node stays in the backlog.

**Proposal: delete all three** (git history keeps them), in this slice, together with:
- the `tests/test_mapping.py` regions `_generate_point_grid`, `_find_nearest_point` and `_format_lat_lon`, including the
  strict `xfail` `test_generate_point_grid_tuple`. This deletes tests, so it needs the owner's approval; the code they
  cover no longer exists.
- the backlog's "Tuple bounds crash" row and the draft-helpers bullet (the "naming files by BARRA2 node" bullet stays);
  the module docstring `Todo` and the then unused `pandas` and `cast` imports in `mapping.py`; the commented `Todo
  BARRA2_AU11_LATLONBBOX` line in `globals.py`; the draft-helpers sentence in `AGENTS.md`.
- **For the owner to change** (the file is theirs): the "Draft helpers (...) are unwired" bullet under **Design** in
  `docs/development/conventions.md` would then be wrong. Suggested change: delete the bullet.

Alternative: finish them. Not recommended: nothing needs a locally generated grid, and a finished `_generate_point_grid`
would invite the origin arithmetic the RFC removed.

### Tests (offline unless marked live)

`requests.get` is faked as in `tests/test_download.py`. The fake serves `tests/data/` fixtures by the `var` in the url,
and for the box tests it applies NCSS's cell-overlap rule (with the observed north/east-count edge rule) to the 5 x 5
`superset` fixture, so a boundary point is tested against the real behaviour rather than a hard-coded block.

- **New fixtures**, built live by a new `save_node_lookups` in `scripts/build_test_fixtures.py` (same style as
  `save_node_boxes`): the `sftlf` grid for the `superset` box, and `orog` and `sftlf` for one AUST-04 box (5 x 5), so a
  lookup can be served for both domains. Needs the network once; run with the owner's go-ahead.
- `tests/test_mapping.py` (`GridNode`, `nearest_nodes` and `NodeLookupError` regions): returns the `n` nearest in order
  with the fixture values; `n=1`, `n=9`, `n=10` and `n=0` (error); tie order; fewer nodes at a domain edge; unknown
  domain; request shape (two urls, `orog` and `sftlf`, the shrunk box, `accept=netcdf4`, `horizStride=1`); a failed
  download and a 400 give `NodeLookupError`.
- **Every returned node is a node of the grid** (RFC 5.1), parametrised over AUS-11 and AUST-04 and several points (inside
  a cell, near a node, on a cell boundary): each `lat`/`lon` equals a value of the response's axis exactly, lies on the
  lattice of the response (differences from the other axis values are whole multiples of the domain's spacing), and for
  AUST-04 is not a node an AUS-11 spacing would give (the fork's bug, RFC 3.2). Live (`BARRA2_LIVE=1`): the same check
  against the full-domain axes of each domain's `orog` file, read over OPeNDAP as on 2026-10-31.
- Boundary point: a point exactly on a cell edge returns the two nodes on that axis, not four (the shrunk box), with the
  fake applying the observed edge rule.
- Cache: the first call writes `<cache>/nodes/...`; the second makes no request; `cache=None` writes nothing; a file
  whose extent does not cover the box, and an unreadable file, raise `CacheMismatchError` before any request; a missing
  cache folder raises `FileNotFoundError`.
- `tests/test_download.py`: `nodes_data_urlfilenames` urls, box (a quarter spacing off the nodes), tag and file names; one
  node and several; a different node set gives a different box and names; `_cached_file_problem` accepts the files.
- `tests/test_merge.py`: `merge_netcdf_to_dataset(node_selection='nodes')` with and without the mean; node order is the
  user's; a named non-node raises; with the four surrounding nodes the mean equals `average4`; `dataset_to_frames` and
  `write_csv` names and header lines (no weight without a mean).
- `tests/test_project.py`: each validation row above; `site_from_dict` and `load_project` with `nodes`; the unknown-key
  list; `plan_site` lists the nodes files; `run_site` for a nodes site, csv and netCDF, with and without the mean
  (outputs, summary `inputs` and `nodes`, `weight` null); a non-node fails the site with the message and keeps the cache;
  the 1.5-spacing location limit (a far node of the block passes, an `average4` node at 1.2 spacings still fails).
- `tests/test_package.py`: `import barra2_dl.mapping` first still works (no cycle); `NodeSelection` and
  `BARRA2_NODE_SELECTIONS` agree.
- Live (`BARRA2_LIVE=1`): the grid-membership check above, and one month of `run_site` for a `nodes` site (two nodes,
  with the mean) on AUS-11 and on AUST-04.

### Examples and docs

- `scripts/example_project.toml`: a `nodes` site; its node values come from a live `nearest_nodes` call, never from
  computation. `scripts/example_barra2_dl_netcdf.py` and its notebook (kept in step by jupytext) gain a cell that prints
  the `nearest_nodes` table for a point and a cell that runs a `nodes` site. The csv example is unchanged.
- `docs/how-to-use.md`: "Choosing nodes" (the lookup, the `orog` and `sftlf` columns, the project-file keys, the output
  files, and the research note's advice to correlate each node and the mean) and a pointer from the project-file section.
- `CONTEXT.md`: **Grid node** (`GridNode`) and **Chosen nodes** (`nodes`); **Node selection** gains `nodes`; the **Node**
  entry's "never computed" stays. `docs/modules.md` needs nothing (mkdocstrings reads `__all__`). README one-liner.
  `AGENTS.md` loses the draft-helpers sentence.
- No new ADR: the rules this slice applies (nodes from the server, no origin arithmetic) are RFC-005 5.1. No new
  dependency.

### Not in scope, noted for later slices

- A larger lookup for the GUI node layer (slice 5): the internal fixed-field fetch takes a box, so slice 5 can call it for
  a site's margin with the same cache folder; no public API for it is added here.
- Reusing a covering cache file for nearby pins; naming files by node.

### Acceptance

- `nearest_nodes` returns real nodes for both domains, pinned by the grid-membership test (offline and live), and the
  boundary-point test passes with the NCSS edge rule applied.
- A project file with a `nodes` site loads, validates (each row above), plans, runs and writes `node<k>` csv files (and
  the mean on request) or one netCDF; the summary lists the nodes in the user's order; a named non-node fails the site
  with the message above.
- The mean of the four surrounding nodes through `nodes` equals `average4`.
- `make check`, `make test`, `make docs-test`, the live tests and an end-to-end run of the example project in a scratch
  folder pass, with no suppression added; the example pairs are in step.
- If approved, the three draft helpers, their tests and their notes are gone and the owner has updated `conventions.md`.

### Questions for the owner

1. **Box:** shrink the `average4` box by 1% of the spacing for `nearest_nodes` (b, recommended), or use it exactly (a)?
2. **`nodes` implied by `nodes = [...]`** (recommended, as a box implies an area), or an explicit
   `node_selection = "nodes"`?
3. **Delete the three draft helpers and their tests**, including the strict `xfail`, and edit the Design bullet of
   `conventions.md` (yours to change)?
4. **Function-level import** of `download` in `mapping.nearest_nodes` (a, recommended) to break the import cycle?
