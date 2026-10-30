"""This module contains the barra2 download function(s)."""

import calendar
import csv
import logging
import re
import sys
import time
import warnings
from datetime import datetime, timedelta
from multiprocessing import cpu_count
from multiprocessing.pool import ThreadPool
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import numpy as np
import pandas as pd
import requests
import xarray as xr

from barra2_dl.globals import (
    BARRA2_DOMAINS,
    BARRA2_FIXED_FREQ,
    BARRA2_FIXED_VARS_AUTO,
    BARRA2_FREQS,
    BARRA2_GRID_SPACING,
    BARRA2_PRESETS,
    BARRA2_URL,
    BARRA2_URL_AUS11_1HR,
    BARRA2_URL_AUST04_1HR,
    BARRA2_URL_BBOX,
    BARRA2_URL_FX,
    BARRA2_URL_FX_BBOX,
    BARRA2_VAR_ALIASES,
    BARRA2_VARS,
)
from barra2_dl.mapping import LatLonBBox, bracket_index

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

__all__ = [
    'CacheMismatchError',
    'area_data_urlfilenames',
    'download_multithread',
    'download_serial',
    'point_data_urlfilenames',
    'preset_variables',
    'resolve_variable_versions',
]


# region Constants and types
type URLFilenamePair = tuple[str, str]

# deprecated pre-filled url templates -> the (domain, freq) they are filled for
_DEPRECATED_URLS = {
    BARRA2_URL_AUS11_1HR: ('AUS-11', '1hr'),
    BARRA2_URL_AUST04_1HR: ('AUST-04', '1hr'),
}

# how far a cached point's requested location may differ from the request, in degrees: NCSS writes 3 decimals
_POINT_TOLERANCE = 0.0005
_STATION_PATTERN = re.compile(r'GridPointRequestedAt\[(\d+(?:\.\d+)?)([NS])_(\d+(?:\.\d+)?)([EW])\]')
# endregion


# region Errors
class CacheMismatchError(ValueError):
    """Cached files that don't match the request, or can't be read; raised before any request is made.

    Attributes:
        problems (list[tuple[str, str]]): The (filename, reason) of each failing file.
    """

    def __init__(self, problems: list[tuple[str, str]], folder_path: str | Path) -> None:
        """Build the message listing each failing file and how to fix it."""
        self.problems = problems
        listing = '\n'.join(f'  {name}: {reason}' for name, reason in problems)
        super().__init__(
            f"Cached files don't match the request:\n{listing}\n"
            f'Rename the site (the filename prefix) or delete these files from {folder_path}, then run again.'
        )


# endregion


