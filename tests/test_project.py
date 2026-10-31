"""This module contains the barra2.project test function(s)."""

import json
import os
import threading
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
import requests
import xarray as xr

import barra2_dl.project
from barra2_dl.download import FileResult
from barra2_dl.globals import BARRA2_GRID_SPACING
from barra2_dl.mapping import LatLonBBox, LatLonPoint, Polygon, nearest_nodes, read_polygon
from barra2_dl.merge import read_csv
from barra2_dl.project import (
    Problem,
    ProjectError,
    Settings,
    Site,
    load_project,
    plan_site,
    project_from_dict,
    run_site,
    site_from_dict,
    site_result_to_dict,
    validate,
)

# region Test helpers
# Tests that hit the real THREDDS server are opt-in: set BARRA2_LIVE=1 to run them.
live_network = pytest.mark.skipif(not os.environ.get('BARRA2_LIVE'), reason='live network test; set BARRA2_LIVE=1')

DATA = Path(__file__).parent / 'data'  # small point and grid files built by scripts/build_test_fixtures.py
FIXTURE_VARS = ['ua50m', 'va50m', 'tas']
VERSIONS = {'ua50m': 'v20240516', 'va50m': 'v20240516', 'tas': 'v20231001', 'orog': 'v20231001'}
POINT = LatLonPoint(-23.55, 133.40)  # the location the fixtures were requested for
BOX = LatLonBBox(north=-23.4, south=-23.7, east=133.5, west=133.2)  # inside the grid fixtures' bounds


class _Response:
    """Minimal stand-in for requests.Response."""

    def __init__(self, status_code: int, content: bytes) -> None:
        self.status_code = status_code
        self.content = content


class _Server:
    """A fake NCSS: serves the tests/data fixture for each request, and records the urls asked for."""

    def __init__(self) -> None:
        self.requested: list[str] = []
        self.fail: tuple[str, ...] = ()  # a request whose url contains any of these gets a 404
        self.cancel: threading.Event | None = None

    def get(self, url: str, **_kwargs: object) -> _Response:
        """Return the fixture for the url's variable, in the format and shape (point or grid) it asks for."""
        self.requested.append(url)
        if any(text in url for text in self.fail):
            return _Response(404, b'missing')
        query = {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}
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


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> _Server:
    """Replace requests.get with the fake server, retries without waiting, and the variables with the fixtures'."""
    fake = _Server()
    monkeypatch.setattr(requests, 'get', fake.get)
    monkeypatch.setattr(barra2_dl.download.time, 'sleep', lambda _seconds: None)
    real_preset_variables = barra2_dl.project.preset_variables

    def fixture_variables(preset: str, domain: str = 'AUS-11', freq: str = '1hr') -> list[str]:
        real_preset_variables(preset, domain, freq)  # still rejects a preset the domain and freq don't have
        return FIXTURE_VARS

    monkeypatch.setattr(barra2_dl.project, 'preset_variables', fixture_variables)
    monkeypatch.setattr(barra2_dl.project, 'resolve_variable_versions', lambda *_args: VERSIONS)
    return fake


def _settings(tmp_path: Path, **changes: Any) -> Settings:
    """Settings for one month, with the cache and output folders under tmp_path."""
    return replace(
        Settings(start=date(2023, 1, 1), end=date(2023, 1, 31), cache=tmp_path / 'cache', out=tmp_path / 'out'),
        **changes,
    )


def _problems(error: ProjectError) -> set[tuple[str | None, str]]:
    """The (site, key) of each problem in the error."""
    return {(problem.site, problem.key) for problem in error.problems}


VALID_PROJECT = {
    'settings': {'start': '2023-01-01', 'end': date(2023, 1, 31), 'format': 'netcdf', 'cache': 'c', 'workers': 2},
    'site': [
        {'name': 'mast-north', 'lat': -33.87, 'lon': 151.21},
        {'name': 'mast-south', 'lat': -34.1, 'lon': 150.95, 'node_selection': 'average4', 'end': '2023-01-15'},
        {'name': 'farm-area', 'north': -33.7, 'south': -34.0, 'east': 151.3, 'west': 151.0},
    ],
}
# the grid fixtures hold the nodes at lat -23.65, -23.54, -23.43 and lon 133.25, 133.36, 133.47
NODES = [LatLonPoint(-23.54, 133.36), LatLonPoint(-23.43, 133.47)]

TWO_CELLS = read_polygon(DATA / 'boundary_two_cells.geojson')  # equal parts of the cells of two grid nodes
SUB_CELL = read_polygon(DATA / 'boundary_sub_cell.geojson')  # lies in one cell and straddles a second
# endregion


# region Errors
# region ProjectError
def test_project_error_lists_every_problem_with_its_site_and_key() -> None:
    """The message has a line for each problem, and problems holds them as data."""
    problems = [Problem('mast', 'freq', 'change it'), Problem(None, 'workers', 'Use at least 1.')]

    error = ProjectError(problems)

    assert error.problems == problems
    assert 'site <mast>, freq: change it' in str(error)
    assert 'settings, workers: Use at least 1.' in str(error)
    assert isinstance(error, ValueError)


# endregion
# endregion


# region Public API
# region load_project
def test_load_project_reads_settings_and_sites(tmp_path: Path) -> None:
    """A valid file gives typed settings and sites, with folders relative to the file."""
    path = tmp_path / 'project.toml'
    path.write_text(
        '[settings]\nstart = 2023-01-01\nend = "2023-01-31"\nfreq = "1hr"\ncache = "cache"\nout = "output"\n'
        '[[site]]\nname = "mast"\nlat = -33.87\nlon = 151.21\n'
        '[[site]]\nname = "farm"\nnorth = -33.7\nsouth = -34.0\neast = 151.3\nwest = 151.0\nformat = "netcdf"\n'
    )

    project = load_project(path)

    assert project.path == path
    assert project.settings == Settings(
        start=date(2023, 1, 1), end=date(2023, 1, 31), cache=tmp_path / 'cache', out=tmp_path / 'output'
    )
    assert [site.name for site in project.sites] == ['mast', 'farm']
    assert project.sites[0].point == LatLonPoint(-33.87, 151.21)
    assert project.sites[1].bbox == LatLonBBox(-33.7, -34.0, 151.3, 151.0)
    assert project.sites[1].overrides == {'format': 'netcdf'}


def test_load_project_invalid_toml_is_a_project_error(tmp_path: Path) -> None:
    """A file that isn't TOML is reported like any other problem."""
    path = tmp_path / 'project.toml'
    path.write_text('[settings\n')

    with pytest.raises(ProjectError) as error:
        load_project(path)

    assert _problems(error.value) == {(None, 'file')}


