"""Display-free smoke test of the notebook spike: run the script's cells in a plain interpreter, drive the widgets."""

import csv
import json
import runpy
import shutil
import time
from pathlib import Path
from typing import Any

import pytest
import spike_common
import xarray as xr

from barra2_dl import globals as barra2_globals
from barra2_dl.download import preset_variables

APP = Path(__file__).with_name('app.py')
DATA = Path(__file__).resolve().parents[2] / 'tests' / 'data'
RING = [[133.35, -23.60], [133.50, -23.60], [133.50, -23.50], [133.35, -23.50], [133.35, -23.60]]
PROJECT = """
[settings]
start = 2023-01-01
end = 2023-01-31
domain = "AUS-11"
freq = "1hr"
preset = "wind+density"
format = "netcdf"
cache = "cache-from-project"
out = "out-from-project"

[[site]]
name = "masta"
lat = -23.55
lon = 133.40
nodes = [[-23.54, 133.36]]

[[site]]
name = "farm"
polygon = "boundary_two_cells.geojson"

[[site]]
name = "second-farm"
polygon = "boundary_two_cells.geojson"
"""


def _feature(ring: list[list[float]]) -> dict[str, Any]:
    return {'type': 'Feature', 'properties': {}, 'geometry': {'type': 'Polygon', 'coordinates': [ring]}}


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


_started: list[dict[str, Any]] = []


def _fresh() -> dict[str, Any]:
    shutil.rmtree(spike_common.SCRATCH / 'cache', ignore_errors=True)  # an earlier run may cache other requests
    while _started:  # one app at a time, so only one timer watches the shared cache
        _started.pop()['plan_ticker'].set()
    ns = runpy.run_path(str(APP))
    _started.append(ns)
    return ns


@pytest.fixture(autouse=True)
def _stop_timers():
    """Stop the cache-watching timer of every app a test started."""
    yield
    while _started:
        _started.pop()['plan_ticker'].set()


def _wait(ns: dict[str, Any]) -> None:
    for _ in range(300):
        if ns['state']['cancel'] is None:
            return
        time.sleep(0.2)


def test_notebook_form_nodes_and_masts() -> None:
    """Nodes, validation, a moved mast and a second mast; both masts run."""
    ns = _fresh()
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

    ns['add_site'](None)
    _check(len(sites) == 2 and state['active'] == 1 and sites[1]['name'] == 'mast-2', 'second mast added and active')
    ns['select'](0)
    _check(ns['site_fields']['name'].value == 'mast-1' and sites[0]['lat'] == -23.5, 'switching keeps each site')
    ns['select'](1)
    ns['site_fields']['name'].value = 'mast-1'
    _check('names must be different' in ns['problems_box'].value, 'duplicate name reported')
    _check(ns['run_button'].disabled and ns['run_selected_button'].disabled, 'duplicate name blocks both runs')
    ns['site_fields']['name'].value = 'mast-2'

    ns['start'](list(range(len(sites))))
    _wait(ns)
    html = ns['result_box'].value
    _check('mast-1: ok' in html and 'mast-2: ok' in html, 'both masts ran ok')


