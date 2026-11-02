"""The notebook GUI: a form, a map and run controls built from ipywidgets and ipyleaflet.

build_app makes the widgets and the state behind them; the handlers are functions over the GuiApp it returns, so the
whole interface can be driven, and tested, without a display. The notebook shipped as barra2_dl_gui.ipynb only calls
build_app and shows the layout. Everything that is not widgets is a library call: node lookups, planning, validation
and the runs themselves.
"""

import json
import logging
import math
import re
import sys
import tempfile
import threading
import tomllib
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Any

import ipywidgets as w
import pandas as pd
from ipyleaflet import AwesomeIcon, CircleMarker, DivIcon, GeomanDrawControl, Map, Marker

from barra2_dl import globals as barra2_globals
from barra2_dl.download import preset_variables
from barra2_dl.globals import (
    BARRA2_DOMAINS,
    BARRA2_FREQS,
    BARRA2_NODE_SELECTIONS,
    BARRA2_OUTPUT_FORMATS,
    BARRA2_PRESETS,
)
from barra2_dl.mapping import (
    BoundaryFileError,
    GridNode,
    LatLonPoint,
    Polygon,
    nearest_nodes,
    planned_nodes,
    polygon_from_geojson,
    polygon_from_kml,
    polygon_nodes,
)
from barra2_dl.project import (
    Project,
    Settings,
    Site,
    load_project,
    plan_site,
    project_from_dict,
    project_to_dict,
    run_site,
    site_result_to_dict,
    validate,
)

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

__all__ = [
    'GuiApp',
    'SiteState',
    'add_site',
    'build_app',
    'find',
    'import_from_path',
    'import_from_upload',
    'load_session',
    'moved',
    'remove_site',
    'select',
    'start',
    'toggle',
]


# region Constants and types
DEFAULT_POINT = (-23.55, 133.40)  # the first mast, near Alice Springs
SESSION_FILE = 'last_session.json'  # in the notebook's folder, written at every run, read by Load last session
PLAN_REFRESH_SECONDS = 3.0  # how often the 'N files, M cached' line looks at the cache folder again
DRAW_POLYGON = {'pathOptions': {'color': '#a855f7'}}  # an empty dict would switch the tool off
AREA_COLOURS = {True: '#a855f7', False: '#9ca3af'}  # the active area is purple, an idle one grey, as the masts are
PLANNED = '#7c3aed'  # the ring round a node a run would download
COLOURS = {'offered': '#3b82f6', 'chosen': '#16a34a', 'used': '#f97316'}
NO_NODE = {'distance_km': math.nan, 'orog': math.nan, 'sftlf': math.nan}  # a node from a project has only a place
SELECTIONS = [name for name in BARRA2_NODE_SELECTIONS if name in ('nearest', 'average4')]
RED = '#dc2626'


@dataclass
class SiteState:
    """One site as the form holds it: a mast (a point), or the area when it has a polygon.

    Attributes:
        name: The site name, which is the filename prefix.
        lat: Latitude of the mast, or of the middle of the area's vertices.
        lon: Longitude of the mast, or of the middle of the area's vertices.
        polygon: The area as a GeoJSON feature, or None for a mast.
        offered: The nodes the last Find nodes offered.
        shares: The share of its cell inside the area for each offered node of an area, by (lat, lon).
        chosen: The nodes the analyst chose for a mast.
        used: The nodes the last run used, from its summary.
        mean: Whether to also write the weighted mean of the nodes.
    """

    name: str
    lat: float
    lon: float
    polygon: dict[str, Any] | None = None
    offered: list[GridNode] = field(default_factory=list)
    shares: dict[tuple[float, float], float] = field(default_factory=dict)
    chosen: list[GridNode] = field(default_factory=list)
    used: list[dict[str, Any]] = field(default_factory=list)
    mean: bool = False

    def forget_nodes(self) -> None:
        """Forget the nodes, because the site moved or the settings they depend on changed."""
        self.offered, self.shares, self.chosen, self.used = [], {}, [], []


@dataclass
class GuiApp:
    """The widgets of the notebook GUI and the state behind them; the handlers in this module work on it.

    The widget fields are typed Any because ipywidgets and ipyleaflet ship no type information.

    Attributes:
        folder: Where the cache, the output and the last session are kept unless the form says otherwise.
        sites: The masts and the one area, in order.
        active: Index in sites of the one being worked on.
        results: The latest run summary of each site, as HTML, by site name.
        cancel: Set to stop a run; None when no run is going.
        layout: The form and the map, to show in a cell.
    """

    folder: Path
    plan_refresh: float
    sites: list[SiteState]
    site_select: Any
    add_button: Any
    remove_button: Any
    site_fields: dict[str, Any]
    shared_fields: dict[str, Any]
    mean_box: Any
    selection_note: Any
    preset_note: Any
    find_button: Any
    run_button: Any
    run_selected_button: Any
    cancel_button: Any
    plan_label: Any
    problems_box: Any
    node_info: Any
    progress: Any
    progress_label: Any
    result_box: Any
    import_path: Any
    import_button: Any
    import_upload: Any
    session_button: Any
    import_info: Any
    fmap: Any
    draw: Any
    layout: Any = None
    active: int = 0
    results: dict[str, str] = field(default_factory=dict)
    cancel: threading.Event | None = None
    loading: bool = False  # True while widgets are set from a site, so their observers stay quiet
    markers: list[Any] = field(default_factory=list)
    node_layers: list[Any] = field(default_factory=list)
    worker: threading.Thread | None = None
    stop_timer: threading.Event = field(default_factory=threading.Event)

    def show(self) -> Any:
        """Return the form and the map; as the last line of a cell, the notebook displays them."""
        return self.layout

    def close(self) -> None:
        """Stop the timer that watches the cache folder."""
        self.stop_timer.set()

    def wait(self, timeout: float = 60.0) -> None:
        """Wait for the run in progress, if any, to finish."""
        if self.worker is not None:
            self.worker.join(timeout)