def test_load_project_missing_file(tmp_path: Path) -> None:
    """A missing file raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        load_project(tmp_path / 'missing.toml')


# endregion


# region project_from_dict
def test_project_from_dict_round_trips_a_valid_project(tmp_path: Path) -> None:
    """Dates may be ISO strings or dates, overrides are kept, and relative folders resolve against base_dir."""
    project = project_from_dict(VALID_PROJECT, tmp_path)

    assert project.settings.start == date(2023, 1, 1)
    assert project.settings.end == date(2023, 1, 31)
    assert (project.settings.cache, project.settings.out) == (tmp_path / 'c', tmp_path / 'output')
    assert project.settings.workers == 2
    assert project.sites[1].overrides == {'node_selection': 'average4', 'end': date(2023, 1, 15)}
    assert project.sites[2].bbox is not None


def test_project_from_dict_reports_every_problem_at_once() -> None:
    """Each fault is listed with its site and key in one error."""
    data = {
        'extra': {},
        'settings': {'start': 'tomorrow', 'domian': 'AUS-11', 'workers': 0, 'cache': 3},
        'site': [
            {'name': 'a', 'lat': -33.0, 'lon': 151.0, 'north': -33.0, 'south': -34.0, 'east': 152.0, 'west': 151.0},
            {'name': 'a', 'lat': 95.0, 'lon': 151.0},
            {'name': 'bad name', 'lat': -33.0},
            {'name': 'c', 'lat': -33.0, 'lon': 151.0, 'colour': 'red', 'freq': 3},
            {'lat': -33.0, 'lon': 151.0},
            {'name': 'd', 'north': -34.0, 'south': -33.0, 'east': 152.0, 'west': 151.0},
        ],
    }

    with pytest.raises(ProjectError) as error:
        project_from_dict(data, '.')

    assert _problems(error.value) >= {
        (None, 'extra'),
        (None, 'start'),
        (None, 'end'),
        (None, 'domian'),
        (None, 'workers'),
        (None, 'cache'),
        ('a', 'lat/lon'),
        ('a', 'name'),
        ('bad name', 'lat/lon'),
        ('bad name', 'name'),
        ('c', 'colour'),
        ('c', 'freq'),
        (None, 'name'),
        ('d', 'north/south/east/west'),
    }


@pytest.mark.parametrize(
    ('settings', 'site', 'expected'),
    [
        ({'workers': 'many'}, {}, (None, 'workers')),
        ({'workers': True}, {}, (None, 'workers')),
        ({'start': 5}, {}, (None, 'start')),
        ({'start': '31/01/2023'}, {}, (None, 'start')),
        ({}, {'lat': 'north'}, ('a', 'lat/lon')),
        ({}, {'lat': True}, ('a', 'lat/lon')),
        ({}, {'end': 7}, ('a', 'end')),
        ({}, {'freq': 3}, ('a', 'freq')),
    ],
)
def test_project_from_dict_rejects_values_of_the_wrong_type(
    settings: dict, site: dict, expected: tuple[str | None, str], tmp_path: Path
) -> None:
    """A value of the wrong type or format is reported with its site and key."""
    data = {
        'settings': {'start': '2023-01-01', 'end': '2023-01-31'} | settings,
        'site': [{'name': 'a', 'lat': -23.55, 'lon': 133.4} | site],
    }

    with pytest.raises(ProjectError) as error:
        project_from_dict(data, tmp_path)

    assert expected in _problems(error.value)


def test_project_from_dict_takes_a_toml_datetime_as_its_date(tmp_path: Path) -> None:
    """A TOML offset date-time, which parses to a datetime, is taken as its date."""
    stamp = datetime(2023, 1, 1, 12, 0, tzinfo=UTC)
    data = {'settings': {'start': stamp, 'end': '2023-01-31'}, 'site': [{'name': 'a', 'lat': -23.55, 'lon': 133.4}]}

    assert project_from_dict(data, tmp_path).settings.start == date(2023, 1, 1)


def test_project_from_dict_needs_a_site() -> None:
    """A project without sites is an error."""
    with pytest.raises(ProjectError) as error:
        project_from_dict({'settings': {'start': '2023-01-01', 'end': '2023-01-31'}}, '.')

    assert _problems(error.value) == {(None, 'site')}


def test_project_from_dict_settings_must_be_a_table() -> None:
    """A settings value that isn't a table is reported."""
    with pytest.raises(ProjectError) as error:
        project_from_dict({'settings': 3, 'site': [{'name': 'a', 'lat': 1, 'lon': 1}, 5]}, '.')

    assert {(None, 'settings'), (None, 'site')} <= _problems(error.value)


@pytest.mark.parametrize(
    ('settings', 'site', 'expected'),
    [
        ({'domain': 'AUS-11', 'freq': '20min'}, {}, 'freq'),
        ({'domain': 'MERRA', 'freq': '1hr'}, {}, 'domain'),
        ({'domain': 'AUST-04', 'freq': '20min', 'preset': 'wind+density'}, {}, 'preset'),
        ({'preset': 'nonsense'}, {}, 'preset'),
        ({'node_selection': 'area'}, {}, 'node_selection'),
        ({'node_selection': 'nearest'}, {'node_selection': 'sideways'}, 'node_selection'),
        ({'format': 'xlsx'}, {}, 'format'),
        ({'download': 'grib'}, {}, 'download'),
        ({'start': '2023-02-01'}, {}, 'start'),
        ({'workers': 0}, {}, 'workers'),
        ({'download': 'csv', 'node_selection': 'average4'}, {}, 'download'),
        ({'download': 'csv', 'format': 'netcdf'}, {}, 'download'),
    ],
)
def test_project_from_dict_rejects_invalid_combinations(
    settings: dict, site: dict, expected: str, tmp_path: Path
) -> None:
    """A combination that cannot run is reported with the key to change, before any request."""
    data = {
        'settings': {'start': '2023-01-01', 'end': '2023-01-31'} | settings,
        'site': [{'name': 'a', 'lat': -23.55, 'lon': 133.4} | site],
    }

    with pytest.raises(ProjectError) as error:
        project_from_dict(data, tmp_path)

    assert expected in {key for _, key in _problems(error.value)}


@pytest.mark.parametrize(
    ('site', 'expected'),
    [
        ({'format': 'csv'}, 'format'),
        ({'node_selection': 'nearest', 'format': 'netcdf'}, 'node_selection'),
        ({'download': 'csv', 'format': 'netcdf'}, 'download'),
    ],
)
def test_project_from_dict_box_site_rules(site: dict, expected: str, tmp_path: Path) -> None:
    """A box is an area: it can't be csv, name another selection, or take the csv download."""
    box = {'north': -23.4, 'south': -23.7, 'east': 133.5, 'west': 133.2}
    data = {'settings': {'start': '2023-01-01', 'end': '2023-01-31'}, 'site': [{'name': 'a'} | box | site]}

    with pytest.raises(ProjectError) as error:
        project_from_dict(data, tmp_path)

    assert ('a', expected) in _problems(error.value)


