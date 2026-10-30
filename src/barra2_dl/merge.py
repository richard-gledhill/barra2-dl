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
    BARRA2_NODE_SELECTIONS,
    BARRA2_VAR_ALIASES,
    BARRA2_VAR_INFO,
    BARRA2_WIND_VARS,
)
from barra2_dl.mapping import LatLonPoint, bracket_index, distance_km, inverse_distance_weights

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

__all__ = [
    'dataset_to_frames',
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
    requested: LatLonPoint | None = None,
    orog: float | None = None,
    node_selection: str = 'nearest',
    versions: dict[str, str] | None = None,
    fixed_pattern: str | None = None,
) -> xr.Dataset:
    """Merge downloaded netCDF4 files straight into a CF-style xarray Dataset, without a DataFrame.

    The files come from point_data_urlfilenames(..., fileout_type='netcdf4') for the nearest node, from
    point_data_urlfilenames(..., node_selection='average4') for the four-node average, or from area_data_urlfilenames
    for an area. Each variable's months are joined in time, the variables are merged, and wind speed and direction are
    derived from the ua/va pairs present. Fixed-field files (with '_fx_' in the name) are skipped. The nearest node
    has the layout described in to_dataset; the others are described below.

    node_selection='average4' averages the four nodes that surround the requested point (not a boundary or area) with
    inverse-distance weights, using the hybrid
    method: wind speed is the weighted mean of each node's own speed (a scalar mean), direction comes from the
    weighted-mean ua and va (a vector mean), and the averaged ua and va are written too. The averaged speed is
    therefore not hypot(ua, va), which would be lower where the nodes' winds differ in direction. cell_methods says
    which mean each variable is. The four node series are written beside the average as <name>_node variables on a
    node dimension, with node_lat, node_lon, node_distance (km), node_weight and, if fixed_pattern is given, node_orog
    coordinates. lat and lon are the requested site.

    node_selection='area' keeps every node: lat and lon are dimensions, the variables are (time[, height], lat, lon),
    and orog, if fixed_pattern is given, is a (lat, lon) variable. There is no requested site.

    Args:
        filein_folder (str): Folder holding the downloaded files, e.g. the cache folder.
        filename_pattern (str): Filename matching pattern, e.g. f'{prefix}_AUS-11_1hr_*.nc' for the nearest node or
            f'{prefix}_AUS-11_1hr_average4_*.nc' for the four-node average.
        domain (str): BARRA2 domain the data came from, a key of BARRA2_DOMAINS.
        freq (str): BARRA2 frequency the data came from.
        requested (LatLonPoint | None): The site that was requested. Not used for an area.
        orog (float | None): Node altitude in m, for the nearest node. Written as an attribute.
        node_selection (str): 'nearest' (default), 'average4' or 'area'.
        versions (dict[str, str] | None): Dataset version of each variable, e.g. from
            download.resolve_variable_versions. Recorded as attributes; 'latest' where unknown.
        fixed_pattern (str | None): Filename pattern of the downloaded orog grid for average4 and area, e.g.
            f'{prefix}_AUS-11_fx_average4_orog.nc'.

    Returns:
        xr.Dataset: Ready for to_netcdf().

    Raises:
        ValueError: If node_selection is unknown, a site is needed and missing, no file matches, a file isn't a
            single-variable file of the right kind, the files hold more than one node, or the site is outside the grid.
    """
    if node_selection not in BARRA2_NODE_SELECTIONS:
        raise ValueError(f'node_selection <{node_selection}> must be one of {", ".join(BARRA2_NODE_SELECTIONS)}.')
    if node_selection == 'area':
        grids, units = _read_grids(_data_files(filein_folder, filename_pattern, node_selection))
        return _area_dataset(grids, units, _read_fixed_grid(filein_folder, fixed_pattern), (domain, freq), versions)
    site = _site(requested, node_selection)
    files = _data_files(filein_folder, filename_pattern, node_selection)
    if node_selection == 'nearest':
        return _nearest_dataset(files, (domain, freq), site, orog, versions)
    grids, units = _read_grids(files)
    return _average4_dataset(
        grids, units, _read_fixed_grid(filein_folder, fixed_pattern), (domain, freq), site, versions
    )


