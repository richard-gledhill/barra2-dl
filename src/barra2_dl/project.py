"""The engine: a project file or a form becomes sites and settings, and run_site turns each site into output files."""

import json
import logging
import re
import sys
import threading
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from functools import partial
from importlib.metadata import version
from pathlib import Path
from typing import Any, cast

import xarray as xr

from barra2_dl.convert import convert_wind_components
from barra2_dl.download import (
    CacheMismatchError,
    FileResult,
    ProgressCallback,
    area_data_urlfilenames,
    cache_problems,
    download_multithread,
    point_data_urlfilenames,
    preset_variables,
    resolve_variable_versions,
)
from barra2_dl.globals import (
    BARRA2_DOWNLOAD_FORMATS,
    BARRA2_FREQS,
    BARRA2_GRID_SPACING,
    BARRA2_INDEX,
    BARRA2_NODE_SELECTIONS,
    BARRA2_OUTPUT_FORMATS,
    BARRA2_PRESET_DEFAULT,
    BARRA2_PRESETS,
    BARRA2_URL,
    DownloadFormat,
    NodeSelection,
    OutputFormat,
    SiteStatus,
)
from barra2_dl.mapping import LatLonBBox, LatLonPoint, distance_km
from barra2_dl.merge import (
    merge_csvs_to_df,
    merge_netcdf_to_dataset,
    read_fixed_fields,
    to_dataset,
    write_csv,
    write_df_csv,
)

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

__all__ = [
    'PlannedFile',
    'Problem',
    'Project',
    'ProjectError',
    'Settings',
    'Site',
    'SitePlan',
    'SiteResult',
    'load_project',
    'plan_site',
    'project_from_dict',
    'run_site',
    'site_from_dict',
    'site_result_to_dict',
    'validate',
]


# region Constants and types
SCHEMA_VERSION = 1

# the settings a site may override; cache, out and workers belong to the whole project
_SITE_SETTINGS = ('domain', 'freq', 'preset', 'node_selection', 'format', 'download', 'start', 'end')
_PROJECT_SETTINGS = ('cache', 'out', 'workers')
_TEXT_SETTINGS = ('domain', 'freq', 'preset', 'node_selection', 'format', 'download')
_POINT_KEYS = ('lat', 'lon')
_BOX_KEYS = ('north', 'south', 'east', 'west')
_SITE_NAME = re.compile(r'[A-Za-z0-9._-]+')
# the variable and month in a series filename, e.g. demo_AUS-11_1hr_ua50m_20230201_20230228.nc
_SERIES_FILE = re.compile(r'_(?P<var>[A-Za-z0-9]+)_(?P<year>\d{4})(?P<month>\d{2})\d{2}_\d{8}\.(?:nc|csv)$')
_FIXED_FILE = re.compile(r'_(?P<var>[A-Za-z0-9]+)\.(?:nc|csv)$')


@dataclass(frozen=True)
class Settings:
    """What a run does, for the whole project and as the default for each site.

    Attributes:
        start: First day to download, inclusive.
        end: Last day to download, inclusive.
        domain: BARRA2 domain, a key of BARRA2_DOMAINS.
        freq: BARRA2 frequency available for the domain in BARRA2_FREQS.
        preset: A key of BARRA2_PRESETS.
        node_selection: 'nearest' or 'average4' for a point site; a box site is always 'area'.
        format: The output, 'csv' or 'netcdf'.
        download: The download format, 'netcdf4' (default) or 'csv' (a nearest-node point site with csv output).
        cache: Folder for the downloaded files.
        out: Folder for the outputs and run summaries.
        workers: Parallel downloads.
    """

    start: date
    end: date
    domain: str = 'AUS-11'
    freq: str = '1hr'
    preset: str = BARRA2_PRESET_DEFAULT
    node_selection: NodeSelection = 'nearest'
    format: OutputFormat = 'csv'
    download: DownloadFormat = 'netcdf4'
    cache: Path = Path('cache')
    out: Path = Path('output')
    workers: int = 4


