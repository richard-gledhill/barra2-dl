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
from barra2_dl.mapping import LatLonBBox, LatLonPoint
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
