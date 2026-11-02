# %% [markdown]
# # Spike 6: a notebook as the interface (ipywidgets + ipyleaflet, no Voila)
#
# A jupytext "percent" script: open it in JupyterLab as a notebook (right-click, Open With, Notebook) or convert it with
# `jupytext --to ipynb spikes/notebook/app.py`. Run all cells; the last cell shows the form, map and run controls.
#
# The project has one set of settings (dates, domain, preset, output) and any number of sites: masts (a point) and at
# most one area (a drawn polygon). Pick a site in the Site list or click it on the map. Drag a mast to move it. Draw a
# polygon to add the area; the map's edit tool reshapes it and its remove tool deletes it. Import a project.toml or a
# polygon file from the Import section.
#
# Throwaway code, never merged. The fake NCSS server (spikes/common) supplies the data, so no network is needed
# except for the map tiles.

# %%
import json
import math
import re
import tempfile
import threading
import tomllib
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import ipywidgets as w
import pandas as pd
from ipyleaflet import AwesomeIcon, CircleMarker, DivIcon, GeomanDrawControl, Map, Marker
from spike_common import (
    COLOURS,
    DEFAULTS,
    DOMAINS,
    FORMATS,
    PRESETS,
    SCRATCH,
    SELECTIONS,
    build,
    find_nodes,
    find_polygon_nodes,
    freqs,
    plan_text,
    planned_nodes,
    summary,
)

from barra2_dl import globals as barra2_globals
from barra2_dl.download import preset_variables
from barra2_dl.mapping import Polygon, polygon_from_geojson, polygon_from_kml
from barra2_dl.project import Project, load_project, project_from_dict, run_site

# %% [markdown]
# ## State and widgets

# %%
# one dict per site; `used` comes from the last run; an area is the site with a polygon (at most one)
sites: list[dict[str, Any]] = []
state: dict[str, Any] = {'active': 0, 'cancel': None, 'node_layers': [], 'markers': [], 'results': {}}
DRAW_POLYGON = {'pathOptions': {'color': '#a855f7'}}  # an empty dict would switch the tool off
AREA_COLOURS = {True: '#a855f7', False: '#9ca3af'}  # the active area is purple, an idle one grey, as the masts are
PLANNED = '#7c3aed'  # the ring round a node a run would download
NO_NODE = {'distance_km': math.nan, 'orog': math.nan, 'sftlf': math.nan}


def new_site(name: str, lat: float, lon: float, polygon: str | None = None) -> dict[str, Any]:
    """A mast (a point), or the area when it has a polygon; nothing is offered or chosen yet."""
    return {
        'name': name,
        'lat': lat,
        'lon': lon,
        'offered': [],
        'chosen': [],
        'polygon': polygon,
        'used': [],
        'mean': False,
    }


def unique_name(prefix: str) -> str:
    """mast-1, mast-2, ... the first one no site has."""
    taken = {site['name'] for site in sites}
    return next(f'{prefix}-{n}' for n in range(1, len(taken) + 2) if f'{prefix}-{n}' not in taken)


def centre(feature: dict[str, Any]) -> tuple[float, float]:
    """The middle of a polygon feature's vertices as (lat, lon), which stands in for the area's place."""
    ring = feature['geometry']['coordinates'][0][:-1]
    return round(sum(p[1] for p in ring) / len(ring), 4), round(sum(p[0] for p in ring) / len(ring), 4)


def feature_of(polygon: Polygon) -> dict[str, Any]:
    """A mapping.Polygon as a GeoJSON feature: the engine keeps (lat, lon), GeoJSON wants [lon, lat] closed rings."""
    rings = [[[lon, lat] for lat, lon in ring] for ring in (polygon.exterior, *polygon.holes)]
    return {
        'type': 'Feature',
        'properties': {},
        'geometry': {'type': 'Polygon', 'coordinates': [[*ring, ring[0]] for ring in rings]},
    }


def same_shape(first: dict[str, Any], second: dict[str, Any]) -> bool:
    """Whether two polygon features have the same outline, to 5 decimals (Leaflet rounds what it sends back)."""

    def rounded(feature: dict[str, Any]) -> list[Any]:
        return [[[round(c, 5) for c in point] for point in ring] for ring in feature['geometry']['coordinates']]

    return rounded(first) == rounded(second)