# region Public API
def point_data_urlfilenames(
    barra2_url: str,
    barra2_vars: list,
    latitude: float | int,
    longitude: float | int,
    start_datetime: str | datetime,
    end_datetime: str | datetime,
    fileout_prefix: str | None = None,
    fileout_type: str | None = None,
    *,
    domain: str = 'AUS-11',
    freq: str = '1hr',
    node_selection: str = 'nearest',
) -> list[URLFilenamePair]:
    """Generate a list of URLs and Filenames for downloading barra2 point data.

    Uses nearest node for each var in barra2_vars for a given time period, or with node_selection='average4' the grid
    of nodes around the site, for merge.merge_netcdf_to_dataset to average.
    List of URLs and filenames can be used to download files.
    URLs and filenames for each month between start and end datetime.
    filenames as f'{fileout_prefix}_{domain}_{freq}_{var}_{time_start[:10]}_{time_end[:10]}.{fileout_type}'
    fileout_type 'csv_file' (the default for the nearest node) downloads csv for merge_csvs_to_df; 'netcdf4' downloads
    netCDF4 (extension nc) for merge.merge_netcdf_to_dataset. Both can share a cache folder.

    Every variable is checked against the inventory BARRA2_VARS before any URL is built. Fixed (fx) fields such as
    orog and sftlf have no time axis, so each gets one request, named f'{fileout_prefix}_{domain}_fx_{var}.csv'.
    The node altitude, orog, is added automatically whenever at least one variable is requested.

    node_selection='average4' makes one small bounding-box request per variable-month around the point, sized from
    BARRA2_GRID_SPACING, only to fetch the real nodes around it. The merge averages the four that surround the point
    with inverse-distance weights and ignores the rest of the response.
    A grid can't be written as csv, so it is always netCDF4, and its filenames carry average4:
    f'{fileout_prefix}_{domain}_{freq}_average4_{var}_{time_start[:10]}_{time_end[:10]}.nc'.

    Args:
        barra2_url (str): BARRA2_URL from barra2_dl.globals. The pre-filled BARRA2_URL_AUS11_1HR and
            BARRA2_URL_AUST04_1HR still work but are deprecated; they set domain and freq themselves.
        barra2_vars (list): Use from barra2-dl.globals, a preset from preset_variables, or set explicitly.
            Aliases in BARRA2_VAR_ALIASES (ua10m, va10m) are downloaded under their server name (uas, vas).
        latitude (float |int):  Point latitude.
        longitude (float |int):  Point longitude.
        start_datetime (str | datetime): Used to define start of inclusive download period
        end_datetime (str | datetime): Used to define end of inclusive download period
        fileout_prefix (str): Optional prefix for downloaded file. E.g. location reference
        fileout_type (str | None): Download format, 'csv_file' or 'netcdf4'. Default csv_file for the nearest node and
            netcdf4 for average4.
        domain (str): BARRA2 domain, a key of BARRA2_DOMAINS. Default 'AUS-11'.
        freq (str): BARRA2 frequency available for the domain in BARRA2_FREQS. Default '1hr'.
        node_selection (str): 'nearest' (default) or 'average4'. For an area use area_data_urlfilenames.

    Returns:
        point_data_urlfilenamepair(list[URLFilenamePair])

    Raises:
        ValueError: If fileout_type is not 'csv_file' or 'netcdf4' (or is csv with average4), node_selection is not
            'nearest' or 'average4', the domain and freq are not in BARRA2_FREQS, or a variable is not available at
            that domain and freq.

    Examples:
        >>> from barra2_dl.globals import BARRA2_URL
        >>> pairs = point_data_urlfilenames(
        ...     BARRA2_URL, ['ua10m'], -33.88, 151.18, '2020-01-01', '2020-01-31', 'site',
        ...     domain='AUST-04', freq='20min',
        ... )
        >>> [name for _, name in pairs]
        ['site_AUST-04_20min_uas_20200101_20200131.csv', 'site_AUST-04_fx_orog.csv']
        >>> 'time_end=2020-01-31T23:40:00Z' in pairs[0][0]
        True
        >>> pairs = point_data_urlfilenames(
        ...     BARRA2_URL, ['ua10m'], -33.88, 151.18, '2020-01-01', '2020-01-31', 'site', node_selection='average4',
        ... )
        >>> [name for _, name in pairs]
        ['site_AUS-11_1hr_average4_uas_20200101_20200131.nc', 'site_AUS-11_fx_average4_orog.nc']
        >>> 'north=-33.77&south=-33.99&east=151.29&west=151.07' in pairs[0][0]
        True

    Todo:
        Set default fileout_prefix if not set by user
        Add option to name file_prefix using BARRA2 node if fileout_prefix is None
    """
    if node_selection not in ('nearest', 'average4'):
        raise ValueError(f'node_selection <{node_selection}> is not supported here; use nearest or average4.')
    fileout_type = _resolve_fileout_type(fileout_type, node_selection)
    domain, freq = _resolve_domain_freq(barra2_url, domain, freq)
    if node_selection == 'nearest':
        return _build_pairs(
            (barra2_url, BARRA2_URL_FX),
            {'latitude': latitude, 'longitude': longitude},
            (barra2_vars, domain, freq, '', fileout_type),
            (start_datetime, end_datetime, fileout_prefix),
        )
    spacing = BARRA2_GRID_SPACING[domain]
    box = {
        'north': round(float(latitude) + spacing, 6),
        'south': round(float(latitude) - spacing, 6),
        'east': round(float(longitude) + spacing, 6),
        'west': round(float(longitude) - spacing, 6),
    }
    return _build_pairs(
        (BARRA2_URL_BBOX, BARRA2_URL_FX_BBOX),
        box,
        (barra2_vars, domain, freq, 'average4', fileout_type),
        (start_datetime, end_datetime, fileout_prefix),
    )


