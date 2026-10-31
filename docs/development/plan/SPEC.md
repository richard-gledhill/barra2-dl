# SPEC: GUI for wind resource assessment (RFC-005), starting with the engine

Requirement: [RFC-005](../requirements/gui-prd.md); its decisions are in section 8 and are not reopened here.
Style and gates: [conventions.md](../conventions.md), [constraints.md](../constraints.md).

## Slice status

- Slice 1 (the engine) shipped in #147.
- Slice 1b (research) is in progress: see "Slice 1b addendum" at the end.

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
