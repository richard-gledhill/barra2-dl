"""This module contains the barra2.merge test function(s)."""

import shutil
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from barra2_dl.convert import convert_units, convert_wind_components
from barra2_dl.globals import BARRA2_INDEX
from barra2_dl.mapping import LatLonPoint, Polygon, distance_km, read_polygon
from barra2_dl.merge import (
    _csv_header,
    _merge_suffix_columns,
    _split_height,
    dataset_to_frames,
    merge_csvs_to_df,
    merge_netcdf_to_dataset,
    read_csv,
    read_fixed_fields,
    to_dataset,
    write_csv,
    write_df_csv,
)

# region Test helpers
DATA = Path(__file__).parent / 'data'  # small point files built by scripts/build_test_fixtures.py
SITE = LatLonPoint(-33.88, 151.18)
NODE = {
    'station': 0,
    'latitude[unit="degrees_north"]': -33.9,
    'longitude[unit="degrees_east"]': 151.2,
}


def _write_csv(folder: Path, name: str, data: dict) -> None:
    pd.DataFrame(data).to_csv(folder / name, index=False)


def _frame(times: list[str], **columns: list[float]) -> pd.DataFrame:
    """A merged-style frame: the index columns for one node plus the given variable columns."""
    return pd.DataFrame({'time': times, **{key: [value] * len(times) for key, value in NODE.items()}, **columns})


def _minutes(values: object) -> list[str]:
    """Format datetime64 values to the minute, to compare timestamps exactly."""
    return [str(value) for value in np.asarray(values).astype('datetime64[m]').astype(str).ravel()]


# endregion


# region Public API
# region merge_csvs_to_df
def test_merge_csvs_to_df_outer_join(tmp_path: Path) -> None:
    """Two files sharing a time column are joined into one wide frame."""
    _write_csv(tmp_path, 'a.csv', {'time': [1, 2], 'ua50m': [1.0, 2.0]})
    _write_csv(tmp_path, 'b.csv', {'time': [1, 2], 'va50m': [3.0, 4.0]})

    df = merge_csvs_to_df(str(tmp_path), index_for_join='time')

    assert sorted(df.columns) == ['time', 'ua50m', 'va50m']
    assert df.sort_values('time')['ua50m'].tolist() == [1.0, 2.0]
    assert df.sort_values('time')['va50m'].tolist() == [3.0, 4.0]


def test_merge_csvs_to_df_outer_join_keeps_unmatched_rows(tmp_path: Path) -> None:
    """Rows present in only one file are kept and filled with NaN."""
    _write_csv(tmp_path, 'a.csv', {'time': [1, 2], 'ua50m': [1.0, 2.0]})
    _write_csv(tmp_path, 'b.csv', {'time': [2, 3], 'va50m': [4.0, 5.0]})

    df = merge_csvs_to_df(str(tmp_path), index_for_join='time').sort_values('time').reset_index(drop=True)

    assert df['time'].tolist() == [1, 2, 3]
    assert df['ua50m'].isna().tolist() == [False, False, True]
    assert df['va50m'].isna().tolist() == [True, False, False]


def test_merge_csvs_to_df_filename_pattern(tmp_path: Path) -> None:
    """Only files matching the pattern are merged."""
    _write_csv(tmp_path, 'siteA_ua50m.csv', {'time': [1], 'ua50m': [1.0]})
    _write_csv(tmp_path, 'siteA_va50m.csv', {'time': [1], 'va50m': [2.0]})
    _write_csv(tmp_path, 'siteB_ta50m.csv', {'time': [1], 'ta50m': [3.0]})

    df = merge_csvs_to_df(str(tmp_path), filename_pattern='siteA_*.csv', index_for_join='time')

    assert sorted(df.columns) == ['time', 'ua50m', 'va50m']


def test_merge_csvs_to_df_single_file(tmp_path: Path) -> None:
    """A single file is returned unchanged."""
    _write_csv(tmp_path, 'a.csv', {'time': [1, 2], 'ua50m': [1.0, 2.0]})

    df = merge_csvs_to_df(str(tmp_path), index_for_join='time')

    pd.testing.assert_frame_equal(df, pd.read_csv(tmp_path / 'a.csv'))


def test_merge_csvs_to_df_no_matching_files(tmp_path: Path) -> None:
    """A folder with no matching files gives an empty frame."""
    assert merge_csvs_to_df(str(tmp_path), index_for_join='time').empty


def test_merge_csvs_to_df_repeated_column_is_combined(tmp_path: Path) -> None:
    """A non-index column repeated across files (e.g. month files) ends up as one column, without suffixes."""
    _write_csv(tmp_path, 'a.csv', {'time': [1, 2], 'ua50m': [1.0, None]})
    _write_csv(tmp_path, 'b.csv', {'time': [2, 3], 'ua50m': [2.0, 3.0]})
    _write_csv(tmp_path, 'c.csv', {'time': [4], 'ua50m': [4.0]})

    df = merge_csvs_to_df(str(tmp_path), index_for_join='time').sort_values('time')

    assert sorted(df.columns) == ['time', 'ua50m']
    assert df['ua50m'].tolist() == [1.0, 2.0, 3.0, 4.0]


def test_merge_csvs_to_df_multiple_index_columns(tmp_path: Path) -> None:
    """The join accepts a list of index columns, as used by BARRA2_INDEX."""
    _write_csv(tmp_path, 'a.csv', {'time': [1, 1], 'station': [0, 1], 'ua50m': [1.0, 2.0]})
    _write_csv(tmp_path, 'b.csv', {'time': [1, 1], 'station': [0, 1], 'va50m': [3.0, 4.0]})

    df = merge_csvs_to_df(str(tmp_path), index_for_join=['time', 'station'])

    assert len(df) == 2
    assert sorted(df.columns) == ['station', 'time', 'ua50m', 'va50m']


def test_merge_csvs_to_df_skips_fixed_field_files(tmp_path: Path) -> None:
    """An fx file such as the automatic orog download is left out, so a loose pattern adds no 1970 row."""
    _write_csv(
        tmp_path, 'site_AUS-11_1hr_ua50m_20230101_20230131.csv', {'time': ['2023-01-01T00:00:00Z'], 'ua50m': [1.0]}
    )
    _write_csv(tmp_path, 'site_AUS-11_fx_orog.csv', {'time': ['1970-01-01T00:00:00Z'], 'orog[unit="m"]': [33.0]})

    df = merge_csvs_to_df(str(tmp_path), 'site*.csv', index_for_join='time')

    assert df['time'].tolist() == ['2023-01-01T00:00:00Z']
    assert 'orog[unit="m"]' not in df.columns


# endregion


# region read_fixed_fields
def test_read_fixed_fields_returns_each_value(tmp_path: Path) -> None:
    """Every fx file contributes its field and value; the index columns are left out."""
    index = {
        'time': ['1970-01-01T00:00:00Z'],
        'station': ['GridPointRequestedAt[33.880S_151.180E]'],
        'latitude[unit="degrees_north"]': [-33.879],
        'longitude[unit="degrees_east"]': [151.18],
    }
    _write_csv(tmp_path, 'site_AUS-11_fx_orog.csv', index | {'orog[unit="m"]': [33.05]})
    _write_csv(tmp_path, 'site_AUS-11_fx_sftlf.csv', index | {'sftlf[unit="%"]': [100.0]})
    _write_csv(
        tmp_path, 'site_AUS-11_1hr_ua50m_20230101_20230131.csv', {'time': ['2023-01-01T00:00:00Z'], 'ua50m': [1.0]}
    )

    assert read_fixed_fields(str(tmp_path)) == {'orog[unit="m"]': 33.05, 'sftlf[unit="%"]': 100.0}


def test_read_fixed_fields_reads_netcdf_files() -> None:
    """An orog netCDF file gives the same field name and value as its csv twin."""
    from_nc = read_fixed_fields(str(DATA), 'fixture_AUS-11_fx_*.nc')
    from_csv = read_fixed_fields(str(DATA), 'fixture_AUS-11_fx_*.csv')

    assert list(from_nc) == ['orog[unit="m"]']
    assert from_nc == pytest.approx(from_csv)


def test_read_fixed_fields_none_found(tmp_path: Path) -> None:
    """A folder without fx files gives an empty dict."""
    assert read_fixed_fields(str(tmp_path)) == {}


# endregion


# region to_dataset
def test_to_dataset_stacks_wind_on_height() -> None:
    """Components, speed and direction share a height dimension; heights a quantity lacks are NaN."""
    df = _frame(
        ['2020-01-01T00:00:00Z', '2020-01-01T01:00:00Z'],
        **{
            'ua10m[unit="m s-1"]': [1.0, 2.0],
            'ua50m[unit="m s-1"]': [3.0, 4.0],
            'va10m[unit="m s-1"]': [0.0, 0.0],
            'va50m[unit="m s-1"]': [0.0, 0.0],
            'v50m[unit="m s-1"]': [3.0, 4.0],
            'v50m_phi_met[unit="degrees"]': [270.0, 270.0],
        },
    )

    ds = to_dataset(df, domain='AUS-11', freq='1hr', requested=SITE)

    assert ds['height'].to_numpy().tolist() == [10.0, 50.0]
    assert ds['ua'].dims == ('time', 'height')
    assert ds['ua'].sel(height=50).to_numpy().tolist() == [3.0, 4.0]
    assert ds['wind_speed'].sel(height=50).to_numpy().tolist() == [3.0, 4.0]
    assert np.isnan(ds['wind_speed'].sel(height=10).to_numpy()).all()
    assert ds['wind_from_direction'].attrs['standard_name'] == 'wind_from_direction'
    assert ds['ua'].attrs['units'] == 'm s-1'
    assert ds['ua'].attrs['standard_name'] == 'eastward_wind'


