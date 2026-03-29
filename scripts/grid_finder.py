"""BARRA2 grid finder module.

Finds the four nearest grid points surrounding a given coordinate
for BARRA2 AUS-11 and AUST-04 resolutions.
"""
import math
import os
import sys
from pathlib import Path

# Ensure parent directory is in path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# BARRA2 grid parameters derived from BOM documentation and actual grid data
# AUS-11: ~0.11 degree resolution (~12 km)
#   Source: barra2_dl/data/BOM_BARRA2_AUS11_latlon.csv
#   Reference: http://www.bom.gov.au/research/publications/researchreports/BRR-067.pdf
# AUST-04: ~0.44 degree resolution (~50 km)
BARRA2_GRID_PARAMS = {
    'AUS11': {
        'lat_origin': 12.98,
        'lon_origin': 88.48,
        'spacing': 0.11,
        'north': 12.98,
        'south': -57.97,
        'west': 88.48,
        'east': 207.39,
        'lat_direction': -1,  # latitude decreases (north to south)
        'url': 'AUS-11',
    },
    'AUST04': {
        'lat_origin': 12.0,
        'lon_origin': 88.0,
        'spacing': 0.44,
        'north': 12.0,
        'south': -56.44,
        'west': 88.0,
        'east': 208.36,
        'lat_direction': -1,
        'url': 'AUST-04',
    },
}

# 6 环境变量
BARRA2_ENV_VARIABLES = {
    'tas':    ('2m air temperature',         'K'),
    'hurs':   ('2m relative humidity',       '%'),
    'pr':     ('Precipitation flux',         'kg m-2 s-1'),
    'ps':     ('Surface pressure',           'Pa'),
    'ta50m':  ('50m air temperature',        'K'),
    'rsds':   ('Surface shortwave radiation', 'W m-2'),
}

# 风速变量 (5个可用高度 × 2分量 = 10个)
# NOTE: 10m/20m/30m/70m/300m 在 BARRA2 AUS-11 服务器上返回 404，不可用
BARRA2_WIND_HEIGHTS = [50, 100, 150, 200, 250]

BARRA2_WIND_VARIABLES = {}
for height in BARRA2_WIND_HEIGHTS:
    BARRA2_WIND_VARIABLES[f'ua{height}m'] = (f'{height}m U-wind', 'm s-1')
    BARRA2_WIND_VARIABLES[f'va{height}m'] = (f'{height}m V-wind', 'm s-1')

