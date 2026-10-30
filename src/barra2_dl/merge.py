"""This module contains the barra2 merge function(s)."""

import logging
import re
import sys
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from barra2_dl.convert import wind_components_to_direction, wind_components_to_speed
from barra2_dl.globals import (
    BARRA2_DOMAINS,
    BARRA2_FIXED_FREQ,
    BARRA2_FREQS,
    BARRA2_INDEX,
    BARRA2_VAR_ALIASES,
    BARRA2_VAR_INFO,
    BARRA2_WIND_VARS,
)
from barra2_dl.mapping import LatLonPoint

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

__all__ = [
    'merge_csvs_to_df',
    'merge_netcdf_to_dataset',
    'read_fixed_fields',
    'to_dataset',
]


# region Constants and types
# CF standard names of the variables that have one. Air temperature at a height (ta50m) shares tas's name.
_STANDARD_NAMES = {
    'ua': 'eastward_wind',
    'va': 'northward_wind',
    'wind_speed': 'wind_speed',
    'wind_from_direction': 'wind_from_direction',
    'tas': 'air_temperature',
    'ps': 'surface_air_pressure',
    'hurs': 'relative_humidity',
    'pr': 'precipitation_flux',
    'rsds': 'surface_downwelling_shortwave_flux_in_air',
    'wsgsmax': 'wind_speed_of_gust',
}
_AIR_TEMPERATURE_AT_HEIGHT = re.compile(r'ta\d+m')
_TIME_UNITS = 'seconds since 1970-01-01 00:00:00'
_UNIT_SUFFIX = re.compile(r'\[unit="(.*)"\]$')

# written to every dataset
_LICENSE = 'CC BY 4.0, Bureau of Meteorology'
_REFERENCES = 'http://www.bom.gov.au/research/publications/researchreports/BRR-067.pdf'
# endregion


# region Public API


def merge_csvs_to_df(
    filein_folder: str,
    filename_pattern: str = '*.csv',
    index_for_join: str | list[str] | None = None,
) -> pd.DataFrame:
    """Function to merge csv files iteratively from a folder based on filename wildcard.

    Uses outer join based on index_for_join. If filename wildcard is omitted all csv files in the folder will be merged.
    Fixed-field files (with '_fx_' in the name, such as the automatic orog download) are skipped, because they hold one
    value with a dummy 1970 time rather than a time series; read them with read_fixed_fields.

    Args:
        filein_folder (str): Folder
        filename_pattern (str): Filename matching pattern. Use if multiple location files are in same folder.
        index_for_join (str | list[str]): Pandas <on> parameter.

    Returns:
        DataFrame: A DataFrame with the merged csvs.

    Todo:
        Add csv check for filename_prefix
        Add pandas kwargs
    """
    # instantiate dataframe for merging csv files
    df_merged = pd.DataFrame()

    for file in Path(filein_folder).glob(filename_pattern):
        if f'_{BARRA2_FIXED_FREQ}_' in file.name:
            logger.info(f'Skipped fixed-field file: {file}')
            continue
        if df_merged.empty:
            # read csv file without indexing to retain time as column for join
            df_merged = pd.read_csv(file)
        else:
            # read next file into new df
            df_add = pd.read_csv(file)
            df_merged = pd.merge(df_merged, df_add, how='outer', on=index_for_join)
            df_merged = _merge_suffix_columns(df_merged)
            logger.info(f'Merged file: {file}')
            sys.stdout.write(f'Merged file: {file}')
            sys.stdout.write('\n')

    return df_merged


def read_fixed_fields(
    filein_folder: str,
    filename_pattern: str = f'*_{BARRA2_FIXED_FREQ}_*.csv',
) -> dict[str, float]:
    """Read the fixed (time-invariant) fields, such as the node altitude orog, from downloaded fx files.

    Reads csv files, or netCDF files (extension nc) when the pattern matches those.

    Args:
        filein_folder (str): Folder holding the downloaded files, e.g. the cache folder.
        filename_pattern (str): Filename matching pattern for the fx files, e.g. f'{prefix}_AUS-11_fx_*.csv' or
            f'{prefix}_AUS-11_fx_*.nc'.

    Returns:
        dict[str, float]: Each field's column header and value, e.g. {'orog[unit="m"]': 33.05}.
    """
    fields: dict[str, float] = {}
    for file in sorted(Path(filein_folder).glob(filename_pattern)):
        if file.suffix == '.nc':
            name, unit, series, _ = _read_point_file(file)
            fields[f'{name}[unit="{unit}"]'] = float(series.iloc[0])
            continue
        row = pd.read_csv(file).iloc[0]
        fields |= {str(column): float(row[column]) for column in row.index if column not in BARRA2_INDEX}
    return fields