def test_to_dataset_server_names_map_to_ten_metres() -> None:
    """The server names uas and vas are the 10 m winds, like the ua10m alias."""
    df = _frame(['2020-01-01T00:00:00Z'], **{'uas[unit="m s-1"]': [1.0], 'vas[unit="m s-1"]': [2.0]})

    ds = to_dataset(df, domain='AUS-11', freq='1hr', requested=SITE)

    assert ds['height'].to_numpy().tolist() == [10.0]
    assert ds['va'].to_numpy().tolist() == [[2.0]]


def test_to_dataset_keeps_scalar_variable_units_and_names() -> None:
    """Other variables keep their BARRA2 name and unit, and get inventory attributes."""
    df = _frame(['2020-01-01T00:00:00Z'], **{'tas[unit="K"]': [293.0], 'ta50m[unit="K"]': [292.0]})

    ds = to_dataset(df, domain='AUS-11', freq='1hr', requested=SITE)

    assert ds['tas'].attrs['units'] == 'K'
    assert ds['tas'].attrs['standard_name'] == 'air_temperature'
    assert ds['tas'].attrs['barra2_name'] == 'tas'
    assert ds['ta50m'].attrs['standard_name'] == 'air_temperature'
    assert 'long_name' in ds['tas'].attrs


def test_to_dataset_variable_outside_the_inventory_keeps_only_its_name_and_unit() -> None:
    """A column the inventory doesn't list still converts, with just its unit and BARRA2 name."""
    df = _frame(['2020-01-01T00:00:00Z'], **{'mystery[unit="W"]': [1.0]})

    ds = to_dataset(df, domain='AUS-11', freq='1hr', requested=SITE)

    assert ds['mystery'].attrs == {'units': 'W', 'barra2_name': 'mystery'}


def test_to_dataset_node_and_requested_coordinates() -> None:
    """The node is the frame's, the requested site is the one passed in."""
    df = _frame(['2020-01-01T00:00:00Z'], **{'tas[unit="K"]': [1.0]})

    ds = to_dataset(df, domain='AUS-11', freq='1hr', requested=SITE)

    assert (float(ds['lat']), float(ds['lon'])) == (-33.9, 151.2)
    assert (float(ds['requested_lat']), float(ds['requested_lon'])) == (-33.88, 151.18)


def test_to_dataset_mean_variables_use_time_mean_unshifted() -> None:
    """Mean pr (stamped :30) and tas (:00) keep their own timestamps: no shifting, no padded rows."""
    tas = _frame(['2020-01-01T00:00:00Z', '2020-01-01T01:00:00Z'], **{'tas[unit="K"]': [293.0, 294.0]})
    pr = _frame(['2020-01-01T00:30:00Z', '2020-01-01T01:30:00Z'], **{'pr[unit="kg m-2 s-1"]': [0.1, 0.2]})

    ds = to_dataset(pd.concat([tas, pr], ignore_index=True), domain='AUS-11', freq='1hr', requested=SITE)

    assert _minutes(ds['time']) == ['2020-01-01T00:00', '2020-01-01T01:00']
    assert _minutes(ds['time_mean']) == ['2020-01-01T00:30', '2020-01-01T01:30']
    assert ds['pr'].dims == ('time_mean',)
    assert ds['tas'].dims == ('time',)
    assert ds['pr'].to_numpy().tolist() == [0.1, 0.2]
    assert 'time: mean' in ds['pr'].attrs['cell_methods']
    assert _minutes(ds['time_bnds'].to_numpy()[0]) == ['2020-01-01T00:00', '2020-01-01T01:00']
    assert ds['time_mean'].attrs['bounds'] == 'time_bnds'


def test_to_dataset_without_mean_variables_has_no_time_mean() -> None:
    """Instantaneous data needs no time_mean coordinate."""
    df = _frame(['2020-01-01T00:00:00Z'], **{'tas[unit="K"]': [1.0]})

    ds = to_dataset(df, domain='AUS-11', freq='1hr', requested=SITE)

    assert 'time_mean' not in ds.coords
    assert 'time_bnds' not in ds


def test_to_dataset_twenty_minute_bounds_use_the_step() -> None:
    """time_bnds span one step centred on the stamp: 20 minutes at AUST-04 20min."""
    df = _frame(['2020-01-01T00:10:00Z'], **{'prra[unit="kg m-2 s-1"]': [0.1]})

    ds = to_dataset(df, domain='AUST-04', freq='20min', requested=SITE)

    assert _minutes(ds['time_bnds'].to_numpy()[0]) == ['2020-01-01T00:00', '2020-01-01T00:20']


def test_to_dataset_attributes() -> None:
    """Provenance, conventions, licence and orog are recorded."""
    df = _frame(['2020-01-01T00:00:00Z'], **{'tas[unit="K"]': [1.0]})

    ds = to_dataset(df, domain='AUST-04', freq='1hr', requested=SITE, orog=33.05)

    assert ds.attrs['Conventions'] == 'CF-1.10'
    assert (ds.attrs['domain'], ds.attrs['freq'], ds.attrs['node_selection']) == ('AUST-04', '1hr', 'nearest')
    assert ds.attrs['barra2_version'] == 'latest'
    assert len(str(ds.attrs['downloaded'])) == len('2020-01-01')
    assert ds.attrs['orog'] == 33.05
    assert 'BARRA-C2' in str(ds.attrs['source'])
    assert 'barra2-dl' in str(ds.attrs['history'])
    assert ds.attrs['license']
    assert ds.attrs['references']


def test_to_dataset_versions_follow_aliases_and_default_to_latest() -> None:
    """A version recorded under the server name uas applies to the ua10m column; unresolved variables get none."""
    df = _frame(['2020-01-01T00:00:00Z'], **{'ua10m[unit="m s-1"]': [1.0], 'tas[unit="K"]': [293.0]})

    ds = to_dataset(df, domain='AUS-11', freq='1hr', requested=SITE, versions={'uas': 'v20231001'})

    assert ds['ua'].attrs['barra2_version'] == 'v20231001'
    assert 'barra2_version' not in ds['tas'].attrs
    assert ds.attrs['barra2_version'] == 'v20231001'


def test_to_dataset_omits_orog_when_unknown() -> None:
    """There is no orog attribute without a value."""
    df = _frame(['2020-01-01T00:00:00Z'], **{'tas[unit="K"]': [1.0]})

    assert 'orog' not in to_dataset(df, domain='AUS-11', freq='1hr', requested=SITE).attrs


def test_to_dataset_netcdf_round_trip(tmp_path: Path) -> None:
    """Writing and reading back keeps values, units, attributes and the unshifted times."""
    inst = _frame(
        ['2020-01-01T00:00:00Z', '2020-01-01T01:00:00Z'],
        **{'tas[unit="K"]': [293.0, 294.0], 'ua50m[unit="m s-1"]': [1.0, 2.0]},
    )
    mean = _frame(['2020-01-01T00:30:00Z'], **{'pr[unit="kg m-2 s-1"]': [0.1]})
    ds = to_dataset(pd.concat([inst, mean], ignore_index=True), domain='AUS-11', freq='1hr', requested=SITE, orog=33.0)
    path = tmp_path / 'site.nc'

    ds.to_netcdf(path, engine='h5netcdf')

    with xr.open_dataset(path, engine='h5netcdf') as back:
        assert back['tas'].to_numpy().tolist() == [293.0, 294.0]
        assert back['tas'].attrs['units'] == 'K'
        assert back['ua'].sel(height=50).to_numpy().tolist() == [1.0, 2.0]
        assert _minutes(back['time_mean']) == ['2020-01-01T00:30']
        assert back.attrs['orog'] == 33.0
        assert back.attrs['Conventions'] == 'CF-1.10'


@pytest.mark.parametrize('frame', [pd.DataFrame(), pd.DataFrame({'tas': [1.0]})])
def test_to_dataset_rejects_frames_without_time_or_rows(frame: pd.DataFrame) -> None:
    """An empty frame or one without a time column is an error."""
    with pytest.raises(ValueError, match='time column'):
        to_dataset(frame, domain='AUS-11', freq='1hr', requested=SITE)


def test_to_dataset_rejects_more_than_one_node() -> None:
    """Two nodes in one frame cannot become a point dataset."""
    other = _frame(['2020-01-01T00:00:00Z'], **{'tas[unit="K"]': [2.0]})
    other['latitude[unit="degrees_north"]'] = -34.0
    df = pd.concat([_frame(['2020-01-01T00:00:00Z'], **{'tas[unit="K"]': [1.0]}), other])

    with pytest.raises(ValueError, match='one node'):
        to_dataset(df, domain='AUS-11', freq='1hr', requested=SITE)


# endregion


# region merge_netcdf_to_dataset
def _fixture_dataset(orog: float | None = None, versions: dict[str, str] | None = None) -> xr.Dataset:
    """The netCDF4 fixtures merged with the AUS-11 1hr defaults."""
    return merge_netcdf_to_dataset(
        str(DATA), 'fixture_AUS-11_1hr_*.nc', domain='AUS-11', freq='1hr', requested=SITE, orog=orog, versions=versions
    )


def _csv_route_dataset() -> xr.Dataset:
    """The same fixtures through the csv route: merge, convert, to_dataset."""
    df = merge_csvs_to_df(str(DATA), 'fixture_AUS-11_1hr_*.csv', BARRA2_INDEX)
    return to_dataset(convert_wind_components(df), domain='AUS-11', freq='1hr', requested=SITE)


