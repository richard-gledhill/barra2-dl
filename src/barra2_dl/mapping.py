"""This modules contains helper geo and mapping classes, constants and functions.

References:
    https://stackoverflow.com/questions/79174938/how-to-fix-order-of-inherited-subclasses-in-python-dataclass/79174970
"""

import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Self

import numpy as np
import xarray as xr
from numpy.typing import ArrayLike

from barra2_dl.globals import BARRA2_DOMAINS, BARRA2_GRID_SPACING, BARRA2_URL_FX_BBOX

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

__all__ = [
    'GridNode',
    'LatLonBBox',
    'LatLonPoint',
    'Latitude',
    'Longitude',
    'NodeLookupError',
    'bracket_index',
    'distance_km',
    'inverse_distance_weights',
    'nearest_nodes',
]


# region Constants and types
class _Geodetic(float):
    """Float specialization base class for Latitude and Longitude.

    Adds _check_limits on min max to avoid code duplication on setting and checking float value.

    Attributes:
        min (float): Minimum allowable value.
        max (float): Maximum allowable value.
        name (str): Name
    """

    min = 0.0
    max = 0.0
    name = 'Geodetic'

    def __new__(cls, value: float | int) -> Self:
        instance = super().__new__(cls, value)
        instance._check_limits()
        return instance

    def _check_limits(self):
        """We _ARE_ a float, so "self"  can be used directly for the value."""
        if not self.min <= self <= self.max:
            raise ValueError(f'{self.name} must be from {self.min} to {self.max}')


class Latitude(_Geodetic):
    """Specialization base class for Latitude and Longitude."""

    min = -90
    max = 90
    name = 'Lat'


class Longitude(_Geodetic):
    """Specialization base class for Latitude and Longitude."""

    min = -180
    max = 180
    name = 'Lon'


@dataclass
class LatLonPoint:
    """Custom point.

    Attributes:
        lat (Latitude): Custom Geodetic
        lon (Longitude): Custom Geodetic
    """

    lat: Latitude
    lon: Longitude

    def __init__(
        self,
        lat: Latitude | float | int,
        lon: Longitude | float | int,
    ) -> None:
        """Set latitude and longitude."""
        self.lat = Latitude(lat)
        self.lon = Longitude(lon)


@dataclass
class LatLonBBox:
    """A north south east west bounding box by latitude and longitude.

    Attributes:
        north (Latitude): Custom Geodetic
        south (Latitude): Custom Geodetic
        east (Longitude): Custom Geodetic
        west (Longitude): Custom Geodetic

    Todo:
        Add checks to make sure co-ordinates are correct with respect to each other.
    """

    north: Latitude
    south: Latitude
    east: Longitude
    west: Longitude

    def __init__(
        self,
        north: Latitude | float | int,
        south: Latitude | float | int,
        east: Longitude | float | int,
        west: Longitude | float | int,
    ) -> None:
        """Set north, south, east, and west attributes."""
        self.north = Latitude(north)
        self.south = Latitude(south)
        self.east = Longitude(east)
        self.west = Longitude(west)


@dataclass(frozen=True)
class GridNode:
    """One node of a BARRA2 grid, as the server returns it.

    Attributes:
        lat (float): Exact grid latitude in degrees north, as served.
        lon (float): Exact grid longitude in degrees east, as served.
        distance_km (float): Great-circle distance from the point the lookup was made for, in km.
        orog (float): Surface altitude of the node in m.
        sftlf (float): Percentage of the node's grid cell occupied by land, 0 to 100.
    """

    lat: float
    lon: float
    distance_km: float
    orog: float
    sftlf: float


# endregion


# region Errors
class NodeLookupError(RuntimeError):
    """The server could not give the nodes around a point, e.g. it is offline or the point is outside the domain."""


# endregion