@dataclass(frozen=True)
class Site:
    """A place to get data for: a point or a box, with any settings it overrides.

    Attributes:
        name: Becomes the filename prefix, so only letters, digits, dot, underscore and hyphen.
        point: The site, for a nearest-node or four-node-average download.
        bbox: The box, for an area download. Exactly one of point and bbox is set.
        overrides: Settings this site changes, keys from the site-overridable settings.
    """

    name: str
    point: LatLonPoint | None = None
    bbox: LatLonBBox | None = None
    overrides: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Project:
    """The settings, the sites, and the file they came from if any."""

    settings: Settings
    sites: list[Site]
    path: Path | None = None


@dataclass(frozen=True)
class Problem:
    """One fault: the site (None for a project-wide setting), the key, and what to change."""

    site: str | None
    key: str
    message: str

    def __str__(self) -> str:
        """Format as 'site <name>, key: message'."""
        where = f'site <{self.site}>' if self.site else 'settings'
        return f'{where}, {self.key}: {self.message}'


@dataclass(frozen=True)
class PlannedFile:
    """A file a run would download: its name, url, whether it is already cached, and why a cached file fails."""

    filename: str
    url: str
    cached: bool
    problem: str | None = None


@dataclass(frozen=True)
class SitePlan:
    """The files a run of one site would download, and which are already in the cache."""

    site: str
    files: list[PlannedFile]


@dataclass(frozen=True)
class SiteResult:
    """The outcome of one site's run; site_result_to_dict is its run summary.

    Attributes:
        site: The site name.
        status: 'ok', 'partial' (output written, some files missing), 'failed' or 'cancelled'.
        outputs: The files written, empty if failed or cancelled.
        summary_path: The run summary file, written for every outcome.
        files: The result of every file.
        missing: The variable-months and fixed fields that could not be downloaded, e.g. 'ua50m 2023-02'.
        error: What went wrong when status is 'failed', else None.
        inputs: The site and its effective settings, as written to the summary.
        started: When the run began, UTC.
        finished: When it ended, UTC.
        variable_versions: The dataset version of each variable.
        nodes: The requested and actual node for each node used, with its distance and altitude.
    """

    site: str
    status: SiteStatus
    outputs: list[Path]
    summary_path: Path
    files: list[FileResult]
    missing: list[str]
    error: str | None
    inputs: dict[str, Any]
    started: datetime
    finished: datetime
    variable_versions: dict[str, str] = field(default_factory=dict)
    nodes: list[dict[str, Any]] = field(default_factory=list)


# endregion


# region Errors
class ProjectError(ValueError):
    """The project, a site or the settings are invalid; raised before any request, listing every problem.

    Attributes:
        problems (list[Problem]): One per fault, each with its site and key.
    """

    def __init__(self, problems: list[Problem]) -> None:
        """Build the message listing each problem."""
        self.problems = problems
        super().__init__('Invalid project:\n' + '\n'.join(f'  {problem}' for problem in problems))


# endregion


# region Public API
def load_project(path: str | Path) -> Project:
    """Read and validate a TOML project file: a [settings] table and one [[site]] table per site.

    Relative cache and out folders are relative to the file's folder. See project_from_dict for the keys.

    Args:
        path (str | Path): The project file.

    Returns:
        Project: The validated settings and sites.

    Raises:
        ProjectError: If the file isn't valid TOML or any setting or site is invalid; every problem is listed.
        FileNotFoundError: If the file doesn't exist.
    """
    file = Path(path)
    try:
        data = tomllib.loads(file.read_text(encoding='utf-8'))
    except tomllib.TOMLDecodeError as error:
        raise ProjectError([Problem(None, 'file', f'{file.name} is not valid TOML: {error}')]) from None
    return replace(project_from_dict(data, file.parent), path=file)


