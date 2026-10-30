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
One request per node, cached as `<prefix>_<domain>_fx_<var>.csv`, and read with `read_fixed_fields` rather than
merged. `orog` comes with every point download.
_Avoid_: Static variable

**Preset** (`BARRA2_PRESETS`):
A named list of variables for a wind energy assessment task, e.g. `wind+density` (the default,
`BARRA2_PRESET_DEFAULT`). Defined at `1hr`; `preset_variables` rejects a preset at a frequency missing any of its
variables.

**Point data**:
The time series of one variable at the grid node nearest a latitude and longitude, fetched through the NetCDF
Subset Service as CSV.
_Avoid_: Grid data (a gridded/bounding-box download is not implemented)

### Processing

**Cache folder**:
The folder the per-variable-month CSVs are downloaded into. Existing files are skipped, so re-running a download
resumes.
_Avoid_: Output folder (the merged result is written elsewhere)

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

**Wind speed** (`v*`):
The magnitude of the `ua`/`va` pair, added as `v<height>[unit="m s-1"]`.

**Meteorological direction** (`v*_phi_met`):
The direction the wind blows from, in degrees clockwise from north, added as `v<height>_phi_met[unit="degrees"]`.
_Avoid_: Direction of travel (the opposite convention)
