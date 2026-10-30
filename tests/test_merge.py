"""This module contains the barra2.merge test function(s)."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from barra2_dl.convert import convert_wind_components
from barra2_dl.globals import BARRA2_INDEX
from barra2_dl.mapping import LatLonPoint
from barra2_dl.merge import (
    _merge_suffix_columns,
    _split_height,
    merge_csvs_to_df,
    merge_netcdf_to_dataset,
    read_fixed_fields,
    to_dataset,
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
    with pytest.raises(ValueError, match='No netCDF files'):
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