def test_notebook_one_area_that_can_be_reshaped_and_deleted() -> None:
    """A drawn polygon is one area, independent of the masts; a second is refused; reshape and delete are followed."""
    ns = _fresh()
    sites, state = ns['sites'], ns['state']
    ns['draw'].data = [_feature(RING)]
    _check(len(sites) == 2 and state['active'] == 1 and sites[1]['name'] == 'area-1', 'the area is a new, active site')
    _check(sites[0]['polygon'] is None, 'the mast is untouched')
    ns['find'](None)
    _check(len(sites[1]['offered']) == 4 and 'overlap' in sites[1]['offered'][0], 'area nodes previewed')
    _check(ns['site_fields']['lat'].layout.display == 'none', 'an area has no place boxes')

    other = [[133.0, -23.9], [133.2, -23.9], [133.2, -23.8], [133.0, -23.8], [133.0, -23.9]]
    ns['draw'].data = [_feature(RING), _feature(other)]
    _check(len(sites) == 2 and 'Only one area' in ns['node_info'].value, 'a second polygon is refused')
    _check(len(ns['draw'].data) == 1, 'and taken off the map')

    bigger = [[133.30, -23.65], [133.55, -23.65], [133.55, -23.45], [133.30, -23.45], [133.30, -23.65]]
    ns['draw'].data = [_feature(bigger)]
    _check(len(sites) == 2 and not sites[1]['offered'], 'reshaping keeps the one area and forgets its nodes')
    _check(
        'reshaped' in ns['node_info'].value
        and json.loads(sites[1]['polygon'])['geometry']['coordinates'][0][1][0] == 133.55,
        'new shape taken',
    )

    ns['draw'].data = []
    _check(len(sites) == 1 and sites[0]['polygon'] is None, 'deleting the polygon on the map deletes the area')

    ns['draw'].data = [_feature(RING)]
    ns['remove_site'](None)
    _check(len(sites) == 1 and len(ns['draw'].data) == 0, 'Remove site on the area clears it from the map')


def test_notebook_run_selected_site_only() -> None:
    """Run selected site runs the active site alone, and leaves the other site's result as it was."""
    ns = _fresh()
    sites, state = ns['sites'], ns['state']
    ns['add_site'](None)
    ns['start']([0])
    _wait(ns)
    _check('mast-1: ok' in ns['result_box'].value and 'mast-2' not in ns['result_box'].value, 'only mast-1 ran')
    ns['select'](1)
    ns['start']([state['active']])
    _wait(ns)
    html = ns['result_box'].value
    _check(html.index('mast-1: ok') < html.index('mast-2: ok'), 'both results shown in site order')
    _check(len(sites[0]['used']) >= 1 and len(sites[1]['used']) >= 1, 'each site kept its own used nodes')


def test_notebook_imports_a_project_and_a_polygon(tmp_path: Path) -> None:
    """A project.toml replaces settings and sites; a polygon file becomes the area, by path or by upload."""
    shutil.copy(DATA / 'boundary_two_cells.geojson', tmp_path / 'boundary_two_cells.geojson')
    (tmp_path / 'project.toml').write_text(PROJECT, encoding='utf-8')
    ns = _fresh()
    sites = ns['sites']
    ns['import_path'].value = str(tmp_path / 'project.toml')
    ns['import_from_path'](None)
    _check([s['name'] for s in sites] == ['masta', 'farm'], 'sites imported, the second area skipped')
    _check('only one area is allowed' in ns['import_info'].value, 'the skipped area is reported')
    _check(len(sites[0]['chosen']) == 1 and sites[1]['polygon'] is not None, 'nodes and polygon came with the sites')
    _check(ns['shared_fields']['end'].value.day == 31, 'settings imported')
    _check(Path(ns['shared_fields']['cache'].value).name == 'cache-from-project', 'folders imported')
    _check(len(ns['draw'].data) == 1, 'the polygon is on the map')

    ns['import_path'].value = str(tmp_path / 'missing.toml')
    ns['import_from_path'](None)
    _check('missing.toml' in ns['import_info'].value and len(sites) == 2, 'a missing file is reported, nothing changes')

    text = (DATA / 'boundary_sub_cell.geojson').read_text(encoding='utf-8')
    ns['import_from_upload']({'new': ({'name': 'sub.geojson', 'content': text.encode()},)})
    _check(len(sites) == 2 and 'sub.geojson' in ns['import_info'].value, 'an uploaded polygon replaces the area')

    ns['import_from_upload']({'new': ({'name': 'broken.geojson', 'content': b'{"type": "Point"}'},)})
    _check('broken.geojson' in ns['import_info'].value and len(sites) == 2, 'a bad polygon is reported')


