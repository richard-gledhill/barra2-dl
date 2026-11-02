# GUI toolkit spikes (RFC-005, slice 3)

Evidence for [ADR-005](../adr/ADR-005-gui-toolkit.md). Spike code is not on `main`: it is on the branch
`chore/gui-toolkit-spikes`, tagged `rfc005-spikes` (commit `1a62287`). Paths below are relative to that tag. Measured on
Windows 11, Python 3.12, against the fake NCSS server (`spikes/common/fake_ncss.py`, which serves the `tests/data`
fixtures anywhere in Australia), 2026-10-31 to 2026-11-02.

## Spike register: what was run and what was not

Kept for future reference, so a later reader knows which toolkits were actually tried.

| Candidate | Status | What exists |
|---|---|---|
| Streamlit 1.66.1 (+ streamlit-folium 0.27.4) | **Built and measured** | `spikes/streamlit/`, 225 lines; findings, screenshots and freeze in `spikes/_evidence/` |
| NiceGUI 3.18.0 (built-in Leaflet) | **Built and measured** | `spikes/nicegui/`, 295 lines; same evidence folder |
| Notebook: ipywidgets 8.1.9 + ipyleaflet 0.20.0, **no Voila** | **Built, iterated on, and chosen** | `spikes/notebook/app.py`, 893 lines, 13 tests; completed checklist below |
| Panel | **Not built.** Pin dry run only | `spikes/_evidence/compile-panel-*.txt` (58 packages pinned) |
| Dash (Plotly) | **Not built.** Pin dry run only | `compile-dash-*.txt` (49 packages) |
| Flet | **Not built**, so no freeze attempt. Pin dry run only | `compile-flet-*.txt` (24 packages) |
| tkinter | **Not written up on paper** | none |
| Voila (part of the notebook spike as first proposed) | **Dropped** by the owner, 2026-11-01 | none |
| Gradio, Reflex, pywebview with HTML, Qt (PySide6), Textual, Solara | Not built or assessed (named in the SPEC only) | none |

Why the others were not built: the owner reviewed spikes 1 and 2 at the optional checkpoint, asked for the notebook
spike, found it did what they wanted, and chose it on 2026-11-02 without building Panel, Dash or Flet. The 4-hour time
boxes for those three were not spent. If the notebook later proves a poor fit, NiceGUI is the built fallback; Panel,
Dash and Flet would be starting from nothing.

## Pins (gate 4), all six candidates

`uv pip compile` of each spike's `requirements.txt` against the library's pins resolved with no change to numpy 2.5.4,
pandas 3.1.0, xarray 2026.9.0, h5py 3.16.0 or requests 2.34.2, on Python 3.12, 3.13 and 3.14
(`spikes/_evidence/compile-<toolkit>-<version>.txt`). The notebook run still included Voila (94 packages). Installed and
run on 3.12 only.

## Streamlit and NiceGUI

Full table: `spikes/_evidence/findings-1-streamlit-2-nicegui.md`. Both worked for the whole thin slice (form validated by
`validate`, offered, chosen and used nodes on the map, polygon drawing into `polygon_from_geojson`, progress and cancel
from a worker thread, a `cancelled` result). Streamlit added 173 MB and 2,745 files over the library, collects usage
statistics unless switched off, and lagged 1 to 2 s on a map click because the script reruns. NiceGUI added 55 MB and
2,431 files, and has no layer click events, so the spike hit-tested map clicks. Both kept a run alive after a page reload
with no way to cancel it. Both servers printed the library's per-file progress lines to the console.

## Notebook: what it does

All through `__all__` names and `globals` constants:

- A form built from the library's choices (domains, frequencies, presets, node selections, formats), validated by
  `project.validate` with a red border on the field and a problem list, and the preset's variables read from
  `globals` on every refresh.
- Several draggable masts. Find nodes (`mapping.nearest_nodes`) draws the offered nodes, a click chooses one, and the nodes
  a run would download are ringed (nearest, the 2x2 block for `average4`, the chosen nodes, or every node an area
  overlaps).
- One editable polygon area, independent of the masts (grey when idle, purple when selected, labelled), with an optional
  overlap-weighted mean.
- "N files, M cached" from `plan_site`, refreshed every 3 s so cache files deleted by hand show.
- Run all sites or the selected site on a worker thread, with a progress bar, Cancel, and a summary of files and nodes
  from `site_result_to_dict`; the used nodes drawn after the run.
- Import of a `project.toml` (with its polygon file), or a GeoJSON or KML polygon, by path or upload; `last_session.json`
  written at every run and restored by Load last session.

## Notebook checklist

Assessed by the owner on 2026-11-02. Claude prefilled the items its work and tests settled, and the owner confirmed
them and answered the rest. A gate item marked No would remove the toolkit; none did.

