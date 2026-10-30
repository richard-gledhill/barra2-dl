Status: Accepted

# RFC-003: netCDF output, node averaging and area download

| | |
|---|---|
| Backlog | "Additional output types beyond `csv_file`" and the gridded-download item in [backlog.md](../backlog.md) |
| Depends on | [RFC-001 wind variable fix](wind-variables-bugfix-prd.md) (Done), [RFC-002 parameter review](parameter-review-prd.md) (variable inventory, cell methods, `orog`) |
| Related | [ADR-002](../adr/ADR-002-per-variable-month-idempotent-downloads.md), [RFC-005 GUI](gui-prd.md), [roadmap](wind-engineering-roadmap-prd.md) |
| Drafted | 2026-10-28, updated 2026-10-30 with the owner's decisions (section 7); `average4` clarified 2026-10-30 (decision 8) |

## 1. Summary

Produce CF-compliant netCDF via xarray, alongside CSV. netCDF keeps units, coordinates, provenance and a proper time
axis inside the file, and it's the native format of BARRA2 and of most meteorological tooling. CSV stays the default
for spreadsheet and wind-software users.

The RFC also adds two ways of choosing which BARRA2 nodes a series comes from, beyond today's nearest node:
- a four-node average around the requested point, in CSV and netCDF;
- an area download, a `(time, lat, lon)` grid, in netCDF only.

The GUI (RFC-005) offers both, so the library has to provide them.

## 2. Motivation

- Units today live in column names (`ua50m[unit="m s-1"]`), and metadata such as cell methods, the dataset version
  and the actual node coordinates is lost.
- Height is encoded in names. A `height` dimension makes shear and profile work a one-liner
  (`ds.wind_speed.sel(height=[50, 100])`).
- Long multi-decade series are large as CSV; netCDF is compact and loads lazily.
- Analysts want either the nearest node, an average of the nodes around a point, or a wind-farm area. The last is
  a natural `(time, lat, lon)` array, which CSV can't hold cleanly.

## 3. What the server offers (verified 2026-10-28)

| Route | Result |
|---|---|
| NCSS point, `accept=netcdf4` | HTTP 200, `application/x-netcdf`, 24.5 kB per variable-month vs 67.5 kB as CSV. CF-1.9 discrete sampling geometry (`featureType: timeSeries`, dims `station`, `obs`). `accept=netcdf` returns netCDF-3. |
| NCSS bounding box (`north`/`south`/`east`/`west`), `accept=netcdf4` | HTTP 200, a normal `(time, lat, lon)` grid of real nodes; AUST-04 nodes every 0.04°. |
| NCSS point, `fx/orog` | HTTP 200 CSV, one row with a dummy time `1970-01-01T00:00:00Z` (checked 2026-10-30). |
| OPeNDAP (`/thredds/dodsC/...`) with `xarray.open_dataset` | Opens lazily; `.sel(lat=…, lon=…, method='nearest')` pulls only the point. Values match NCSS. |
| AWS Open Data `s3://bom-opendata-climate/BARRA2/` (anonymous) | Same netCDF files in dated version folders (e.g. `v20250528`), about 700 MB per variable-month. |

## 4. Goals and non-goals

**Goals**
- G1. An `xarray.Dataset` from a cache folder, with CF attributes, ready to `to_netcdf()`.
- G2. Wind components on a `height` dimension; derived speed and direction with CF standard names.
- G3. Provenance attributes: domain, frequency, dataset version and download date (recorded, not pinned; decision 4),
  requested and actual node(s), `orog` per node, package version, licence and citation for BARRA2.
- G4. CSV output and the current DataFrame API keep working unchanged.
- G5. Node selection with three modes: `nearest` (today's behaviour, the default), `average4` (inverse-distance
  average of the four nodes around the requested point) and `area` (a bounding box, netCDF only).
- G6. Downloaded data keeps its original timestamps everywhere: no shifting in the cache, CSV or netCDF (decision 1).
- G7. One output file per site (decision 3).

**Non-goals**
- Zarr or cloud-optimised output.
- Replacing pandas in the pipeline.
- Downloading from S3. Its whole-domain files are too large for point and small-area work; THREDDS NCSS stays the
  only source.

## 5. Proposed design

### 5.1 Phases

1. **netCDF from what we already download.** Add `merge.to_dataset(df) -> xr.Dataset`. It converts the merged
   DataFrame: the index becomes `time` plus scalar node coordinates, `ua*`/`va*` are stacked on `height`, and units
   move from the column names into `attrs`. No change to downloads or the cache. This is the thinnest useful slice.
2. **Native netCDF download.** Pass `fileout_type='netcdf4'` (the URL template already has `accept={fileout_type}`)
   and add `merge.merge_netcdf_to_dataset(folder, pattern)` using `xr.open_mfdataset`. The cache stays one file per
   variable-month, so ADR-002's idempotent resume still holds. The NCSS point file is a DSG ragged array
   (`station`, `obs`); normalise it to `time` on read.
3. **Four-node average and area download** (5.6), built on the bounding-box route of phase 2.