def to_dataset(
    df: pd.DataFrame,
    *,
    domain: str,
    freq: str,
    requested: LatLonPoint,
    orog: float | None = None,
    node_selection: str = 'nearest',
    versions: dict[str, str] | None = None,
) -> xr.Dataset:
    """Convert a merged (and optionally converted) point DataFrame to a CF-style xarray Dataset.

    This is the bridge from the csv route. To skip the DataFrame, download with fileout_type='netcdf4' and use
    merge_netcdf_to_dataset, which gives the same layout.

    Wind components, speed and direction go on a height dimension; other variables keep their BARRA2 names and units.
    Timestamps are kept exactly as served. Variables averaged over the time step (cell methods 'time: mean', such as pr
    and rsds, stamped mid-step) go on their own time_mean coordinate with time_bnds; the rest use time.

    Args:
        df (DataFrame): From merge_csvs_to_df, optionally after convert_wind_components and convert_units.
        domain (str): BARRA2 domain the data came from, a key of BARRA2_DOMAINS.
        freq (str): BARRA2 frequency the data came from.
        requested (LatLonPoint): The site that was requested; the node coordinates come from the frame.
        orog (float | None): Node altitude in m, e.g. from read_fixed_fields. Written as an attribute.
        node_selection (str): How the node was chosen, recorded as an attribute. Default 'nearest'.
        versions (dict[str, str] | None): Dataset version of each variable, e.g. from
            download.resolve_variable_versions. Recorded as attributes; 'latest' where unknown.

    Returns:
        xr.Dataset: Ready for to_netcdf().

    Raises:
        ValueError: If the frame has no time column or no rows, or holds more than one node.

    Examples:
        >>> frame = pd.DataFrame({
        ...     'time': ['2020-01-01T00:00:00Z'], 'station': [0], 'latitude[unit="degrees_north"]': [-33.9],
        ...     'longitude[unit="degrees_east"]': [151.2], 'tas[unit="K"]': [293.0],
        ... })
        >>> ds = to_dataset(frame, domain='AUS-11', freq='1hr', requested=LatLonPoint(-33.88, 151.18))
        >>> float(ds['tas'].values[0]), ds['tas'].attrs['units']
        (293.0, 'K')
    """
    if 'time' not in df.columns or df.empty:
        raise ValueError('The frame needs a time column and at least one row.')
    position_columns = [column for column in BARRA2_INDEX if column.startswith(('latitude', 'longitude'))]
    nodes = df[position_columns].drop_duplicates()
    if len(nodes) != 1:
        raise ValueError(f'Expected one node in the frame, found {len(nodes)}.')
    lat, lon = nodes.to_numpy(dtype=float)[0]

    times = pd.DatetimeIndex(pd.to_datetime(df['time'], utc=True).dt.tz_localize(None))
    series: dict[str, pd.Series] = {}
    units: dict[str, str] = {}
    for column in (c for c in df.columns if c not in BARRA2_INDEX):
        name = _variable_name(column)
        series[name] = _clean(pd.Series(df[column].to_numpy(dtype=float), index=times))
        units[name] = _unit(column)
    return _build_dataset(
        series, units, (float(lat), float(lon)), (domain, freq), requested, orog, node_selection, versions
    )