def area_data_urlfilenames(
    bbox: LatLonBBox,
    barra2_vars: list,
    start_datetime: str | datetime,
    end_datetime: str | datetime,
    fileout_prefix: str | None = None,
    fileout_type: str = 'netcdf4',
    *,
    domain: str = 'AUS-11',
    freq: str = '1hr',
) -> list[URLFilenamePair]:
    """Generate a list of URLs and Filenames for downloading barra2 data for every node in a bounding box.

    One bounding-box request per variable-month returns a (time, lat, lon) grid of real nodes; merge it with
    merge.merge_netcdf_to_dataset(..., node_selection='area'). A grid can't be written as csv, so only netcdf4 is
    supported. NCSS returns the nodes whose grid cell overlaps the box. The box is in the filename so a different area
    has its own cache files:
    f'{fileout_prefix}_{domain}_{freq}_area_n{north}_s{south}_e{east}_w{west}_{var}_{time_start[:10]}_{time_end[:10]}.nc'

    Variables are checked and fixed fields (orog added automatically) handled as in point_data_urlfilenames.

    Args:
        bbox (LatLonBBox): The area, from barra2_dl.mapping.
        barra2_vars (list): A preset from preset_variables, or set explicitly. Aliases are resolved as for points.
        start_datetime (str | datetime): Used to define start of inclusive download period
        end_datetime (str | datetime): Used to define end of inclusive download period
        fileout_prefix (str): Optional prefix for downloaded file. E.g. wind farm reference
        fileout_type (str): Download format; only 'netcdf4'.
        domain (str): BARRA2 domain, a key of BARRA2_DOMAINS. Default 'AUS-11'.
        freq (str): BARRA2 frequency available for the domain in BARRA2_FREQS. Default '1hr'.

    Returns:
        list[URLFilenamePair]

    Raises:
        ValueError: If fileout_type is not 'netcdf4', the domain and freq are not in BARRA2_FREQS, or a variable is not
            available at that domain and freq.

    Examples:
        >>> from barra2_dl.mapping import LatLonBBox, bracket_index
        >>> box = LatLonBBox(north=-23.4, south=-23.7, east=133.5, west=133.2)
        >>> pairs = area_data_urlfilenames(box, ['ua50m'], '2020-01-01', '2020-01-31', 'farm')
        >>> for _, name in pairs:
        ...     print(name)
        farm_AUS-11_1hr_area_n-23.4_s-23.7_e133.5_w133.2_ua50m_20200101_20200131.nc
        farm_AUS-11_fx_area_n-23.4_s-23.7_e133.5_w133.2_orog.nc
    """
    if fileout_type != 'netcdf4':
        raise ValueError(f'An area is a grid and can only be downloaded as netcdf4, not {fileout_type}.')
    _check_domain_freq(domain, freq)
    box = {'north': float(bbox.north), 'south': float(bbox.south), 'east': float(bbox.east), 'west': float(bbox.west)}
    tag = f'area_n{box["north"]:g}_s{box["south"]:g}_e{box["east"]:g}_w{box["west"]:g}'
    return _build_pairs(
        (BARRA2_URL_BBOX, BARRA2_URL_FX_BBOX),
        box,
        (barra2_vars, domain, freq, tag, fileout_type),
        (start_datetime, end_datetime, fileout_prefix),
    )


