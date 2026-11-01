"""What every spike shares: the choices, the form-to-dataclasses step, node lookups and the map styling.

Only barra2_dl names in an __all__ and globals constants are used (ADR-004 rule 1). Anything here that a second
interface would also need is a finding for the engine, listed in the research note.
"""

from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

import fake_ncss
import numpy as np

from barra2_dl.globals import (
    BARRA2_DOMAINS,
    BARRA2_FREQS,
    BARRA2_GRID_SPACING,
    BARRA2_NODE_SELECTIONS,
    BARRA2_OUTPUT_FORMATS,
    BARRA2_PRESETS,
)
from barra2_dl.mapping import (
    BoundaryFileError,
    LatLonPoint,
    NodeLookupError,
    bracket_index,
    nearest_nodes,
    polygon_from_geojson,
)
from barra2_dl.project import Settings, Site, plan_site, site_result_to_dict, validate

FAKE = fake_ncss.install()
DOMAINS = list(BARRA2_DOMAINS)
PRESETS = list(BARRA2_PRESETS)
SELECTIONS = [name for name in BARRA2_NODE_SELECTIONS if name in ('nearest', 'average4')]
FORMATS = list(BARRA2_OUTPUT_FORMATS)
SCRATCH = Path(__file__).resolve().parents[1] / '_scratch'
DEFAULTS: dict[str, Any] = {
    'lat': fake_ncss.FIXTURE_POINT[0],
    'lon': fake_ncss.FIXTURE_POINT[1],
    'start': date(2023, 1, 1),
    'end': date(2023, 6, 30),
    'domain': 'AUS-11',
    'freq': '1hr',
    'preset': 'wind+density',
    'node_selection': 'nearest',
    'format': 'netcdf',
    'name': 'spike-site',
}
COLOURS = {'site': '#111111', 'offered': '#3b82f6', 'chosen': '#16a34a', 'used': '#f97316'}


def freqs(domain: str) -> list[str]:
    """The frequencies of a domain, from the library."""
    return list(BARRA2_FREQS[domain])


def find_nodes(lat: float, lon: float, domain: str) -> list[dict[str, Any]]:
    """The nodes around a point as plain dicts for a map: lat, lon, distance_km, orog, sftlf."""
    return [asdict(node) for node in nearest_nodes(LatLonPoint(lat, lon), domain, n=9)]


def find_polygon_nodes(polygon_geojson: str, domain: str) -> list[dict[str, Any]]:
    """The nodes whose cell the polygon overlaps, as dicts with the share (overlap) of each cell inside it.

    The engine has no such preview (a polygon run finds its nodes while it downloads), so this samples nearest_nodes on
    a lattice over the polygon's box, a lookup covering a 3 x 3 block, and keeps the nodes Polygon.cell_overlap says are
    touched. A lookup outside the data (the fake server only serves the fixture area) is skipped.
    """
    polygon = polygon_from_geojson(polygon_geojson, 'drawn')
    spacing = BARRA2_GRID_SPACING[domain]
    box = polygon.bbox()
    step = 2.5 * spacing
    found: dict[tuple[float, float], dict[str, Any]] = {}
    for lat in np.arange(box.south, box.north + step, step):
        for lon in np.arange(box.west, box.east + step, step):
            try:
                nodes = nearest_nodes(LatLonPoint(min(lat, box.north), min(lon, box.east)), domain, n=9)
            except NodeLookupError:
                continue
            found |= {(round(node.lat, 5), round(node.lon, 5)): asdict(node) for node in nodes}
    if not found:
        return []
    lats = sorted({key[0] for key in found})
    lons = sorted({key[1] for key in found})
    overlap = polygon.cell_overlap(lats, lons, spacing)
    kept = []
    for (lat, lon), node in found.items():
        share = float(overlap[lats.index(lat), lons.index(lon)])
        if share > 0:
            kept.append(node | {'overlap': share})
    return sorted(kept, key=lambda node: (node['lat'], node['lon']))


def build(
    values: dict[str, Any], chosen: list[dict[str, Any]], polygon_geojson: str | None
) -> tuple[Settings, Site, list[tuple[str, str]]]:
    """Make Settings and Site from form values, validate, and return (key, message) pairs for each problem."""
    SCRATCH.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        start=values['start'],
        end=values['end'],
        domain=values['domain'],
        freq=values['freq'],
        preset=values['preset'],
        node_selection=values['node_selection'],
        format=values['format'],
        cache=Path(values.get('cache') or SCRATCH / 'cache'),
        out=Path(values.get('out') or SCRATCH / 'out'),
    )
    messages: list[tuple[str, str]] = []
    polygon = None
    if polygon_geojson:
        try:
            polygon = polygon_from_geojson(polygon_geojson, 'drawn')
        except BoundaryFileError as error:
            messages.append(('polygon', str(error)))
    point = None if polygon else LatLonPoint(values['lat'], values['lon'])
    nodes = None if polygon else ([LatLonPoint(n['lat'], n['lon']) for n in chosen] or None)
    node_mean = bool(values.get('node_mean')) and (polygon is not None or nodes is not None)
    site = Site(name=values['name'], point=point, polygon=polygon, nodes=nodes, node_mean=node_mean)
    messages += [(problem.key, problem.message) for problem in validate(settings, site)]
    return settings, site, messages


def planned_nodes(
    lat: float, lon: float, offered: list[dict[str, Any]], chosen: list[dict[str, Any]], selection: str, area: bool
) -> list[dict[str, Any]]:
    """The offered nodes a run would download: all of an area's, the chosen ones, else the nearest or the four around.

    The four are the pair of neighbouring nodes on each axis that surround the point (mapping.bracket_index, as the
    engine's average4 merge finds them); where the offered block is too small to hold them, the four nearest stand in.
    """
    if area:
        return offered
    if chosen:
        return chosen
    if not offered or selection == 'nearest':
        return offered[:1]
    lats = np.array(sorted({node['lat'] for node in offered}))
    lons = np.array(sorted({node['lon'] for node in offered}))
    try:
        south, west = bracket_index(lats, lat), bracket_index(lons, lon)
    except ValueError:
        return offered[:4]
    rows, columns = {lats[south], lats[south + 1]}, {lons[west], lons[west + 1]}
    around = [node for node in offered if node['lat'] in rows and node['lon'] in columns]
    return around if len(around) == 4 else offered[:4]


def plan_text(site: Site, settings: Settings) -> str:
    """'N files, M cached'."""
    plan = plan_site(site, settings)
    cached = sum(file.cached for file in plan.files)
    return f'{len(plan.files)} files, {cached} cached'


def summary(result: Any) -> dict[str, Any]:
    """The run summary as plain data."""
    return site_result_to_dict(result)