def test_notebook_far_sites_find_and_run() -> None:
    """A mast and an area far from the fixture point: nodes are found and the run uses the previewed ones."""
    ns = _fresh()
    sites = ns['sites']
    ns['moved'](0, (-33.87, 151.21))
    ns['find'](None)
    _check(len(sites[0]['offered']) == 9, 'nodes found for a site far from the fixture')
    ns['toggle'](sites[0]['offered'][0])
    ring = [[150.95, -33.75], [151.1, -33.75], [151.1, -33.65], [150.95, -33.65], [150.95, -33.75]]
    ns['draw'].data = [_feature(ring)]
    ns['find'](None)
    previewed = sorted((round(n['lat'], 3), round(n['lon'], 3)) for n in sites[1]['offered'])
    _check(len(previewed) > 1, 'area nodes previewed')
    ns['start']([0, 1])
    _wait(ns)
    _check('mast-1: ok' in ns['result_box'].value and 'area-1: ok' in ns['result_box'].value, 'both far sites ran')
    used = sorted((round(n['lat'], 3), round(n['lon'], 3)) for n in sites[1]['used'])
    _check(used == previewed, 'the run used the nodes the preview showed')


def test_notebook_highlights_the_nodes_a_run_would_download() -> None:
    """Nearest rings the one nearest node, average4 the four around the mast, an area all its nodes."""
    ns = _fresh()
    sites = ns['sites']
    planned, nodes_field = ns['planned_nodes'], ns['shared_fields']['node_selection']
    ns['find'](None)
    site = sites[0]
    _check(planned(site['lat'], site['lon'], site['offered'], [], 'nearest', False) == site['offered'][:1], 'nearest')
    four = planned(site['lat'], site['lon'], site['offered'], [], 'average4', False)
    lats, lons = sorted({n['lat'] for n in four}), sorted({n['lon'] for n in four})
    _check(len(four) == 4 and len(lats) == 2 and len(lons) == 2, 'average4 is a 2 x 2 block')
    _check(lats[0] <= site['lat'] <= lats[1] and lons[0] <= site['lon'] <= lons[1], 'that surrounds the mast')
    ns['toggle'](site['offered'][3])
    _check(
        planned(site['lat'], site['lon'], site['offered'], site['chosen'], 'nearest', False) == site['chosen'], 'chosen'
    )
    rings = [layer for layer in ns['state']['node_layers'] if layer.color == ns['PLANNED']]
    _check(len(rings) == 1, 'a chosen node alone is ringed')
    ns['find'](None)
    nodes_field.value = 'average4'
    rings = [layer for layer in ns['state']['node_layers'] if layer.color == ns['PLANNED']]
    _check(len(rings) == 4, 'average4 rings four nodes on the map')
    _check('average4' in ns['selection_note'].value, 'and the note says so')
    ns['draw'].data = [_feature(RING)]
    ns['find'](None)
    rings = [layer for layer in ns['state']['node_layers'] if layer.color == ns['PLANNED']]
    _check(len(rings) == len(sites[1]['offered']) == 4, 'an area rings every node it overlaps')
    _check(nodes_field.disabled and 'not just the centre' in ns['selection_note'].value, 'the node choice is off')


def test_notebook_area_is_grey_when_idle_and_labelled() -> None:
    """The area is purple while active and grey otherwise, and carries its name as a label with a tooltip."""
    ns = _fresh()
    sites, state = ns['sites'], ns['state']
    ns['draw'].data = [_feature(RING)]
    colour = json.loads(sites[1]['polygon'])['properties']['style']['color']
    _check(colour == ns['AREA_COLOURS'][True], 'active area is purple')
    ns['select'](0)
    _check(json.loads(sites[1]['polygon'])['properties']['style']['color'] == ns['AREA_COLOURS'][False], 'idle is grey')
    _check(ns['draw'].data[0]['properties']['style']['color'] == ns['AREA_COLOURS'][False], 'and on the map')
    _check(any(marker.title == 'area-1' for marker in state['markers']), 'the area has a labelled marker')
    ns['select'](1)
    _check(json.loads(sites[1]['polygon'])['properties']['style']['color'] == ns['AREA_COLOURS'][True], 'purple again')


