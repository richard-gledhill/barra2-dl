"""This module contains the barra2 convert function(s)."""

import logging
import sys
from typing import List

import numpy as np
import pandas as pd

from barra2_dl.globals import BARRA2_ENV_VARS, BARRA2_WIND_VARS

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

__all__ = [
    'calculate_wind_speed',
    'wind_components_to_speed',
    'calculate_wind_direction',
    'wind_components_to_direction',
    'convert_wind_components',
    'convert_temperature',
    'convert_humidity',
    'convert_pressure',
    'convert_precipitation',
    'convert_environment_variables',
]


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
    return np.sqrt(u ** 2 + v ** 2)


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
        return [calculate_wind_speed(u, v) for u, v in zip(ua, va)]
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
    return np.mod(180 + np.rad2deg(np.arctan2(u, v)), 360)


def wind_components_to_direction(
    ua: float | int | List[float | int],
    va: float | int | List[float | int],
) -> float | List[float]:
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
        return [calculate_wind_direction(u, v) for u, v in zip(ua, va)]
    else:
        raise ValueError('Both arguments must be either both float/int or both lists of float/int.')


def convert_wind_components(
    df_merged: pd.DataFrame,
) -> pd.DataFrame:
    """Converts columns of wind components ua* and va* to v and phi.

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
    # loop through all possible wind components
    df_processed = df_merged

    for tup in BARRA2_WIND_VARS:
        mask_wind_speed_h = tup[0][2:]
        mask_ua = df_merged.columns.str.contains(tup[0])  # select the ua column header
        mask_va = df_merged.columns.str.contains(tup[1])  # select the va column header

        if np.any(mask_ua == True) and np.any(mask_va == True):
            # create temporary dataframe for ua and va using the mask
            df_merged_ua = df_merged.loc[:, mask_ua]
            df_merged_va = df_merged.loc[:, mask_va]


            df_processed_v = pd.DataFrame(
                wind_components_to_speed(df_merged_ua.iloc[:, 0].tolist(), df_merged_va.iloc[:, 0].tolist()),
                columns=['v' + mask_wind_speed_h + '[unit="m s-1"]'],
            )

            # instantiate a temp dataframe for the phi value
            df_processed_phi_met = pd.DataFrame(
                wind_components_to_direction(df_merged_ua.iloc[:, 0].tolist(), df_merged_va.iloc[:, 0].tolist()),
                columns=['v' + mask_wind_speed_h + '_' + 'phi_met[unit="degrees"]'],
            )

            # Merge the current variable DataFrame with the combined DataFrame
            df_processed = df_processed.join(df_processed_v)
            df_processed = df_processed.join(df_processed_phi_met)

            sys.stdout.write('Converted: ' + df_merged_ua.columns.values[0] + ', ' + df_merged_va.columns.values[0])
            sys.stdout.write('\n')

    # todo check if df_processed was updated
    # if df_processed == df_merged:
    #     raise ValueError('No ua or va values in the dataframe to convert.')

    return df_processed


def convert_temperature(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """Convert temperature columns from Kelvin to degrees Celsius.

    Matches columns starting with 'tas' (tas, tasmax, tasmin) and creates
    new columns with values converted to degrees Celsius.

    Args:
        df: Dataframe with temperature data in Kelvin.

    Returns:
        Dataframe: With additional converted columns.
    """
    df_processed = df

    for var_prefix in ['tas', 'tasmax', 'tasmin', 'ta50m']:
        mask = df.columns.str.contains(var_prefix)
        if np.any(mask):
            col_name = df.loc[:, mask].columns[0]
            df_converted = pd.DataFrame(
                df.loc[:, col_name].values - 273.15,
                columns=[var_prefix + '_celsius[unit="degrees_C"]'],
            )
            df_processed = df_processed.join(df_converted)
            sys.stdout.write(f'Converted: {col_name} (K -> degC)')
            sys.stdout.write('\n')

    return df_processed


def convert_humidity(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """Convert specific humidity from kg/kg to g/kg.

    Matches columns starting with 'huss' and creates new columns
    with values converted to g/kg.

    Args:
        df: Dataframe with humidity data.

    Returns:
        Dataframe: With additional converted columns.
    """
    df_processed = df

    mask = df.columns.str.contains('huss')
    if np.any(mask):
        col_name = df.loc[:, mask].columns[0]
        df_converted = pd.DataFrame(
            df.loc[:, col_name].values * 1000.0,
            columns=['huss_gkg[unit="g kg-1"]'],
        )
        df_processed = df_processed.join(df_converted)
        sys.stdout.write(f'Converted: {col_name} (kg/kg -> g/kg)')
        sys.stdout.write('\n')

    return df_processed


def convert_pressure(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """Convert pressure columns from Pa to hPa.

    Matches columns starting with 'psl' or 'ps' and creates new columns
    with values converted to hPa (divide by 100).

    Args:
        df: Dataframe with pressure data in Pa.

    Returns:
        Dataframe: With additional converted columns.
    """
    df_processed = df

    for var_prefix in ['psl', 'ps']:
        mask = df.columns.str.contains(f'^{var_prefix}')
        if np.any(mask):
            col_name = df.loc[:, mask].columns[0]
            df_converted = pd.DataFrame(
                df.loc[:, col_name].values * 0.01,
                columns=[var_prefix + '_hPa[unit="hPa"]'],
            )
            df_processed = df_processed.join(df_converted)
            sys.stdout.write(f'Converted: {col_name} (Pa -> hPa)')
            sys.stdout.write('\n')

    return df_processed


def convert_precipitation(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """Convert precipitation rate from kg m-2 s-1 to mm hr-1.

    Matches columns starting with 'pr' (pr, prc, prsn) and creates new columns
    with values converted to mm/hr (multiply by 3600).

    Args:
        df: Dataframe with precipitation data.

    Returns:
        Dataframe: With additional converted columns.
    """
    df_processed = df

    for var_prefix in ['prc', 'prsn', 'pr']:
        mask = df.columns.str.contains(f'^{var_prefix}')
        if np.any(mask):
            col_name = df.loc[:, mask].columns[0]
            df_converted = pd.DataFrame(
                df.loc[:, col_name].values * 3600.0,
                columns=[var_prefix + '_mmhr[unit="mm hr-1"]'],
            )
            df_processed = df_processed.join(df_converted)
            sys.stdout.write(f'Converted: {col_name} (kg/m2/s -> mm/hr)')
            sys.stdout.write('\n')

    return df_processed


def convert_environment_variables(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """Convert environment variables to more common units using BARRA2_ENV_VARS descriptors.

    Iterates through BARRA2_ENV_VARS and applies the appropriate conversion
    for each variable found in the dataframe.

    Args:
        df: Dataframe with environment variable data.

    Returns:
        Dataframe: With additional converted columns.
    """
    df_processed = df

    for var_prefix, original_unit, converted_unit, factor, suffix in BARRA2_ENV_VARS:
        mask = df.columns.str.contains(f'^{var_prefix}')
        if np.any(mask):
            col_name = df.loc[:, mask].columns[0]

            # temperature uses offset (add factor which is negative), others use multiplier
            if factor < 0:
                converted_values = df.loc[:, col_name].values + factor
            else:
                converted_values = df.loc[:, col_name].values * factor

            df_converted = pd.DataFrame(
                converted_values,
                columns=[var_prefix + f'_{suffix}[unit="{converted_unit}"]'],
            )
            df_processed = df_processed.join(df_converted)
            sys.stdout.write(f'Converted: {col_name} ({original_unit} -> {converted_unit})')
            sys.stdout.write('\n')

    return df_processed