def test_merge_netcdf_to_dataset_matches_the_csv_route() -> None:
    """Both routes give the same values, times, coordinates and units for the same point and period."""
    from_nc, from_csv = _fixture_dataset(), _csv_route_dataset()

    assert set(from_nc.data_vars) == set(from_csv.data_vars)
    for name in from_csv.data_vars:
        assert from_nc[name].dims == from_csv[name].dims
        if name == 'time_bnds':
            assert (from_nc[name].to_numpy() == from_csv[name].to_numpy()).all()
            continue
        np.testing.assert_allclose(from_nc[name].to_numpy(), from_csv[name].to_numpy(), err_msg=str(name))
        assert from_nc[name].attrs.get('units') == from_csv[name].attrs.get('units')
    assert _minutes(from_nc['time']) == _minutes(from_csv['time'])
    assert _minutes(from_nc['time_mean']) == _minutes(from_csv['time_mean'])
    assert (float(from_nc['lat']), float(from_nc['lon'])) == (float(from_csv['lat']), float(from_csv['lon']))
    assert from_nc['height'].to_numpy().tolist() == from_csv['height'].to_numpy().tolist()


def test_merge_netcdf_to_dataset_derives_wind_speed_and_direction() -> None:
    """Speed is the magnitude of ua and va, and direction is a compass bearing."""
    ds = _fixture_dataset()

    speed = np.hypot(ds['ua'].sel(height=50), ds['va'].sel(height=50))
    np.testing.assert_allclose(ds['wind_speed'].sel(height=50), speed)
    assert ds['wind_from_direction'].sel(height=50).min() >= 0
    assert ds['wind_from_direction'].sel(height=50).max() <= 360


def test_merge_netcdf_to_dataset_keeps_timestamps_as_served() -> None:
    """Instantaneous variables stay at :00 and the mean pr at :30, on their own time axes."""
    ds = _fixture_dataset()

    assert _minutes(ds['time'])[:2] == ['2023-01-01T00:00', '2023-01-01T01:00']
    assert _minutes(ds['time_mean'])[:2] == ['2023-01-01T00:30', '2023-01-01T01:30']
    assert ds['pr'].dims == ('time_mean',)
    assert ds['tas'].dims == ('time',)


def test_merge_netcdf_to_dataset_skips_fixed_field_files() -> None:
    """A loose pattern that also matches the fx file adds no 1970 time and no orog variable."""
    ds = merge_netcdf_to_dataset(str(DATA), 'fixture_*.nc', domain='AUS-11', freq='1hr', requested=SITE)

    assert 'orog' not in ds.data_vars
    assert ds['time'].to_numpy().min() >= np.datetime64('2023-01-01')


def test_merge_netcdf_to_dataset_joins_months_in_time(tmp_path: Path) -> None:
    """The same variable from consecutive months is concatenated in time order."""
    name = 'fixture_AUS-11_1hr_ua50m_20230101_20230103.nc'
    with xr.open_dataset(DATA / name) as first:
        first.load().to_netcdf(tmp_path / 'm1_ua50m.nc')
        first.assign_coords(time=first['time'] + np.timedelta64(31, 'D')).load().to_netcdf(tmp_path / 'm2_ua50m.nc')

    ds = merge_netcdf_to_dataset(str(tmp_path), '*.nc', domain='AUS-11', freq='1hr', requested=SITE)

    assert ds.sizes['time'] == 2 * 72
    assert ds['time'].to_index().is_monotonic_increasing
    assert _minutes(ds['time'])[72] == '2023-02-01T00:00'


def test_merge_netcdf_to_dataset_records_orog_and_versions() -> None:
    """The node altitude and per-variable dataset versions are written as attributes."""
    ds = _fixture_dataset(orog=747.6, versions={'ua50m': 'v20240516', 'va50m': 'v20240516', 'tas': 'v20231001'})

    assert ds.attrs['orog'] == 747.6
    assert ds.attrs['barra2_version'] == 'v20231001, v20240516'
    assert ds['tas'].attrs['barra2_version'] == 'v20231001'
    assert ds['ua'].attrs['barra2_version'] == 'v20240516'
    assert 'barra2_version' not in ds['pr'].attrs


def test_merge_netcdf_to_dataset_without_versions_says_latest() -> None:
    """No resolved versions means the dataset is recorded as latest."""
    assert _fixture_dataset().attrs['barra2_version'] == 'latest'


def test_merge_netcdf_to_dataset_round_trip(tmp_path: Path) -> None:
    """Writing and reading back keeps values and units."""
    ds = _fixture_dataset()
    ds.to_netcdf(tmp_path / 'site.nc')

    with xr.open_dataset(tmp_path / 'site.nc') as back:
        np.testing.assert_allclose(back['ua'].to_numpy(), ds['ua'].to_numpy())
        assert back['tas'].attrs['units'] == 'K'
        assert _minutes(back['time_mean'])[0] == '2023-01-01T00:30'


def test_merge_netcdf_to_dataset_no_files(tmp_path: Path) -> None:
    """A folder without matching files is an error."""
    with pytest.raises(ValueError, match='No nearest netCDF files'):
        merge_netcdf_to_dataset(str(tmp_path), '*.nc', domain='AUS-11', freq='1hr', requested=SITE)


def test_merge_netcdf_to_dataset_rejects_more_than_one_node(tmp_path: Path) -> None:
    """Files from two nodes cannot become a point dataset."""
    with xr.open_dataset(DATA / 'fixture_AUS-11_1hr_ua50m_20230101_20230103.nc') as ds:
        ds.load().to_netcdf(tmp_path / 'a_ua50m.nc')
        ds.assign_coords(latitude=ds['latitude'] + 1).load().to_netcdf(tmp_path / 'b_ua50m.nc')

    with pytest.raises(ValueError, match='one node'):
        merge_netcdf_to_dataset(str(tmp_path), '*.nc', domain='AUS-11', freq='1hr', requested=SITE)


def test_merge_netcdf_to_dataset_rejects_files_without_one_variable(tmp_path: Path) -> None:
    """A file with two data variables on obs is not a single-variable point file."""
    with xr.open_dataset(DATA / 'fixture_AUS-11_1hr_ua50m_20230101_20230103.nc') as ds:
        ds.assign(extra=ds['ua50m']).load().to_netcdf(tmp_path / 'both.nc')

    with pytest.raises(ValueError, match='one data variable'):
        merge_netcdf_to_dataset(str(tmp_path), '*.nc', domain='AUS-11', freq='1hr', requested=SITE)


# endregion


# region merge_netcdf_to_dataset (average4)
GRID_FILE = DATA / 'grid_AUS-11_1hr_average4_ua50m_20230101_20230103.nc'
GRID_SITE = LatLonPoint(-23.55, 133.40)


def _average4(
    site: LatLonPoint = GRID_SITE, fixed_pattern: str | None = None, versions: dict[str, str] | None = None
) -> xr.Dataset:
    """The bounding-box fixtures merged as a four-node average around the site."""
    return merge_netcdf_to_dataset(
        str(DATA),
        'grid_AUS-11_1hr_average4_*.nc',
        domain='AUS-11',
        freq='1hr',
        requested=site,
        node_selection='average4',
        fixed_pattern=fixed_pattern,
        versions=versions,
    )


def _write_grid(path: Path, name: str, values: np.ndarray, unit: str = 'm s-1') -> None:
    """Write a tiny (time, lat, lon) bounding-box file on a 2 x 2 grid at 0 and 1 degrees."""
    times = pd.date_range('2023-01-01', periods=values.shape[0], freq='h')
    grid = xr.Dataset(
        {name: (('time', 'lat', 'lon'), values, {'units': unit})},
        coords={'time': times, 'lat': [0.0, 1.0], 'lon': [0.0, 1.0]},
    )
    grid.to_netcdf(path, engine='h5netcdf')


def test_merge_netcdf_to_dataset_average4_uses_the_real_nodes_of_the_response() -> None:
    """The four nodes are grid nodes from the file that surround the site, not computed positions."""
    with xr.open_dataset(GRID_FILE) as grid:
        file_lats, file_lons = grid['lat'].to_numpy(), grid['lon'].to_numpy()

    ds = _average4()

    assert ds.sizes['node'] == 4
    assert set(ds['node_lat'].to_numpy()) <= set(file_lats)
    assert set(ds['node_lon'].to_numpy()) <= set(file_lons)
    assert len(set(zip(ds['node_lat'].to_numpy(), ds['node_lon'].to_numpy(), strict=True))) == 4
    assert ds['node_lat'].min() <= GRID_SITE.lat <= ds['node_lat'].max()
    assert ds['node_lon'].min() <= GRID_SITE.lon <= ds['node_lon'].max()


def test_merge_netcdf_to_dataset_average4_weights_sum_to_one_and_favour_near_nodes() -> None:
    """Inverse-distance weights sum to 1, and the nearest node weighs most."""
    ds = _average4()

    assert float(ds['node_weight'].sum()) == pytest.approx(1)
    assert np.argmax(ds['node_weight'].to_numpy()) == np.argmin(ds['node_distance'].to_numpy())
    assert ds['node_distance'].attrs['units'] == 'km'
    assert (ds['node_distance'] > 0).all()


def test_merge_netcdf_to_dataset_average4_speed_is_the_scalar_mean_of_node_speeds() -> None:
    """Averaged speed is the weighted mean of each node's own speed."""
    ds = _average4()

    expected = (ds['wind_speed_node'] * ds['node_weight']).sum('node')
    np.testing.assert_allclose(ds['wind_speed'].to_numpy(), expected.to_numpy())


def test_merge_netcdf_to_dataset_average4_components_and_direction_are_the_vector_mean() -> None:
    """Ua and va are weighted means, and the direction is taken from them."""
    ds = _average4()

    for component in ('ua', 'va'):
        expected = (ds[f'{component}_node'] * ds['node_weight']).sum('node')
        np.testing.assert_allclose(ds[component].to_numpy(), expected.to_numpy())
    direction = np.mod(180 + np.rad2deg(np.arctan2(ds['ua'], ds['va'])), 360)
    np.testing.assert_allclose(ds['wind_from_direction'].to_numpy(), direction.to_numpy())