def dataset_to_frames(ds: xr.Dataset) -> dict[str, pd.DataFrame]:
    """Convert a point or four-node-average Dataset to DataFrames for csv output.

    The frames have the same columns as the csv route (BARRA2_INDEX, then e.g. ua50m[unit="m s-1"], v50m ...), with
    timestamps as served, so variables stamped at :30 get their own rows. A nearest-node Dataset gives one frame. A
    four-node average gives the average, keyed 'average4', and one frame per node, keyed node1 to node4, so each can be
    written to its own file.

    Args:
        ds (xr.Dataset): From merge_netcdf_to_dataset or to_dataset.

    Returns:
        dict[str, pd.DataFrame]: The frames by name.

    Raises:
        ValueError: If the Dataset is an area, which is a grid and doesn't fit csv.
    """
    if 'lat' in ds.dims:
        raise ValueError('An area is a grid and cannot be written as csv; write it as netCDF.')
    frames = {str(ds.attrs.get('node_selection', 'nearest')): _frame(ds, None)}
    if 'node' in ds.dims:
        frames |= {f'node{int(node) + 1}': _frame(ds, int(node)) for node in ds['node'].to_numpy()}
    return frames


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

    times = _union_times([series[name].index for name in series_names])
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

    _set_time_encoding(ds)
    ds.attrs = _global_attrs(domain, freq, node_selection, orog, sorted(set(versions.values())))
    return ds


def _with_aliases(versions: dict[str, str]) -> dict[str, str]:
    """Return the versions with each alias (ua10m) given the version of its server variable (uas)."""
    return versions | {alias: versions[server] for alias, server in BARRA2_VAR_ALIASES.items() if server in versions}


def _union_times(indexes: list[pd.Index]) -> pd.DatetimeIndex:
    """Return the sorted union of the timestamp indexes (empty if there are none)."""
    return pd.DatetimeIndex(sorted(set().union(*indexes)))


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
    mean_times = _union_times([series[name].index for name in mean_names])
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


def _site(requested: LatLonPoint | None, node_selection: str) -> LatLonPoint:
    """Return the requested site, which every node selection except area needs."""
    if requested is None:
        raise ValueError(f'requested (the site) is needed for node_selection <{node_selection}>.')
    return requested


def _data_files(folder: str, pattern: str, node_selection: str) -> list[Path]:
    """Return the files matching the pattern that belong to the node selection; raise if there are none.

    Fixed-field files are always left out. Grid files are named with average4 or area, so a loose pattern such as
    f'{prefix}_AUS-11_1hr_*.nc' can match them all and still merge only the kind asked for.
    """
    grid_tags = {'average4': '_average4_', 'area': '_area_'}
    files = []
    for file in sorted(Path(folder).glob(pattern)):
        wanted = grid_tags[node_selection] in file.name if node_selection in grid_tags else True
        other_grid = node_selection == 'nearest' and any(tag in file.name for tag in grid_tags.values())
        if wanted and not other_grid and f'_{BARRA2_FIXED_FREQ}_' not in file.name:
            files.append(file)
    if not files:
        raise ValueError(f'No {node_selection} netCDF files matching <{pattern}> in <{folder}>.')
    return files


def _nearest_dataset(
    files: list[Path],
    domain_freq: tuple[str, str],
    requested: LatLonPoint,
    orog: float | None,
    versions: dict[str, str] | None,
) -> xr.Dataset:
    """Merge NCSS point files for the nearest node into a Dataset."""
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
    _add_wind(series, units)
    return _build_dataset(series, units, nodes.pop(), domain_freq, requested, orog, 'nearest', versions)


def _add_wind(series: dict[str, pd.Series], units: dict[str, str]) -> None:
    """Add the derived wind speed and direction series, and their units, in place."""
    for name, derived in _derive_wind(series).items():
        series[name], units[name] = derived


def _read_grid_file(path: Path) -> tuple[str, str, xr.DataArray]:
    """Read one NCSS bounding-box file: its variable name, unit and (time, lat, lon) array, loaded and sorted."""
    with xr.open_dataset(path, engine='h5netcdf') as ds:
        names = [name for name in ds.data_vars if ds[name].dims == ('time', 'lat', 'lon')]
        if len(names) != 1:
            raise ValueError(f'Expected one (time, lat, lon) data variable in <{path.name}>, found {len(names)}.')
        name = str(names[0])
        array = ds[name].load().reset_coords(drop=True).astype(float).sortby('lat').sortby('lon')
        unit = str(ds[name].attrs.get('units', '1'))
    return name, unit, array.drop_attrs()


def _read_grids(files: list[Path]) -> tuple[dict[str, xr.DataArray], dict[str, str]]:
    """Read bounding-box files into one (time, lat, lon) array per variable, joining its months in time."""
    pieces: dict[str, list[xr.DataArray]] = {}
    units: dict[str, str] = {}
    for file in files:
        name, unit, array = _read_grid_file(file)
        pieces.setdefault(name, []).append(array)
        units[name] = unit
    grids = {}
    for name, parts in pieces.items():
        joined = xr.concat(parts, dim='time', join='exact').sortby('time')
        grids[name] = joined.isel(time=~joined.get_index('time').duplicated())
    return grids, units


