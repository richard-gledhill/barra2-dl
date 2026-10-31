"""Spike 2: NiceGUI with its built-in Leaflet map.

Run: python spikes/nicegui/app.py (starts the server on port 8602 and opens the browser).
"""

import json
import os
import threading
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from nicegui import run, ui
from spike_common import (
    COLOURS,
    DEFAULTS,
    DOMAINS,
    FORMATS,
    PRESETS,
    SELECTIONS,
    build,
    find_nodes,
    freqs,
    plan_text,
    summary,
)

from barra2_dl.project import run_site


@dataclass
class State:
    """Everything one browser tab holds."""

    values: dict[str, Any] = field(
        default_factory=lambda: dict(DEFAULTS) | {'start': '2023-01-01', 'end': '2023-06-30'}
    )
    offered: list[dict[str, Any]] = field(default_factory=list)
    chosen: list[dict[str, Any]] = field(default_factory=list)
    polygon: str | None = None
    layers: list[Any] = field(default_factory=list)
    done: int = 0
    total: int = 0
    last: str = ''
    running: bool = False
    cancel: threading.Event = field(default_factory=threading.Event)


def main() -> None:
    """Start the server and open the browser, as barra2_dl.gui:main would."""
    ui.run(port=int(os.environ.get('SPIKE_PORT', '8602')), reload=False, title='BARRA2 download (NiceGUI spike)')


def _circle(m: Any, node: dict[str, Any], radius: int, colour: str, fill: bool, text: str) -> Any:
    options = {'radius': radius, 'color': colour, 'fillColor': colour, 'fill': fill, 'fillOpacity': 0.7, 'weight': 4}
    layer = m.generic_layer(name='circleMarker', args=[[node['lat'], node['lon']], options])
    layer.run_method('bindTooltip', text)
    return layer


def _geojson(layer: dict[str, Any]) -> str:
    """The drawn polygon as GeoJSON text, from the latlngs Leaflet.draw sends."""
    ring = layer['_latlngs'][0]
    coords = [[p['lng'], p['lat']] for p in ring]
    coords.append(coords[0])
    return json.dumps({'type': 'Feature', 'properties': {}, 'geometry': {'type': 'Polygon', 'coordinates': [coords]}})


def _draw(state: State, m: Any, summary_nodes: list[dict[str, Any]]) -> None:
    for layer in state.layers:
        m.remove_layer(layer)
    state.layers = []
    v = state.values
    state.layers.append(m.marker(latlng=(v['lat'], v['lon'])))
    picked = {(n['lat'], n['lon']) for n in state.chosen}
    for node in state.offered:
        colour = COLOURS['chosen'] if (node['lat'], node['lon']) in picked else COLOURS['offered']
        text = f'{node["distance_km"]:.1f} km, orog {node["orog"]:.0f} m, land {node["sftlf"]:.0f}%'
        state.layers.append(_circle(m, node, 9, colour, True, text))
    for node in summary_nodes:
        state.layers.append(_circle(m, node, 15, COLOURS['used'], False, f'used: {node["distance_km"]:.1f} km'))