def test_merge_netcdf_to_dataset_average4_speed_is_not_the_speed_of_the_mean_vector() -> None:
    """The averaged speed is at least hypot(ua, va), and larger where the nodes' winds differ in direction."""
    ds = _average4()

    vector_speed = np.hypot(ds['ua'], ds['va'])
    assert (ds['wind_speed'] >= vector_speed - 1e-9).all()
    assert (ds['wind_speed'] > vector_speed + 1e-6).any()


def test_merge_netcdf_to_dataset_average4_opposed_winds_keep_their_speed(tmp_path: Path) -> None:
    """Opposed 5 m/s winds average to 5 m/s by the scalar mean, not the 0 m/s of the mean vector."""
    ua = np.tile(np.array([[5.0, -5.0], [5.0, -5.0]]), (2, 1, 1))
    _write_grid(tmp_path / 'g_AUS-11_1hr_average4_ua50m_20230101_20230101.nc', 'ua50m', ua)
    _write_grid(tmp_path / 'g_AUS-11_1hr_average4_va50m_20230101_20230101.nc', 'va50m', np.zeros_like(ua))

    ds = merge_netcdf_to_dataset(
        str(tmp_path),
        '*.nc',
        domain='AUS-11',
        freq='1hr',
        requested=LatLonPoint(0.5, 0.5),
        node_selection='average4',
    )

    assert ds['wind_speed'].to_numpy() == pytest.approx(5.0)
    assert abs(ds['ua'].to_numpy()).max() < 1e-9


def test_merge_netcdf_to_dataset_average4_labels_the_means_in_cell_methods() -> None:
    """The file says which mean each variable is: scalar for speed, vector for components and direction."""
    ds = _average4()

    assert ds['wind_speed'].attrs['cell_methods'] == 'node: mean (scalar)'
    for name in ('ua', 'va', 'wind_from_direction'):
        assert ds[name].attrs['cell_methods'] == 'node: mean (vector)'
    assert ds['tas'].attrs['cell_methods'].endswith('node: mean')
    assert 'node:' not in ds['wind_speed_node'].attrs.get('cell_methods', '')


def test_merge_netcdf_to_dataset_average4_writes_the_node_series_beside_the_average() -> None:
    """Every averaged variable has its four node series on a node dimension."""
    ds = _average4()

    assert ds['ua_node'].dims == ('node', 'time', 'height')
    assert ds['tas_node'].dims == ('node', 'time')
    assert ds['pr_node'].dims == ('node', 'time_mean')
    assert ds['ua'].dims == ('time', 'height')
    assert ds['ua_node'].attrs['units'] == 'm s-1'


def test_merge_netcdf_to_dataset_average4_site_is_the_requested_one_and_timestamps_are_unshifted() -> None:
    """Lat and lon are the requested site; instantaneous variables are at :00 and the mean pr at :30."""
    ds = _average4()

    assert (float(ds['lat']), float(ds['lon'])) == (GRID_SITE.lat, GRID_SITE.lon)
    assert ds.attrs['node_selection'] == 'average4'
    assert _minutes(ds['time'])[:2] == ['2023-01-01T00:00', '2023-01-01T01:00']
    assert _minutes(ds['time_mean'])[:2] == ['2023-01-01T00:30', '2023-01-01T01:30']


def test_merge_netcdf_to_dataset_average4_site_on_a_node_gives_that_nodes_values() -> None:
    """A site exactly on a node gets that node's series, with all the weight."""
    first = _average4()
    index = int(np.argmin(first['node_distance'].to_numpy()))
    on_node = LatLonPoint(float(first['node_lat'][index]), float(first['node_lon'][index]))

    ds = _average4(on_node)

    assert float(ds['node_weight'].max()) == 1.0
    best = int(np.argmax(ds['node_weight'].to_numpy()))
    np.testing.assert_allclose(ds['ua'].to_numpy(), ds['ua_node'].isel(node=best).to_numpy())
    np.testing.assert_allclose(ds['wind_speed'].to_numpy(), ds['wind_speed_node'].isel(node=best).to_numpy())


def test_merge_netcdf_to_dataset_average4_orog_is_per_node_and_weighted() -> None:
    """With the orog grid, each node has its altitude and the dataset attribute is their weighted mean."""
    ds = _average4(fixed_pattern='grid_AUS-11_fx_average4_orog.nc')

    assert ds['node_orog'].dims == ('node',)
    assert float(ds.attrs['orog']) == pytest.approx(float((ds['node_orog'] * ds['node_weight']).sum()))
    assert ds['node_orog'].attrs['units'] == 'm'


def test_merge_netcdf_to_dataset_average4_without_orog_grid_has_no_orog() -> None:
    """No fixed_pattern means no altitude is written."""
    ds = _average4()

    assert 'node_orog' not in ds.coords
    assert 'orog' not in ds.attrs


def test_merge_netcdf_to_dataset_average4_records_versions() -> None:
    """Versions reach the average, the node series and the global attribute."""
    ds = _average4(versions={'ua50m': 'v20240516', 'va50m': 'v20240516', 'tas': 'v20231001'})

    assert ds['tas'].attrs['barra2_version'] == 'v20231001'
    assert ds['tas_node'].attrs['barra2_version'] == 'v20231001'
    assert ds.attrs['barra2_version'] == 'v20231001, v20240516'


def test_merge_netcdf_to_dataset_average4_round_trip(tmp_path: Path) -> None:
    """Writing and reading back keeps the node dimension and values."""
    ds = _average4(fixed_pattern='grid_AUS-11_fx_average4_orog.nc')
    ds.to_netcdf(tmp_path / 'site.nc')

    with xr.open_dataset(tmp_path / 'site.nc') as back:
        np.testing.assert_allclose(back['ua_node'].to_numpy(), ds['ua_node'].to_numpy())
        np.testing.assert_allclose(back['node_weight'].to_numpy(), ds['node_weight'].to_numpy())


def test_merge_netcdf_to_dataset_average4_site_outside_the_grid() -> None:
    """A site the downloaded grid doesn't surround can't be averaged."""
    with pytest.raises(ValueError, match='outside'):
        _average4(LatLonPoint(10.0, 133.4))


@pytest.mark.parametrize('node_selection', ['nearest', 'average4'])
def test_merge_netcdf_to_dataset_needs_the_site_unless_area(node_selection: str) -> None:
    """The nearest node and the average need the requested site."""
    with pytest.raises(ValueError, match='requested'):
        merge_netcdf_to_dataset(
            str(DATA), 'grid_AUS-11_1hr_average4_*.nc', domain='AUS-11', freq='1hr', node_selection=node_selection
        )


def test_merge_netcdf_to_dataset_a_loose_pattern_merges_only_the_kind_asked_for() -> None:
    """With point, grid and fixed-field files in one folder, each node selection picks its own files."""
    nearest = merge_netcdf_to_dataset(str(DATA), '*_AUS-11_*.nc', domain='AUS-11', freq='1hr', requested=SITE)
    average = merge_netcdf_to_dataset(
        str(DATA),
        '*_AUS-11_*.nc',
        domain='AUS-11',
        freq='1hr',
        requested=GRID_SITE,
        node_selection='average4',
    )

    assert 'node' not in nearest.dims
    assert average.sizes['node'] == 4


def test_merge_netcdf_to_dataset_unknown_node_selection() -> None:
    """Only nearest, average4 and area are node selections."""
    with pytest.raises(ValueError, match='node_selection'):
        merge_netcdf_to_dataset(
            str(DATA), '*.nc', domain='AUS-11', freq='1hr', requested=SITE, node_selection='average9'
        )


def test_merge_netcdf_to_dataset_grid_file_that_is_not_a_grid(tmp_path: Path) -> None:
    """A point file given as a grid is rejected."""
    shutil.copy(DATA / 'fixture_AUS-11_1hr_ua50m_20230101_20230103.nc', tmp_path / 'point_average4_ua50m.nc')

    with pytest.raises(ValueError, match=r'\(time, lat, lon\)'):
        merge_netcdf_to_dataset(
            str(tmp_path), '*.nc', domain='AUS-11', freq='1hr', requested=SITE, node_selection='average4'
        )


def test_merge_netcdf_to_dataset_grid_months_are_joined(tmp_path: Path) -> None:
    """Two months of a grid variable are joined in time."""
    with xr.open_dataset(GRID_FILE) as first:
        first.load().to_netcdf(tmp_path / 'm1_average4_ua50m.nc')
        shifted = first.assign_coords(time=first['time'] + np.timedelta64(31, 'D'))
        shifted.load().to_netcdf(tmp_path / 'm2_average4_ua50m.nc')

    ds = merge_netcdf_to_dataset(
        str(tmp_path), '*.nc', domain='AUS-11', freq='1hr', requested=GRID_SITE, node_selection='average4'
    )

    assert ds.sizes['time'] == 2 * 72


def test_merge_netcdf_to_dataset_fixed_pattern_without_files(tmp_path: Path) -> None:
    """A fixed_pattern that matches nothing is an error, not a silently missing altitude."""
    with pytest.raises(ValueError, match='No fixed-field files'):
        _average4(fixed_pattern='nothing_*.nc')


def test_merge_netcdf_to_dataset_fixed_file_that_is_not_a_grid() -> None:
    """A fixed-field point file can't be the orog grid."""
    with pytest.raises(ValueError, match=r'\(lat, lon\)'):
        _average4(fixed_pattern='fixture_AUS-11_fx_orog.nc')


# endregion


# region merge_netcdf_to_dataset (nodes)
# the grid fixtures hold the 3 x 3 nodes at lat -23.65, -23.54, -23.43 and lon 133.25, 133.36, 133.47
SURROUNDING = [
    LatLonPoint(-23.65, 133.36),
    LatLonPoint(-23.65, 133.47),
    LatLonPoint(-23.54, 133.36),
    LatLonPoint(-23.54, 133.47),
]
CHOSEN = [LatLonPoint(-23.54, 133.36), LatLonPoint(-23.43, 133.47)]


