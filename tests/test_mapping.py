"""This module contains the barra2.mapping test function(s)."""

import dataclasses
import os
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import numpy as np
import pytest
import requests
import xarray as xr

import barra2_dl.download
from barra2_dl.download import CacheMismatchError
from barra2_dl.globals import BARRA2_DOMAINS, BARRA2_GRID_SPACING, BARRA2_URL_FX
from barra2_dl.mapping import (
    GridNode,
    Latitude,
    LatLonBBox,
    LatLonPoint,
    Longitude,
    NodeLookupError,
    _lookup_box,
    _lookup_pair,
    _rank_nodes,
    bracket_index,
    distance_km,
    inverse_distance_weights,
    nearest_nodes,
)

# region Test helpers
DATA = Path(__file__).parent / 'data'
# Tests that hit the real THREDDS server are opt-in: set BARRA2_LIVE=1 to run them.
live_network = pytest.mark.skipif(not os.environ.get('BARRA2_LIVE'), reason='live network test; set BARRA2_LIVE=1')
# the 5 x 5 (AUS-11) and 6 x 6 (AUST-04) grids around -23.55, 133.40 that the fake server cuts boxes from
FIXTURES = {
    ('AUS-11', 'orog'): 'ncss_box_superset.nc',
    ('AUS-11', 'sftlf'): 'ncss_box_superset_sftlf.nc',
    ('AUST-04', 'orog'): 'ncss_box_aust04_orog.nc',
    ('AUST-04', 'sftlf'): 'ncss_box_aust04_sftlf.nc',
}
EDGE = 1e-9


class _Response:
    """Minimal stand-in for requests.Response."""

    def __init__(self, status_code: int = 200, content: bytes = b'') -> None:
        self.status_code = status_code
        self.content = content


def _overlapping(axis: np.ndarray, spacing: float, low: float, high: float) -> np.ndarray:
    """Mask of the nodes whose cell overlaps low to high; touching the high edge counts, touching the low does not.

    This is the behaviour pinned by tests/test_ncss_nodes.py.
    """
    return (axis - spacing / 2 <= high + EDGE) & (axis + spacing / 2 > low + EDGE)


def _serve(url: str, folder: Path) -> _Response:
    """Cut the box in the url out of the fixture for its domain and variable, as the server would answer it."""
    query = {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}
    domain = 'AUST-04' if '/AUST-04/' in url else 'AUS-11'
    spacing = BARRA2_GRID_SPACING[domain]
    with xr.open_dataset(DATA / FIXTURES[(domain, query['var'])]) as source:
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
    path = folder / 'served.nc'
    cut.to_netcdf(path, engine='h5netcdf')
    return _Response(200, path.read_bytes())


