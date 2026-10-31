"""Pin which nodes NCSS returns for a bounding box, from fixtures built by scripts/build_test_fixtures.py.

The research note (docs/development/research/reanalysis-site-data.md, task 4) found that a box returns every node whose
grid cell overlaps it, not only the nodes inside it; a box edge exactly on a cell edge is covered separately. Slices 2
and 2b build on that, so these tests fail loudly if the server's behaviour changes.
"""

from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from barra2_dl.globals import BARRA2_GRID_SPACING

DATA = Path(__file__).parent / 'data'
TOLERANCE = 1e-6

# name -> (domain, north, south, east, west), as in scripts/build_test_fixtures.py NODE_BOXES
BOXES = {
    'overlaps_four_cells': ('AUS-11', -23.45, -23.60, 133.40, 133.30),
    'inside_one_cell': ('AUS-11', -23.50, -23.52, 133.40, 133.38),
    'one_cell_exactly': ('AUS-11', -23.485, -23.595, 133.415, 133.305),
    'a_point': ('AUS-11', -23.54, -23.54, 133.36, 133.36),
    'superset': ('AUS-11', -23.30, -23.75, 133.60, 133.15),
    'aust04_across_a_boundary': ('AUST-04', -23.505, -23.515, 133.405, 133.395),
}


def _grid(name: str) -> tuple[xr.Dataset, float]:
    """Open the fixture for a box, and the grid spacing of its domain."""
    ds = xr.open_dataset(DATA / f'ncss_box_{name}.nc').load()
    return ds, BARRA2_GRID_SPACING[BOXES[name][0]]


def _cell_overlaps(node: float, spacing: float, low: float, high: float) -> bool:
    """True if the cell of width spacing centred on the node overlaps the interval low to high."""
    return node - spacing / 2 <= high + TOLERANCE and node + spacing / 2 >= low - TOLERANCE


@pytest.mark.parametrize('name', [name for name in BOXES if name != 'one_cell_exactly'])
def test_a_box_returns_exactly_the_nodes_whose_cell_overlaps_it(name: str) -> None:
    """Every node returned has a cell that overlaps the box, and the next node out on each side does not."""
    _, north, south, east, west = BOXES[name]
    ds, spacing = _grid(name)
    lats, lons = ds['lat'].to_numpy(), ds['lon'].to_numpy()

    assert all(_cell_overlaps(lat, spacing, south, north) for lat in lats)
    assert all(_cell_overlaps(lon, spacing, west, east) for lon in lons)
    assert not _cell_overlaps(lats[0] - spacing, spacing, south, north)
    assert not _cell_overlaps(lats[-1] + spacing, spacing, south, north)
    assert not _cell_overlaps(lons[0] - spacing, spacing, west, east)
    assert not _cell_overlaps(lons[-1] + spacing, spacing, west, east)
    assert np.allclose(np.diff(lats), spacing, atol=1e-4)
    assert np.allclose(np.diff(lons), spacing, atol=1e-4)


@pytest.mark.parametrize('name', ['inside_one_cell', 'a_point'])
def test_a_box_smaller_than_a_cell_returns_the_node_whose_cell_holds_it(name: str) -> None:
    """A tiny box, or a point, gets the one node whose cell contains it, even when that node is outside the box."""
    ds, _ = _grid(name)

    assert ds['lat'].to_numpy().tolist() == pytest.approx([-23.54])
    assert ds['lon'].to_numpy().tolist() == pytest.approx([133.36])


def test_a_box_can_return_nodes_that_are_not_inside_it() -> None:
    """The nodes are not filtered to those inside the box: the returned node lies outside the tiny box."""
    ds, _ = _grid('inside_one_cell')
    _, north, south, east, west = BOXES['inside_one_cell']
    lat, lon = float(ds['lat'][0]), float(ds['lon'][0])

    assert not (south <= lat <= north and west <= lon <= east)


def test_a_box_across_cell_edges_returns_each_neighbouring_node() -> None:
    """A small box straddling the edge between cells returns a 2 x 2 block, on AUST-04 as on AUS-11."""
    ds, _ = _grid('aust04_across_a_boundary')

    assert ds.sizes['lat'] == ds.sizes['lon'] == 2


def test_a_box_exactly_one_cell_wide_includes_the_cells_it_touches_on_the_north_and_east_only() -> None:
    """Box edges on cell edges count on the north and east sides but not the south and west (half-open cells).

    Observed, not designed: callers must not rely on edge behaviour, so slice 2 pads boxes rather than sit on an edge.
    """
    ds, _ = _grid('one_cell_exactly')

    assert ds['lat'].to_numpy().tolist() == pytest.approx([-23.54, -23.43])
    assert ds['lon'].to_numpy().tolist() == pytest.approx([133.36, 133.47])


def test_a_larger_box_gives_the_same_values_at_shared_nodes() -> None:
    """One request for a bigger box serves any smaller box inside it: shared nodes have identical values."""
    small, _ = _grid('overlaps_four_cells')
    large, _ = _grid('superset')

    shared = large['orog'].sel(lat=small['lat'], lon=small['lon'], method='nearest')

    assert small.sizes['lat'] < large.sizes['lat']
    np.testing.assert_array_equal(shared.to_numpy(), small['orog'].to_numpy())