@pytest.fixture
def nodes_folder(tmp_path: Path) -> Path:
    """The average4 grid fixtures copied under nodes names, as a nodes download would leave them."""
    for source in DATA.glob('grid_AUS-11_*average4_*.nc'):
        shutil.copy(source, tmp_path / source.name.replace('grid_', 'site_').replace('average4', 'nodes_n1_s2_e3_w4'))
    return tmp_path


def _nodes(
    folder: Path,
    nodes: list[LatLonPoint] | None = None,
    *,
    node_mean: bool = False,
    fixed: bool = True,
    site: LatLonPoint = GRID_SITE,
) -> xr.Dataset:
    """The grid fixtures merged as chosen nodes."""
    return merge_netcdf_to_dataset(
        str(folder),
        'site_AUS-11_1hr_nodes_*.nc',
        domain='AUS-11',
        freq='1hr',
        requested=site,
        node_selection='nodes',
        fixed_pattern='site_AUS-11_fx_nodes_*_orog.nc' if fixed else None,
        nodes=CHOSEN if nodes is None else nodes,
        node_mean=node_mean,
    )


def test_merge_netcdf_to_dataset_nodes_keeps_the_chosen_nodes_in_the_order_given(nodes_folder: Path) -> None:
    """The node dimension holds exactly the chosen nodes, as served, in the order the user gave them."""
    ds = _nodes(nodes_folder, list(reversed(CHOSEN)))

    assert ds['node_lat'].to_numpy().tolist() == pytest.approx([-23.43, -23.54])
    assert ds['node_lon'].to_numpy().tolist() == pytest.approx([133.47, 133.36])
    assert ds.attrs['node_selection'] == 'nodes'
    assert (float(ds['lat']), float(ds['lon'])) == (GRID_SITE.lat, GRID_SITE.lon)


def test_merge_netcdf_to_dataset_nodes_without_a_mean_has_node_series_only(nodes_folder: Path) -> None:
    """No mean variables and no weights unless the mean is asked for."""
    ds = _nodes(nodes_folder)

    assert {str(name).removesuffix('_node') for name in ds.data_vars if name != 'time_bnds'} >= {'ua', 'va'}
    assert all(str(name).endswith('_node') for name in ds.data_vars if name != 'time_bnds')
    assert 'node_weight' not in ds.coords
    assert ds.sizes['node'] == 2


def test_merge_netcdf_to_dataset_nodes_series_match_the_grid_at_those_nodes(nodes_folder: Path) -> None:
    """Each node's series is the grid's series at that node, not a neighbour's."""
    ds = _nodes(nodes_folder)
    average4 = _average4()

    first = ds['ua_node'].isel(node=0, height=0).to_numpy()
    lat, lon = average4['node_lat'].to_numpy(), average4['node_lon'].to_numpy()
    index = int(np.flatnonzero(np.isclose(lat, -23.54) & np.isclose(lon, 133.36))[0])
    expected = average4['ua_node'].isel(node=index, height=0)
    np.testing.assert_allclose(first, expected.to_numpy())


def test_merge_netcdf_to_dataset_nodes_distance_is_from_the_requested_site(nodes_folder: Path) -> None:
    """node_distance is the great-circle distance in km from the site to each node."""
    ds = _nodes(nodes_folder)

    expected = [float(distance_km(GRID_SITE.lat, GRID_SITE.lon, node.lat, node.lon)) for node in CHOSEN]
    assert ds['node_distance'].to_numpy().tolist() == pytest.approx(expected)
    assert ds['node_distance'].attrs['units'] == 'km'


def test_merge_netcdf_to_dataset_nodes_mean_of_the_surrounding_four_equals_average4(nodes_folder: Path) -> None:
    """Chosen as the four nodes around the site, the mean is the four-node average (same weights, same method)."""
    ds = _nodes(nodes_folder, SURROUNDING, node_mean=True)
    expected = _average4()

    for name in ('ua', 'va', 'wind_speed', 'wind_from_direction'):
        np.testing.assert_allclose(ds[name].to_numpy(), expected[name].to_numpy())
    np.testing.assert_allclose(np.sort(ds['node_weight'].to_numpy()), np.sort(expected['node_weight'].to_numpy()))
    assert float(ds['node_weight'].sum()) == pytest.approx(1.0)
    assert ds['wind_speed'].attrs['cell_methods'].endswith('node: mean (scalar)')


def test_merge_netcdf_to_dataset_nodes_orog_is_per_node_when_the_grid_is_given(nodes_folder: Path) -> None:
    """With the orog grid each node has its altitude; the mean's altitude attribute is their weighted mean."""
    ds = _nodes(nodes_folder, node_mean=True)

    assert ds['node_orog'].dims == ('node',)
    assert float(ds.attrs['orog']) == pytest.approx(float((ds['node_orog'] * ds['node_weight']).sum()))
    assert 'node_orog' not in _nodes(nodes_folder, fixed=False).coords


def test_merge_netcdf_to_dataset_nodes_forgives_a_value_rounded_by_hand(nodes_folder: Path) -> None:
    """A latitude a few metres off a node still names it, as the tolerance is far below any grid spacing."""
    ds = _nodes(nodes_folder, [LatLonPoint(-23.540049, 133.36)])

    assert float(ds['node_lat'][0]) == pytest.approx(-23.54)


@pytest.mark.parametrize('node', [LatLonPoint(-23.55, 133.36), LatLonPoint(-23.54, 133.40)])
def test_merge_netcdf_to_dataset_nodes_rejects_a_value_that_is_not_a_node(
    nodes_folder: Path, node: LatLonPoint
) -> None:
    """A made-up node raises, naming the nodes near it and pointing at mapping.nearest_nodes."""
    with pytest.raises(ValueError, match=r'is not a node of AUS-11.*nearest_nodes'):
        _nodes(nodes_folder, [node])


def test_merge_netcdf_to_dataset_nodes_needs_nodes(nodes_folder: Path) -> None:
    """The nodes selection without nodes is an error."""
    with pytest.raises(ValueError, match='needs nodes'):
        merge_netcdf_to_dataset(
            str(nodes_folder),
            'site_AUS-11_1hr_nodes_*.nc',
            domain='AUS-11',
            freq='1hr',
            requested=GRID_SITE,
            node_selection='nodes',
        )


def test_dataset_to_frames_nodes_gives_a_frame_per_node_and_the_mean_only_if_asked(nodes_folder: Path) -> None:
    """Without the mean the frames are node1 to nodeN; with it the mean comes first, keyed nodes."""
    assert list(dataset_to_frames(_nodes(nodes_folder))) == ['node1', 'node2']
    assert list(dataset_to_frames(_nodes(nodes_folder, node_mean=True))) == ['nodes', 'node1', 'node2']


def test_dataset_to_frames_nodes_frames_carry_each_nodes_position(nodes_folder: Path) -> None:
    """Each node frame has its node's latitude and longitude and its label."""
    frames = dataset_to_frames(_nodes(nodes_folder))

    assert frames['node2'].loc[0, 'station'] == 'node2'
    assert frames['node2'].loc[0, BARRA2_INDEX[2]] == pytest.approx(-23.43)
    assert frames['node2'].loc[0, BARRA2_INDEX[3]] == pytest.approx(133.47)


def test_write_csv_nodes_names_files_and_writes_node_lines_in_the_mean_header(
    nodes_folder: Path, tmp_path: Path
) -> None:
    """One file per node, and the mean's file, with Node lines in the mean's header; no weight without a mean."""
    out = tmp_path / 'out'
    out.mkdir()

    paths = write_csv(_nodes(nodes_folder, node_mean=True), out, 'site')
    plain = write_csv(_nodes(nodes_folder), out, 'plain')

    assert [path.name for path in paths] == [
        f'site_AUS-11_1hr_{name}_20230101_20230103.csv' for name in ('nodes', 'node1', 'node2')
    ]
    mean_header = read_csv(paths[0])[1]
    assert mean_header['Node selection'] == 'nodes'
    assert mean_header['Node 1'].startswith('lat -23.54')
    assert 'weight' in mean_header['Node 1']
    assert [path.name for path in plain] == [f'plain_AUS-11_1hr_node{k}_20230101_20230103.csv' for k in (1, 2)]
    node_header = read_csv(plain[1])[1]
    assert float(node_header['Latitude']) == pytest.approx(-23.43)
    assert float(node_header['Distance to node']) == pytest.approx(
        float(distance_km(GRID_SITE.lat, GRID_SITE.lon, -23.43, 133.47))
    )


# endregion


# region merge_netcdf_to_dataset (area)
@pytest.fixture
def area(tmp_path: Path) -> Callable[..., xr.Dataset]:
    """Merge the bounding-box fixtures as an area, after renaming them as an area download would name them."""
    for file in DATA.glob('grid_*.nc'):
        shutil.copy(file, tmp_path / file.name.replace('_average4_', '_area_'))

    def merge(fixed_pattern: str | None = None, versions: dict[str, str] | None = None) -> xr.Dataset:
        return merge_netcdf_to_dataset(
            str(tmp_path),
            'grid_AUS-11_1hr_area_*.nc',
            domain='AUS-11',
            freq='1hr',
            node_selection='area',
            fixed_pattern=fixed_pattern,
            versions=versions,
        )

    return merge


def test_merge_netcdf_to_dataset_area_has_lat_and_lon_dimensions(area: Callable[..., xr.Dataset]) -> None:
    """Every node of the box is kept: lat and lon are dimensions of the variables."""
    ds = area()

    assert ds['ua'].dims == ('time', 'height', 'lat', 'lon')
    assert ds['tas'].dims == ('time', 'lat', 'lon')
    assert ds['pr'].dims == ('time_mean', 'lat', 'lon')
    assert ds.sizes['lat'] == ds.sizes['lon'] == 3
    assert 'node' not in ds.dims
    assert ds.attrs['node_selection'] == 'area'
    assert 'requested_lat' not in ds.coords


