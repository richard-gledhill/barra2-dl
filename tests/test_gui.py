"""This module contains the barra2.gui.app test function(s): the notebook GUI driven without a display.

The tests call the handlers on the GuiApp that build_app makes, with the fake NCSS server of tests/fake_ncss.py, as an
analyst's clicks would. A core-only environment, without the gui extra, skips the file.
"""

import csv
import json
import shutil
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import fake_ncss
import pytest
import xarray as xr

from barra2_dl import globals as barra2_globals
from barra2_dl.download import preset_variables
from barra2_dl.mapping import GridNode

pytest.importorskip('ipywidgets')
gui = pytest.importorskip('barra2_dl.gui.app')

# region Test helpers
DATA = Path(__file__).parent / 'data'
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
    """A polygon drawn on the map, as the draw control reports it."""
    return {'type': 'Feature', 'properties': {}, 'geometry': {'type': 'Polygon', 'coordinates': [ring]}}


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Any]:
    """A GUI app in a temporary folder with the fake NCSS server, a quick cache timer and no display."""
    fake_ncss.install(monkeypatch)
    built = gui.build_app(tmp_path, plan_refresh=0.2)
    yield built
    built.wait()
    built.close()


def _rings(app: Any) -> list[Any]:
    """The rings on the map that mark the nodes a run would download."""
    return [layer for layer in app.node_layers if layer.color == gui.PLANNED]


def _upload(name: str, content: bytes) -> dict[str, Any]:
    """One file as the Upload box reports it."""
    return {'name': name, 'content': content}


def _output_columns(path: Path) -> list[str]:
    """The data columns of an output file: variable names of a netCDF, the header row of a csv."""
    if path.suffix == '.nc':
        with xr.open_dataset(path) as data:
            return sorted(str(name) for name in data.data_vars)
    with open(path, encoding='utf-8', newline='') as file:
        return next(row for row in csv.reader(file) if row and row[0] == 'time')


def _wait_for(condition: Any, seconds: float = 10.0) -> bool:
    """Poll until the condition holds; the plan line is refreshed by a timer thread."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.05)
    return False


# endregion


# region Public API
# region build_app
def test_build_app_shows_one_mast_with_the_form_ready_to_run(app: Any) -> None:
    """A new app has mast-1, valid defaults, a plan line, and the folder's cache and output as defaults."""
    assert [site.name for site in app.sites] == ['mast-1']
    assert not app.run_button.disabled
    assert 'mast-1: ' in app.plan_label.value
    assert Path(app.shared_fields['cache'].value) == app.folder / 'cache'
    assert Path(app.shared_fields['out'].value) == app.folder / 'out'
    assert app.layout is not None


