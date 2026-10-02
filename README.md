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

This package and example scripts provides examples to recursively download data in csv (for point data) relevant to wind farm resource analysis for
specific locations and time periods.

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

- Point data download to closest node from BARRA2 AUS-11 (BARRA-R2) and AUST-04 (BARRA-C2) 1-hourly reanalysis data
- Parallel, resumable download: files already in the cache folder are skipped
- Merge the downloaded csv files into one DataFrame, and derive wind speed and direction from the u/v components
- Fully typed with annotations and checked with mypy, [PEP561 compatible](https://www.python.org/dev/peps/pep-0561/)

## Installation

barra2-dl is not published on PyPI. Install it from GitHub (Python 3.12 or later):

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
from barra2_dl.globals import BARRA2_INDEX, BARRA2_URL_AUS11_1HR, BARRA2_VAR_WIND_DEFAULT

cache_dir = Path('cache')
cache_dir.mkdir(exist_ok=True)  # the download folder must already exist

# 1. Build one (url, filename) pair per variable per month
urlfilenames = barra2_dl.download.point_data_urlfilenames(
    barra2_url=BARRA2_URL_AUS11_1HR,  # or BARRA2_URL_AUST04_1HR
    barra2_vars=BARRA2_VAR_WIND_DEFAULT,
    latitude=-23.5527472,
    longitude=133.3961111,
    start_datetime=datetime(2023, 1, 1),
    end_datetime=datetime(2023, 3, 31),
    fileout_prefix='Demo',
)

# 2. Download the csv files into the cache folder (files already there are skipped)
barra2_dl.download.download_multithread(urlfilenames, cache_dir)

# 3. Merge the csv files into one DataFrame
df_merged = barra2_dl.merge.merge_csvs_to_df(
    filein_folder=str(cache_dir),
    filename_pattern='Demo*.csv',
    index_for_join=BARRA2_INDEX,
)

# 4. Add wind speed (v*) and meteorological direction (v*_phi_met) columns from ua*/va*
df_converted = barra2_dl.convert.convert_wind_components(df_merged)
```

Also refer to the example Jupyter Notebook and script in `scripts/`.

## License

[CC-BY-4.0](https://github.com/richard-gledhill/barra2-dl/blob/main/LICENSE)


## Roadmap
1) Currently, AUS-11 and AUST-04 1hr is implemented.
2) Add option for AUS-22
3) Implement bulk download for netCDF (for gridded data)
4) Add download progress bar
5) Multi-location download
6) CLI interface

## Contributing
Refer to [Contributing.md](https://github.com/richard-gledhill/barra2-dl/blob/main/CONTRIBUTING.md)

Or if you are so inclined or use this for commercial work you can
[!["Buy Me A Coffee"](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://www.buymeacoffee.com/richardgledhill)

## Authors and acknowledgment

[richard-gledhill](https://github.com/richard-gledhill)

This project was originally generated with [`wemake-python-package`](https://github.com/wemake-services/wemake-python-package).
Refactored after 0.3.0 to uv based on  [`osprey-oss/cookiecutter-uv`](https://github.com/osprey-oss/cookiecutter-uv).