def preset_variables(
    preset: str,
    domain: str = 'AUS-11',
    freq: str = '1hr',
) -> list[str]:
    """Return the variables of a named preset, checked for the domain and frequency.

    Presets are defined in BARRA2_PRESETS for 1hr data on both domains. At an opt-in frequency such as AUST-04
    20min some variables may not exist; then the preset is rejected rather than downloaded in part.

    Args:
        preset (str): A key of BARRA2_PRESETS, e.g. 'wind+density' (BARRA2_PRESET_DEFAULT).
        domain (str): BARRA2 domain, a key of BARRA2_DOMAINS. Default 'AUS-11'.
        freq (str): BARRA2 frequency available for the domain in BARRA2_FREQS. Default '1hr'.

    Returns:
        list[str]: The preset's variables, ready for point_data_urlfilenames.

    Raises:
        ValueError: If the preset is unknown, the domain and freq are not supported, or the preset needs variables
            that are not available at that domain and freq.

    Examples:
        >>> preset_variables('wind', 'AUST-04', '20min')[:4]
        ['uas', 'vas', 'ua50m', 'va50m']
    """
    if preset not in BARRA2_PRESETS:
        raise ValueError(f'Unknown preset <{preset}>. Presets: {", ".join(BARRA2_PRESETS)}.')
    _check_domain_freq(domain, freq)

    available = BARRA2_VARS[(domain, freq)] | BARRA2_VARS[(domain, BARRA2_FIXED_FREQ)]
    missing = [var for var in BARRA2_PRESETS[preset] if var not in available]
    if missing:
        usable = [name for name, variables in BARRA2_PRESETS.items() if set(variables) <= available]
        message = (
            f'Preset <{preset}> needs {", ".join(missing)}, which are not available at {domain} {freq}; '
            f'they are available at 1hr. Presets available at {domain} {freq}: {", ".join(usable)}.'
        )
        logger.error(message)
        raise ValueError(message)
    return list(BARRA2_PRESETS[preset])


def resolve_variable_versions(
    barra2_vars: list,
    domain: str = 'AUS-11',
    freq: str = '1hr',
) -> dict[str, str]:
    """Look up the dataset version that 'latest' resolves to for each variable, for recording in the output.

    THREDDS serves only 'latest', but each file's attributes name the version it holds (variable_version, e.g.
    'v20240516'). One small OPeNDAP attribute request is made per variable; a variable that can't be resolved is
    recorded as 'latest' and logged. Versions differ between variables, so the result is a dict.

    Args:
        barra2_vars (list): Variables as given to point_data_urlfilenames; aliases (ua10m) are resolved to server names.
        domain (str): BARRA2 domain, a key of BARRA2_DOMAINS. Default 'AUS-11'.
        freq (str): BARRA2 frequency available for the domain in BARRA2_FREQS. Default '1hr'.

    Returns:
        dict[str, str]: The version of each variable under its server name, e.g. {'ua50m': 'v20240516'}. The node
        altitude orog is included.

    Raises:
        ValueError: If the domain and freq are not in BARRA2_FREQS.
    """
    _check_domain_freq(domain, freq)
    server_vars = list(dict.fromkeys(BARRA2_VAR_ALIASES.get(var, var) for var in barra2_vars))
    variables = list(dict.fromkeys([*server_vars, *(BARRA2_FIXED_VARS_AUTO if server_vars else [])]))
    fixed_available = BARRA2_VARS[(domain, BARRA2_FIXED_FREQ)]
    with ThreadPool(min(4, max(1, len(variables)))) as pool:
        found = pool.starmap(_lookup_version, [(var, domain, freq, var in fixed_available) for var in variables])
    return dict(zip(variables, found, strict=True))


def download_serial(
    urlfilenames: list[URLFilenamePair],
    folder_path: str | Path,
) -> None:
    """Download all files from urls in list of URLFilenamePairs and save it as folder_path/filename, using a loop.

    Args:
        urlfilenames (list[URLFilenamePair]): A list of URLFilenamePair of the files to be downloaded.
        folder_path (str | Path): The path where the file should be saved.

    Returns: None

    Raises:
        CacheMismatchError: If a file already in folder_path holds another location than the url requests, or can't be
            read. Raised before any request, with every failing file listed.

    References:
        https://opensourceoptions.com/use-python-to-download-multiple-files-or-urls-in-parallel/
        https://medium.com/towards-data-science/use-python-to-download-multiple-files-or-urls-in-parallel-1759da9d6535
    """
    _check_cache(urlfilenames, folder_path)
    # download multiple files in loop
    t0 = time.time()
    for url, filename in urlfilenames:
        _download_file(url, filename, folder_path)
    logger.info(f'Download time <{time.time() - t0}>')
    sys.stdout.write(f'Download time: <{time.time() - t0}>')
    sys.stdout.write('\n')


