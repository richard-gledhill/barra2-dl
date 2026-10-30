"""This module contains the barra2 convert function(s)."""

import logging
import sys
from typing import overload

import numpy as np
import pandas as pd

from barra2_dl.globals import BARRA2_VAR_ALIASES, BARRA2_WIND_VARS

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

__all__ = [
    'calculate_wind_direction',
    'calculate_wind_speed',
    'convert_units',
    'convert_wind_components',
    'wind_components_to_direction',
    'wind_components_to_speed',
]

# units convert_units changes: BARRA2 unit -> (new unit, conversion)
_UNIT_CONVERSIONS = {
    'K': ('degC', lambda values: values - 273.15),
    'Pa': ('hPa', lambda values: values / 100),
    'kg m-2 s-1': ('mm h-1', lambda values: values * 3600),
}


def calculate_wind_speed(
    u: float | int,
    v: float | int,
) -> float:
    """Calculate the wind speed from u and v components.

    Args:
        u (float | int): The u component of the wind vector.
        v (float | int): The v component of the wind vector.

    Returns:
        Wind speed. If both u and v are zero, it returns 0.0.
    """
    if u == 0 and v == 0:
        return 0.0
    return float(np.sqrt(u**2 + v**2))


@overload
def wind_components_to_speed(ua: float | int, va: float | int) -> float: ...
@overload
def wind_components_to_speed(ua: list[float | int], va: list[float | int]) -> list[float]: ...
def wind_components_to_speed(
    ua: float | int | list[float | int],
    va: float | int | list[float | int],
) -> float | list[float]:
    """Convert wind components ua and va to wind speed v.

    Args:
        ua (float | int | list[float | int]): The u-component of the wind.
        va (float | int | list[float | int]): The v-component of the wind.

    Returns:
        float | list[float]: The calculated wind speed.

    Raises:
        ValueError: If the input types do not match or if they are neither list[float] nor list[int] nor float.
    """
    if isinstance(ua, (float, int)) and isinstance(va, (float, int)):
        if ua == 0 and va == 0:
            return 0
        return calculate_wind_speed(ua, va)
    elif isinstance(ua, list) and isinstance(va, list):
        if not all(isinstance(num, (float, int)) for num in ua + va):
            raise ValueError('All elements in both lists must be either float or int.')
        if len(ua) != len(va):
            raise ValueError('Both lists must be of the same length.')
        return [calculate_wind_speed(u, v) for u, v in zip(ua, va, strict=True)]
    else:
        raise ValueError('Both arguments must be either both float/int or both lists of float/int.')


def calculate_wind_direction(
    u: float | int,
    v: float | int,
) -> float:
    """Calculate angular meteorological wind direction.

    Args:
        u (float | int): The u component of the wind vector, which can be a float or an int.
        v (float | int): The v component of the wind vector, which can be a float or an int.

    Returns:
        The Calculated wind direction in degrees. If both u and v are zero, it returns 0.0.
    """
    if u == 0 and v == 0:
        return 0
    return float(np.mod(180 + np.rad2deg(np.arctan2(u, v)), 360))


@overload
def wind_components_to_direction(ua: float | int, va: float | int) -> float: ...
@overload
def wind_components_to_direction(ua: list[float | int], va: list[float | int]) -> list[float]: ...
def wind_components_to_direction(
    ua: float | int | list[float | int],
    va: float | int | list[float | int],
) -> float | list[float]:
    """Convert wind components ua and va to wind direction phi.

    Args:
        ua (float | int | List[float | int]): The u-component of the wind.
        va (float | int | List[float | int]): The v-component of the wind.

    Returns:
        The calculated wind speed direction.

    Raises:
        ValueError: If the input types and incorrect or do not match or if lists of different lengths are provided.
    """
    if isinstance(ua, (float, int)) and isinstance(va, (float, int)):
        return calculate_wind_direction(ua, va)
    elif isinstance(ua, list) and isinstance(va, list):
        if not all(isinstance(num, (float, int)) for num in ua + va):
            raise ValueError('All elements in both lists must be either float or int.')
        if len(ua) != len(va):
            raise ValueError('Both lists must be of the same length.')
        return [calculate_wind_direction(u, v) for u, v in zip(ua, va, strict=True)]
    else:
        raise ValueError('Both arguments must be either both float/int or both lists of float/int.')