def _read_fixed_grid(folder: str, pattern: str | None) -> xr.DataArray | None:
    """Read the orog (lat, lon) grid from the first fixed-field file matching the pattern, if there is a pattern."""
    if pattern is None:
        return None
    files = sorted(Path(folder).glob(pattern))
    if not files:
        raise ValueError(f'No fixed-field files matching <{pattern}> in <{folder}>.')
    with xr.open_dataset(files[0], engine='h5netcdf') as ds:
        names = [name for name in ds.data_vars if ds[name].dims == ('lat', 'lon')]
        if len(names) != 1:
            raise ValueError(f'Expected one (lat, lon) data variable in <{files[0].name}>, found {len(names)}.')
        return ds[names[0]].load().reset_coords(drop=True).astype(float).sortby('lat').sortby('lon').drop_attrs()


def _node_series(grids: dict[str, xr.DataArray], lat_index: int, lon_index: int) -> dict[str, pd.Series]:
    """Return the series of every variable at one grid node."""
    return {
        name: _clean(pd.Series(grid.isel(lat=lat_index, lon=lon_index).to_numpy(), index=grid.get_index('time')))
        for name, grid in grids.items()
    }


def _average_series(per_node: list[dict[str, pd.Series]], weights: np.ndarray) -> dict[str, pd.Series]:
    """Average the nodes' series with the weights, by the hybrid method.

    Speed and every other variable are weighted means of the nodes' own values (the scalar mean), including ua and va
    (the vector mean). Direction is then taken from the averaged ua and va, since averaging bearings is meaningless.
    """
    averaged: dict[str, pd.Series] = {}
    for name in per_node[0]:
        if not name.endswith('_phi_met'):
            frame = pd.concat([node[name] for node in per_node], axis=1, join='inner')
            averaged[name] = pd.Series(frame.to_numpy() @ weights, index=frame.index)
    components = {name: series for name, series in averaged.items() if _split_height(name)[0] in ('ua', 'va')}
    for name, (series, _) in _derive_wind(components).items():
        if name.endswith('_phi_met'):
            averaged[name] = series
    return averaged


def _average4_dataset(
    grids: dict[str, xr.DataArray],
    units: dict[str, str],
    fixed: xr.DataArray | None,
    domain_freq: tuple[str, str],
    requested: LatLonPoint,
    versions: dict[str, str] | None,
) -> xr.Dataset:
    """Average the four nodes around the requested site, and write the four node series beside the average."""
    template = next(iter(grids.values()))
    lats, lons = template['lat'].to_numpy(), template['lon'].to_numpy()
    lat_index, lon_index = bracket_index(lats, float(requested.lat)), bracket_index(lons, float(requested.lon))
    cells = [(a, b) for a in (lat_index, lat_index + 1) for b in (lon_index, lon_index + 1)]
    node_lat, node_lon = np.array([lats[a] for a, _ in cells]), np.array([lons[b] for _, b in cells])
    distances = distance_km(float(requested.lat), float(requested.lon), node_lat, node_lon)
    weights = inverse_distance_weights(distances)
    orogs = (
        np.array(
            [float(fixed.sel(lat=la, lon=lo, method='nearest')) for la, lo in zip(node_lat, node_lon, strict=True)]
        )
        if fixed is not None
        else None
    )

    per_node = [_node_series(grids, a, b) for a, b in cells]
    for series in per_node:
        _add_wind(series, units)
    site = (float(requested.lat), float(requested.lon))
    mean_orog = float(weights @ orogs) if orogs is not None else None
    ds = _build_dataset(
        _average_series(per_node, weights), units, site, domain_freq, requested, mean_orog, 'average4', versions
    )
    ds = _label_node_means(ds)
    node_datasets = [
        _build_dataset(
            per_node[k], units, (node_lat[k], node_lon[k]), domain_freq, requested, None, 'average4', versions
        )
        for k in range(len(cells))
    ]
    coords = {'node_lat': node_lat, 'node_lon': node_lon, 'node_distance': distances, 'node_weight': weights}
    if orogs is not None:
        coords['node_orog'] = orogs
    return _add_nodes(ds, node_datasets, coords)


