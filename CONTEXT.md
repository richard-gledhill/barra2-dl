# barra2-dl

A Python library that bulk-downloads BARRA2 point data from the Bureau of Meteorology's NCI THREDDS server, merges
it and derives wind speed and direction for wind resource and energy assessment.

## Language

### Source data

**BARRA2**:
The Bureau of Meteorology's second-generation atmospheric reanalysis, served from the NCI THREDDS server.
_Avoid_: BARRA (the first-generation reanalysis, a different product)

**Domain**:
A BARRA2 model grid, named as on the server: AUS-11 or AUST-04. Listed in `BARRA2_DOMAINS` with the model that
produced it, and passed as `domain=` with the `BARRA2_URL` template.

**AUS-11**:
The BARRA-R2 regional domain, about 11 km grid spacing. Frequencies: `1hr`.
_Avoid_: BARRA-R2 when naming the domain in code (it names the model, AUS-11 the domain)

**AUST-04**:
The BARRA-C2 convective-scale domain, about 4 km grid spacing. Frequencies: `1hr`, `20min`.
_Avoid_: BARRA-C2 when naming the domain in code

**Frequency**:
The time step of a BARRA2 output, named as its server folder: `1hr` (the default) or `20min` (AUST-04 only). Listed
per domain in `BARRA2_FREQS` and passed as `freq=`.
_Avoid_: Resolution (that is the grid spacing)

**Variable**:
One BARRA2 field such as `ua50m` or `ta50m`. BARRA2 stores each variable-month as a separate remote file.
_Avoid_: Column (that is the same data after download and merge)

**Inventory** (`BARRA2_VARS`):
The variables BARRA2 publishes for each domain and frequency, with their units and cell methods
(`BARRA2_VAR_INFO`). Checked in as `barra2_dl/data/barra2_variables.csv` and rebuilt with
`scripts/build_barra2_inventory.py`. A variable name not in it is rejected before download.

**Fixed field**:
A time-invariant variable in the `fx` folder, such as `orog` (model surface altitude) or `sftlf` (land fraction).
One request per node, cached as `<prefix>_<domain>_fx_<var>.csv` (or `.nc`), and read with `read_fixed_fields` rather than
merged. `orog` comes with every point download.
_Avoid_: Static variable

**Preset** (`BARRA2_PRESETS`):
A named list of variables for a wind energy assessment task, e.g. `wind+density` (the default,
`BARRA2_PRESET_DEFAULT`). Defined at `1hr`; `preset_variables` rejects a preset at a frequency missing any of its
variables.

**Node**:
One point of the BARRA2 grid, with its own latitude, longitude and altitude (`orog`). The nodes are 0.11 degrees apart
on AUS-11 and 0.04 on AUST-04 (`BARRA2_GRID_SPACING`). Always taken from the server's response, never computed.
_Avoid_: Cell, grid point (a grid point is requested at a latitude and longitude; the node is what the server returns)

**Grid node** (`mapping.GridNode`):
A node as `nearest_nodes` returns it: the exact grid `lat` and `lon` as the server holds them, the distance in km from
the point asked about, `orog` and `sftlf` (land fraction of the cell, in percent). Taken from a small bounding-box
request, never computed from a grid origin.
_Avoid_: Grid point (a grid point is requested; the grid node is what the server returns)

**Chosen nodes** (`nodes`):
The nodes a user picks from `nearest_nodes` for a point site, named by exact latitude and longitude (`Site.nodes`, `nodes =
[[lat, lon], ...]` in a project file). Each is written as its own series (`node<k>`, in the order given), with an opt-in
inverse-distance mean (`node_mean`). A site with nodes is a `nodes` download.

**Boundary** (`mapping.Polygon`):
A site's outline (one polygon, with optional holes) read from a GeoJSON or KML file in WGS 84. A boundary site is an `area`
download of the nodes whose cell overlaps it.
_Avoid_: Shapefile (not read), area (that is the box or the download)

**Cell overlap** (`Polygon.cell_overlap`):
The share (0 to 1) of a node's grid cell, the node plus or minus half the spacing, that lies inside the boundary. A node is
used when it is above 0; it is also the basis of its weight in the site mean.

**Site mean** (`node_mean`, `<name>_site_mean`):
The opt-in mean of the nodes a boundary uses, weighted by cell overlap area times the cosine of latitude, by the hybrid
method of the four-node average. Not for extremes or gusts.

**Node selection** (`BARRA2_NODE_SELECTIONS`):
How the nodes for a point are chosen: `nearest` (the default point request), `average4` (the four nodes around the
point, averaged), `area` (every node in a box, netCDF only) or `nodes` (nodes chosen by their exact latitude and
longitude, netCDF download). `area` and `nodes` are implied by a site's geometry (a box or boundary, or `nodes`), not set.

