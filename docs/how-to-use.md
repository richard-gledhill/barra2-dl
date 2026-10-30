# How to use barra2-dl

barra2-dl is a pipeline of small steps. You chain them yourself:

1. **Download** one file per variable per month, plus the node altitude, into a cache folder.
2. **Merge** the cached files into one pandas DataFrame.
3. **Convert** the wind components to speed and direction, and optionally the units.
4. **Output** the result as the DataFrame itself, as csv, or as netCDF.

Steps 1 to 3 are the same for the DataFrame and csv outputs. For netCDF there is a parallel route that downloads
netCDF4 files and merges them straight into an xarray Dataset, with no DataFrame ([Output 3](#output-3-netcdf)). Complete, runnable versions of the whole pipeline are in `scripts/`:

| Output | Script | Notebook |
|---|---|---|
| csv | `example_barra2_dl_csv.py` | `example_barra2_dl_csv.ipynb` |
| netCDF | `example_barra2_dl_netcdf.py` | `example_barra2_dl_netcdf.ipynb` |

## Steps 1 to 3: download, merge and convert

```python
from datetime import datetime
from pathlib import Path

import barra2_dl
from barra2_dl.globals import BARRA2_INDEX, BARRA2_PRESET_DEFAULT, BARRA2_URL
from barra2_dl.mapping import LatLonPoint

cache_dir = Path('cache')
cache_dir.mkdir(exist_ok=True)  # the download folder must already exist
point = LatLonPoint(-23.5527472, 133.3961111)

# the default preset, wind+density: winds at 10 to 250 m plus pressure, temperature and humidity
variables = barra2_dl.download.preset_variables(BARRA2_PRESET_DEFAULT, domain='AUS-11', freq='1hr')

urlfilenames = barra2_dl.download.point_data_urlfilenames(
    BARRA2_URL, variables, point.lat, point.lon, datetime(2023, 1, 1), datetime(2023, 3, 31),
    fileout_prefix='Demo', domain='AUS-11', freq='1hr',
)
barra2_dl.download.download_multithread(urlfilenames, cache_dir)  # files already in the cache are skipped

df = barra2_dl.merge.merge_csvs_to_df(str(cache_dir), 'Demo_AUS-11_1hr_*.csv', BARRA2_INDEX)
df = barra2_dl.convert.convert_wind_components(df)
df = barra2_dl.convert.convert_units(df)  # optional: K to degC, Pa to hPa, precipitation flux to mm h-1
```

- Data comes from the grid node nearest the point, on the AUS-11 (BARRA-R2) or AUST-04 (BARRA-C2) domain, at `1hr`
  or, on AUST-04, `20min`. Variables are checked against the inventory before anything is downloaded.
- The node altitude (`orog`) is downloaded with every point. It is one value, not a time series, so it isn't merged:
  read it with `merge.read_fixed_fields(cache_dir, 'Demo_AUS-11_fx_*.csv')`.
- At `20min` use the `wind` preset: pressure and humidity are not published every 20 minutes, so `wind+density`
  raises an error rather than downloading part of it.

## Output 1: the pandas DataFrame

After step 3, `df` is a wide DataFrame with one row per time stamp. Columns carry their unit in the name, for example
`ua50m[unit="m s-1"]`, and the derived wind columns are `v50m[unit="m s-1"]` (speed) and `v50m_phi_met[unit="degrees"]`
(the direction the wind blows from, clockwise from north). The 10 m wind is named `ua10m`/`va10m`, like the other
heights.

Use the DataFrame directly for analysis in pandas:

```python
import pandas as pd

df['time'] = pd.to_datetime(df['time'])
df.set_index('time')['v100m[unit="m s-1"]'].resample('MS').mean()
```

## Output 2: csv

```python
df.to_csv('Demo_converted_20230101_20230331.csv', index=False)
```

This is the format for spreadsheets and most wind analysis software. The cached per-variable files are csv too, so
you can also use those directly. See `example_barra2_dl_csv.py`.

The merged frame is written as it is. For the converted frame the example uses `merge.write_df_csv`, which writes the
same frame under a [metadata header](#csv-metadata-header) (the node, elevation, requested point and dataset versions):

```python
versions = barra2_dl.download.resolve_variable_versions(variables, domain='AUS-11', freq='1hr')
orog = barra2_dl.merge.read_fixed_fields(cache_dir, 'Demo_AUS-11_fx_orog.csv')['orog[unit="m"]']
barra2_dl.merge.write_df_csv(
    df, 'Demo_AUS-11_1hr_nearest_converted_20230101_20230331.csv',
    domain='AUS-11', freq='1hr', requested=point, orog=orog, versions=versions,
)
```

The example names its files `<prefix>_<domain>_<freq>_<node type>_merged_<start>_<end>.csv` and `..._converted_...`, as the
netCDF route names its files.

## Output 3: netCDF

netCDF keeps the units, coordinates and provenance inside the file, and loads lazily, which suits long series. The
netCDF files are about a third the size of the csv files, and each file also carries the node it came from.

The recommended route downloads netCDF4 files (`fileout_type='netcdf4'`) and merges them straight into a CF-style
[xarray](https://xarray.dev) Dataset. It runs alongside the csv route, and both can share one cache folder.

```python
urlfilenames = barra2_dl.download.point_data_urlfilenames(
    BARRA2_URL, variables, point.lat, point.lon, datetime(2023, 1, 1), datetime(2023, 3, 31),
    fileout_prefix='Demo', fileout_type='netcdf4', domain='AUS-11', freq='1hr',
)
barra2_dl.download.download_multithread(urlfilenames, cache_dir)

# which dataset version 'latest' was, per variable (a few small requests)
versions = barra2_dl.download.resolve_variable_versions(variables, domain='AUS-11', freq='1hr')

orog = barra2_dl.merge.read_fixed_fields(str(cache_dir), 'Demo_AUS-11_fx_*.nc')['orog[unit="m"]']
ds = barra2_dl.merge.merge_netcdf_to_dataset(
    str(cache_dir), 'Demo_AUS-11_1hr_*.nc', domain='AUS-11', freq='1hr', requested=point, orog=orog, versions=versions
)
ds.to_netcdf('Demo_AUS-11_1hr_nearest_20230101_20230331.nc')
```

`merge_netcdf_to_dataset` derives wind speed and direction from the `ua` and `va` pairs, so no separate convert step is
needed. Units stay as BARRA2 serves them (K, Pa, kg m-2 s-1); convert in xarray if you want other units.

Name the file for the site, as `<prefix>_<domain>_<freq>_<selection>_<start>_<end>.nc`. Each site gets its own file.
See `example_barra2_dl_netcdf.py`.

**From csv files you already have.** If you have a csv cache, `to_dataset` converts the merged and converted DataFrame
into the same Dataset, so you don't need to download again:

```python
ds = barra2_dl.merge.to_dataset(df, domain='AUS-11', freq='1hr', requested=point, orog=orog)
```

Here the units are those in the DataFrame, so a frame passed through `convert_units` gives `degC` and `hPa`.

### Layout

- `time` and a `height` dimension (10, 50, 100, 150, 200, 250 and 1500 m, where downloaded). `ua`, `va`,
  `wind_speed` and `wind_from_direction` are `(time, height)`. The 10 m wind (`uas`/`vas`, `ua10m`/`va10m`) is
  height 10, so `ds.wind_speed.sel(height=[50, 100])` selects heights directly.
- Other variables (`tas`, `ps`, `hurs`, `ta50m` ...) keep their BARRA2 names and units, with the inventory's long name
  and cell methods as attributes.
- `lat` and `lon` are the BARRA2 node; `requested_lat` and `requested_lon` are the site you asked for.
- Global attributes record the domain, frequency, node selection, the BARRA2 dataset version and the download date,
  the node altitude (`orog`), the barra2-dl version, the licence and a reference. The dataset version is not
  pinned: THREDDS serves only the latest, so `barra2_version` records the version that `latest` resolved to when
  you downloaded (for example `v20240516`), per variable and overall, and `downloaded` says when. Without
  `versions` it reads `latest`.

## Choosing the nodes

By default each series comes from the BARRA2 grid node nearest the point (`nearest`). Two other selections download a
small grid of real nodes instead (`fileout_type='netcdf4'` is implied, because a grid doesn't fit csv). The nodes always
come from the server's response, never from arithmetic on the grid spacing.

| Selection | What you get | csv | netCDF |
|---|---|---|---|
| `nearest` (default) | The nearest node | Yes | Yes |
| `average4` | The four nodes around the point, averaged, plus the four node series | Yes | Yes |
| `area` | Every node in a box you give | No | Yes |

### Four-node average

```python
urlfilenames = barra2_dl.download.point_data_urlfilenames(
    BARRA2_URL, variables, point.lat, point.lon, datetime(2023, 1, 1), datetime(2023, 3, 31),
    fileout_prefix='Demo', domain='AUS-11', freq='1hr', node_selection='average4',
)
barra2_dl.download.download_multithread(urlfilenames, cache_dir)

ds = barra2_dl.merge.merge_netcdf_to_dataset(
    str(cache_dir), 'Demo_AUS-11_1hr_*.nc', domain='AUS-11', freq='1hr', requested=point,
    node_selection='average4', fixed_pattern='Demo_AUS-11_fx_average4_orog.nc',
)
ds.to_netcdf('Demo_AUS-11_1hr_average4_20230101_20230331.nc')
```

You give one point. The average is of the four grid nodes that surround that point (the node either side of it in
latitude and either side in longitude), weighted by the inverse of each node's distance from it. There is no site
boundary and no averaging over an area: the same point always gives the same four nodes. A point exactly on a node gets
that node's values.

To find those nodes, one small download window is requested per variable-month, a grid spacing (0.11 degrees on
AUS-11, 0.04 on AUST-04) either side of the point. The server returns a grid of real nodes for it, typically 3 x 3.
The window is only how the nodes are fetched: the four that surround the point are used and the others are ignored.

**How the average is made.** Speed and direction are averaged differently, on purpose:

- **Speed** is the weighted mean of each node's own speed (a scalar mean). Averaging the components first would give a
  lower speed wherever the nodes' winds point in different directions, and wind power goes with the cube of speed.
- **Direction** comes from the weighted-mean `ua` and `va` (a vector mean). Averaging bearings directly would fail at
  north, where 350 and 10 degrees would average to 180.
- **`ua` and `va`** are the weighted means, and are written too.

So the averaged `wind_speed` is **not** `hypot(ua, va)`: recomputing speed from the averaged components gives the
lower vector-mean value. The file says which mean each variable is in its `cell_methods` (`node: mean (scalar)` or
`node: mean (vector)`). Scalar variables such as `tas` are plain weighted means. This is the same method NOAA's NDBC
uses for buoy winds, and what Copernicus Marine recommends when both speed and direction matter.

**The four node series** are written beside the average. In the netCDF each averaged variable has a `<name>_node`
twin on a `node` dimension (size 4), with `node_lat`, `node_lon`, `node_distance` (km), `node_weight` and, with
`fixed_pattern`, `node_orog` as coordinates. `lat` and `lon` are the point you asked for, and the `orog` attribute is the
weighted mean. Comparing the node series shows which node best represents the point.

**csv output.** `dataset_to_frames(ds)` returns a DataFrame for the average (key `average4`) and one for each node
(`node1` to `node4`), with the same columns as the csv route. `write_csv` writes each to its own file, with a
[metadata header](#csv-metadata-header):

```python
paths = barra2_dl.merge.write_csv(ds, 'output', 'Demo')
# Demo_AUS-11_1hr_average4_20230101_20230331.csv, Demo_AUS-11_1hr_node1_20230101_20230331.csv, ...
```

### Area

```python
from barra2_dl.mapping import LatLonBBox

box = LatLonBBox(north=-23.4, south=-23.7, east=133.5, west=133.2)
urlfilenames = barra2_dl.download.area_data_urlfilenames(
    box, variables, datetime(2023, 1, 1), datetime(2023, 3, 31), fileout_prefix='Farm', domain='AUS-11', freq='1hr'
)
barra2_dl.download.download_multithread(urlfilenames, cache_dir)

ds = barra2_dl.merge.merge_netcdf_to_dataset(
    str(cache_dir), 'Farm_AUS-11_1hr_*.nc', domain='AUS-11', freq='1hr', node_selection='area',
    fixed_pattern='Farm_AUS-11_fx_area_*orog.nc',
)
ds.to_netcdf('Farm_AUS-11_1hr_area_20230101_20230331.nc')
```

The Dataset keeps every node of the box: `lat` and `lon` are dimensions, so the variables are
`(time, height, lat, lon)` and orog is a `(lat, lon)` variable. The server returns the nodes whose grid cell overlaps the
box, so the edge nodes can sit just outside it. An area can't be written as csv.

**Sharing a cache folder.** Point, `average4` and `area` files are named differently (`average4` or `area` and the box
are in the name), so they can share a cache folder. `merge_netcdf_to_dataset` picks only the files of the node
selection you ask for, so a loose pattern such as `Demo_AUS-11_1hr_*.nc` is safe. For the nearest node, read the node
altitude from its exact name (`Demo_AUS-11_fx_orog.nc`), because `read_fixed_fields` reads every file the pattern matches.

## Re-running and the cache

A file already in the cache folder is not downloaded again, so a re-run resumes. Before any request, every cached
file is checked against what you are asking for:

- a point file (csv or netCDF) must have been requested for the same point, to the 3 decimals the server records;
- an `average4` file must have nodes that surround the point;
- an `area` file must cover the box;
- any file that can't be read (empty, cut short, not csv or netCDF) fails the check.

If a file fails, `CacheMismatchError` lists each one with the location it holds and the one you asked for, and nothing
is downloaded. This happens when you move a site but keep its name, because the filename holds the site name and not the
location. Either rename the site (the `fileout_prefix`) so it gets its own files, or delete the files the error lists
from the cache folder, then run again.

A download is written under a temporary `.part` name and renamed when complete, and an empty response is reported as a
failure, so a run that is stopped part way leaves no file that the next run would trust.

## csv metadata header

`merge.write_csv(ds, folder, prefix)` writes the netCDF route's Dataset as csv, one file per frame, and
`merge.write_df_csv(df, path, ...)` writes the csv route's converted DataFrame under the same header. Each file opens
with `key,value` lines, then a blank line, then the same columns as the csv route:

```text
File,barra2-dl output
Source,"BARRA2 BARRA-R2 reanalysis, Bureau of Meteorology, via NCI THREDDS"
Domain,AUS-11
Time step,1hr
Node selection,nearest
Latitude,-23.54
Longitude,133.36
Elevation,747.6107
Elevation units,m
Requested latitude,-23.5527472
Requested longitude,133.3961111
Distance to node,3.6
Distance units,km
Time zone,UTC
Time stamp,instantaneous at the stamp; time-mean variables (pr, rsds) are stamped mid-step
Dataset versions,v20240516
Downloaded,2026-10-31
Created by,barra2-dl 0.3.1
License,"CC BY 4.0, Bureau of Meteorology"
References,http://www.bom.gov.au/research/publications/researchreports/BRR-067.pdf
Header lines,22

time,station,latitude[unit="degrees_north"],longitude[unit="degrees_east"],...
```

Latitude and longitude are decimal degrees (south and west negative). Every key is always present, empty when unknown
(for example `Elevation` when no orog file was supplied). For the four-node average the file also has `Node 1` to
`Node 4` lines (position, distance, weight and altitude of each node), `Header lines` is 26, and each node's own file
holds that node's position, distance and altitude.

**Reading it.** `merge.read_csv(path)` returns the frame and the header as a dict. In pandas or other software, skip
the first `Header lines` lines (the count includes the blank line):

```python
frame, header = barra2_dl.merge.read_csv('output/Demo_AUS-11_1hr_nearest_20230101_20230331.csv')
frame = pd.read_csv(path, skiprows=int(header['Header lines']))  # the same frame, without barra2-dl
```

`header=False` writes the bare frame, as the csv route does. Windographer detects and strips a header block like this
on import. Whether it also reads the latitude, longitude and elevation from the header has not been confirmed; if it
doesn't, set them in Windographer's Configure Dataset dialog after importing.

## Timestamps: :00 and :30

barra2-dl keeps every timestamp exactly as the server returned it, in the cache, the DataFrame, the csv and the
netCDF, for every node selection. It never shifts or resamples.

BARRA2 stamps instantaneous variables (winds, `tas`, `ps`) at the top of the time step, for example 01:00. Variables
averaged over the step (cell methods `time: mean`, such as `pr` and `rsds`) are stamped in the middle of the period they
average, for example 01:30 for 01:00 to 02:00.

- **DataFrame and csv:** downloading both kinds together gives separate :00 and :30 rows, with blanks where a
  variable has no value. Every `wind+density` variable is instantaneous, so this only happens with presets such as
  `environment`.
- **netCDF:** mean variables sit on their own `time_mean` coordinate, with `time_bnds` giving the period each value
  covers, so no rows are padded with blanks. Instantaneous variables use `time`.

If you need one time axis, shift or resample it yourself, after deciding what the average should mean for your
analysis.
