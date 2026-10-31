"""This modules contains helper geo and mapping classes, constants and functions.

References:
    https://stackoverflow.com/questions/79174938/how-to-fix-order-of-inherited-subclasses-in-python-dataclass/79174970
"""

import json
import logging
import math
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self
from xml.parsers import expat

import numpy as np
import xarray as xr
from numpy.typing import ArrayLike

from barra2_dl.globals import BARRA2_DOMAINS, BARRA2_GRID_SPACING, BARRA2_URL_FX_BBOX

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

_MAX_VERTICES = 5000
_USED = 1e-9  # a cell is used when the share of it inside the polygon is above this
_KM_PER_DEGREE = 6371.0088 * math.pi / 180

__all__ = [
    'BoundaryFileError',
    'GridNode',
    'LatLonBBox',
    'LatLonPoint',
    'Latitude',
    'Longitude',
    'NodeLookupError',
    'Polygon',
    'bracket_index',
    'distance_km',
    'inverse_distance_weights',
    'nearest_nodes',
    'polygon_from_geojson',
    'polygon_from_kml',
    'read_polygon',
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


@dataclass(frozen=True)
class Polygon:
    """A site boundary: an outline with optional holes, in WGS 84 degrees, planar for area and overlap.

    The rings are checked and normalised when the Polygon is made (exterior counter-clockwise, holes clockwise, the
    closing vertex dropped), so any Polygon is a valid boundary.

    Attributes:
        exterior (tuple[tuple[float, float], ...]): The (lat, lon) vertices of the outline.
        holes (tuple[tuple[tuple[float, float], ...], ...]): Rings cut out of the outline, each as (lat, lon) vertices.
        source (str): Where it came from, a file name or 'drawn', recorded in the run summary.

    Raises:
        BoundaryFileError: If a ring has fewer than 3 distinct vertices, repeats a vertex, has no area, is out of range,
            has more than 5,000 vertices, crosses itself or another ring, or a hole lies outside the outline.
    """

    exterior: tuple[tuple[float, float], ...]
    holes: tuple[tuple[tuple[float, float], ...], ...] = ()
    source: str = ''

    def __post_init__(self) -> None:
        """Check the rings, and store them oriented and without the closing vertex."""
        exterior = _clean_ring(self.exterior, 'The outline')
        holes = tuple(_clean_ring(hole, f'Hole {k}') for k, hole in enumerate(self.holes, start=1))
        _check_rings(exterior, holes)
        object.__setattr__(self, 'exterior', _oriented(exterior, counter_clockwise=True))
        object.__setattr__(self, 'holes', tuple(_oriented(hole, counter_clockwise=False) for hole in holes))

    def bbox(self) -> LatLonBBox:
        """Return the bounding box of the outline."""
        lats, lons = zip(*self.exterior, strict=True)
        return LatLonBBox(north=max(lats), south=min(lats), east=max(lons), west=min(lons))

    def area_deg2(self) -> float:
        """Return the area of the outline less the holes, in square degrees."""
        return sum(_signed_area(ring) for ring in (self.exterior, *self.holes))

    def area_km2(self) -> float:
        """Return the area in km2, approximately: square degrees scaled by the cosine of the centroid latitude."""
        return self.area_deg2() * _KM_PER_DEGREE**2 * math.cos(math.radians(float(self.centroid().lat)))

    def centroid(self) -> LatLonPoint:
        """Return the area centroid of the outline less the holes."""
        total = self.area_deg2()
        lat_sum = lon_sum = 0.0
        for ring in (self.exterior, *self.holes):
            area, (lat, lon) = _signed_area(ring), _ring_centroid(ring)
            lat_sum, lon_sum = lat_sum + area * lat, lon_sum + area * lon
        return LatLonPoint(lat_sum / total, lon_sum / total)

    def contains(self, point: LatLonPoint) -> bool:
        """Return True if the point is inside the outline and outside every hole (even-odd rule)."""
        crossings = sum(
            _ray_crossings(ring, float(point.lat), float(point.lon)) for ring in (self.exterior, *self.holes)
        )
        return crossings % 2 == 1

    def cell_overlap(self, lats: ArrayLike, lons: ArrayLike, spacing: float) -> np.ndarray:
        """Return, for each node, the share (0 to 1) of its grid cell that lies inside the boundary.

        A cell is the node plus or minus half the spacing in each direction, the cell NCSS uses to decide which nodes a
        box returns. The boundary is clipped to each cell, holes subtracted. A boundary that only touches a cell's edge
        gives 0.

        Args:
            lats (ArrayLike): Node latitudes of the grid axis.
            lons (ArrayLike): Node longitudes of the grid axis.
            spacing (float): The grid spacing in degrees.

        Returns:
            np.ndarray: Shape (len(lats), len(lons)).
        """
        lat_axis, lon_axis = np.asarray(lats, dtype=float), np.asarray(lons, dtype=float)
        half, box = spacing / 2, self.bbox()
        overlap = np.zeros((len(lat_axis), len(lon_axis)))
        for i, lat in enumerate(lat_axis):
            if lat + half <= box.south or lat - half >= box.north:
                continue
            for j, lon in enumerate(lon_axis):
                if lon + half <= box.west or lon - half >= box.east:
                    continue
                window = (lon - half, lat - half, lon + half, lat + half)
                inside = _clipped_area(self.exterior, window) - sum(_clipped_area(hole, window) for hole in self.holes)
                overlap[i, j] = inside / spacing**2
        return np.clip(overlap, 0.0, 1.0)


# endregion


# region Errors
class NodeLookupError(RuntimeError):
    """The server could not give the nodes around a point, e.g. it is offline or the point is outside the domain."""


class BoundaryFileError(ValueError):
    """A boundary file or shape is not usable; the message says which file and what to change."""


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


def read_polygon(path: str | Path) -> Polygon:
    """Read a site boundary from a GeoJSON (.geojson, .json) or KML (.kml) file.

    The file must hold one polygon in WGS 84; see polygon_from_geojson and polygon_from_kml for what is accepted.

    Args:
        path (str | Path): The boundary file.

    Returns:
        Polygon: The boundary, with the file name as its source.

    Raises:
        BoundaryFileError: If the file type is not supported or the file is not a usable boundary.
        OSError: If the file cannot be read.
    """
    file = Path(path)
    suffix = file.suffix.lower()
    if suffix == '.kmz':
        raise BoundaryFileError(f'{file.name} is zipped KML (KMZ); extract the .kml file from it and use that.')
    if suffix not in ('.geojson', '.json', '.kml'):
        raise BoundaryFileError(
            f'{file.name}: use a GeoJSON (.geojson, .json) or KML (.kml) file; shapefiles are not read.'
        )
    text = file.read_text(encoding='utf-8-sig')
    return polygon_from_kml(text, file.name) if suffix == '.kml' else polygon_from_geojson(text, file.name)


def polygon_from_geojson(text: str, source: str = '') -> Polygon:
    """Parse a boundary from GeoJSON text: a Polygon, or a Feature or FeatureCollection holding exactly one.

    Coordinates are longitude then latitude in WGS 84 (a third value is ignored); a legacy crs member is accepted only
    if it names WGS 84. A MultiPolygon of one part is accepted; more than one polygon is refused.

    Args:
        text (str): The GeoJSON.
        source (str): The file name, for messages and the run summary.

    Returns:
        Polygon: The boundary.

    Raises:
        BoundaryFileError: If the text is not JSON, holds no polygon or more than one, uses another CRS, or the polygon
            is not valid.
    """
    name = source or 'The GeoJSON'
    try:
        data = json.loads(text)
    except ValueError as error:
        raise BoundaryFileError(f'{name} is not valid JSON: {error}.') from None
    crs = data.get('crs') if isinstance(data, dict) else None
    label = str(crs.get('properties', {}).get('name', '')) if isinstance(crs, dict) else ''
    if crs is not None and not ('CRS84' in label or '4326' in label):
        raise BoundaryFileError(
            f'{name} uses the coordinate system <{label}>; only WGS 84 is read. Re-export it as WGS 84.'
        )
    parts = _geojson_polygons(data, name)
    if len(parts) != 1:
        raise BoundaryFileError(
            f'{name} holds {len(parts)} polygons; give each its own site.' if parts else f'{name} holds no polygon.'
        )
    rings = [_lonlat_ring(ring, name) for ring in parts[0]]
    if not rings:
        raise BoundaryFileError(f'{name} has a polygon without coordinates.')
    return Polygon(rings[0], tuple(rings[1:]), source)


def polygon_from_kml(text: str, source: str = '') -> Polygon:
    """Parse a boundary from KML text: one Polygon (outerBoundaryIs and any innerBoundaryIs) in WGS 84.

    Element names are matched without their namespace. A file with a DOCTYPE or entity declaration is refused before
    parsing, because the parser is not hardened against entity expansion.

    Args:
        text (str): The KML.
        source (str): The file name, for messages and the run summary.

    Returns:
        Polygon: The boundary.

    Raises:
        BoundaryFileError: If the text is not KML, has a DOCTYPE, holds no polygon or more than one, or the polygon is
            not valid.
    """
    name = source or 'The KML'
    if re.search(r'<!(DOCTYPE|ENTITY)', text, re.IGNORECASE):
        raise BoundaryFileError(f'{name} has a DOCTYPE or entity declaration, which is refused; remove it.')
    polygons = _KmlReader().read(text, name)
    if len(polygons) != 1:
        raise BoundaryFileError(
            f'{name} holds {len(polygons)} polygons; give each its own site.'
            if polygons
            else f'{name} holds no polygon.'
        )
    if polygons[0]['outer'] is None:
        raise BoundaryFileError(f'{name} has a polygon without an outerBoundaryIs.')
    rings = [_kml_ring(coordinates, name) for coordinates in (polygons[0]['outer'], *polygons[0]['inner'])]
    return Polygon(rings[0], tuple(rings[1:]), source)


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


class _KmlReader:
    """Collects the polygons of a KML text with expat: for each, its outer and inner coordinate texts."""

    def __init__(self) -> None:
        self.stack: list[str] = []
        self.polygons: list[dict[str, Any]] = []
        self.buffer: list[str] = []

    def read(self, text: str, name: str) -> list[dict[str, Any]]:
        """Parse the text and return the polygons found, or raise BoundaryFileError if it is not XML."""
        parser = expat.ParserCreate()
        parser.StartElementHandler, parser.EndElementHandler = self.start, self.end
        parser.CharacterDataHandler = self.characters
        try:
            parser.Parse(text, True)
        except expat.ExpatError as error:
            raise BoundaryFileError(f'{name} is not valid KML: {error}.') from None
        return self.polygons

    def start(self, tag: str, _attributes: object) -> None:
        """Note an opening element; a Polygon starts a new entry and coordinates a new text."""
        local = tag.rsplit(':', 1)[-1]
        self.stack.append(local)
        if local == 'Polygon':
            self.polygons.append({'outer': None, 'inner': []})
        elif local == 'coordinates':
            self.buffer.clear()

    def end(self, tag: str) -> None:
        """Store the coordinates text of a closing element under the outer or inner boundary it is in."""
        if tag.rsplit(':', 1)[-1] == 'coordinates' and self.polygons:
            if 'outerBoundaryIs' in self.stack:
                self.polygons[-1]['outer'] = ''.join(self.buffer)
            elif 'innerBoundaryIs' in self.stack:
                self.polygons[-1]['inner'].append(''.join(self.buffer))
        self.stack.pop()

    def characters(self, data: str) -> None:
        """Collect the text inside a coordinates element."""
        if self.stack and self.stack[-1] == 'coordinates':
            self.buffer.append(data)


def _signed_area(ring: tuple[tuple[float, float], ...]) -> float:
    """Return the signed shoelace area of a ring in square degrees: positive counter-clockwise (lon east, lat north)."""
    return (
        sum(lon1 * lat2 - lon2 * lat1 for (lat1, lon1), (lat2, lon2) in zip(ring, ring[1:] + ring[:1], strict=True)) / 2
    )


def _ring_centroid(ring: tuple[tuple[float, float], ...]) -> tuple[float, float]:
    """Return the (lat, lon) area centroid of a ring."""
    area, lat_sum, lon_sum = _signed_area(ring), 0.0, 0.0
    for (lat1, lon1), (lat2, lon2) in zip(ring, ring[1:] + ring[:1], strict=True):
        cross = lon1 * lat2 - lon2 * lat1
        lat_sum, lon_sum = lat_sum + (lat1 + lat2) * cross, lon_sum + (lon1 + lon2) * cross
    return lat_sum / (6 * area), lon_sum / (6 * area)


def _oriented(ring: tuple[tuple[float, float], ...], *, counter_clockwise: bool) -> tuple[tuple[float, float], ...]:
    """Return the ring running counter-clockwise or clockwise, as asked."""
    return ring if (_signed_area(ring) > 0) == counter_clockwise else ring[::-1]


def _clean_ring(ring: Any, label: str) -> tuple[tuple[float, float], ...]:
    """Return the ring as (lat, lon) float pairs without a closing vertex, or raise BoundaryFileError saying why not."""
    try:
        vertices = [(float(lat), float(lon)) for lat, lon in ring]
    except (TypeError, ValueError):
        raise BoundaryFileError(f'{label} must be a list of (lat, lon) vertices.') from None
    if len(vertices) > 1 and vertices[0] == vertices[-1]:
        vertices.pop()
    for lat, lon in vertices:
        try:
            LatLonPoint(lat, lon)
        except ValueError as error:
            raise BoundaryFileError(
                f'{label} has a vertex out of range ({lat}, {lon}): {error}. Antimeridian boundaries are not read.'
            ) from None
    if len(vertices) > _MAX_VERTICES:
        raise BoundaryFileError(
            f'{label} has {len(vertices)} vertices; the limit is {_MAX_VERTICES}. Simplify the outline.'
        )
    if len(set(vertices)) != len(vertices):
        raise BoundaryFileError(f'{label} repeats a vertex; remove the duplicate.')
    if len(vertices) < 3:
        raise BoundaryFileError(f'{label} needs at least 3 distinct vertices.')
    return tuple(vertices)


def _check_rings(exterior: tuple[tuple[float, float], ...], holes: tuple[tuple[tuple[float, float], ...], ...]) -> None:
    """Raise BoundaryFileError if a ring crosses itself or another ring, or a hole is outside the outline."""
    rings = [exterior, *holes]
    for k, ring in enumerate(rings):
        label = 'The outline' if k == 0 else f'Hole {k}'
        if _rings_meet(ring, ring):
            raise BoundaryFileError(f'{label} crosses itself; redraw it so its edges do not cross.')
        if abs(_signed_area(ring)) < _USED:
            raise BoundaryFileError(f'{label} has no area: its vertices lie on a line.')
        for other in range(k):
            if _rings_meet(ring, rings[other]):
                raise BoundaryFileError(
                    f'{label} crosses {"the outline" if other == 0 else f"hole {other}"}; keep the holes apart.'
                )
    for k, hole in enumerate(holes, start=1):
        if not _ray_crossings(exterior, *hole[0]) % 2:
            raise BoundaryFileError(f'Hole {k} is not inside the outline.')


def _rings_meet(first: tuple[tuple[float, float], ...], second: tuple[tuple[float, float], ...]) -> bool:
    """Return True if any two non-adjacent edges of the rings touch or cross; with one ring, its own edges."""
    a = np.array(first)[:, ::-1]  # x = lon, y = lat
    b = np.array(second)[:, ::-1]
    a0, a1, b0, b1 = a, np.roll(a, -1, axis=0), b, np.roll(b, -1, axis=0)
    same, count = first is second, len(a)
    for i in range(count):
        meets = _segments_meet(a0[i], a1[i], b0, b1)
        if same:
            meets[[i, (i - 1) % count, (i + 1) % count]] = False
        if meets.any():
            return True
    return False


def _segments_meet(a0: np.ndarray, a1: np.ndarray, b0: np.ndarray, b1: np.ndarray) -> np.ndarray:
    """Return, for one segment a0-a1 against many b0-b1, whether each pair touches or crosses."""

    def side(p: np.ndarray, q: np.ndarray, r: np.ndarray) -> np.ndarray:
        return np.asarray(
            (q[..., 0] - p[..., 0]) * (r[..., 1] - p[..., 1]) - (q[..., 1] - p[..., 1]) * (r[..., 0] - p[..., 0])
        )

    d1, d2, d3, d4 = side(b0, b1, a0), side(b0, b1, a1), side(a0, a1, b0), side(a0, a1, b1)
    meet = (d1 * d2 <= 0) & (d3 * d4 <= 0)
    collinear = (d1 == 0) & (d2 == 0) & (d3 == 0) & (d4 == 0)
    overlap = np.ones(len(b0), dtype=bool)
    for axis in (0, 1):
        overlap &= (min(a0[axis], a1[axis]) <= np.maximum(b0[:, axis], b1[:, axis])) & (
            np.minimum(b0[:, axis], b1[:, axis]) <= max(a0[axis], a1[axis])
        )
    return np.asarray(np.where(collinear, overlap, meet))


def _ray_crossings(ring: tuple[tuple[float, float], ...], lat: float, lon: float) -> int:
    """Return how many edges of the ring a ray running east from the point crosses."""
    points = np.array(ring)
    lat1, lon1 = points[:, 0], points[:, 1]
    lat2, lon2 = np.roll(lat1, -1), np.roll(lon1, -1)
    straddles = (lat1 > lat) != (lat2 > lat)
    rise = np.where(lat2 == lat1, 1.0, lat2 - lat1)
    east_of_point = lon < (lon2 - lon1) * (lat - lat1) / rise + lon1
    return int(np.count_nonzero(straddles & east_of_point))


def _clip_axis(
    points: list[tuple[float, float]], axis: int, bound: float, *, keep_above: bool
) -> list[tuple[float, float]]:
    """Clip a polygon (x, y points) to one side of the line x = bound (axis 0) or y = bound (axis 1)."""
    clipped: list[tuple[float, float]] = []
    for current, previous in zip(points, points[-1:] + points[:-1], strict=True):
        current_in = current[axis] >= bound if keep_above else current[axis] <= bound
        previous_in = previous[axis] >= bound if keep_above else previous[axis] <= bound
        if current_in != previous_in:
            t = (bound - previous[axis]) / (current[axis] - previous[axis])
            clipped.append((previous[0] + t * (current[0] - previous[0]), previous[1] + t * (current[1] - previous[1])))
        if current_in:
            clipped.append(current)
    return clipped


def _clipped_area(ring: tuple[tuple[float, float], ...], window: tuple[float, float, float, float]) -> float:
    """Return the area of the ring inside the window (xmin, ymin, xmax, ymax), Sutherland-Hodgman, in square degrees."""
    points: list[tuple[float, float]] = [(lon, lat) for lat, lon in ring]
    xmin, ymin, xmax, ymax = window
    for axis, bound, keep_above in ((0, xmin, True), (0, xmax, False), (1, ymin, True), (1, ymax, False)):
        points = _clip_axis(points, axis, bound, keep_above=keep_above)
        if not points:
            return 0.0
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1], strict=True))) / 2


