# %% [markdown]
# # Spike 6: a notebook as the interface (ipywidgets + ipyleaflet, no Voila)
#
# A jupytext "percent" script: open it in JupyterLab as a notebook (right-click, Open With, Notebook) or convert it with
# `jupytext --to ipynb spikes/notebook/app.py`. Run all cells; the last cell shows the form, map and run controls.
#
# Throwaway code, never merged. The fake NCSS server (spikes/common) supplies the data, so no network is needed
# except for the map tiles.

# %%
import json
import threading
from datetime import date
from typing import Any

import ipywidgets as w
import pandas as pd
from ipyleaflet import CircleMarker, GeomanDrawControl, Map, Marker
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

# %% [markdown]
# ## State and widgets

# %%
state: dict[str, Any] = {'offered': [], 'chosen': [], 'used': [], 'polygon': None, 'layers': [], 'cancel': None}

fields: dict[str, w.Widget] = {
    'name': w.Text(value=DEFAULTS['name'], description='Site name'),
    'lat': w.BoundedFloatText(value=DEFAULTS['lat'], min=-90, max=90, step=0.01, description='Latitude'),
    'lon': w.BoundedFloatText(value=DEFAULTS['lon'], min=-180, max=180, step=0.01, description='Longitude'),
    'start': w.DatePicker(value=DEFAULTS['start'], description='Start'),
    'end': w.DatePicker(value=DEFAULTS['end'], description='End'),
    'domain': w.Dropdown(options=DOMAINS, value=DEFAULTS['domain'], description='Domain'),
    'freq': w.Dropdown(options=freqs(DEFAULTS['domain']), value=DEFAULTS['freq'], description='Frequency'),
    'preset': w.Dropdown(options=PRESETS, value=DEFAULTS['preset'], description='Preset'),
    'node_selection': w.Dropdown(options=SELECTIONS, value=DEFAULTS['node_selection'], description='Nodes'),
    'format': w.Dropdown(options=FORMATS, value=DEFAULTS['format'], description='Output'),
}
find_button = w.Button(description='Find nodes', icon='search')
run_button = w.Button(description='Run', button_style='primary', icon='play')
cancel_button = w.Button(description='Cancel', button_style='warning', icon='stop', layout=w.Layout(display='none'))
plan_label = w.Label()
problems_box = w.HTML()
node_info = w.HTML('Click a blue node on the map to choose it; draw a polygon with the toolbar.')
progress = w.IntProgress(min=0, max=1, layout=w.Layout(width='100%', display='none'))
progress_label = w.Label()
result_box = w.HTML()

fmap = Map(center=(DEFAULTS['lat'], DEFAULTS['lon']), zoom=11, scroll_wheel_zoom=True, layout=w.Layout(height='480px'))
draw = GeomanDrawControl(
    polygon={'pathOptions': {'color': '#a855f7'}},  # an empty dict would switch the tool off
    polyline={},
    rectangle={},
    circle={},
    marker={},
    circlemarker={},
    edit=True,
    remove=True,
    drag=True,
)
fmap += draw

# %% [markdown]
# ## Behaviour: form values to Settings/Site, the map layers, the run


# %%
def values() -> dict[str, Any]:
    """The form values; a cleared date reads as year 1900 so validation reports it."""
    out = {key: widget.value for key, widget in fields.items()}
    for key in ('start', 'end'):
        out[key] = out[key] or date(1900, 1, 1)
    return out


def redraw() -> None:
    """Redraw the site, the offered/chosen nodes and the nodes used by the last run (the polygon is the control's)."""
    for layer in state['layers']:
        fmap.remove(layer)
    state['layers'] = [Marker(location=(fields['lat'].value, fields['lon'].value), draggable=False, title='site')]
    picked = {(n['lat'], n['lon']) for n in state['chosen']}
    for node in state['offered']:
        colour = COLOURS['chosen'] if (node['lat'], node['lon']) in picked else COLOURS['offered']
        marker = CircleMarker(
            location=(node['lat'], node['lon']), radius=9, color=colour, fill_color=colour, fill_opacity=0.7
        )
        marker.on_click(lambda *_a, node=node, **_k: toggle(node))
        state['layers'].append(marker)
    for node in state['used']:
        state['layers'].append(
            CircleMarker(location=(node['lat'], node['lon']), radius=15, color=COLOURS['used'], fill=False, weight=4)
        )
    for layer in state['layers']:
        fmap.add(layer)


def refresh(*_args: Any) -> None:
    """Validate the form, mark the fields at fault, update the plan and the buttons, redraw the map."""
    for widget in fields.values():
        widget.layout.border = ''
    try:
        settings, site, problems = build(values(), state['chosen'], state['polygon'])
    except ValueError as error:  # a latitude or longitude the library rejects
        settings = site = None
        problems = [('lat', str(error))]
    for key, _message in problems:
        if key in fields:
            fields[key].layout.border = '2px solid #dc2626'
    problems_box.value = ''.join(f'<div style="color:#dc2626">{key}: {message}</div>' for key, message in problems)
    plan_label.value = '' if problems else plan_text(site, settings)
    running = state['cancel'] is not None
    run_button.disabled = bool(problems) or running
    redraw()


