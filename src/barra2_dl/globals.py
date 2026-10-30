"""This module contains global or default variables required to download barra2-dl data from thredds.nci.org.au."""

import csv
from datetime import timedelta
from importlib.resources import files

# Todo from .mapping import LatLonBBox

# index for barra2 used to join separate files
BARRA2_INDEX = [
    'time',
    'station',
    'latitude[unit="degrees_north"]',
    'longitude[unit="degrees_east"]',
]

# BARRA2 height wind pairs (ua, va, height in metres above ground), by server name. The names are the same on every
# domain and frequency with height winds. uas/vas are the 10 m winds; there is no ua10m/va10m on the server.
BARRA2_WIND_VARS: list[tuple[str, str, int]] = [
    ('uas', 'vas', 10),
    ('ua50m', 'va50m', 50),
    ('ua100m', 'va100m', 100),
    ('ua150m', 'va150m', 150),
    ('ua200m', 'va200m', 200),
    ('ua250m', 'va250m', 250),
    ('ua1500m', 'va1500m', 1500),
]

# barra2-dl alias -> BARRA2 server variable. Aliases are downloaded under the server name, and the converted output
# uses the alias so the 10 m wind is named like the other heights.
BARRA2_VAR_ALIASES = {'ua10m': 'uas', 'va10m': 'vas'}

# BARRA2 domain -> model that produced it
BARRA2_DOMAINS = {'AUS-11': 'BARRA-R2', 'AUST-04': 'BARRA-C2'}

# Frequencies downloadable for each domain, with their time step. 1hr is the default.
BARRA2_FREQS = {
    'AUS-11': {'1hr': timedelta(hours=1)},
    'AUST-04': {'1hr': timedelta(hours=1), '20min': timedelta(minutes=20)},
}

# Frequency folder of the fixed (time-invariant) fields such as orog and sftlf, fetched once per node
BARRA2_FIXED_FREQ = 'fx'


def _read_inventory() -> list[dict[str, str]]:
    """Read the BARRA2 variable inventory shipped in barra2_dl/data, built by scripts/build_barra2_inventory.py."""
    text = files('barra2_dl').joinpath('data', 'barra2_variables.csv').read_text(encoding='utf-8')
    return list(csv.DictReader(text.splitlines()))


# Variables barra2-dl can download, per (domain, freq), including the fixed fields under (domain, 'fx')
BARRA2_VARS: dict[tuple[str, str], frozenset[str]] = {}
# Units, cell methods and long name of each variable, per (domain, freq, var)
BARRA2_VAR_INFO: dict[tuple[str, str, str], dict[str, str]] = {}
for _row in _read_inventory():
    _key = (_row['domain'], _row['freq'])
    BARRA2_VARS[_key] = BARRA2_VARS.get(_key, frozenset()) | {_row['var']}
    BARRA2_VAR_INFO[(*_key, _row['var'])] = {k: _row[k] for k in ('units', 'cell_methods', 'long_name')}

# Fixed fields added to every point download, once per node
BARRA2_FIXED_VARS_AUTO = ['orog']

# Named variable presets for wind energy assessment (RFC-002). All are available at 1hr on both domains.
_WIND = ['uas', 'vas', 'ua50m', 'va50m', 'ua100m', 'va100m', 'ua150m', 'va150m', 'ua200m', 'va200m', 'ua250m', 'va250m']
_DENSITY = ['ps', 'tas', 'ta50m', 'ta100m', 'ta150m', 'ta200m', 'ta250m', 'hurs']
BARRA2_PRESETS = {
    'wind': _WIND,
    'wind+density': _WIND + _DENSITY,
    'wind+stability': _WIND + _DENSITY + ['zmla', 'hfss'],
    'extremes': ['sfcWindmax', 'wsgsmax'],
    'environment': ['pr', 'rsds', 'hurs', 'tas'],
    'site': ['sftlf'],
}

# Preset used when the user picks none
BARRA2_PRESET_DEFAULT = 'wind+density'

# barra2_aus11_extents http://www.bom.gov.au/research/publications/researchreports/BRR-067.pdf
# Todo BARRA2_AU11_LATLONBBOX = LatLonBBox(north=12.95, south=-57.97, east=207.39, west=88.48)

# Grid spacing of each domain in degrees (about 11 km and 4 km). Sizes the box around a site for the four-node
# average; the nodes themselves always come from the bounding-box response, never from this arithmetic.
BARRA2_GRID_SPACING = {'AUS-11': 0.11, 'AUST-04': 0.04}

# How the nodes for a site are chosen: the nearest node (point request), the four nodes around the site averaged, or
# every node in a user-given box (netCDF only)
BARRA2_NODE_SELECTIONS = ('nearest', 'average4', 'area')

# default list of BARRA2 variables for wind analysis
BARRA2_VAR_WIND_DEFAULT = ['uas', 'vas', 'ua50m', 'va50m', 'ua100m', 'va100m', 'ua150m', 'va150m', 'ta50m']

