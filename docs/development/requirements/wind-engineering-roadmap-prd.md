Status: Draft

# Research: making barra2-dl useful for wind energy assessment

| | |
|---|---|
| Audience | Wind farm developers and wind resource / energy-yield analysts |
| RFCs | The order is in [section 4](#4-rfc-roadmap) |
| Related | [backlog](../backlog.md) |
| Drafted | 2026-10-28 |

## 1. Where barra2-dl fits

In a wind energy assessment, a reanalysis series is used as the **long-term reference**: an on-site mast or lidar
measures 1-3 years, and measure-correlate-predict (MCP) against a 20-40 year reference corrects it to the long-term
climate. BARRA2 is attractive here: a CSIRO validation against 54 Australian wind farms ranked BARRA-R2 ahead of
MERRA-2 and ERA5 ([Environmental Science, ES24028](https://publish.csiro.au/ES/fulltext/ES24028)). Commercial tools
(Windographer, WindPRO, openWind) download ERA5 and MERRA-2 for free but not BARRA2, so getting BARRA2 into those
tools is the gap this project can fill.

The analyst's job is: pick the node(s) near the mast → get hub-relevant heights plus density inputs for the full
record → load into their analysis tool. Every item below is ranked against that job.

## 2. Correctness first

Found while reviewing the fork; these undermine trust and come before features.

| Issue | Evidence | Fix |
|---|---|---|
| `BARRA2_WIND_VARS` lists variables that don't exist | 11 of 18 pairs are placeholders that return 404; real height winds are `uas`/`vas` (10 m) and `ua50m`…`ua250m`, `ua1500m`. | [RFC-001](wind-variables-bugfix-prd.md). |
| Node actually used isn't reported | NCSS snaps `-33.88` to node `-33.879`; the CSV records it but nothing surfaces it. | Report requested vs actual node; nearest-node lookup on the real grid (RFC-005 5.1). |
| Silent failures | HTTP failures are logged, not raised (by design), but nothing summarises gaps. | End-of-run summary of missing variable-months; non-zero exit code in the CLI. |
| Mixed :00/:30 timestamps | `pr`, `rsds` are `time: mean`, stamped at :30. | Keep timestamps as served and document the convention; netCDF puts mean variables on their own time coordinate (RFC-003 5.4). |
| `cpu_count() - 1` threads for I/O | Thread count tied to CPU, not to server politeness; no retries. | Fixed, configurable pool (4-8), retries with back-off on 5xx/timeouts, `timeout=` on every request. |

## 3. Opportunities, ranked

Value is to a wind analyst; effort is rough relative size. This ranks value only; the delivery order is
section 4.

| # | Item | Value | Effort | Notes |
|---|---|---|---|---|
| 1 | Correctness fixes (section 2) | High | S | Prerequisite for everything else. RFC-001. |
| 2 | CLI | Medium | S | See 3.1. RFC-004 was dropped; the tool is in the backlog. Its engine is in [RFC-005](gui-prd.md). |
| 3 | **PyPI release** | High | S | `barra2-dl` is free on PyPI. See 3.2. |
| 4 | **Wind-software export formats** | High | M | See 3.3. The main differentiator. RFC-006. |
| 5 | Supported parameters and derived variables | High | M | See 3.4. [RFC-002](parameter-review-prd.md). |
| 6 | netCDF output | Medium-High | M | [RFC-003](netcdf-output-prd.md). |
| 7 | GUI | High | M-L | [RFC-005](gui-prd.md), with the engine and project file. Builds on 5 and 6. |
| 8 | Multi-site project file | Medium | S | A TOML listing masts and shared settings; used by the GUI and the example script ([RFC-005](gui-prd.md) 5.5). |
| 9 | Data-quality and summary report | Medium | M | Data recovery %, monthly/annual means, 12×24 diurnal-monthly table, wind rose PNG, inter-annual variability. Helps decide if a node is representative. |
| 10 | Gridded / area download | Medium | L | Existing backlog; via NCSS bbox or OPeNDAP. Feeds mesoscale maps and multi-node checks. |
| 11 | Python ecosystem bridges | Medium | S | See 3.5. |
| 12 | Documentation for analysts | Medium | S | A "BARRA2 for MCP" tutorial, variable/height table, citation and licence guidance, known limits of reanalysis (no TI, smoothed extremes). |
| 13 | conda-forge package | Low | S | After PyPI is stable. |

### 3.1 CLI (deferred)

RFC-004 was dropped on 2026-10-30: wind analysts will use the GUI, and Python users the example script. Its engine
(`run_site`), project file (`load_project`), retries and run summary are folded into [RFC-005](gui-prd.md). The
command-line tool is in the [backlog](../backlog.md). The notes below are kept as its design for when someone needs
headless or scheduled runs; it would be a thin layer over the RFC-005 engine.

`[project.scripts] barra2-dl = "barra2_dl.cli:main"`, built with **`argparse`**: it's in the standard library, so
there's no new runtime dependency (decided 2026-10-30).

```bash
barra2-dl nodes  --lat -33.87 --lon 151.21 --domain AUS-11 -n 4
barra2-dl point  --lat -33.87 --lon 151.21 --start 1990-01 --end 2025-12 --out site/
barra2-dl run    project.toml
```

- **Defaults:** domain AUS-11, frequency `1hr`, preset `wind+density` (RFC-002), node selection `nearest`
  (RFC-003).
- **Exit codes and dry run:** the exit code is non-zero when months are missing; `--dry-run` lists URLs and the
  file count.
- **Thin layer:** the CLI only calls the public API, like the GUI.
- **No export command yet.** An `export` subcommand arrives with RFC-006, which is now last.

**Project file (in v1).** A TOML file lists several sites (masts) plus the settings they share, and
`barra2-dl run project.toml` downloads and converts all of them. It's read with the standard library's `tomllib`.
The same file works from the **example script**: a public `load_project(path)` returns the parsed sites and
settings, so `scripts/example_barra2_dl.py` and its notebook can loop over them instead of hard-coding one point.
Ship an `example_project.toml` beside the scripts.

```toml
[settings]
domain = "AUS-11"
freq = "1hr"
preset = "wind+density"
node_selection = "nearest"
start = "1990-01-01"
end = "2025-12-31"
output = "netcdf"

[[site]]
name = "mast-north"
lat = -33.87
lon = 151.21

[[site]]
name = "mast-south"
lat = -34.10
lon = 150.95
```

**Default domain: AUS-11** (decided 2026-10-30). RFC-005 adds a user-docs note on why: BARRA-R2 covers a wider area
than BARRA-C2, and it ranked first, ahead of MERRA-2 and ERA5, in the CSIRO validation against 54 Australian wind
farms ([ES24028](https://publish.csiro.au/ES/fulltext/ES24028)). The CSIRO link returned 404 when last checked, so
confirm the current URL before publishing.

### 3.2 PyPI packaging

- **Timing:** the first PyPI release comes **after RFC-005**, once the GUI and its engine are in (decided 2026-10-30).
- **Release workflow:** `uv build` already works; add a workflow using PyPI **Trusted Publishing** (no API tokens)
  on a GitHub release, alongside the existing docs deploy.
- **Metadata:** classifiers and `project.urls` (Documentation, Changelog, Issues), and move to
  `Development Status :: 4 - Beta`.
- **Optional extras:** `[gui]` (and `[plots]` if added). xarray is a core dependency (RFC-003), so there's no
  `[netcdf]` extra.
- **Licence: relicense the code to MIT before the first PyPI release** (decided 2026-10-30). CC-BY-4.0 isn't
  OSI-approved, and Creative Commons recommends against CC licences for software. Keep the CC-BY-4.0 attribution
  for BARRA2 *data* in the docs. The GUI is a fresh build (RFC-005), so no atl3b code needs their agreement. Any
  other code contributors would.

### 3.3 Export to wind-engineering software

Analysts work in Windographer, WindPRO, openWind, WAsP, WindFarmer, WindSim and Meteodyn. Formats confirmed from
vendor docs; layouts need checking against each manual and a sample import before release.

| Target | Format to produce | Content |
|---|---|---|
| Windographer | Delimited text with a header block (Windographer auto-detects column layout); netCDF import to be verified | Time stamp, speed and direction per height, temperature, pressure. Column names Windographer recognises without manual mapping would save time; the exact names need testing. |
| WindPRO (METEO object) | Text time series | Same as above; used for MCP in WindPRO. |
| openWind | openWind time-series file | Speed, direction, temperature, density (TI not available from reanalysis). |
| WAsP | `.tab` observed wind climate | Frequency table: 12 (or 36) sectors × 1 m/s bins at one height, with header lat/lon/height. Generated directly from the series. |
| WindFarmer, WindSim, Meteodyn | Time series or `.tab` | Lower priority; follow demand. |
| brightwind (Python, MIT) | pandas DataFrame with a DatetimeIndex and its column naming | Gives free MCP, shear and long-term adjustment in Python. |

Proposed module: `export.py` with one public function per format, taking the merged DataFrame or Dataset. Golden
files in `tests/data/` pin each format.

### 3.4 Derived variables

| Variable | Method | Inputs |
|---|---|---|
| Wind speed / direction | Existing | `ua`, `va` |
| Shear exponent α | `ln(v2/v1) / ln(h2/h1)` per time step and as monthly/diurnal means | two heights |
| Veer | Direction difference between heights | two heights |
| Hub-height speed | Power law or log law from the nearest heights; interpolation preferred over extrapolation | heights, hub height |
| Air density | `ρ = p / (R_d T)`, corrected to hub height with a lapse rate or `ta50m`; humidity correction from `hurs` | `ps`, `tas`, `ta50m`, `hurs` |
| Gusts | Provide `wsgsmax` (available, verified) | |
| Icing risk flags | Temperature below 0 °C with high humidity, as a screening flag only | `tas`, `hurs` |

### 3.5 Python ecosystem bridges

- **brightwind**: export helper and a notebook doing MCP with BARRA2 as the reference.
- **windrose**: wind rose plot in the summary report.
- **windpowerlib**: hub-height correction and turbine power curves for a quick gross-yield check.
- **PyWake**: wake/AEP studies take a wind climate (`.tab`-like sector frequencies), which 3.3 produces.
- **atlite**: PyPSA's renewables tool is ERA5-first; a BARRA2 cutout loader could be an upstream contribution.

## 4. RFC roadmap

Delivery order set by the owner: fix first, then decide the parameters, then netCDF output, then the GUI, and export
to wind software last. Each RFC builds on the ones before it. RFC-004 (CLI) was dropped and its number retired, so
the merged RFCs' references to RFC-005 and RFC-006 stay valid.

| Order | RFC | Scope | Status |
|---|---|---|---|
| 1 | [RFC-001 Fix the wind variable table](wind-variables-bugfix-prd.md) | Remove placeholder variables, numeric heights, exact column matching, `ua10m`/`va10m` aliases for `uas`/`vas` with height-named converted output (`ua10m`, `v10m`). Clears two backlog bugs. | Done (#128) |
| 2 | [RFC-002 Parameter review](parameter-review-prd.md) | Which BARRA2 parameters to support (pressure, humidity, temperature at height, stability, gusts, site fields), presets, checked variable inventory. Derived variables (density, shear, veer) follow from it. | Merged as a doc (#130), not built |
| 3 | [RFC-003 netCDF output, node averaging and area download](netcdf-output-prd.md) | xarray Dataset with a `height` dimension and CF metadata; native netCDF download; nearest node, four-node average and area download. | Draft, decisions recorded |
| 4 | ~~RFC-004 CLI~~ | Dropped 2026-10-30. Engine, project file, retries and run summary moved to RFC-005; the command-line tool is in the backlog. | Dropped |
| 5 | [RFC-005 GUI](gui-prd.md) | Engine (`run_site`), TOML project file (also used by the example script), retries and run summary, then a fresh-build GUI on top (toolkit by spikes, Streamlit preferred). Includes the atl3b fork review. First PyPI release and MIT relicence follow it (3.2). | Draft, decisions recorded |
| 6 | RFC-006 Export to wind software | Windographer, WAsP `.tab`, openWind first, then WindPRO and others (section 3.3). Last, once the parameters, netCDF output and GUI are settled. | To draft |

Retries, back-off and the run summary (section 2) land with RFC-005's engine. Area download is now part of
RFC-003. The summary report comes after RFC-006 unless reprioritised.

## 5. Open questions for the owner

1. Which wind tools do target users actually use most? A short poll of a few consultancies would set the export
   order for RFC-006.

Decided on 2026-10-30:
- **Licence:** relicense the code to MIT before the first PyPI release (3.2).
- **Default domain:** AUS-11, with a docs note on its coverage and CSIRO ranking (3.1).
- **Dataset version:** record it with the download date, don't pin it (RFC-003 5.7).
- **First PyPI release:** after RFC-005 (3.2).

## Sources

- atl3b fork: <https://github.com/atl3b/barra2-dl-wr>, and [issue #59](https://github.com/richard-gledhill/barra2-dl/issues/59)
- NCI BARRA2 Parameter Descriptions: <https://opus.nci.org.au/spaces/NDP/pages/338002591/BARRA2+Parameter+Descriptions>
- NCI BARRA2 FAQ: <https://opus.nci.org.au/pages/viewpage.action?pageId=264241306>
- BARRA2 on AWS Open Data: <https://registry.opendata.aws/australian-bureau-of-meteorology-barra-2/>
- BARRA2 dataset record: <https://data.gov.au/data/en/dataset/5589426c-daac-4193-a9f1-551c690a44d0>
- BARRA2 validation with wind power: <https://publish.csiro.au/ES/fulltext/ES24028>
- Windographer export formats: <https://support.ul-renewables.com/windographer/dlg-file-export-data.htm>
- Windographer product page: <https://www.ul.com/services/windographer>
- WAsP Climate Analyst: <https://wasp.dtu.dk/software/wasp-tools/wasp-climate-analyst>
- THREDDS access (CSIRO guide): <https://research.csiro.au/dap/download/accessing-data-via-a-thredds-catalogue>
- siphon NCSS client: <https://unidata.github.io/siphon/latest/_modules/siphon/ncss.html>
- brightwind: <https://brightwind-dev.github.io/brightwind-docs/tutorials/becoming_a_correlation_wizard.html>
- atlite: <https://atlite.readthedocs.io/>
- windpowerlib: <https://docsearch.algolia.com/mcp/docs/repo/wind-python/windpowerlib>
- Live probes of `thredds.nci.org.au` and `bom-opendata-climate` S3, 2026-10-28 (this review).
