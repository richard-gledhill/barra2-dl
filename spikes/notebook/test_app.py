"""Display-free smoke test of the notebook spike: run the script's cells in a plain interpreter, drive the widgets."""

import runpy
import shutil
import time
from pathlib import Path

import spike_common

APP = Path(__file__).with_name('app.py')
RING = [[133.35, -23.60], [133.50, -23.60], [133.50, -23.50], [133.35, -23.50], [133.35, -23.60]]
POLYGON = {'type': 'Feature', 'properties': {}, 'geometry': {'type': 'Polygon', 'coordinates': [RING]}}


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_notebook_form_nodes_polygon_sites_and_run() -> None:
    """One site: nodes, validation, a moved marker, a polygon with its node preview. Two sites: a run of both."""
    shutil.rmtree(spike_common.SCRATCH / 'cache', ignore_errors=True)  # an earlier run may cache other requests
    ns = runpy.run_path(str(APP))
    sites, state = ns['sites'], ns['state']
    ns['find'](None)
    _check(len(sites[0]['offered']) == 9, 'nine nodes offered')
    ns['toggle'](sites[0]['offered'][0])
    _check(len(sites[0]['chosen']) == 1, 'one node chosen')
    start = ns['shared_fields']['start'].value
    ns['shared_fields']['end'].value = start.replace(year=2000)
    _check(ns['run_button'].disabled and bool(ns['problems_box'].value), 'end before start is reported')
    ns['shared_fields']['end'].value = start.replace(month=1, day=31)
    _check(not ns['run_button'].disabled, 'run enabled again')

    ns['moved'](0, (-23.5, 133.45))
    _check((sites[0]['lat'], sites[0]['lon']) == (-23.5, 133.45) and not sites[0]['chosen'], 'marker move taken')
    _check(ns['site_fields']['lat'].value == -23.5, 'form follows the marker')

    ns['draw'].data = [POLYGON]
    _check(bool(sites[0]['polygon']) and 'polygon set (4 vertices)' in ns['node_info'].value, 'polygon taken')
    ns['find'](None)
    _check(len(sites[0]['offered']) == 4 and 'overlap' in sites[0]['offered'][0], 'polygon nodes previewed')
    ns['clear_polygon'](None)
    _check(sites[0]['polygon'] is None, 'polygon cleared')

    ns['add_site'](None)
    _check(len(sites) == 2 and state['active'] == 1, 'second site added and active')
    ns['select'](0)
    _check(ns['site_fields']['name'].value == 'mast-1' and sites[0]['lat'] == -23.5, 'switching keeps each site')
    ns['select'](1)
    ns['site_fields']['name'].value = 'mast-2b'
    _check(sites[1]['name'] == 'mast-2b', 'name edit taken')
    ns['site_fields']['name'].value = 'mast-1'
    _check(
        'names must be different' in ns['problems_box'].value and ns['run_button'].disabled, 'duplicate name blocked'
    )
    ns['site_fields']['name'].value = 'mast-2'

    ns['start'](None)
    for _ in range(150):
        if state['cancel'] is None:
            break
        time.sleep(0.2)
    html = ns['result_box'].value
    _check('mast-1: ok' in html and 'mast-2: ok' in html, 'both sites ran ok')