def download_multithread(
    urlfilenames: list[URLFilenamePair],
    folder_path: str | Path,
) -> None:
    """Download all files from urls in list of URLFilenamePairs and save it as folder_path/filename, using multithread.

    Args:
        urlfilenames (list[URLFilenamePair]): A list of URLFilenamePair of the files to be downloaded.
        folder_path (str | Path): The path where the file should be saved.

    Returns: None

    Raises:
        CacheMismatchError: If a file already in folder_path holds another location than the url requests, or can't be
            read. Raised before any request, with every failing file listed.

    References:
        https://opensourceoptions.com/use-python-to-download-multiple-files-or-urls-in-parallel/
        https://medium.com/towards-data-science/use-python-to-download-multiple-files-or-urls-in-parallel-1759da9d6535
    """
    _check_cache(urlfilenames, folder_path)
    # download multiple files in parallel
    workers = max(1, cpu_count() - 1)
    t0 = time.time()
    with ThreadPool(workers) as pool:
        pool.starmap(_download_file, [(url, filename, folder_path) for url, filename in urlfilenames])
    logger.info(f'Download time <{time.time() - t0}>')
    sys.stdout.write(f'Download time: <{time.time() - t0}>')
    sys.stdout.write('\n')


# endregion


# region Helpers
def _resolve_fileout_type(fileout_type: str | None, node_selection: str) -> str:
    """Return the download format: csv_file for the nearest node and netcdf4 for a grid, unless given; reject others."""
    grid = node_selection != 'nearest'
    fileout_type = fileout_type or ('netcdf4' if grid else 'csv_file')
    if fileout_type not in ('csv_file', 'netcdf4'):
        logger.error(f'Unsupported fileout_type: {fileout_type}')
        raise ValueError(f'{fileout_type} is currently not supported.')
    if grid and fileout_type != 'netcdf4':
        raise ValueError(f'{node_selection} downloads a grid, which can only be netcdf4, not {fileout_type}.')
    return fileout_type


def _resolve_domain_freq(barra2_url: str, domain: str, freq: str) -> tuple[str, str]:
    """Return the domain and freq, taking them from a deprecated pre-filled url template, and check them."""
    # a template without a {freq} placeholder is a deprecated pre-filled one, which fixes the domain and freq
    if '{freq}' not in barra2_url:
        warnings.warn(
            'Pre-filled BARRA2 url templates such as BARRA2_URL_AUS11_1HR are deprecated; '
            'pass BARRA2_URL with domain= and freq= instead.',
            DeprecationWarning,
            stacklevel=3,
        )
        domain, freq = _DEPRECATED_URLS.get(barra2_url, (domain, freq))
    _check_domain_freq(domain, freq)
    return domain, freq


