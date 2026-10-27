# barra2-dl

A Python library that bulk-downloads BARRA2 point data from the Bureau of Meteorology's NCI THREDDS server, merges
it and derives wind speed and direction for wind resource and energy assessment.

## Language

### Source data

**BARRA2**:
The Bureau of Meteorology's second-generation atmospheric reanalysis, served from the NCI THREDDS server.
_Avoid_: BARRA (the first-generation reanalysis, a different product)

**AUS-11**:
The BARRA-R2 regional domain, about 11 km grid spacing. Template: `BARRA2_URL_AUS11_1HR`.
_Avoid_: BARRA-R2 when naming the domain in code (it names the model, AUS-11 the domain)

**AUST-04**:
The BARRA-C2 convective-scale domain, about 4 km grid spacing. Template: `BARRA2_URL_AUST04_1HR`.
_Avoid_: BARRA-C2 when naming the domain in code

**Variable**:
One BARRA2 field such as `ua50m` or `ta50m`. BARRA2 stores each variable-month as a separate remote file.
_Avoid_: Column (that is the same data after download and merge)

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
The eastward and northward wind components at a height, in m s-1. Listed in `BARRA2_WIND_VARS`.
_Avoid_: u / v in column names (the BARRA2 names are `ua*` and `va*`)

**Wind speed** (`v*`):
The magnitude of the `ua`/`va` pair, added as `v<height>[unit="m s-1"]`.

**Meteorological direction** (`v*_phi_met`):
The direction the wind blows from, in degrees clockwise from north, added as `v<height>_phi_met[unit="degrees"]`.
_Avoid_: Direction of travel (the opposite convention)
