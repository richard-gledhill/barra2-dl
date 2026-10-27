"""This module contains the barra2.merge test function(s)."""

from pathlib import Path

import pandas as pd

from barra2_dl.merge import _merge_suffix_columns, merge_csvs_to_df


# region Test helpers
def _write_csv(folder: Path, name: str, data: dict) -> None:
    pd.DataFrame(data).to_csv(folder / name, index=False)


# endregion


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