def _geojson_polygons(data: Any, name: str) -> list[list[Any]]:
    """Return the polygons (each a list of rings) in GeoJSON data of any of the four polygon-bearing types."""
    kind = data.get('type') if isinstance(data, dict) else None
    if kind == 'FeatureCollection':
        return [polygon for feature in data.get('features', []) for polygon in _geojson_polygons(feature, name)]
    if kind == 'Feature':
        return _geojson_polygons(data.get('geometry'), name)
    if kind == 'Polygon':
        return [data.get('coordinates', [])]
    if kind == 'MultiPolygon':
        return list(data.get('coordinates', []))
    raise BoundaryFileError(f'{name} holds {kind or "no geometry"}, not a Polygon.')


def _lonlat_ring(ring: Any, name: str) -> tuple[tuple[float, float], ...]:
    """Return a GeoJSON ring of [lon, lat, ...] positions as (lat, lon) pairs."""
    try:
        return tuple((float(position[1]), float(position[0])) for position in ring)
    except (TypeError, ValueError, IndexError):
        raise BoundaryFileError(f'{name} has a position that is not [longitude, latitude].') from None


def _kml_ring(coordinates: str, name: str) -> tuple[tuple[float, float], ...]:
    """Return the (lat, lon) pairs in a KML coordinates text of 'lon,lat[,alt]' tuples."""
    ring = []
    for token in coordinates.split():
        try:
            lon, lat = token.split(',')[:2]
            ring.append((float(lat), float(lon)))
        except ValueError:
            raise BoundaryFileError(f'{name} has a coordinate it cannot read: <{token}>.') from None
    return tuple(ring)


# endregion