def merge_netcdf_to_dataset(
    filein_folder: str,
    filename_pattern: str = '*.nc',
    *,
    domain: str,
    freq: str,
    requested: LatLonPoint,
    orog: float | None = None,
    node_selection: str = 'nearest',
    versions: dict[str, str] | None = None,
) -> xr.Dataset:
    """Merge downloaded netCDF4 point files straight into a CF-style xarray Dataset, without a DataFrame.

    The files come from point_data_urlfilenames(..., fileout_type='netcdf4'). Each variable's months are joined in time,
    the variables are merged, and wind speed and direction are derived from the ua/va pairs present. The result has the
    same layout as to_dataset, whose docstring describes it. Fixed-field files (with '_fx_' in the name) are skipped;
    read the node altitude with read_fixed_fields and pass it as orog.

    Args:
        filein_folder (str): Folder holding the downloaded files, e.g. the cache folder.
        filename_pattern (str): Filename matching pattern, e.g. f'{prefix}_AUS-11_1hr_*.nc'.
        domain (str): BARRA2 domain the data came from, a key of BARRA2_DOMAINS.
        freq (str): BARRA2 frequency the data came from.
        requested (LatLonPoint): The site that was requested.
        orog (float | None): Node altitude in m. Written as an attribute.
        node_selection (str): How the node was chosen, recorded as an attribute. Default 'nearest'.
        versions (dict[str, str] | None): Dataset version of each variable, e.g. from
            download.resolve_variable_versions. Recorded as attributes; 'latest' where unknown.

    Returns:
        xr.Dataset: Ready for to_netcdf().

    Raises:
        ValueError: If no file matches, a file isn't a single-variable point file, or the files hold more than one node.
    """
    files = [
        file for file in sorted(Path(filein_folder).glob(filename_pattern)) if f'_{BARRA2_FIXED_FREQ}_' not in file.name
    ]
    if not files:
        raise ValueError(f'No netCDF files matching <{filename_pattern}> in <{filein_folder}>.')

    pieces: dict[str, list[pd.Series]] = {}
    units: dict[str, str] = {}
    nodes: set[tuple[float, float]] = set()
    for file in files:
        name, unit, piece, node = _read_point_file(file)
        pieces.setdefault(name, []).append(piece)
        units[name] = unit
        nodes.add(node)
    if len(nodes) != 1:
        raise ValueError(f'Expected one node in the files, found {len(nodes)}.')

    series = {name: _clean(pd.concat(parts)) for name, parts in pieces.items()}
    for name, derived in _derive_wind(series).items():
        series[name], units[name] = derived
    return _build_dataset(series, units, nodes.pop(), (domain, freq), requested, orog, node_selection, versions)


# endregion


# region Helpers
def _clean(series: pd.Series) -> pd.Series:
    """Return the series sorted by time, without missing values or repeated times."""
    series = series.dropna().sort_index()
    return series[~series.index.duplicated()]


def _read_point_file(path: Path) -> tuple[str, str, pd.Series, tuple[float, float]]:
    """Read one NCSS netCDF4 point file: its variable name, unit, series on time, and (lat, lon) node.

    The file is a CF discrete-sampling-geometry ragged array (dims station and obs); the one data variable on obs is
    taken and indexed by its time.
    """
    with xr.open_dataset(path, engine='h5netcdf') as ds:
        names = [name for name in ds.data_vars if ds[name].dims == ('obs',) and name != 'stationIndex']
        if len(names) != 1:
            raise ValueError(f'Expected one data variable in <{path.name}>, found {len(names)}.')
        name = str(names[0])
        values = ds[name].to_numpy().astype(float)
        times = pd.DatetimeIndex(ds['time'].to_numpy())
        node = (float(ds['latitude'].to_numpy()[0]), float(ds['longitude'].to_numpy()[0]))
        unit = str(ds[name].attrs.get('units', '1'))
    return name, unit, pd.Series(values, index=times), node


def _derive_wind(series: dict[str, pd.Series]) -> dict[str, tuple[pd.Series, str]]:
    """Derive v<height>m and v<height>m_phi_met for every ua/va pair present, as {name: (series, unit)}."""
    derived: dict[str, tuple[pd.Series, str]] = {}
    for ua, va, height in BARRA2_WIND_VARS:
        ua_name = ua if ua in series else f'ua{height}m'
        va_name = va if va in series else f'va{height}m'
        if ua_name in series and va_name in series:
            both = pd.concat([series[ua_name], series[va_name]], axis=1, join='inner')
            ua_values, va_values = both.iloc[:, 0].tolist(), both.iloc[:, 1].tolist()
            derived[f'v{height}m'] = (
                pd.Series(wind_components_to_speed(ua_values, va_values), index=both.index),
                'm s-1',
            )
            derived[f'v{height}m_phi_met'] = (
                pd.Series(wind_components_to_direction(ua_values, va_values), index=both.index),
                'degrees',
            )
    return derived