def _build_pairs(
    templates: tuple[str, str],
    location: dict[str, float | int],
    request: tuple[list, str, str, str, str],
    period: tuple[str | datetime, str | datetime, str | None],
) -> list[URLFilenamePair]:
    """Build the (url, filename) pairs: one per variable-month, then one per fixed field.

    templates are the series and fixed-field url templates; location the fields they take for the site or box;
    request the variables, domain, freq, the filename tag for a grid ('' for a point) and the fileout_type; period the
    start, end and filename prefix.
    """
    series_template, fixed_template = templates
    barra2_vars, domain, freq, tag, fileout_type = request
    start_datetime, end_datetime, fileout_prefix = period
    fileout_ext = {'csv_file': 'csv', 'netcdf4': 'nc'}[fileout_type]
    model = BARRA2_DOMAINS[domain]
    step = BARRA2_FREQS[domain][freq]
    tag_part = f'{tag}_' if tag else ''

    # resolve aliases to server names, dropping repeats such as uas and ua10m
    server_vars = list(dict.fromkeys(BARRA2_VAR_ALIASES.get(var, var) for var in barra2_vars))

    # split the time series from the fixed fields, and reject anything the server doesn't have, before any URL
    fixed_available = BARRA2_VARS[(domain, BARRA2_FIXED_FREQ)]
    series_vars = [var for var in server_vars if var not in fixed_available]
    _check_variables(series_vars, domain, freq)
    fixed_vars = (
        list(dict.fromkeys([*BARRA2_FIXED_VARS_AUTO, *(var for var in server_vars if var in fixed_available)]))
        if server_vars
        else []
    )

    pairs: list[URLFilenamePair] = []

    # each variable is saved in a separate url, and each BARRA2 file is saved by month
    for var in series_vars:
        for date in _list_months(start_datetime, end_datetime, freq='MS'):
            # the month ends one time step before the next month
            time_end = date + timedelta(days=calendar.monthrange(date.year, date.month)[1]) - step
            url = series_template.format(
                domain=domain,
                model=model,
                freq=freq,
                var=var,
                year=date.year,
                month=date.month,
                time_start_str=date.isoformat() + 'Z',
                time_end_str=time_end.isoformat() + 'Z',
                fileout_type=fileout_type,
                **location,
            )
            # the filename includes domain and freq so different runs can share a cache folder
            pairs.append(
                (
                    url,
                    f'{fileout_prefix}_{domain}_{freq}_{tag_part}{var}'
                    f'_{date.strftime("%Y%m%d")}_{time_end.strftime("%Y%m%d")}.{fileout_ext}',
                )
            )

    # fixed fields have one file per domain, so one request each with no time range
    for var in fixed_vars:
        url = fixed_template.format(domain=domain, model=model, var=var, fileout_type=fileout_type, **location)
        pairs.append((url, f'{fileout_prefix}_{domain}_{BARRA2_FIXED_FREQ}_{tag_part}{var}.{fileout_ext}'))

    return pairs


def _check_domain_freq(domain: str, freq: str) -> None:
    """Raise ValueError if the domain and freq are not a supported combination in BARRA2_FREQS."""
    if freq not in BARRA2_FREQS.get(domain, {}):
        supported = ', '.join(f'{d} {f}' for d, freqs in BARRA2_FREQS.items() for f in freqs)
        logger.error(f'Unsupported domain and freq: {domain} {freq}')
        raise ValueError(f'{domain} {freq} is not supported. Supported: {supported}.')


def _check_variables(variables: list[str], domain: str, freq: str) -> None:
    """Raise ValueError naming any time-series variable not in the inventory for the domain and freq."""
    unknown = [var for var in variables if var not in BARRA2_VARS[(domain, freq)]]
    if not unknown:
        return
    message = f'Not available at {domain} {freq}: {", ".join(unknown)}.'
    at_hourly = [var for var in unknown if freq != '1hr' and var in BARRA2_VARS[(domain, '1hr')]]
    if at_hourly:
        message += f' Available at 1hr: {", ".join(at_hourly)}.'
    logger.error(message)
    raise ValueError(message)


def _lookup_version(var: str, domain: str, freq: str, fixed: bool) -> str:
    """Return the variable_version attribute of one variable's file (any month), or 'latest' if it can't be read."""
    template = BARRA2_URL_FX if fixed else BARRA2_URL
    url = template.split('?', 1)[0].replace('/ncss/grid/', '/dodsC/')
    url = url.format(domain=domain, model=BARRA2_DOMAINS[domain], freq=freq, var=var, year=2020, month=1) + '.das'
    try:
        response = requests.get(url, timeout=20)
    except requests.RequestException as error:
        logger.warning(f'Could not resolve the version of <{var}>: {error}')
        return 'latest'
    found = re.search(r'variable_version "([^"]+)"', response.text) if response.status_code == 200 else None
    if found is None:
        logger.warning(f'Could not resolve the version of <{var}>; recorded as latest.')
        return 'latest'
    return found.group(1)