def project_from_dict(data: Mapping[str, Any], base_dir: str | Path = '.') -> Project:
    """Build a Project from plain data, as a project file or a form gives it, checking everything at once.

    The data has a 'settings' table (keys of Settings; start and end are required, as ISO dates or dates) and a 'site'
    list of tables. A site has a name and either lat and lon or north, south, east and west, and may override domain,
    freq, preset, node_selection, format, download, start and end. Unknown keys are errors.

    Args:
        data (Mapping[str, Any]): The parsed project.
        base_dir (str | Path): Relative cache and out folders are relative to this.

    Returns:
        Project: The validated settings and sites.

    Raises:
        ProjectError: If anything is invalid; every problem is listed with its site and key.
    """
    problems: list[Problem] = []
    for key in sorted(set(data) - {'settings', 'site'}):
        problems.append(Problem(None, key, 'Unknown table. A project has [settings] and [[site]] tables only.'))
    settings_data = data.get('settings', {})
    if not isinstance(settings_data, Mapping):
        problems.append(Problem(None, 'settings', 'Must be a table.'))
        settings_data = {}
    settings = _settings_from_dict(settings_data, Path(base_dir), problems)
    site_data = data.get('site', [])
    if not isinstance(site_data, list) or not site_data:
        problems.append(Problem(None, 'site', 'Add at least one [[site]] table.'))
        site_data = []
    sites = [_site_from_dict(item, settings, problems) for item in site_data if isinstance(item, Mapping)]
    if len(sites) != len(site_data):
        problems.append(Problem(None, 'site', 'Every site must be a table.'))
    for name in sorted({site.name for site in sites if [other.name for other in sites].count(site.name) > 1}):
        problems.append(Problem(name, 'name', 'Site names must be unique, because the name is the filename prefix.'))
    # a faulty project-wide setting is reported once, not once for every site that inherits it
    inherited = _value_problems(settings)
    problems += [Problem(None, key, message) for key, message in inherited]
    for site in sites:
        problems += [
            problem
            for problem in validate(settings, site)
            if (problem.key, problem.message) not in inherited or problem.key in site.overrides
        ]
    if problems:
        raise ProjectError(problems)
    return Project(settings, sites)


def site_from_dict(data: Mapping[str, Any], settings: Settings) -> Site:
    """Build one validated Site from plain data, as a form gives it.

    Args:
        data (Mapping[str, Any]): The site's keys: name, lat and lon or north, south, east and west, and any overrides.
        settings (Settings): The project settings the site is checked against.

    Returns:
        Site: The site.

    Raises:
        ProjectError: If the site is invalid; every problem is listed.
    """
    problems: list[Problem] = []
    site = _site_from_dict(data, settings, problems)
    problems += validate(settings, site)
    if problems:
        raise ProjectError(problems)
    return site


def validate(settings: Settings, site: Site) -> list[Problem]:
    """Return every problem with a site run under the settings, empty if it is fine to run.

    A form calls this to mark fields; run_site calls it before any request. Each message says what to change.

    Args:
        settings (Settings): The project settings.
        site (Site): The site, with any overrides.

    Returns:
        list[Problem]: One per fault.
    """
    problems: list[Problem] = []

    def add(key: str, message: str) -> None:
        problems.append(Problem(site.name, key, message))

    if not _SITE_NAME.fullmatch(site.name):
        add('name', 'Use letters, digits, dot, underscore and hyphen only: the name becomes the filename prefix.')
    for key in sorted(set(site.overrides) - set(_SITE_SETTINGS)):
        add(key, f'A site cannot override this. Overridable: {", ".join(_SITE_SETTINGS)}.')
    if (site.point is None) == (site.bbox is None):
        add('lat/lon', 'Give either lat and lon, or north, south, east and west, not both and not neither.')
    if site.bbox is not None and not (site.bbox.north > site.bbox.south and site.bbox.east > site.bbox.west):
        add('north/south/east/west', 'north must be greater than south and east greater than west.')
    effective = replace(settings, **{key: value for key, value in site.overrides.items() if key in _SITE_SETTINGS})
    problems += [Problem(site.name, key, message) for key, message in _setting_problems(effective, site)]
    return problems