def on_domain(change: dict[str, Any]) -> None:
    """The frequencies depend on the domain."""
    options = freqs(change['new'])
    freq = fields['freq']
    freq.options = options
    freq.value = freq.value if freq.value in options else options[0]


def find(_button: Any) -> None:
    """Look up the nodes around the site."""
    try:
        state['offered'] = find_nodes(fields['lat'].value, fields['lon'].value, fields['domain'].value)
        state['chosen'] = []
        node_info.value = f'{len(state["offered"])} nodes offered. Click one to choose it.'
    except Exception as error:  # the library raises NodeLookupError and the like
        node_info.value = f'<span style="color:#dc2626">{error}</span>'
    refresh()


def toggle(node: dict[str, Any]) -> None:
    """Choose or drop an offered node, and show its details."""
    key = (node['lat'], node['lon'])
    if any((c['lat'], c['lon']) == key for c in state['chosen']):
        state['chosen'] = [c for c in state['chosen'] if (c['lat'], c['lon']) != key]
    else:
        state['chosen'] = [*state['chosen'], node]
    node_info.value = (
        f'{node["lat"]:.3f}, {node["lon"]:.3f}: {node["distance_km"]:.1f} km, orog {node["orog"]:.0f} m, '
        f'land {node["sftlf"]:.0f}%. {len(state["chosen"])} chosen.'
    )
    refresh()


def on_draw(change: dict[str, Any]) -> None:
    """The drawn features changed (created, edited or removed): keep the last polygon."""
    polygons = [f for f in change['new'] if f.get('geometry', {}).get('type') == 'Polygon']
    if polygons:
        state['polygon'] = json.dumps(polygons[-1])
        vertices = len(polygons[-1]['geometry']['coordinates'][0]) - 1
        node_info.value = f'Polygon set ({vertices} vertices); it replaces the point.'
    else:
        state['polygon'] = None
        node_info.value = 'No polygon; the site is the point.'
    refresh()


def start(_button: Any) -> None:
    """Run the site on a worker thread; the thread updates the widgets itself."""
    settings, site, _problems = build(values(), state['chosen'], state['polygon'])
    cancel = state['cancel'] = threading.Event()
    state['used'] = []
    result_box.value = ''
    progress.value, progress.max = 0, 1
    progress.layout.display = cancel_button.layout.display = ''
    run_button.disabled = True

    def on_progress(done: int, total: int, result: Any) -> None:
        progress.max, progress.value = max(total, 1), done
        progress_label.value = f'file {done} of {total}: {result.filename}: {result.status}'

    def work() -> None:
        data = summary(run_site(site, settings, on_progress, cancel))
        state['cancel'], state['used'] = None, data['nodes']
        progress.layout.display = cancel_button.layout.display = 'none'
        result_box.value = render(data)
        refresh()

    threading.Thread(target=work, daemon=True).start()


def render(data: dict[str, Any]) -> str:
    """The run summary as HTML."""
    parts = [f'<h3>Result: {data["status"]}</h3>']
    if data['error']:
        parts.append(f'<p style="color:#dc2626">{data["error"]}</p>')
    if data['missing']:
        parts.append('<p style="color:#d97706">missing: ' + ', '.join(data['missing']) + '</p>')
    parts.append('<p>Outputs: ' + ', '.join(data['outputs']) + '</p>')
    parts.append(pd.DataFrame(data['files'])[['name', 'status', 'status_code', 'attempts']].to_html(index=False))
    if data['nodes']:
        nodes = pd.DataFrame(data['nodes'])
        keys = [c for c in ('lat', 'lon', 'distance_km', 'orog', 'weight', 'overlap') if c in nodes]
        parts.append(nodes[keys].to_html(index=False))
    return ''.join(parts)


for widget in fields.values():
    widget.observe(refresh, names='value')
fields['domain'].observe(on_domain, names='value')
find_button.on_click(find)
run_button.on_click(start)
cancel_button.on_click(lambda _b: state['cancel'] and state['cancel'].set())
draw.observe(on_draw, names='data')

# %% [markdown]
# ## The app

# %%
form = w.VBox([*fields.values(), find_button], layout=w.Layout(width='320px'))
right = w.VBox(
    [
        fmap,
        node_info,
        plan_label,
        problems_box,
        w.HBox([run_button, cancel_button]),
        progress,
        progress_label,
        result_box,
    ],
    layout=w.Layout(flex='1'),
)
refresh()
w.HBox([form, right])
