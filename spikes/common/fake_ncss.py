"""A fake NCSS server for the toolkit spikes: serves the tests/data fixtures so a run needs no network.

The one thing a spike uses beyond the public API, because it stands in for the network. It serves AUS-11 only and only
for the fixture point near -23.55, 133.40. Set SPIKE_LIVE=1 to leave the real server alone, SPIKE_DELAY to change the
seconds per file and SPIKE_FAIL to a variable name (for example va50m) to make its requests return 404.
"""

import os
import sys
import time
from collections.abc import Iterator
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


class _Response:
    def __init__(self, status_code: int, content: bytes) -> None:
        self.status_code = status_code
        self.content = content


def _overlapping(axis: np.ndarray, spacing: float, low: float, high: float) -> np.ndarray:
    return (axis - spacing / 2 <= high + EDGE) & (axis + spacing / 2 > low + EDGE)


def _lookup(url: str, query: dict[str, str]) -> _Response:
    """Cut the requested box out of the node-lookup fixture, as tests/test_mapping.py does."""
    domain = 'AUST-04' if '/AUST-04/' in url else 'AUS-11'
    spacing = BARRA2_GRID_SPACING[domain]
    with xr.open_dataset(DATA / LOOKUP[(domain, query['var'])]) as source:
        full = source.load()
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