**Point data**:
The time series of one variable at the grid node nearest a latitude and longitude, fetched through the NetCDF
Subset Service as CSV (`fileout_type='csv_file'`) or netCDF4 (`fileout_type='netcdf4'`).
_Avoid_: Grid data (a bounding-box download is a node selection: `average4` or `area`)

### Processing

**Cache folder**:
The folder the per-variable-month CSVs are downloaded into. Existing files are skipped, so re-running a download
resumes.
_Avoid_: Output folder (the merged result is written elsewhere)

**Cache mismatch**:
A cached file that holds another location than the request, or can't be read. Found by checking every cached file
before any request, and raised as `CacheMismatchError`; fixed by renaming the site or deleting the listed files.
_Avoid_: Stale cache (the file isn't old, it is for another request)

**Index** (`BARRA2_INDEX`):
The columns `time`, `station`, latitude and longitude that the per-variable CSVs are outer-joined on.
_Avoid_: Key

**ua / va**:
The eastward and northward wind components at a height, in m s-1. Listed in `BARRA2_WIND_VARS` with their height:
`uas`/`vas` (10 m), `ua50m`…`ua250m` and `ua1500m`. `ua<N>` without the `m` (e.g. `ua850`) is a pressure level in
hPa, not a height.
_Avoid_: u / v in column names (the BARRA2 names are `ua*` and `va*`)

**Alias** (`BARRA2_VAR_ALIASES`):
A barra2-dl name for a server variable: `ua10m`/`va10m` for `uas`/`vas`. An alias is downloaded under the server
name, and the converted output uses the alias so the 10 m wind is named like the other heights.
_Avoid_: Treating `ua10m` as a server variable (the server has none)

**Four-node average** (`average4`):
The inverse-distance weighted mean of the four nodes surrounding the one point the user gave (not a site boundary or
area), by the hybrid method: speed is the mean of the
nodes' own speeds (scalar mean), direction comes from the mean `ua` and `va` (vector mean). The averaged speed is
therefore not `hypot(ua, va)`. The four node series are written beside it.
_Avoid_: Averaging bearings, or speed from averaged components

**Wind speed** (`v*`):
The magnitude of the `ua`/`va` pair, added as `v<height>[unit="m s-1"]`.

**Meteorological direction** (`v*_phi_met`):
The direction the wind blows from, in degrees clockwise from north, added as `v<height>_phi_met[unit="degrees"]`.
_Avoid_: Direction of travel (the opposite convention)

### Output

**Dataset**:
The xarray form of the merged data, from `merge.merge_netcdf_to_dataset` (netCDF4 downloads) or `merge.to_dataset`
(a csv DataFrame), written with `to_netcdf()`: wind quantities on a `height`
dimension, units and cell methods as attributes, the node altitude and provenance as global attributes. One file per
site, named `<prefix>_<domain>_<freq>_<selection>_<start>_<end>.nc`.
_Avoid_: Treating a Dataset as a grid (a gridded download is not implemented)

**Project file**:
A TOML file with a `[settings]` table and one `[[site]]` per mast, point or area, read by `project.load_project` into
`Settings` and `Site` dataclasses. A form builds the same dataclasses, so both go through `project.validate` and
`project.run_site`. Unknown keys are errors.
_Avoid_: Config file (it holds the sites too)

**Site**:
One place to get data for, named (the name is the filename prefix) with a point or a box, and any settings it overrides.
A point is a nearest-node or four-node-average download; a box is an area download.
_Avoid_: Mast (a mast is one kind of site)

**Run summary**:
`<name>_run_summary.json`, written by `project.run_site` for every outcome: the inputs, versions, the result of every
file, the missing months, the outputs and the requested and actual node(s). `project.site_result_to_dict` is its one
serialiser.
_Avoid_: Log (it is data for a reader or an interface, not progress messages)

**Metadata header**:
The `key,value` block at the top of a csv written by `merge.write_csv` or `merge.write_df_csv`, ending in a blank line: source, node, elevation,
requested point, time zone, dataset versions and download date, mirroring the Dataset attributes. `merge.read_csv`
returns it as a dict. The csv route's merged file has none; its converted file has it.
_Avoid_: Header row (that is the column names)

**time_mean**:
The time coordinate of variables averaged over the time step (cell methods `time: mean`, such as `pr`), stamped mid-period
(:30 at `1hr`) and kept as served; `time_bnds` gives the period. Instantaneous variables use `time`.
_Avoid_: Shifting or resampling the timestamps