def test_merge_netcdf_to_dataset_area_derives_wind_per_node(area: Callable[..., xr.Dataset]) -> None:
    """Speed is hypot(ua, va) at each node, and direction a compass bearing."""
    ds = area()

    np.testing.assert_allclose(ds['wind_speed'].to_numpy(), ((ds['ua'] ** 2 + ds['va'] ** 2) ** 0.5).to_numpy())
    assert ds['wind_from_direction'].min() >= 0
    assert ds['wind_from_direction'].max() <= 360


def test_merge_netcdf_to_dataset_area_matches_the_average4_node_series(area: Callable[..., xr.Dataset]) -> None:
    """The area values at a node equal that node's series in the four-node average."""
    area_ds, average = area(), _average4()
    for node in range(4):
        node_lat, node_lon = float(average['node_lat'][node]), float(average['node_lon'][node])
        at_node = area_ds['ua'].sel(lat=node_lat, lon=node_lon, method='nearest')
        np.testing.assert_allclose(at_node.to_numpy(), average['ua_node'].isel(node=node).to_numpy())


def test_merge_netcdf_to_dataset_area_orog_is_a_grid_variable(area: Callable[..., xr.Dataset]) -> None:
    """With the orog grid, orog is a (lat, lon) variable in m."""
    ds = area(fixed_pattern='grid_AUS-11_fx_area_orog.nc')

    assert ds['orog'].dims == ('lat', 'lon')
    assert ds['orog'].attrs['units'] == 'm'


def test_merge_netcdf_to_dataset_area_keeps_timestamps_and_records_versions(area: Callable[..., xr.Dataset]) -> None:
    """Mean variables stay on time_mean at :30; versions are recorded per variable."""
    ds = area(versions={'tas': 'v20231001', 'pr': 'v20240516', 'ua50m': 'v20231001'})

    assert _minutes(ds['time_mean'])[:2] == ['2023-01-01T00:30', '2023-01-01T01:30']
    assert _minutes(ds['time_bnds'].to_numpy()[0]) == ['2023-01-01T00:00', '2023-01-01T01:00']
    assert ds['tas'].attrs['barra2_version'] == 'v20231001'
    assert ds['ua'].attrs['barra2_version'] == 'v20231001'
    assert ds.attrs['barra2_version'] == 'v20231001, v20240516'


def test_merge_netcdf_to_dataset_area_of_one_instantaneous_scalar(tmp_path: Path) -> None:
    """An area without winds or mean variables has just the scalar on (time, lat, lon)."""
    _write_grid(tmp_path / 'g_AUS-11_1hr_area_tas_20230101_20230101.nc', 'tas', np.full((2, 2, 2), 290.0), 'K')

    ds = merge_netcdf_to_dataset(str(tmp_path), '*.nc', domain='AUS-11', freq='1hr', node_selection='area')

    assert list(ds.data_vars) == ['tas']
    assert 'height' not in ds.coords
    assert 'time_mean' not in ds.coords
    assert ds['tas'].dims == ('time', 'lat', 'lon')


def test_merge_netcdf_to_dataset_area_round_trip(area: Callable[..., xr.Dataset], tmp_path: Path) -> None:
    """Writing and reading back keeps the grid and values."""
    ds = area(fixed_pattern='grid_AUS-11_fx_area_orog.nc')
    ds.to_netcdf(tmp_path / 'area.nc')

    with xr.open_dataset(tmp_path / 'area.nc') as back:
        np.testing.assert_allclose(back['wind_speed'].to_numpy(), ds['wind_speed'].to_numpy())
        assert back.sizes['lat'] == 3


# endregion


# region merge_netcdf_to_dataset (polygon)
# the grid fixtures hold the nodes at lat -23.65, -23.54, -23.43 and lon 133.25, 133.36, 133.47; the two-cells boundary
# covers equal parts of the cells of (-23.54, 133.36) and (-23.54, 133.47), the sub-cell one lies in the first
TWO_CELLS = read_polygon(DATA / 'boundary_two_cells.geojson')
SUB_CELL = read_polygon(DATA / 'boundary_sub_cell.geojson')


@pytest.fixture
def boundary(tmp_path: Path) -> Callable[..., xr.Dataset]:
    """Merge the bounding-box fixtures as an area selected by a boundary."""
    for file in DATA.glob('grid_*.nc'):
        shutil.copy(file, tmp_path / file.name.replace('_average4_', '_area_'))

    def merge(
        polygon: Polygon | None = TWO_CELLS, *, node_mean: bool = False, fixed_pattern: str | None = None
    ) -> xr.Dataset:
        return merge_netcdf_to_dataset(
            str(tmp_path),
            'grid_AUS-11_1hr_area_*.nc',
            domain='AUS-11',
            freq='1hr',
            node_selection='area',
            fixed_pattern=fixed_pattern,
            polygon=polygon,
            node_mean=node_mean,
        )

    return merge


def _node(ds: xr.DataArray, lat: float, lon: float) -> xr.DataArray:
    """The series at one node of an area Dataset."""
    return ds.sel(lat=lat, lon=lon, method='nearest')


def test_merge_netcdf_to_dataset_polygon_uses_only_the_nodes_whose_cell_it_overlaps(
    boundary: Callable[..., xr.Dataset],
) -> None:
    """Every variable is missing at the nodes the boundary does not touch, and kept at the two it does."""
    ds = boundary()

    used = ds['cell_overlap'].to_numpy() > 0
    assert used.sum() == 2
    assert ds['cell_overlap'].sel(lat=-23.54, lon=[133.36, 133.47], method='nearest').to_numpy().tolist() == (
        pytest.approx([(0.06 * 0.085) / 0.0121] * 2)
    )
    for name in ('ua', 'tas', 'wind_speed'):
        has_data = ds[name].notnull().any([d for d in ds[name].dims if d not in ('lat', 'lon')]).to_numpy()
        assert (has_data == used).all()
    assert ds.attrs['node_selection'] == 'area'


def test_merge_netcdf_to_dataset_polygon_weights_sum_to_one_and_follow_the_overlap(
    boundary: Callable[..., xr.Dataset],
) -> None:
    """Equal cell overlap at the same latitude gives equal weights of one half; unused nodes have none."""
    ds = boundary()

    assert float(ds['cell_weight'].sum()) == pytest.approx(1.0)
    assert sorted(ds['cell_weight'].to_numpy().ravel().tolist())[-2:] == pytest.approx([0.5, 0.5])
    assert ds['cell_weight'].attrs['units'] == '1'


def test_merge_netcdf_to_dataset_polygon_describes_the_boundary_in_attributes(
    boundary: Callable[..., xr.Dataset],
) -> None:
    """The source, size, centroid, whether it is sub-cell, and how much of it the used cells cover."""
    ds = boundary()

    assert ds.attrs['boundary_source'] == 'boundary_two_cells.geojson'
    assert (ds.attrs['boundary_vertices'], ds.attrs['boundary_holes'], ds.attrs['boundary_sub_cell']) == (4, 0, 0)
    assert ds.attrs['boundary_covered'] == pytest.approx(1.0)
    assert ds.attrs['boundary_centroid_lat'] == pytest.approx(-23.54)
    assert ds.attrs['boundary_centroid_lon'] == pytest.approx(133.415)
    assert ds.attrs['boundary_area_km2'] == pytest.approx(
        0.06 * 0.17 * 111.195**2 * np.cos(np.radians(23.54)), rel=1e-6
    )


def test_merge_netcdf_to_dataset_polygon_masks_the_orog_grid_too(boundary: Callable[..., xr.Dataset]) -> None:
    """The altitude grid is kept only at the used nodes."""
    ds = boundary(fixed_pattern='grid_AUS-11_fx_area_orog.nc')

    assert int(ds['orog'].notnull().sum()) == 2


def test_merge_netcdf_to_dataset_polygon_site_mean_is_the_hybrid_weighted_mean(
    boundary: Callable[..., xr.Dataset],
) -> None:
    """Speed is the mean of the nodes' speeds, components are mean components, direction comes from those."""
    ds = boundary(node_mean=True)
    full = boundary(None)
    first, second = _node(full, -23.54, 133.36), _node(full, -23.54, 133.47)

    np.testing.assert_allclose(
        ds['wind_speed_site_mean'].to_numpy(), ((first['wind_speed'] + second['wind_speed']) / 2).to_numpy()
    )
    np.testing.assert_allclose(ds['ua_site_mean'].to_numpy(), ((first['ua'] + second['ua']) / 2).to_numpy())
    np.testing.assert_allclose(ds['tas_site_mean'].to_numpy(), ((first['tas'] + second['tas']) / 2).to_numpy())
    east, north = ds['ua_site_mean'], ds['va_site_mean']
    expected = np.mod(180 + np.rad2deg(np.arctan2(east, north)), 360)
    np.testing.assert_allclose(ds['wind_from_direction_site_mean'].to_numpy(), expected.to_numpy())
    assert (ds['wind_speed_site_mean'].to_numpy() >= np.hypot(east, north).to_numpy() - 1e-12).all()
    assert ds['ua_site_mean'].dims == ('time', 'height')
    assert ds['pr_site_mean'].dims == ('time_mean',)


def test_merge_netcdf_to_dataset_polygon_site_mean_says_which_mean_it_is(boundary: Callable[..., xr.Dataset]) -> None:
    """cell_methods names the scalar mean of speed and the vector mean of the components and direction."""
    ds = boundary(node_mean=True)

    assert ds['wind_speed_site_mean'].attrs['cell_methods'].endswith('site: mean (scalar)')
    assert ds['ua_site_mean'].attrs['cell_methods'].endswith('site: mean (vector)')
    assert ds['wind_from_direction_site_mean'].attrs['cell_methods'].endswith('site: mean (vector)')
    assert ds['tas_site_mean'].attrs['cell_methods'].endswith('site: mean')
    assert 'ua_site_mean' not in boundary()