_running: list[GuiApp] = []  # the app last built, so running a cell again replaces its timer rather than adding one
# endregion


# region Public API
def build_app(folder: str | Path | None = None, *, plan_refresh: float = PLAN_REFRESH_SECONDS) -> GuiApp:
    """Build the form, the map and the run controls, and wire them up.

    Building a second app closes the first one's cache timer, so running the notebook cell again is safe.

    Args:
        folder (str | Path | None): Where the cache, output and last session are kept. Default the current folder,
            which is the notebook's.
        plan_refresh (float): Seconds between looks at the cache folder to update the 'N files, M cached' line.

    Returns:
        GuiApp: The app; show app.layout.
    """
    base = Path(folder) if folder is not None else Path.cwd()
    first = SiteState('mast-1', *DEFAULT_POINT)
    domain = next(iter(BARRA2_DOMAINS))
    shared: dict[str, Any] = {
        'start': w.DatePicker(value=date(2023, 1, 1), description='Start'),
        'end': w.DatePicker(value=date(2023, 1, 31), description='End'),
        'domain': w.Dropdown(options=list(BARRA2_DOMAINS), value=domain, description='Domain'),
        'freq': w.Dropdown(options=list(BARRA2_FREQS[domain]), value='1hr', description='Frequency'),
        'preset': w.Dropdown(options=list(BARRA2_PRESETS), value='wind+density', description='Preset'),
        'node_selection': w.Dropdown(options=SELECTIONS, value='nearest', description='Mast nodes'),
        'format': w.Dropdown(options=list(BARRA2_OUTPUT_FORMATS), value='netcdf', description='Output'),
        'cache': w.Text(value=str(base / 'cache'), description='Cache folder'),
        'out': w.Text(value=str(base / 'out'), description='Output folder'),
    }
    place: dict[str, Any] = {
        'name': w.Text(value=first.name, description='Name'),
        'lat': w.BoundedFloatText(value=first.lat, min=-90, max=90, step=0.01, description='Latitude'),
        'lon': w.BoundedFloatText(value=first.lon, min=-180, max=180, step=0.01, description='Longitude'),
    }
    fmap = Map(center=DEFAULT_POINT, zoom=11, scroll_wheel_zoom=True, layout=w.Layout(height='480px'))
    draw = GeomanDrawControl(
        polygon=DRAW_POLYGON,
        polyline={},
        rectangle={},
        circle={},
        marker={},
        circlemarker={},
        edit=True,
        remove=True,
        drag=True,
        cut=False,
        rotate=False,
    )
    fmap.add(draw)
    app = GuiApp(
        folder=base,
        plan_refresh=plan_refresh,
        sites=[first],
        site_select=w.Dropdown(options=[(first.name, 0)], value=0, description='Site'),
        add_button=w.Button(description='Add mast', icon='plus'),
        remove_button=w.Button(description='Remove site', icon='trash'),
        site_fields=place,
        shared_fields=shared,
        mean_box=w.Checkbox(description='Also write the weighted mean of the nodes', indent=False),
        selection_note=w.HTML(layout=w.Layout(margin='0 0 6px 6px')),
        preset_note=w.HTML(layout=w.Layout(margin='0 0 6px 6px')),
        find_button=w.Button(description='Find nodes', icon='search'),
        run_button=w.Button(description='Run all sites', button_style='primary', icon='play'),
        run_selected_button=w.Button(description='Run selected site', icon='play'),
        cancel_button=w.Button(
            description='Cancel', button_style='warning', icon='stop', layout=w.Layout(display='none')
        ),
        plan_label=w.Label(),
        problems_box=w.HTML(),
        node_info=w.HTML('Drag a mast to move it. Click a blue node to choose it. Draw a polygon to add the area.'),
        progress=w.IntProgress(min=0, max=1, layout=w.Layout(width='100%', display='none')),
        progress_label=w.Label(),
        result_box=w.HTML(),
        import_path=w.Text(
            placeholder='path to a project.toml, .geojson, .json or .kml', layout=w.Layout(width='300px')
        ),
        import_button=w.Button(description='Import path', icon='folder-open'),
        import_upload=w.FileUpload(accept='.toml,.geojson,.json,.kml', multiple=True, description='Upload file(s)'),
        session_button=w.Button(description='Load last session', icon='history'),
        import_info=w.HTML(),
        fmap=fmap,
        draw=draw,
    )
    app.layout = _layout(app)
    _wire(app)
    while _running:
        _running.pop().close()
    _running.append(app)
    threading.Thread(target=_keep_plan_current, args=(app,), daemon=True).start()
    _refresh(app)
    return app


def select(app: GuiApp, index: int) -> None:
    """Make another site the one being worked on."""
    app.active = index
    _refresh(app)


def moved(app: GuiApp, index: int, location: tuple[float, float]) -> None:
    """A mast was dragged: move it, and forget its nodes because they were for the old place."""
    site = app.sites[index]
    lat, lon = round(location[0], 4), round(location[1], 4)
    if (site.lat, site.lon) == (lat, lon):
        return
    site.lat, site.lon = lat, lon
    site.forget_nodes()
    app.active = index
    app.node_info.value = f'{site.name} moved to {lat:.4f}, {lon:.4f}. Find nodes again to see its nodes.'
    _refresh(app)