def _build_dataset(
    series: dict[str, pd.Series],
    units: dict[str, str],
    node: tuple[float, float],
    domain_freq: tuple[str, str],
    requested: LatLonPoint,
    orog: float | None,
    node_selection: str,
    versions: dict[str, str] | None,
) -> xr.Dataset:
    """Assemble the Dataset from per-variable series (indexed by their own timestamps), their units and the node."""
    domain, freq = domain_freq
    versions = _with_aliases(versions or {})
    stacked, plain = _group_by_height(list(series))
    mean_names = [name for name in plain if _is_mean(domain, freq, name)]
    series_names = [name for name in series if name not in mean_names]

    times = _union_times([series[name] for name in series_names])
    ds = xr.Dataset(coords={'time': times})
    ds['time'].attrs = {'standard_name': 'time', 'long_name': 'time as served, UTC'}
    if stacked:
        ds = _add_height_variables(ds, series, units, stacked, versions)
    for name in plain:
        if name not in mean_names:
            attrs = _variable_attrs(domain, freq, name, units[name], versions)
            ds[name] = ('time', series[name].reindex(times).to_numpy(), attrs)
    if mean_names:
        ds = _add_mean_variables(ds, series, units, mean_names, domain_freq, versions)

    ds = ds.assign_coords(
        lat=node[0], lon=node[1], requested_lat=float(requested.lat), requested_lon=float(requested.lon)
    )
    ds['lat'].attrs = {'units': 'degrees_north', 'standard_name': 'latitude'}
    ds['lon'].attrs = {'units': 'degrees_east', 'standard_name': 'longitude'}

    # one explicit unit for every time axis, so time_mean and time_bnds are encoded alike (CF) and exactly
    for name in ('time', 'time_mean', 'time_bnds'):
        if name in ds.variables:
            ds[name].encoding['units'] = _TIME_UNITS
    ds.attrs = _global_attrs(domain, freq, node_selection, orog, sorted(set(versions.values())))
    return ds


def _with_aliases(versions: dict[str, str]) -> dict[str, str]:
    """Return the versions with each alias (ua10m) given the version of its server variable (uas)."""
    return versions | {alias: versions[server] for alias, server in BARRA2_VAR_ALIASES.items() if server in versions}


def _union_times(series: list[pd.Series]) -> pd.DatetimeIndex:
    """Return the sorted union of the series' timestamps (empty if there are none)."""
    return pd.DatetimeIndex(sorted(set().union(*(one.index for one in series))))


def _add_height_variables(
    ds: xr.Dataset,
    series: dict[str, pd.Series],
    units: dict[str, str],
    stacked: dict[str, dict[int, str]],
    versions: dict[str, str],
) -> xr.Dataset:
    """Add the height coordinate and one (time, height) variable per quantity; a height a quantity lacks is NaN."""
    times = ds['time'].to_numpy()
    heights = sorted({height for names in stacked.values() for height in names})
    ds = ds.assign_coords(height=('height', np.array(heights, dtype=float)))
    ds['height'].attrs = {'units': 'm', 'positive': 'up', 'long_name': 'height above ground'}
    for quantity, names in stacked.items():
        values = np.column_stack(
            [
                series[names[height]].reindex(times).to_numpy() if height in names else np.full(len(times), np.nan)
                for height in heights
            ]
        )
        attrs = {
            'units': units[names[min(names)]],
            'standard_name': _STANDARD_NAMES[quantity],
            'barra2_name': ', '.join(names[height] for height in sorted(names)),
        }
        found = sorted({versions[name] for name in names.values() if name in versions})
        if found:
            attrs['barra2_version'] = ', '.join(found)
        ds[quantity] = (('time', 'height'), values, attrs)
    return ds


def _group_by_height(names: list[str]) -> tuple[dict[str, dict[int, str]], list[str]]:
    """Split names into height-stacked quantities ({quantity: {height: name}}) and the rest."""
    stacked: dict[str, dict[int, str]] = {}
    plain: list[str] = []
    for name in names:
        quantity, height = _split_height(name)
        if quantity is None:
            plain.append(name)
        else:
            stacked.setdefault(quantity, {})[height] = name
    return stacked, plain


def _add_mean_variables(
    ds: xr.Dataset,
    series: dict[str, pd.Series],
    units: dict[str, str],
    mean_names: list[str],
    domain_freq: tuple[str, str],
    versions: dict[str, str],
) -> xr.Dataset:
    """Add the time_mean coordinate, its bounds (one step wide, centred on the stamp) and the mean variables."""
    domain, freq = domain_freq
    half_step = BARRA2_FREQS[domain][freq] / 2
    mean_times = _union_times([series[name] for name in mean_names])
    ds = ds.assign_coords(time_mean=('time_mean', mean_times))
    ds['time_mean'].attrs = {'standard_name': 'time', 'bounds': 'time_bnds', 'long_name': 'middle of the mean period'}
    ds['time_bnds'] = (('time_mean', 'bnds'), np.column_stack([mean_times - half_step, mean_times + half_step]))
    for name in mean_names:
        attrs = _variable_attrs(domain, freq, name, units[name], versions)
        ds[name] = ('time_mean', series[name].reindex(mean_times).to_numpy(), attrs)
    return ds


