"""This module contains the tests of the fake NCSS server the GUI tests use (tests/fake_ncss.py)."""

import fake_ncss
import pytest
import requests

from barra2_dl.mapping import LatLonPoint, NodeLookupError, Polygon, nearest_nodes, polygon_nodes


@pytest.fixture(autouse=True)
def _fake(monkeypatch: pytest.MonkeyPatch) -> None:
    """Install the fake server for every test."""
    fake_ncss.install(monkeypatch)


def test_fake_serves_node_lookups_anywhere_in_the_domain() -> None:
    """A point far from the fixture still has nine nodes, on the real grid."""
    nodes = nearest_nodes(LatLonPoint(-33.87, 151.21), 'AUS-11', 9)

    assert len(nodes) == 9


def test_fake_serves_a_polygon_lookup() -> None:
    """A polygon box returns the nodes its cells overlap."""
    polygon = Polygon(((-33.9, 151.2), (-33.9, 151.4), (-33.8, 151.4), (-33.8, 151.2)))

    assert len(polygon_nodes(polygon, 'AUS-11')) >= 4


def test_fake_refuses_a_lookup_outside_australia() -> None:
    """The fake answers a box outside its grid with a 400, as the real server does outside the domain."""
    with pytest.raises(NodeLookupError):
        nearest_nodes(LatLonPoint(60.0, 0.0), 'AUS-11', 4)


def test_fake_fails_the_data_urls_it_is_told_to(monkeypatch: pytest.MonkeyPatch) -> None:
    """A data url containing the fail text gets a 404; another does not."""
    fake_ncss.install(monkeypatch, fail='tas')

    assert requests.get('http://x/tas?var=tas&accept=csv_file', timeout=5).status_code == 404
    assert requests.get('http://x/ua50m?var=ua50m&accept=csv_file', timeout=5).status_code == 200