@pytest.fixture
def ncss(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[str]:
    """Replace requests.get with a fake NCSS server for the fixed fields; the list collects the requested urls."""
    served = tmp_path / 'served'
    served.mkdir()
    requested: list[str] = []

    def _get(url: str, **_kwargs) -> _Response:
        requested.append(url)
        return _serve(url, served)

    monkeypatch.setattr(barra2_dl.download.requests, 'get', _get)
    monkeypatch.setattr(barra2_dl.download.time, 'sleep', lambda _seconds: None)
    return requested


@pytest.fixture
def cache(tmp_path: Path) -> Path:
    """An existing, empty cache folder."""
    folder = tmp_path / 'cache'
    folder.mkdir()
    return folder


def _fixture_axes(domain: str) -> tuple[np.ndarray, np.ndarray]:
    """The lat and lon axes of a domain's fixture grid."""
    with xr.open_dataset(DATA / FIXTURES[(domain, 'orog')]) as ds:
        return ds['lat'].to_numpy(), ds['lon'].to_numpy()


def _axis(text: str, name: str) -> np.ndarray:
    """The values of a 1-D axis in a DAP2 ascii response."""
    found = re.search(rf'\n{name}\[\d+\]\n([^\n]*)', text)
    assert found
    return np.array([float(value) for value in found.group(1).split(',')])


def _field(lats: list[float], lons: list[float], values: list[list[float]]) -> xr.DataArray:
    """A small (lat, lon) field."""
    return xr.DataArray(np.array(values), coords={'lat': lats, 'lon': lons}, dims=('lat', 'lon'))


# endregion


# region Constants and types
# region Latitude
@pytest.mark.parametrize('value', [-90, 0, 45.5, 90])
def test_latitude_valid(value: float) -> None:
    """Latitude accepts values from -90 to 90 inclusive, and is a float."""
    lat = Latitude(value)
    assert isinstance(lat, float)
    assert lat == value


@pytest.mark.parametrize('value', [-90.0001, 90.0001, 200])
def test_latitude_out_of_range(value: float) -> None:
    """Latitude rejects values outside -90 to 90."""
    with pytest.raises(ValueError, match='Lat must be from'):
        Latitude(value)


# endregion


# region Longitude
@pytest.mark.parametrize('value', [-180, 0, 133.39, 180])
def test_longitude_valid(value: float) -> None:
    """Longitude accepts values from -180 to 180 inclusive, and is a float."""
    lon = Longitude(value)
    assert isinstance(lon, float)
    assert lon == value


@pytest.mark.parametrize('value', [-180.0001, 180.0001, 360])
def test_longitude_out_of_range(value: float) -> None:
    """Longitude rejects values outside -180 to 180."""
    with pytest.raises(ValueError, match='Lon must be from'):
        Longitude(value)


# endregion


# region LatLonPoint
def test_lat_lon_point_coerces_to_geodetic_types() -> None:
    """Plain numbers become Latitude and Longitude."""
    point = LatLonPoint(-23.55, 133.39)
    assert isinstance(point.lat, Latitude)
    assert isinstance(point.lon, Longitude)
    assert (point.lat, point.lon) == (-23.55, 133.39)


def test_lat_lon_point_equality() -> None:
    """Points with the same coordinates are equal."""
    assert LatLonPoint(-23.55, 133.39) == LatLonPoint(-23.55, 133.39)
    assert LatLonPoint(-23.55, 133.39) != LatLonPoint(-23.55, 133.4)


@pytest.mark.parametrize(('lat', 'lon'), [(91, 0), (0, 181), (-91, 0), (0, -181)])
def test_lat_lon_point_invalid(lat: float, lon: float) -> None:
    """Out of range coordinates are rejected."""
    with pytest.raises(ValueError):
        LatLonPoint(lat, lon)


# endregion


# region LatLonBBox
def test_lat_lon_bbox_coerces_to_geodetic_types() -> None:
    """Bounding box edges become Latitude and Longitude."""
    bbox = LatLonBBox(north=-10, south=-40, east=150, west=110)
    assert isinstance(bbox.north, Latitude)
    assert isinstance(bbox.south, Latitude)
    assert isinstance(bbox.east, Longitude)
    assert isinstance(bbox.west, Longitude)
    assert (bbox.north, bbox.south, bbox.east, bbox.west) == (-10, -40, 150, 110)


@pytest.mark.parametrize(
    'kwargs',
    [
        {'north': 91, 'south': 0, 'east': 0, 'west': 0},
        {'north': 0, 'south': -91, 'east': 0, 'west': 0},
        {'north': 0, 'south': 0, 'east': 181, 'west': 0},
        {'north': 0, 'south': 0, 'east': 0, 'west': -181},
    ],
)
def test_lat_lon_bbox_invalid(kwargs: dict) -> None:
    """Out of range bounding box edges are rejected."""
    with pytest.raises(ValueError):
        LatLonBBox(**kwargs)


# endregion


# region GridNode
def test_grid_node_is_frozen() -> None:
    """A GridNode cannot be changed after it is made."""
    node = GridNode(-23.54, 133.36, 1.0, 500.0, 100.0)

    with pytest.raises(dataclasses.FrozenInstanceError):
        node.__setattr__('lat', 0.0)


# endregion
# endregion


# region Errors
# region NodeLookupError
def test_node_lookup_error_is_a_runtime_error() -> None:
    """A failed lookup is a RuntimeError, so callers can tell it from a bad argument."""
    assert issubclass(NodeLookupError, RuntimeError)


# endregion
# endregion


# region Public API
# region nearest_nodes
POINT = LatLonPoint(-23.55, 133.40)


def test_nearest_nodes_returns_the_nearest_first_with_the_fixture_values(ncss: list[str]) -> None:
    """The nodes are in order of distance, with orog and sftlf from the server's response."""
    nodes = nearest_nodes(POINT, 'AUS-11', 4)

    assert len(nodes) == 4
    assert (nodes[0].lat, nodes[0].lon) == pytest.approx((-23.54, 133.36))
    assert [node.distance_km for node in nodes] == sorted(node.distance_km for node in nodes)
    assert nodes[0].distance_km == pytest.approx(float(distance_km(-23.55, 133.40, -23.54, 133.36)))
    with (
        xr.open_dataset(DATA / FIXTURES[('AUS-11', 'orog')]) as orog,
        xr.open_dataset(DATA / FIXTURES[('AUS-11', 'sftlf')]) as sftlf,
    ):
        for node in nodes:
            assert node.orog == pytest.approx(float(orog['orog'].sel(lat=node.lat, lon=node.lon, method='nearest')))
            assert node.sftlf == pytest.approx(float(sftlf['sftlf'].sel(lat=node.lat, lon=node.lon, method='nearest')))
            assert 0 <= node.sftlf <= 100


def test_nearest_nodes_asks_for_both_fixed_fields_in_a_box_less_one_percent(ncss: list[str]) -> None:
    """Two requests: orog and sftlf, each for one spacing less 1% either side of the point, as netCDF4."""
    nearest_nodes(POINT, 'AUS-11')

    assert len(ncss) == 2
    for url, var in zip(ncss, ('orog', 'sftlf'), strict=True):
        assert f'var={var}' in url
        assert 'north=-23.4411&south=-23.6589&east=133.5089&west=133.2911' in url
        assert 'horizStride=1' in url
        assert 'accept=netcdf4' in url


@pytest.mark.parametrize(('n', 'expected'), [(1, 1), (4, 4), (9, 9)])
def test_nearest_nodes_returns_n_nodes_of_the_three_by_three_block(ncss: list[str], n: int, expected: int) -> None:
    """A point inside a cell gets the 3 x 3 block around it, so up to 9 nodes."""
    nodes = nearest_nodes(POINT, 'AUS-11', n)

    assert len(nodes) == expected
    assert len({node.lat for node in nearest_nodes(POINT, 'AUS-11', 9)}) == 3
    assert len({node.lon for node in nearest_nodes(POINT, 'AUS-11', 9)}) == 3


@pytest.mark.parametrize('n', [-1, 0, 10])
def test_nearest_nodes_rejects_n_outside_one_to_nine(ncss: list[str], n: int) -> None:
    """A box returns at most 9 nodes, so n outside 1 to 9 is an error before any request."""
    with pytest.raises(ValueError, match='n must be from 1 to 9'):
        nearest_nodes(POINT, 'AUS-11', n)

    assert ncss == []


def test_nearest_nodes_rejects_an_unknown_domain(ncss: list[str]) -> None:
    """The domain must be one of BARRA2_DOMAINS."""
    with pytest.raises(ValueError, match='Unknown domain <AUS-99>'):
        nearest_nodes(POINT, 'AUS-99')

    assert ncss == []


@pytest.mark.parametrize(
    ('domain', 'lat', 'lon'),
    [
        ('AUS-11', -23.55, 133.40),
        ('AUS-11', -23.54, 133.36),
        ('AUS-11', -23.485, 133.415),
        ('AUS-11', -23.60, 133.30),
        ('AUST-04', -23.55, 133.40),
        ('AUST-04', -23.56, 133.41),
    ],
)
def test_nearest_nodes_returns_only_nodes_of_the_grid(ncss: list[str], domain: str, lat: float, lon: float) -> None:
    """Every node is a value of the response's axes, on the lattice of the domain's spacing (RFC-005 5.1)."""
    spacing = BARRA2_GRID_SPACING[domain]
    lats, lons = _fixture_axes(domain)

    nodes = nearest_nodes(LatLonPoint(lat, lon), domain, 9)

    assert nodes
    for node in nodes:
        assert np.isin(node.lat, lats) and np.isin(node.lon, lons)
        assert abs((node.lat - lats[0]) / spacing - round((node.lat - lats[0]) / spacing)) < 1e-6
        assert abs((node.lon - lons[0]) / spacing - round((node.lon - lons[0]) / spacing)) < 1e-6


def test_nearest_nodes_on_aust04_does_not_return_nodes_on_the_aus11_spacing(ncss: list[str]) -> None:
    """The fork's bug: nodes worked out with the wrong domain's spacing. Here no node is a multiple of 0.11."""
    lats, _ = _fixture_axes('AUST-04')

    nodes = nearest_nodes(POINT, 'AUST-04', 9)

    offsets = [(node.lat - lats[0]) / 0.11 for node in nodes if node.lat != lats[0]]
    assert offsets
    assert any(abs(offset - round(offset)) > 1e-3 for offset in offsets)


def test_nearest_nodes_for_a_point_on_a_cell_boundary_returns_the_nodes_either_side(ncss: list[str]) -> None:
    """A point exactly on a cell edge gets the 2 x 2 nodes it sits between, not a block 4 wide."""
    nodes = nearest_nodes(LatLonPoint(-23.485, 133.415), 'AUS-11', 9)

    assert {round(node.lat, 2) for node in nodes} == {-23.54, -23.43}
    assert {round(node.lon, 2) for node in nodes} == {133.36, 133.47}
    assert len(nodes) == 4


def test_nearest_nodes_with_a_cache_keeps_the_two_files_and_reuses_them(ncss: list[str], cache: Path) -> None:
    """The fixed fields go in <cache>/nodes and a repeat lookup makes no request."""
    first = nearest_nodes(POINT, 'AUS-11', 9, cache=cache)
    second = nearest_nodes(POINT, 'AUS-11', 9, cache=cache)

    box = _lookup_box(POINT, BARRA2_GRID_SPACING['AUS-11'])
    names = sorted(_lookup_pair('AUS-11', var, box)[1] for var in ('orog', 'sftlf'))
    assert sorted(path.name for path in (cache / 'nodes').iterdir()) == names
    assert len(ncss) == 2
    assert first == second


def test_nearest_nodes_without_a_cache_writes_nothing(ncss: list[str], cache: Path) -> None:
    """With no cache the files live in a temporary folder that is gone afterwards."""
    nearest_nodes(POINT, 'AUS-11')

    assert list(cache.iterdir()) == []


def test_nearest_nodes_with_a_missing_cache_folder_raises(ncss: list[str], tmp_path: Path) -> None:
    """The cache folder must exist, as for the downloads."""
    with pytest.raises(FileNotFoundError, match='does not exist'):
        nearest_nodes(POINT, 'AUS-11', cache=tmp_path / 'nope')

    assert ncss == []


def test_nearest_nodes_refuses_a_cached_file_that_does_not_cover_the_box(ncss: list[str], cache: Path) -> None:
    """RFC-007's check applies to the lookup files: a file for another box raises before any request."""
    name = _lookup_pair('AUS-11', 'orog', _lookup_box(POINT, BARRA2_GRID_SPACING['AUS-11']))[1]
    (cache / 'nodes').mkdir()
    (cache / 'nodes' / name).write_bytes((DATA / 'ncss_box_inside_one_cell.nc').read_bytes())

    with pytest.raises(CacheMismatchError, match="doesn't cover the box"):
        nearest_nodes(POINT, 'AUS-11', cache=cache)

    assert ncss == []


def test_nearest_nodes_refuses_an_unreadable_cached_file(ncss: list[str], cache: Path) -> None:
    """A cached lookup file that is not a netCDF file raises CacheMismatchError and is not deleted."""
    name = _lookup_pair('AUS-11', 'orog', _lookup_box(POINT, BARRA2_GRID_SPACING['AUS-11']))[1]
    (cache / 'nodes').mkdir()
    (cache / 'nodes' / name).write_bytes(b'not a netcdf file')

    with pytest.raises(CacheMismatchError, match="can't be read"):
        nearest_nodes(POINT, 'AUS-11', cache=cache)

    assert (cache / 'nodes' / name).read_bytes() == b'not a netcdf file'


def test_nearest_nodes_rejects_a_file_without_one_lat_lon_variable(ncss: list[str], cache: Path) -> None:
    """A cached file with two (lat, lon) variables can't be read as one field."""
    name = _lookup_pair('AUS-11', 'orog', _lookup_box(POINT, BARRA2_GRID_SPACING['AUS-11']))[1]
    (cache / 'nodes').mkdir()
    with xr.open_dataset(DATA / FIXTURES[('AUS-11', 'orog')]) as ds:
        ds.load().assign(extra=ds['orog']).to_netcdf(cache / 'nodes' / name, engine='h5netcdf')

    with pytest.raises(NodeLookupError, match='Expected one'):
        nearest_nodes(POINT, 'AUS-11', cache=cache)


def test_nearest_nodes_outside_the_domain_raises_with_the_status(ncss: list[str]) -> None:
    """A point where the server finds no nodes (HTTP 400) is a NodeLookupError that says why."""
    with pytest.raises(NodeLookupError, match='Status code: 400'):
        nearest_nodes(LatLonPoint(10.0, 100.0), 'AUS-11')


def test_nearest_nodes_when_the_server_fails_raises_after_the_retries(
    ncss: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A server error is retried, then reported as a NodeLookupError naming the file."""
    attempts: list[str] = []

    def _fail(url: str, **_kwargs) -> _Response:
        attempts.append(url)
        return _Response(503)

    monkeypatch.setattr(barra2_dl.download.requests, 'get', _fail)

    with pytest.raises(NodeLookupError, match='orog'):
        nearest_nodes(POINT, 'AUS-11')

    assert len(attempts) > 2


@live_network
@pytest.mark.parametrize(
    ('domain', 'lat', 'lon'),
    [
        ('AUS-11', -23.55, 133.40),
        ('AUS-11', -33.87, 151.21),
        ('AUST-04', -33.87, 151.21),
        ('AUST-04', -23.485, 133.415),
    ],
)
def test_nearest_nodes_live_returns_nodes_of_the_full_domain_grid(domain: str, lat: float, lon: float) -> None:
    """Every node is a value of the domain's own latitude and longitude axes, read over OPeNDAP (RFC-005 5.1)."""
    url = BARRA2_URL_FX.split('?')[0].replace('/ncss/grid/', '/dodsC/')
    text = requests.get(
        url.format(domain=domain, model=BARRA2_DOMAINS[domain], var='orog') + '.ascii?lat,lon', timeout=120
    ).text
    lats, lons = _axis(text, 'lat'), _axis(text, 'lon')

    nodes = nearest_nodes(LatLonPoint(lat, lon), domain, 9)

    assert nodes
    assert all(np.isclose(lats, node.lat, atol=1e-6, rtol=0).any() for node in nodes)
    assert all(np.isclose(lons, node.lon, atol=1e-6, rtol=0).any() for node in nodes)


# endregion


# region distance_km
def test_distance_km_one_degree_of_latitude() -> None:
    """One degree of latitude is about 111.2 km."""
    assert distance_km(0, 0, 1, 0) == pytest.approx(111.195, abs=0.01)


def test_distance_km_same_point_is_zero() -> None:
    """A point is no distance from itself."""
    assert distance_km(-33.88, 151.18, -33.88, 151.18) == 0


def test_distance_km_array_and_longitude_shrinks_with_latitude() -> None:
    """Several points at once; a degree of longitude is shorter away from the equator."""
    result = distance_km(60, 0, np.array([60.0, 60.0]), np.array([1.0, 2.0]))

    assert result[1] == pytest.approx(2 * result[0], rel=1e-3)
    assert result[0] == pytest.approx(111.195 / 2, rel=5e-3)


# endregion


# region bracket_index
@pytest.mark.parametrize(
    ('x', 'expected'),
    [(0.0, 0), (0.5, 0), (1.0, 1), (1.5, 1), (2.0, 2), (3.0, 2), (3.0000004, 2), (-0.0000004, 0)],
)
def test_bracket_index_pairs_around_x(x: float, expected: int) -> None:
    """The pair is (i, i + 1); a node at x starts the pair, except the last node, which ends it."""
    assert bracket_index(np.array([0.0, 1.0, 2.0, 3.0]), x) == expected


@pytest.mark.parametrize('x', [-0.1, 3.1])
def test_bracket_index_outside_axis(x: float) -> None:
    """A coordinate beyond the nodes can't be surrounded."""
    with pytest.raises(ValueError, match='outside'):
        bracket_index(np.array([0.0, 1.0, 2.0, 3.0]), x)


# endregion


# region inverse_distance_weights
def test_inverse_distance_weights_sum_to_one_and_favour_near_nodes() -> None:
    """Weights are proportional to 1 / distance."""
    weights = inverse_distance_weights(np.array([1.0, 2.0, 4.0, 4.0]))

    assert weights.sum() == pytest.approx(1)
    assert weights[0] > weights[1] > weights[2]
    assert weights[0] / weights[1] == pytest.approx(2)


def test_inverse_distance_weights_node_at_the_site_takes_all() -> None:
    """A node at the site has all the weight, so the others are ignored."""
    assert inverse_distance_weights(np.array([0.0, 5.0, 5.0, 5.0])).tolist() == [1.0, 0.0, 0.0, 0.0]


# endregion


# endregion


# region Helpers
# region _rank_nodes
def test_rank_nodes_breaks_a_tie_towards_the_lower_longitude() -> None:
    """Two nodes the same distance away are ordered by latitude, then longitude, so the order is stable."""
    orog = _field([0.0], [0.0, 1.0], [[10.0, 20.0]])
    sftlf = _field([0.0], [0.0, 1.0], [[100.0, 0.0]])

    nodes = _rank_nodes(LatLonPoint(0.0, 0.5), orog, sftlf, 2)

    assert [(node.lon, node.orog, node.sftlf) for node in nodes] == [(0.0, 10.0, 100.0), (1.0, 20.0, 0.0)]


def test_rank_nodes_rejects_grids_with_different_nodes() -> None:
    """The orog and sftlf grids must be for the same nodes."""
    orog = _field([0.0], [0.0, 1.0], [[10.0, 20.0]])
    sftlf = _field([0.0], [0.0, 2.0], [[100.0, 0.0]])

    with pytest.raises(NodeLookupError, match='different nodes'):
        _rank_nodes(LatLonPoint(0.0, 0.5), orog, sftlf, 2)


# endregion


# endregion