def plan_site(site: Site, settings: Settings) -> SitePlan:
    """List the files a run of the site would download and which are already cached, without any request.

    A cached file that doesn't match the request (a moved site that kept its name) is listed with its problem, as
    download would refuse it.

    Args:
        site (Site): The site.
        settings (Settings): The project settings.

    Returns:
        SitePlan: One entry per file, in download order.

    Raises:
        ProjectError: If the site or settings are invalid.
    """
    effective = _checked(site, settings)
    urlfilenames = _urlfilenames(site, effective)
    problems = dict(cache_problems(urlfilenames, effective.cache))
    return SitePlan(
        site.name,
        [
            PlannedFile(
                filename,
                url,
                (effective.cache / filename).is_file() and filename not in problems,
                problems.get(filename),
            )
            for url, filename in urlfilenames
        ],
    )


def run_site(
    site: Site,
    settings: Settings,
    progress: ProgressCallback | None = None,
    cancel: threading.Event | None = None,
) -> SiteResult:
    """Download, merge and write the output for one site, and write its run summary.

    The downloads are netCDF4 unless a nearest-node point site has download='csv', which takes the csv route. Output is
    <name>_<domain>_<freq>_<selection>_<start>_<end>.nc, or csv files with the metadata header, beside
    <name>_run_summary.json. A failure of the site is returned, not raised, so a loop over sites carries on; the
    gaps of a partial run are in missing. A cancelled run writes only the summary.

    Args:
        site (Site): The site.
        settings (Settings): The project settings.
        progress (ProgressCallback | None): Called as progress(done, total, result) once per file.
        cancel (threading.Event | None): Set it to stop new requests; the result is cancelled.

    Returns:
        SiteResult: The outcome; site_result_to_dict is the run summary written to summary_path.

    Raises:
        ProjectError: If the site or settings are invalid, before any request.
    """
    effective = _checked(site, settings)
    finish = partial(_finish, site, effective, datetime.now(UTC))
    effective.cache.mkdir(parents=True, exist_ok=True)
    effective.out.mkdir(parents=True, exist_ok=True)
    urlfilenames = _urlfilenames(site, effective)
    try:
        files = download_multithread(
            urlfilenames, effective.cache, workers=effective.workers, progress=progress, cancel=cancel
        )
    except CacheMismatchError as error:
        refused = [FileResult(name, 'failed', error=reason) for name, reason in error.problems]
        return finish('failed', str(error), files=refused, missing=[_label(result.filename) for result in refused])
    missing = [_label(result.filename) for result in files if result.status == 'failed']
    if any(result.status == 'cancelled' for result in files):
        return finish('cancelled', None, files=files, missing=missing)
    if not any(result.status in ('downloaded', 'skipped') and _SERIES_FILE.search(result.filename) for result in files):
        return finish(
            'failed', 'No data files could be downloaded; see the file results.', files=files, missing=missing
        )
    versions: dict[str, str] = {}
    try:
        variables = preset_variables(effective.preset, effective.domain, effective.freq)
        versions = resolve_variable_versions(variables, effective.domain, effective.freq)
        outputs, nodes, problem = _write_outputs(site, effective, urlfilenames, versions)
    except (ValueError, OSError, KeyError) as error:
        return finish('failed', f'{type(error).__name__}: {error}', files=files, missing=missing, versions=versions)
    if problem:
        return finish('failed', problem, files=files, missing=missing, versions=versions, nodes=nodes)
    return finish(
        'partial' if missing else 'ok',
        None,
        files=files,
        missing=missing,
        outputs=outputs,
        versions=versions,
        nodes=nodes,
    )


def site_result_to_dict(result: SiteResult) -> dict[str, Any]:
    """Return the result as the run summary: plain data that json.dumps writes, the same for any interface.

    Args:
        result (SiteResult): From run_site.

    Returns:
        dict[str, Any]: schema_version, site, status, error, inputs, package_version, started and finished (UTC),
        variable_versions, files, missing, outputs and nodes.
    """
    return {
        'schema_version': SCHEMA_VERSION,
        'site': result.site,
        'status': result.status,
        'error': result.error,
        'inputs': result.inputs,
        'package_version': version('barra2-dl'),
        'started': result.started.isoformat(),
        'finished': result.finished.isoformat(),
        'variable_versions': result.variable_versions,
        'files': [
            {
                'name': file.filename,
                'status': file.status,
                'status_code': file.status_code,
                'attempts': file.attempts,
                'error': file.error,
            }
            for file in result.files
        ],
        'missing': result.missing,
        'outputs': [str(path) for path in result.outputs],
        'nodes': result.nodes,
    }


