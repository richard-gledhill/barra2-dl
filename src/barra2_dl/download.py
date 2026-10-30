"""This module contains the barra2 download function(s)."""

import calendar
import logging
import sys
import time
import warnings
from datetime import datetime, timedelta
from multiprocessing import cpu_count
from multiprocessing.pool import ThreadPool
from pathlib import Path

import pandas as pd
import requests

from barra2_dl.globals import (
    BARRA2_DOMAINS,
    BARRA2_FIXED_FREQ,
    BARRA2_FIXED_VARS_AUTO,
    BARRA2_FREQS,
    BARRA2_PRESETS,
    BARRA2_URL_AUS11_1HR,
    BARRA2_URL_AUST04_1HR,
    BARRA2_URL_FX,
    BARRA2_VAR_ALIASES,
    BARRA2_VARS,
)

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

__all__ = [
    'download_multithread',
    'download_serial',
    'point_data_urlfilenames',
    'preset_variables',
]


# region Constants and types
type URLFilenamePair = tuple[str, str]

# deprecated pre-filled url templates -> the (domain, freq) they are filled for
_DEPRECATED_URLS = {
    BARRA2_URL_AUS11_1HR: ('AUS-11', '1hr'),
    BARRA2_URL_AUST04_1HR: ('AUST-04', '1hr'),
}
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
    fileout_type: str = 'csv_file',
    *,
    domain: str = 'AUS-11',
    freq: str = '1hr',
) -> list[URLFilenamePair]:
    """Generate a list of URLs and Filenames for downloading barra2 point data.

    Uses nearest node for each var in barra2_vars for a given time period.
    List of URLs and filenames can be used to download files.
    URLs and filenames for each month between start and end datetime.
    filenames as f'{fileout_prefix}_{domain}_{freq}_{var}_{time_start[:10]}_{time_end[:10]}.{fileout_type}'
    Currently limited to csv file download only.

    Every variable is checked against the inventory BARRA2_VARS before any URL is built. Fixed (fx) fields such as
    orog and sftlf have no time axis, so each gets one request, named f'{fileout_prefix}_{domain}_fx_{var}.csv'.
    The node altitude, orog, is added automatically whenever at least one variable is requested.

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
        fileout_type (str): Output file option, 'csv_file'
        domain (str): BARRA2 domain, a key of BARRA2_DOMAINS. Default 'AUS-11'.
        freq (str): BARRA2 frequency available for the domain in BARRA2_FREQS. Default '1hr'.

    Returns:
        point_data_urlfilenamepair(list[URLFilenamePair])

    Raises:
        ValueError: If not csv file set for export, the domain and freq are not in BARRA2_FREQS, or a variable is not
            available at that domain and freq.

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

    Todo:
        Add additional output types
        Implement grid netCDF download
        Set default fileout_prefix if not set by user
        Add option to name file_prefix using BARRA2 node if fileout_prefix is None
    """
    # Set file extension based on fileout_type
    match fileout_type:
        case 'csv_file':
            fileout_ext = 'csv'
        case _:
            logger.error(f'Unsupported fileout_type: {fileout_type}')
            raise ValueError(f'{fileout_type} is currently not supported.')

    # a template without a {freq} placeholder is a deprecated pre-filled one, which fixes the domain and freq
    if '{freq}' not in barra2_url:
        warnings.warn(
            'Pre-filled BARRA2 url templates such as BARRA2_URL_AUS11_1HR are deprecated; '
            'pass BARRA2_URL with domain= and freq= instead.',
            DeprecationWarning,
            stacklevel=2,
        )
        domain, freq = _DEPRECATED_URLS.get(barra2_url, (domain, freq))

    _check_domain_freq(domain, freq)
    model = BARRA2_DOMAINS[domain]
    step = BARRA2_FREQS[domain][freq]

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

    # create empty list for url and filename
    point_data_urlfilenamepair = []

    # loop through each variable requested for download as each variable is saved in a separate url
    for var in series_vars:
        # loop through each month as each BARRA2 file is saved by month todo check index enumerate addition works
        for date in _list_months(start_datetime, end_datetime, freq='MS'):
            year = date.year
            month = date.month
            time_start = date
            time_start_str = date.isoformat() + 'Z'
            # Get the number of days in the current month; the month ends one time step before the next month
            days_in_month = calendar.monthrange(year, month)[1]
            time_end = date + timedelta(days=days_in_month) - step
            time_end_str = time_end.isoformat() + 'Z'

            # update thredds_base_url and set as url for request
            url = barra2_url.format(
                domain=domain,
                model=model,
                freq=freq,
                var=var,
                year=year,
                month=month,
                latitude=latitude,
                longitude=longitude,
                time_start_str=time_start_str,
                time_end_str=time_end_str,
                fileout_type=fileout_type,
            )

            # set fileout_name, including domain and freq so different runs can share a cache folder
            fileout_name = (
                f'{fileout_prefix}_{domain}_{freq}_{var}'
                f'_{time_start.strftime("%Y%m%d")}_{time_end.strftime("%Y%m%d")}.{fileout_ext}'
            )
            # append url and filename as tuple
            point_data_urlfilenamepair.append((url, fileout_name))

    # fixed fields have one file per domain, so one request each with no time range
    for var in fixed_vars:
        url = BARRA2_URL_FX.format(
            domain=domain,
            model=model,
            var=var,
            latitude=latitude,
            longitude=longitude,
            fileout_type=fileout_type,
        )
        point_data_urlfilenamepair.append((url, f'{fileout_prefix}_{domain}_{BARRA2_FIXED_FREQ}_{var}.{fileout_ext}'))

    return point_data_urlfilenamepair


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


def download_serial(
    urlfilenames: list[URLFilenamePair],
    folder_path: str | Path,
) -> None:
    """Download all files from urls in list of URLFilenamePairs and save it as folder_path/filename, using a loop.

    Args:
        urlfilenames (list[URLFilenamePair]): A list of URLFilenamePair of the files to be downloaded.
        folder_path (str | Path): The path where the file should be saved.

    Returns: None

    Raises: None

    References:
        https://opensourceoptions.com/use-python-to-download-multiple-files-or-urls-in-parallel/
        https://medium.com/towards-data-science/use-python-to-download-multiple-files-or-urls-in-parallel-1759da9d6535
    """
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

    Raises: None

    References:
        https://opensourceoptions.com/use-python-to-download-multiple-files-or-urls-in-parallel/
        https://medium.com/towards-data-science/use-python-to-download-multiple-files-or-urls-in-parallel-1759da9d6535
    """
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
        logger.info(f'<{file_name}> already exists in the <{folder_path}>. File not downloaded.')
        sys.stdout.write(f'<{file_name}> already exists in the folder <{folder_path}>. File not downloaded.')
        sys.stdout.write('\n')
    else:
        response = requests.get(url, timeout=20)
        # check file is not empty or contains server error 'FileNotFound: No such file or directory'
        # Check if the request was successful
        if response.status_code == 200:
            # write content to folder_file
            folder_file.write_bytes(response.content)
            logger.info(f'<{file_name}> downloaded to <{folder_path}>')
            sys.stdout.write(f'<{file_name}> downloaded to <{folder_path}>')
            sys.stdout.write('\n')
        else:
            logger.info(f'<{file_name}> Failed to download. Status code: {response.status_code}')
            sys.stdout.write(f'<{file_name}> Failed to download. Status code: {response.status_code}')
            sys.stdout.write('\n')


# endregion