# endregion


# region site_from_dict
def test_site_from_dict_builds_a_site(tmp_path: Path) -> None:
    """A form's data becomes a site, checked against the settings."""
    site = site_from_dict(
        {'name': 'mast', 'lat': -23.55, 'lon': 133.4, 'node_selection': 'average4'}, _settings(tmp_path)
    )

    assert site == Site('mast', LatLonPoint(-23.55, 133.4), None, {'node_selection': 'average4'})


def test_site_from_dict_rejects_an_invalid_site(tmp_path: Path) -> None:
    """Structural and semantic problems are both raised."""
    with pytest.raises(ProjectError) as error:
        site_from_dict({'name': 'mast', 'lat': -23.55, 'lon': 133.4, 'freq': '20min'}, _settings(tmp_path))

    assert _problems(error.value) == {('mast', 'freq')}


# region nodes
def test_site_from_dict_builds_a_site_with_nodes(tmp_path: Path) -> None:
    """Nodes is a list of [lat, lon] pairs in the order given, node_mean a bool."""
    site = site_from_dict(
        {'name': 'mast', 'lat': -23.55, 'lon': 133.4, 'nodes': [[-23.54, 133.36], [-23.43, 133.47]], 'node_mean': True},
        _settings(tmp_path),
    )

    assert site == Site('mast', POINT, None, {}, NODES, True)


@pytest.mark.parametrize(
    'nodes', ['x', [[-23.54]], [[-23.54, 'a']], [[True, 1]], [[91.0, 133.0]], [-23.54, 133.36]], ids=str
)
def test_site_from_dict_rejects_nodes_that_are_not_lat_lon_pairs(tmp_path: Path, nodes: object) -> None:
    """Each node must be two numbers in range."""
    with pytest.raises(ProjectError) as error:
        site_from_dict({'name': 'mast', 'lat': -23.55, 'lon': 133.4, 'nodes': nodes}, _settings(tmp_path))

    assert _problems(error.value) == {('mast', 'nodes')}
    assert 'copied from nearest_nodes' in str(error.value)


def test_site_from_dict_rejects_a_node_mean_that_is_not_true_or_false(tmp_path: Path) -> None:
    """node_mean is a bool."""
    with pytest.raises(ProjectError) as error:
        site_from_dict(
            {'name': 'mast', 'lat': -23.55, 'lon': 133.4, 'nodes': [[-23.54, 133.36]], 'node_mean': 'yes'},
            _settings(tmp_path),
        )

    assert _problems(error.value) == {('mast', 'node_mean')}


def test_project_from_dict_reads_nodes_from_a_project_file(tmp_path: Path) -> None:
    """A TOML site with nodes and node_mean loads, and the unknown-key list names them."""
    file = tmp_path / 'project.toml'
    file.write_text(
        '[settings]\nstart = "2023-01-01"\nend = "2023-01-31"\n'
        '[[site]]\nname = "mast"\nlat = -23.55\nlon = 133.4\nnodes = [[-23.54, 133.36], [-23.43, 133.47]]\n'
        'node_mean = true\n',
        encoding='utf-8',
    )

    (site,) = load_project(file).sites

    assert site.nodes == NODES
    assert site.node_mean is True
    with pytest.raises(ProjectError, match='nodes, node_mean'):
        project_from_dict(
            {'settings': {'start': '2023-01-01', 'end': '2023-01-31'}, 'site': [{'name': 'a', 'colour': 1}]}
        )


# endregion


# region polygon
def test_site_from_dict_reads_a_boundary_file_relative_to_the_base_folder(tmp_path: Path) -> None:
    """A polygon given as a path is read, relative to base_dir, and kept on the site."""
    (tmp_path / 'farm.geojson').write_text((DATA / 'boundary_two_cells.geojson').read_text(), encoding='utf-8')

    site = site_from_dict(
        {'name': 'farm', 'polygon': 'farm.geojson', 'node_mean': True, 'format': 'netcdf'},
        _settings(tmp_path, format='netcdf'),
        base_dir=tmp_path,
    )

    assert site.polygon is not None
    assert site.polygon.exterior == TWO_CELLS.exterior
    assert site.polygon.source == 'farm.geojson'
    assert site.node_mean is True


def test_site_from_dict_takes_a_polygon_object_from_a_form(tmp_path: Path) -> None:
    """A drawn boundary is a Polygon already."""
    site = site_from_dict({'name': 'farm', 'polygon': TWO_CELLS}, _settings(tmp_path, format='netcdf'))

    assert site.polygon is TWO_CELLS


@pytest.mark.parametrize(
    ('polygon', 'text'),
    [
        ('missing.geojson', 'Cannot read missing.geojson'),
        ('bad.geojson', 'Cannot read bad.geojson: bad.geojson is not valid JSON'),
        (3, 'path of a GeoJSON or KML file'),
    ],
    ids=['missing', 'bad-json', 'not-text'],
)
def test_site_from_dict_reports_a_boundary_that_cannot_be_read(tmp_path: Path, polygon: Any, text: str) -> None:
    """A missing file, a file that is not a boundary and a value that is not a path each get a message under polygon."""
    (tmp_path / 'bad.geojson').write_text('{nope', encoding='utf-8')

    with pytest.raises(ProjectError) as error:
        site_from_dict({'name': 'farm', 'polygon': polygon}, _settings(tmp_path, format='netcdf'), base_dir=tmp_path)

    assert ('farm', 'polygon') in _problems(error.value)
    assert text in str(error.value)


def test_load_project_reads_the_polygon_key_relative_to_the_project_file(tmp_path: Path) -> None:
    """In a project file the boundary path is relative to the file, like cache and out."""
    (tmp_path / 'farm.kml').write_text((DATA / 'boundary_two_cells.kml').read_text(), encoding='utf-8')
    file = tmp_path / 'project.toml'
    file.write_text(
        '[settings]\nstart = "2023-01-01"\nend = "2023-01-31"\nformat = "netcdf"\n'
        '[[site]]\nname = "farm"\npolygon = "farm.kml"\nnode_mean = true\n',
        encoding='utf-8',
    )

    (site,) = load_project(file).sites

    assert site.polygon is not None
    assert site.polygon.exterior == TWO_CELLS.exterior


# endregion


# endregion


# region validate
def test_validate_returns_nothing_for_a_valid_site(tmp_path: Path) -> None:
    """A valid site has no problems."""
    assert validate(_settings(tmp_path), Site('mast', POINT)) == []