### 5.2 Dataset layout (point or four-node average)

```
<xarray.Dataset>
Dimensions:  (time: N, height: k)
Coordinates:
  * time        datetime64  (UTC; standard_name=time), as served
  * height      float       [10, 50, 100, 150, 200, 250, (1500)] m, positive=up
    lat, lon    float       actual BARRA2 node (nearest) or requested site (average4)
    requested_lat, requested_lon
Data variables:
    ua, va                (time, height)  m s-1   eastward_wind / northward_wind
    wind_speed            (time, height)  m s-1   wind_speed
    wind_from_direction   (time, height)  degree  wind_from_direction
    tas, ps, hurs, ta50m … (time)          original names and units
Attributes: Conventions=CF-1.10, source, domain, freq, node_selection, barra2_version, downloaded, orog,
            history, license, references
```

- `uas`/`vas` map to height 10. The `ua10m`/`va10m` aliases from RFC-001 need no special case, since the `height`
  coordinate already carries the 10.
- Inside the file, CF standard names win, with the BARRA2 name kept in a `barra2_name` attribute.
- `orog` (RFC-002 5.7) is an attribute. For `average4`, it's a per-node coordinate on the `node` dimension, plus
  the weighted mean as an attribute.
- For `average4`, the four node series sit on a `node` dimension beside the averaged variables (5.6).
- The area layout is the same with `lat`/`lon` as dimensions instead of scalar coordinates.

### 5.3 Dependencies

xarray and the `h5netcdf` engine become **core dependencies** (decision 2), so netCDF works out of the box.
`h5netcdf` ships wheels on all CI Python versions; `netCDF4` is the alternative if netCDF-3 output is ever
required. Both are imported by the package, so `deptry` stays clean.

### 5.4 Timestamps: kept as served

Mean variables such as `pr` and `rsds` are stamped at :30, the middle of the hour they average, while
instantaneous variables are stamped at :00. barra2-dl keeps every timestamp exactly as the server returned it,
in the cache, the CSV and the netCDF (decision 1).

- **CSV:** the merged frame has separate :00 and :30 rows when mean and instantaneous variables are downloaded
  together, with blanks where a variable has no value. That only happens with the `environment` preset; every
  `wind+density` variable is instantaneous.
- **netCDF:** mean variables go on their own time coordinate (`time_mean`), with `cell_methods` and `time_bnds`
  from the RFC-002 inventory, so no rows are padded.
- **Docs:** a user-docs note explains the :00/:30 convention, why barra2-dl doesn't shift, and that analysts who
  want one time axis must shift or resample themselves.

### 5.5 One file per site

Each site gets its own output file (decision 3): `<prefix>_<domain>_<freq>_<selection>_<start>_<end>.nc`, with
`selection` one of `nearest`, `average4` or `area`. This matches how wind software loads one mast per file. A
`site` dimension combining several sites in one file can be added later if a user asks for it.

### 5.6 Node selection