# endregion


# region Helpers
def _finish(
    site: Site,
    settings: Settings,
    started: datetime,
    status: SiteStatus,
    error: str | None,
    *,
    files: list[FileResult],
    missing: list[str],
    outputs: list[Path] | None = None,
    versions: dict[str, str] | None = None,
    nodes: list[dict[str, Any]] | None = None,
) -> SiteResult:
    """Build the result and write <name>_run_summary.json beside the outputs."""
    result = SiteResult(
        site=site.name,
        status=status,
        outputs=outputs or [],
        summary_path=settings.out / f'{site.name}_run_summary.json',
        files=files,
        missing=missing,
        error=error,
        inputs=_inputs(site, settings),
        started=started,
        finished=datetime.now(UTC),
        variable_versions=versions or {},
        nodes=nodes or [],
    )
    result.summary_path.write_text(json.dumps(site_result_to_dict(result), indent=2, default=str), encoding='utf-8')
    message = f'<{site.name}> {status}' + (f': {error}' if error else '')
    logger.info(message)
    sys.stdout.write(f'{message}\n')
    return result


def _settings_from_dict(data: Mapping[str, Any], base_dir: Path, problems: list[Problem]) -> Settings:
    """Build Settings from a [settings] table, adding to problems; a bad value falls back to the default."""
    known = (*_SITE_SETTINGS, *_PROJECT_SETTINGS)
    for key in sorted(set(data) - set(known)):
        problems.append(Problem(None, key, f'Unknown setting. Known: {", ".join(known)}.'))
    values: dict[str, Any] = {}
    for key in _TEXT_SETTINGS:
        if key in data:
            _put_text(values, key, data[key], None, problems)
    for key in ('start', 'end'):
        if key not in data:
            problems.append(Problem(None, key, 'Required: a date such as "2023-01-31".'))
            values[key] = date(1970, 1, 1)
        else:
            values[key] = _put_date(data[key], None, key, problems) or date(1970, 1, 1)
    values |= _project_values(data, base_dir, problems)
    return Settings(**values)


def _project_values(data: Mapping[str, Any], base_dir: Path, problems: list[Problem]) -> dict[str, Any]:
    """Return the cache, out and workers settings from a [settings] table, adding to problems."""
    values: dict[str, Any] = {'cache': base_dir / Settings.cache, 'out': base_dir / Settings.out}
    for key in ('cache', 'out'):
        if key in data:
            if isinstance(data[key], str):
                values[key] = base_dir / data[key]
            else:
                problems.append(Problem(None, key, 'Must be a folder path in quotes.'))
    if 'workers' in data:
        workers = data['workers']
        if isinstance(workers, int) and not isinstance(workers, bool):
            values['workers'] = workers
        else:
            problems.append(Problem(None, 'workers', 'Must be a whole number.'))
    return values


def _site_from_dict(data: Mapping[str, Any], settings: Settings, problems: list[Problem]) -> Site:
    """Build a Site from a [[site]] table, adding to problems; settings is only for the defaults of a bad override."""
    name = data.get('name')
    if not isinstance(name, str):
        problems.append(Problem(None, 'name', 'Every site needs a name, in quotes.'))
        name = '(unnamed)'
    known = ('name', *_POINT_KEYS, *_BOX_KEYS, *_SITE_SETTINGS)
    for key in sorted(set(data) - set(known)):
        problems.append(Problem(name, key, f'Unknown key. Known: {", ".join(known)}.'))
    point = _geometry(data, _POINT_KEYS, name, problems)
    box = _geometry(data, _BOX_KEYS, name, problems)
    overrides: dict[str, Any] = {}
    for key in _TEXT_SETTINGS:
        if key in data:
            _put_text(overrides, key, data[key], name, problems)
    for key in ('start', 'end'):
        if key in data and (parsed := _put_date(data[key], name, key, problems)):
            overrides[key] = parsed
    return Site(
        name,
        LatLonPoint(*point) if point else None,
        LatLonBBox(*box) if box else None,
        overrides,
    )