def test_merge_netcdf_to_dataset_polygon_without_a_wind_pair_has_no_direction_mean(tmp_path: Path) -> None:
    """With only a temperature grid there is a mean of it and nothing to derive a direction from."""
    shutil.copy(DATA / 'grid_AUS-11_1hr_average4_tas_20230101_20230103.nc', tmp_path / 'g_AUS-11_1hr_area_tas_x.nc')

    ds = merge_netcdf_to_dataset(
        str(tmp_path), 'g_AUS-11_1hr_area_*.nc', domain='AUS-11', freq='1hr', node_selection='area',
        polygon=TWO_CELLS, node_mean=True,
    )  # fmt: skip

    assert 'tas_site_mean' in ds
    assert 'wind_from_direction_site_mean' not in ds


def test_merge_netcdf_to_dataset_polygon_smaller_than_a_cell_uses_the_node_holding_its_centroid(
    boundary: Callable[..., xr.Dataset],
) -> None:
    """A sub-cell boundary uses one node with weight 1, though it also overlaps a neighbouring cell."""
    ds = boundary(SUB_CELL, node_mean=True)

    assert ds.attrs['boundary_sub_cell'] == 1
    assert int((ds['cell_weight'] > 0).sum()) == 1
    assert float(_node(ds['cell_weight'], -23.54, 133.36)) == 1.0
    assert float(_node(ds['cell_overlap'], -23.54, 133.36)) == pytest.approx(0.04 * 0.015 / 0.0121)
    assert ds.attrs['boundary_covered'] == pytest.approx(0.75)
    np.testing.assert_allclose(ds['ua_site_mean'].to_numpy(), _node(boundary(None)['ua'], -23.54, 133.36).to_numpy())


def test_merge_netcdf_to_dataset_polygon_centroid_on_a_cell_edge_takes_the_lower_node(
    boundary: Callable[..., xr.Dataset],
) -> None:
    """A centroid exactly between two nodes goes to the lower latitude."""
    edge = Polygon(((-23.60, 133.36), (-23.60, 133.38), (-23.59, 133.38), (-23.59, 133.36)))

    ds = boundary(edge)

    assert float(_node(ds['cell_weight'], -23.65, 133.36)) == 1.0
    assert int((ds['cell_weight'] > 0).sum()) == 1


def test_merge_netcdf_to_dataset_polygon_leaving_the_grid_covers_less_of_itself(
    boundary: Callable[..., xr.Dataset],
) -> None:
    """A boundary partly outside the downloaded grid still works, and says how much of it the used cells cover."""
    wide = Polygon(((-23.60, 133.30), (-23.60, 133.80), (-23.50, 133.80), (-23.50, 133.30)))

    ds = boundary(wide)

    assert 0.3 < ds.attrs['boundary_covered'] < 0.7


def test_merge_netcdf_to_dataset_polygon_outside_the_grid_raises(boundary: Callable[..., xr.Dataset]) -> None:
    """A boundary that overlaps none of the nodes is an error naming the domain."""
    far = Polygon(((-10, 100), (-10, 101), (-9, 101), (-9, 100)))

    with pytest.raises(ValueError, match='overlaps no BARRA2 node of AUS-11'):
        boundary(far)


def test_merge_netcdf_to_dataset_polygon_needs_an_area(nodes_folder: Path) -> None:
    """A polygon selects the nodes of an area and nothing else."""
    with pytest.raises(ValueError, match='selects the nodes of an area'):
        merge_netcdf_to_dataset(
            str(nodes_folder),
            'site_AUS-11_1hr_nodes_*.nc',
            domain='AUS-11',
            freq='1hr',
            requested=GRID_SITE,
            node_selection='nodes',
            nodes=CHOSEN,
            polygon=TWO_CELLS,
        )


def test_merge_netcdf_to_dataset_node_mean_of_an_area_needs_a_polygon(boundary: Callable[..., xr.Dataset]) -> None:
    """A mean needs weights, which only a boundary gives."""
    with pytest.raises(ValueError, match='needs a polygon'):
        boundary(None, node_mean=True)


# endregion


# region dataset_to_frames
def test_dataset_to_frames_nearest_matches_the_csv_route() -> None:
    """A nearest-node Dataset gives the frame the csv route gives: same columns, values and timestamps."""
    ds = merge_netcdf_to_dataset(str(DATA), 'fixture_AUS-11_1hr_*.nc', domain='AUS-11', freq='1hr', requested=SITE)
    csv = convert_wind_components(merge_csvs_to_df(str(DATA), 'fixture_AUS-11_1hr_*.csv', BARRA2_INDEX))

    frames = dataset_to_frames(ds)

    assert list(frames) == ['nearest']
    frame = frames['nearest']
    assert set(frame.columns) == set(csv.columns)
    assert list(frame.columns[:4]) == BARRA2_INDEX
    merged = frame.merge(csv, on='time', suffixes=('_nc', '_csv'))
    assert len(merged) == len(csv)
    for column in csv.columns.difference(BARRA2_INDEX):
        np.testing.assert_allclose(merged[f'{column}_nc'].to_numpy(), merged[f'{column}_csv'].to_numpy())


def test_dataset_to_frames_average4_gives_the_average_and_one_frame_per_node() -> None:
    """The average and the four node series each get a frame, so each can be written to its own file."""
    ds = _average4()

    frames = dataset_to_frames(ds)

    assert list(frames) == ['average4', 'node1', 'node2', 'node3', 'node4']
    assert frames['average4'].loc[0, 'station'] == 'average4'
    assert frames['node2'].loc[0, 'station'] == 'node2'
    assert frames['node2'].loc[0, BARRA2_INDEX[2]] == float(ds['node_lat'][1])
    column = 'ua50m[unit="m s-1"]'
    np.testing.assert_allclose(
        frames['node3'][column].dropna().to_numpy(), ds['ua_node'].isel(node=2, height=0).to_numpy()
    )
    np.testing.assert_allclose(frames['average4'][column].dropna().to_numpy(), ds['ua'].isel(height=0).to_numpy())


def test_dataset_to_frames_keeps_the_half_hour_rows() -> None:
    """Mean variables keep their :30 timestamps in their own rows, with blanks, as in the csv route."""
    frame = dataset_to_frames(_average4())['average4']

    assert frame['time'].iloc[1] == '2023-01-01T00:30:00Z'
    assert pd.isna(frame['ua50m[unit="m s-1"]'].iloc[1])
    assert not pd.isna(frame['pr[unit="kg m-2 s-1"]'].iloc[1])


def test_dataset_to_frames_refuses_an_area(area: Callable[..., xr.Dataset]) -> None:
    """An area is a grid and can't be written as csv."""
    with pytest.raises(ValueError, match='cannot be written as csv'):
        dataset_to_frames(area())


# endregion


# region write_csv
def _nearest() -> xr.Dataset:
    """The nearest-node fixtures with an altitude and versions, for the header."""
    return _fixture_dataset(orog=747.6, versions={'ua50m': 'v20240516', 'va50m': 'v20240516', 'tas': 'v20231001'})


def _average_with_orog() -> xr.Dataset:
    """The four-node average with the orog grid, for the header."""
    return _average4(fixed_pattern='grid_AUS-11_fx_average4_orog.nc')


def test_write_csv_names_files_by_frame_and_dates(tmp_path: Path) -> None:
    """One file per frame, named for the site, domain, time step, frame and the Dataset's first and last dates."""
    paths = write_csv(_average_with_orog(), tmp_path, 'site')

    assert [path.name for path in paths] == [
        f'site_AUS-11_1hr_{name}_20230101_20230103.csv' for name in ('average4', 'node1', 'node2', 'node3', 'node4')
    ]
    assert all(path.exists() and path.parent == tmp_path for path in paths)


@pytest.mark.parametrize('dataset', [_nearest, _average_with_orog], ids=['nearest', 'average4'])
def test_write_csv_round_trips_each_frame_and_header(dataset: Callable[[], xr.Dataset], tmp_path: Path) -> None:
    """read_csv gives back each frame of dataset_to_frames and the header written for it."""
    ds = dataset()
    frames = dataset_to_frames(ds)

    paths = write_csv(ds, tmp_path, 'site')

    assert len(paths) == len(frames)
    for path, (name, frame) in zip(paths, frames.items(), strict=True):
        read, header = read_csv(path)
        pd.testing.assert_frame_equal(read, frame)
        assert header == dict(_csv_header(ds, name))


def test_write_csv_nearest_header_values_come_from_the_dataset(tmp_path: Path) -> None:
    """The header repeats the Dataset's attributes and coordinates, and the nearest node's distance."""
    ds = _nearest()

    (path,) = write_csv(ds, tmp_path, 'site')
    _, header = read_csv(path)

    assert list(header) == [
        'File',
        'Source',
        'Domain',
        'Time step',
        'Node selection',
        'Latitude',
        'Longitude',
        'Elevation',
        'Elevation units',
        'Requested latitude',
        'Requested longitude',
        'Distance to node',
        'Distance units',
        'Time zone',
        'Time stamp',
        'Dataset versions',
        'Downloaded',
        'Created by',
        'License',
        'References',
        'Header lines',
    ]
    assert header['Source'] == ds.attrs['source']
    assert (header['Domain'], header['Time step'], header['Node selection']) == ('AUS-11', '1hr', 'nearest')
    assert float(header['Latitude']) == float(ds['lat'])
    assert float(header['Longitude']) == float(ds['lon'])
    assert float(header['Elevation']) == 747.6
    assert (header['Elevation units'], header['Distance units'], header['Time zone']) == ('m', 'km', 'UTC')
    assert float(header['Requested latitude']) == SITE.lat
    assert float(header['Requested longitude']) == SITE.lon
    assert float(header['Distance to node']) == pytest.approx(
        float(distance_km(SITE.lat, SITE.lon, float(ds['lat']), float(ds['lon'])))
    )
    assert header['Dataset versions'] == ds.attrs['barra2_version'] == 'v20231001, v20240516'
    assert header['Downloaded'] == ds.attrs['downloaded']
    assert header['Created by'].startswith('barra2-dl ')
    assert (header['License'], header['References']) == (ds.attrs['license'], ds.attrs['references'])
    assert header['Header lines'] == '22'