# region Public API
def nearest_nodes(
    point: LatLonPoint, domain: str = 'AUS-11', n: int = 4, *, cache: str | Path | None = None
) -> list[GridNode]:
    """Return the n grid nodes nearest a point, nearest first, with their altitude and land fraction.

    The nodes come from the server, never from arithmetic on a grid origin: two small NCSS bounding-box requests, for
    the fixed fields orog and sftlf, return every node whose grid cell overlaps a box of one grid spacing (less 1%)
    either side of the point. That is the 3 x 3 block around the cell holding the point, or fewer at the edge of the
    domain, so n is at most 9. Distances are great-circle, ties go to the lower latitude then longitude. For n = 4 these
    are normally, but not always, the four nodes that surround the point, which the four-node average uses.

    With cache, the two files are kept in <cache>/nodes and a repeat lookup of the same point makes no request. A
    cached file is checked as every cache file is (download.CacheMismatchError) and nothing is deleted. Without cache
    nothing is written.

    Args:
        point (LatLonPoint): The place to look around.
        domain (str): BARRA2 domain, a key of BARRA2_DOMAINS. Default 'AUS-11'.
        n (int): How many nodes, 1 to 9. Default 4.
        cache (str | Path | None): An existing folder to keep the lookup files in. Default None.

    Returns:
        list[GridNode]: Up to n nodes, nearest first.

    Raises:
        ValueError: If the domain is unknown or n is not from 1 to 9.
        FileNotFoundError: If cache is given and does not exist.
        NodeLookupError: If the server could not give the nodes, e.g. the point is outside the domain.
        download.CacheMismatchError: If a cached lookup file does not cover the box or can't be read.
    """
    if domain not in BARRA2_GRID_SPACING:
        raise ValueError(f'Unknown domain <{domain}>. Domains: {", ".join(BARRA2_DOMAINS)}.')
    if not 1 <= n <= 9:
        raise ValueError(f'n must be from 1 to 9, because a box returns at most a 3 x 3 block; got {n}.')
    # download imports this module, so it can only be imported here, not at the top
    from barra2_dl.download import download_serial

    box = _lookup_box(point, BARRA2_GRID_SPACING[domain])
    pairs = [_lookup_pair(domain, var, box) for var in ('orog', 'sftlf')]
    with tempfile.TemporaryDirectory() as scratch:
        if cache is None:
            folder = Path(scratch)
        else:
            if not Path(cache).is_dir():
                raise FileNotFoundError(f'The cache folder <{cache}> does not exist.')
            folder = Path(cache) / 'nodes'
            folder.mkdir(exist_ok=True)
        results = download_serial(pairs, folder)
        failed = [result for result in results if result.status not in ('downloaded', 'skipped')]
        if failed:
            reason = '; '.join(f'{result.filename}: {result.error}' for result in failed)
            raise NodeLookupError(
                f'Could not get the nodes around {float(point.lat):.4f}, {float(point.lon):.4f} in {domain}: {reason}'
            )
        orog, sftlf = (_read_field(folder / name) for _, name in pairs)
    return _rank_nodes(point, orog, sftlf, n)


def distance_km(lat1: float, lon1: float, lat2: ArrayLike, lon2: ArrayLike) -> np.ndarray:
    """Great-circle (haversine) distance in km from one point to another, or to each of several.

    Args:
        lat1 (float): Latitude of the first point in degrees.
        lon1 (float): Longitude of the first point in degrees.
        lat2 (ArrayLike): Latitude(s) of the other point(s) in degrees.
        lon2 (ArrayLike): Longitude(s) of the other point(s) in degrees.

    Returns:
        np.ndarray: The distance(s) in km, using a mean Earth radius of 6371.0088 km.

    Examples:
        >>> round(float(distance_km(0, 0, 0, 1)), 1)
        111.2
    """
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    half_dlat, half_dlon = (phi2 - phi1) / 2, np.radians(np.asarray(lon2) - lon1) / 2
    a = np.sin(half_dlat) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(half_dlon) ** 2
    return np.asarray(2 * 6371.0088 * np.arcsin(np.sqrt(a)))


def bracket_index(values: np.ndarray, x: float, tolerance: float = 1e-6) -> int:
    """Return the index i of the pair of neighbouring nodes (i, i + 1) on a sorted axis that surround x.

    If x lies on a node, that node is the first of the pair, or the second when it is the last node. The axis must hold
    at least two nodes, and x must lie within it.

    Args:
        values (np.ndarray): Node coordinates in ascending order, e.g. the lat or lon of a bounding-box grid.
        x (float): The coordinate to surround.
        tolerance (float): How far outside the axis x may be, and how close to a node counts as on it, in degrees.

    Returns:
        int: The index of the lower node of the pair.

    Raises:
        ValueError: If x is outside the axis.

    Examples:
        >>> bracket_index(np.array([0.0, 1.0, 2.0]), 1.5), bracket_index(np.array([0.0, 1.0, 2.0]), 2.0)
        (1, 1)
    """
    if x < values[0] - tolerance or x > values[-1] + tolerance:
        raise ValueError(f'{x} is outside the nodes {values[0]} to {values[-1]}.')
    last_at_or_below = int(np.searchsorted(values, x + tolerance, side='right')) - 1
    return min(max(last_at_or_below, 0), len(values) - 2)


