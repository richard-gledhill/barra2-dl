# barra2-dl

[![Build Status](https://img.shields.io/github/actions/workflow/status/richard-gledhill/barra2-dl/main.yml?branch=main)](https://github.com/richard-gledhill/barra2-dl/actions/workflows/main.yml?query=branch%3Amain)
[![Python Version](https://img.shields.io/python/required-version-toml?tomlFilePath=https%3A%2F%2Fraw.githubusercontent.com%2Frichard-gledhill%2Fbarra2-dl%2Fmain%2Fpyproject.toml)](https://github.com/richard-gledhill/barra2-dl/blob/main/pyproject.toml)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

A tool for downloading BARRA version 2 (BARRA2) atmospheric reanalysis data.

## Background

barra2-dl is a Python package to bulk download data from
BARRA2 reanalysis data for a specific latitude and longitude. It is for use in
wind resource and energy assessments, but can be used to download other data from BARRA2.

> BARRA2 provides the Bureau's higher resolution regional atmospheric reanalysis
> over Australia and surrounding regions, spanning 1979-present day time period.
> When completed, it replaces the first version of BARRA (Su et al.,
> doi: 10.5194/gmd-14-4357-2021; 10.5194/gmd-12-2049-2019).
>
>It is produced using the Bureau's data assimilation system for numerical weather
> prediction - 4D variational scheme, and ACCESS as a limited-area dynamical
> coupled atmosphere-land model - Unified Model (UM) and JULES.
>
>The data set includes sub-daily, daily and monthly data for temperature,
> moisture, wind and flux variables at sub-surface, surface, and pressure levels,
> and heights above surface. The vertical levels include many pressure levels and
> several heights above surface.
>
>Data Provider: Bureau of Meteorology
>
>NCI Data Catalogue: https://dx.doi.org/10.25914/1x6g-2v48
>NCI THREDDS Data Server: https://dx.doi.org/10.25914/1x6g-2v48
>License: https://creativecommons.org/licenses/by/4.0/
>Extended Documentation: https://opus.nci.org.au/x/DgDADw

Source: https://thredds.nci.org.au/thredds/fileServer/ob53/BARRA2/README.txt

Data from BARRA2 can be downloaded in netCDF or CSV format from the NCI THREDDS server
using the NetCDF Subset Service for Grids / Grids As Points.

However, BARRA2 is structured with data for each variable saved in separate folders with separate files for each month.
Therefore, for the purpose of downloading a subset of variables for a specific location,
a recursive web request is required using the NetcdfSubset Data Access to get subsetted data.

This package and its example scripts download point data as csv, relevant to wind farm resource analysis for
specific locations and time periods, and can write the result as csv or netCDF.

The following links provide an example of the urls:

>Example URL for NetCDF grid files for ua50m wind speed:
> https://thredds.nci.org.au/thredds/ncss/grid/ob53/output/reanalysis/AUS-11/BOM/ERA5/historical/hres/BARRA-R2/v1/1hr/ua50m/latest/ua50m_AUS-11_ERA5_historical_hres_BOM_BARRA-R2_v1_1hr_197901-197901.nc?var=ua50m&north=-36&west=140&east=141&south=-37&horizStride=1&time_start=1979-01-01T00:00:00Z&time_end=1979-01-31T23:00:00Z&&&accept=netcdf3
>
>Or as grid points to get CSV files for ua50m wind speed:
>https://thredds.nci.org.au/thredds/ncss/grid/ob53/output/reanalysis/AUS-11/BOM/ERA5/historical/hres/BARRA-R2/v1/1hr/ua50m/latest/ua50m_AUS-11_ERA5_historical_hres_BOM_BARRA-R2_v1_1hr_197901-197901.nc?var=ua50m&latitude=-36&longitude=140&time_start=1979-01-01T00%3A00%3A00Z&time_end=1979-01-31T23%3A00%3A00Z&timeStride=&vertCoord=&accept=csv

Reference for downloading from thredds is provided here:
https://opus.nci.org.au/display/DAE/examples-thredds

For a full list of BARRA2 variables refer to the BARRA2 FAQ:
https://opus.nci.org.au/pages/viewpage.action?pageId=264241306

Refer to BARRA2 documentation for further details:
https://opus.nci.org.au/pages/viewpage.action?pageId=264241166


## Features

- Point data download to closest node from BARRA2 AUS-11 (BARRA-R2) and AUST-04 (BARRA-C2) reanalysis data,
  1-hourly by default, and 20-minute on AUST-04
- Node selection: the nearest node, an inverse-distance average of the four nodes around the point (with the four node
  series written too), nodes you choose by their exact latitude and longitude after a `nearest_nodes` lookup (with an
  optional mean), or every node in an area (netCDF only)
- Wind at 10, 50, 100, 150, 200, 250 and 1500 m; the 10 m wind (`uas`/`vas`) is output as `ua10m`/`va10m` so every
  height is named alike
- Variable presets for wind energy assessment: `wind`, `wind+density` (the default: winds plus pressure,
  temperature and humidity for air density), `wind+stability`, `extremes`, `environment` and `site`
- Variable names are checked against the BARRA2 inventory before anything is downloaded
- The node altitude (`orog`) comes with every point download; land fraction (`sftlf`) on request
- Parallel, resumable download: files already in the cache folder are skipped
- Merge the downloaded csv files into one DataFrame, and derive wind speed and direction from the u/v components
- netCDF output: download netCDF4 (`fileout_type='netcdf4'`) and `merge.merge_netcdf_to_dataset` gives a CF-style
  xarray Dataset with a `height` dimension, units, the dataset version and the node altitude, ready for
  `to_netcdf()`; `merge.to_dataset` does the same from csv files; `merge.write_csv` writes the Dataset as csv with a metadata header, and `merge.write_df_csv` does the same for the
  csv route's converted frame (`merge.read_csv` reads either back); a cached file that doesn't match the request stops a re-run with `CacheMismatchError`;
  timestamps are kept as served ([how to use](https://richard-gledhill.github.io/barra2-dl/how-to-use/))
- Project file and engine: `project.load_project` reads a TOML project of sites, `project.run_site` downloads, merges and
  writes each site's output with a run summary; downloads retry, report each file, and take progress and cancel
- Optional unit conversion: K to °C, Pa to hPa, precipitation flux to mm/h
- Fully typed with annotations and checked with mypy, [PEP561 compatible](https://www.python.org/dev/peps/pep-0561/)

## Installation

barra2-dl is not published on PyPI yet (a release is planned after the GUI, see the roadmap). Install it from GitHub (Python 3.12 or later):

```bash
pip install git+https://github.com/richard-gledhill/barra2-dl.git
```

Or clone the repository for development (uses [uv](https://docs.astral.sh/uv/)):

```bash
git clone https://github.com/richard-gledhill/barra2-dl.git
cd barra2-dl
uv sync
```

## Example

```python
from datetime import datetime
from pathlib import Path

import barra2_dl
from barra2_dl.globals import BARRA2_INDEX, BARRA2_PRESET_DEFAULT, BARRA2_URL
from barra2_dl.mapping import LatLonPoint

cache_dir = Path('cache')
cache_dir.mkdir(exist_ok=True)  # the download folder must already exist

# 1. Choose the variables with a preset; wind+density is the default
barra2_vars = barra2_dl.download.preset_variables(BARRA2_PRESET_DEFAULT, domain='AUS-11', freq='1hr')

# 2. Build one (url, filename) pair per variable per month, plus one for the node altitude (orog)
urlfilenames = barra2_dl.download.point_data_urlfilenames(
    barra2_url=BARRA2_URL,
    barra2_vars=barra2_vars,
    latitude=-23.5527472,
    longitude=133.3961111,
    start_datetime=datetime(2023, 1, 1),
    end_datetime=datetime(2023, 3, 31),
    fileout_prefix='Demo',
    domain='AUS-11',  # or 'AUST-04'
    freq='1hr',  # or '20min' on AUST-04
)

# 3. Download the csv files into the cache folder (files already there are skipped)
barra2_dl.download.download_multithread(urlfilenames, cache_dir)

# 4. Merge the time series into one DataFrame; the node altitude is read separately
df_merged = barra2_dl.merge.merge_csvs_to_df(
    filein_folder=str(cache_dir),
    filename_pattern='Demo_AUS-11_1hr_*.csv',
    index_for_join=BARRA2_INDEX,
)
node_fields = barra2_dl.merge.read_fixed_fields(str(cache_dir), 'Demo_AUS-11_fx_*.csv')  # {'orog[unit="m"]': ...}

# 5. Add wind speed (v*) and meteorological direction (v*_phi_met) columns from ua*/va*, and optionally convert units
df_converted = barra2_dl.convert.convert_wind_components(df_merged)
df_converted = barra2_dl.convert.convert_units(df_converted)

# 6. Optionally write a netCDF file from the csv data
node_altitude = node_fields['orog[unit="m"]']
ds = barra2_dl.merge.to_dataset(
    df_converted, domain='AUS-11', freq='1hr', requested=LatLonPoint(-23.5527472, 133.3961111), orog=node_altitude
)
ds.to_netcdf(Path('Demo_AUS-11_1hr_nearest_20230101_20230331.nc'))
```

To go straight to netCDF, download with `fileout_type='netcdf4'` in step 2 and use `merge_netcdf_to_dataset` in place
of steps 4 to 6; it is smaller, quicker and carries the dataset version. See the how-to guide below.

Presets are defined at 1-hourly data. At AUST-04 20-minute data use the `wind` preset: pressure and humidity
aren't published every 20 minutes, so `wind+density` raises an error rather than downloading part of it.

Cache files are named `<prefix>_<domain>_<freq>_<var>_<start>_<end>.csv`, so runs for different domains or
frequencies can share a cache folder. `BARRA2_URL_AUS11_1HR` and `BARRA2_URL_AUST04_1HR` still work in place of
`BARRA2_URL` but are deprecated.

For the DataFrame, csv and netCDF outputs and the timestamp convention, see the [how-to guide](https://richard-gledhill.github.io/barra2-dl/how-to-use/). Runnable examples, as scripts and Jupyter notebooks, are in `scripts/`: `example_barra2_dl_csv` and `example_barra2_dl_netcdf`.

## License

[CC-BY-4.0](https://github.com/richard-gledhill/barra2-dl/blob/main/LICENSE)


## Roadmap

Implemented: AUS-11 at `1hr` and AUST-04 at `1hr` and `20min`; wind variables at 10 to 1500 m; variable presets and
the checked variable inventory; the node altitude (`orog`); csv and netCDF output; the nearest node, a four-node
average and an area download.

The work is planned as a series of requirements documents (RFCs), set out in the
[roadmap](https://github.com/richard-gledhill/barra2-dl/blob/main/docs/development/requirements/wind-engineering-roadmap-prd.md#4-rfc-roadmap). In delivery order:

| Order | Work | Status |
|---|---|---|
| 1 | [Fix the wind variable table](https://github.com/richard-gledhill/barra2-dl/blob/main/docs/development/requirements/wind-variables-bugfix-prd.md): real variables, heights, `ua10m`/`va10m` aliases | Done |
| 2 | [Parameter review](https://github.com/richard-gledhill/barra2-dl/blob/main/docs/development/requirements/parameter-review-prd.md): presets, variable inventory, node altitude, unit conversion | Done |
| 3 | [netCDF output, node averaging and area download](https://github.com/richard-gledhill/barra2-dl/blob/main/docs/development/requirements/netcdf-output-prd.md): a CF-style xarray Dataset from netCDF4 downloads or csv, with the nearest node, a four-node average and a `(time, lat, lon)` area download | Done |
| 4 | [GUI](https://github.com/richard-gledhill/barra2-dl/blob/main/docs/development/requirements/gui-prd.md): a download engine with retries, a run summary and a multi-site project file, then a graphical app on top | Draft |
| 5 | First PyPI release, and relicensing the code to MIT | After the GUI |
| 6 | Export to wind-engineering software (Windographer, WAsP `.tab`, openWind, WindPRO) | To be drafted |

Also under consideration, not yet scheduled (see the roadmap above and the [backlog](https://github.com/richard-gledhill/barra2-dl/blob/main/docs/development/backlog.md)): a command-line tool, derived variables
(air density, shear, veer, hub-height speed), a data-quality summary report, and downloading only new data.
The AUS-22 domain is not currently planned.

## Contributing
Refer to [Contributing.md](https://github.com/richard-gledhill/barra2-dl/blob/main/CONTRIBUTING.md)

Or if you are so inclined or use this for commercial work you can
[!["Buy Me A Coffee"](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://www.buymeacoffee.com/richardgledhill)

## Authors and acknowledgment

[richard-gledhill](https://github.com/richard-gledhill)

This project was originally generated with [`wemake-python-package`](https://github.com/wemake-services/wemake-python-package).
Refactored after 0.3.0 to uv based on  [`osprey-oss/cookiecutter-uv`](https://github.com/osprey-oss/cookiecutter-uv).