def test_notebook_weighted_mean_option_and_run() -> None:
    """The mean box shows for an area, and a run with it still finishes ok."""
    ns = _fresh()
    ns['draw'].data = [_feature(RING)]
    _check(ns['mean_box'].layout.display == '', 'an area offers the weighted mean')
    ns['mean_box'].value = True
    _check(ns['sites'][1]['mean'] is True and not ns['run_selected_button'].disabled, 'ticked and runnable')
    ns['start']([1])
    _wait(ns)
    _check('area-1: ok' in ns['result_box'].value, 'the area ran ok with the mean on')
    ns['select'](0)
    _check(ns['mean_box'].layout.display == 'none', 'a mast with no chosen nodes has no mean box')


def test_notebook_loads_the_last_session_and_carries_on() -> None:
    """A run saves the settings and sites; a new app loads them and a Run only fetches what is not cached."""
    session = spike_common.SCRATCH / 'last_session.json'
    session.unlink(missing_ok=True)
    first = _fresh()
    first['load_session']()
    _check('No last session' in first['import_info'].value, 'nothing to load before a run')
    first['shared_fields']['preset'].value = 'wind+density'
    first['shared_fields']['format'].value = 'csv'
    first['draw'].data = [_feature(RING)]
    first['sites'][0]['name'] = 'mast-kept'
    first['start']([0])  # an area cannot be written as csv
    _wait(first)
    _check(session.exists(), 'a run writes last_session.json')

    second = _fresh()
    second['load_session']()
    sites = second['sites']
    _check([s['name'] for s in sites] == ['mast-kept', 'area-1'], f'sites restored: {[s["name"] for s in sites]}')
    _check(second['shared_fields']['format'].value == 'csv', 'settings restored')
    _check(sites[1]['polygon'] is not None and second['draw'].data, 'the area is on the map again')
    _check('Loaded the last session' in second['import_info'].value, second['import_info'].value)
    for each in sites:
        for out in (spike_common.SCRATCH / 'out').glob(f'{each["name"]}_*'):
            out.unlink()
    second['start']([0])
    _wait(second)
    _check('mast-kept: ok' in second['result_box'].value, 'the loaded session runs')
    _check(any((spike_common.SCRATCH / 'out').glob('mast-kept_*.csv')), 'the output files are written again')


def test_notebook_uploads_a_project_with_its_polygon_file(tmp_path: Path) -> None:
    """Selecting the project.toml and its polygon file together imports both; the folders land by the notebook."""
    ns = _fresh()
    toml = PROJECT.replace('second-farm', 'unused').split('[[site]]\nname = "unused"')[0]
    content = [
        {'name': 'project.toml', 'content': toml.encode()},
        {'name': 'boundary_two_cells.geojson', 'content': (DATA / 'boundary_two_cells.geojson').read_bytes()},
    ]
    ns['import_from_upload']({'new': tuple(content)})
    _check([s['name'] for s in ns['sites']] == ['masta', 'farm'], 'both sites imported from the upload')
    _check(
        Path(ns['shared_fields']['cache'].value) == Path.cwd() / 'cache-from-project', 'cache folder by the notebook'
    )
    ns['import_from_upload']({'new': tuple(content[:1])})
    _check(
        'Cannot read' in ns['import_info'].value and 'together' in ns['import_info'].value,
        'a missing polygon is explained',
    )


def _output_columns(path: Path) -> list[str]:
    """The data columns of an output file: variable names of a netCDF, the header row of a csv."""
    if path.suffix == '.nc':
        with xr.open_dataset(path) as data:
            return sorted(data.data_vars)
    with open(path, encoding='utf-8', newline='') as file:
        return next(row for row in csv.reader(file) if row and row[0] == 'time')