def inverse_distance_weights(distances: np.ndarray, tolerance: float = 1e-6) -> np.ndarray:
    """Return weights proportional to 1 / distance, summing to 1; a node at the site takes all the weight.

    Args:
        distances (np.ndarray): Distance from the site to each node, in any one unit.
        tolerance (float): A distance below this counts as zero.

    Returns:
        np.ndarray: One weight per node.

    Examples:
        >>> inverse_distance_weights(np.array([1.0, 3.0])).tolist()
        [0.75, 0.25]
        >>> inverse_distance_weights(np.array([0.0, 3.0])).tolist()
        [1.0, 0.0]
    """
    on_node = distances < tolerance
    weights = on_node.astype(float) if on_node.any() else 1 / distances
    return weights / weights.sum()


# endregion


# region Helpers
def _lookup_box(point: LatLonPoint, spacing: float) -> dict[str, float]:
    """Return the lookup box: one spacing either side of the point, less 1% of a spacing, to keep it off cell edges.

    NCSS counts a cell touching the north or east edge of a box but not one touching the south or west edge, so a box
    edge exactly on a cell edge is unreliable. With the 1% that happens only for a point 1% of a spacing from a cell
    boundary, instead of for a point on one (a round coordinate such as 133.415 on AUS-11).
    """
    half = spacing - spacing / 100
    lat, lon = float(point.lat), float(point.lon)
    return {
        'north': round(lat + half, 6),
        'south': round(lat - half, 6),
        'east': round(lon + half, 6),
        'west': round(lon - half, 6),
    }


def _lookup_pair(domain: str, var: str, box: dict[str, float]) -> tuple[str, str]:
    """Return the (url, filename) of one fixed field for the lookup box; the box, at 4 decimals, is in the filename."""
    url = BARRA2_URL_FX_BBOX.format(domain=domain, model=BARRA2_DOMAINS[domain], var=var, fileout_type='netcdf4', **box)
    tag = f'n{box["north"]:.4f}_s{box["south"]:.4f}_e{box["east"]:.4f}_w{box["west"]:.4f}'
    return url, f'{domain}_fx_{var}_{tag}.nc'


def _read_field(path: Path) -> xr.DataArray:
    """Read the (lat, lon) fixed field in a lookup file, loaded and sorted ascending."""
    with xr.open_dataset(path, engine='h5netcdf') as ds:
        names = [name for name in ds.data_vars if ds[name].dims == ('lat', 'lon')]
        if len(names) != 1:
            raise NodeLookupError(f'Expected one (lat, lon) data variable in <{path.name}>, found {len(names)}.')
        return ds[names[0]].load().reset_coords(drop=True).astype(float).sortby('lat').sortby('lon')


def _rank_nodes(point: LatLonPoint, orog: xr.DataArray, sftlf: xr.DataArray, n: int) -> list[GridNode]:
    """Return the n nodes of the grids nearest the point, nearest first; ties go to the lower lat then lon."""
    if not (np.array_equal(orog['lat'], sftlf['lat']) and np.array_equal(orog['lon'], sftlf['lon'])):
        raise NodeLookupError('The orog and sftlf grids have different nodes.')
    lats, lons = (grid.ravel() for grid in np.meshgrid(orog['lat'].to_numpy(), orog['lon'].to_numpy(), indexing='ij'))
    distances = distance_km(float(point.lat), float(point.lon), lats, lons)
    order = np.lexsort((lons, lats, distances))[:n]
    orogs, land = orog.to_numpy().ravel(), sftlf.to_numpy().ravel()
    return [
        GridNode(float(lats[k]), float(lons[k]), float(distances[k]), float(orogs[k]), float(land[k])) for k in order
    ]


# endregion