def test_validate_returns_a_problem_per_fault_for_a_form_built_site(tmp_path: Path) -> None:
    """A site built without a file is checked the same way, one Problem per fault with its site and key."""
    site = Site('bad name!', None, LatLonBBox(north=-34.0, south=-33.0, east=152.0, west=151.0), {'colour': 'red'})

    problems = validate(_settings(tmp_path), site)

    assert {(problem.site, problem.key) for problem in problems} == {
        ('bad name!', 'name'),
        ('bad name!', 'colour'),
        ('bad name!', 'north/south/east/west'),
        ('bad name!', 'format'),
    }
    assert all(isinstance(problem, Problem) and problem.message for problem in problems)


def test_validate_needs_exactly_one_of_point_and_box(tmp_path: Path) -> None:
    """Neither, or both, is a problem."""
    neither = validate(_settings(tmp_path), Site('a'))
    both = validate(_settings(tmp_path, format='netcdf'), Site('a', POINT, BOX))

    assert [problem.key for problem in neither] == ['lat/lon']
    assert [problem.key for problem in both] == ['lat/lon']


# region nodes
def _nodes_site(**changes: Any) -> Site:
    """A point site with the two chosen nodes."""
    return replace(Site('mast', POINT, nodes=list(NODES)), **changes)


def test_validate_accepts_a_nodes_site(tmp_path: Path) -> None:
    """A point with nodes within reach, with or without the mean, has no problems."""
    assert validate(_settings(tmp_path), _nodes_site()) == []
    assert validate(_settings(tmp_path, format='netcdf'), _nodes_site(node_mean=True)) == []


@pytest.mark.parametrize(
    ('site', 'key', 'text'),
    [
        (_nodes_site(nodes=[]), 'nodes', 'Give 1 to 9 nodes'),
        (
            _nodes_site(nodes=[LatLonPoint(-23.54 + 0.001 * k, 133.36) for k in range(10)]),
            'nodes',
            'Give 1 to 9 nodes',
        ),
        (_nodes_site(nodes=[NODES[0], NODES[1], NODES[0]]), 'nodes', 'Node 3 repeats node 1.'),
        (_nodes_site(nodes=[LatLonPoint(-23.30, 133.40)]), 'nodes', 'Node 1 is too far from the site'),
        (_nodes_site(nodes=[LatLonPoint(-23.55, 133.60)]), 'nodes', 'more than 1.5 grid spacings'),
        (_nodes_site(point=None), 'lat/lon', 'A site with nodes also needs lat and lon'),
        (_nodes_site(overrides={'node_selection': 'nearest'}), 'node_selection', 'remove node_selection'),
        (_nodes_site(overrides={'node_selection': 'nodes'}), 'node_selection', 'a site with nodes is a nodes download'),
        (_nodes_site(overrides={'node_selection': 'area'}), 'node_selection', 'a site with nodes is a nodes download'),
        (_nodes_site(overrides={'download': 'csv'}), 'download', 'csv download'),
        (Site('mast', POINT, node_mean=True), 'node_mean', 'applies to a site with nodes'),
        (Site('mast', POINT, overrides={'node_selection': 'nodes'}), 'node_selection', 'nodes download, automatically'),
    ],
    ids=str,
)
def test_validate_reports_each_nodes_fault_with_what_to_change(tmp_path: Path, site: Site, key: str, text: str) -> None:
    """One message per fault, keyed by the field, saying what to change."""
    problems = validate(_settings(tmp_path), site)

    assert any(problem.key == key and text in problem.message for problem in problems), problems


def test_validate_nodes_reach_is_measured_in_the_effective_domains_spacing(tmp_path: Path) -> None:
    """A node 0.1 degrees away is within reach on AUS-11 (0.11) but not on AUST-04 (0.04)."""
    site = _nodes_site(nodes=[LatLonPoint(-23.55, 133.50)])

    assert validate(_settings(tmp_path), site) == []
    assert [
        problem.key for problem in validate(_settings(tmp_path), replace(site, overrides={'domain': 'AUST-04'}))
    ] == ['nodes']


def test_validate_a_box_site_cannot_have_nodes(tmp_path: Path) -> None:
    """Nodes belong to a point site."""
    problems = validate(_settings(tmp_path, format='netcdf'), Site('a', None, BOX, nodes=list(NODES)))

    assert [problem.message for problem in problems if problem.key == 'nodes'] == [
        'Nodes belong to a point site; remove nodes, or use lat and lon.'
    ]


# endregion


# region polygon
def _polygon_site(**changes: Any) -> Site:
    """A boundary site."""
    return replace(Site('farm', polygon=TWO_CELLS), **changes)


def test_validate_accepts_a_polygon_site_with_netcdf_output(tmp_path: Path) -> None:
    """A boundary with netCDF output, with or without the mean, has no problems."""
    assert validate(_settings(tmp_path, format='netcdf'), _polygon_site()) == []
    assert validate(_settings(tmp_path, format='netcdf'), _polygon_site(node_mean=True)) == []


@pytest.mark.parametrize(
    ('site', 'settings', 'key', 'text'),
    [
        (
            _polygon_site(point=POINT),
            {'format': 'netcdf'},
            'lat/lon',
            'Give one place: lat and lon, a box, or a polygon.',
        ),
        (_polygon_site(bbox=BOX), {'format': 'netcdf'}, 'lat/lon', 'Give one place'),
        (Site('farm'), {}, 'lat/lon', 'Give one place'),
        (
            _polygon_site(nodes=list(NODES)),
            {'format': 'netcdf'},
            'polygon',
            'Nodes belong to a point site; remove nodes, or remove polygon.',
        ),
        (
            _polygon_site(overrides={'node_selection': 'nearest'}),
            {'format': 'netcdf'},
            'node_selection',
            'A polygon site is an area download',
        ),
        (_polygon_site(), {'format': 'csv'}, 'format', 'A boundary is a grid and cannot be written as csv'),
        (_polygon_site(overrides={'download': 'csv'}), {'format': 'csv'}, 'download', 'csv download'),
        (Site('mast', POINT, node_mean=True), {}, 'node_mean', 'applies to a site with nodes or a polygon'),
    ],
    ids=str,
)
def test_validate_reports_each_polygon_fault_with_what_to_change(
    tmp_path: Path, site: Site, settings: dict[str, Any], key: str, text: str
) -> None:
    """One message per fault, keyed by the field, saying what to change."""
    problems = validate(_settings(tmp_path, **settings), site)

    assert any(problem.key == key and text in problem.message for problem in problems), problems
    assert not any('An area is a grid' in problem.message for problem in problems if site.polygon is not None)