def convert_wind_components(
    df_merged: pd.DataFrame,
) -> pd.DataFrame:
    """Converts columns of wind components ua* and va* to v and phi.

    Columns are matched on their exact variable name (the text before '[unit=...]'), and output columns are named
    from the height in BARRA2_WIND_VARS. The 10 m server names uas and vas are renamed to their BARRA2_VAR_ALIASES
    (ua10m, va10m), so every height is named alike for import into other software.

    Args:
        df_merged: Dataframe with wind data ua and va columns to convert to v and phi

    Returns:
        Dataframe: With additional converted columns

    Raises:
        ValueError: If there are not wind components to convert.

    Todo:
        Add checks for ua and va components
        Update function as following leverages global variables
    """
    # map each variable name to its full column header, e.g. 'ua50m' -> 'ua50m[unit="m s-1"]'
    columns = {str(column).split('[', 1)[0]: column for column in df_merged.columns}

    # loop through all possible wind components
    df_processed = df_merged

    for ua, va, height in BARRA2_WIND_VARS:
        if ua in columns and va in columns:
            ua_values = df_merged[columns[ua]].tolist()
            va_values = df_merged[columns[va]].tolist()

            df_processed_v = pd.DataFrame(
                wind_components_to_speed(ua_values, va_values),
                columns=[f'v{height}m[unit="m s-1"]'],
            )

            # instantiate a temp dataframe for the phi value
            df_processed_phi_met = pd.DataFrame(
                wind_components_to_direction(ua_values, va_values),
                columns=[f'v{height}m_phi_met[unit="degrees"]'],
            )

            # Merge the current variable DataFrame with the combined DataFrame
            df_processed = df_processed.join(df_processed_v)
            df_processed = df_processed.join(df_processed_phi_met)

            sys.stdout.write(f'Converted: {columns[ua]}, {columns[va]}')
            sys.stdout.write('\n')

    # rename server names to their aliases, keeping the unit suffix, e.g. uas[unit="m s-1"] -> ua10m[unit="m s-1"]
    renames = {
        columns[server]: str(columns[server]).replace(server, alias, 1)
        for alias, server in BARRA2_VAR_ALIASES.items()
        if server in columns
    }
    df_processed = df_processed.rename(columns=renames)

    # todo check if df_processed was updated
    # if df_processed == df_merged:
    #     raise ValueError('No ua or va values in the dataframe to convert.')

    return df_processed


def convert_units(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """Convert BARRA2 SI units to those common in wind and weather analysis.

    An opt-in step: K to degC, Pa to hPa and kg m-2 s-1 (precipitation and snowfall flux) to mm h-1. Columns are
    matched on their unit suffix, which is renamed with the values, e.g. tas[unit="K"] becomes tas[unit="degC"].
    Other columns are left as they are.

    Args:
        df: DataFrame with BARRA2 columns named <var>[unit="<unit>"], e.g. from merge_csvs_to_df.

    Returns:
        DataFrame: A copy with the converted columns; the input is not modified.

    Examples:
        >>> convert_units(pd.DataFrame({'tas[unit="K"]': [293.15], 'ps[unit="Pa"]': [101325.0]})).round(2).to_dict()
        {'tas[unit="degC"]': {0: 20.0}, 'ps[unit="hPa"]': {0: 1013.25}}
    """
    df_converted = df.copy()
    renames = {}
    for column in df.columns:
        for unit, (new_unit, conversion) in _UNIT_CONVERSIONS.items():
            if str(column).endswith(f'[unit="{unit}"]'):
                df_converted[column] = conversion(df[column])
                renames[column] = str(column).replace(f'[unit="{unit}"]', f'[unit="{new_unit}"]')
    return df_converted.rename(columns=renames)
