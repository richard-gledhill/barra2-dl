"""A fake NCSS server for the toolkit spikes: serves the tests/data fixtures so a run needs no network.

The one thing a spike uses beyond the public API, because it stands in for the network. It serves AUS-11 anywhere in
Australia on the real grid: node lookups (nearest_nodes) and the grid files of a nodes or area download are built for
whatever box is asked for, from the tests/data fixtures, with made-up altitudes and the fixture's weather repeated
across the nodes. A point site's data is still the one fixture point's. Set SPIKE_LIVE=1 to leave the real server
alone, SPIKE_DELAY to change the seconds per file and SPIKE_FAIL to a variable name (for example va50m) to make its
requests return 404.
"""

import math
import os
import sys
import time
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path
from types import CodeType
from urllib.parse import parse_qs, urlsplit

import numpy as np
import requests
import xarray as xr

import barra2_dl.project
from barra2_dl.globals import BARRA2_GRID_SPACING

DATA = Path(__file__).resolve().parents[2] / 'tests' / 'data'
FIXTURE_VARS = ['ua50m', 'va50m', 'tas']
VERSIONS = {'ua50m': 'v20240516', 'va50m': 'v20240516', 'tas': 'v20231001', 'orog': 'v20231001'}
LOOKUP = {
    ('AUS-11', 'orog'): 'ncss_box_superset.nc',
    ('AUS-11', 'sftlf'): 'ncss_box_superset_sftlf.nc',
    ('AUST-04', 'orog'): 'ncss_box_aust04_orog.nc',
    ('AUST-04', 'sftlf'): 'ncss_box_aust04_sftlf.nc',
}
EDGE = 1e-9
FIXTURE_POINT = (-23.55, 133.40)
LAT_RANGE = (-45.0, -10.0)
LON_RANGE = (110.0, 156.0)


class _Response:
    def __init__(self, status_code: int, content: bytes) -> None:
        self.status_code = status_code
        self.content = content


def _overlapping(axis: np.ndarray, spacing: float, low: float, high: float) -> np.ndarray:
    return (axis - spacing / 2 <= high + EDGE) & (axis + spacing / 2 > low + EDGE)


@lru_cache(maxsize=8)
def _extended(domain: str, var: str) -> xr.Dataset:
    """The node-lookup fixture grown to the whole of Australia on the same grid, so any site or polygon has nodes.

    The fixture's own 5 x 5 nodes keep their real values; every other node gets a smooth made-up altitude and is land.
    """
    spacing = BARRA2_GRID_SPACING[domain]
    with xr.open_dataset(DATA / LOOKUP[(domain, var)]) as source:
        fixture = source.load()
    lat0, lon0 = round(float(fixture['lat'][0]), 6), round(float(fixture['lon'][0]), 6)
    below, above = math.ceil((lat0 - LAT_RANGE[0]) / spacing), math.ceil((LAT_RANGE[1] - lat0) / spacing)
    west, east = math.ceil((lon0 - LON_RANGE[0]) / spacing), math.ceil((LON_RANGE[1] - lon0) / spacing)
    lats = np.round(lat0 + spacing * np.arange(-below, above + 1), 6)
    lons = np.round(lon0 + spacing * np.arange(-west, east + 1), 6)
    made_up = (
        400 + 250 * np.sin(lats[:, None] * 7) * np.cos(lons[None, :] * 5)
        if var == 'orog'
        else np.full((len(lats), len(lons)), 100.0)
    )
    grown = xr.DataArray(made_up.astype('float32'), coords={'lat': lats, 'lon': lons}, dims=('lat', 'lon'))
    fixture = fixture.assign_coords(
        lat=np.round(fixture['lat'].to_numpy(), 6), lon=np.round(fixture['lon'].to_numpy(), 6)
    )
    out = xr.Dataset({var: fixture[var].combine_first(grown)})
    out[var].attrs = fixture[var].attrs
    out['crs'] = fixture['crs']
    out.attrs = fixture.attrs
    return out