def _geometry(
    data: Mapping[str, Any], keys: tuple[str, ...], name: str, problems: list[Problem]
) -> tuple[float, ...] | None:
    """Return the numbers of a point or box, or None if absent or invalid (problems then says why)."""
    present = [key for key in keys if key in data]
    if not present:
        return None
    missing = [key for key in keys if key not in data]
    if missing:
        problems.append(Problem(name, '/'.join(keys), f'Also give {", ".join(missing)}.'))
        return None
    values = [data[key] for key in keys]
    if not all(isinstance(value, int | float) and not isinstance(value, bool) for value in values):
        problems.append(Problem(name, '/'.join(keys), 'Must be numbers in degrees.'))
        return None
    try:
        if keys == _POINT_KEYS:
            LatLonPoint(*values)
        else:
            LatLonBBox(*values)
    except ValueError as error:
        problems.append(Problem(name, '/'.join(keys), str(error)))
        return None
    return tuple(float(value) for value in values)


def _put_text(values: dict[str, Any], key: str, value: object, site: str | None, problems: list[Problem]) -> None:
    """Store a text setting in values, or add a problem if it isn't text."""
    if isinstance(value, str):
        values[key] = value
    else:
        problems.append(Problem(site, key, 'Must be text in quotes.'))


def _put_date(value: object, site: str | None, key: str, problems: list[Problem]) -> date | None:
    """Return a date from a TOML date or an ISO string, or add a problem and return None."""
    try:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            return date.fromisoformat(value)
    except ValueError:
        pass
    problems.append(Problem(site, key, 'Must be a date such as "2023-01-31".'))
    return None


def _setting_problems(settings: Settings, site: Site) -> list[tuple[str, str]]:
    """Return the (key, message) of each problem with the settings as the site would run them."""
    return _value_problems(settings) + _combination_problems(settings, site)


def _value_problems(settings: Settings) -> list[tuple[str, str]]:
    """Return the (key, message) of each setting that is not one of the allowed values."""
    problems: list[tuple[str, str]] = []
    if settings.freq not in BARRA2_FREQS.get(settings.domain, {}):
        key = 'freq' if settings.domain in BARRA2_FREQS else 'domain'
        supported = ', '.join(f'{domain} {freq}' for domain, freqs in BARRA2_FREQS.items() for freq in freqs)
        problems.append((key, f'{settings.domain} {settings.freq} is not supported. Supported: {supported}.'))
    elif settings.preset not in BARRA2_PRESETS:
        problems.append(('preset', f'Unknown preset. Presets: {", ".join(BARRA2_PRESETS)}.'))
    else:
        try:
            preset_variables(settings.preset, settings.domain, settings.freq)
        except ValueError as error:
            problems.append(('preset', str(error)))
    if settings.node_selection not in BARRA2_NODE_SELECTIONS or settings.node_selection == 'area':
        problems.append(('node_selection', 'Use nearest or average4; a box site is an area automatically.'))
    if settings.format not in BARRA2_OUTPUT_FORMATS:
        problems.append(('format', f'Use one of: {", ".join(BARRA2_OUTPUT_FORMATS)}.'))
    if settings.download not in BARRA2_DOWNLOAD_FORMATS:
        problems.append(('download', f'Use one of: {", ".join(BARRA2_DOWNLOAD_FORMATS)}.'))
    if settings.start > settings.end:
        problems.append(('start', 'start must not be after end.'))
    if settings.workers < 1:
        problems.append(('workers', 'Use at least 1.'))
    return problems


