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

## Timestamps: :00 and :30

barra2-dl keeps every timestamp exactly as the server returned it, in the cache, the DataFrame, the csv and the
netCDF. It never shifts or resamples.

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
