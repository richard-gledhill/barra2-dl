"""Spike 1: Streamlit with streamlit-folium.

Run: python spikes/streamlit/app.py (starts `streamlit run` on this file).
"""

import json
import sys
import threading
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import folium
import streamlit as st
from folium.plugins import Draw
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
from streamlit.runtime.scriptrunner import get_script_run_ctx
from streamlit_folium import st_folium

from barra2_dl.project import run_site


@dataclass
class Run:
    """Shared between the worker thread and the page; plain data, so the thread never touches st."""

    cancel: threading.Event = field(default_factory=threading.Event)
    done: int = 0
    total: int = 0
    last: str = ''
    result: dict[str, Any] | None = None
    thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        """Whether the worker thread is alive."""
        return self.thread is not None and self.thread.is_alive()


def main() -> None:
    """Start the server and open the browser, as barra2_dl.gui:main would."""
    from streamlit.web.cli import main as streamlit_main

    sys.argv = ['streamlit', 'run', __file__, '--browser.gatherUsageStats=false']
    streamlit_main()


def _start(site, settings) -> None:
    run = Run()
    st.session_state.run = run

    def progress(done: int, total: int, result) -> None:
        run.done, run.total, run.last = done, total, f'{result.filename}: {result.status}'

    def work() -> None:
        outcome = run_site(site, settings, progress, run.cancel)
        run.result = summary(outcome)

    run.thread = threading.Thread(target=work, daemon=True)
    run.thread.start()


@st.fragment(run_every=0.5)
def _run_panel() -> None:
    run: Run | None = st.session_state.get('run')
    if run is None:
        return
    if run.running:
        st.progress(run.done / run.total if run.total else 0.0, text=f'file {run.done} of {run.total}: {run.last}')
        if st.button('Cancel', key='cancel'):
            run.cancel.set()
    elif run.result is not None and not st.session_state.get('shown'):
        st.session_state.shown = True
        st.rerun()  # redraw the whole page so the map shows the nodes used


def _map(values: dict[str, Any], offered, chosen, polygon, used) -> dict[str, Any]:
    fmap = folium.Map(location=[values['lat'], values['lon']], zoom_start=11, control_scale=True)
    Draw(
        export=False,
        draw_options={'polyline': False, 'rectangle': False, 'circle': False, 'marker': False, 'circlemarker': False},
    ).add_to(fmap)
    folium.Marker([values['lat'], values['lon']], tooltip='site', icon=folium.Icon(color='black')).add_to(fmap)
    picked = {(n['lat'], n['lon']) for n in chosen}
    for node in offered:
        colour = COLOURS['chosen'] if (node['lat'], node['lon']) in picked else COLOURS['offered']
        folium.CircleMarker(
            [node['lat'], node['lon']],
            radius=9,
            color=colour,
            fill=True,
            fill_opacity=0.7,
            tooltip=f'{node["distance_km"]:.1f} km, orog {node["orog"]:.0f} m, land {node["sftlf"]:.0f}%',
        ).add_to(fmap)
    for node in used:
        folium.CircleMarker(
            [node['lat'], node['lon']],
            radius=15,
            color=COLOURS['used'],
            weight=4,
            fill=False,
            tooltip=f'used: {node["distance_km"]:.1f} km',
        ).add_to(fmap)
    if polygon:
        folium.GeoJson(json.loads(polygon), style_function=lambda _f: {'color': '#a855f7'}).add_to(fmap)
    return st_folium(
        fmap, height=520, width='stretch', key='map', returned_objects=['last_object_clicked', 'all_drawings']
    )