sites.append(new_site('mast-1', DEFAULTS['lat'], DEFAULTS['lon']))

site_select = w.Dropdown(options=[(sites[0]['name'], 0)], value=0, description='Site')
add_button = w.Button(description='Add mast', icon='plus')
remove_button = w.Button(description='Remove site', icon='trash')
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
    'node_selection': w.Dropdown(options=SELECTIONS, value=DEFAULTS['node_selection'], description='Mast nodes'),
    'format': w.Dropdown(options=FORMATS, value=DEFAULTS['format'], description='Output'),
    'cache': w.Text(value=str(SCRATCH / 'cache'), description='Cache folder'),
    'out': w.Text(value=str(SCRATCH / 'out'), description='Output folder'),
}
fields = site_fields | shared_fields
mean_box = w.Checkbox(description='Also write the weighted mean of the nodes', indent=False)
selection_note = w.HTML(layout=w.Layout(margin='0 0 6px 6px'))
preset_note = w.HTML(layout=w.Layout(margin='0 0 6px 6px'))
find_button = w.Button(description='Find nodes', icon='search')
run_button = w.Button(description='Run all sites', button_style='primary', icon='play')
run_selected_button = w.Button(description='Run selected site', icon='play')
cancel_button = w.Button(description='Cancel', button_style='warning', icon='stop', layout=w.Layout(display='none'))
plan_label = w.Label()
problems_box = w.HTML()
node_info = w.HTML('Drag a mast to move it. Click a blue node to choose it. Draw a polygon to add the area.')
progress = w.IntProgress(min=0, max=1, layout=w.Layout(width='100%', display='none'))
progress_label = w.Label()
result_box = w.HTML()

import_path = w.Text(placeholder='path to a project.toml, .geojson, .json or .kml', layout=w.Layout(width='300px'))
import_button = w.Button(description='Import path', icon='folder-open')
import_upload = w.FileUpload(accept='.toml,.geojson,.json,.kml', multiple=True, description='Upload file(s)')
import_info = w.HTML()
import_box = w.Accordion(
    children=[
        w.VBox(
            [
                w.HTML(
                    'A <b>project.toml</b> replaces the settings and all sites. A <b>.geojson</b>, <b>.json</b> or '
                    '<b>.kml</b> polygon becomes the area. A path resolves a polygon file named in a project '
                    'relative to the project. An upload takes the polygon file too: select it with the '
                    'project.toml (Ctrl-click).'
                ),
                w.HBox([import_path, import_button]),
                import_upload,
                import_info,
            ]
        )
    ],
    titles=('Import a project or polygon file',),
    selected_index=None,
)

fmap = Map(center=(DEFAULTS['lat'], DEFAULTS['lon']), zoom=11, scroll_wheel_zoom=True, layout=w.Layout(height='480px'))
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
fmap += draw

# %% [markdown]
# ## Behaviour: sites, the map layers, the run

# %%
loading = {'on': False}  # True while the widgets are being set from a site, so their observers stay quiet


def active() -> dict[str, Any]:
    """The site being worked on."""
    return sites[state['active']]


def area_index() -> int | None:
    """Where the area is in the site list, or None."""
    return next((i for i, site in enumerate(sites) if site['polygon']), None)


def values_for(site: dict[str, Any]) -> dict[str, Any]:
    """The shared settings plus one site's name and place; a cleared date reads as year 1900 to be reported."""
    out = {key: widget.value for key, widget in shared_fields.items()}
    for key in ('start', 'end'):
        out[key] = out[key] or date(1900, 1, 1)
    return out | {'name': site['name'], 'lat': site['lat'], 'lon': site['lon'], 'node_mean': site['mean']}


def site_icon(is_active: bool) -> AwesomeIcon:
    """Black for the active site, grey for the others."""
    return AwesomeIcon(name='crosshairs', marker_color='black' if is_active else 'lightgray', icon_color='white')


def style_area() -> None:
    """Purple for the active area, grey otherwise: the draw control takes a feature's colour from its properties."""
    index = area_index()
    if index is None:
        return
    feature = json.loads(sites[index]['polygon'])
    colour = AREA_COLOURS[index == state['active']]
    style = feature.setdefault('properties', {}).get('style') or {}
    if style.get('color') == colour:
        return
    feature['properties']['style'] = {**style, 'color': colour, 'fillColor': colour}
    sites[index]['polygon'] = json.dumps(feature)
    draw.data = [feature]