def test_build_app_again_stops_the_first_apps_timer(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Running the notebook cell twice leaves one timer, not two."""
    fake_ncss.install(monkeypatch)
    first = gui.build_app(tmp_path)
    second = gui.build_app(tmp_path)

    assert first.stop_timer.is_set()
    assert not second.stop_timer.is_set()
    second.close()


# endregion


# region find, toggle and the masts
def test_gui_form_nodes_and_masts(app: Any) -> None:
    """Nodes, validation, a moved mast and a second mast; both masts run."""
    gui.find(app)
    assert len(app.sites[0].offered) == 9
    gui.toggle(app, app.sites[0].offered[0])
    assert len(app.sites[0].chosen) == 1
    start = app.shared_fields['start'].value
    app.shared_fields['end'].value = start.replace(year=2000)
    assert app.run_button.disabled
    assert app.problems_box.value
    app.shared_fields['end'].value = start.replace(month=1, day=31)
    assert not app.run_button.disabled

    gui.moved(app, 0, (-23.5, 133.45))
    assert (app.sites[0].lat, app.sites[0].lon) == (-23.5, 133.45)
    assert not app.sites[0].chosen
    assert app.site_fields['lat'].value == -23.5

    gui.add_site(app)
    assert len(app.sites) == 2
    assert app.active == 1
    assert app.sites[1].name == 'mast-2'
    gui.select(app, 0)
    assert app.site_fields['name'].value == 'mast-1'
    assert app.sites[0].lat == -23.5
    gui.select(app, 1)
    app.site_fields['name'].value = 'mast-1'
    assert 'names must be different' in app.problems_box.value
    assert app.run_button.disabled
    assert app.run_selected_button.disabled
    app.site_fields['name'].value = 'mast-2'

    gui.start(app, [0, 1])
    app.wait()
    assert 'mast-1: ok' in app.result_box.value
    assert 'mast-2: ok' in app.result_box.value


def test_gui_toggle_drops_a_node_chosen_twice(app: Any) -> None:
    """Clicking a chosen node again takes it off the choice."""
    gui.find(app)
    node = app.sites[0].offered[0]

    gui.toggle(app, node)
    gui.toggle(app, node)

    assert app.sites[0].chosen == []


def test_gui_find_reports_a_failed_lookup(app: Any) -> None:
    """A mast outside the grid gives a message under the map, not a traceback."""
    gui.moved(app, 0, (60.0, 0.0))
    gui.find(app)

    assert 'Could not get the nodes' in app.node_info.value
    assert app.sites[0].offered == []


def test_gui_far_sites_find_and_run(app: Any) -> None:
    """A mast and an area far from the fixture point: nodes are found and the run uses the previewed ones."""
    gui.moved(app, 0, (-33.87, 151.21))
    gui.find(app)
    assert len(app.sites[0].offered) == 9
    gui.toggle(app, app.sites[0].offered[0])
    ring = [[150.95, -33.75], [151.1, -33.75], [151.1, -33.65], [150.95, -33.65], [150.95, -33.75]]
    app.draw.data = [_feature(ring)]
    gui.find(app)
    previewed = sorted((round(node.lat, 3), round(node.lon, 3)) for node in app.sites[1].offered)
    assert len(previewed) > 1

    gui.start(app, [0, 1])
    app.wait()

    assert 'mast-1: ok' in app.result_box.value
    assert 'area-1: ok' in app.result_box.value
    assert sorted((round(n['lat'], 3), round(n['lon'], 3)) for n in app.sites[1].used) == previewed


# endregion


# region the area
def test_gui_one_area_that_can_be_reshaped_and_deleted(app: Any) -> None:
    """A drawn polygon is one area, independent of the masts; a second is refused; reshape and delete are followed."""
    app.draw.data = [_feature(RING)]
    assert len(app.sites) == 2
    assert app.active == 1
    assert app.sites[1].name == 'area-1'
    assert app.sites[0].polygon is None
    gui.find(app)
    assert len(app.sites[1].offered) == 4
    assert all(0 < share <= 1 for share in app.sites[1].shares.values())
    assert app.site_fields['lat'].layout.display == 'none'

    other = [[133.0, -23.9], [133.2, -23.9], [133.2, -23.8], [133.0, -23.8], [133.0, -23.9]]
    app.draw.data = [_feature(RING), _feature(other)]
    assert len(app.sites) == 2
    assert 'Only one area' in app.node_info.value
    assert len(app.draw.data) == 1

    bigger = [[133.30, -23.65], [133.55, -23.65], [133.55, -23.45], [133.30, -23.45], [133.30, -23.65]]
    app.draw.data = [_feature(bigger)]
    assert len(app.sites) == 2
    assert not app.sites[1].offered
    assert 'reshaped' in app.node_info.value
    assert app.sites[1].polygon['geometry']['coordinates'][0][1][0] == 133.55

    app.draw.data = []
    assert len(app.sites) == 1
    assert app.sites[0].polygon is None

    app.draw.data = [_feature(RING)]
    gui.remove_site(app)
    assert len(app.sites) == 1
    assert len(app.draw.data) == 0


def test_gui_area_is_grey_when_idle_and_labelled(app: Any) -> None:
    """The area is purple while active and grey otherwise, and carries its name as a label with a tooltip."""
    app.draw.data = [_feature(RING)]
    assert app.sites[1].polygon['properties']['style']['color'] == gui.AREA_COLOURS[True]
    gui.select(app, 0)
    assert app.sites[1].polygon['properties']['style']['color'] == gui.AREA_COLOURS[False]
    assert app.draw.data[0]['properties']['style']['color'] == gui.AREA_COLOURS[False]
    assert any(marker.title == 'area-1' for marker in app.markers)
    gui.select(app, 1)
    assert app.sites[1].polygon['properties']['style']['color'] == gui.AREA_COLOURS[True]


def test_gui_weighted_mean_option_and_run(app: Any) -> None:
    """The mean box shows for an area, and a run with it still finishes ok."""
    app.draw.data = [_feature(RING)]
    assert app.mean_box.layout.display == ''
    app.mean_box.value = True
    assert app.sites[1].mean is True
    assert not app.run_selected_button.disabled

    gui.start(app, [1])
    app.wait()

    assert 'area-1: ok' in app.result_box.value
    gui.select(app, 0)
    assert app.mean_box.layout.display == 'none'


# endregion


# region the nodes a run would download
def test_gui_highlights_the_nodes_a_run_would_download(app: Any) -> None:
    """Nearest rings the one nearest node, average4 the four around the mast, an area all its nodes."""
    nodes_field = app.shared_fields['node_selection']
    gui.find(app)
    assert len(_rings(app)) == 1
    nodes_field.value = 'average4'
    assert len(_rings(app)) == 4
    assert 'average4' in app.selection_note.value
    site = app.sites[0]
    ringed = {tuple(layer.location) for layer in _rings(app)}
    lats, lons = sorted({lat for lat, _lon in ringed}), sorted({lon for _lat, lon in ringed})
    assert len(lats) == len(lons) == 2
    assert lats[0] <= site.lat <= lats[1]
    assert lons[0] <= site.lon <= lons[1]

    gui.toggle(app, site.offered[3])
    assert len(_rings(app)) == 1
    assert nodes_field.disabled

    app.draw.data = [_feature(RING)]
    gui.find(app)
    assert len(_rings(app)) == len(app.sites[1].offered) == 4
    assert nodes_field.disabled
    assert 'not just the centre' in app.selection_note.value


# endregion


# region import and the last session
def test_gui_imports_a_project_and_a_polygon(app: Any, tmp_path: Path) -> None:
    """A project.toml replaces settings and sites; a polygon file becomes the area, by path or by upload."""
    shutil.copy(DATA / 'boundary_two_cells.geojson', tmp_path / 'boundary_two_cells.geojson')
    (tmp_path / 'project.toml').write_text(PROJECT, encoding='utf-8')
    app.import_path.value = str(tmp_path / 'project.toml')
    gui.import_from_path(app)
    assert [site.name for site in app.sites] == ['masta', 'farm']
    assert 'only one area is allowed' in app.import_info.value
    assert len(app.sites[0].chosen) == 1
    assert app.sites[1].polygon is not None
    assert app.shared_fields['end'].value.day == 31
    assert Path(app.shared_fields['cache'].value).name == 'cache-from-project'
    assert len(app.draw.data) == 1

    app.import_path.value = str(tmp_path / 'missing.toml')
    gui.import_from_path(app)
    assert 'missing.toml' in app.import_info.value
    assert len(app.sites) == 2

    text = (DATA / 'boundary_sub_cell.geojson').read_bytes()
    gui.import_from_upload(app, [_upload('sub.geojson', text)])
    assert len(app.sites) == 2
    assert 'sub.geojson' in app.import_info.value

    gui.import_from_upload(app, [_upload('broken.geojson', b'{"type": "Point"}')])
    assert 'broken.geojson' in app.import_info.value
    assert len(app.sites) == 2


def test_gui_import_centres_the_map_when_fit_bounds_has_no_event_loop(
    app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Outside a kernel, Python 3.14 refuses fit_bounds; the map is centred on the polygon instead."""

    def refuse(_bounds: Any) -> None:
        raise RuntimeError('There is no current event loop')

    monkeypatch.setattr(app.fmap, 'fit_bounds', refuse)

    gui.import_from_upload(app, [_upload('farm.geojson', (DATA / 'boundary_two_cells.geojson').read_bytes())])

    assert [site.name for site in app.sites] == ['mast-1', 'farm']
    assert tuple(app.fmap.center) == pytest.approx((-23.54, 133.41), abs=0.2)


def test_gui_imports_a_kml_polygon_as_the_area(app: Any) -> None:
    """A .kml polygon is read as a .geojson one is, and named after its file."""
    gui.import_from_upload(app, [_upload('farm.kml', (DATA / 'boundary_two_cells.kml').read_bytes())])

    assert [site.name for site in app.sites] == ['mast-1', 'farm']
    assert app.sites[1].polygon is not None


def test_gui_import_refuses_other_file_types(app: Any) -> None:
    """A file that is not a project or a polygon is reported, and nothing changes."""
    gui.import_from_upload(app, [_upload('notes.txt', b'hello')])

    assert 'use a .toml project' in app.import_info.value
    assert len(app.sites) == 1


def test_gui_uploads_a_project_with_its_polygon_file(app: Any) -> None:
    """Selecting the project.toml and its polygon file together imports both; the folders land by the notebook."""
    toml = PROJECT.split('[[site]]\nname = "second-farm"')[0]
    content = [
        _upload('project.toml', toml.encode()),
        _upload('boundary_two_cells.geojson', (DATA / 'boundary_two_cells.geojson').read_bytes()),
    ]
    gui.import_from_upload(app, content)
    assert [site.name for site in app.sites] == ['masta', 'farm']
    assert Path(app.shared_fields['cache'].value) == app.folder / 'cache-from-project'

    gui.import_from_upload(app, content[:1])
    assert 'Cannot read' in app.import_info.value
    assert 'together' in app.import_info.value


def test_gui_loads_the_last_session_and_carries_on(app: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """A run saves the settings and sites; a new app loads them and a Run only fetches what is not cached."""
    gui.load_session(app)
    assert 'No last session' in app.import_info.value

    app.draw.data = [_feature(RING)]
    app.sites[0].name = 'mast-kept'
    gui.select(app, 0)
    gui.toggle(app, gui.GridNode(-23.54, 133.36, 4.0, 400.0, 100.0))
    app.mean_box.value = True
    gui.start(app, [0])
    app.wait()
    session = json.loads((app.folder / gui.SESSION_FILE).read_text(encoding='utf-8'))
    assert [site['name'] for site in session['site']] == ['mast-kept', 'area-1']
    assert session['active'] == 'mast-kept'
    app.close()

    second = gui.build_app(app.folder, plan_refresh=0.2)
    gui.load_session(second)
    assert [site.name for site in second.sites] == ['mast-kept', 'area-1']
    assert second.shared_fields['format'].value == 'netcdf'
    assert second.sites[0].mean is True
    assert [(node.lat, node.lon) for node in second.sites[0].chosen] == [(-23.54, 133.36)]
    assert second.sites[1].polygon is not None
    assert second.draw.data
    assert 'Loaded the last session' in second.import_info.value
    for out in (app.folder / 'out').glob('mast-kept_*'):
        out.unlink()
    gui.start(second, [0])
    second.wait()
    assert 'mast-kept: ok' in second.result_box.value
    assert any((app.folder / 'out').glob('mast-kept_*.nc'))
    second.close()


# endregion


# region the run
def test_gui_run_selected_site_only(app: Any) -> None:
    """Run selected site runs the active site alone, and leaves the other site's result as it was."""
    gui.add_site(app)
    gui.start(app, [0])
    app.wait()
    assert 'mast-1: ok' in app.result_box.value
    assert 'mast-2' not in app.result_box.value

    gui.select(app, 1)
    gui.start(app, [app.active])
    app.wait()

    html = app.result_box.value
    assert html.index('mast-1: ok') < html.index('mast-2: ok')
    assert app.sites[0].used
    assert app.sites[1].used


def test_gui_cancel_stops_after_the_file_in_progress(app: Any) -> None:
    """Cancel sets the run's event; the run ends as cancelled and the buttons come back."""
    gui.start(app, [0])
    app.cancel_button.click()
    app.wait()

    assert 'cancelled' in app.result_box.value or 'mast-1: ok' in app.result_box.value
    assert app.cancel is None
    assert app.cancel_button.layout.display == 'none'
    assert not app.run_button.disabled


@pytest.mark.parametrize(('preset', 'count'), [('wind', 12), ('wind+density', 20)])
@pytest.mark.parametrize('output', ['netcdf', 'csv'])
def test_gui_downloads_every_variable_of_a_preset(app: Any, preset: str, count: int, output: str) -> None:
    """Every variable of the wind and wind+density presets is downloaded and reaches the netCDF and the csv."""
    wanted = barra2_globals.BARRA2_PRESETS[preset]
    assert len(wanted) == count
    app.shared_fields['preset'].value = preset
    app.shared_fields['format'].value = output

    gui.start(app, [0])
    app.wait()

    assert 'mast-1: ok' in app.result_box.value
    cached = {f.name.split('_1hr_')[1].split('_2023')[0] for f in (app.folder / 'cache').glob('*_1hr_*')}
    assert set(wanted) <= cached
    (written,) = (f for f in (app.folder / 'out').glob('mast-1_*') if f.suffix in ('.nc', '.csv'))
    columns = _output_columns(written)
    winds = [v for v in wanted if v[0] in 'uv' and v not in ('uas', 'vas')]
    if output == 'csv':
        shown = [f'{v[:2]}10m' if v in ('uas', 'vas') else v for v in wanted]
        assert all(v in ' '.join(columns) for v in shown)
    else:
        with xr.open_dataset(written) as data:
            assert data['ua'].height.values.tolist() == [10.0, 50.0, 100.0, 150.0, 200.0, 250.0]
        assert all(v in columns for v in wanted if v not in ('uas', 'vas', *winds))


# endregion


# region the notes and the plan line
def test_gui_preset_note_lists_the_variables_from_globals(app: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """The note under Preset names the variables the engine's own preset table holds, and follows a change of preset."""
    note = app.preset_note
    for preset, variables in barra2_globals.BARRA2_PRESETS.items():
        app.shared_fields['preset'].value = preset
        assert f'{preset}: {len(variables)} variables' in note.value
        assert all(v in note.value for v in variables)
    app.shared_fields['preset'].value = 'wind'
    monkeypatch.setitem(barra2_globals.BARRA2_PRESETS, 'wind', ['uas', 'vas'])
    app.shared_fields['preset'].value = 'extremes'
    app.shared_fields['preset'].value = 'wind'
    assert 'wind: 2 variables: uas, vas' in note.value

    app.shared_fields['domain'].value = 'AUST-04'
    app.shared_fields['freq'].value = '20min'
    app.shared_fields['preset'].value = 'wind+density'
    works = True
    try:
        preset_variables('wind+density', 'AUST-04', '20min')
    except ValueError:
        works = False
    assert ('not available' in note.value) == (not works)


def test_gui_plan_line_follows_cache_files_deleted_by_hand(app: Any) -> None:
    """After a run the plan line counts cached files; deleting them by hand shows without touching the form."""
    gui.start(app, [0])
    app.wait()
    assert _wait_for(lambda: ' 0 cached' not in app.plan_label.value)

    for path in (app.folder / 'cache').glob('*'):
        for _ in range(50):  # the timer may be looking at a file just now, and Windows will not delete it then
            try:
                path.unlink()
                break
            except PermissionError:
                time.sleep(0.1)

    assert _wait_for(lambda: ' 0 cached' in app.plan_label.value)


def test_gui_node_choice_note_follows_the_site(app: Any) -> None:
    """The note says what a run of the active site downloads, for a mast with and without chosen nodes."""
    assert 'nearest' in app.selection_note.value
    gui.find(app)
    gui.toggle(app, app.sites[0].offered[0])

    assert '1 chosen node' in app.selection_note.value
    assert isinstance(app.sites[0].chosen[0], GridNode)


# endregion
# endregion
