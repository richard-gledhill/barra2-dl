"""This module contains the barra2.mapping test function(s)."""

from typing import Any

import numpy as np
import pandas as pd
import pytest

from barra2_dl.mapping import (
    Latitude,
    LatLonBBox,
    LatLonPoint,
    Longitude,
    _find_nearest_point,
    _format_lat_lon,
    _generate_point_grid,
    bracket_index,
    distance_km,
    inverse_distance_weights,
)


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


# region _generate_point_grid
def test_generate_point_grid_dict() -> None:
    """A dict bounding box gives a lat/lon grid including both edges."""
    grid = _generate_point_grid({'north': 1, 'south': 0, 'east': 1, 'west': 0}, lat_res=1)

    assert list(grid.columns) == ['latitude', 'longitude']
    assert len(grid) == 4
    assert set(zip(grid['latitude'], grid['longitude'], strict=True)) == {(0, 0), (0, 1), (1, 0), (1, 1)}


def test_generate_point_grid_separate_lon_resolution() -> None:
    """lon_res overrides lat_res for longitudes only."""
    grid = _generate_point_grid({'north': 1, 'south': 0, 'east': 1, 'west': 0}, lat_res=1, lon_res=0.5)

    assert len(grid) == 2 * 3
    assert sorted(grid['longitude'].unique()) == [0, 0.5, 1]


def test_generate_point_grid_offset_gives_cell_centres() -> None:
    """With offset the points sit at the centre of each cell."""
    grid = _generate_point_grid({'north': 1, 'south': 0, 'east': 1, 'west': 0}, lat_res=1, offset=True)

    assert grid['latitude'].tolist() == [0.5]
    assert grid['longitude'].tolist() == [0.5]


@pytest.mark.parametrize('bbox', [{'north': 1, 'south': 0, 'east': 1}, (1, 0, 1), 'bbox', None])
def test_generate_point_grid_invalid_bounds(bbox) -> None:
    """Incomplete dicts, wrong length tuples and other types are rejected."""
    with pytest.raises(ValueError):
        _generate_point_grid(bbox, lat_res=1)


@pytest.mark.xfail(strict=True, raises=TypeError, reason='tuple bounds pass validation but are then indexed by key')
def test_generate_point_grid_tuple() -> None:
    """The docstring promises tuple input (north, south, east, west)."""
    bbox: Any = (1, 0, 1, 0)
    grid = _generate_point_grid(bbox, lat_res=1)
    assert len(grid) == 4


# endregion


# region _find_nearest_point
def test_find_nearest_point() -> None:
    """The closest grid row is returned."""
    grid = _generate_point_grid({'north': 10, 'south': 0, 'east': 10, 'west': 0}, lat_res=1)

    nearest = _find_nearest_point(grid, 3.2, 6.9)

    assert isinstance(nearest, pd.Series)
    assert (nearest['latitude'], nearest['longitude']) == (3, 7)


@pytest.mark.parametrize(('lat', 'lon'), [(-1, 5), (11, 5), (5, -1), (5, 11)])
def test_find_nearest_point_outside_grid(lat: float, lon: float) -> None:
    """A target outside the grid extent is rejected."""
    grid = _generate_point_grid({'north': 10, 'south': 0, 'east': 10, 'west': 0}, lat_res=1)

    with pytest.raises(ValueError, match='out of the range'):
        _find_nearest_point(grid, lat, lon)


# endregion


# region _format_lat_lon
@pytest.mark.parametrize(
    ('latitude', 'longitude', 'expected'),
    [
        (-23.5527472, 133.3961111, ['S23.55', '133.40']),
        (23.5527472, 133.3961111, ['23.55', '133.40']),
        (0, 0, ['0.00', '0.00']),
    ],
)
def test_format_lat_lon(latitude: float, longitude: float, expected: list[str]) -> None:
    """Latitudes are formatted to two decimals, with an S prefix when negative."""
    assert _format_lat_lon(latitude, longitude) == expected


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