def area_label(site: dict[str, Any], is_active: bool) -> Marker:
    """The area's name at its middle: shown on the map, and as a tooltip like a mast's."""
    colour = '#7c3aed' if is_active else '#6b7280'
    style = f'color:{colour}; font-weight:600; text-shadow:0 0 3px #fff; text-align:center'
    html = f'<div style="{style}">{site["name"]}</div>'
    icon = DivIcon(html=html, icon_size=(90, 20), icon_anchor=(45, 10))
    return Marker(location=(site['lat'], site['lon']), draggable=False, title=site['name'], icon=icon)


def draw_sites() -> None:
    """A draggable marker for each mast and a name label for the area; the area is the draw control's own layer."""
    for layer in state['markers']:
        fmap.remove(layer)
    state['markers'] = []
    for index, site in enumerate(sites):
        if site['polygon']:
            label = area_label(site, index == state['active'])
            label.on_click(lambda *_a, index=index, **_k: select(index))
            state['markers'].append(label)
            fmap.add(label)
            continue
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


def draw_nodes() -> None:
    """The active site's offered, chosen and used nodes (the markers are drawn by draw_sites)."""
    for layer in state['node_layers']:
        fmap.remove(layer)
    state['node_layers'] = []
    site = active()
    picked = {(n['lat'], n['lon']) for n in site['chosen']}
    for node in [*site['offered'], *(n for n in site['chosen'] if n not in site['offered'])]:
        colour = COLOURS['chosen'] if (node['lat'], node['lon']) in picked or site['polygon'] else COLOURS['offered']
        marker = CircleMarker(
            location=(node['lat'], node['lon']), radius=9, color=colour, fill_color=colour, fill_opacity=0.7
        )
        marker.on_click(lambda *_a, node=node, **_k: toggle(node))
        state['node_layers'].append(marker)
    selection = shared_fields['node_selection'].value
    for node in planned_nodes(
        site['lat'], site['lon'], site['offered'], site['chosen'], selection, bool(site['polygon'])
    ):
        ring = CircleMarker(location=(node['lat'], node['lon']), radius=14, color=PLANNED, fill=False, weight=3)
        state['node_layers'].append(ring)
    for node in site['used']:
        ring = CircleMarker(location=(node['lat'], node['lon']), radius=19, color=COLOURS['used'], fill=False, weight=4)
        state['node_layers'].append(ring)
    for layer in state['node_layers']:
        fmap.add(layer)


def describe_preset() -> str:
    """The chosen preset's variables from barra2_dl.globals (read each time), and whether the domain has them."""
    name, domain, freq = (shared_fields[key].value for key in ('preset', 'domain', 'freq'))
    variables = barra2_globals.BARRA2_PRESETS[name]
    fixed = ', '.join(barra2_globals.BARRA2_FIXED_VARS_AUTO)
    text = f'<i>{name}: {len(variables)} variables: {", ".join(variables)}. {fixed} is added to every download.</i>'
    try:
        preset_variables(name, domain, freq)
    except ValueError as error:  # the preset needs variables this domain and frequency do not have
        text += f'<br><span style="color:#dc2626">{error}</span>'
    return text


def describe_selection(site: dict[str, Any]) -> str:
    """What a run of the active site downloads, in words, since the node choice only applies to a mast."""
    if site['polygon']:
        found = f' ({len(site["offered"])} shown)' if site['offered'] else ''
        return (
            f'<i>Area: every node whose cell the polygon overlaps is downloaded{found}, not just the centre. '
            'The node choice does not apply. Violet rings mark them.</i>'
        )
    if site['chosen']:
        return f'<i>The {len(site["chosen"])} chosen node(s) are downloaded; the node choice does not apply.</i>'
    if shared_fields['node_selection'].value == 'nearest':
        return '<i>nearest: the one node nearest the mast is downloaded (violet ring after Find nodes).</i>'
    return (
        '<i>average4: the four nodes around the mast are downloaded and averaged with inverse-distance weights '
        '(violet rings after Find nodes).</i>'
    )


