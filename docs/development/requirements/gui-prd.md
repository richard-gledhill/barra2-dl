Status: Draft

# RFC-005: GUI for wind resource assessment

| | |
|---|---|
| Raised by | atl3b, in [issue #59](https://github.com/richard-gledhill/barra2-dl/issues/59), with a proof of concept in the fork [atl3b/barra2-dl-wr](https://github.com/atl3b/barra2-dl-wr) (v0.5.0, commit `0f1a360`). The GUI is a fresh build; credit atl3b as the person who raised the feature. |
| Depends on | [RFC-001](wind-variables-bugfix-prd.md) (Done), [RFC-002 parameter review](parameter-review-prd.md), [RFC-003 netCDF output](netcdf-output-prd.md); see the [roadmap](wind-engineering-roadmap-prd.md#4-rfc-roadmap) |
| Replaces | RFC-004 (CLI), dropped on 2026-10-30. Its engine and project file are folded in here (5.5, 5.6); the command-line tool is deferred to the backlog |
| Drafted | 2026-10-28, updated 2026-10-30 with the owner's decisions (section 8) |

## 1. Summary

Give analysts who don't write Python a GUI where they can:
- pick sites on a map;
- choose the BARRA2 domain, frequency, preset, node selection and date range;
- get a merged, converted file for each site.

The library stays the product: the GUI is a thin, optional front end over the same public functions a script uses.
This RFC also adds what both of them need to run a batch of sites (5.5, 5.6):
- an engine function, `run_site`, that runs one site end to end;
- a TOML project file listing sites and shared settings, also usable from the example script;
- retries, a result for every downloaded file, and a run summary.

These came from RFC-004, which planned a separate command-line tool on top of them. That RFC was dropped (decision
6): wind analysts will use the GUI and Python users the script. The command-line tool itself is in the backlog,
as a small add-on once this engine exists.

The GUI is a **fresh build** (decision 1). It isn't a port or merge of the atl3b fork, which branched from upstream
v0.2.0, keeps its business logic inside the GUI class and has a critical grid bug for AUST-04 (section 3). The fork
proved the demand and supplied several ideas (3.3). atl3b is credited as having raised the feature, in the README,
the docs and the release notes.

The toolkit is chosen by spikes (5.2), with a web-style interface such as Streamlit as the current preference.

## 2. Motivation

- Wind farm developers and resource analysts want a long-term reference series for a mast or site, not a Python
  workflow. Today they must edit `scripts/example_barra2_dl.py`.
- Choosing the right grid node matters: the user needs to see which BARRA2 node(s) surround the site and how far
  away they are before downloading years of data.
- A GUI is the lowest-friction way to show that, and to run multi-site, multi-node batches.

## 3. Review of atl3b/barra2-dl-wr

Tested in an isolated clone and Python 3.12 venv outside this repository, against the live NCI THREDDS server, on
2026-10-28.

### 3.1 Does it work?

Mostly, for AUS-11.

| Check | Result |
|---|---|
| Install (`pip install pandas requests pywebview folium`) | Works. `pywebview` and `folium` are not declared in its `pyproject.toml`. |
| `pytest tests` | 38 passed (61 s). |
| Bare `pytest` (repo root) | Fails at collection: `scripts/example_barra2_dl.py` runs a download at import and raises `FileNotFoundError` for `scripts/cache`. |
| GUI start-up (`Barra2GUI` built and a coordinate added, headless smoke test) | Works; four candidate nodes found per coordinate. |
| AUS-11 node maths (`find_nearest_four_grid_points`) vs the shipped 698,972-node `BOM_BARRA2_AUS11_latlon.csv` | 8,000 of 8,000 corners from 2,000 random Australian sites are real grid nodes. |
| Live download, AUS-11, `ua50m`/`ua100m`/`tas`/`rsds`/`ta50m` | HTTP 200, about 3 s per variable-month. |
| `ruff check` / `mypy` on the fork | 59 and 27 errors respectively (it predates this repo's ruff/mypy setup). |

### 3.2 Defects

1. **AUST-04 grid is wrong (critical).** `BARRA2_GRID_PARAMS['AUST04']` uses 0.44° spacing and the README calls
   AUST-04 "~50 km". AUST-04 (BARRA-C2) is 0.04° (about 4.4 km): an NCSS bounding-box request near Sydney returns
   nodes at -33.89, -33.85 … and 151.14, 151.18, 151.22 …. For a site at (-33.87, 151.21) the fork offers "grid
   points" 18-45 km away that are not AUST-04 nodes. NCSS silently snaps each request to the nearest real node, so
   the user gets data from somewhere other than the node shown on the map, and the filenames and labels are wrong.
2. **Logic lives in the GUI.** `_download_worker` is a 230-line method in the tkinter class that re-implements
   downloading (its own `ThreadPoolExecutor` and `requests.get`), timestamp shifting, merging, unit conversion and
   column selection. None of it is reachable from a script or testable without Tk, and there are no tests for the
   GUI, `grid_finder.py` or `map_viewer.py`.
3. **The cache is edited in place.** `pr` and `rsds` CSVs are rewritten with times shifted -30 min, so the cache
   folder no longer holds what the server returned. The shift is decided from the first row only and wrapped in
   `except Exception: pass`.
4. **Failures are hidden.** Errors are reduced to a status-bar string, skipped files count as successes, and a site
   with missing months is still merged and written without a warning. There is no retry, back-off or cancel.
5. **Variable list.** It correctly drops heights the server doesn't have, but its README says only 5 heights
   exist. In fact `uas`/`vas` (10 m) and `ua1500m` also exist, and so do pressure-level winds (`ua1000`, `ua850`).
   Upstream has the mirror-image bug (placeholder heights); see [RFC-001](wind-variables-bugfix-prd.md).
6. **Packaging.** Poetry, `python = "^3.10"`, GUI under `scripts/` with `sys.path` hacks, so it can't be installed
   and run as a command.
7. **Minor.** The bounds error prints the east limit as `-152.61`; comments mix English and Chinese; the map needs
   internet access for tiles.

### 3.3 Ideas worth adopting

- Four surrounding nodes per site, each with distance, selectable independently (lets an analyst pick the most
  representative node or average them).
- Map preview of site and nodes (folium).
- Environment variables for density and icing work: `tas`, `hurs`, `ps`, `ta50m`, `pr`, `rsds`.
- Unit conversions (K → °C, Pa → hPa, flux → mm/h).
- Atomic writes (temporary file, then rename) and skipping empty responses.
- Per-node cache sub-folders and a progress bar by file count.

Because the GUI is a fresh build, no fork code is copied. These ideas are reimplemented, so the MIT relicence
(roadmap, decision 9) needs no agreement from atl3b.

## 4. Goals and non-goals

**Goals**
- G1. Pick one or more sites (type coordinates, paste a list, or load a CSV of masts or a project file, 5.5)
  and see the surrounding BARRA2 nodes for the chosen domain, with distances, on a map.
- G2. Choose the domain (AUS-11 default; AUST-04), the frequency (`1hr` default; AUST-04 `20min`), an RFC-002 preset
  (`wind+density` default) and a date range.
- G3. Choose the node selection (RFC-003): **nearest node** or **four-node average** for CSV and netCDF, and
  **area download** for netCDF only. The GUI disables combinations the library doesn't support, such as an area as
  CSV, or a preset at a frequency missing its variables.
- G4. Run the download in the background with progress, cancel and resume (the existing idempotent cache).
- G5. Write one output file per site, in CSV or netCDF (RFC-003).
- G6. Show a clear end-of-run report: months missing, nodes used (requested vs actual node returned by NCSS),
  `orog` per node.
- G7. Installable as `pip install barra2-dl[gui]` with a `barra2-dl-gui` command. No single-file Windows executable
  in v1 (decision 4).
- G8. A public engine, `run_site`, and a TOML project file, `load_project`, shared by the GUI and the example
  script (5.5).
- G9. Downloads retry transient failures, report a result for every file and write a run summary per site (5.6,
  5.4).

**Non-goals**
- Wind analysis inside the GUI (rose plots, Weibull, MCP). Those belong in the output formats and third-party tools
  (roadmap).
- A hosted web service or multi-user deployment. A web-style toolkit such as Streamlit still runs locally, on the
  user's own machine, for one user.
- A Windows executable in v1.
- A command-line tool (`barra2-dl point …`, `barra2-dl run project.toml`). It's deferred to the backlog (decision 6).
  The engine in 5.5 is shaped so that it can be added later in about 100 lines.

## 5. Proposed design

### 5.1 Library first

Everything the GUI needs lives in the library, so the GUI and scripts share it:

| Public function (indicative) | Module | From RFC |
|---|---|---|
| `nearest_nodes(point, domain, n=4) -> list[GridNode]`, from a bounding-box request of real nodes | `mapping.py` (replaces the draft `_find_nearest_point`) | RFC-003 5.6 |
| `point_data_urlfilenames(..., node_selection=...)`, `area_data_urlfilenames(bbox, ...)` | `download.py` | RFC-003 |
| `download_multithread(..., progress=callback, cancel=event)`, with retries and back-off | `download.py` | This RFC, 5.6 |
| `load_project(path)`, `run_site(site, settings)` | new `project.py` | This RFC, 5.5 |
| `convert_units(df)` | `convert.py` | RFC-002 5.5 |

- **Node lookup uses the real grid.** Nodes come from a bounding-box request, never from arithmetic on a hard-coded
  origin (which is what caused the fork's AUST-04 bug). A test pins that every returned node is a node of the
  domain's grid.
- **Timestamps aren't shifted** (RFC-003 decision 1), so there is no `align_time` step.

This follows the conventions: functional modules, no orchestrator class, and the GUI is the only stateful piece.

### 5.2 Toolkit: chosen by spikes

The owner's preference is Streamlit or a similar web interface. The choice is made by time-boxed spikes that build
the same thin slice in each candidate. The slice is: a map with a site and its four nodes; a form for domain,
frequency, preset, node selection and dates; a background download with progress and cancel; and a result
summary. Spikes are judged on look, ease of use for a non-programmer, and the criteria below. The result is
recorded in an ADR.

| Candidate | For | Against / to test in the spike |
|---|---|---|
| **Streamlit** (current preference) | Quick to build; maps via `streamlit-folium` or `pydeck`; file upload for mast lists and project files | Reruns the script on each interaction, so a long download needs background-thread handling; runs a local server; hard to freeze |
| NiceGUI | Event-driven (no rerun model), built-in Leaflet map, good for long-running tasks | Smaller community; check the look |
| Panel | Strong mapping/data widgets (HoloViz), event-driven | Heavier dependency set; more setup |
| tkinter (baseline) | Standard library, no extra dependencies, easy to freeze later | Dated look; map has to open in a browser |

Criteria common to all spikes:
- Launches with one command (`barra2-dl-gui`).
- Works offline apart from the BARRA2 downloads and map tiles.
- A download of several years can be cancelled and resumed.
- Calls only public library functions.

### 5.3 Packaging

- Optional extra `gui = [...]` holding the chosen toolkit and map packages, so the core install stays lean.
- Entry point `barra2-dl-gui = "barra2_dl.gui:main"`. For a web-style toolkit, `main` starts the local server and
  opens the browser.
- No PyInstaller build in v1 (decision 4). Revisit after the GUI settles; web-style toolkits are harder to freeze,
  so the spikes should note how hard that would be.
- If a coverage threshold is set later, the GUI module may be excluded from it. The logic beneath it is covered by
  normal tests.

### 5.4 Run summary

`run_site` writes `<name>_run_summary.json` beside each site's output, and the GUI shows it as the end-of-run
report (G6). It holds:
- the inputs;
- package version, dataset version and download date (RFC-003 5.7);
- the result of every file: downloaded, skipped or failed (5.6);
- the requested and actual node(s): NCSS returns `-33.879` for a request at `-33.88`;
- `orog` per node;
- any missing months.

This gives the traceability energy-yield reviewers expect.

### 5.5 Engine and project file (from RFC-004)

**Project file.** TOML, read with the standard library's `tomllib`, so there's no new dependency (decision 7).

```toml
# scripts/example_project.toml
[settings]
domain = "AUS-11"
freq = "1hr"
preset = "wind+density"
node_selection = "nearest"
format = "csv"
start = "1990-01-01"
end = "2025-12-31"
cache = "cache"          # relative paths are relative to this file
out = "output"

[[site]]
name = "mast-north"
lat = -33.87
lon = 151.21

[[site]]
name = "mast-south"
lat = -34.10
lon = 150.95
node_selection = "average4"   # any setting can be overridden per site

[[site]]
name = "farm-area"
north = -33.70
south = -34.00
east = 151.30
west = 151.00                  # a box instead of lat/lon is an area download (netCDF only)
format = "netcdf"
```

- Defaults are those of the earlier RFCs: domain AUS-11 (decision 8), `1hr`, `wind+density`, `nearest`, CSV.
- Each `[[site]]` has a unique `name` and either `lat`/`lon` or a box, and can override any setting.
- Unknown keys are errors, so a typo like `domian` doesn't silently fall back to the default.
- Every problem is reported at once, with the site name and key.
- Invalid combinations are rejected before any request, with a message saying what to change: `20min` on AUS-11,
  `wind+density` at `20min` (RFC-002), or an area as CSV.

**Engine.** A new `src/barra2_dl/project.py`, exported from `__init__.py`:

```python
from barra2_dl import project

proj = project.load_project('scripts/example_project.toml')   # validated settings and sites
for site in proj.sites:
    result = project.run_site(site, proj.settings)              # the same call the GUI makes
    print(result.summary_path, result.missing)
```

- `load_project(path)` returns validated settings and sites as plain dataclasses. The GUI builds the same
  dataclasses from its form, so a project file and a form run go through one code path.
- `run_site(site, settings, progress=None, cancel=None)` builds the URLs, downloads, merges, converts, writes the
  output (RFC-003) and writes the run summary. It returns the result. It's a function, not a class, as the
  conventions require.
- It passes the deletion test: the GUI and the example script would otherwise each rebuild the pipeline, which is
  the fork's main defect.
- **Example script:** `scripts/example_barra2_dl.py` and its notebook gain a cell that loads
  `scripts/example_project.toml` and loops over the sites. The existing step-by-step cells stay, to show what
  `run_site` does underneath.

### 5.6 Downloads: retries, results and workers (from RFC-004)

- **Retries.** `_download_file` retries timeouts, connection errors and HTTP 5xx up to 3 times, with exponential
  back-off (1, 2, 4 s). A 404 isn't retried. HTTP failures are still logged and printed, not raised.
- **Results.** `download_serial` and `download_multithread` return one result per file: `downloaded`, `skipped` or
  `failed`, with the status code. They return `None` today, so callers that ignore the result are unaffected.
- **Workers.** A fixed, configurable pool (default 4, decision 11) replaces `cpu_count() - 1`. The right size
  depends on what load is polite for the NCI server, not on the CPU count.
- **Progress and cancel.** Optional callback and cancel-event arguments. The GUI drives its progress bar and Cancel
  button from them; a script can ignore them.
- **Batches.** A failing site doesn't stop the others in a project run. Its gaps are listed in its run summary,
  and the end-of-run report highlights failed sites (decision 12).

## 6. Testing

- **Project file:** a valid file round-trips through `load_project`. Unknown keys, duplicate site names, a site with
  both a point and a box, bad dates and invalid combinations are each reported, all in one error. Relative paths
  resolve against the file's folder.
- **`run_site`:** tested with `requests.get` faked and `tmp_path` folders. It writes the output and the run
  summary, resumes from a part-filled cache, and lists the missing months when a file fails.
- **Retries:** a 503 and then a 200 downloads once after one retry; a 404 isn't retried; each file reports
  `downloaded`, `skipped` or `failed` as appropriate.
- **Progress and cancel:** the callback sees every file; setting the cancel event stops new requests.
- **GUI:** a smoke test that needs no display builds the app and drives one fake download.
- **Live** (`BARRA2_LIVE=1`): `run_site` for one month on each `(domain, freq)`.

## 7. Rollout (thin slices)

1. Engine: `project.py` (`load_project`, `run_site`), retries, per-file results, progress/cancel and the run summary,
   with their tests. Example project file and example-script cell.
2. Library pieces from RFC-003 (node lookup, node selection) if not already built.
3. Toolkit spikes (5.2); ADR recording the choice.
4. GUI under `src/barra2_dl/gui/` calling only public API; a smoke test that needs no display.
5. Map preview, mast-list and project-file import, run summary view.
6. User docs: the GUI, the project file reference, and the note on why AUS-11 is the default (decision 8).
   "Raised by atl3b" credit in the README, the docs and the release notes.

## 8. Decisions

Decided by the owner on 2026-10-30:

1. **Fork:** fresh build, not a port or merge; credit atl3b as the person who raised the feature (1, 3.3).
2. **Node selection:** nearest node and four-node averaging for CSV; nearest, averaging and area download for netCDF
   (G3, RFC-003 5.6).
3. **Toolkit:** decided by spikes for the best-looking, most user-friendly option. The current preference is
   Streamlit or a similar web interface (5.2).
4. **Windows executable:** not in v1 (5.3).
5. **Timestamps:** kept as served, no shift (RFC-003 decision 1).
6. **RFC-004 dropped:** no command-line tool for now. Its engine and project file are folded into this RFC (5.5,
   5.6). The tool itself goes to the backlog.
7. **Project file:** TOML, in v1, also usable from the example script (5.5).
8. **Default domain:** AUS-11. User docs explain why: BARRA-R2 covers a wider area than BARRA-C2, and it ranked
   first, ahead of MERRA-2 and ERA5, in the CSIRO validation against 54 Australian wind farms. The CSIRO link
   returned 404 when last checked, so confirm the current URL before publishing.
9. **PyPI and licence:** the first PyPI release follows this RFC, after the code is relicensed to MIT (roadmap 3.2).
10. **Default output:** CSV, matching RFC-003; netCDF is one choice away (5.5).
11. **Parallel downloads:** 4 by default, configurable in the GUI and the project file (5.6).
12. **Failing sites:** a project run always carries on; each site's gaps are in its run summary, and the
    end-of-run report highlights failures (5.6).