| Mode | How it's fetched | CSV | netCDF |
|---|---|---|---|
| `nearest` (default) | NCSS point request, as today; NCSS snaps to the nearest node | Yes | Yes |
| `average4` | One small NCSS bounding-box request around the requested point, sized from the domain's grid spacing, used only as a download window to fetch the real nodes around the point. The four nodes that surround the point are averaged with inverse-distance weights. | Yes | Yes |
| `area` | NCSS bounding-box request for a user-given `north`/`south`/`east`/`west` | No (a grid doesn't fit CSV) | Yes |

- **Real nodes only.** The bounding-box response contains real nodes with their true coordinates. So `average4`
  never computes nodes arithmetically, avoiding the AUST-04 grid bug found in the atl3b fork. Add
  `BARRA2_GRID_SPACING` (AUS-11 0.11°, AUST-04 0.04°) to `globals.py` for sizing the box.
- **One point, no boundary.** `average4` averages the four nodes around the single point the user gives (the node
  either side of it in latitude and either side in longitude). It does not take a site boundary or area, and it
  is not an average over the box: the box is only the download window, which returns a grid (typically 3 × 3) of
  which the four surrounding nodes are used and the rest ignored. A point exactly on a node gives that node's values.
  Averaging over a user-given area is not offered; `area` returns every node unaveraged.
- **How values are averaged** (5.8). Each time step uses one set of inverse-distance weights:
  - **Speed:** the scalar mean, i.e. the weighted mean of each node's own speed, `sum(w_i * hypot(ua_i, va_i))`.
  - **Direction:** taken from the weighted mean components, `atan2` of the mean `ua` and `va`, converted to the
    meteorological convention.
  - **`ua`/`va`:** the weighted means are written too, so the vector mean is available.
  - **Scalar variables** (`tas`, `ps` …): plain weighted means.
- **Node series written too** (decision 6). `average4` writes the averaged series and the four node series, so an
  analyst can see which node best represents the point. In netCDF they share one file, with a `node` dimension
  (size 4, with each node's coordinates, distance, weight and `orog`) beside the averaged variables. In CSV there is
  one file per node, plus the average file.
- **Cache.** Bounding-box files are cached per variable-month like point files, with `average4` or `area` and the
  box in the filename, so resume still works.
- **API.** `point_data_urlfilenames` gains `node_selection='nearest' | 'average4'`. `area` gets its own
  `area_data_urlfilenames(bbox, …)`, because it takes a box rather than a point.

### 5.7 Dataset version

Record, don't pin (decision 4). THREDDS serves only `latest`. barra2-dl writes the version that `latest` resolves
to (from the THREDDS catalogue, or the matching S3 version folder) and the download date into the netCDF attributes
and the run summary. If the version can't be resolved, it records `latest` plus the download date.

### 5.8 Why speed and direction are averaged differently

Averaging the components and then taking the speed (a vector mean) gives a speed equal to or lower than averaging
each node's speed (a scalar mean). Components from different directions cancel: a 5 m/s northerly and a 5 m/s
southerly give a scalar mean of 5 m/s and a vector mean of 0 m/s. Copernicus Marine recommends:
- the scalar mean to characterise mean wind-speed magnitude;
- the vector mean when the resulting direction or net transport matters.

It warns that wind power has to be computed from speed first and then averaged
([Copernicus Marine, averaging wind speed and wind vectors](https://help.marine.copernicus.eu/en/articles/5487266-averaging-wind-speed-and-wind-vectors)).
NOAA's NDBC uses the same hybrid for its buoy winds: a scalar-averaged speed with a direction from the averaged
components ([NDBC wind averaging](https://www.ndbc.noaa.gov/wndav.shtml)).

A wind resource assessment cares about speed magnitude, because power goes with the cube of speed, and also needs a
direction for the wind rose. So barra2-dl uses the scalar mean for speed and the vector mean for direction:
- Averaging components alone would bias the averaged speed low.
- Averaging directions arithmetically would break at north (350° and 10° would average to 180°).

Across four neighbouring nodes at the same time step the directions are usually close, so the two speeds differ by
little. The gap grows at fronts, sea-breeze boundaries and in complex terrain, where averaging components alone would
understate the resource.

One consequence has to be documented: the averaged speed is **not** `hypot` of the averaged `ua`/`va`. Users who
recompute speed from the averaged components get the lower vector-mean value. The netCDF `wind_speed` carries
`cell_methods: node: mean (scalar)` and the components `node: mean (vector)`, so the difference is visible in the
file.

### 5.9 API sketch

```python
df = merge.merge_csvs_to_df(cache, pattern, BARRA2_INDEX)
df = convert.convert_wind_components(df)
ds = merge.to_dataset(df, domain='AUS-11', freq='1hr', requested=point)   # phase 1
ds.to_netcdf(out / 'site_AUS-11_1hr_nearest_20230101_20231231.nc')

pairs = download.point_data_urlfilenames(BARRA2_URL, vars, lat, lon, start, end, 'site',
                                         fileout_type='netcdf4', node_selection='average4')
ds = merge.merge_netcdf_to_dataset(cache, 'site_AUS-11_1hr_average4_*.nc')   # phases 2 and 3
```

## 6. Testing

- Offline fixtures: a small NCSS netCDF4 point file and the CSV for the same variable-month, checked in under
  `tests/data/`, so tests assert both routes give identical values. Add a small bounding-box fixture for `average4`
  and `area`.
- Round trip: `to_dataset(df).to_netcdf()` → `open_dataset` keeps values, units and attributes.
- Timestamps: a frame mixing `pr` (:30) and `tas` (:00) keeps both sets of times unchanged in CSV and netCDF.
- `average4` speed is the weighted mean of node speeds, and for opposed node winds it is larger than the speed of
  the mean vector. Direction comes from the mean components, and the four node series are written beside the
  average.
- `average4`: the weights sum to 1, a site exactly on a node gives that node's values, and all four nodes come from
  the response, not from arithmetic.
- `area` refuses CSV output.
- A simple attribute check for CF compliance.
- Live tests (`BARRA2_LIVE=1`) for `accept=netcdf4` point and bounding-box requests on every `(domain, freq)`.

## 7. Decisions

Decided by the owner on 2026-10-30:

1. **Timestamps:** no shift. Downloaded data keeps its original timestamps; this is noted in the docs (5.4).
2. **xarray:** a core dependency (5.3).
3. **Multi-site output:** one file per site (5.5).
4. **Dataset version:** record it, don't pin it (5.7).
5. **Node selection:** nearest node and four-node averaging for CSV and netCDF; area download for netCDF (5.6). This
   comes from the RFC-005 Q&A.

6. **`average4` output:** write the average plus the four node series (5.6).
7. **`average4` method:** hybrid. Scalar mean for speed, vector mean (from averaged components) for direction
   (5.8). This replaces the earlier "average components" recommendation, because components alone bias speed low.
8. **`average4` input (2026-10-30):** the average is of the nodes around the single input point the user provides,
   not a site boundary or area (5.6). The bounding box is only a download window.