def _label_node_means(ds: xr.Dataset) -> xr.Dataset:
    """Add the node mean to each variable's cell_methods: scalar for speed, vector for the components and direction."""
    labels = {'wind_speed': 'node: mean (scalar)', 'ua': 'node: mean (vector)', 'va': 'node: mean (vector)'}
    labels['wind_from_direction'] = 'node: mean (vector)'
    for name in ds.data_vars:
        if name != 'time_bnds':
            label = labels.get(str(name), 'node: mean')
            existing = ds[name].attrs.get('cell_methods')
            ds[name].attrs['cell_methods'] = f'{existing} {label}' if existing else label
    return ds


def _add_nodes(ds: xr.Dataset, node_datasets: list[xr.Dataset], coords: dict[str, np.ndarray]) -> xr.Dataset:
    """Add the node dimension, its coordinates, and each variable's four node series as <name>_node variables."""
    names = [str(name) for name in ds.data_vars if name != 'time_bnds']
    node = np.arange(len(node_datasets))
    units = {'node_lat': 'degrees_north', 'node_lon': 'degrees_east', 'node_distance': 'km', 'node_weight': '1'}
    ds = ds.assign_coords({'node': ('node', node), **{key: ('node', value) for key, value in coords.items()}})
    for key in coords:
        ds[key].attrs = {'units': units.get(key, 'm')}
    for name in names:
        stacked = xr.concat([nd[name].reset_coords(drop=True) for nd in node_datasets], dim='node')
        ds[f'{name}_node'] = stacked.assign_coords(node=node).assign_attrs(node_datasets[0][name].attrs)
    return ds


def _derive_wind_grids(grids: dict[str, xr.DataArray], units: dict[str, str]) -> None:
    """Add wind speed and meteorological direction grids for every ua/va pair present, in place."""
    for ua, va, height in BARRA2_WIND_VARS:
        ua_name = ua if ua in grids else f'ua{height}m'
        va_name = va if va in grids else f'va{height}m'
        if ua_name in grids and va_name in grids:
            u, v = grids[ua_name], grids[va_name]
            direction = np.mod(180 + np.rad2deg(np.arctan2(u, v)), 360)
            grids[f'v{height}m'] = (u**2 + v**2) ** 0.5
            grids[f'v{height}m_phi_met'] = xr.where((u == 0) & (v == 0), 0.0, direction)
            units[f'v{height}m'], units[f'v{height}m_phi_met'] = 'm s-1', 'degrees'


def _area_dataset(
    grids: dict[str, xr.DataArray],
    units: dict[str, str],
    fixed: xr.DataArray | None,
    domain_freq: tuple[str, str],
    versions: dict[str, str] | None,
) -> xr.Dataset:
    """Assemble an area Dataset: every node, with lat and lon as dimensions."""
    domain, freq = domain_freq
    versions = _with_aliases(versions or {})
    _derive_wind_grids(grids, units)
    stacked, plain = _group_by_height(list(grids))
    mean_names = [name for name in plain if _is_mean(domain, freq, name)]
    series_names = [name for name in grids if name not in mean_names]

    template = next(iter(grids.values()))
    times = _union_times([grids[name].get_index('time') for name in series_names])
    ds = xr.Dataset(coords={'time': times, 'lat': template['lat'].to_numpy(), 'lon': template['lon'].to_numpy()})
    ds['time'].attrs = {'standard_name': 'time', 'long_name': 'time as served, UTC'}
    ds['lat'].attrs = {'units': 'degrees_north', 'standard_name': 'latitude'}
    ds['lon'].attrs = {'units': 'degrees_east', 'standard_name': 'longitude'}
    if stacked:
        ds = _add_height_grids(ds, grids, units, stacked, versions)
    for name in plain:
        if name not in mean_names:
            attrs = _variable_attrs(domain, freq, name, units[name], versions)
            ds[name] = grids[name].reindex(time=times).transpose('time', 'lat', 'lon').assign_attrs(attrs)
    if mean_names:
        ds = _add_mean_grids(ds, grids, units, mean_names, domain_freq, versions)
    if fixed is not None:
        ds['orog'] = fixed.assign_attrs({'units': 'm', 'standard_name': 'surface_altitude', 'barra2_name': 'orog'})
    _set_time_encoding(ds)
    ds.attrs = _global_attrs(domain, freq, 'area', None, sorted(set(versions.values())))
    return ds


