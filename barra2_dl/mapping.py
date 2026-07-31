"""This modules contains helper geo and mapping classes, constants and functions.

References:
    https://stackoverflow.com/questions/79174938/how-to-fix-order-of-inherited-subclasses-in-python-dataclass/79174970

Todo:
    Draft functions to set grid for mapping support.
    Implement _format_lat_lon for converting lat lon for file naming
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd


class _Geodetic(float):
    """Float specialization base class for Latitude and Longitude.

    Adds _check_limits on min max to avoid code duplication on setting and checking float value.

    Attributes:
        min (float): Minimum allowable value.
        max (float): Maximum allowable value.
        name (str): Name
    """
    min = 0.0
    max = 0.0
    name = "Geodetic"

    def __new__(cls, value):
        instance = super().__new__(cls, value)
        instance._check_limits()
        return instance

    def _check_limits(self):
        """We _ARE_ a float, so "self"  can be used directly for the value."""
        if not self.min <= self <= self.max:
            raise ValueError(f"{self.name} must be from {self.min} to {self.max}")


class Latitude(_Geodetic):
    """Specialization base class for Latitude and Longitude."""
    min = -90
    max = 90
    name = "Lat"


class Longitude(_Geodetic):
    """Specialization base class for Latitude and Longitude."""
    min = -180
    max = 180
    name = "Lon"


@dataclass
class LatLonPoint:
    """Custom point.

    Attributes:
        lat (Latitude): Custom Geodetic
        lon (Longitude): Custom Geodetic
    """
    lat: Latitude
    lon: Longitude

    def __init__(
        self,
        lat: Latitude | float | int,
        lon: Longitude | float | int,
    ) -> None:
        """Set latitude and longitude."""
        self.lat = Latitude(lat)
        self.lon = Longitude(lon)


@dataclass
class LatLonBBox:
    """A north south east west bounding box by latitude and longitude.

    Attributes:
        north (Latitude): Custom Geodetic
        south (Latitude): Custom Geodetic
        east (Longitude): Custom Geodetic
        west (Longitude): Custom Geodetic

    Todo:
        Add checks to make sure co-ordinates are correct with respect to each other.
    """
    north: Latitude
    south: Latitude
    east: Longitude
    west: Longitude

    def __post_init__(self):
        """Set self attributes."""
        for field_name, field in self.__dataclass_fields__.items():
            setattr(self, field_name, field.type(getattr(self, field_name)))


def _generate_point_grid(
    lat_lon_bbox: dict | tuple,
    lat_res: float,
    lon_res: float,
    offset:bool = None,
) -> pd.DataFrame:
    """Create a grid of longitude and latitude points between specified minimum and maximum values.

    Args:
        lat_lon_bbox (dict | tuple): Dictionary or tuple containing geographic boundaries.
                                     Dictionary should have keys 'north', 'south', 'east', 'west'.
                                     Tuple should contain values in the order (north, south, east, west).
        lon_res (float): Resolution of the longitude points.
        lat_res (float): Resolution of the latitude points. Optional lon_res = lat_res if not specified.
        offset: Offsets the first point by half the lat_res and lon_res to create points at centre.

    Returns:
        pd.DataFrame: DataFrame containing the grid points with columns 'longitude' and 'latitude'.

    Raises:
        ValueError: If bounds is neither a dictionary nor a tuple, or if the keys/values are missing or invalid.

    Todo:
        Draft function and not yet implemented
    """
    if isinstance(lat_lon_bbox, dict):
        required_keys = ['north', 'south', 'east', 'west']
        if not all(key in lat_lon_bbox for key in required_keys):
            raise ValueError("Dictionary must contain 'north', 'south', 'east', and 'west' keys.")
    elif isinstance(lat_lon_bbox, tuple):
        if len(lat_lon_bbox) != 4:
            raise ValueError("Tuple must contain exactly 4 values: (north, south, east, west).")
    else:
        raise ValueError("Bounds must be a dictionary or tuple.")

    if lon_res is None:
        lon_res = lat_res

    if offset:
        lat_lon_bbox = {
            'north': lat_lon_bbox['north'] - lat_res/2,
            'south': lat_lon_bbox['south'] + lat_res/2,
            'east': lat_lon_bbox['east'] - lon_res/2,
            'west': lat_lon_bbox['west'] + lon_res/2
        }

    longitudes = np.arange(lat_lon_bbox['west'], lat_lon_bbox['east'] + lon_res, lon_res)
    latitudes = np.arange(lat_lon_bbox['south'], lat_lon_bbox['north'] + lat_res, lat_res)
    long_grid, lat_grid = np.meshgrid(longitudes, latitudes)

    df_point_grid = pd.DataFrame({
        'latitude': lat_grid.flatten(),
        'longitude': long_grid.flatten()
    })

    return df_point_grid


def _find_nearest_point(
    df_point_grid: pd.DataFrame,
    target_lat: float,
    target_lon: float,
) -> pd.Series:
    """Find the nearest point in a DataFrame of latitude, longitude points to a target point (target_lat, target_lon).

    Args:
        df_point_grid (pd.DataFrame): DataFrame containing the points with 'Longitude' and 'Latitude' columns.
        target_lon (float): The x-coordinate of the target point.
        target_lat (float): The y-coordinate of the target point.

    Returns:
        pd.Series: The row of the nearest point in the DataFrame.

    Todo:
        Draft function and not yet implemented
    """
    # check if target falls within grid
    min_lat, max_lat = df_point_grid['latitude'].min(), df_point_grid['latitude'].max()
    min_lon, max_lon = df_point_grid['longitude'].min(), df_point_grid['longitude'].max()

    if not (min_lat <= target_lat <= max_lat) or not (min_lon <= target_lon <= max_lon):
        raise ValueError("Target latitude and/or longitude are out of the range of the DataFrame's coordinates.")

    distances = np.sqrt((df_point_grid['latitude'] - target_lat) ** 2 + (df_point_grid['longitude'] - target_lon) ** 2)
    nearest_index = distances.idxmin()
    return df_point_grid.loc[nearest_index]


def _format_lat_lon(
    latitude: float | int,
    longitude: float | int,
) -> list[str]:
    """Format a dictionary containing 'lat' and 'lon' as floats to a string.

    Uses 2 decimal precision, and converts negative values to 'S'.

    Args:
        longitude (float | int): Longitude
        latitude (float | int): Latitude

    Returns:
        list[str]: Formatted string of the latitude and longitude.

    Todo:
        Draft function and not yet implemented
    """
    formatted_lat = ('S' if latitude < 0 else '') + '{:.2f}'.format(abs(latitude))
    formatted_lon = '{:.2f}'.format(abs(longitude))

    return [formatted_lat, formatted_lon]

