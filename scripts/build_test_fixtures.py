"""Build the small netCDF4 and csv test fixtures in tests/data from the NCI THREDDS server.

Downloads the same point (three days of January 2023, AUS-11 1hr) as netCDF4 and as csv, so tests can check that the
two routes give identical values, and the bounding-box grid around it as netCDF4 for the four-node average and area
tests. Run it from the repository root only if the fixtures need rebuilding:

    uv run python scripts/build_test_fixtures.py
"""

import sys
from pathlib import Path

import requests

import barra2_dl
from barra2_dl.globals import BARRA2_DOMAINS, BARRA2_URL, BARRA2_URL_FX_BBOX

OUT = Path(__file__).resolve().parents[1] / 'tests' / 'data'
LAT, LON = -23.55, 133.40
VARIABLES = ['ua50m', 'va50m', 'tas', 'pr']  # winds, an instantaneous scalar and a time mean
TIME_END = '2023-01-03T23:00:00Z'
# Boxes sent to NCSS to pin which nodes a bounding box returns (research note reanalysis-site-data.md, task 4).
# AUS-11 nodes near the point are at lat -23.65, -23.54, -23.43 and lon 133.25, 133.36, 133.47 (spacing 0.11).
NODE_BOXES = {
    'overlaps_four_cells': ('AUS-11', -23.45, -23.60, 133.40, 133.30),
    'inside_one_cell': ('AUS-11', -23.50, -23.52, 133.40, 133.38),
    'one_cell_exactly': ('AUS-11', -23.485, -23.595, 133.415, 133.305),
    'a_point': ('AUS-11', -23.54, -23.54, 133.36, 133.36),
    'superset': ('AUS-11', -23.30, -23.75, 133.60, 133.15),
    'aust04_across_a_boundary': ('AUST-04', -23.505, -23.515, 133.405, 133.395),
}
# Fixed-field grids for the nearest_nodes tests: (fixture name, domain, variable, north, south, east, west). The AUS-11
# one is the superset box above for sftlf (orog is ncss_box_superset.nc); AUST-04 spacing is 0.04.
NODE_LOOKUPS = {
    'ncss_box_superset_sftlf': ('AUS-11', 'sftlf', -23.30, -23.75, 133.60, 133.15),
    'ncss_box_aust04_orog': ('AUST-04', 'orog', -23.45, -23.65, 133.50, 133.30),
    'ncss_box_aust04_sftlf': ('AUST-04', 'sftlf', -23.45, -23.65, 133.50, 133.30),
}


def save(pairs: list[tuple[str, str]]) -> None:
    """Download each (url, filename) pair into tests/data, shortening the monthly time range to three days."""
    for url, name in pairs:
        if '_fx_' not in name:
            url = url.replace('time_end=2023-01-31T23:00:00Z', f'time_end={TIME_END}')
            name = name.replace('20230131', '20230103')
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        (OUT / name).write_bytes(response.content)
        sys.stdout.write(f'{name}: {len(response.content)} bytes')
        sys.stdout.write('\n')


def save_node_boxes() -> None:
    """Download the orog grid for each box in NODE_BOXES as ncss_box_<name>.nc."""
    for name, (domain, north, south, east, west) in NODE_BOXES.items():
        url = BARRA2_URL_FX_BBOX.format(
            domain=domain,
            model=BARRA2_DOMAINS[domain],
            var='orog',
            north=north,
            south=south,
            east=east,
            west=west,
            fileout_type='netcdf4',
        )
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        (OUT / f'ncss_box_{name}.nc').write_bytes(response.content)
        sys.stdout.write(f'ncss_box_{name}.nc: {len(response.content)} bytes')
        sys.stdout.write('\n')


def save_node_lookups() -> None:
    """Download the fixed-field grids in NODE_LOOKUPS as <name>.nc."""
    for name, (domain, var, north, south, east, west) in NODE_LOOKUPS.items():
        url = BARRA2_URL_FX_BBOX.format(
            domain=domain,
            model=BARRA2_DOMAINS[domain],
            var=var,
            north=north,
            south=south,
            east=east,
            west=west,
            fileout_type='netcdf4',
        )
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        (OUT / f'{name}.nc').write_bytes(response.content)
        sys.stdout.write(f'{name}.nc: {len(response.content)} bytes')
        sys.stdout.write('\n')


def main() -> None:
    """Download the point fixtures as csv and netCDF4, and the grid fixtures as netCDF4, into tests/data."""
    OUT.mkdir(exist_ok=True)
    for fileout_type in ('csv_file', 'netcdf4'):
        save(
            barra2_dl.download.point_data_urlfilenames(
                BARRA2_URL, VARIABLES, LAT, LON, '2023-01-01', '2023-01-31', 'fixture', fileout_type=fileout_type
            )
        )
    save(
        barra2_dl.download.point_data_urlfilenames(
            BARRA2_URL, VARIABLES, LAT, LON, '2023-01-01', '2023-01-31', 'grid', node_selection='average4'
        )
    )
    save_node_boxes()
    save_node_lookups()


if __name__ == '__main__':
    main()
