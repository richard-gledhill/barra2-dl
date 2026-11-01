# %% [markdown]
# # Spike 6: a notebook as the interface (ipywidgets + ipyleaflet, no Voila)
#
# A jupytext "percent" script: open it in JupyterLab as a notebook (right-click, Open With, Notebook) or convert it with
# `jupytext --to ipynb spikes/notebook/app.py`. Run all cells; the last cell shows the form, map and run controls.
#
# The project has one set of settings (dates, domain, preset, output) and any number of sites, for example two masts.
# Drag a marker to move its site, click a marker to work on it, draw a polygon to make the active site an area.
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
from ipyleaflet import AwesomeIcon, CircleMarker, GeoJSON, GeomanDrawControl, Map, Marker
from spike_common import (
    COLOURS,
    DEFAULTS,
    DOMAINS,
    FORMATS,
    PRESETS,
    SELECTIONS,
    build,
    find_nodes,
    find_polygon_nodes,
    freqs,
    plan_text,
    summary,
)

from barra2_dl.project import run_site

# %% [markdown]
# ## State and widgets

# %%
# one dict per site; `used` comes from the last run
sites: list[dict[str, Any]] = []
state: dict[str, Any] = {'active': 0, 'cancel': None, 'node_layers': [], 'markers': [], 'polygon_layers': []}


def new_site(name: str, lat: float, lon: float) -> dict[str, Any]:
    """A site with nothing chosen yet."""
    return {'name': name, 'lat': lat, 'lon': lon, 'offered': [], 'chosen': [], 'polygon': None, 'used': []}


sites.append(new_site('mast-1', DEFAULTS['lat'], DEFAULTS['lon']))

site_select = w.Dropdown(options=[(sites[0]['name'], 0)], value=0, description='Site')
add_button = w.Button(description='Add site', icon='plus')
remove_button = w.Button(description='Remove site', icon='trash')
clear_polygon_button = w.Button(description='Clear polygon', icon='eraser')
site_fields: dict[str, w.Widget] = {
    'name': w.Text(value='mast-1', description='Name'),
    'lat': w.BoundedFloatText(value=DEFAULTS['lat'], min=-90, max=90, step=0.01, description='Latitude'),
    'lon': w.BoundedFloatText(value=DEFAULTS['lon'], min=-180, max=180, step=0.01, description='Longitude'),
}
shared_fields: dict[str, w.Widget] = {
    'start': w.DatePicker(value=DEFAULTS['start'], description='Start'),
    'end': w.DatePicker(value=DEFAULTS['end'], description='End'),
    'domain': w.Dropdown(options=DOMAINS, value=DEFAULTS['domain'], description='Domain'),
    'freq': w.Dropdown(options=freqs(DEFAULTS['domain']), value=DEFAULTS['freq'], description='Frequency'),
    'preset': w.Dropdown(options=PRESETS, value=DEFAULTS['preset'], description='Preset'),
    'node_selection': w.Dropdown(options=SELECTIONS, value=DEFAULTS['node_selection'], description='Nodes'),
    'format': w.Dropdown(options=FORMATS, value=DEFAULTS['format'], description='Output'),
}
fields = site_fields | shared_fields
find_button = w.Button(description='Find nodes', icon='search')
run_button = w.Button(description='Run all sites', button_style='primary', icon='play')
cancel_button = w.Button(description='Cancel', button_style='warning', icon='stop', layout=w.Layout(display='none'))
plan_label = w.Label()
problems_box = w.HTML()
node_info = w.HTML('Drag a marker to move a site. Click a blue node to choose it; draw a polygon for an area.')
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
    edit=False,
    remove=False,
    drag=False,
    cut=False,
    rotate=False,
)
fmap += draw

# %% [markdown]
# ## Behaviour: sites, the map layers, the run

# %%
loading = {'on': False}  # True while the widgets are being set from a site, so their observers stay quiet


def active() -> dict[str, Any]:
    """The site being worked on."""
    return sites[state['active']]


def values_for(site: dict[str, Any]) -> dict[str, Any]:
    """The shared settings plus one site's name and place; a cleared date reads as year 1900 to be reported."""
    out = {key: widget.value for key, widget in shared_fields.items()}
    for key in ('start', 'end'):
        out[key] = out[key] or date(1900, 1, 1)
    return out | {'name': site['name'], 'lat': site['lat'], 'lon': site['lon']}


def site_icon(is_active: bool) -> AwesomeIcon:
    """Black for the active site, grey for the others."""
    return AwesomeIcon(name='crosshairs', marker_color='black' if is_active else 'lightgray', icon_color='white')


