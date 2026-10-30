"""This module contains the barra2 merge function(s)."""

import logging
import sys
from pathlib import Path

import pandas as pd

from barra2_dl.globals import BARRA2_FIXED_FREQ, BARRA2_INDEX

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

__all__ = [
    'merge_csvs_to_df',
    'read_fixed_fields',
]


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

    Args:
        filein_folder (str): Folder holding the downloaded files, e.g. the cache folder.
        filename_pattern (str): Filename matching pattern for the fx files, e.g. f'{prefix}_AUS-11_fx_*.csv'.

    Returns:
        dict[str, float]: Each field's column header and value, e.g. {'orog[unit="m"]': 33.05}.
    """
    fields: dict[str, float] = {}
    for file in sorted(Path(filein_folder).glob(filename_pattern)):
        row = pd.read_csv(file).iloc[0]
        fields |= {str(column): float(row[column]) for column in row.index if column not in BARRA2_INDEX}
    return fields


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