def test_validate_a_polygon_site_with_an_unknown_domain_reports_the_domain_only(tmp_path: Path) -> None:
    """The size guard needs the domain's spacing, so with an unknown domain only the domain is reported."""
    problems = validate(_settings(tmp_path, format='netcdf'), _polygon_site(overrides={'domain': 'XX-99'}))

    assert [problem.key for problem in problems] == ['domain']


def test_validate_refuses_a_boundary_that_covers_too_many_nodes(tmp_path: Path) -> None:
    """A continent-sized outline is an error with the node count, not tens of thousands of requests."""
    huge = Polygon(((-40, 110), (-40, 150), (-10, 150), (-10, 110)))

    problems = validate(_settings(tmp_path, format='netcdf'), Site('farm', polygon=huge))

    assert [problem.key for problem in problems] == ['polygon']
    assert 'covers about 99,372 grid nodes; the limit is 2,500' in problems[0].message
    # the same outline is far more nodes on AUST-04, and a farm-sized one is fine on both
    assert validate(_settings(tmp_path, format='netcdf', domain='AUST-04'), _polygon_site()) == []


# endregion


# endregion


# region plan_site
def test_plan_site_lists_the_files_and_which_are_cached(server: _Server, tmp_path: Path) -> None:
    """The plan names each file a run would fetch, marks cached ones, and makes no request."""
    settings = _settings(tmp_path)
    settings.cache.mkdir()
    (settings.cache / 'mast_AUS-11_1hr_tas_20230101_20230131.nc').write_bytes(
        (DATA / 'fixture_AUS-11_1hr_tas_20230101_20230103.nc').read_bytes()
    )

    plan = plan_site(Site('mast', POINT), settings)

    assert plan.site == 'mast'
    assert [(file.filename, file.cached) for file in plan.files] == [
        ('mast_AUS-11_1hr_ua50m_20230101_20230131.nc', False),
        ('mast_AUS-11_1hr_va50m_20230101_20230131.nc', False),
        ('mast_AUS-11_1hr_tas_20230101_20230131.nc', True),
        ('mast_AUS-11_fx_orog.nc', False),
    ]
    assert all(file.url.startswith('https://') and file.problem is None for file in plan.files)
    assert server.requested == []


def test_plan_site_shows_a_cached_file_for_another_location(server: _Server, tmp_path: Path) -> None:
    """A moved site that kept its name shows the mismatch in the plan, as the download would refuse it."""
    settings = _settings(tmp_path)
    settings.cache.mkdir()
    (settings.cache / 'mast_AUS-11_1hr_tas_20230101_20230131.nc').write_bytes(
        (DATA / 'fixture_AUS-11_1hr_tas_20230101_20230103.nc').read_bytes()
    )

    plan = plan_site(Site('mast', LatLonPoint(-23.65, 133.4)), settings)

    (cached,) = (file for file in plan.files if file.problem)
    assert cached.filename == 'mast_AUS-11_1hr_tas_20230101_20230131.nc'
    assert not cached.cached
    assert 'requested -23.650, 133.400' in str(cached.problem)


def test_plan_site_rejects_an_invalid_site(tmp_path: Path) -> None:
    """An invalid site raises before anything is planned."""
    with pytest.raises(ProjectError):
        plan_site(Site('mast'), _settings(tmp_path))


# region nodes
def test_plan_site_nodes_lists_the_box_files_with_the_box_in_the_names(server: _Server, tmp_path: Path) -> None:
    """A nodes plan names the grid files for the chosen nodes' box, none cached, with no request."""
    plan = plan_site(Site('mast', POINT, nodes=list(NODES)), _settings(tmp_path))

    assert plan.files[0].filename == (
        'mast_AUS-11_1hr_nodes_n-23.4025_s-23.5675_e133.4975_w133.3325_ua50m_20230101_20230131.nc'
    )
    assert all('_nodes_n-23.4025' in file.filename for file in plan.files)
    assert not any(file.cached for file in plan.files)
    assert server.requested == []


# endregion


# region polygon
def test_plan_site_polygon_lists_the_area_files_of_the_widened_bounding_box(server: _Server, tmp_path: Path) -> None:
    """The files are those of an area download for the polygon's bounding box widened by 1% of the spacing."""
    plan = plan_site(_polygon_site(), _settings(tmp_path, format='netcdf'))

    assert '_area_n-23.5089_s-23.5711_e133.501_w133.329_' in plan.files[0].filename
    assert not any(file.cached for file in plan.files)
    assert server.requested == []


# endregion


# endregion


# region run_site
def test_run_site_nearest_csv_writes_output_with_header_and_summary(server: _Server, tmp_path: Path) -> None:
    """The default run downloads netCDF4, writes csv under the metadata header, and writes the run summary."""
    settings = _settings(tmp_path)

    result = run_site(Site('mast', POINT), settings)

    assert result.status == 'ok'
    assert result.error is None
    assert [path.name for path in result.outputs] == ['mast_AUS-11_1hr_nearest_20230101_20230103.csv']
    frame, header = read_csv(result.outputs[0])
    assert header['Node selection'] == 'nearest'
    assert header['Dataset versions'] == 'v20231001, v20240516'
    assert float(header['Elevation']) == pytest.approx(747.6107, abs=1e-3)
    assert 'ua50m[unit="m s-1"]' in frame.columns
    assert [file.status for file in result.files] == ['downloaded'] * 4
    assert all('accept=netcdf4' in url for url in server.requested)
    assert result.summary_path == settings.out / 'mast_run_summary.json'
    assert json.loads(result.summary_path.read_text()) == json.loads(json.dumps(site_result_to_dict(result)))


def test_run_site_netcdf_output(server: _Server, tmp_path: Path) -> None:
    """With format netcdf, the Dataset is written as <name>_<domain>_<freq>_<selection>_<start>_<end>.nc."""
    result = run_site(Site('mast', POINT), _settings(tmp_path, format='netcdf'))

    assert [path.name for path in result.outputs] == ['mast_AUS-11_1hr_nearest_20230101_20230131.nc']
    with xr.open_dataset(result.outputs[0]) as ds:
        assert ds.attrs['node_selection'] == 'nearest'
        assert float(ds.attrs['orog']) == pytest.approx(747.6107, abs=1e-3)


def test_run_site_average4_csv_writes_the_average_and_each_node(server: _Server, tmp_path: Path) -> None:
    """The four-node average gives the average and four node files, and the four nodes in the summary."""
    result = run_site(Site('mast', POINT, overrides={'node_selection': 'average4'}), _settings(tmp_path))

    assert result.status == 'ok'
    assert [path.name.split('_')[3] for path in result.outputs] == ['average4', 'node1', 'node2', 'node3', 'node4']
    assert len(result.nodes) == 4
    assert {'requested_lat', 'lat', 'distance_km', 'weight', 'orog'} <= set(result.nodes[0])
    assert all('north=' in url for url in server.requested)