def draw_sites() -> None:
    """One draggable marker and, if it has one, one polygon layer per site."""
    for layer in [*state['markers'], *state['polygon_layers']]:
        fmap.remove(layer)
    state['markers'], state['polygon_layers'] = [], []
    for index, site in enumerate(sites):
        marker = Marker(
            location=(site['lat'], site['lon']),
            draggable=True,
            title=site['name'],
            icon=site_icon(index == state['active']),
        )
        marker.on_click(lambda *_a, index=index, **_k: select(index))
        marker.observe(lambda change, index=index: moved(index, change['new']), names='location')
        state['markers'].append(marker)
        fmap.add(marker)
        if site['polygon']:
            style = {'color': '#a855f7' if index == state['active'] else '#9ca3af', 'fillOpacity': 0.2}
            layer = GeoJSON(data=json.loads(site['polygon']), style=style)
            state['polygon_layers'].append(layer)
            fmap.add(layer)


def draw_nodes() -> None:
    """The active site's offered, chosen and used nodes (the markers and polygons are drawn by draw_sites)."""
    for layer in state['node_layers']:
        fmap.remove(layer)
    state['node_layers'] = []
    site = active()
    picked = {(n['lat'], n['lon']) for n in site['chosen']}
    for node in site['offered']:
        colour = COLOURS['chosen'] if (node['lat'], node['lon']) in picked or site['polygon'] else COLOURS['offered']
        marker = CircleMarker(
            location=(node['lat'], node['lon']), radius=9, color=colour, fill_color=colour, fill_opacity=0.7
        )
        marker.on_click(lambda *_a, node=node, **_k: toggle(node))
        state['node_layers'].append(marker)
    for node in site['used']:
        ring = CircleMarker(location=(node['lat'], node['lon']), radius=15, color=COLOURS['used'], fill=False, weight=4)
        state['node_layers'].append(ring)
    for layer in state['node_layers']:
        fmap.add(layer)


def load_site() -> None:
    """Show the active site in the name, latitude and longitude boxes and in the site list."""
    loading['on'] = True
    site = active()
    for key in ('name', 'lat', 'lon'):
        site_fields[key].value = site[key]
    site_select.options = [(f'{s["name"]}{" (polygon)" if s["polygon"] else ""}', i) for i, s in enumerate(sites)]
    site_select.value = state['active']
    remove_button.disabled = len(sites) == 1
    clear_polygon_button.disabled = not site['polygon']
    loading['on'] = False


def refresh(*_args: Any) -> None:
    """Validate every site, mark the active site's fields at fault, update the plan and the buttons, redraw the map."""
    if loading['on']:
        return
    for widget in fields.values():
        widget.layout.border = ''
    lines, plans = [], []
    for index, each in enumerate(sites):
        try:
            settings, site_obj, problems = build(values_for(each), each['chosen'], each['polygon'])
        except ValueError as error:  # a latitude or longitude the library rejects
            settings = site_obj = None
            problems = [('lat', str(error))]
        lines += [f'<div style="color:#dc2626">{each["name"]}: {key}: {message}</div>' for key, message in problems]
        if index == state['active']:
            for key, _message in problems:
                if key in fields:
                    fields[key].layout.border = '2px solid #dc2626'
        if not problems:
            plans.append(f'{each["name"]}: {plan_text(site_obj, settings)}')
    names = [each['name'] for each in sites]
    if len(set(names)) != len(names):
        lines.append('<div style="color:#dc2626">site names must be different</div>')
    problems_box.value = ''.join(lines)
    plan_label.value = '' if lines else '; '.join(plans)
    run_button.disabled = bool(lines) or state['cancel'] is not None
    load_site()
    draw_sites()
    draw_nodes()


def select(index: int) -> None:
    """Make another site the one being worked on."""
    state['active'] = index
    refresh()


def moved(index: int, location: tuple[float, float]) -> None:
    """A marker was dragged: move its site, and forget its nodes because they were for the old place."""
    site = sites[index]
    lat, lon = round(location[0], 4), round(location[1], 4)
    if (site['lat'], site['lon']) == (lat, lon):
        return
    site.update(lat=lat, lon=lon, offered=[], chosen=[], used=[])
    state['active'] = index
    node_info.value = f'{site["name"]} moved to {lat:.4f}, {lon:.4f}. Find nodes again to see its nodes.'
    refresh()


def on_domain(change: dict[str, Any]) -> None:
    """The frequencies depend on the domain; the nodes depend on it too."""
    options = freqs(change['new'])
    freq = shared_fields['freq']
    freq.options = options
    freq.value = freq.value if freq.value in options else options[0]
    for each in sites:
        each.update(offered=[], chosen=[], used=[])


def on_site_edit(_change: dict[str, Any]) -> None:
    """The name, latitude or longitude box was edited: the site takes it, the marker follows, and moved nodes go."""
    if loading['on']:
        return
    site = active()
    place = (site_fields['lat'].value, site_fields['lon'].value)
    if place != (site['lat'], site['lon']):
        site.update(offered=[], chosen=[], used=[])
    site.update(name=site_fields['name'].value, lat=place[0], lon=place[1])
    refresh()