def load_site() -> None:
    """Show the active site in the name, latitude and longitude boxes (an area has no place boxes) and the list."""
    loading['on'] = True
    site = active()
    for key in ('name', 'lat', 'lon'):
        site_fields[key].value = site[key]
    for key in ('lat', 'lon'):
        site_fields[key].layout.display = 'none' if site['polygon'] else ''
    site_select.options = [(f'{s["name"]}{" (area)" if s["polygon"] else ""}', i) for i, s in enumerate(sites)]
    site_select.value = state['active']
    remove_button.disabled = len(sites) == 1 and not site['polygon']
    uses_nodes = bool(site['polygon'] or site['chosen'])
    mean_box.layout.display = '' if uses_nodes else 'none'
    mean_box.value = site['mean'] and uses_nodes
    shared_fields['node_selection'].disabled = uses_nodes
    selection_note.value = describe_selection(site)
    preset_note.value = describe_preset()
    loading['on'] = False


def show_results() -> None:
    """The latest result of each site that has one, in site order."""
    result_box.value = ''.join(state['results'][s['name']] for s in sites if s['name'] in state['results'])


def check_sites() -> tuple[list[str], list[str], set[int]]:
    """Validate every site: the problem lines to show, each valid site's plan, and which sites have problems."""
    lines, plans, bad = [], [], set()
    for index, each in enumerate(sites):
        try:
            settings, site_obj, problems = build(values_for(each), each['chosen'], each['polygon'])
        except ValueError as error:  # a latitude or longitude the library rejects
            settings = site_obj = None
            problems = [('lat', str(error))]
        lines += [f'<div style="color:#dc2626">{each["name"]}: {key}: {message}</div>' for key, message in problems]
        if problems:
            bad.add(index)
        if index == state['active']:
            for key, _message in problems:
                if key in fields:
                    fields[key].layout.border = '2px solid #dc2626'
        if not problems:
            plans.append(f'{each["name"]}: {plan_text(site_obj, settings)}')
    return lines, plans, bad


def refresh(*_args: Any) -> None:
    """Validate every site, mark the active site's fields at fault, update the plan and the buttons, redraw the map."""
    if loading['on']:
        return
    for widget in fields.values():
        widget.layout.border = ''
    lines, plans, bad = check_sites()
    names = [each['name'] for each in sites]
    duplicate = len(set(names)) != len(names)
    if duplicate:
        lines.append('<div style="color:#dc2626">site names must be different</div>')
    problems_box.value = ''.join(lines)
    plan_label.value = '; '.join(plans)
    busy = state['cancel'] is not None
    run_button.disabled = bool(bad) or duplicate or busy
    run_selected_button.disabled = state['active'] in bad or duplicate or busy
    # one area only: the draw tool goes while there is one (if the control ignores this, on_draw keeps the first)
    wanted = {} if area_index() is not None else DRAW_POLYGON
    if draw.polygon != wanted:
        draw.polygon = wanted
    style_area()
    load_site()
    draw_sites()
    draw_nodes()


def select(index: int) -> None:
    """Make another site the one being worked on."""
    state['active'] = index
    refresh()


def moved(index: int, location: tuple[float, float]) -> None:
    """A mast was dragged: move it, and forget its nodes because they were for the old place."""
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
    new_name = site_fields['name'].value
    if new_name != site['name'] and site['name'] in state['results']:
        state['results'][new_name] = state['results'].pop(site['name'])
    site.update(name=new_name, lat=place[0], lon=place[1])
    refresh()


def on_mean(change: dict[str, Any]) -> None:
    """The mean box was ticked: the active site writes the weighted mean of its nodes too."""
    if not loading['on']:
        active()['mean'] = bool(change['new'])
        refresh()


def find(_button: Any) -> None:
    """Look up the nodes the active site would use: the nearest nine for a mast, the nodes the area overlaps."""
    site = active()
    domain = shared_fields['domain'].value
    try:
        if site['polygon']:
            site['offered'] = find_polygon_nodes(site['polygon'], domain)
            node_info.value = f'{len(site["offered"])} nodes overlap {site["name"]} (click one for its share).'
        else:
            site['offered'] = find_nodes(site['lat'], site['lon'], domain)
            node_info.value = f'{len(site["offered"])} nodes offered. Click one to choose it.'
        site['chosen'] = []
    except Exception as error:  # the library raises NodeLookupError and the like
        node_info.value = f'<span style="color:#dc2626">{error}</span>'
    refresh()