def test_run_site_area_netcdf(server: _Server, tmp_path: Path) -> None:
    """A box site is an area download written as netCDF, with the node count and orog range in the summary."""
    result = run_site(Site('farm', bbox=BOX), _settings(tmp_path, format='netcdf'))

    assert result.status == 'ok'
    assert [path.name for path in result.outputs] == ['farm_AUS-11_1hr_area_20230101_20230131.nc']
    assert result.nodes[0]['count'] == 9
    assert result.nodes[0]['orog_min'] <= result.nodes[0]['orog_max']
    assert result.inputs['selection'] == 'area'


def test_run_site_csv_download_takes_the_csv_route(server: _Server, tmp_path: Path) -> None:
    """Download = csv fetches csv files and writes csv with the same header, named like the other route."""
    settings = _settings(tmp_path)

    result = run_site(Site('mast', POINT, overrides={'download': 'csv'}), settings)

    assert result.status == 'ok'
    assert all('accept=csv_file' in url for url in server.requested)
    assert sorted(path.suffix for path in settings.cache.iterdir()) == ['.csv'] * 4
    assert [path.name for path in result.outputs] == ['mast_AUS-11_1hr_nearest_20230101_20230131.csv']
    frame, header = read_csv(result.outputs[0])
    assert header['Node selection'] == 'nearest'
    assert float(header['Elevation']) == pytest.approx(747.6107, abs=1e-3)
    assert 'v50m[unit="m s-1"]' in frame.columns


def test_run_site_resumes_from_the_cache(server: _Server, tmp_path: Path) -> None:
    """A second run skips every file and makes no request."""
    settings = _settings(tmp_path)
    run_site(Site('mast', POINT), settings)
    requests_made = len(server.requested)

    result = run_site(Site('mast', POINT), settings)

    assert [file.status for file in result.files] == ['skipped'] * 4
    assert len(server.requested) == requests_made
    assert result.status == 'ok'


def test_run_site_missing_month_is_a_partial_result(server: _Server, tmp_path: Path) -> None:
    """A file that fails still lets the site merge what there is; the gap is listed in missing."""
    server.fail = ('var=tas',)

    result = run_site(Site('mast', POINT), _settings(tmp_path))

    assert result.status == 'partial'
    assert result.missing == ['tas 2023-01']
    assert result.outputs
    assert [file.status for file in result.files] == ['downloaded', 'downloaded', 'failed', 'downloaded']
    assert json.loads(result.summary_path.read_text())['missing'] == ['tas 2023-01']


def test_run_site_no_data_is_a_failed_result_not_an_exception(server: _Server, tmp_path: Path) -> None:
    """When nothing downloads the site fails with a message, writes only its summary, and does not raise."""
    server.fail = ('thredds',)

    result = run_site(Site('mast', POINT), _settings(tmp_path))

    assert result.status == 'failed'
    assert result.outputs == []
    assert 'No data files' in str(result.error)
    assert sorted(result.missing) == ['orog', 'tas 2023-01', 'ua50m 2023-01', 'va50m 2023-01']
    assert [path.name for path in result.summary_path.parent.iterdir()] == ['mast_run_summary.json']


def test_run_site_cache_mismatch_fails_the_site_before_any_request(server: _Server, tmp_path: Path) -> None:
    """A moved site that kept its name fails with the mismatch listed, and nothing is requested or overwritten."""
    settings = _settings(tmp_path)
    run_site(Site('mast', POINT), settings)
    requests_made = len(server.requested)

    result = run_site(Site('mast', LatLonPoint(-23.65, 133.4)), settings)

    assert result.status == 'failed'
    assert 'Rename the site' in str(result.error)
    assert len(server.requested) == requests_made
    assert 'tas 2023-01' in result.missing


def test_run_site_node_far_from_the_request_fails_the_site(server: _Server, tmp_path: Path) -> None:
    """The safety net: a merged node more than one grid spacing from the request fails the site, writing no output."""
    result = run_site(Site('mast', LatLonPoint(-23.9, 133.4)), _settings(tmp_path))

    assert result.status == 'failed'
    assert 'more than one grid spacing' in str(result.error)
    assert result.outputs == []
    assert result.nodes