def add_site(app: GuiApp) -> None:
    """Add a mast just north of the active site, and work on it."""
    site = _active(app)
    name = _unique_name(app, 'mast')
    app.sites.append(SiteState(name, round(site.lat + 0.06, 4), site.lon))
    app.active = len(app.sites) - 1
    app.node_info.value = f'Added {name}. Drag its marker to where it belongs.'
    _refresh(app)


def remove_site(app: GuiApp) -> None:
    """Remove the active site; removing the area clears it from the map too."""
    gone = app.sites.pop(app.active)
    app.results.pop(gone.name, None)
    if gone.polygon:
        app.draw.data = []
    if not app.sites:
        app.sites.append(SiteState('mast-1', *DEFAULT_POINT))
    app.active = max(0, app.active - 1)
    _show_results(app)
    _refresh(app)


def find(app: GuiApp) -> None:
    """Look up the nodes the active site would use: the nine around a mast, the nodes the area overlaps."""
    site = _active(app)
    domain = app.shared_fields['domain'].value
    try:
        if site.polygon:
            found = polygon_nodes(_polygon_of(site), domain)
            site.offered = [node for node, _share in found]
            site.shares = {(node.lat, node.lon): share for node, share in found}
            app.node_info.value = f'{len(found)} nodes overlap {site.name} (click one for its share).'
        else:
            site.offered = nearest_nodes(LatLonPoint(site.lat, site.lon), domain, n=9)
            app.node_info.value = f'{len(site.offered)} nodes offered. Click one to choose it.'
        site.chosen = []
    except (ValueError, RuntimeError) as error:  # NodeLookupError, BoundaryFileError, CacheMismatchError and the like
        app.node_info.value = f'<span style="color:{RED}">{error}</span>'
    _refresh(app)


def toggle(app: GuiApp, node: GridNode) -> None:
    """Show a node's details; for a mast also choose or drop it."""
    site = _active(app)
    text = f'{node.lat:.3f}, {node.lon:.3f}: {node.distance_km:.1f} km, orog {node.orog:.0f} m, land {node.sftlf:.0f}%'
    if site.polygon:
        share = site.shares.get((node.lat, node.lon), math.nan)
        app.node_info.value = f'{text}, {share:.0%} of its cell inside the area. An area uses all of these.'
        return
    key = (node.lat, node.lon)
    if any((chosen.lat, chosen.lon) == key for chosen in site.chosen):
        site.chosen = [chosen for chosen in site.chosen if (chosen.lat, chosen.lon) != key]
    else:
        site.chosen = [*site.chosen, node]
    app.node_info.value = f'{text}. {len(site.chosen)} chosen.'
    _refresh(app)


def start(app: GuiApp, indices: list[int]) -> None:
    """Run these sites one after another on a worker thread; the thread updates the widgets itself."""
    jobs = []
    for index in indices:
        settings, built, _problems = _build(app, app.sites[index])
        jobs.append((app.sites[index].name, settings, built))
    _save_session(app)
    cancel = app.cancel = threading.Event()
    for index in indices:
        app.sites[index].used = []
        app.results.pop(app.sites[index].name, None)
    _show_results(app)
    app.progress.value, app.progress.max = 0, 1
    app.progress.layout.display = app.cancel_button.layout.display = ''
    app.run_button.disabled = app.run_selected_button.disabled = True
    _note(f'Run started: {", ".join(name for name, _s, _b in jobs)}')

    def work() -> None:
        for number, (name, settings, built) in enumerate(jobs, start=1):
            if cancel.is_set():
                break

            def on_progress(done: int, total: int, result: Any, name: str = name, number: int = number) -> None:
                app.progress.max, app.progress.value = max(total, 1), done
                where = f'{name} (site {number} of {len(jobs)})' if len(jobs) > 1 else name
                app.progress_label.value = f'{where}: file {done} of {total}: {result.filename}: {result.status}'

            data = site_result_to_dict(run_site(built, settings, on_progress, cancel))
            site = next((each for each in app.sites if each.name == name), None)
            if site is not None:
                site.used = data['nodes']
            app.results[name] = _render(name, data)
            _show_results(app)
            _note(f'{name}: {data["status"]}')
        app.cancel = None
        app.progress.layout.display = app.cancel_button.layout.display = 'none'
        _refresh(app)

    app.worker = threading.Thread(target=work, daemon=True)
    app.worker.start()


def load_session(app: GuiApp) -> None:
    """Restore the settings and sites saved by the last run, ready to Run again: cached files are skipped."""
    path = app.folder / SESSION_FILE
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        active = data.pop('active', None)
        project = project_from_dict(data, app.folder)
    except (OSError, ValueError) as error:  # a missing file, bad JSON or ProjectError
        _say(app, f'No last session to load ({SESSION_FILE}: {error}). One is saved each time you run.', ok=False)
        return
    names = [site.name for site in project.sites]
    _apply_project(app, project, '', names.index(active) if active in names else 0)
    _say(app, f'Loaded the last session: {len(project.sites)} site(s). Run to update the cache and the output files.')