def toggle(node: dict[str, Any]) -> None:
    """Show a node's details; for a mast also choose or drop it."""
    site = active()
    text = f'{node["lat"]:.3f}, {node["lon"]:.3f}: {node["distance_km"]:.1f} km, orog {node["orog"]:.0f} m, '
    text += f'land {node["sftlf"]:.0f}%'
    if site['polygon']:
        node_info.value = text + f', {node["overlap"]:.0%} of its cell inside the area. An area uses all of these.'
        return
    key = (node['lat'], node['lon'])
    if any((c['lat'], c['lon']) == key for c in site['chosen']):
        site['chosen'] = [c for c in site['chosen'] if (c['lat'], c['lon']) != key]
    else:
        site['chosen'] = [*site['chosen'], node]
    node_info.value = f'{text}. {len(site["chosen"])} chosen.'
    refresh()


def on_draw(change: dict[str, Any]) -> None:
    """The map's polygons changed (drawn, reshaped, moved or deleted): keep the one area in step with them."""
    polygons = [f for f in change['new'] if f.get('geometry', {}).get('type') == 'Polygon']
    index = area_index()
    if not polygons:
        if index is None:
            return
        gone = sites.pop(index)
        state['results'].pop(gone['name'], None)
        if not sites:
            sites.append(new_site('mast-1', DEFAULTS['lat'], DEFAULTS['lon']))
        state['active'] = min(state['active'], len(sites) - 1)
        node_info.value = f'{gone["name"]} was deleted.'
        refresh()
        return
    if index is None:
        lat, lon = centre(polygons[-1])
        sites.append(new_site(unique_name('area'), lat, lon, json.dumps(polygons[-1])))
        state['active'] = len(sites) - 1
        vertices = len(polygons[-1]['geometry']['coordinates'][0]) - 1
        node_info.value = f'Added {sites[-1]["name"]} ({vertices} vertices). Find nodes to preview its nodes.'
        refresh()
        return
    site = sites[index]
    current = json.loads(site['polygon'])
    if len(polygons) > 1:  # a second polygon was drawn: keep the first
        node_info.value = f'Only one area is allowed. Delete {site["name"]} to draw another.'
        draw.data = [current]
        return
    if same_shape(polygons[0], current):
        return
    lat, lon = centre(polygons[0])
    site.update(polygon=json.dumps(polygons[0]), lat=lat, lon=lon, offered=[], chosen=[], used=[])
    state['active'] = index
    node_info.value = f'{site["name"]} was reshaped. Find nodes to preview its nodes.'
    refresh()


def on_area_click(**_event: Any) -> None:
    """The area was clicked on the map: make it the site being worked on."""
    index = area_index()
    if index is not None and index != state['active']:
        select(index)


def add_site(_button: Any) -> None:
    """Add a mast just north of the active site, and work on it."""
    site = active()
    name = unique_name('mast')
    sites.append(new_site(name, round(site['lat'] + 0.06, 4), site['lon']))
    state['active'] = len(sites) - 1
    node_info.value = f'Added {name}. Drag its marker to where it belongs.'
    refresh()


def remove_site(_button: Any) -> None:
    """Remove the active site; removing the area clears it from the map too."""
    gone = sites.pop(state['active'])
    state['results'].pop(gone['name'], None)
    if gone['polygon']:
        draw.data = []
    if not sites:
        sites.append(new_site('mast-1', DEFAULTS['lat'], DEFAULTS['lon']))
    state['active'] = max(0, state['active'] - 1)
    show_results()
    refresh()


def start(indices: list[int]) -> None:
    """Run these sites one after another on a worker thread; the thread updates the widgets itself."""
    jobs = [(sites[i]['name'], *build(values_for(sites[i]), sites[i]['chosen'], sites[i]['polygon'])) for i in indices]
    cancel = state['cancel'] = threading.Event()
    for i in indices:
        sites[i]['used'] = []
        state['results'].pop(sites[i]['name'], None)
    show_results()
    progress.value, progress.max = 0, 1
    progress.layout.display = cancel_button.layout.display = ''
    run_button.disabled = run_selected_button.disabled = True

    def work() -> None:
        for number, (name, settings, site_obj, _problems) in enumerate(jobs, start=1):
            if cancel.is_set():
                break

            def on_progress(done: int, total: int, result: Any, name: str = name, number: int = number) -> None:
                progress.max, progress.value = max(total, 1), done
                where = f'{name} (site {number} of {len(jobs)})' if len(jobs) > 1 else name
                progress_label.value = f'{where}: file {done} of {total}: {result.filename}: {result.status}'

            data = summary(run_site(site_obj, settings, on_progress, cancel))
            site = next((s for s in sites if s['name'] == name), None)
            if site is not None:
                site['used'] = data['nodes']
            state['results'][name] = render(name, data)
            show_results()
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