def _global_attrs(
    domain: str, freq: str, node_selection: str, orog: float | None, versions: list[str]
) -> dict[str, str | float]:
    """Dataset attributes: CF conventions, provenance, licence and the node altitude."""
    today = datetime.now(UTC).date().isoformat()
    attrs: dict[str, str | float] = {
        'Conventions': 'CF-1.10',
        'source': f'BARRA2 {BARRA2_DOMAINS[domain]} reanalysis, Bureau of Meteorology, via NCI THREDDS',
        'domain': domain,
        'freq': freq,
        'node_selection': node_selection,
        'barra2_version': ', '.join(versions) or 'latest',
        'downloaded': today,
        'history': f'{today}: created by barra2-dl {version("barra2-dl")}',
        'license': _LICENSE,
        'references': _REFERENCES,
    }
    if orog is not None:
        attrs |= {'orog': float(orog), 'orog_units': 'm'}
    return attrs


def _variable_name(column: str) -> str:
    """Return the variable name of a column such as 'ua50m[unit="m s-1"]'."""
    return str(column).split('[', 1)[0]


def _unit(column: str) -> str:
    """Return the unit of a column such as 'ua50m[unit="m s-1"]', or '1' if it has none."""
    match = _UNIT_SUFFIX.search(str(column))
    return match.group(1) if match else '1'


def _is_mean(domain: str, freq: str, name: str) -> bool:
    """Return True if the inventory lists the variable as a time mean."""
    return 'time: mean' in BARRA2_VAR_INFO.get((domain, freq, name), {}).get('cell_methods', '')


def _split_height(name: str) -> tuple[str | None, int]:
    """Split a name into its height-stacked quantity and height, or (None, 0) if it is not stacked.

    Examples:
        >>> _split_height('ua50m'), _split_height('uas'), _split_height('v100m_phi_met'), _split_height('tas')
        (('ua', 50), ('ua', 10), ('wind_from_direction', 100), (None, 0))
    """
    for ua, va, height in BARRA2_WIND_VARS:
        if name in (ua, f'ua{height}m'):
            return 'ua', height
        if name in (va, f'va{height}m'):
            return 'va', height
    if speed := re.fullmatch(r'v(\d+)m', name):
        return 'wind_speed', int(speed.group(1))
    if direction := re.fullmatch(r'v(\d+)m_phi_met', name):
        return 'wind_from_direction', int(direction.group(1))
    return None, 0


def _variable_attrs(domain: str, freq: str, name: str, unit: str, versions: dict[str, str]) -> dict[str, str]:
    """Attributes of a variable kept under its BARRA2 name: units, names, the inventory's cell methods and version."""
    info = BARRA2_VAR_INFO.get((domain, freq, name), {})
    attrs = {'units': unit, 'barra2_name': name}
    if info.get('long_name'):
        attrs['long_name'] = info['long_name']
    if info.get('cell_methods'):
        attrs['cell_methods'] = info['cell_methods']
    if name in _STANDARD_NAMES:
        attrs['standard_name'] = _STANDARD_NAMES[name]
    elif _AIR_TEMPERATURE_AT_HEIGHT.fullmatch(name):
        attrs['standard_name'] = 'air_temperature'
    if name in versions:
        attrs['barra2_version'] = versions[name]
    return attrs


def _merge_suffix_columns(
    df: pd.DataFrame,
    suffix_x: str = '_x',
    suffix_y: str = '_y',
) -> pd.DataFrame:
    """Function to merge DataFrame columns with '_x' and '_y' suffixes.

    Args:
        df: The DataFrame that contains columns with suffixes to be merged.
        suffix_x: The suffix used in the first set of columns (default is '_x').
        suffix_y: The suffix used in the second set of columns (default is '_y').

    Returns:
        DataFrame: A DataFrame with the merged columns.
        If no suffix_x returns the original DataFrame.

    Todo:
        Add checks for multiple and mismatched suffixed columns
    """
    for column in df.columns:
        if column.endswith(suffix_x):
            base_column = column[: -len(suffix_x)]
            column_y = base_column + suffix_y
            if column_y in df.columns:
                # Create a new column without suffix and merge the values
                df[base_column] = df[column].combine_first(df[column_y])
                # Drop the old suffix columns
                df.drop([column, column_y], axis=1, inplace=True)
    return df


# endregion
