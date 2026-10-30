# SPEC: netCDF output, four-node averaging and area download

Requirement: [RFC-003](../requirements/netcdf-output-prd.md), decisions in its section 7. Style and gates:
[conventions.md](../conventions.md), [constraints.md](../constraints.md).

## Scope

RFC-003 in two PRs. Phases 1 and 2 were combined, because a netCDF example that downloads csv is the wrong one to
publish; the csv route stays and the netCDF route runs alongside it.

1. `merge.to_dataset` from the merged DataFrame (phase 1) and the native netCDF4 download with
   `merge.merge_netcdf_to_dataset` (phase 2).
2. `average4` and `area` node selection (phase 3).

Out of scope: Zarr, S3, multi-site files, the GUI (RFC-005), derived variables, any timestamp shifting.

## Changes

### Dependencies

`xarray`, `h5netcdf` and `h5py` (the backend h5netcdf needs) become core dependencies. `uv lock` is rerun. xarray loads the
two by engine name, so deptry reports them unused; the owner approved a `DEP002` ignore for exactly these two.

### `globals.py`

- Slice 3: `BARRA2_GRID_SPACING = {'AUS-11': 0.11, 'AUST-04': 0.04}` (degrees), replacing the two `Todo` comments;
  `BARRA2_NODE_SELECTIONS = ('nearest', 'average4', 'area')`.

### `merge.py`

- Slice 1: `to_dataset(df, *, domain, freq, requested, orog=None, node_selection='nearest', versions=None) -> xr.Dataset`
  (the csv bridge).
  - `requested` is a `LatLonPoint`; the node `lat`/`lon` come from the frame's index columns.
  - `ua*`/`va*` (with the `convert_wind_components` speed and direction) are stacked on a `height` dimension
    (`uas`/`ua10m` is 10 m).
  - Units and `cell_methods` come from `BARRA2_VAR_INFO`, not from the column names; each variable keeps its BARRA2
    name in `barra2_name` and gets a CF `standard_name`.
  - Variables whose `cell_methods` contain `time: mean` go on their own `time_mean` coordinate with `time_bnds`.
    Timestamps are never shifted.
  - Attributes: `Conventions`, `source`, `domain`, `freq`, `node_selection`, `barra2_version` (the resolved
    `variable_version`s, or `latest`), a per-variable `barra2_version`, `downloaded` (UTC date), `orog`, package
    version in `history`, `license`, `references`.
- Slice 1: `merge_netcdf_to_dataset(folder, pattern, *, domain, freq, requested, orog=None, node_selection, versions)
  -> xr.Dataset`. Opens the NCSS point files, normalises the DSG `(station, obs)` layout to `time`, joins each
  variable's months, derives wind speed and direction on the Dataset, and returns the same layout as `to_dataset`.
  Fixed-field files are skipped. `read_fixed_fields` also reads `.nc` files.
- Slice 3: `node` dimension (size 4; node `lat`/`lon`, `distance`, `weight`, `orog`) for `average4`, the hybrid
  averaging of RFC-003 5.8 with `cell_methods` `node: mean (scalar)` on speed and `node: mean (vector)` on components,
  and `lat`/`lon` dimensions for `area`. `dataset_to_frames(ds) -> dict[str, DataFrame]` gives the average plus one
  frame per node, for CSV output.

### `download.py`

- Slice 1: `fileout_type='netcdf4'` (extension `.nc`, also for the `orog` fixed field);
  `resolve_variable_versions(variables, domain, freq) -> dict[str, str]` reads each variable's `variable_version`
  from its OPeNDAP `.das` attributes (the THREDDS catalogue lists only `latest`), falling back to `'latest'`.
- Slice 3: `point_data_urlfilenames(..., node_selection='nearest' | 'average4')`; `average4` always downloads netCDF4
  bounding-box files, sized from `BARRA2_GRID_SPACING`, with `average4` in the cache filename.
  `area_data_urlfilenames(bbox, ...)` for `area`.

### Fixtures

`tests/data/` holds three days of AUS-11 1hr point files for `ua50m`, `va50m`, `tas`, `pr` and `orog`, each as netCDF4
and csv, built from the live server by `scripts/build_test_fixtures.py`. Tests assert both routes give identical
values. The bounding-box fixture arrives with slice 3.

### Output files

One file per site: `<prefix>_<domain>_<freq>_<selection>_<start>_<end>.nc`, built by the caller (scripts, docs). No
helper.

### Docs

README, `CONTEXT.md`, a MkDocs page on the :00/:30 timestamp convention and node averaging, the example script and
notebook kept in step.

## Acceptance

- Every test in RFC-003 section 6 exists; live ones are opt-in with `BARRA2_LIVE=1`.
- `make check` and `make test` pass per slice; live tests and an end-to-end example run in a scratch folder pass.
- After slice 2: archive this folder, set RFC-003 to Done, update the roadmap status.