# %% [markdown]
# ## Behaviour: importing a project or a polygon file


# %%
def say(text: str, ok: bool = True) -> None:
    """Report an import's outcome under the Import section, red when it failed."""
    colour = '#16a34a' if ok else '#dc2626'
    import_info.value = f'<div style="color:{colour}; white-space:pre-wrap">{text}</div>'


def show_area(feature: dict[str, Any]) -> None:
    """Put a polygon on the map and zoom to it."""
    draw.data = [feature]
    ring = feature['geometry']['coordinates'][0]
    lons, lats = [p[0] for p in ring], [p[1] for p in ring]
    fmap.fit_bounds([[min(lats), min(lons)], [max(lats), max(lons)]])


def apply_polygon(polygon: Polygon, name: str) -> None:
    """Make an imported polygon the area, replacing the area there is."""
    feature = feature_of(polygon)
    lat, lon = centre(feature)
    stem = re.sub(r'[^A-Za-z0-9._-]', '-', Path(name).stem)
    index = area_index()
    if index is None:
        taken = {site['name'] for site in sites}
        label = stem if stem and stem not in taken else unique_name('area')
        sites.append(new_site(label, lat, lon, json.dumps(feature)))
        index = len(sites) - 1
    else:
        sites[index].update(polygon=json.dumps(feature), lat=lat, lon=lon, offered=[], chosen=[], used=[])
    state['active'] = index
    node_info.value = 'Find nodes to preview the nodes this area uses.'
    show_area(feature)
    refresh()
    rings = len(feature['geometry']['coordinates'])
    say(f'Imported the polygon from {name} as {sites[index]["name"]} ({rings} ring(s)).')


def apply_project(project: Project, name: str) -> None:
    """Replace the settings and the sites with a project's. What the notebook cannot show is skipped, and said so."""
    notes, imported, area = [], [], None
    for site in project.sites:
        if site.bbox is not None:
            notes.append(f'{site.name}: a box site is not supported here, skipped.')
            continue
        if site.overrides:
            notes.append(
                f'{site.name}: its own {", ".join(site.overrides)} setting(s) are ignored; settings are shared.'
            )
        if site.polygon is not None:
            if area is not None:
                notes.append(f'{site.name}: only one area is allowed, skipped.')
                continue
            area = feature_of(site.polygon)
            lat, lon = centre(area)
            imported.append(new_site(site.name, lat, lon, json.dumps(area)) | {'mean': site.node_mean})
            continue
        mast = new_site(site.name, float(site.point.lat), float(site.point.lon))
        mast['chosen'] = [{'lat': float(n.lat), 'lon': float(n.lon)} | NO_NODE for n in site.nodes or []]
        mast['mean'] = site.node_mean
        imported.append(mast)
    if not imported:
        raise ValueError('The project has no site this notebook can show.')
    settings = project.settings
    loading['on'] = True
    shared_fields['domain'].value = settings.domain
    shared_fields['freq'].options = freqs(settings.domain)
    for key in ('start', 'end', 'freq', 'preset', 'node_selection', 'format'):
        shared_fields[key].value = getattr(settings, key)
    shared_fields['cache'].value, shared_fields['out'].value = str(settings.cache), str(settings.out)
    loading['on'] = False
    sites[:] = imported
    state.update(active=0, results={})
    show_results()
    node_info.value = 'Pick a site and Find nodes to see its nodes.'
    if area is not None:
        show_area(area)
    else:
        draw.data = []
        fmap.center = (imported[0]['lat'], imported[0]['lon'])
    refresh()
    say('\n'.join([f'Imported {name}: {len(imported)} site(s).', *notes]), ok=not notes)


