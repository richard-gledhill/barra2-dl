"""This module contains the barra2.convert test function(s)."""

import numpy as np
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