def _combination_problems(settings: Settings, site: Site) -> list[tuple[str, str]]:
    """Return the (key, message) of each combination of site and settings that cannot run."""
    problems: list[tuple[str, str]] = []
    selection = _selection(site, settings)
    if site.bbox is not None and site.overrides.get('node_selection', 'area') != 'area':
        problems.append(('node_selection', 'A box site is an area download; remove node_selection or use a point.'))
    if selection == 'area' and settings.format == 'csv':
        problems.append(('format', 'An area is a grid and cannot be written as csv; set format = "netcdf".'))
    if settings.download == 'csv' and (site.bbox is not None or selection != 'nearest' or settings.format != 'csv'):
        problems.append(
            ('download', 'The csv download is for a nearest-node point site with csv output; use netcdf4 otherwise.')
        )
    return problems


def _selection(site: Site, settings: Settings) -> str:
    """Return the node selection a site runs: area for a box, else the setting."""
    return 'area' if site.bbox is not None else settings.node_selection


def _effective(site: Site, settings: Settings) -> Settings:
    """Return the settings with the site's overrides applied."""
    return replace(settings, **{key: value for key, value in site.overrides.items() if key in _SITE_SETTINGS})


def _checked(site: Site, settings: Settings) -> Settings:
    """Return the site's effective settings, or raise ProjectError listing every problem."""
    problems = validate(settings, site)
    if problems:
        raise ProjectError(problems)
    return _effective(site, settings)


def _urlfilenames(site: Site, settings: Settings) -> list[tuple[str, str]]:
    """Return the (url, filename) pairs for the site: netCDF4 unless the csv download is chosen."""
    variables = preset_variables(settings.preset, settings.domain, settings.freq)
    period = (settings.start.isoformat(), settings.end.isoformat())
    if site.bbox is not None:
        return area_data_urlfilenames(
            site.bbox, variables, *period, site.name, domain=settings.domain, freq=settings.freq
        )
    point = cast(LatLonPoint, site.point)  # validate has checked that exactly one of point and bbox is set
    return point_data_urlfilenames(
        BARRA2_URL,
        variables,
        point.lat,
        point.lon,
        *period,
        site.name,
        'csv_file' if settings.download == 'csv' else 'netcdf4',
        domain=settings.domain,
        freq=settings.freq,
        node_selection=settings.node_selection,
    )


def _label(filename: str) -> str:
    """Name a file for the missing list: 'ua50m 2023-02' for a series file, 'orog' for a fixed field."""
    series = _SERIES_FILE.search(filename)
    if series:
        return f'{series["var"]} {series["year"]}-{series["month"]}'
    fixed = _FIXED_FILE.search(filename)
    return fixed['var'] if fixed else filename


def _inputs(site: Site, settings: Settings) -> dict[str, Any]:
    """Describe the site and its effective settings for the summary, as plain data."""
    place: dict[str, Any] = {}
    if site.point is not None:
        place = {'lat': float(site.point.lat), 'lon': float(site.point.lon)}
    if site.bbox is not None:
        box = site.bbox
        place = {'north': float(box.north), 'south': float(box.south), 'east': float(box.east), 'west': float(box.west)}
    return {
        'name': site.name,
        **place,
        'selection': _selection(site, settings),
        'domain': settings.domain,
        'freq': settings.freq,
        'preset': settings.preset,
        'format': settings.format,
        'download': settings.download,
        'start': settings.start.isoformat(),
        'end': settings.end.isoformat(),
        'cache': str(settings.cache),
        'out': str(settings.out),
        'workers': settings.workers,
    }


