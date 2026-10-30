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
- Slice 2: `merge_netcdf_to_dataset(..., requested=None, node_selection='nearest', versions=None, fixed_pattern=None)`
  takes `node_selection` `nearest`, `average4` or `area`; it keeps only the files of that kind, so a loose filename
  pattern is safe in a shared cache. `average4` picks the four nodes that bracket the site in the response grid
  (`mapping.bracket_index`), weights them by inverse haversine distance (`mapping.distance_km`,
  `mapping.inverse_distance_weights`), and applies the hybrid method of RFC-003 5.8: speed is the weighted mean of node
  speeds, `ua`/`va` the weighted means, direction from those. Each averaged variable gets a `<name>_node` twin on a
  `node` dimension (size 4) with `node_lat`, `node_lon`, `node_distance`, `node_weight` and, from `fixed_pattern`,
  `node_orog` coordinates; `cell_methods` says `node: mean (scalar)` on speed and `node: mean (vector)` on the components
  and direction. `area` keeps every node with `lat`/`lon` dimensions and `orog` as a `(lat, lon)` variable.
  `dataset_to_frames(ds) -> dict[str, DataFrame]` gives the csv frames: the series (or `average4`) plus `node1` to
  `node4`; it refuses an area.

### `download.py`

- Slice 1: `fileout_type='netcdf4'` (extension `.nc`, also for the `orog` fixed field);
  `resolve_variable_versions(variables, domain, freq) -> dict[str, str]` reads each variable's `variable_version`
  from its OPeNDAP `.das` attributes (the THREDDS catalogue lists only `latest`), falling back to `'latest'`.
- Slice 2: `point_data_urlfilenames(..., fileout_type=None, node_selection='nearest' | 'average4')`; `average4` is
  netCDF4 only (csv is an error) and makes one bounding-box request per variable-month, a grid spacing either side of
  the site, with `average4` in the cache filename and for the `orog` grid. `area_data_urlfilenames(bbox, vars, start,
  end, prefix, fileout_type='netcdf4', *, domain, freq)` for `area`, with the box in the filename. `globals` gains
  `BARRA2_GRID_SPACING`, `BARRA2_NODE_SELECTIONS`, `BARRA2_URL_BBOX` and `BARRA2_URL_FX_BBOX`.

### Fixtures

`tests/data/` holds three days of AUS-11 1hr point files for `ua50m`, `va50m`, `tas`, `pr` and `orog`, each as netCDF4
and csv, and the 3 x 3 bounding-box grids around the same site (`grid_*`), built from the live server by
`scripts/build_test_fixtures.py`. Tests assert both point routes give identical values; the grids serve `average4`
and, renamed as an area download names them, `area`.

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