# All available variables (merged for backward compatibility)
BARRA2_ALL_VARIABLES = {**BARRA2_ENV_VARIABLES, **BARRA2_WIND_VARIABLES}


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great-circle distance between two points on Earth.

    Args:
        lat1: Latitude of point 1 in degrees.
        lon1: Longitude of point 1 in degrees.
        lat2: Latitude of point 2 in degrees.
        lon2: Longitude of point 2 in degrees.

    Returns:
        Distance in kilometers.
    """
    R = 6371.0  # Earth radius in km
    lat1_rad, lon1_rad = math.radians(lat1), math.radians(lon1)
    lat2_rad, lon2_rad = math.radians(lat2), math.radians(lon2)
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))
    return R * c


def normalize_longitude(lon: float) -> float:
    """Convert longitude from 0~360 to -180~180 range.

    Args:
        lon: Longitude in 0~360 range.

    Returns:
        Longitude in -180~180 range.
    """
    if lon > 180:
        return lon - 360
    return lon


def find_nearest_four_grid_points(
    target_lat: float,
    target_lon: float,
    resolution: str = 'AUS11',
) -> list[dict]:
    """Find the four surrounding grid points for a given coordinate.

    Given a target coordinate, calculates the four grid points that form
    the bounding box cell containing the target point.

    Args:
        target_lat: Target latitude in degrees.
        target_lon: Target longitude in degrees (-180~180).
        resolution: Grid resolution, 'AUS11' or 'AUST04'.

    Returns:
        List of 4 dicts with keys: label, lat, lon, distance_km
        Labels: 'Top-Left', 'Top-Right', 'Bottom-Left', 'Bottom-Right'

    Raises:
        ValueError: If coordinate is outside grid bounds or resolution is invalid.
    """
    if resolution not in BARRA2_GRID_PARAMS:
        raise ValueError(f"Invalid resolution: {resolution}. Use 'AUS11' or 'AUST04'.")

    params = BARRA2_GRID_PARAMS[resolution]
    origin_lat = params['lat_origin']
    origin_lon = params['lon_origin']
    spacing = params['spacing']
    lat_dir = params['lat_direction']

    # Normalize target longitude to match grid (0~360 range)
    target_lon_360 = target_lon if target_lon >= 0 else target_lon + 360

    # Validate bounds
    south = params['south']
    north = params['north']
    west = params['west']
    east = params['east']
    if not (south <= target_lat <= north):
        raise ValueError(
            f"Latitude {target_lat} is outside {resolution} bounds "
            f"[{south}, {north}]."
        )
    if not (west <= target_lon_360 <= east):
        raise ValueError(
            f"Longitude {target_lon} is outside {resolution} bounds "
            f"[{normalize_longitude(west)}, {normalize_longitude(east)}]."
        )

    # Calculate grid indices
    # For AUS-11: lat starts at 12.98 and decreases by 0.11 each step (southward)
    # floor_lat_idx = number of grid steps from origin to the grid point just above target
    floor_lat_idx = int((origin_lat - target_lat) / spacing)
    if floor_lat_idx < 0:
        floor_lat_idx = 0

    floor_lon_idx = int((target_lon_360 - origin_lon) / spacing)
    if floor_lon_idx < 0:
        floor_lon_idx = 0

    # Calculate the four corner grid points
    # Top row (higher latitude, closer to north): floor_lat_idx
    # Bottom row (lower latitude, closer to south): floor_lat_idx + 1
    top_lat = origin_lat - floor_lat_idx * spacing
    bottom_lat = origin_lat - (floor_lat_idx + 1) * spacing

    left_lon = origin_lon + floor_lon_idx * spacing
    right_lon = origin_lon + (floor_lon_idx + 1) * spacing

    # Build result with labels and distances
    points = [
        {'label': 'Top-Left', 'lat': round(top_lat, 2), 'lon': round(left_lon, 2)},
        {'label': 'Top-Right', 'lat': round(top_lat, 2), 'lon': round(right_lon, 2)},
        {'label': 'Bottom-Left', 'lat': round(bottom_lat, 2), 'lon': round(left_lon, 2)},
        {'label': 'Bottom-Right', 'lat': round(bottom_lat, 2), 'lon': round(right_lon, 2)},
    ]

    # Calculate distance to target for each point
    for pt in points:
        pt['distance_km'] = round(haversine_distance(
            target_lat, target_lon,
            pt['lat'], normalize_longitude(pt['lon']),
        ), 2)

    return points


def find_nearest_single_grid_point(
    target_lat: float,
    target_lon: float,
    resolution: str = 'AUS11',
) -> dict:
    """Find the single nearest grid point to a given coordinate.

    Args:
        target_lat: Target latitude in degrees.
        target_lon: Target longitude in degrees (-180~180).
        resolution: Grid resolution, 'AUS11' or 'AUST04'.

    Returns:
        Dict with keys: lat, lon, distance_km
    """
    four_points = find_nearest_four_grid_points(target_lat, target_lon, resolution)
    nearest = min(four_points, key=lambda p: p['distance_km'])
    return {
        'lat': nearest['lat'],
        'lon': normalize_longitude(nearest['lon']),
        'distance_km': nearest['distance_km'],
    }


if __name__ == '__main__':
    # Quick test
    print("Testing grid_finder.py")
    print("=" * 60)

    test_coords = [
        (-23.55, 133.40, 'Alice Springs area'),
        (-33.87, 151.21, 'Sydney'),
        (-37.81, 144.96, 'Melbourne'),
        (-27.47, 153.03, 'Brisbane'),
    ]

    for lat, lon, name in test_coords:
        print(f"\nTest: {name} ({lat}, {lon})")
        try:
            points = find_nearest_four_grid_points(lat, lon, 'AUS11')
            print(f"  Grid resolution: AUS-11 (0.11 deg)")
            for p in points:
                lon_display = normalize_longitude(p['lon'])
                print(f"    {p['label']:15s}: ({p['lat']:8.2f}, {lon_display:9.2f})  dist={p['distance_km']:.2f} km")
        except ValueError as e:
            print(f"  ERROR: {e}")