def test_write_csv_average_and_node_files_have_their_own_positions(tmp_path: Path) -> None:
    """The average sits at the requested site with four Node lines; each node file has its node's position."""
    ds = _average_with_orog()

    paths = write_csv(ds, tmp_path, 'site')
    headers = [read_csv(path)[1] for path in paths]

    average = headers[0]
    assert float(average['Latitude']) == float(ds['lat']) == GRID_SITE.lat
    assert float(average['Elevation']) == float(ds.attrs['orog'])
    assert average['Distance to node'] == ''
    assert average['Header lines'] == '26'
    assert [key for key in average if key.startswith('Node ') and key != 'Node selection'] == [
        'Node 1',
        'Node 2',
        'Node 3',
        'Node 4',
    ]
    for k, header in enumerate(headers[1:]):
        assert (float(header['Latitude']), float(header['Longitude'])) == (
            float(ds['node_lat'][k]),
            float(ds['node_lon'][k]),
        )
        assert float(header['Elevation']) == float(ds['node_orog'][k])
        assert float(header['Distance to node']) == float(ds['node_distance'][k])
        assert (header['Requested latitude'], header['Header lines']) == (average['Requested latitude'], '22')
        assert not any(key.startswith('Node ') and key != 'Node selection' for key in header)
        node_line = average[f'Node {k + 1}']
        assert node_line.startswith(f'lat {float(ds["node_lat"][k])!r}; lon {float(ds["node_lon"][k])!r}; distance ')
        assert f'weight {float(ds["node_weight"][k])!r}; orog {float(ds["node_orog"][k])!r} m' in node_line


def test_write_csv_unknown_values_are_empty_and_the_layout_is_stable(tmp_path: Path) -> None:
    """Without an orog grid the Elevation value is empty, but the keys are the same."""
    with_orog, without = _average_with_orog(), _average4()

    header_with = read_csv(write_csv(with_orog, tmp_path, 'a')[0])[1]
    header_without = read_csv(write_csv(without, tmp_path, 'b')[0])[1]

    assert list(header_without) == list(header_with)
    assert header_without['Elevation'] == ''
    assert 'orog  m' in header_without['Node 1']


def test_write_csv_header_lines_skips_to_the_frame_in_plain_pandas(tmp_path: Path) -> None:
    """Pandas with skiprows=Header lines reads the same frame as read_csv."""
    for ds in (_nearest(), _average_with_orog()):
        path = write_csv(ds, tmp_path, 'site')[0]
        frame, header = read_csv(path)

        pd.testing.assert_frame_equal(pd.read_csv(path, skiprows=int(header['Header lines'])), frame)


def test_write_csv_header_false_writes_the_bare_frame(tmp_path: Path) -> None:
    """header=False is byte for byte what frame.to_csv(path, index=False) writes, and reads back with no header."""
    ds = _nearest()
    expected = tmp_path / 'expected.csv'
    dataset_to_frames(ds)['nearest'].to_csv(expected, index=False)

    (path,) = write_csv(ds, tmp_path, 'site', header=False)
    frame, header = read_csv(path)

    assert path.read_bytes() == expected.read_bytes()
    assert header == {}
    pd.testing.assert_frame_equal(frame, dataset_to_frames(ds)['nearest'])


def test_write_csv_refuses_an_area(area: Callable[..., xr.Dataset], tmp_path: Path) -> None:
    """An area is a grid and can't be written as csv; nothing is written."""
    with pytest.raises(ValueError, match='cannot be written as csv'):
        write_csv(area(), tmp_path, 'site')

    assert list(tmp_path.glob('*.csv')) == []


# endregion


# region write_df_csv
def _converted_fixtures() -> pd.DataFrame:
    """The csv fixtures merged, with wind and units converted, as the csv example writes them."""
    df = merge_csvs_to_df(str(DATA), 'fixture_AUS-11_1hr_*.csv', BARRA2_INDEX)
    return convert_units(convert_wind_components(df))


def test_write_df_csv_has_the_header_the_netcdf_route_gives(tmp_path: Path) -> None:
    """The csv route's file opens with the same header as write_csv gives the same data and inputs."""
    versions = {'ua50m': 'v20240516', 'va50m': 'v20240516', 'tas': 'v20231001'}
    path = write_df_csv(
        _converted_fixtures(), tmp_path / 'a.csv', domain='AUS-11', freq='1hr', requested=SITE, orog=747.6,
        versions=versions,
    )  # fmt: skip
    (netcdf_path,) = write_csv(_nearest(), tmp_path, 'b')

    assert read_csv(path)[1] == read_csv(netcdf_path)[1]
    assert read_csv(path)[1]['Header lines'] == '22'


def test_write_df_csv_writes_the_frame_unchanged(tmp_path: Path) -> None:
    """The columns, units and rows after the header are the frame's own, converted units included."""
    df = _converted_fixtures()

    path = write_df_csv(df, tmp_path / 'a.csv', domain='AUS-11', freq='1hr', requested=SITE)
    frame, header = read_csv(path)

    pd.testing.assert_frame_equal(frame, df)
    assert 'tas[unit="degC"]' in frame.columns
    assert header['Elevation'] == ''
    assert header['Dataset versions'] == 'latest'


def test_write_df_csv_rejects_more_than_one_node(tmp_path: Path) -> None:
    """A frame of two nodes can't take one node's header; nothing is written."""
    df = pd.concat(
        [_frame(['2023-01-01T00:00:00Z'], x=[1.0]), _frame(['2023-01-01T01:00:00Z'], x=[2.0])], ignore_index=True
    )
    df.loc[df.index[-1], 'latitude[unit="degrees_north"]'] = -30.0

    with pytest.raises(ValueError, match='Expected one node'):
        write_df_csv(df, tmp_path / 'a.csv', domain='AUS-11', freq='1hr', requested=SITE)

    assert list(tmp_path.iterdir()) == []


# endregion


# region read_csv
def test_read_csv_without_header_gives_an_empty_dict(tmp_path: Path) -> None:
    """A csv route file, which starts with the time column, is read whole."""
    path = tmp_path / 'a.csv'
    pd.DataFrame({'time': ['2023-01-01T00:00:00Z'], 'x': [1.5]}).to_csv(path, index=False)

    frame, header = read_csv(path)

    assert header == {}
    assert frame.to_dict('list') == {'time': ['2023-01-01T00:00:00Z'], 'x': [1.5]}


def test_read_csv_reads_quoted_values_and_the_frame_after_the_blank_line(tmp_path: Path) -> None:
    """Values with commas are unquoted, a key with no value is empty, and the frame starts after the blank line."""
    path = tmp_path / 'a.csv'
    path.write_text('File,barra2-dl output\nSource,"BARRA2, via NCI"\nElevation,\n\ntime,x\n2023-01-01T00:00:00Z,2.5\n')

    frame, header = read_csv(path)

    assert header == {'File': 'barra2-dl output', 'Source': 'BARRA2, via NCI', 'Elevation': ''}
    assert frame.to_dict('list') == {'time': ['2023-01-01T00:00:00Z'], 'x': [2.5]}


def test_read_csv_header_without_a_frame_raises(tmp_path: Path) -> None:
    """A header that never reaches its blank line leaves no frame to read."""
    path = tmp_path / 'a.csv'
    path.write_text('File,barra2-dl output\nSource,BARRA2\n')

    with pytest.raises(pd.errors.EmptyDataError):
        read_csv(path)


def test_read_csv_missing_file(tmp_path: Path) -> None:
    """A missing file raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        read_csv(tmp_path / 'missing.csv')


# endregion
# endregion


# region Helpers
# region _split_height
@pytest.mark.parametrize(
    ('name', 'expected'),
    [
        ('uas', ('ua', 10)),
        ('ua10m', ('ua', 10)),
        ('va250m', ('va', 250)),
        ('ua1500m', ('ua', 1500)),
        ('v50m', ('wind_speed', 50)),
        ('v100m_phi_met', ('wind_from_direction', 100)),
        ('tas', (None, 0)),
        ('ua850', (None, 0)),
    ],
)
def test_split_height_maps_names_to_quantity_and_height(name: str, expected: tuple[str | None, int]) -> None:
    """Height wind names map to their quantity; pressure levels such as ua850 and other variables do not."""
    assert _split_height(name) == expected


# endregion


# region _merge_suffix_columns
def test_merge_suffix_columns_prefers_x_then_fills_from_y() -> None:
    """Suffixed pairs collapse to the base column, taking _x first and _y where _x is missing."""
    df = pd.DataFrame({'time': [1, 2, 3], 'a_x': [1.0, None, 3.0], 'a_y': [9.0, 2.0, 9.0]})

    result = _merge_suffix_columns(df)

    assert sorted(result.columns) == ['a', 'time']
    assert result['a'].tolist() == [1.0, 2.0, 3.0]


def test_merge_suffix_columns_leaves_unpaired_columns() -> None:
    """A suffixed column without a partner, and plain columns, are left alone."""
    df = pd.DataFrame({'time': [1], 'a_x': [1.0], 'b': [2.0]})

    result = _merge_suffix_columns(df)

    assert sorted(result.columns) == ['a_x', 'b', 'time']


def test_merge_suffix_columns_custom_suffixes() -> None:
    """Custom suffixes are honoured."""
    df = pd.DataFrame({'a_left': [1.0, None], 'a_right': [5.0, 2.0]})

    result = _merge_suffix_columns(df, suffix_x='_left', suffix_y='_right')

    assert result.columns.tolist() == ['a']
    assert result['a'].tolist() == [1.0, 2.0]


# endregion
# endregion
