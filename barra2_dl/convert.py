"""This module contains the barra2 convert function(s)."""

import logging
import sys
from typing import List, overload

import numpy as np
import pandas as pd

from barra2_dl.globals import BARRA2_WIND_VARS

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

__all__ = [
    'calculate_wind_speed',
    'wind_components_to_speed',
    'calculate_wind_direction',
    'wind_components_to_direction',
    'convert_wind_components',
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
    return np.mod(180 + np.rad2deg(np.arctan2(u, v)), 360)


@overload
def wind_components_to_direction(ua: float | int, va: float | int) -> float: ...
@overload
def wind_components_to_direction(ua: List[float | int], va: List[float | int]) -> List[float]: ...
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
        return [calculate_wind_direction(u, v) for u, v in zip(ua, va, strict=True)]
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

        if np.any(mask_ua) and np.any(mask_va):
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
