"""This module contains global or default variables required to download barra2-dl data from thredds.nci.org.au."""

from datetime import timedelta

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

# barra2_aus11_extents http://www.bom.gov.au/research/publications/researchreports/BRR-067.pdf
# Todo BARRA2_AU11_LATLONBBOX = LatLonBBox(north=12.95, south=-57.97, east=207.39, west=88.48)

# Todo BARRA2_AUS11_GRID_SPACING = 0.11

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

# Deprecated: BARRA2_URL pre-filled for one domain at 1hr. Use BARRA2_URL with domain= and freq= instead.
BARRA2_URL_AUS11_1HR = BARRA2_URL.replace('{domain}', 'AUS-11').replace('{model}', 'BARRA-R2').replace('{freq}', '1hr')
BARRA2_URL_AUST04_1HR = (
    BARRA2_URL.replace('{domain}', 'AUST-04').replace('{model}', 'BARRA-C2').replace('{freq}', '1hr')
)
