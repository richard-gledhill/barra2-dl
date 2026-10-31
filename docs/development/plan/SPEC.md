# SPEC: GUI for wind resource assessment (RFC-005), starting with the engine

Requirement: [RFC-005](../requirements/gui-prd.md); its decisions are in section 8 and are not reopened here.
Style and gates: [conventions.md](../conventions.md), [constraints.md](../constraints.md).

## Slice status

- Slice 1 (the engine) shipped in #147.
- Slice 1b (research) is done and reviewed: see "Slice 1b addendum" for the owner's decisions.
- Slice 2 (node lookup, chosen nodes) has its addendum, "Slice 2 addendum" at the end, approved by the owner on 2026-10-31, and shipped in #150.
- Slice 2b (polygon boundary) has its addendum, "Slice 2b addendum", approved by the owner on 2026-10-31, and shipped in #152.
- Slice 3 (toolkit spikes and ADR-005) has its addendum, "Slice 3 addendum" at the end, proposed for the owner's review; nothing is built until it is approved.

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

Written 2026-10-31, when slice 2 started. **Status: approved with the owner's four answers on 2026-10-31 (see "Decisions"). Implementation
is a separate PR, started when the owner says.** It settles the two rows of the design table marked "Slice 2" (choosing specific nodes for a point, and the
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
- **GUI requirement (owner, 2026-10-31):** the map shows the nodes selected or used for a site (nearest, the four of
  `average4`, the chosen `nodes`, or an area's nodes), with distance, `orog` and `sftlf` on hover or select, both when
  choosing and for a finished run (from the summary's `nodes`). A table alone does not meet it. Slice 4 carries the node
  data through the form and the result; slice 5 draws it.

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

### Decisions

Owner's answers of 2026-10-31 to the four questions raised in review; the option tables above are the reasoning.

1. **Box:** the `average4` box shrunk by 1% of the spacing on every side (option b).
2. **`nodes` is implied** by `nodes = [[lat, lon], ...]` on a point site; it is not a `node_selection` value.
3. **The three draft helpers and their tests are deleted** in this slice, including the strict `xfail`. The Design bullet
   in `conventions.md` stays for the owner to delete; this slice does not edit that file.
4. **Function-level import** of `download` inside `nearest_nodes`, with a comment saying why (the import cycle).

Added by the owner: the GUI must show a visual representation of the nodes selected or used, on the map, for a chosen or
used site, not only a table. This is a slice 4/5 requirement (see "Not in scope" and `plan.md`).

## Slice 2b addendum: polygon boundary (`feat/polygon-boundary`)

Written 2026-10-31, when slice 2b started. **Status: approved with the owner's five answers on 2026-10-31 (see "Decisions"). Implementation
is a separate PR, started when the owner says.** It builds on the slice 1b owner decisions (the table under "Slice 1b addendum") and the slice 2 work (#150),
settles the rows still open for 2b in the design table, and does not reopen RFC-005 section 8, the section 9 answers or
the slice 1b and slice 2 decisions.

**Scope.** A site whose place is a polygon boundary (a wind-farm or lease outline) instead of a point, a box or chosen
nodes: a `Polygon` type, readers for GeoJSON and KML, the node mask by cell overlap, an optional area-weighted site mean,
the project-file key `polygon = "farm.geojson"`, and the run summary entries the GUI needs to draw the nodes used. Out of
scope: the GUI (drawing a polygon and showing the nodes is slice 5), shapefiles (owner: not in v1), csv output for a
boundary, and any change to `nearest`, `average4`, `nodes` or box-`area` behaviour.

### Decisions already made (not reopened)

| Question | Decision (owner, 2026-10-31) |
|---|---|
| Default output for a boundary | All nodes whose cell overlaps the polygon, one series each, plus an opt-in site mean |
| Site mean | Opt-in, weighted by each cell's overlap with the polygon, by the hybrid method (scalar-mean speed, vector-mean direction) |
| Polygon smaller than one grid cell | The node whose cell holds the centroid (`average4` at the centroid stays an option) |
| Node inclusion rule | The cell overlaps the polygon, as NCSS returns it |
| Boundary file types | GeoJSON and KML with the standard library; no shapefile, no `pyshp` |

### Proposed decisions (for the owner)

| # | Question | Proposal |
|---|---|---|
| A | Where the geometry lives | `mapping.py`, as the plan says: `Polygon`, `read_polygon`, `polygon_from_geojson`, `polygon_from_kml`, `BoundaryFileError`. numpy only, no new dependency. |
| B | Site key and selection | `Site.polygon: Polygon | None`; project file `polygon = "farm.geojson"` (relative to the project file). A polygon site is an `area` download automatically, as a box is. Exactly one of point, box and polygon. |
| C | The mean | `node_mean = true`, the key slice 2 added, so one key means "also write the mean of the nodes used" for `nodes` and for a polygon. Weights are cell overlap area (times the cosine of the node latitude), normalised; hybrid method. |
| D | Output | netCDF only, the `area` grid (`lat`, `lon` dimensions) with nodes that do not overlap the polygon set to missing, plus `cell_overlap` and `cell_weight` grids and, with `node_mean`, the `<var>_site_mean` series. |
| E | Request | One box per variable-month, the polygon's bounding box widened by 1% of the spacing (box type and cache files as an area), so the cache is the same for any polygon with that bounding box. The mask is applied at merge. |
| F | Several points for one site (turbines) | Out of scope (owner): a site is a boundary or user-defined points. |

### `Polygon` and the readers (`mapping.py`)

```python
@dataclass(frozen=True)
class Polygon:
    exterior: tuple[tuple[float, float], ...]          # (lat, lon) vertices, counter-clockwise, not repeated at the end
    holes: tuple[tuple[tuple[float, float], ...], ...] = ()
    source: str = ''                                   # file name or 'drawn', for the summary

    def bbox(self) -> LatLonBBox
    def centroid(self) -> LatLonPoint                  # area-weighted; the bbox centre for a zero-area ring
    def contains(self, point: LatLonPoint) -> bool     # inside the exterior and outside every hole
    def cell_overlap(self, lats, lons, spacing) -> np.ndarray   # (lat, lon): fraction 0 to 1 of each cell inside

def read_polygon(path: str | Path) -> Polygon                    # by suffix: .geojson, .json, .kml
def polygon_from_geojson(text: str, source: str = '') -> Polygon
def polygon_from_kml(text: str, source: str = '') -> Polygon
class BoundaryFileError(ValueError)                               # one problem, saying what to change
```

`__all__` gains these. The text readers let the GUI parse an uploaded file or a drawn shape without touching the disk.

**Geometry (numpy, planar in degrees).**
- A cell is the node plus or minus half the grid spacing in each direction, the cell NCSS uses (pinned by
  `tests/test_ncss_nodes.py`). `cell_overlap` clips the polygon to each cell (Sutherland-Hodgman against the rectangle,
  whose area by the shoelace formula is right for a concave polygon too), subtracts the clipped holes, and divides by the
  cell area. A node is **used** when its fraction is above `1e-9`, so a polygon that only touches a cell edge does not
  use it, and the NCSS edge rule (north and east count, south and west do not) never matters.
- Weights: `overlap area x cos(node latitude)`, normalised to sum to 1. Within a farm the cosine is almost constant;
  it keeps the weights right for a boundary spanning degrees of latitude. Distances elsewhere are great-circle; areas
  here are planar in degrees, which is the stated approximation.
- `contains` uses the even-odd rule; the centroid is the polygon area centroid.

**What a boundary may be (validation, one `BoundaryFileError` per fault).**
- At least 3 distinct vertices, latitude -90 to 90, longitude -180 to 180 (a polygon across the antimeridian is
  rejected; `Longitude` has the same limit today), no repeated vertex except the closing one, and no self-intersection of
  a ring or crossing between rings (checked pairwise, fine for hundreds of vertices; above 5,000 vertices the file is
  rejected with "simplify the outline").
- GeoJSON (RFC 7946): a `Polygon`, a `Feature` holding one, or a `FeatureCollection` of exactly one such feature.
  Coordinates are longitude then latitude; a third value is ignored. A legacy `crs` member is accepted only for
  WGS 84 (`EPSG:4326`, `CRS84`); any other is an error. Order of the rings is normalised (exterior counter-clockwise,
  holes clockwise).
- KML: a `Placemark` with one `Polygon` (`outerBoundaryIs`, any `innerBoundaryIs`), tags matched regardless of the XML
  namespace. A file with a `DOCTYPE` or entity declaration is refused before parsing (the standard parser is not hardened
  against entity expansion). KMZ (zipped) is not read: the message says to extract the `.kml`.
- A `MultiPolygon`, several features, or several placemarks are refused (see Q1): `farm.geojson holds 3 polygons; give each
  its own site.`

### Node mask and the sub-cell case

- **Used nodes.** After the box download, the mask is `polygon.cell_overlap(lat, lon, spacing)` on the returned axes. The
  returned grid always contains every used node, because NCSS returns every node whose cell overlaps the box and the box
  contains the polygon; a live test pins this.
- **Sub-cell polygon** (**Q2**): the polygon's bounding box is smaller than one grid spacing in both latitude and
  longitude. Then exactly one node is used: of the returned nodes, the one whose cell holds the centroid, found as the
  smallest Chebyshev distance `max(|dlat|, |dlon|)` to the centroid (a centroid on a cell edge goes to the lower latitude,
  then the lower longitude). It is chosen among the server's nodes, never computed. Its `cell_overlap` is the polygon's real
  fraction, but its weight is 1.
  A bigger polygon that happens to lie in one cell is just the ordinary case and gives the same node.

| Option for "smaller than one cell" | Effect |
|---|---|
| a. Bounding box under one spacing in both directions (**recommended**) | A small polygon straddling a cell boundary gets the one node holding its centroid, as the owner decision says. Simple to state and to test. |
| b. Polygon area under one cell area | A thin long polygon (a 12 km x 1 km strip) counts as sub-cell and loses all but one node. |
| c. Polygon overlaps only one cell | No special case, but a small polygon straddling a boundary gets two nodes, which is not what the decision says. |

### The Dataset

`merge.merge_netcdf_to_dataset(..., node_selection='area', polygon=polygon, node_mean=False)` builds the area Dataset as
today, then:
- every data variable is set to missing at unused nodes (a rectangular grid cannot drop individual nodes), so a
  statistic over the grid ignores them;
- `cell_overlap (lat, lon)`: the fraction of each cell inside the polygon, 0 where unused;
- `cell_weight (lat, lon)`: the normalised weights above, 0 where unused (1 at the one node of a sub-cell polygon);
- attributes: `boundary_source`, `boundary_vertices`, `boundary_area_km2` (planar area x 111.195^2 x cosine of the
  centroid latitude, an approximation), `boundary_centroid`, `boundary_sub_cell` (bool), `boundary_covered` (the used cells'
  share of the polygon area, below 1 only where the polygon leaves the domain);
- with `node_mean`: `<var>_site_mean` for every data variable, by the hybrid method: speed is the weighted mean of
  each used node's own speed (scalar mean), `ua`/`va` are weighted means of the components, direction is taken from them
  (vector mean), and `cell_methods` says which, as for `average4`. `_site_mean` rather than `_mean`, because `_is_mean`
  already means a time-mean variable (`pr`).

netCDF only: `area` with `csv` stays an error, and the message for a polygon site says to use `format = "netcdf"` (**Q3**).

### `project.py` and the project file

```toml
[[site]]
name = "farm"
polygon = "farm.geojson"     # GeoJSON or KML, WGS 84; relative to this file
node_mean = true             # optional: also write the area-weighted mean of the nodes used
format = "netcdf"
```

- `Site` gains `polygon: Polygon | None = None`. `site_from_dict` accepts `polygon` as a path (read with `read_polygon`,
  relative to the project file's folder, so `project_from_dict` passes its `base_dir`) or as a `Polygon` (a form).
  `_selection` returns `area` for a polygon site.
- `validate` adds, each with the site and key and a message that says what to change:

  | Key | When | Message |
  |---|---|---|
  | `polygon` | the file is missing or unreadable | `Cannot read farm.geojson: <reason>.` (the `BoundaryFileError` message, with the path) |
  | `polygon` | not text or a `Polygon` | `Give the path of a GeoJSON or KML file, in quotes.` |
  | `lat/lon` | more or fewer than one of point, box and polygon (nodes count with a point) | `Give one place: lat and lon, a box, or a polygon.` |
  | `polygon` | the site also has `nodes` | `Nodes belong to a point site; remove nodes, or remove polygon.` |
  | `node_selection` | an override on a polygon site | `A polygon site is an area download; remove node_selection.` |
  | `format` | `csv` on a polygon site | `A boundary is a grid and cannot be written as csv; set format = "netcdf".` |
  | `download` | `csv` on a polygon site | the existing csv-download message |
  | `polygon` | the bounding box covers more than 2,500 nodes (**Q4**) | `This boundary covers about 4,000 grid nodes; the limit is 2,500. Use a smaller boundary.` The count is `ceil(extent / spacing)` per axis, a guard on size, not a node position. |
  | `node_mean` | set on a site with neither `nodes` nor a polygon | `node_mean applies to a site with nodes or a polygon.` (the slice 2 message, widened) |

- `urlfilenames`: `area_data_urlfilenames(LatLonBBox(<bbox widened by 1% of the spacing>), ...)`, so the files are the area
  files of that box and RFC-007's coverage check applies unchanged. The widening is arithmetic on the polygon's own
  extent, not on the grid.
- `run_site`: downloads, `merge_netcdf_to_dataset(..., node_selection='area', polygon=..., node_mean=...)`, then writes
  `<name>_<domain>_<freq>_area_<start>_<end>.nc`. No used node (the polygon is outside the domain) fails the site with
  `The boundary overlaps no BARRA2 node of AUS-11; check its coordinates.`
- Summary: `inputs` gains `polygon` (`source`, `vertices`, `holes`, `bbox`, `area_km2`, `sha256` of the vertex list, so a
  changed file shows) and `node_mean`; `selection` stays `area`. `nodes` lists every used node, in latitude then longitude
  order, with `lat`, `lon`, `overlap`, `weight`, `orog` and `distance_km` from the centroid, plus `sub_cell` and `covered` on
  the site entry (`inputs`), so the GUI can draw the nodes used and their weights from the summary alone (the owner's slice 5
  requirement). A plain box `area` summary keeps `count` and the `orog` range; listing its nodes is a slice 5 question.
  New keys are additive, so `schema_version` stays 1.

### Options considered

| Question | Options | Choice |
|---|---|---|
| Several parts (**Q1**) | a. refuse a `MultiPolygon` and multi-feature files, asking for one site per part (**recommended**); b. accept them as one boundary (the overlap is the sum over parts; holes per part) | a: the weights, the centroid and the sub-cell test are all clearer for one outline, and a farm in two blocks is two sites to compare. b is a small extension if wanted. |
| Output for a boundary (**Q3**) | a. netCDF only (**recommended**); b. also a csv per used node, as `nodes` writes | a: a boundary can use hundreds of nodes on AUST-04, and the site mean as a csv can be added later without a decision now. |
| Size guard (**Q4**) | a. error above 2,500 nodes from the bounding box (**recommended**); b. no guard; c. a warning only | a: a continent-sized polygon would otherwise start tens of thousands of requests. The bound is a setting-free constant; raise it if wanted. |
| Geometry home | a. `mapping.py` (**recommended**, as planned); b. a new `boundary.py` | a: about 300 lines more, still one concern (geometry on the grid); splitting later changes only imports. |
| Weights | a. cell overlap area x cos(lat) (**owner decision**); b. equal; c. inverse distance | a |
| Several points for one site (**Q5**) | a. each point its own site; b. a site group sharing one download | Owner: skipped. A site is a boundary or user-defined points. |

### Tests (offline unless marked live)

- **Fixtures.** Hand-written boundary files in `tests/data/`: a simple GeoJSON polygon over two of the 3 x 3 grid cells, one with
  a hole, a sub-cell polygon straddling a cell boundary, a `Feature`/`FeatureCollection`/`MultiPolygon`/KML twin of the first,
  a legacy-`crs` file, and bad files (open ring, self-intersecting, one vertex, projected `crs`, KML with a `DOCTYPE`, KMZ
  bytes). No download is needed; the series come from the existing `grid_AUS-11_*` fixtures.
- `tests/test_mapping.py`: `Polygon` validation (each fault above, one message each); `contains` with a hole;
  `centroid` of a square, an L shape and a zero-area ring; `cell_overlap` against hand-computed fractions (a polygon
  covering exactly one cell is 1.0; half of a cell is 0.5; a hole subtracts; a polygon touching an edge only is 0); the
  **sum of overlap areas equals the polygon area** when the grid covers it (property, several shapes, concave included);
  the readers (GeoJSON `Polygon`, `Feature`, `FeatureCollection` of one, lon-lat order, third value ignored, legacy `crs`, KML with and
  without a namespace, holes) and their refusals, each with its message; `read_polygon` by suffix and an unknown suffix.
- `tests/test_merge.py`: the area Dataset with a polygon masks unused nodes to missing, has `cell_overlap`/`cell_weight`
  with weights summing to 1; with `node_mean` the `_site_mean` series equals the hybrid mean computed by hand for two
  weighted nodes (speed scalar, direction vector, speed not equal to `hypot` of the mean components); a sub-cell polygon uses
  one node (the one holding the centroid, found on a centroid at a cell edge too) with weight 1; a polygon outside the grid
  raises; `area` without a polygon is unchanged.
- `tests/test_project.py`: each validation row; `load_project` with `polygon` relative to the file; `plan_site` lists
  the widened-box files; `run_site` with a polygon site writes the netCDF and the summary (`inputs.polygon`, `nodes` entries
  with `overlap`, `weight`, `sub_cell`, `covered`); a polygon file that changes keeps its name but changes `sha256`; no used
  node fails the site; the cache check still refuses files for another box.
- `tests/test_package.py`: nothing new beyond `__all__` resolving.
- Live (`BARRA2_LIVE=1`): **NCSS returns every used node**, for a polygon on AUS-11 and one on AUST-04 (each node with
  `cell_overlap > 0` is in the downloaded grid), a boundary that straddles cell edges exactly (a polygon whose edges lie on
  cell edges, built from a `nearest_nodes` lookup, never computed), and one month of `run_site` for a polygon site with `node_mean` on
  both domains.

### Examples and docs

- `scripts/example_boundary.geojson` (a small outline near the example sites) and a `polygon` site in `scripts/example_project.toml`;
  a cell in the netCDF example (`.py` and `.ipynb`, kept in step) that reads the boundary, prints the cell overlaps and
  runs the site.
- `docs/how-to-use.md`: "Site boundary" (files accepted, the rule, sub-cell, the mean and its weights, why the mean is
  not for extremes, what the output variables are). `CONTEXT.md`: **Boundary**, **Cell overlap**, **Site mean**. README
  one-liner. `docs/modules.md` needs nothing. No new ADR and no new dependency.

### Not in scope, noted for later slices

- Slice 5: drawing a polygon on the map, importing a boundary file in the GUI, drawing the nodes used from the summary
  (`nodes` entries above), and whether a plain box `area` summary should list its nodes too.
- Backlog: csv for a boundary, `MultiPolygon` support, shapefile, a
  node-inside-polygon filter (the owner's alternative inclusion rule), and antimeridian polygons.

### Acceptance

- `Polygon` and the two readers accept the formats above and refuse the faulty files with one clear message each.
- `cell_overlap` matches hand-computed fractions and its areas sum to the polygon's.
- A polygon site loads from a project file, validates (each row above), plans, runs and writes the netCDF with the mask,
  `cell_overlap`, `cell_weight` and, on request, `<var>_site_mean`; the summary lists the nodes used with their weights.
- A sub-cell polygon uses exactly the node whose cell holds its centroid.
- The live tests show NCSS returns every used node on both domains.
- `make check`, `make test`, `make docs-test`, the live tests and an end-to-end run of the example project in a scratch
  folder pass, with no suppression added; the example pairs are in step.

### Decisions

Owner's answers of 2026-10-31; the option tables above are the reasoning.

1. **Several parts:** a `MultiPolygon` or several features are refused, with a message asking for one site per part.
2. **Sub-cell:** a polygon whose bounding box is under one grid spacing in both latitude and longitude uses the one node whose
   cell holds its centroid.
3. **Output:** netCDF only. A boundary cannot be written as csv.
4. **Size guard:** error above 2,500 nodes. The owner asked for the size of a 1 GW farm to be estimated and the limit used if
   it is under 2,500. At 2 MW/km² (a conservative onshore density; offshore is higher) 1 GW is about 500 km², a 22 km square
   or a 50 km x 10 km strip. A cell is about 137 km² on AUS-11 and 18 km² on AUST-04 near -23°, so the bounding box holds about 9
   to 12 nodes on AUS-11 and 35 to 45 on AUST-04. At 1 MW/km² on AUST-04 it is still under 150. 2,500 leaves more than an order
   of magnitude of headroom, so it stands. The figures are a rough estimate, not measured.
5. **Turbine points:** out of scope. A site is either a boundary or user-defined points (a point, the four around it, or chosen
   `nodes`). No site group is planned and none goes in the backlog.

## Slice 3 addendum: toolkit spikes and ADR-005 (`docs/gui-toolkit-adr`)

Written 2026-10-31, when slice 3 started. **Status: proposed, for the owner's review. Nothing is built, installed or added to the
repo's dependencies until the owner approves this addendum.** It does not reopen RFC-005 section 8, the section 9 answers, ADR-004,
or the slice 1b, 2 and 2b owner decisions.

**Scope.** Choose the GUI toolkit (RFC-005 5.2, decision 3) by building the same thin slice in six candidates, scoring them on
fixed criteria, and recording the choice as ADR-005. Spike code is throwaway: it is never merged to `main`. The slice's PR holds the
ADR, a research note with the evidence, and plan updates, and nothing else. Out of scope: the GUI skeleton (slice 4), the real map
and imports (slice 5), any `gui` extra, `barra2_dl/gui/` code, a CLI, and a Windows executable (decision 4).

### Decisions already made (not reopened)

| Question | Decision |
|---|---|
| How the toolkit is chosen | Time-boxed spikes of one thin slice, judged on look and ease of use for a non-programmer; owner prefers Streamlit or a similar web interface (RFC decision 3) |
| Candidates | Streamlit, NiceGUI, Panel, Dash (Plotly) and Flet are built; tkinter is judged on paper only, as the baseline (owner, 2026-10-30). A sixth spike, a Jupyter notebook with `ipywidgets` and `ipyleaflet`, served as an app with Voila, was added by the owner on 2026-10-31 |
| Layering | `barra2_dl/gui/` beside the library; the library never imports an interface; an interface imports only `__all__` names (ADR-004) |
| Map | The nodes selected or used for a site are drawn on the map, not only listed (owner, 2026-10-31); drawing a polygon on the map is a criterion |
| Packaging | Optional `gui` extra and entry point `barra2-dl-gui = "barra2_dl.gui:main"` (RFC 5.3); no executable in v1 |
| Console output | Keep the log-and-print convention for now; revisit at slice 4 (section 9, answer 3). The convention is the owner's to change |

### Proposed decisions (for the owner)

| # | Question | Proposal |
|---|---|---|
| A | Time box | 4 hours of work per spike, a hard stop. A feature not working at the stop is scored as not working and noted, not finished. About 24 hours of spikes, 1 hour for tkinter on paper, 3 for the note |
| B | Where spike code lives | Branch `chore/gui-toolkit-spikes` (a Conventional Commits type, so the branch-name check passes), in `spikes/<toolkit>/` plus `spikes/common/`. Never merged and never a PR. Pushed so the work is not lost, and tagged `rfc005-spikes` when the spikes finish, so ADR-005 can cite a commit that stays reproducible. See "Options: where spike code lives" |
| C | Environments | Each spike installs into its own scratch virtual environment outside the repo (`uv venv` under the scratchpad folder, `uv pip install -e <worktree>` plus the spike's `requirements.txt`). The spike branch never changes `pyproject.toml` or `uv.lock`; `git diff main -- pyproject.toml uv.lock` must be empty, and `uv sync` is never run with toolkit packages |
| D | Evidence home | A research note, `docs/development/research/gui-toolkit-spikes.md` (raw evidence: scores, timings, sizes, pin checks, screenshots, the `uv pip freeze` of each spike), and ADR-005 (the decision, short, linking the note). Screenshots are small PNGs in `docs/development/research/gui-toolkit-spikes/` |
| E | Scoring | Hard gates (pass or fail) and weighted criteria scored 0 to 4, below. Claude scores the measurable criteria with evidence; the owner scores looks and ease after running each spike. The owner's scores replace Claude's on those two |
| F | Decision rule | A toolkit failing a gate is out unless the owner waives that gate. Among the rest, the weighted score ranks them and the owner decides, taking the ranking, the evidence and their stated preference into account. There is no automatic winner and no automatic tie-break |
| G | Spikes without the network | A shared fake NCSS server (`spikes/common/fake_ncss.py`) patches `requests.get` from the `tests/data/` fixtures, with a short delay per file so progress and cancel are visible. It is the one thing a spike uses beyond the public API, because it stands in for the network. It works only for the fixture points (`scripts/build_test_fixtures.py`). A switch (`SPIKE_LIVE=1`) turns it off for one real month, run once per spike so the owner sees real data |
| H | Map and draw libraries | Left to the spike author within the time box, from the candidates in the table below. A toolkit with no usable polygon drawing scores 0 on that criterion and the workaround, if any, is noted. The health of a third-party map component counts under maintenance, because the GUI would depend on it too |
| I | Other toolkits | Gradio, Reflex, pywebview with HTML, Qt (PySide6) and Textual are not built. ADR-005 names each in one line under alternatives, from paper, so the record shows they were considered. The owner's list of six stands. Solara, which is built on the same notebook widgets, is named in the notebook spike's alternatives |

### The thin slice every spike builds

One page, built the same way in every toolkit, calling only `__all__` names of `barra2_dl` modules (ADR-004 rule 1) and `globals`
constants; no private name, and no logic that a second interface would need (rule 3). Anything that is not widgets, layout, state or
threading, and that a spike author has to write, is a finding for the engine, not code to keep.

1. **Form to `Settings`/`Site`.** Fields: latitude and longitude (or, after a polygon is drawn, the polygon), start and end date,
   domain, frequency, preset and node selection (`nearest`, `average4`, chosen `nodes`), with choices from `BARRA2_DOMAINS`,
   `BARRA2_FREQS`, `BARRA2_PRESETS` and `BARRA2_NODE_SELECTIONS`, never retyped. A site name and the output folder (a scratch one).
   The form builds the dataclasses through `site_from_dict` or the constructors, calls `project.validate` and shows each `Problem`
   against the field named by its `key`; invalid combinations (`20min` on AUS-11) are shown, not hidden.
2. **Map: site and nodes.** On "Find nodes", call `mapping.nearest_nodes` and draw the site and the returned nodes, each popup
   or tooltip showing `distance_km`, `orog` and `sftlf`. The user can pick which nodes to use (click a node or tick a list),
   which sets `Site.nodes`. Nodes picked are drawn differently from those only offered. A click on the map also sets the site
   point.
3. **Map: nodes used after the run.** At the end of a run the nodes in the run summary (`site_result_to_dict(result)['nodes']`)
   are drawn on the map, requested position and actual node, so the "used" half of the owner's requirement is shown too.
4. **Polygon drawing.** Draw a polygon on the map, convert it to GeoJSON text and build a `Polygon` with
   `mapping.polygon_from_geojson`; a `BoundaryFileError` is shown as an error. A drawn polygon makes the site a boundary site.
   (A pre-run preview of the nodes a polygon will use is not in the engine; if a spike author wants it, it is a finding for slice
   5, not spike work.)
5. **Background run.** `project.plan_site` shows "N files, M cached". "Run" starts `project.run_site(site, settings, progress,
   cancel)` on a worker thread; the callback drives a progress bar and a "file i of n" line; "Cancel" sets the
   `threading.Event`. The page stays responsive while it runs (the form can be read and the map panned), and a second browser tab
   or a page reload during a run is observed and recorded, not fixed.
6. **Run summary.** At the end show `site_result_to_dict(result)`: status, outputs, missing months, the files table, nodes and
   their distances. A `failed` run (the fake server can return a 404 for one variable) and a `cancelled` run both display.
7. **One command.** A `main()` in `spikes/<toolkit>/app.py` that starts the server (or window) and opens the browser, shaped as
   the future `barra2_dl.gui:main` would be.

### Candidates and the map and draw components to try

The component names are starting points from the author's knowledge at the time of writing; the spike confirms what exists, works
and is maintained, and the exact versions go in the note.

| Candidate | Model | Map and polygon drawing to try | Questions the spike must answer |
|---|---|---|---|
| **Streamlit** | Script reruns on each interaction | `streamlit-folium` with folium's `Draw` plugin (returns drawn GeoJSON); `pydeck` has no draw tool | A worker thread needs the script run context to update widgets; what survives a rerun, a reload and a second tab; how `main()` launches `streamlit run`; usage statistics and other outbound calls at start-up; whether one process can share a server with an API (ADR-004 asks) |
| **NiceGUI** | Event-driven on FastAPI | Built-in `ui.leaflet`, with its draw control | Looks out of the box; date and file widgets; the native-window mode and what it needs; per-client state; FastAPI shared with an API |
| **Panel** | Event-driven (Bokeh server, Param) | `ipyleaflet` with `DrawControl`, or `folium` | Dependency weight and pins (bokeh, param, numpy, pandas); time to a good-looking page; updating widgets from a thread |
| **Dash** | Callbacks on a Flask server | `dash-leaflet` with `EditControl` | Background callbacks against a plain thread polled by `dcc.Interval`; extra dependencies for background callbacks; look |
| **Flet** | Flutter client, Python backend | `flet-map` (polygon layers and tap events; check whether drawing is built in or has to be built from taps) | Whether polygon drawing is possible in the time box; desktop window versus web mode; the cost of freezing a desktop build, the one candidate where that is the point; Python 3.14 support of the client |
| **Notebook** (`ipywidgets`, `ipyleaflet`, Voila) | Widgets in a Jupyter kernel; Voila serves the notebook as an app with the code cells hidden | `ipyleaflet` with `DrawControl`, which Panel's `ipyleaflet` route also uses | Run both as a notebook and under Voila, and score the Voila app mode, which is what an analyst would use; the kernel is busy unless `run_site` is on a thread, so progress and cancel need the worker-thread pattern; how `barra2-dl-gui` would launch Voila on a shipped notebook (G7); the Jupyter dependency set against the library's pins; testing with `nbclient` and no display; freeze cost (expected poor); whether `scripts/*.ipynb` and the jupytext pairs could share code |
| **tkinter** (paper) | Event loop, standard library | `tkintermapview` (a tkinter map widget with polygons) | Judged from documentation only, not built: look, map and drawing, thread hand-off through a queue and `after`, display-free testing, freezing cost |

### Criteria and how each is scored

**Hard gates** (pass or fail, from the built spike; for tkinter, from paper). A failure removes the toolkit unless the owner waives it.

| Gate | Passes when |
|---|---|
| G1 Public API only | The spike imports only `__all__` names and `globals` constants, and all slice items except polygon drawing work |
| G2 Nodes on the map | Offered, chosen and used nodes are drawn on the map and distinguishable |
| G3 Cancel | Cancel stops a run through the progress callback and event, and the result reads `cancelled` |
| G4 Install | Resolves against the library's pins with no loosening of numpy, pandas, xarray or requests, on Python 3.12, 3.13 and 3.14, on Windows |
| G5 Licence | The toolkit and the components used are MIT, BSD or Apache-2.0 (or the same family), compatible with the planned MIT relicence; checked from the installed metadata, not from memory |

**Weighted criteria**, each 0 to 4 (0 absent, 2 workable with effort, 4 excellent), with the evidence kept:

| # | Criterion (weight) | How scored |
|---|---|---|
| 1 | Looks, for wind analysts (20) | Owner's score from running the spike, with screenshots at desktop width and a narrow laptop width, light and dark if the toolkit has both |
| 2 | Ease of use for a non-programmer (10) | Owner's score: can an analyst find the next step unaided; one command starts it; date and file inputs; error messages |
| 3 | Map quality (10) | Tiles and zoom, popups, selecting nodes by click, distinguishing offered, chosen and used nodes, needing the internet only for tiles |
| 4 | Polygon drawing (15) | A polygon drawn, edited and deleted, yielding a valid GeoJSON `Polygon`; 0 if absent |
| 5 | Background run (15) | Progress and cancel work; page responsive; behaviour on reload and on a second tab; how much threading code the toolkit asks for |
| 6 | Install and pins (10) | Install size beyond the library's own dependencies (MB, files), new packages, resolution time, pin tension, wheel availability for 3.14 on Windows, outbound calls and telemetry at start-up |
| 7 | Packaging and testing (10) | The `gui` extra and `barra2-dl-gui` entry point shape; one command; whether a smoke test can drive a fake download with no display (the toolkit's own test harness, or a headless browser) and what it costs |
| 8 | Maintenance and licence health (5) | Last release date, cadence, open-issue trend, maintainers, health of the map component, licence history |
| 9 | Freeze cost (5) | What a later executable would take. Measured only for Flet (one timed attempt with its build tool); paper for the rest |
| - | Code size (not scored) | Lines in the spike and how many were toolkit plumbing; shown as a tie-break aid |

The weights sum to 100; the owner may change them before the spikes start. A toolkit's score is the sum of weight x score / 4.

### Console output: what the spikes observe

The convention logs and writes progress to stdout. From a worker thread a GUI server prints that to its console. For the same
one-year run on the fake server, each spike records: (a) lines written to the server console, and whether the toolkit captures,
duplicates or hides them; (b) whether a `logging` handler on the `barra2_dl` logger can feed a log pane in the UI, and whether the
progress callback alone is enough for a user; (c) whether redirecting stdout in the worker is safe (it is process-wide, so likely
not in a threaded server). The note ends with the findings and a recommendation among the options already on the table (keep the
dual pattern; the library logs and interfaces print; a `verbose` argument). **Changing the convention is the owner's call, made at
slice 4**; this slice only produces the evidence.

### Options: where spike code lives

| Option | For | Against |
|---|---|---|
| **a. A never-merged branch with `spikes/`, tagged (proposed)** | Same repo, same hooks, reproducible from a tag, the ADR can link a commit, no new account or repo | The pre-commit hooks (ruff check and format) run on spike code, so it must pass them (never suppressed); a pushed branch may trigger CI jobs, whose failures are noise to tidy |
| b. A scratch folder outside the repo, not in git | No hooks, no clutter | Not reproducible later; the ADR could not point at anything |
| c. A separate public repository | No hooks or CI of this repo | The owner must create and keep it; a second place to look; more than six small apps need |

### Packaging and `pyproject.toml` during the spikes

Nothing changes in the repo's dependencies. There is no `gui` extra, no `[project.scripts]` entry and no `uv.lock` change in this
slice or on the spike branch. Each spike's `requirements.txt` lists only its toolkit and components. The pin check (criterion 6)
resolves them together with the library's own dependencies in a scratch environment for Python 3.12, 3.13 and 3.14
(`uv pip compile`, then an install per version), recording the versions chosen for numpy, pandas, xarray, h5py and requests and
whether any differs from the library's current lock. The `gui` extra is added at slice 4 with the chosen toolkit, and `deptry` and
the lockfile check start covering it then.

### The ADR

`docs/development/adr/ADR-005-gui-toolkit.md`, "Status: Proposed" until the owner accepts it, with a row in `adr/README.md`. It
follows the ADR README (context, decision, alternatives and why they lost, consequences):

- **Context.** RFC-005 5.2, the owner's preference, the thin slice, the gates and criteria in short.
- **Decision.** The chosen toolkit and map/draw component, with the versions the spike used.
- **Evidence.** The scoring table (all six plus tkinter on paper), the gates, and links to the research note and the
  `rfc005-spikes` tag with its commit.
- **Alternatives considered.** Each of the others and why it lost, in one or two lines; the toolkits in decision I, one line each.
- **Consequences.** The shape of `gui/` and `main()` for that toolkit; the threading pattern slice 4 must use; the `gui` extra's
  pins; the console-output findings and the choices for slice 4; the freeze cost; whether an API could share its server (ADR-004's
  note); the map component's maintenance risk and the fallback if it is abandoned; what the spikes could not settle.

The decision rule is proposal F. ADR-005 does not replace ADR-004, and a toolkit later dropped gets a superseding ADR.

### Tests and acceptance

There is no library code, so no unit tests. Acceptance:

- ADR-005 is merged with the decision, the scoring table, the alternatives and the consequences listed above, and its row in
  `adr/README.md`.
- `docs/development/research/gui-toolkit-spikes.md` and its screenshots are merged and listed in `research/README.md`. The findings
  are reproducible: for each spike it gives the tag and commit, the exact commands, the Python version, the full `uv pip freeze`,
  the date, and how each number (install size, timings, line counts) was measured.
- **No spike code, dependency or `gui` extra is on `main`**: the slice's diff touches only `docs/development/` and no file under
  `src/`, `tests/`, `scripts/`, `pyproject.toml` or `uv.lock`. The spike branch's diff to `main` for `pyproject.toml` and `uv.lock`
  is empty.
- The owner's scores for looks and ease are in the note, with the date of the walkthrough.
- `make check` and `make docs-test` pass with no suppression added. (`make test` is not required: no code changes.)
- The slice 4 addendum can start from the ADR with no open toolkit question; anything the spikes could not settle is a named open
  item in the ADR.

### Timeline (each step waits for the owner's go)

| Step | What | About |
|---|---|---|
| 0 | Owner reviews and approves this addendum (this PR) and answers its questions | owner |
| 1 | Set up: spike branch and worktree, `spikes/common` (fake NCSS server, shared form spec, scoring sheet), scratch environments, and a pin and wheel dry run for all six on 3.12 to 3.14. A toolkit failing G4 or G5 outright is flagged to the owner now, before time is spent on it | 2 h |
| 2 | Spike 1 Streamlit, then spike 2 NiceGUI (the likelier choices). Optional checkpoint: the owner looks at these two before the rest | 4 h each |
| 3 | Spikes 3 to 6: Panel, Dash, Flet (including the freeze attempt), notebook with Voila | 4 h each |
| 4 | tkinter on paper | 1 h |
| 5 | The note: measurements, console-output findings, Claude's scores, screenshots | 3 h |
| 6 | Owner's walkthrough: run each spike with one command, score looks and ease (about 10 minutes each), choose | owner |
| 7 | ADR-005 written to the owner's choice; spike branch tagged; PR `docs: ADR-005 GUI toolkit (slice 3)`; merge. The slice 4 addendum follows | 2 h |

### Not in scope, noted for later slices

- Slice 4: the `gui` extra, `barra2-dl-gui`, the skeleton, the real threading pattern, the display-free smoke test, the
  console-output decision, and the cache-mismatch rename flow (slice 1 decision F).
- Slice 5: a pre-run preview of the nodes a polygon will use, the optional node layer, imports, the summary view, and listing the
  nodes of a plain box `area` in the summary (backlog).
- A hosted or multi-user deployment, an executable, and any change to the engine; a gap the spikes find in the engine is reported in
  the note and the ADR, not fixed here.