def find(_button: Any) -> None:
    """Look up the nodes the active site would use: the nearest nine for a point, the nodes a polygon overlaps."""
    site = active()
    domain = shared_fields['domain'].value
    try:
        if site['polygon']:
            site['offered'] = find_polygon_nodes(site['polygon'], domain)
            node_info.value = f'{len(site["offered"])} nodes overlap the polygon (click one for its share).'
        else:
            site['offered'] = find_nodes(site['lat'], site['lon'], domain)
            node_info.value = f'{len(site["offered"])} nodes offered. Click one to choose it.'
        site['chosen'] = []
    except Exception as error:  # the library raises NodeLookupError and the like
        node_info.value = f'<span style="color:#dc2626">{error}</span>'
    refresh()


def toggle(node: dict[str, Any]) -> None:
    """Show a node's details; for a point site also choose or drop it."""
    site = active()
    text = f'{node["lat"]:.3f}, {node["lon"]:.3f}: {node["distance_km"]:.1f} km, orog {node["orog"]:.0f} m, '
    text += f'land {node["sftlf"]:.0f}%'
    if site['polygon']:
        node_info.value = text + f', {node["overlap"]:.0%} of its cell inside the polygon. A polygon uses all of these.'
        return
    key = (node['lat'], node['lon'])
    if any((c['lat'], c['lon']) == key for c in site['chosen']):
        site['chosen'] = [c for c in site['chosen'] if (c['lat'], c['lon']) != key]
    else:
        site['chosen'] = [*site['chosen'], node]
    node_info.value = f'{text}. {len(site["chosen"])} chosen.'
    refresh()


def on_draw(change: dict[str, Any]) -> None:
    """A polygon was drawn: it becomes the active site's area, and the drawn shape is replaced by the site's layer."""
    polygons = [f for f in change['new'] if f.get('geometry', {}).get('type') == 'Polygon']
    if not polygons:
        return
    site = active()
    site.update(polygon=json.dumps(polygons[-1]), offered=[], chosen=[], used=[])
    vertices = len(polygons[-1]['geometry']['coordinates'][0]) - 1
    node_info.value = (
        f'{site["name"]}: polygon set ({vertices} vertices); it replaces the point. Find nodes to preview.'
    )
    draw.clear()
    refresh()


def clear_polygon(_button: Any) -> None:
    """Make the active site a point again."""
    active().update(polygon=None, offered=[], chosen=[], used=[])
    node_info.value = f'{active()["name"]} is a point again.'
    refresh()


def add_site(_button: Any) -> None:
    """Add a site just north of the active one, and work on it."""
    site = active()
    number = len(sites) + 1
    sites.append(new_site(f'mast-{number}', round(site['lat'] + 0.06, 4), site['lon']))
    state['active'] = len(sites) - 1
    node_info.value = f'Added mast-{number}. Drag its marker to where it belongs.'
    refresh()


def remove_site(_button: Any) -> None:
    """Remove the active site."""
    sites.pop(state['active'])
    state['active'] = max(0, state['active'] - 1)
    refresh()


def start(_button: Any) -> None:
    """Run the sites one after another on a worker thread; the thread updates the widgets itself."""
    jobs = [build(values_for(each), each['chosen'], each['polygon']) for each in sites]
    cancel = state['cancel'] = threading.Event()
    for each in sites:
        each['used'] = []
    result_box.value = ''
    progress.value, progress.max = 0, 1
    progress.layout.display = cancel_button.layout.display = ''
    run_button.disabled = True

    def work() -> None:
        parts = []
        for index, (settings, site_obj, _problems) in enumerate(jobs):
            if cancel.is_set():
                break

            def on_progress(done: int, total: int, result: Any, index: int = index) -> None:
                progress.max, progress.value = max(total, 1), done
                progress_label.value = (
                    f'{sites[index]["name"]} (site {index + 1} of {len(jobs)}): file {done} of {total}: '
                    f'{result.filename}: {result.status}'
                )

            data = summary(run_site(site_obj, settings, on_progress, cancel))
            sites[index]['used'] = data['nodes']
            parts.append(render(sites[index]['name'], data))
            result_box.value = ''.join(parts)
        state['cancel'] = None
        progress.layout.display = cancel_button.layout.display = 'none'
        refresh()

    threading.Thread(target=work, daemon=True).start()


def render(name: str, data: dict[str, Any]) -> str:
    """One site's run summary as HTML."""
    parts = [f'<h3>{name}: {data["status"]}</h3>']
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


for widget in shared_fields.values():
    widget.observe(refresh, names='value')
shared_fields['domain'].observe(on_domain, names='value')
for widget in site_fields.values():
    widget.observe(on_site_edit, names='value')
site_select.observe(lambda change: None if loading['on'] else select(change['new']), names='value')
find_button.on_click(find)
run_button.on_click(start)
cancel_button.on_click(lambda _b: state['cancel'] and state['cancel'].set())
add_button.on_click(add_site)
remove_button.on_click(remove_site)
clear_polygon_button.on_click(clear_polygon)
draw.observe(on_draw, names='data')

# %% [markdown]
# ## The app

# %%
form = w.VBox(
    [
        w.HBox([site_select, add_button], layout=w.Layout(width='440px')),
        *site_fields.values(),
        w.HBox([find_button, clear_polygon_button, remove_button]),
        *shared_fields.values(),
    ],
    layout=w.Layout(width='440px'),
)
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