def _write_outputs(
    site: Site, settings: Settings, urlfilenames: list[tuple[str, str]], versions: dict[str, str]
) -> tuple[list[Path], list[dict[str, Any]], str | None]:
    """Merge the cached files and write the outputs; return (outputs, nodes, a problem that fails the site, or None)."""
    pattern = f'{site.name}_{settings.domain}_{settings.freq}_*'
    cache, out = str(settings.cache), settings.out
    dates = f'{settings.start.strftime("%Y%m%d")}_{settings.end.strftime("%Y%m%d")}'
    selection = _selection(site, settings)
    requested = cast(LatLonPoint, site.point)  # box sites are never the csv download; their requested point is unused
    if settings.download == 'csv':
        orog = read_fixed_fields(cache, f'{site.name}_{settings.domain}_fx_orog.csv').get('orog[unit="m"]')
        frame = convert_wind_components(merge_csvs_to_df(cache, f'{pattern}.csv', BARRA2_INDEX))
        ds = to_dataset(
            frame, domain=settings.domain, freq=settings.freq, requested=requested, orog=orog, versions=versions
        )
    else:
        fixed = next((name for _, name in urlfilenames if '_fx_' in name and '_orog.' in name), None)
        orog = None
        if selection == 'nearest' and fixed:
            orog = read_fixed_fields(cache, fixed).get('orog[unit="m"]')
        ds = merge_netcdf_to_dataset(
            cache,
            f'{pattern}.nc',
            domain=settings.domain,
            freq=settings.freq,
            requested=requested,
            orog=orog,
            node_selection=selection,
            versions=versions,
            fixed_pattern=fixed if selection != 'nearest' else None,
        )
    nodes = _nodes(ds, selection)
    problem = _location_problem(ds, requested, BARRA2_GRID_SPACING[settings.domain]) if requested else None
    if problem:
        return [], nodes, problem
    if settings.download == 'csv':
        return (
            [
                write_df_csv(
                    frame,
                    out / f'{site.name}_{settings.domain}_{settings.freq}_nearest_{dates}.csv',
                    domain=settings.domain,
                    freq=settings.freq,
                    requested=requested,
                    orog=orog,
                    versions=versions,
                )
            ],
            nodes,
            None,
        )
    if settings.format == 'csv':
        return write_csv(ds, out, site.name), nodes, None
    path = out / f'{site.name}_{settings.domain}_{settings.freq}_{selection}_{dates}.nc'
    ds.to_netcdf(path)
    return [path], nodes, None


def _location_problem(ds: xr.Dataset, requested: LatLonPoint, spacing: float) -> str | None:
    """Return why the merged nodes aren't around the requested point (further than one grid spacing), or None."""
    if 'node_lat' in ds:
        lats, lons = list(map(float, ds['node_lat'].to_numpy())), list(map(float, ds['node_lon'].to_numpy()))
    else:
        lats, lons = [float(ds['lat'])], [float(ds['lon'])]
    for lat, lon in zip(lats, lons, strict=True):
        if abs(lat - float(requested.lat)) > spacing or abs(lon - float(requested.lon)) > spacing:
            return (
                f'The node at {lat:.3f}, {lon:.3f} is more than one grid spacing ({spacing}) from the requested point '
                f'{float(requested.lat):.3f}, {float(requested.lon):.3f}; the cached data may be for another location.'
            )
    return None


def _nodes(ds: xr.Dataset, selection: str) -> list[dict[str, Any]]:
    """Describe the nodes in a Dataset: requested and actual position, distance and altitude, or an area's extent."""
    if selection == 'area':
        orog = ds.get('orog')
        return [
            {
                'count': int(ds.sizes['lat'] * ds.sizes['lon']),
                'orog_min': float(orog.min()) if orog is not None else None,
                'orog_max': float(orog.max()) if orog is not None else None,
            }
        ]
    requested = (float(ds['requested_lat']), float(ds['requested_lon']))
    if 'node' in ds.dims:
        return [
            {
                'requested_lat': requested[0],
                'requested_lon': requested[1],
                'lat': float(ds['node_lat'][k]),
                'lon': float(ds['node_lon'][k]),
                'distance_km': float(ds['node_distance'][k]),
                'weight': float(ds['node_weight'][k]),
                'orog': float(ds['node_orog'][k]) if 'node_orog' in ds else None,
            }
            for k in range(ds.sizes['node'])
        ]
    lat, lon = float(ds['lat']), float(ds['lon'])
    return [
        {
            'requested_lat': requested[0],
            'requested_lon': requested[1],
            'lat': lat,
            'lon': lon,
            'distance_km': float(distance_km(*requested, lat, lon)),
            'orog': float(ds.attrs['orog']) if 'orog' in ds.attrs else None,
        }
    ]


# endregion