def _list_months(
    start_datetime: str | datetime,
    end_datetime: str | datetime,
    freq: str = 'MS',
) -> list:
    """Generate a list of months between the given start and end datetime.

    This function converts the provided start and end datetime to datetime objects,
    validates them, and then generates a list of dates at the specified frequency
    between the start and end datetime. The month containing start_datetime is always
    included, so the range begins on the first day of that month.

    Args:
        start_datetime (str or datetime-like): The start datetime for generating dates.
        end_datetime (str or datetime-like): The end datetime for generating dates.
        freq (str): The frequency string representing the interval between dates.
                    Default is 'MS' (Month Start).

    Returns:
        list: A list of dates from start to end at the given frequency.

    Raises:
        ValueError: If the provided start_datetime or end_datetime are not valid datetime-like objects.
    """
    try:
        pd.to_datetime(start_datetime)
    except ValueError as error:
        raise ValueError(f'Invalid start_datetime provided: {error}') from None

    try:
        pd.to_datetime(end_datetime)
    except ValueError as error:
        raise ValueError(f'Invalid end_datetime provided: {error}') from None

    # date_range with a month-start freq skips the start month when start is mid-month, so begin on its first day
    first_of_start_month = pd.Timestamp(start_datetime).normalize().replace(day=1)
    return pd.date_range(start=first_of_start_month, end=end_datetime, freq=freq).tolist()


def _list_timestamp_range(
    dataframe: pd.DataFrame,
    timestamp_column: str,
) -> list[pd.Timestamp]:
    """Get a list containing the range between the first and last timestamp in the specified column of the DataFrame.

    Args:
        dataframe (pd.DataFrame): The DataFrame containing the timestamp column.
        timestamp_column (str): The name of the timestamp column in the DataFrame.

    Returns:
        list: A list containing the first and last timestamp.

    Raises:
        ValueError: if timestamp_column does not exist.

    Todo:
        Not implemented function for only downloading new data based on existing time range.
        Add valid csv file check for downloading files from last 3 months
    """
    if timestamp_column not in dataframe.columns:
        raise ValueError(f'Column <{timestamp_column}> does not exist in the DataFrame.')

    # Ensure the column is of datetime type
    dataframe[timestamp_column] = pd.to_datetime(dataframe[timestamp_column])

    # Sort the DataFrame by the timestamp column
    dataframe = dataframe.sort_values(by=timestamp_column)

    # Get the first and last timestamp
    first_timestamp = dataframe[timestamp_column].iloc[0]
    last_timestamp = dataframe[timestamp_column].iloc[-1]

    return [first_timestamp, last_timestamp]


def _download_file(
    url: str,
    file_name: str,
    folder_path: str | Path,
) -> None:
    """Download the file from the url and save it as folder_path/filename.

    If the downloads folder does not exist, it will be created due to the
    create_folder argument.

    Args:
        url (str): The URL of the file to be downloaded.
        file_name (str): The name to save the downloaded file.
        folder_path (str | Path): The path where the file should be saved.

    Returns: None

    Raises:
        FileNotFoundError: If folder does not exist.
    """
    folder = Path(folder_path)
    folder_file = folder / file_name

    # Check if the folder exists
    if not folder.exists():
        logger.error(f'{folder_path} does not exist.')
        raise FileNotFoundError(f'The folder {folder_path} does not exist. Create folder first.')

    # Check if the file already exists else download the url to the file
    if folder_file.exists():
        _report(f'<{file_name}> already exists in the folder <{folder_path}>. File not downloaded.')
        return
    response = requests.get(url, timeout=20)
    # a failed status or an empty body is not a file: write nothing, so the next run asks for it again
    if response.status_code != 200:
        _report(f'<{file_name}> Failed to download. Status code: {response.status_code}')
    elif not response.content:
        _report(f'<{file_name}> Failed to download. The response was empty.')
    else:
        # the final name only ever holds a complete response: write beside it, then rename
        part_file = folder / f'{file_name}.part'
        part_file.write_bytes(response.content)
        part_file.replace(folder_file)
        _report(f'<{file_name}> downloaded to <{folder_path}>')


def _report(message: str) -> None:
    """Log a progress message and write it to stdout, the dual pattern the modules share."""
    logger.info(message)
    sys.stdout.write(f'{message}\n')