def import_text(name: str, text: str, base_dir: Path) -> None:
    """Import a file's text by what its name ends with; a problem is shown, not raised."""
    lower = name.lower()
    if not lower.endswith(('.toml', '.kml', '.geojson', '.json')):
        say(f'{name}: use a .toml project or a .geojson, .json or .kml polygon.', ok=False)
        return
    try:
        if lower.endswith('.toml'):
            apply_project(project_from_dict(tomllib.loads(text), base_dir), name)
        elif lower.endswith('.kml'):
            apply_polygon(polygon_from_kml(text, name), name)
        else:
            apply_polygon(polygon_from_geojson(text, name), name)
    except ValueError as error:  # a bad project (ProjectError), polygon (BoundaryFileError) or TOML
        say(str(error), ok=False)


def import_from_path(_button: Any) -> None:
    """Import the file named in the path box."""
    path = Path(import_path.value.strip().strip('"'))
    try:
        if path.suffix.lower() == '.toml':
            apply_project(load_project(path), path.name)
        else:
            import_text(path.name, path.read_text(encoding='utf-8'), path.parent)
    except (OSError, ValueError) as error:
        say(str(error), ok=False)


def import_uploaded_project(items: list[dict[str, Any]]) -> None:
    """Import an uploaded project.toml with the files uploaded beside it, which its polygon file may be."""
    with tempfile.TemporaryDirectory() as folder:
        for item in items:
            (Path(folder) / Path(item['name']).name).write_bytes(bytes(item['content']))
        toml = next(item for item in items if item['name'].lower().endswith('.toml'))
        try:
            project = load_project(Path(folder) / Path(toml['name']).name)
            # a relative cache or out folder means next to the notebook, not inside the temporary copy
            settings = replace(
                project.settings, **{k: rebase(getattr(project.settings, k), folder) for k in ('cache', 'out')}
            )
            apply_project(replace(project, settings=settings, path=None), toml['name'])
        except ValueError as error:
            hint = '\nSelect the polygon file together with the project.toml, or use the path box.'
            say(str(error) + (hint if 'Cannot read' in str(error) else ''), ok=False)


def rebase(path: Path, folder: str) -> Path:
    """A path inside the temporary upload folder, moved to the same place under the notebook folder."""
    try:
        return Path.cwd() / path.relative_to(folder)
    except ValueError:
        return path


def import_from_upload(change: dict[str, Any]) -> None:
    """Import what was chosen in the Upload box: a project with its files, or a polygon file."""
    items = list(change['new'])
    if not items:
        return
    if any(item['name'].lower().endswith('.toml') for item in items):
        import_uploaded_project(items)
    else:
        item = items[0]
        import_text(item['name'], bytes(item['content']).decode('utf-8'), Path.cwd())
    import_upload.value = ()


for widget in shared_fields.values():
    widget.observe(refresh, names='value')
shared_fields['domain'].observe(on_domain, names='value')
for widget in site_fields.values():
    widget.observe(on_site_edit, names='value')
site_select.observe(lambda change: None if loading['on'] else select(change['new']), names='value')
find_button.on_click(find)
run_button.on_click(lambda _b: start(list(range(len(sites)))))
run_selected_button.on_click(lambda _b: start([state['active']]))
cancel_button.on_click(lambda _b: state['cancel'] and state['cancel'].set())
add_button.on_click(add_site)
remove_button.on_click(remove_site)
import_button.on_click(import_from_path)
mean_box.observe(on_mean, names='value')
import_upload.observe(import_from_upload, names='value')
draw.observe(on_draw, names='data')
draw.on_click(on_area_click)

# %% [markdown]
# ## The app

# %%
notes = {'preset': (preset_note,), 'node_selection': (selection_note,)}  # shown under the field they explain
form = w.VBox(
    [
        w.HBox([site_select, add_button], layout=w.Layout(width='440px')),
        *site_fields.values(),
        w.HBox([find_button, remove_button]),
        mean_box,
        *(item for key, widget in shared_fields.items() for item in (widget, *notes.get(key, ()))),
        import_box,
    ],
    layout=w.Layout(width='440px'),
)
right = w.VBox(
    [
        fmap,
        node_info,
        plan_label,
        problems_box,
        w.HBox([run_button, run_selected_button, cancel_button]),
        progress,
        progress_label,
        result_box,
    ],
    layout=w.Layout(flex='1'),
)
refresh()
w.HBox([form, right])