# optional limited variables used in pytest
BARRA2_VAR_WIND_50 = ['ua50m', 'va50m', 'ta50m']

# Base BOM BARRA2 thredds url for NetCDF Subset Service for Grids As Points, for any domain and frequency
# Reference url:
# https://thredds.nci.org.au/thredds/ncss/grid/ob53/output/reanalysis/AUST-04/BOM/ERA5/
# historical/hres/BARRA-C2/v1/20min/ua50m/latest/
# ua50m_AUST-04_ERA5_historical_hres_BOM_BARRA-C2_v1_20min_202001-202001.nc?
# var=ua50m&latitude=-33.88&longitude=151.18
# &time_start=2020-01-01T00:00:00Z&time_end=2020-01-31T23:40:00Z&timeStride=&vertCoord=&accept=csv
BARRA2_URL = (
    'https://thredds.nci.org.au/thredds/ncss/grid/ob53/output/reanalysis/{domain}/BOM/ERA5'
    '/historical/hres/{model}/v1/{freq}/{var}/latest/'
    '{var}_{domain}_ERA5_historical_hres_BOM_{model}_v1_{freq}_{year}{month:02d}-{year}{month:02d}.nc'
    '?var={var}&latitude={latitude}&longitude={longitude}'
    '&time_start={time_start_str}&time_end={time_end_str}'
    '&timeStride=&vertCoord='
    '&accept={fileout_type}'
)

# Fixed (fx) fields have one file per domain, with no month in the name and no time range
# Reference url:
# https://thredds.nci.org.au/thredds/ncss/grid/ob53/output/reanalysis/AUS-11/BOM/ERA5/historical/hres/BARRA-R2/v1/
# fx/orog/latest/orog_AUS-11_ERA5_historical_hres_BOM_BARRA-R2_v1.nc?
# var=orog&latitude=-33.88&longitude=151.18&accept=csv
BARRA2_URL_FX = (
    'https://thredds.nci.org.au/thredds/ncss/grid/ob53/output/reanalysis/{domain}/BOM/ERA5'
    '/historical/hres/{model}/v1/fx/{var}/latest/'
    '{var}_{domain}_ERA5_historical_hres_BOM_{model}_v1.nc'
    '?var={var}&latitude={latitude}&longitude={longitude}'
    '&accept={fileout_type}'
)

# Deprecated: BARRA2_URL pre-filled for one domain at 1hr. Use BARRA2_URL with domain= and freq= instead.
BARRA2_URL_AUS11_1HR = BARRA2_URL.replace('{domain}', 'AUS-11').replace('{model}', 'BARRA-R2').replace('{freq}', '1hr')
BARRA2_URL_AUST04_1HR = (
    BARRA2_URL.replace('{domain}', 'AUST-04').replace('{model}', 'BARRA-C2').replace('{freq}', '1hr')
)

# Bounding-box (grid) requests return a (time, lat, lon) grid of real nodes, as netCDF4 only. NCSS returns the
# nodes whose grid cell overlaps the box, so a box of one grid spacing either side of a site returns a 3 x 3 grid.
# Reference url:
# https://thredds.nci.org.au/thredds/ncss/grid/ob53/output/reanalysis/AUS-11/BOM/ERA5/historical/hres/BARRA-R2/v1/
# 1hr/ua50m/latest/ua50m_AUS-11_ERA5_historical_hres_BOM_BARRA-R2_v1_1hr_202301-202301.nc?
# var=ua50m&north=-23.44&south=-23.66&east=133.51&west=133.29&horizStride=1
# &time_start=2023-01-01T00:00:00Z&time_end=2023-01-31T23:00:00Z&accept=netcdf4
BARRA2_URL_BBOX = (
    'https://thredds.nci.org.au/thredds/ncss/grid/ob53/output/reanalysis/{domain}/BOM/ERA5'
    '/historical/hres/{model}/v1/{freq}/{var}/latest/'
    '{var}_{domain}_ERA5_historical_hres_BOM_{model}_v1_{freq}_{year}{month:02d}-{year}{month:02d}.nc'
    '?var={var}&north={north}&south={south}&east={east}&west={west}&horizStride=1'
    '&time_start={time_start_str}&time_end={time_end_str}'
    '&accept={fileout_type}'
)

# The same for a fixed (fx) field, which has no time range
BARRA2_URL_FX_BBOX = (
    'https://thredds.nci.org.au/thredds/ncss/grid/ob53/output/reanalysis/{domain}/BOM/ERA5'
    '/historical/hres/{model}/v1/fx/{var}/latest/'
    '{var}_{domain}_ERA5_historical_hres_BOM_{model}_v1.nc'
    '?var={var}&north={north}&south={south}&east={east}&west={west}&horizStride=1'
    '&accept={fileout_type}'
)