def _lookup(url: str, query: dict[str, str]) -> _Response:
    """Cut the requested box out of the grown node-lookup grid, as tests/test_mapping.py does with the fixture."""
    domain = 'AUST-04' if '/AUST-04/' in url else 'AUS-11'
    spacing = BARRA2_GRID_SPACING[domain]
    full = _extended(domain, query['var'])
    lat_ok = _overlapping(full['lat'].to_numpy(), spacing, float(query['south']), float(query['north']))
    lon_ok = _overlapping(full['lon'].to_numpy(), spacing, float(query['west']), float(query['east']))
    if not (lat_ok.any() and lon_ok.any()):
        return _Response(400, b'outside the grid')
    cut = full.isel(lat=np.flatnonzero(lat_ok), lon=np.flatnonzero(lon_ok))
    cut.attrs |= {
        'geospatial_lat_min': float(cut['lat'].min()) - spacing / 2,
        'geospatial_lat_max': float(cut['lat'].max()) + spacing / 2,
        'geospatial_lon_min': float(cut['lon'].min()) - spacing / 2,
        'geospatial_lon_max': float(cut['lon'].max()) + spacing / 2,
    }
    return _Response(200, cut.to_netcdf(engine='h5netcdf'))


def _box_data(query: dict[str, str], template: Path) -> _Response:
    """A grid file for the requested box: the fixture's 3 x 3 grid repeated onto the real nodes the box overlaps."""
    grown = _extended('AUS-11', 'orog')
    spacing = BARRA2_GRID_SPACING['AUS-11']
    lat_ok = _overlapping(grown['lat'].to_numpy(), spacing, float(query['south']), float(query['north']))
    lon_ok = _overlapping(grown['lon'].to_numpy(), spacing, float(query['west']), float(query['east']))
    if not (lat_ok.any() and lon_ok.any()):
        return _Response(400, b'outside the grid')
    lats, lons = grown['lat'].to_numpy()[lat_ok], grown['lon'].to_numpy()[lon_ok]
    with xr.open_dataset(template) as source:
        base = source.load()
    tiled = base.isel(lat=np.arange(len(lats)) % base.sizes['lat'], lon=np.arange(len(lons)) % base.sizes['lon'])
    return _Response(200, tiled.assign_coords(lat=lats, lon=lons).to_netcdf(engine='h5netcdf'))


def _callers() -> Iterator[CodeType]:
    frame = sys._getframe(2)
    while frame is not None:
        yield frame.f_code
        frame = frame.f_back


def _make_get(delay: float, fail: str):
    def get(url: str, **_kwargs: object) -> _Response:
        query = {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}
        if 'north' in query and any(code.co_name == 'nearest_nodes' for code in _callers()):
            return _lookup(url, query)
        time.sleep(delay)
        if fail and fail in url:
            return _Response(404, b'missing')
        grid = 'north' in query
        fixed = '/fx/' in url
        extension = 'csv' if query['accept'] == 'csv_file' else 'nc'
        prefix = 'grid' if grid else 'fixture'
        tag = 'average4_' if grid else ''
        name = (
            f'{prefix}_AUS-11_fx_{tag}{query["var"]}.{extension}'
            if fixed
            else f'{prefix}_AUS-11_1hr_{tag}{query["var"]}_20230101_20230103.{extension}'
        )
        if grid:
            return _box_data(query, DATA / name)
        return _Response(200, (DATA / name).read_bytes())

    return get


def install() -> bool:
    """Patch requests.get and the variable lookups, unless SPIKE_LIVE is set. Returns True if the fake is on."""
    if os.environ.get('SPIKE_LIVE'):
        return False
    requests.get = _make_get(float(os.environ.get('SPIKE_DELAY', '0.4')), os.environ.get('SPIKE_FAIL', ''))
    real_preset_variables = barra2_dl.project.preset_variables

    def fixture_variables(preset: str, domain: str = 'AUS-11', freq: str = '1hr') -> list[str]:
        real_preset_variables(preset, domain, freq)
        return FIXTURE_VARS

    barra2_dl.project.preset_variables = fixture_variables
    barra2_dl.project.resolve_variable_versions = lambda *_args: VERSIONS
    return True