def test_notebook_downloads_every_variable_of_a_preset() -> None:
    """Every variable of the wind and wind+density presets is downloaded and reaches the netCDF and the csv."""
    for preset, count in (('wind', 12), ('wind+density', 20)):
        wanted = barra2_globals.BARRA2_PRESETS[preset]
        _check(len(wanted) == count, f'{preset} has {count} variables')
        for fmt in ('netcdf', 'csv'):
            shutil.rmtree(spike_common.SCRATCH / 'out', ignore_errors=True)  # one output file to look at
            ns = _fresh()
            ns['shared_fields']['preset'].value = preset
            ns['shared_fields']['format'].value = fmt
            ns['start']([0])
            _wait(ns)
            _check('mast-1: ok' in ns['result_box'].value, f'{preset} {fmt} ran ok')
            cache = {
                f.name.split('_1hr_')[1].split('_2023')[0] for f in (spike_common.SCRATCH / 'cache').glob('*_1hr_*')
            }
            _check(set(wanted) <= cache, f'{preset} {fmt}: every variable downloaded, missing {set(wanted) - cache}')
            (output,) = (f for f in (spike_common.SCRATCH / 'out').glob('mast-1_*') if f.suffix in ('.nc', '.csv'))
            columns = _output_columns(output)
            winds = [v for v in wanted if v[0] in 'uv' and v not in ('uas', 'vas')]
            if fmt == 'csv':
                shown = [f'{v[:2]}10m' if v in ('uas', 'vas') else v for v in wanted]
                header = ' '.join(columns)
                _check(all(v in header for v in shown), f'{preset} csv: every variable in the file')
            else:
                with xr.open_dataset(output) as data:
                    heights = data['ua'].height.values.tolist()
                _check(heights == [10.0, 50.0, 100.0, 150.0, 200.0, 250.0], f'{preset} netcdf: six wind heights')
                others = [v for v in wanted if v not in ('uas', 'vas', *winds)]
                _check(all(v in columns for v in others), f'{preset} netcdf: every other variable in the file')


def test_notebook_preset_note_lists_the_variables_from_globals() -> None:
    """The note under Preset names the variables the engine's own preset table holds, and follows a change of preset."""
    ns = _fresh()
    note = ns['preset_note']
    for preset, variables in barra2_globals.BARRA2_PRESETS.items():
        ns['shared_fields']['preset'].value = preset
        _check(f'{preset}: {len(variables)} variables' in note.value, f'{preset} named with its count')
        _check(all(v in note.value for v in variables), f'{preset} lists its variables')
    ns['shared_fields']['preset'].value = 'wind'
    original = barra2_globals.BARRA2_PRESETS['wind']
    barra2_globals.BARRA2_PRESETS['wind'] = ['uas', 'vas']
    try:
        ns['shared_fields']['preset'].value = 'extremes'
        ns['shared_fields']['preset'].value = 'wind'
        _check('wind: 2 variables: uas, vas' in note.value, 'the note reads the table, nothing is copied')
    finally:
        barra2_globals.BARRA2_PRESETS['wind'] = original
    ns['shared_fields']['domain'].value = 'AUST-04'
    ns['shared_fields']['freq'].value = '20min'
    ns['shared_fields']['preset'].value = 'wind+density'
    _check(
        ('not available' in note.value) == (not _preset_works('wind+density', 'AUST-04', '20min')), 'availability shown'
    )


def _preset_works(preset: str, domain: str, freq: str) -> bool:
    try:
        preset_variables(preset, domain, freq)
    except ValueError:
        return False
    return True


def test_notebook_plan_line_follows_cache_files_deleted_by_hand() -> None:
    """After a run the plan line counts cached files; deleting them by hand shows without touching the form."""
    ns = _fresh()
    ns['shared_fields']['end'].value = ns['shared_fields']['start'].value.replace(month=1, day=31)
    ns['start']([0])
    _wait(ns)
    for _ in range(100):  # the run clears its busy flag a moment before it refreshes the line
        if ' 0 cached' not in ns['plan_label'].value:
            break
        time.sleep(0.1)
    _check(' 0 cached' not in ns['plan_label'].value, 'the run left files in the cache')
    cache = spike_common.SCRATCH / 'cache'
    for path in cache.glob('*'):
        for _ in range(50):  # the timer may be looking at a file just now, and Windows will not delete it then
            try:
                path.unlink()
                break
            except PermissionError:
                time.sleep(0.1)
    for _ in range(50):
        if ' 0 cached' in ns['plan_label'].value:
            break
        time.sleep(0.1)
    _check(' 0 cached' in ns['plan_label'].value, 'the plan line noticed the cache was emptied')