def test_run_site_a_merge_error_fails_the_site(
    server: _Server, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An error while merging is returned as a failed site, so a loop over sites carries on."""

    def broken(*_args: object, **_kwargs: object) -> None:
        raise ValueError('cannot merge')

    monkeypatch.setattr(barra2_dl.project, 'merge_netcdf_to_dataset', broken)

    result = run_site(Site('mast', POINT), _settings(tmp_path))

    assert result.status == 'failed'
    assert result.error == 'ValueError: cannot merge'
    assert result.variable_versions == VERSIONS


def test_run_site_cancel_writes_only_the_summary(server: _Server, tmp_path: Path) -> None:
    """A cancelled run makes no request, writes no output, and says cancelled in its summary."""
    cancel = threading.Event()
    cancel.set()

    result = run_site(Site('mast', POINT), _settings(tmp_path), cancel=cancel)

    assert result.status == 'cancelled'
    assert [file.status for file in result.files] == ['cancelled'] * 4
    assert result.outputs == []
    assert server.requested == []
    assert json.loads(result.summary_path.read_text())['status'] == 'cancelled'


def test_run_site_progress_sees_every_file(server: _Server, tmp_path: Path) -> None:
    """The callback is passed to the download and sees each file once."""
    seen: list[tuple[int, int, str]] = []

    def progress(done: int, total: int, result: FileResult) -> None:
        seen.append((done, total, result.status))

    run_site(Site('mast', POINT), _settings(tmp_path), progress=progress)

    assert seen == [(1, 4, 'downloaded'), (2, 4, 'downloaded'), (3, 4, 'downloaded'), (4, 4, 'downloaded')]


def test_run_site_invalid_settings_raise_before_any_request(server: _Server, tmp_path: Path) -> None:
    """Only invalid input raises, and no folder is made or request sent."""
    with pytest.raises(ProjectError):
        run_site(Site('mast', POINT), _settings(tmp_path, freq='20min'))

    assert server.requested == []
    assert not (tmp_path / 'cache').exists()


# endregion


@live_network
@pytest.mark.parametrize(
    ('domain', 'freq', 'preset'),
    [('AUS-11', '1hr', 'wind+density'), ('AUST-04', '1hr', 'wind+density'), ('AUST-04', '20min', 'wind')],
)
def test_run_site_live(domain: str, freq: str, preset: str, tmp_path: Path) -> None:
    """One month of a nearest-node site runs end to end against the real server on every domain and frequency."""
    settings = _settings(tmp_path, domain=domain, freq=freq, preset=preset)

    result = run_site(Site('live', LatLonPoint(-23.5527472, 133.3961111)), settings)

    assert result.status == 'ok', result.error
    assert result.outputs
    assert not result.missing


# region nodes
def test_run_site_nodes_csv_writes_a_file_per_node_in_the_order_given(server: _Server, tmp_path: Path) -> None:
    """Chosen nodes without the mean give node1 to nodeN files and the nodes in the summary, in order."""
    settings = _settings(tmp_path)

    result = run_site(Site('mast', POINT, nodes=list(NODES)), settings)

    assert result.status == 'ok'
    assert [path.name for path in result.outputs] == [f'mast_AUS-11_1hr_node{k}_20230101_20230103.csv' for k in (1, 2)]
    assert all('north=' in url for url in server.requested)
    assert [(node['node'], node['weight']) for node in result.nodes] == [(1, None), (2, None)]
    assert [(node['lat'], node['lon']) for node in result.nodes] == pytest.approx([(-23.54, 133.36), (-23.43, 133.47)])
    assert {'requested_lat', 'distance_km', 'orog'} <= set(result.nodes[0])
    assert result.inputs['selection'] == 'nodes'
    assert result.inputs['nodes'] == [[-23.54, 133.36], [-23.43, 133.47]]
    assert result.inputs['node_mean'] is False
    _, header = read_csv(result.outputs[1])
    assert header['Node selection'] == 'nodes'
    assert float(header['Latitude']) == pytest.approx(-23.43)
    assert json.loads(result.summary_path.read_text())['nodes'] == json.loads(json.dumps(result.nodes))


def test_run_site_nodes_with_the_mean_writes_it_beside_the_nodes(server: _Server, tmp_path: Path) -> None:
    """node_mean adds the mean's file, whose weights are in the summary and sum to one."""
    result = run_site(Site('mast', POINT, nodes=list(NODES), node_mean=True), _settings(tmp_path))

    assert [path.name.split('_')[3] for path in result.outputs] == ['nodes', 'node1', 'node2']
    assert sum(node['weight'] for node in result.nodes) == pytest.approx(1.0)
    assert result.inputs['node_mean'] is True


def test_run_site_nodes_netcdf_is_one_file_with_a_node_dimension(server: _Server, tmp_path: Path) -> None:
    """With format netcdf the nodes are one file named for the selection."""
    result = run_site(Site('mast', POINT, nodes=list(NODES)), _settings(tmp_path, format='netcdf'))

    assert [path.name for path in result.outputs] == ['mast_AUS-11_1hr_nodes_20230101_20230131.nc']
    with xr.open_dataset(result.outputs[0]) as ds:
        assert ds.sizes['node'] == 2
        assert ds.attrs['node_selection'] == 'nodes'
        assert 'wind_speed' not in ds


def test_run_site_nodes_that_are_not_grid_nodes_fail_the_site_and_keep_the_cache(
    server: _Server, tmp_path: Path
) -> None:
    """A made-up node fails the site with a message naming the nodes near it; nothing is written but the summary."""
    settings = _settings(tmp_path)

    result = run_site(Site('mast', POINT, nodes=[LatLonPoint(-23.55, 133.36)]), settings)

    assert result.status == 'failed'
    assert result.error is not None
    assert 'is not a node of AUS-11' in result.error
    assert 'nearest_nodes' in result.error
    assert result.outputs == []
    assert len(list(settings.cache.iterdir())) == 4
    assert result.summary_path.exists()


@live_network
@pytest.mark.parametrize('domain', ['AUS-11', 'AUST-04'])
def test_run_site_nodes_live(domain: str, tmp_path: Path) -> None:
    """One month of a nodes site, with the two nearest nodes from the live lookup and their mean, runs end to end."""
    settings = _settings(tmp_path, domain=domain, preset='wind')
    settings.cache.mkdir()
    point = LatLonPoint(-23.5527472, 133.3961111)
    found = nearest_nodes(point, domain, 2, cache=settings.cache)
    site = Site('live', point, nodes=[LatLonPoint(node.lat, node.lon) for node in found], node_mean=True)

    result = run_site(site, settings)

    assert result.status == 'ok', result.error
    assert [path.name.split('_')[3] for path in result.outputs] == ['nodes', 'node1', 'node2']
    assert [node['lat'] for node in result.nodes] == pytest.approx([node.lat for node in found])
    assert [node['lon'] for node in result.nodes] == pytest.approx([node.lon for node in found])
    assert sum(node['weight'] for node in result.nodes) == pytest.approx(1.0)


def test_run_site_nodes_rejects_invalid_nodes_before_any_request(server: _Server, tmp_path: Path) -> None:
    """A node too far from the site is a ProjectError, raised before any request."""
    with pytest.raises(ProjectError) as error:
        run_site(Site('mast', POINT, nodes=[LatLonPoint(-23.30, 133.40)]), _settings(tmp_path))

    assert _problems(error.value) == {('mast', 'nodes')}
    assert server.requested == []


# region polygon
def test_run_site_polygon_writes_the_masked_grid_and_the_site_mean(server: _Server, tmp_path: Path) -> None:
    """A boundary site is an area download; the netCDF has the mask, the overlap, the weights and the mean."""
    result = run_site(_polygon_site(node_mean=True), _settings(tmp_path, format='netcdf'))

    assert result.status == 'ok', result.error
    assert [path.name for path in result.outputs] == ['farm_AUS-11_1hr_area_20230101_20230131.nc']
    assert all('north=' in url for url in server.requested)
    with xr.open_dataset(result.outputs[0]) as ds:
        assert int((ds['cell_weight'] > 0).sum()) == 2
        assert float(ds['cell_weight'].sum()) == pytest.approx(1.0)
        assert 'ua_site_mean' in ds
        assert ds.attrs['boundary_source'] == 'boundary_two_cells.geojson'


def test_run_site_polygon_summary_lists_the_nodes_used_with_their_weights(server: _Server, tmp_path: Path) -> None:
    """The summary carries what a map needs: the boundary, and each node used with its overlap and weight."""
    result = run_site(_polygon_site(node_mean=True), _settings(tmp_path, format='netcdf'))

    assert result.inputs['selection'] == 'area'
    assert result.inputs['node_mean'] is True
    polygon = result.inputs['polygon']
    assert (polygon['source'], polygon['vertices'], polygon['holes']) == ('boundary_two_cells.geojson', 4, 0)
    assert polygon['bbox'] == {'north': -23.51, 'south': -23.57, 'east': 133.5, 'west': 133.33}
    assert len(polygon['sha256']) == 64
    assert result.inputs['sub_cell'] is False
    assert result.inputs['covered'] == pytest.approx(1.0)
    assert [(node['lat'], node['lon']) for node in result.nodes] == pytest.approx([(-23.54, 133.36), (-23.54, 133.47)])
    assert [node['weight'] for node in result.nodes] == pytest.approx([0.5, 0.5])
    assert all(0 < node['overlap'] < 1 and node['orog'] and node['distance_km'] > 0 for node in result.nodes)
    assert json.loads(result.summary_path.read_text())['nodes'] == json.loads(json.dumps(result.nodes))


def test_run_site_polygon_hash_changes_with_the_outline(server: _Server, tmp_path: Path) -> None:
    """A boundary file edited under the same name shows in the summary through its hash."""
    first = run_site(_polygon_site(), _settings(tmp_path, format='netcdf'))
    second = run_site(replace(_polygon_site(), polygon=SUB_CELL), _settings(tmp_path / 'again', format='netcdf'))

    assert first.inputs['polygon']['sha256'] != second.inputs['polygon']['sha256']


def test_run_site_polygon_smaller_than_a_cell_uses_one_node(server: _Server, tmp_path: Path) -> None:
    """A sub-cell boundary has one node with weight 1, and the summary says it is sub-cell."""
    result = run_site(Site('farm', polygon=SUB_CELL), _settings(tmp_path, format='netcdf'))

    assert result.status == 'ok', result.error
    assert result.inputs['sub_cell'] is True
    assert [(node['lat'], node['lon'], node['weight']) for node in result.nodes] == pytest.approx(
        [(-23.54, 133.36, 1.0)]
    )
    assert result.inputs['covered'] == pytest.approx(0.75)


def test_run_site_polygon_outside_the_downloaded_grid_fails_the_site(server: _Server, tmp_path: Path) -> None:
    """A boundary that overlaps none of the returned nodes fails with a message, writing only the summary."""
    away = Polygon(((-23.30, 133.35), (-23.30, 133.40), (-23.29, 133.40), (-23.29, 133.35)))

    result = run_site(Site('farm', polygon=away), _settings(tmp_path, format='netcdf'))

    assert result.status == 'failed'
    assert 'overlaps no BARRA2 node of AUS-11' in str(result.error)
    assert result.outputs == []


def test_run_site_polygon_with_csv_is_rejected_before_any_request(server: _Server, tmp_path: Path) -> None:
    """A boundary can't be written as csv: a ProjectError, before any request."""
    with pytest.raises(ProjectError) as error:
        run_site(_polygon_site(), _settings(tmp_path))

    assert _problems(error.value) == {('farm', 'format')}
    assert server.requested == []


@live_network
@pytest.mark.parametrize('domain', ['AUS-11', 'AUST-04'])
def test_run_site_polygon_live_ncss_returns_every_node_the_boundary_overlaps(domain: str, tmp_path: Path) -> None:
    """One month on the real server: no node beyond the returned grid overlaps the boundary; the mean is written."""
    spacing = BARRA2_GRID_SPACING[domain]
    polygon = Polygon(
        (
            (-23.5527 - 1.4 * spacing, 133.3961 - 1.3 * spacing),
            (-23.5527 - 1.2 * spacing, 133.3961 + 1.6 * spacing),
            (-23.5527 + 1.5 * spacing, 133.3961 + 1.1 * spacing),
            (-23.5527 + 1.3 * spacing, 133.3961 - 1.5 * spacing),
        ),
        source='live',
    )
    settings = _settings(tmp_path, domain=domain, preset='wind', format='netcdf')

    result = run_site(Site('live', polygon=polygon, node_mean=True), settings)

    assert result.status == 'ok', result.error
    with xr.open_dataset(result.outputs[0]) as ds:
        lats, lons = ds['lat'].to_numpy(), ds['lon'].to_numpy()
        around_lats = [lats[0] - spacing, *lats, lats[-1] + spacing]
        around_lons = [lons[0] - spacing, *lons, lons[-1] + spacing]
        ring = polygon.cell_overlap(around_lats, around_lons, spacing)
        assert ring[0].max() < 1e-9 and ring[-1].max() < 1e-9
        assert ring[:, 0].max() < 1e-9 and ring[:, -1].max() < 1e-9
        assert float(ds['cell_weight'].sum()) == pytest.approx(1.0)
        assert 'wind_speed_site_mean' in ds


@live_network
@pytest.mark.parametrize('domain', ['AUS-11', 'AUST-04'])
def test_run_site_polygon_live_edges_on_cell_edges_use_exactly_one_node(domain: str, tmp_path: Path) -> None:
    """A boundary whose edges lie on the edges of one cell (built from looked-up nodes) uses just that node."""
    found = nearest_nodes(LatLonPoint(-23.5527, 133.3961), domain, 9, cache=tmp_path)
    lats, lons = sorted({node.lat for node in found}), sorted({node.lon for node in found})
    south, north = (lats[0] + lats[1]) / 2, (lats[1] + lats[2]) / 2
    west, east = (lons[0] + lons[1]) / 2, (lons[1] + lons[2]) / 2
    polygon = Polygon(((south, west), (south, east), (north, east), (north, west)), source='live')
    settings = _settings(tmp_path / 'run', domain=domain, preset='wind', format='netcdf')

    result = run_site(Site('live', polygon=polygon), settings)

    assert result.status == 'ok', result.error
    assert [(node['lat'], node['lon']) for node in result.nodes] == pytest.approx([(lats[1], lons[1])])


# endregion


# endregion


# region site_result_to_dict
def test_site_result_to_dict_is_plain_json_data(server: _Server, tmp_path: Path) -> None:
    """The summary has the documented keys, and everything in it serialises."""
    result = run_site(Site('mast', POINT), _settings(tmp_path))

    summary = site_result_to_dict(result)

    assert set(summary) == {
        'schema_version',
        'site',
        'status',
        'error',
        'inputs',
        'package_version',
        'started',
        'finished',
        'variable_versions',
        'files',
        'missing',
        'outputs',
        'nodes',
    }
    assert summary['schema_version'] == 1
    assert summary['inputs']['lat'] == -23.55
    assert summary['files'][0] == {
        'name': 'mast_AUS-11_1hr_ua50m_20230101_20230131.nc',
        'status': 'downloaded',
        'status_code': 200,
        'attempts': 1,
        'error': None,
    }
    assert summary['nodes'][0]['requested_lat'] == -23.55
    assert summary['nodes'][0]['distance_km'] == pytest.approx(4.23, abs=0.05)
    json.dumps(summary)


# endregion
# endregion