class Page:
    """One browser tab: form on the left, map and run on the right."""

    def __init__(self) -> None:
        """Build the widgets and draw the first map."""
        self.state = State()
        self.v = self.state.values
        self.fields: dict[str, Any] = {}
        self.used: list[dict[str, Any]] = []
        ui.page_title('BARRA2 download (NiceGUI spike)')
        with ui.row().classes('w-full no-wrap'):
            with ui.column().classes('w-64'):
                self._form()
            with ui.column().classes('grow'):
                self._map_and_run()
        ui.timer(0.3, self.tick)
        self.refresh()

    # region widgets
    def _form(self) -> None:
        ui.label('Site').classes('text-h6')
        self.field_input('name', 'Site name')
        self.number('lat', 'Latitude')
        self.number('lon', 'Longitude')
        self.field_input('start', 'Start').props('type=date')
        self.field_input('end', 'End').props('type=date')
        self.select('domain', 'Domain', DOMAINS).on_value_change(self.on_domain)
        self.select('freq', 'Frequency', freqs(self.v['domain']))
        self.select('preset', 'Preset', PRESETS)
        self.select('node_selection', 'Node selection', SELECTIONS)
        self.select('format', 'Output', FORMATS)
        ui.button('Find nodes', on_click=self.find)

    def _map_and_run(self) -> None:
        draw = {'polygon': True, 'polyline': False, 'rectangle': False, 'circle': False, 'marker': False}
        draw['circlemarker'] = False
        self.m = ui.leaflet(
            center=(self.v['lat'], self.v['lon']),
            zoom=11,
            draw_control={'draw': draw, 'edit': {'edit': True, 'remove': True}},
        ).classes('w-full h-96')
        self.m.on('map-click', self.on_click)
        self.m.on('draw:created', self.on_created)
        self.m.on('draw:deleted', self.on_deleted)
        ui.label('Click a blue node on the map to choose it. Draw a polygon with the toolbar.').classes('text-caption')
        self.plan = ui.label()
        with ui.row():
            self.run_button = ui.button('Run', on_click=self.start).props('color=primary')
            self.cancel_button = ui.button('Cancel', on_click=lambda: self.state.cancel.set())
            self.cancel_button.set_visibility(False)
        self.progress_bar = ui.linear_progress(value=0, show_value=False).classes('w-full')
        self.progress_bar.set_visibility(False)
        self.progress_label = ui.label()
        self.result_box = ui.column().classes('w-full')

    def field_input(self, key: str, label: str) -> Any:
        """A text input bound to a form value."""
        element = ui.input(label, value=str(self.v[key]), on_change=lambda e, k=key: self.changed(k, e.value))
        self.fields[key] = element
        return element

    def number(self, key: str, label: str) -> None:
        """A number input bound to a form value."""
        self.fields[key] = ui.number(
            label,
            value=self.v[key],
            format='%.4f',
            step=0.01,
            on_change=lambda e, k=key: self.changed(k, float(e.value or 0)),
        )

    def select(self, key: str, label: str, options: list[str]) -> Any:
        """A select bound to a form value."""
        element = ui.select(
            options, label=label, value=self.v[key], on_change=lambda e, k=key: self.changed(k, e.value)
        )
        self.fields[key] = element
        return element

    # endregion

    # region state to screen
    def changed(self, key: str, value: Any) -> None:
        """A form value changed."""
        self.v[key] = value
        self.refresh()

    def values_for_build(self) -> dict[str, Any]:
        """The form values with the date strings read as dates (a half-typed date reads as year 1900)."""
        out = dict(self.v)
        for key in ('start', 'end'):
            try:
                out[key] = date.fromisoformat(str(self.v[key]))
            except ValueError:
                out[key] = date(1900, 1, 1)
        return out

    def refresh(self) -> None:
        """Validate the form, mark the fields at fault, update the plan, the run button and the map."""
        for element in self.fields.values():
            element.props(remove='error')
        settings, site, problems = build(self.values_for_build(), self.state.chosen, self.state.polygon)
        for key, message in problems:
            if key in self.fields:
                self.fields[key].props(f'error error-message="{message}"')
        self.run_button.set_enabled(bool(not problems and not self.state.running))
        self.plan.set_text('' if problems else plan_text(site, settings))
        _draw(self.state, self.m, self.used)

    def tick(self) -> None:
        """Update the progress bar from the numbers the worker thread wrote."""
        if self.state.running:
            self.progress_bar.set_value(self.state.done / self.state.total if self.state.total else 0)
            self.progress_label.set_text(f'file {self.state.done} of {self.state.total}: {self.state.last}')

    # endregion

    # region events
    def on_domain(self, e: Any) -> None:
        """The frequencies depend on the domain."""
        options = freqs(e.value)
        freq = self.fields['freq']
        freq.set_options(options, value=self.v['freq'] if self.v['freq'] in options else options[0])
        self.v['freq'] = freq.value
        self.refresh()

    def find(self) -> None:
        """Look up the nodes around the site."""
        try:
            self.state.offered = find_nodes(self.v['lat'], self.v['lon'], self.v['domain'])
            self.state.chosen = []
        except Exception as error:  # the library raises NodeLookupError and the like
            ui.notify(str(error), type='negative')
        self.refresh()

    def on_click(self, e: Any) -> None:
        """Choose or drop the offered node near the click."""
        lat, lng = e.args['latlng']['lat'], e.args['latlng']['lng']
        for node in self.state.offered:
            if abs(node['lat'] - lat) < 0.015 and abs(node['lon'] - lng) < 0.015:
                key = (node['lat'], node['lon'])
                if any((c['lat'], c['lon']) == key for c in self.state.chosen):
                    self.state.chosen = [c for c in self.state.chosen if (c['lat'], c['lon']) != key]
                else:
                    self.state.chosen.append(node)
                self.refresh()
                return

    def on_created(self, e: Any) -> None:
        """A polygon was drawn."""
        if e.args.get('layerType') == 'polygon':
            self.state.polygon = _geojson(e.args['layer'])
            self.refresh()

    def on_deleted(self, _e: Any) -> None:
        """The drawn polygon was deleted."""
        self.state.polygon = None
        self.refresh()

    async def start(self) -> None:
        """Run the site on a worker thread and show the summary."""
        state = self.state
        self.used = []
        state.cancel = threading.Event()
        state.done = state.total = 0
        state.running = True
        self.result_box.clear()
        settings, site, _problems = build(self.values_for_build(), state.chosen, state.polygon)
        self.run_button.set_enabled(False)
        self.cancel_button.set_visibility(True)
        self.progress_bar.set_visibility(True)

        def progress(done: int, total: int, result: Any) -> None:
            state.done, state.total, state.last = done, total, f'{result.filename}: {result.status}'

        outcome = await run.io_bound(run_site, site, settings, progress, state.cancel)
        state.running = False
        self.cancel_button.set_visibility(False)
        self.progress_bar.set_visibility(False)
        data = summary(outcome)
        self.used = data['nodes']
        self.show(data)
        self.refresh()

    def show(self, data: dict[str, Any]) -> None:
        """The run summary."""
        with self.result_box:
            ui.label(f'Result: {data["status"]}').classes('text-h6')
            if data['error']:
                ui.label(data['error']).classes('text-negative')
            if data['missing']:
                ui.label('missing: ' + ', '.join(data['missing'])).classes('text-warning')
            ui.label('Outputs: ' + ', '.join(data['outputs']))
            ui.table(
                columns=[{'name': k, 'label': k, 'field': k} for k in ('name', 'status', 'status_code', 'attempts')],
                rows=data['files'],
            )
            if data['nodes']:
                keys = [k for k in data['nodes'][0] if k in ('lat', 'lon', 'distance_km', 'orog', 'weight', 'overlap')]
                ui.table(columns=[{'name': k, 'label': k, 'field': k} for k in keys], rows=data['nodes'])

    # endregion


@ui.page('/')
def index() -> None:
    """The one page."""
    Page()


if __name__ in {'__main__', '__mp_main__'}:
    main()