def _check_cache(urlfilenames: list[URLFilenamePair], folder_path: str | Path) -> None:
    """Raise CacheMismatchError, before any request, if a cached file doesn't match its url or can't be read."""
    folder = Path(folder_path)
    problems: list[tuple[str, str]] = []
    for url, filename in urlfilenames:
        if (folder / filename).is_file() and (problem := _cached_file_problem(folder / filename, url)):
            problems.append((filename, problem))
            logger.error(f'<{filename}> {problem}')
            sys.stdout.write(f'<{filename}> {problem}\n')
    if problems:
        raise CacheMismatchError(problems, folder_path)


def _cached_file_problem(path: Path, url: str) -> str | None:
    """Return why the cached file doesn't match the request in url, or None if it does.

    The request is the location in the url query: a point (latitude, longitude) or a box (north, south, east, west).
    A url with neither isn't a BARRA2 request and isn't checked.
    """
    query = {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}
    try:
        if {'latitude', 'longitude'} <= query.keys():
            requested = (float(query['latitude']), float(query['longitude']))
            holds = _csv_point(path) if query.get('accept') == 'csv_file' else _netcdf_point(path)
            return _point_problem(holds, requested)
        if {'north', 'south', 'east', 'west'} <= query.keys():
            box = {key: float(query[key]) for key in ('north', 'south', 'east', 'west')}
            with xr.open_dataset(path) as ds:
                return _grid_problem(ds, box, '_average4_' in path.name)
    except (OSError, ValueError, KeyError, IndexError, csv.Error):
        return "can't be read"
    return None


def _csv_point(path: Path) -> tuple[float, float]:
    """Return the requested (lat, lon) in the station column of a point csv, reading only its first two lines."""
    with path.open(newline='', encoding='utf-8') as file:
        reader = csv.reader(file)
        header, first_row = next(reader, []), next(reader, [])
    return _parse_station(first_row[header.index('station')])


def _netcdf_point(path: Path) -> tuple[float, float]:
    """Return the requested (lat, lon) in station_description of a point netCDF."""
    with xr.open_dataset(path) as ds:
        value = ds['station_description'].values.flat[0]
    return _parse_station(value.decode() if isinstance(value, bytes) else str(value))


def _parse_station(station: str) -> tuple[float, float]:
    """Return (lat, lon) from 'GridPointRequestedAt[23.550S_133.400E]', south and west negative."""
    found = _STATION_PATTERN.fullmatch(station)
    if found is None:
        raise ValueError(f'No requested location in <{station}>.')
    lat, lat_hemisphere, lon, lon_hemisphere = found.groups()
    return float(lat) * (-1 if lat_hemisphere == 'S' else 1), float(lon) * (-1 if lon_hemisphere == 'W' else 1)


def _point_problem(holds: tuple[float, float], requested: tuple[float, float]) -> str | None:
    """Return the mismatch of a cached point's requested location, or None within _POINT_TOLERANCE."""
    # longitudes are compared on -180 to 180, since AUS-11 reaches 207.39 E
    wrap = [(lon + 180) % 360 - 180 for lon in (holds[1], requested[1])]
    lon_difference = abs((wrap[0] - wrap[1] + 180) % 360 - 180)
    if abs(holds[0] - requested[0]) <= _POINT_TOLERANCE and lon_difference <= _POINT_TOLERANCE:
        return None
    return f'holds {holds[0]:.3f}, {holds[1]:.3f}; requested {requested[0]:.3f}, {requested[1]:.3f}'


def _grid_problem(ds: xr.Dataset, box: dict[str, float], average4: bool) -> str | None:
    """Return why a cached grid doesn't serve the box, or None. average4 serves the box centre, an area the box."""
    if average4:
        centre = ((box['north'] + box['south']) / 2, (box['east'] + box['west']) / 2)
        try:
            bracket_index(np.sort(ds['lat'].values), centre[0])
            bracket_index(np.sort(ds['lon'].values), centre[1])
        except ValueError:
            return f"its nodes don't surround {centre[0]:.3f}, {centre[1]:.3f}"
        return None
    covers = (
        ds.attrs['geospatial_lat_min'] <= box['south']
        and ds.attrs['geospatial_lat_max'] >= box['north']
        and ds.attrs['geospatial_lon_min'] <= box['west']
        and ds.attrs['geospatial_lon_max'] >= box['east']
    )
    return None if covers else "doesn't cover the box"


# endregion
