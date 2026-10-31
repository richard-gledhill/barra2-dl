"""Display-free smoke test of the notebook spike: run the script's cells in a plain interpreter, drive the widgets."""

import runpy
import time
from pathlib import Path

APP = Path(__file__).with_name('app.py')


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_notebook_form_nodes_polygon_and_run() -> None:
    """Find nodes, choose one, break and fix the dates, draw and remove a polygon, then run and read the result."""
    ns = runpy.run_path(str(APP))
    ns['find'](None)
    _check(len(ns['state']['offered']) == 9, 'nine nodes offered')
    ns['toggle'](ns['state']['offered'][0])
    _check(len(ns['state']['chosen']) == 1, 'one node chosen')
    _check(not ns['run_button'].disabled, 'run enabled')
    ns['fields']['end'].value = ns['fields']['start'].value.replace(year=2000)
    _check(ns['run_button'].disabled and bool(ns['problems_box'].value), 'end before start is reported')
    ns['fields']['end'].value = ns['fields']['start'].value.replace(month=1, day=31)
    _check(not ns['run_button'].disabled, 'run enabled again')
    ring = [[133.3, -23.6], [133.5, -23.6], [133.5, -23.5], [133.3, -23.5], [133.3, -23.6]]
    feature = {'type': 'Feature', 'properties': {}, 'geometry': {'type': 'Polygon', 'coordinates': [ring]}}
    ns['draw'].data = [feature]
    _check(bool(ns['state']['polygon']) and 'Polygon set (4 vertices)' in ns['node_info'].value, 'polygon taken')
    ns['draw'].data = []
    _check(ns['state']['polygon'] is None, 'polygon removed')
    ns['start'](None)
    for _ in range(100):
        if ns['state']['cancel'] is None:
            break
        time.sleep(0.2)
    _check('Result: ok' in ns['result_box'].value, 'run finished ok')
    _check(len(ns['state']['used']) == 1, 'one node used')
