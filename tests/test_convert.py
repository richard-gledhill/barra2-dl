"""This module contains the barra2.convert test function(s)."""

import numpy as np
import pandas as pd
import pytest

import barra2_dl.convert

"""
helpers_wind.calculate_wind_speed
"""


@pytest.mark.parametrize(
    ('u', 'v', 'expected'),
    [
        (1, 1, 1.4142135623730951),
        (-1, -1, 1.4142135623730951),
        (1.0, 1.0, 1.4142135623730951),
        (-1.0, -1.0, 1.4142135623730951),
        (0, 0, 0),
        (0.0, 0.0, 0.0),
    ],
)
def test_calculate_wind_speed(u: float, v: float, expected: float) -> None:
    """Test with parametrization."""
    assert barra2_dl.convert.calculate_wind_speed(u, v) == expected


"""
helpers_wind.wind_components_to_speed
"""


@pytest.mark.parametrize('ua,va,expected', [([3, 0], [4, 0], [5, 0]), ([0, 0], [0, 0], [0, 0]), (0, 0, 0), (3, 4, 5)])
def test_wind_components_to_speed(ua, va, expected):
    """Test with parametrization."""
    assert barra2_dl.convert.wind_components_to_speed(ua, va) == expected


@pytest.mark.parametrize(
    'ua,va',
    [('3', 4), (3, '4'), (['3', 0], [4, 0]), ([3, 0], ['4', 0]), ([3, 0], [4]), ([3, 0], 4), (3, [4, 0]), ('3', '4')],
)
def test_wind_components_to_speed_exception(ua, va):
    """Test with parametrization."""
    with pytest.raises(ValueError):
        barra2_dl.convert.wind_components_to_speed(ua, va)


"""
helpers_wind.calculate_wind_direction
"""


@pytest.mark.parametrize(
    'u, v, expected',
    [
        (0, 0, 0.0),  # Test when both u and v are zero
        (1, 0, 270.0),  # Test when u is non-zero and v is zero
        (0, 1, 180.0),  # Test when u is zero and v is non-zero
        (1, 1, 225.0),  # Test when both u and v are positive
        (-1, -1, 45.0),  # Test when both u and v are negative
        (-1, 1, 135.0),  # Test when u is negative and v is positive
        (1, -1, 315.0),  # Test when u is positive and v is negative
    ],
)
def test_calculate_wind_direction(u, v, expected):
    """Test with parametrization."""
    assert np.isclose(barra2_dl.convert.calculate_wind_direction(u, v), expected)


"""
helpers_wind.wind_components_to_direction
"""


@pytest.mark.parametrize('ua,va', [(2.5, 3), (7, 4)])
def test_wind_components_to_direction_float_int_input(ua, va):
    """Test the function with float and integer inputs."""
    assert isinstance(barra2_dl.convert.wind_components_to_direction(ua, va), float)


@pytest.mark.parametrize('ua,va', [([2, 3.5, 1], [4, 5, 1.5]), ([5, 2], [0.8, 3])])
def test_wind_components_to_direction_list_input(ua, va):
    """Test the function with list inputs containing both integers and floats."""
    assert isinstance(barra2_dl.convert.wind_components_to_direction(ua, va), list)
    assert all(isinstance(i, float) for i in barra2_dl.convert.wind_components_to_direction(ua, va))


@pytest.mark.parametrize('ua,va', [([2, 3], [4])])
def test_wind_components_to_direction_mismatched_list_lengths(ua, va):
    """Test the function with mismatched list lengths."""
    with pytest.raises(ValueError):
        barra2_dl.convert.wind_components_to_direction(ua, va)


@pytest.mark.parametrize('ua,va', [(2, [4]), ([2, '3'], [4, 5])])
def test_wind_components_to_direction_invalid_input(ua, va):
    """Test the function with inputs not following the correct types."""
    with pytest.raises(ValueError):
        barra2_dl.convert.wind_components_to_direction(ua, va)


def test_wind_components_to_direction_list_values():
    """List input gives the same values as the scalar function, including zero components."""
    result = barra2_dl.convert.wind_components_to_direction([0, 1, 0], [0, 0, 1])
    assert np.allclose(result, [0.0, 270.0, 180.0])


def test_wind_components_numpy_float_scalars():
    """Scalars of the numpy float type (a float subclass) are accepted."""
    assert np.isclose(barra2_dl.convert.wind_components_to_speed(np.float64(3), np.float64(4)), 5.0)
    assert np.isclose(barra2_dl.convert.wind_components_to_direction(np.float64(1), np.float64(0)), 270.0)


"""
convert.convert_wind_components
"""

UA50 = 'ua50m[unit="m s-1"]'
VA50 = 'va50m[unit="m s-1"]'
V50 = 'v50m[unit="m s-1"]'
PHI50 = 'v50m_phi_met[unit="degrees"]'


def test_convert_wind_components_adds_speed_and_direction():
    """A ua/va pair gains speed and meteorological direction columns."""
    df = pd.DataFrame({'time': [1, 2, 3], UA50: [3.0, 0.0, 1.0], VA50: [4.0, 0.0, 0.0]})

    result = barra2_dl.convert.convert_wind_components(df)

    assert list(result.columns) == ['time', UA50, VA50, V50, PHI50]
    assert np.allclose(result[V50], [5.0, 0.0, 1.0])
    assert np.allclose(result[PHI50], [216.8698976, 0.0, 270.0])


def test_convert_wind_components_multiple_heights():
    """Each height with both components present is converted independently."""
    df = pd.DataFrame(
        {
            'ua50m[unit="m s-1"]': [3.0],
            'va50m[unit="m s-1"]': [4.0],
            'ua100m[unit="m s-1"]': [6.0],
            'va100m[unit="m s-1"]': [8.0],
        }
    )

    result = barra2_dl.convert.convert_wind_components(df)

    assert np.isclose(result['v50m[unit="m s-1"]'].iloc[0], 5.0)
    assert np.isclose(result['v100m[unit="m s-1"]'].iloc[0], 10.0)
    assert 'v100m_phi_met[unit="degrees"]' in result.columns


@pytest.mark.parametrize(
    'columns',
    [
        {'time': [1], 'ta50m[unit="K"]': [290.0]},  # no wind components
        {'time': [1], UA50: [3.0]},  # u without v
        {'time': [1], VA50: [4.0]},  # v without u
    ],
)
def test_convert_wind_components_nothing_to_convert(columns):
    """Frames without a complete ua/va pair come back with no new columns."""
    df = pd.DataFrame(columns)

    result = barra2_dl.convert.convert_wind_components(df)

    assert list(result.columns) == list(df.columns)


def test_convert_wind_components_does_not_modify_input():
    """The input frame is left unchanged."""
    df = pd.DataFrame({UA50: [3.0], VA50: [4.0]})

    barra2_dl.convert.convert_wind_components(df)

    assert list(df.columns) == [UA50, VA50]