def _sidebar(state) -> tuple[dict[str, Any], Any, Any, list[tuple[str, str]]]:
    st.subheader('Site')
    values: dict[str, Any] = {'name': st.text_input('Site name', DEFAULTS['name'])}
    values['lat'] = st.number_input('Latitude', value=DEFAULTS['lat'], format='%.4f', step=0.01, key='lat')
    values['lon'] = st.number_input('Longitude', value=DEFAULTS['lon'], format='%.4f', step=0.01, key='lon')
    values['start'] = st.date_input('Start', DEFAULTS['start'], min_value=date(1979, 1, 1))
    values['end'] = st.date_input('End', DEFAULTS['end'], min_value=date(1979, 1, 1))
    values['domain'] = st.selectbox('Domain', DOMAINS)
    values['freq'] = st.selectbox('Frequency', freqs(values['domain']))
    values['preset'] = st.selectbox('Preset', PRESETS, index=PRESETS.index(DEFAULTS['preset']))
    values['node_selection'] = st.selectbox('Node selection', SELECTIONS)
    values['format'] = st.selectbox('Output', FORMATS, index=FORMATS.index(DEFAULTS['format']))
    settings, site, problems = build(values, state.chosen, state.polygon)
    for key, message in problems:
        st.error(f'{key}: {message}')
    if st.button('Find nodes'):
        try:
            state.offered = find_nodes(values['lat'], values['lon'], values['domain'])
            state.chosen = []
            state.lookup_error = None
        except Exception as error:
            state.lookup_error = str(error)
    if state.lookup_error:
        st.error(state.lookup_error)
    if state.polygon and st.button('Clear polygon'):
        state.polygon = None
        st.rerun()
    return values, settings, site, problems


def _toggle(state, clicked: dict[str, float]) -> None:
    for node in state.offered:
        if abs(node['lat'] - clicked['lat']) < 1e-3 and abs(node['lon'] - clicked['lng']) < 1e-3:
            key = (node['lat'], node['lon'])
            if any((c['lat'], c['lon']) == key for c in state.chosen):
                state.chosen = [c for c in state.chosen if (c['lat'], c['lon']) != key]
            else:
                state.chosen = [*state.chosen, node]
            st.rerun()


def _read_map(state, out: dict[str, Any] | None) -> None:
    clicked = out.get('last_object_clicked') if out else None
    if clicked and clicked != state.click:
        state.click = clicked
        _toggle(state, clicked)
    drawings = (out or {}).get('all_drawings') or []
    polygons = [d for d in drawings if d['geometry']['type'] == 'Polygon']
    if polygons and json.dumps(polygons[-1]) != state.polygon:
        state.polygon = json.dumps(polygons[-1])
        st.rerun()


def _result(result: dict[str, Any]) -> None:
    st.subheader(f'Result: {result["status"]}')
    if result['error']:
        st.error(result['error'])
    if result['missing']:
        st.warning('missing: ' + ', '.join(result['missing']))
    st.write('Outputs', result['outputs'])
    st.dataframe(result['files'], width='stretch')
    st.dataframe(result['nodes'], width='stretch')


def page() -> None:
    """Draw the page: form in the sidebar, map on the left, run and result on the right."""
    st.set_page_config(page_title='BARRA2 download (Streamlit spike)', layout='wide')
    state = st.session_state
    state.setdefault('offered', [])
    state.setdefault('chosen', [])
    state.setdefault('polygon', None)
    state.setdefault('click', None)
    state.setdefault('lookup_error', None)

    st.title('BARRA2 wind data')
    with st.sidebar:
        values, settings, site, problems = _sidebar(state)

    left, right = st.columns([3, 2])
    run: Run | None = state.get('run')
    used = (run.result or {}).get('nodes', []) if run else []
    with left:
        out = _map(values, state.offered, state.chosen, state.polygon, used)
    _read_map(state, out)

    with right:
        st.subheader('Run')
        st.caption(f'{len(state.chosen)} node(s) chosen. Click a blue node on the map to choose it.')
        if not problems:
            st.write(plan_text(site, settings))
        if st.button('Run', type='primary', disabled=bool(problems) or bool(run and run.running)):
            state.shown = False
            _start(site, settings)
            st.rerun()
        _run_panel()
        if run and run.result:
            _result(run.result)


if get_script_run_ctx() is not None:
    page()
elif __name__ == '__main__':
    main()