def _add_height_grids(
    ds: xr.Dataset,
    grids: dict[str, xr.DataArray],
    units: dict[str, str],
    stacked: dict[str, dict[int, str]],
    versions: dict[str, str],
) -> xr.Dataset:
    """Add the height coordinate and one (time, height, lat, lon) variable per quantity; a missing height is NaN."""
    heights = np.array(sorted({height for names in stacked.values() for height in names}), dtype=float)
    ds = ds.assign_coords(height=('height', heights))
    ds['height'].attrs = {'units': 'm', 'positive': 'up', 'long_name': 'height above ground'}
    for quantity, names in stacked.items():
        have = sorted(names)
        parts = [grids[names[height]].reindex(time=ds['time']) for height in have]
        stack = xr.concat(parts, dim=pd.Index([float(height) for height in have], name='height'))
        attrs = {
            'units': units[names[have[0]]],
            'standard_name': _STANDARD_NAMES[quantity],
            'barra2_name': ', '.join(names[height] for height in have),
        }
        found = sorted({versions[name] for name in names.values() if name in versions})
        if found:
            attrs['barra2_version'] = ', '.join(found)
        ds[quantity] = stack.reindex(height=heights).transpose('time', 'height', 'lat', 'lon').assign_attrs(attrs)
    return ds


def _add_mean_grids(
    ds: xr.Dataset,
    grids: dict[str, xr.DataArray],
    units: dict[str, str],
    mean_names: list[str],
    domain_freq: tuple[str, str],
    versions: dict[str, str],
) -> xr.Dataset:
    """Add time_mean, its bounds and the mean variables as (time_mean, lat, lon)."""
    domain, freq = domain_freq
    half_step = BARRA2_FREQS[domain][freq] / 2
    mean_times = _union_times([grids[name].get_index('time') for name in mean_names])
    ds = ds.assign_coords(time_mean=('time_mean', mean_times))
    ds['time_mean'].attrs = {'standard_name': 'time', 'bounds': 'time_bnds', 'long_name': 'middle of the mean period'}
    ds['time_bnds'] = (('time_mean', 'bnds'), np.column_stack([mean_times - half_step, mean_times + half_step]))
    for name in mean_names:
        attrs = _variable_attrs(domain, freq, name, units[name], versions)
        array = grids[name].reindex(time=mean_times).rename(time='time_mean')
        ds[name] = array.transpose('time_mean', 'lat', 'lon').assign_attrs(attrs)
    return ds


def _set_time_encoding(ds: xr.Dataset) -> None:
    """Give every time axis one explicit unit, so time_mean and time_bnds are encoded alike (CF) and exactly."""
    for name in ('time', 'time_mean', 'time_bnds'):
        if name in ds.variables:
            ds[name].encoding['units'] = _TIME_UNITS


def _csv_name(quantity: str, height: int) -> str:
    """Return the csv-route column name of a height-stacked quantity, e.g. ('ua', 10) -> 'ua10m'."""
    return {
        'ua': f'ua{height}m',
        'va': f'va{height}m',
        'wind_speed': f'v{height}m',
        'wind_from_direction': f'v{height}m_phi_met',
    }[quantity]


def _frame_columns(name: str, array: xr.DataArray, index: pd.Index) -> dict[str, pd.Series]:
    """Return the csv columns of one variable: one per height for a stacked quantity, else one."""
    unit = array.attrs.get('units', '1')
    if 'height' not in array.dims:
        return {f'{name}[unit="{unit}"]': pd.Series(array.to_numpy(), index=index)}
    return {
        f'{_csv_name(name, int(height))}[unit="{unit}"]': pd.Series(array.sel(height=height).to_numpy(), index=index)
        for height in array['height'].to_numpy()
    }


def _frame(ds: xr.Dataset, node: int | None) -> pd.DataFrame:
    """Build the csv-route frame of the main series (node None) or of one node's series."""
    columns: dict[str, pd.Series] = {}
    for variable in ds.data_vars:
        name = str(variable)
        if name == 'time_bnds' or name.endswith('_node') != (node is not None):
            continue
        array = ds[name].sel(node=node) if node is not None else ds[name]
        index = ds.get_index('time_mean' if 'time_mean' in array.dims else 'time')
        columns |= _frame_columns(name.removesuffix('_node'), array, index)
    data = pd.concat(columns, axis=1).sort_index().dropna(axis=1, how='all')
    lat = float(ds['node_lat'][node]) if node is not None else float(ds['lat'])
    lon = float(ds['node_lon'][node]) if node is not None else float(ds['lon'])
    label = f'node{node + 1}' if node is not None else str(ds.attrs.get('node_selection', 'nearest'))
    index_columns = pd.DataFrame({BARRA2_INDEX[1]: label, BARRA2_INDEX[2]: lat, BARRA2_INDEX[3]: lon}, index=data.index)
    frame = pd.concat([index_columns, data], axis=1)
    frame.insert(0, BARRA2_INDEX[0], pd.DatetimeIndex(data.index).strftime('%Y-%m-%dT%H:%M:%SZ'))
    return frame.reset_index(drop=True)


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
