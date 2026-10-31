"""What every spike shares: the choices, the form-to-dataclasses step, node lookups and the map styling.

Only barra2_dl names in an __all__ and globals constants are used (ADR-004 rule 1). Anything here that a second
interface would also need is a finding for the engine, listed in the research note.
"""

from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

import fake_ncss

from barra2_dl.globals import (
    BARRA2_DOMAINS,
    BARRA2_FREQS,
    BARRA2_NODE_SELECTIONS,
    BARRA2_OUTPUT_FORMATS,
    BARRA2_PRESETS,
)
from barra2_dl.mapping import BoundaryFileError, LatLonPoint, nearest_nodes, polygon_from_geojson
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
        cache=SCRATCH / 'cache',
        out=SCRATCH / 'out',
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
    site = Site(name=values['name'], point=point, polygon=polygon, nodes=nodes)
    messages += [(problem.key, problem.message) for problem in validate(settings, site)]
    return settings, site, messages


def plan_text(site: Site, settings: Settings) -> str:
    """'N files, M cached'."""
    plan = plan_site(site, settings)
    cached = sum(file.cached for file in plan.files)
    return f'{len(plan.files)} files, {cached} cached'


def summary(result: Any) -> dict[str, Any]:
    """The run summary as plain data."""
    return site_result_to_dict(result)
