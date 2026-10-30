"""Build the small netCDF4 and csv test fixtures in tests/data from the NCI THREDDS server.

Downloads the same point (three days of January 2023, AUS-11 1hr) as netCDF4 and as csv, so tests can check that the
two routes give identical values. Run it from the repository root only if the fixtures need rebuilding:

    uv run python scripts/build_test_fixtures.py
"""

import sys
from pathlib import Path

import requests

import barra2_dl
from barra2_dl.globals import BARRA2_URL

OUT = Path(__file__).resolve().parents[1] / 'tests' / 'data'
LAT, LON = -23.55, 133.40
VARIABLES = ['ua50m', 'va50m', 'tas', 'pr']  # winds, an instantaneous scalar and a time mean
TIME_END = '2023-01-03T23:00:00Z'


def main() -> None:
    """Download each fixture as csv and as netCDF4 into tests/data."""
    OUT.mkdir(exist_ok=True)
    for fileout_type in ('csv_file', 'netcdf4'):
        pairs = barra2_dl.download.point_data_urlfilenames(
            BARRA2_URL, VARIABLES, LAT, LON, '2023-01-01', '2023-01-31', 'fixture', fileout_type=fileout_type
        )
        for url, name in pairs:
            if '_fx_' not in name:
                url = url.replace('time_end=2023-01-31T23:00:00Z', f'time_end={TIME_END}')
                name = name.replace('20230131', '20230103')
            response = requests.get(url, timeout=60)
            response.raise_for_status()
            (OUT / name).write_bytes(response.content)
            sys.stdout.write(f'{name}: {len(response.content)} bytes')
            sys.stdout.write('\n')


if __name__ == '__main__':
    main()