def import_from_path(app: GuiApp) -> None:
    """Import the file named in the path box: a project.toml, or a GeoJSON or KML polygon."""
    path = Path(app.import_path.value.strip().strip('"'))
    try:
        if path.suffix.lower() == '.toml':
            _apply_project(app, load_project(path), path.name)
        else:
            _import_text(app, path.name, path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        _say(app, str(error), ok=False)


def import_from_upload(app: GuiApp, items: list[dict[str, Any]]) -> None:
    """Import what was chosen in the Upload box: a project with its files, or a polygon file."""
    if not items:
        return
    if any(item['name'].lower().endswith('.toml') for item in items):
        _import_uploaded_project(app, items)
    else:
        _import_text(app, items[0]['name'], bytes(items[0]['content']).decode('utf-8'))
    app.import_upload.value = ()


# endregion


# region Helpers
def _layout(app: GuiApp) -> Any:
    """The form on the left, the map and the run controls on the right."""
    notes = {
        'preset': (app.preset_note,),
        'node_selection': (app.selection_note,),
    }  # shown under the field they explain
    text = (
        'A <b>project.toml</b> replaces the settings and all sites. A <b>.geojson</b>, <b>.json</b> or <b>.kml</b> '
        'polygon becomes the area. A path resolves a polygon file named in a project relative to the project. An '
        'upload takes the polygon file too: select it with the project.toml (Ctrl-click).'
    )
    session = (
        f'Each run saves its settings and sites to <code>{SESSION_FILE}</code>. <b>Load last session</b> restores '
        'them, so a Run carries on: cached files are skipped and the output files are rewritten.'
    )
    import_box = w.Accordion(
        children=[
            w.VBox(
                [
                    w.HTML(text),
                    w.HBox([app.import_path, app.import_button]),
                    app.import_upload,
                    w.HTML(session),
                    app.session_button,
                    app.import_info,
                ]
            )
        ],
        titles=('Import a project, polygon file or the last session',),
        selected_index=None,
    )
    form = w.VBox(
        [
            w.HBox([app.site_select, app.add_button], layout=w.Layout(width='440px')),
            *app.site_fields.values(),
            w.HBox([app.find_button, app.remove_button]),
            app.mean_box,
            *(item for key, widget in app.shared_fields.items() for item in (widget, *notes.get(key, ()))),
            import_box,
        ],
        layout=w.Layout(width='440px'),
    )
    right = w.VBox(
        [
            app.fmap,
            app.node_info,
            app.plan_label,
            app.problems_box,
            w.HBox([app.run_button, app.run_selected_button, app.cancel_button]),
            app.progress,
            app.progress_label,
            app.result_box,
        ],
        layout=w.Layout(flex='1'),
    )
    return w.HBox([form, right])


def _wire(app: GuiApp) -> None:
    """Connect the widgets' events to the handlers."""
    for widget in app.shared_fields.values():
        widget.observe(lambda _change: _refresh(app), names='value')
    app.shared_fields['domain'].observe(lambda change: _on_domain(app, change['new']), names='value')
    for widget in app.site_fields.values():
        widget.observe(lambda _change: _on_site_edit(app), names='value')
    app.site_select.observe(lambda change: None if app.loading else select(app, change['new']), names='value')
    app.find_button.on_click(lambda _button: find(app))
    app.run_button.on_click(lambda _button: start(app, list(range(len(app.sites)))))
    app.run_selected_button.on_click(lambda _button: start(app, [app.active]))
    app.cancel_button.on_click(lambda _button: _cancel(app))
    app.add_button.on_click(lambda _button: add_site(app))
    app.remove_button.on_click(lambda _button: remove_site(app))
    app.import_button.on_click(lambda _button: import_from_path(app))
    app.session_button.on_click(lambda _button: load_session(app))
    app.mean_box.observe(lambda change: _on_mean(app, bool(change['new'])), names='value')
    app.import_upload.observe(lambda change: import_from_upload(app, list(change['new'])), names='value')
    app.draw.observe(lambda change: _on_draw(app, change['new']), names='data')
    app.draw.on_click(lambda **_event: _on_area_click(app))


def _cancel(app: GuiApp) -> None:
    """Stop the run in progress after the file it is on."""
    if app.cancel is not None:
        app.cancel.set()


def _note(text: str) -> None:
    """Report progress to the log and to the console under the cell, as the library's modules do."""
    logger.info(text)
    sys.stdout.write(text + '\n')


def _active(app: GuiApp) -> SiteState:
    """The site being worked on."""
    return app.sites[app.active]


def _area_index(app: GuiApp) -> int | None:
    """Where the area is in the site list, or None."""
    return next((i for i, site in enumerate(app.sites) if site.polygon), None)


def _unique_name(app: GuiApp, prefix: str) -> str:
    """mast-1, mast-2, ... the first one no site has."""
    taken = {site.name for site in app.sites}
    return next(f'{prefix}-{n}' for n in range(1, len(taken) + 2) if f'{prefix}-{n}' not in taken)


def _centre(feature: dict[str, Any]) -> tuple[float, float]:
    """The middle of a polygon feature's vertices as (lat, lon), which stands in for the area's place."""
    ring = feature['geometry']['coordinates'][0][:-1]
    return round(sum(p[1] for p in ring) / len(ring), 4), round(sum(p[0] for p in ring) / len(ring), 4)


def _feature_of(polygon: Polygon, source: str = '') -> dict[str, Any]:
    """A Polygon as a GeoJSON feature: the library keeps (lat, lon), GeoJSON wants [lon, lat] and closed rings."""
    rings = [[[lon, lat] for lat, lon in ring] for ring in (polygon.exterior, *polygon.holes)]
    return {
        'type': 'Feature',
        'properties': {'source': source or polygon.source},
        'geometry': {'type': 'Polygon', 'coordinates': [[*ring, ring[0]] for ring in rings]},
    }


def _polygon_of(site: SiteState) -> Polygon:
    """The area as a Polygon; its source is where it was imported from, or 'drawn'."""
    feature = site.polygon or {}
    source = feature.get('properties', {}).get('source') or 'drawn'
    return polygon_from_geojson(json.dumps(feature), source)


def _same_shape(first: dict[str, Any], second: dict[str, Any]) -> bool:
    """Whether two polygon features have the same outline, to 5 decimals (Leaflet rounds what it sends back)."""

    def rounded(feature: dict[str, Any]) -> list[Any]:
        return [[[round(c, 5) for c in point] for point in ring] for ring in feature['geometry']['coordinates']]

    return rounded(first) == rounded(second)


def _folder(app: GuiApp, text: str, default: str) -> Path:
    """A folder from the form: relative to the notebook's folder, or the default there when the box is empty."""
    return app.folder / (text.strip() or default)


def _settings(app: GuiApp) -> Settings:
    """The shared settings from the form; a cleared date reads as year 1900 so that validation reports it."""
    values = {key: widget.value for key, widget in app.shared_fields.items()}
    return Settings(
        start=values['start'] or date(1900, 1, 1),
        end=values['end'] or date(1900, 1, 1),
        domain=values['domain'],
        freq=values['freq'],
        preset=values['preset'],
        node_selection=values['node_selection'],
        format=values['format'],
        cache=_folder(app, values['cache'], 'cache'),
        out=_folder(app, values['out'], 'out'),
    )


def _build(app: GuiApp, each: SiteState) -> tuple[Settings, Site, list[tuple[str, str]]]:
    """Settings, Site and (key, message) problems for one site; a place or polygon the library rejects is one."""
    settings, problems = _settings(app), []
    polygon, point = None, None
    if each.polygon:
        try:
            polygon = _polygon_of(each)
        except BoundaryFileError as error:
            problems.append(('polygon', str(error)))
    else:
        try:
            point = LatLonPoint(each.lat, each.lon)
        except ValueError as error:
            problems.append(('lat', str(error)))
    nodes = [LatLonPoint(node.lat, node.lon) for node in each.chosen] or None
    nodes = None if each.polygon else nodes
    mean = each.mean and (polygon is not None or nodes is not None)
    built = Site(each.name, point=point, polygon=polygon, nodes=nodes, node_mean=mean)
    if not problems:
        problems += [(problem.key, problem.message) for problem in validate(settings, built)]
    return settings, built, problems


def _plan_text(built: Site, settings: Settings) -> str:
    """'N files, M cached'."""
    plan = plan_site(built, settings)
    return f'{len(plan.files)} files, {sum(file.cached for file in plan.files)} cached'


def _plan_summary(app: GuiApp) -> str:
    """'name: N files, M cached' for each valid site, looking at the cache folder as it is now."""
    plans = []
    for each in list(app.sites):
        settings, built, problems = _build(app, each)
        if not problems:
            plans.append(f'{each.name}: {_plan_text(built, settings)}')
    return '; '.join(plans)


def _keep_plan_current(app: GuiApp) -> None:
    """Every few seconds, look at the cache folder's file names; when they change, update the plan line.

    Listing names is cheap. Checking the files themselves (what _plan_summary does) opens each one, so it waits for a
    change, and for a run to finish, which refreshes the line itself.
    """
    seen: frozenset[str] | None = None
    while not app.stop_timer.wait(app.plan_refresh):
        folder = _folder(app, app.shared_fields['cache'].value, 'cache')
        try:
            names = frozenset(path.name for path in folder.iterdir()) if folder.is_dir() else frozenset()
            if names == seen or app.cancel is not None or app.loading:
                continue
            seen = names
            text = _plan_summary(app)
        except (OSError, ValueError, KeyError, IndexError):  # the form was mid-change; try again next time
            continue
        if text != app.plan_label.value:
            app.plan_label.value = text


def _check_sites(app: GuiApp) -> tuple[list[str], list[str], set[int]]:
    """Validate every site: the problem lines to show, each valid site's plan, and which sites have problems."""
    lines, plans, bad = [], [], set()
    fields = app.site_fields | app.shared_fields
    for index, each in enumerate(app.sites):
        settings, built, problems = _build(app, each)
        lines += [f'<div style="color:{RED}">{each.name}: {key}: {message}</div>' for key, message in problems]
        if problems:
            bad.add(index)
        if index == app.active:
            for key, _message in problems:
                if key in fields:
                    fields[key].layout.border = f'2px solid {RED}'
        if not problems:
            plans.append(f'{each.name}: {_plan_text(built, settings)}')
    return lines, plans, bad


def _refresh(app: GuiApp, *_args: Any) -> None:
    """Validate every site, mark the active site's fields at fault, update the plan and the buttons, redraw the map."""
    if app.loading:
        return
    for widget in (app.site_fields | app.shared_fields).values():
        widget.layout.border = ''
    lines, plans, bad = _check_sites(app)
    names = [each.name for each in app.sites]
    duplicate = len(set(names)) != len(names)
    if duplicate:
        lines.append(f'<div style="color:{RED}">site names must be different</div>')
    app.problems_box.value = ''.join(lines)
    app.plan_label.value = '; '.join(plans)
    busy = app.cancel is not None
    app.run_button.disabled = bool(bad) or duplicate or busy
    app.run_selected_button.disabled = app.active in bad or duplicate or busy
    # one area only: the draw tool goes while there is one (if the control ignores this, _on_draw keeps the first)
    wanted = {} if _area_index(app) is not None else DRAW_POLYGON
    if app.draw.polygon != wanted:
        app.draw.polygon = wanted
    _style_area(app)
    _load_site(app)
    _draw_sites(app)
    _draw_nodes(app)


def _style_area(app: GuiApp) -> None:
    """Purple for the active area, grey otherwise: the draw control takes a feature's colour from its properties."""
    index = _area_index(app)
    feature = app.sites[index].polygon if index is not None else None
    if feature is None:
        return
    colour = AREA_COLOURS[index == app.active]
    style = feature.setdefault('properties', {}).get('style') or {}
    if style.get('color') == colour:
        return
    feature['properties']['style'] = {**style, 'color': colour, 'fillColor': colour}
    app.draw.data = [feature]


def _area_label(site: SiteState, is_active: bool) -> Any:
    """The area's name at its middle: shown on the map, and as a tooltip like a mast's."""
    colour = '#7c3aed' if is_active else '#6b7280'
    style = f'color:{colour}; font-weight:600; text-shadow:0 0 3px #fff; text-align:center'
    icon = DivIcon(html=f'<div style="{style}">{site.name}</div>', icon_size=(90, 20), icon_anchor=(45, 10))
    return Marker(location=(site.lat, site.lon), draggable=False, title=site.name, icon=icon)


def _draw_sites(app: GuiApp) -> None:
    """A draggable marker for each mast and a name label for the area; the area is the draw control's own layer."""
    for layer in app.markers:
        app.fmap.remove(layer)
    app.markers = []
    for index, site in enumerate(app.sites):
        if site.polygon:
            marker = _area_label(site, index == app.active)
        else:
            colour = 'black' if index == app.active else 'lightgray'
            icon = AwesomeIcon(name='crosshairs', marker_color=colour, icon_color='white')
            marker = Marker(location=(site.lat, site.lon), draggable=True, title=site.name, icon=icon)
            marker.observe(lambda change, index=index: moved(app, index, change['new']), names='location')
        marker.on_click(lambda *_a, index=index, **_k: select(app, index))
        app.markers.append(marker)
        app.fmap.add(marker)


def _planned(app: GuiApp, site: SiteState) -> list[GridNode]:
    """The nodes a run of the site would download, out of the nodes offered: the library's own plan."""
    point = LatLonPoint(site.lat, site.lon)
    if site.polygon:
        return planned_nodes(point, site.offered, 'area')
    if site.chosen:
        return planned_nodes(point, site.chosen, 'nodes')
    return planned_nodes(point, site.offered, app.shared_fields['node_selection'].value)


def _draw_nodes(app: GuiApp) -> None:
    """The active site's offered, chosen and used nodes (the markers are drawn by _draw_sites)."""
    for layer in app.node_layers:
        app.fmap.remove(layer)
    app.node_layers = []
    site = _active(app)
    picked = {(node.lat, node.lon) for node in site.chosen}
    for node in [*site.offered, *(node for node in site.chosen if node not in site.offered)]:
        colour = COLOURS['chosen'] if (node.lat, node.lon) in picked or site.polygon else COLOURS['offered']
        marker = CircleMarker(
            location=(node.lat, node.lon), radius=9, color=colour, fill_color=colour, fill_opacity=0.7
        )
        marker.on_click(lambda *_a, node=node, **_k: toggle(app, node))
        app.node_layers.append(marker)
    for node in _planned(app, site):
        app.node_layers.append(
            CircleMarker(location=(node.lat, node.lon), radius=14, color=PLANNED, fill=False, weight=3)
        )
    for used in site.used:
        app.node_layers.append(
            CircleMarker(location=(used['lat'], used['lon']), radius=19, color=COLOURS['used'], fill=False, weight=4)
        )
    for layer in app.node_layers:
        app.fmap.add(layer)


def _describe_preset(app: GuiApp) -> str:
    """The chosen preset's variables from barra2_dl.globals (read each time), and whether the domain has them."""
    name, domain, freq = (app.shared_fields[key].value for key in ('preset', 'domain', 'freq'))
    variables = barra2_globals.BARRA2_PRESETS[name]
    fixed = ', '.join(barra2_globals.BARRA2_FIXED_VARS_AUTO)
    text = f'<i>{name}: {len(variables)} variables: {", ".join(variables)}. {fixed} is added to every download.</i>'
    try:
        preset_variables(name, domain, freq)
    except ValueError as error:  # the preset needs variables this domain and frequency do not have
        text += f'<br><span style="color:{RED}">{error}</span>'
    return text


def _describe_selection(app: GuiApp, site: SiteState) -> str:
    """What a run of the site downloads, in words, since the node choice only applies to a mast."""
    if site.polygon:
        found = f' ({len(site.offered)} shown)' if site.offered else ''
        return (
            f'<i>Area: every node whose cell the polygon overlaps is downloaded{found}, not just the centre. '
            'The node choice does not apply. Violet rings mark them.</i>'
        )
    if site.chosen:
        return f'<i>The {len(site.chosen)} chosen node(s) are downloaded; the node choice does not apply.</i>'
    if app.shared_fields['node_selection'].value == 'nearest':
        return '<i>nearest: the one node nearest the mast is downloaded (violet ring after Find nodes).</i>'
    return (
        '<i>average4: the four nodes around the mast are downloaded and averaged with inverse-distance weights '
        '(violet rings after Find nodes).</i>'
    )


def _load_site(app: GuiApp) -> None:
    """Show the active site in the name, latitude and longitude boxes (an area has no place boxes) and the list."""
    app.loading = True
    site = _active(app)
    app.site_fields['name'].value = site.name
    for key in ('lat', 'lon'):
        app.site_fields[key].value = getattr(site, key)
        app.site_fields[key].layout.display = 'none' if site.polygon else ''
    app.site_select.options = [(f'{s.name}{" (area)" if s.polygon else ""}', i) for i, s in enumerate(app.sites)]
    app.site_select.value = app.active
    app.remove_button.disabled = len(app.sites) == 1 and not site.polygon
    uses_nodes = bool(site.polygon or site.chosen)
    app.mean_box.layout.display = '' if uses_nodes else 'none'
    app.mean_box.value = site.mean and uses_nodes
    app.shared_fields['node_selection'].disabled = uses_nodes
    app.selection_note.value = _describe_selection(app, site)
    app.preset_note.value = _describe_preset(app)
    app.loading = False


def _show_results(app: GuiApp) -> None:
    """The latest result of each site that has one, in site order."""
    app.result_box.value = ''.join(app.results[site.name] for site in app.sites if site.name in app.results)


def _render(name: str, data: dict[str, Any]) -> str:
    """One site's run summary as HTML."""
    parts = [f'<h3>{name}: {data["status"]}</h3>']
    if data['error']:
        parts.append(f'<p style="color:{RED}">{data["error"]}</p>')
    if data['missing']:
        parts.append('<p style="color:#d97706">missing: ' + ', '.join(data['missing']) + '</p>')
    parts.append('<p>Outputs: ' + ', '.join(data['outputs']) + '</p>')
    if data['files']:
        parts.append(pd.DataFrame(data['files'])[['name', 'status', 'status_code', 'attempts']].to_html(index=False))
    if data['nodes']:
        nodes = pd.DataFrame(data['nodes'])
        keys = [column for column in ('lat', 'lon', 'distance_km', 'orog', 'weight', 'overlap') if column in nodes]
        parts.append(nodes[keys].to_html(index=False))
    return ''.join(parts)


def _on_domain(app: GuiApp, domain: str) -> None:
    """The frequencies depend on the domain; the nodes depend on it too."""
    options = list(BARRA2_FREQS[domain])
    freq = app.shared_fields['freq']
    freq.options = options
    freq.value = freq.value if freq.value in options else options[0]
    for each in app.sites:
        each.forget_nodes()


def _on_site_edit(app: GuiApp) -> None:
    """The name, latitude or longitude box was edited: the site takes it, the marker follows, and moved nodes go."""
    if app.loading:
        return
    site = _active(app)
    place = (app.site_fields['lat'].value, app.site_fields['lon'].value)
    if place != (site.lat, site.lon):
        site.forget_nodes()
    new_name = app.site_fields['name'].value
    if new_name != site.name and site.name in app.results:
        app.results[new_name] = app.results.pop(site.name)
    site.name, site.lat, site.lon = new_name, place[0], place[1]
    _refresh(app)


def _on_mean(app: GuiApp, ticked: bool) -> None:
    """The mean box was ticked: the active site writes the weighted mean of its nodes too."""
    if not app.loading:
        _active(app).mean = ticked
        _refresh(app)


def _on_draw(app: GuiApp, features: list[dict[str, Any]]) -> None:
    """The map's polygons changed (drawn, reshaped, moved or deleted): keep the one area in step with them."""
    polygons = [feature for feature in features if feature.get('geometry', {}).get('type') == 'Polygon']
    index = _area_index(app)
    if not polygons:
        if index is None:
            return
        gone = app.sites.pop(index)
        app.results.pop(gone.name, None)
        if not app.sites:
            app.sites.append(SiteState('mast-1', *DEFAULT_POINT))
        app.active = min(app.active, len(app.sites) - 1)
        app.node_info.value = f'{gone.name} was deleted.'
        _refresh(app)
        return
    if index is None:
        lat, lon = _centre(polygons[-1])
        app.sites.append(SiteState(_unique_name(app, 'area'), lat, lon, polygons[-1]))
        app.active = len(app.sites) - 1
        vertices = len(polygons[-1]['geometry']['coordinates'][0]) - 1
        app.node_info.value = f'Added {_active(app).name} ({vertices} vertices). Find nodes to preview its nodes.'
        _refresh(app)
        return
    site = app.sites[index]
    if len(polygons) > 1:  # a second polygon was drawn: keep the first
        app.node_info.value = f'Only one area is allowed. Delete {site.name} to draw another.'
        app.draw.data = [site.polygon]
        return
    if site.polygon is not None and _same_shape(polygons[0], site.polygon):
        return
    site.polygon = polygons[0]
    site.lat, site.lon = _centre(polygons[0])
    site.forget_nodes()
    app.active = index
    app.node_info.value = f'{site.name} was reshaped. Find nodes to preview its nodes.'
    _refresh(app)


def _on_area_click(app: GuiApp) -> None:
    """The area was clicked on the map: make it the site being worked on."""
    index = _area_index(app)
    if index is not None and index != app.active:
        select(app, index)


def _say(app: GuiApp, text: str, *, ok: bool = True) -> None:
    """Report an import's outcome under the Import section, red when it failed."""
    colour = '#16a34a' if ok else RED
    app.import_info.value = f'<div style="color:{colour}; white-space:pre-wrap">{text}</div>'
    _note(text)


def _show_area(app: GuiApp, feature: dict[str, Any]) -> None:
    """Put a polygon on the map and zoom to it."""
    app.draw.data = [feature]
    ring = feature['geometry']['coordinates'][0]
    lons, lats = [p[0] for p in ring], [p[1] for p in ring]
    try:
        app.fmap.fit_bounds([[min(lats), min(lons)], [max(lats), max(lons)]])
    except RuntimeError:  # fit_bounds needs an event loop, which a kernel has and a plain interpreter (3.14) may not
        app.fmap.center = (sum(lats) / len(lats), sum(lons) / len(lons))


def _apply_polygon(app: GuiApp, polygon: Polygon, name: str) -> None:
    """Make an imported polygon the area, replacing the area there is."""
    feature = _feature_of(polygon, name)
    lat, lon = _centre(feature)
    stem = re.sub(r'[^A-Za-z0-9._-]', '-', Path(name).stem)
    index = _area_index(app)
    if index is None:
        taken = {site.name for site in app.sites}
        label = stem if stem and stem not in taken else _unique_name(app, 'area')
        app.sites.append(SiteState(label, lat, lon, feature))
        index = len(app.sites) - 1
    else:
        site = app.sites[index]
        site.polygon, site.lat, site.lon = feature, lat, lon
        site.forget_nodes()
    app.active = index
    app.node_info.value = 'Find nodes to preview the nodes this area uses.'
    _show_area(app, feature)
    _refresh(app)
    rings = len(feature['geometry']['coordinates'])
    _say(app, f'Imported the polygon from {name} as {app.sites[index].name} ({rings} ring(s)).')


def _project_sites(project: Project) -> tuple[list[SiteState], dict[str, Any] | None, list[str]]:
    """The sites of a project as the notebook shows them, the area's feature, and notes on what was left out."""
    notes, imported, area = [], [], None
    for site in project.sites:
        if site.bbox is not None:
            notes.append(f'{site.name}: a box site is not supported here, skipped.')
            continue
        if site.overrides:
            ignored = ', '.join(site.overrides)
            notes.append(f'{site.name}: its own {ignored} setting(s) are ignored; settings are shared.')
        if site.polygon is not None:
            if area is not None:
                notes.append(f'{site.name}: only one area is allowed, skipped.')
                continue
            area = _feature_of(site.polygon)
            imported.append(SiteState(site.name, *_centre(area), area, mean=site.node_mean))
        elif site.point is not None:
            nodes = [GridNode(float(node.lat), float(node.lon), **NO_NODE) for node in site.nodes or []]
            place = (float(site.point.lat), float(site.point.lon))
            imported.append(SiteState(site.name, *place, chosen=nodes, mean=site.node_mean))
    return imported, area, notes


def _apply_project(app: GuiApp, project: Project, name: str, active: int = 0) -> None:
    """Replace the settings and the sites with a project's. What the notebook cannot show is skipped, and said so."""
    imported, area, notes = _project_sites(project)
    if not imported:
        raise ValueError('The project has no site this notebook can show.')
    settings, fields = project.settings, app.shared_fields
    app.loading = True
    try:
        fields['domain'].value = settings.domain
        fields['freq'].options = list(BARRA2_FREQS[settings.domain])
        for key in ('start', 'end', 'freq', 'preset', 'format'):
            fields[key].value = getattr(settings, key)
        if settings.node_selection in SELECTIONS:
            fields['node_selection'].value = settings.node_selection
        fields['cache'].value, fields['out'].value = str(settings.cache), str(settings.out)
    finally:
        app.loading = False
    _show_sites(app, imported, area, min(active, len(imported) - 1))
    if name:
        _say(app, '\n'.join([f'Imported {name}: {len(imported)} site(s).', *notes]), ok=not notes)


def _show_sites(app: GuiApp, new_sites: list[SiteState], area: dict[str, Any] | None, active: int) -> None:
    """Replace the sites and show them: the area on the map, or the active mast when there is none."""
    app.sites[:] = new_sites
    app.active, app.results = active, {}
    _show_results(app)
    app.node_info.value = 'Pick a site and Find nodes to see its nodes.'
    if area is not None:
        _show_area(app, area)
    else:
        app.draw.data = []
        app.fmap.center = (new_sites[active].lat, new_sites[active].lon)
    _refresh(app)


def _save_session(app: GuiApp) -> None:
    """Write the settings and the valid sites to the session file, so a later run can carry on. Done at every run."""
    settings, built = _settings(app), []
    for each in app.sites:
        _settings_unused, site, problems = _build(app, each)
        if not problems:
            built.append(site)
    data = project_to_dict(Project(settings, built)) | {'active': _active(app).name}
    (app.folder / SESSION_FILE).write_text(json.dumps(data, indent=2), encoding='utf-8')


def _import_text(app: GuiApp, name: str, text: str) -> None:
    """Import a file's text by what its name ends with; a problem is shown, not raised."""
    lower = name.lower()
    if not lower.endswith(('.toml', '.kml', '.geojson', '.json')):
        _say(app, f'{name}: use a .toml project or a .geojson, .json or .kml polygon.', ok=False)
        return
    try:
        if lower.endswith('.toml'):
            _apply_project(app, project_from_dict(tomllib.loads(text), app.folder), name)
        elif lower.endswith('.kml'):
            _apply_polygon(app, polygon_from_kml(text, name), name)
        else:
            _apply_polygon(app, polygon_from_geojson(text, name), name)
    except ValueError as error:  # a bad project (ProjectError), polygon (BoundaryFileError) or TOML
        _say(app, str(error), ok=False)


def _import_uploaded_project(app: GuiApp, items: list[dict[str, Any]]) -> None:
    """Import an uploaded project.toml with the files uploaded beside it, which its polygon file may be."""
    with tempfile.TemporaryDirectory() as folder:
        for item in items:
            (Path(folder) / Path(item['name']).name).write_bytes(bytes(item['content']))
        toml = next(item for item in items if item['name'].lower().endswith('.toml'))
        try:
            project = load_project(Path(folder) / Path(toml['name']).name)
            # a relative cache or out folder means next to the notebook, not inside the temporary copy
            settings = replace(
                project.settings,
                cache=_rebase(app, project.settings.cache, folder),
                out=_rebase(app, project.settings.out, folder),
            )
            _apply_project(app, replace(project, settings=settings, path=None), toml['name'])
        except ValueError as error:
            hint = '\nSelect the polygon file together with the project.toml, or use the path box.'
            _say(app, str(error) + (hint if 'Cannot read' in str(error) else ''), ok=False)


def _rebase(app: GuiApp, path: Path, folder: str) -> Path:
    """A path inside the temporary upload folder, moved to the same place under the notebook's folder."""
    try:
        return app.folder / path.relative_to(folder)
    except ValueError:
        return path


# endregion