| # | Item | Answer | Evidence and comment |
|---|---|---|---|
| 1 | **gate** `__all__` names only, thin slice complete | Yes | Polygon drawing also works |
| 2 | **gate** Offered, chosen, used nodes distinguishable | Yes | Blue offered, orange-ringed used, violet-ringed planned |
| 3 | **gate** Cancel gives `cancelled` | Yes | Test and browser |
| 4 | **gate** Installs against the pins on 3.12, 3.13, 3.14 | Yes | Resolves unchanged on all three; installed and run on 3.12 only |
| 5 | **gate** Licences | Yes | ipywidgets BSD-3-Clause, ipyleaflet MIT, JupyterLab BSD-3-Clause, xyzservices BSD-3-Clause |
| 6 | Looks good at desktop width | Yes | |
| 7 | Narrow laptop width | **Not tested** | |
| 8 | Analyst finds the next step unaided | Yes | "Very intuitive." Minor text-cell updates to the notebook, and `how-to-use.md` to be updated |
| 9 | One command to start | Yes | Two today (`jupytext --to notebook`, then `jupyter lab`); the `barra2-dl-gui` entry point will give one |
| 10 | Validation beside the field | Yes | Red border on the field plus a problem list |
| 11 | Pan, zoom, tiles smooth | Yes | |
| 12 | Click a node to select it | Yes | |
| 13 | Distance, altitude, land fraction for a node | Yes | Shown in a line under the map when a node is clicked |
| 14 | Draw a polygon | Yes | Geoman draw control |
| 15 | Edit and delete it | Yes | One area at a time; a second polygon is refused |
| 16 | Valid `Polygon` via `polygon_from_geojson` | Yes | |
| 17 | Live progress | Yes | Bar plus a "file i of n" line |
| 18 | Responsive during a run | Yes | |
| 19 | Reload or second tab during a run | Yes | |
| 20 | Failed and cancelled runs shown properly | Yes | |
| 21 | Modest threading code | Yes | One worker thread and one timer thread, each about 20 lines, writing widget values directly |
| 22 | Install size and package count | **Not measured** | Measure at slice 4. The pin run listed 94 packages with Voila, fewer without it |
| 23 | No unwanted outbound calls at start-up | **Not measured** | |
| 24 | Fits a `gui` extra and entry point | Yes | Copy the notebook, start JupyterLab; slice 4 settles the layout |
| 25 | Display-free smoke test | Yes | 13 tests call the app's functions after `runpy.run_path`; no display or browser |
| 26 | Actively maintained, including the map component | Yes | ipywidgets 8.1.9 (2026-08-18) and JupyterLab 4.6.5 (2026-10-29) are current. **ipyleaflet's last release is 0.20.0 on 2025-06-13, over 12 months old.** The owner judged it maintained; the ADR names the fallback |
| 27 | Freeze to a desktop executable | No, out of scope | Not needed in v1 (RFC decision 4) |

**Final comment (owner):** first choice; the preferred spike. Update the notebook's text cells and `how-to-use.md`.

Information beside the checklist: code size 893 lines plus 421 of tests (Streamlit 225, NiceGUI 295).

## Findings for the engine and slice 4

- A preset with variables outside the fixtures downloaded only the three the fixtures held. This was a defect in the
  fake server, fixed in `spikes/common/fake_ncss.py`, not in the engine.
- The csv written by the netCDF-to-csv route labels the `station` column with the node selection (`nearest`, `average4`),
  while the raw THREDDS csv keeps `GridPointRequestedAt[...]`. This is by design in `merge._frame`; the requested point is
  in the csv header block.
- `run_site` raises `ProjectError` for an `area` site with `format = "csv"`, so an interface must validate before it runs.
- A pre-run preview of a polygon's nodes needed spike code (`find_polygon_nodes`, a lattice of `nearest_nodes` lookups
  filtered by `Polygon.cell_overlap`). Which nodes a site's selection will download (`planned_nodes`) is also spike code.
  Both belong in the library (ADR-004 rule 3); the SPEC listed the first as a slice 5 finding.
- A session file (`last_session.json`) was added by the owner's request. Whether it stays a convenience or becomes an
  engine feature (for example a `project.toml` writer) is open.

## Console output

Both web spikes showed the library's progress prints in the server console. The notebook shows them under the cell that
started the app, not in the page; the progress callback alone drove the progress bar. Not tried: a `logging` handler
feeding a log pane, or redirecting stdout in the worker.

## Not established

Narrow-width layout, the notebook's install size and telemetry, Panel, Dash and Flet beyond their pins, the freeze cost
of any candidate, and tkinter on paper.
