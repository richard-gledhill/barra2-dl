# ADR-005: The GUI is a Jupyter notebook of ipywidgets and ipyleaflet

Status: Proposed (the owner chose the notebook on 2026-11-02; accepted when this ADR merges)

## Context

RFC-005 5.2 asks for a GUI that a wind analyst can use without writing code, built on the engine of ADR-004. The owner
preferred Streamlit or a similar web interface. Slice 3 built the same thin slice in candidate toolkits and the owner
compared them by using them. The evidence, the register of spikes run and not run, and the completed checklist are in
[the research note](../research/gui-toolkit-spikes.md). The spike code is on the tag `rfc005-spikes` (commit `1a62287`)
and is not on `main`.

## Decision

The interface is a Jupyter notebook using **ipywidgets** for the form and **ipyleaflet** (with its Geoman draw control)
for the map. Voila is not part of it: the analyst opens the notebook in JupyterLab and runs the cells. The spike versions
were ipywidgets 8.1.9, ipyleaflet 0.20.0 and JupyterLab 4.6.5.

The owner picked it after using three spikes (Streamlit, NiceGUI, notebook). It passed all five gates and every item the
owner assessed except two they left unmeasured; the owner called it "very intuitive". It did more than the others: several
draggable masts, one editable polygon, the nodes a run will download ringed on the map, import of a project or polygon
file, and a saved last session.

## Spikes run and not run

| Candidate | Status |
|---|---|
| Streamlit, NiceGUI, notebook (ipywidgets + ipyleaflet) | Built; the notebook was iterated on and chosen |
| Panel, Dash, Flet | Not built; only their pins were checked (they resolve unchanged on 3.12 to 3.14) |
| tkinter | Not written up |
| Voila | Dropped by the owner |
| Gradio, Reflex, pywebview with HTML, Qt (PySide6), Textual, Solara | Not built or assessed |

The decision rests on three built spikes, not the six the SPEC planned. A reader who wants Panel, Dash or Flet compared
should treat them as untried.

## Alternatives considered

- **Streamlit.** Worked for the thin slice. Heaviest install (+173 MB), usage statistics on by default, 1 to 2 s lag on every
  map click, and a run survives a reload with no way to cancel it. Not chosen.
- **NiceGUI.** Worked; lighter (+55 MB) and event-driven, with no layer click events on its Leaflet map. Not chosen. It is
  the built fallback.
- **Panel, Dash, Flet.** Not built, because the owner decided first.
- **tkinter.** Not assessed.
- **Gradio, Reflex, pywebview, Qt, Textual.** Not assessed. Solara, built on the same widgets, is the route to a hosted app
  if one is ever wanted.

## Consequences

- **Shape of `gui/`.** The notebook is the interface, so `barra2_dl/gui/` holds the notebook source (a jupytext `.py` with
  `# %%` cells, paired with an `.ipynb`) and the widget code it calls, kept in `.py` modules where it can be tested.
  `barra2-dl-gui` copies the notebook to a folder the analyst names and starts JupyterLab on it, so starting it is one
  command. Slice 4 settles the layout.
- **`gui` extra.** `ipywidgets`, `ipyleaflet` and `jupyterlab` (with `ipykernel`). The spike's pins resolve against the
  library's with no change on 3.12 to 3.14. The extra's size is not yet measured: slice 4 measures it.
- **Threading.** A run is a plain `threading.Thread` that sets widget values from the progress callback, with a
  `threading.Event` for cancel. The page stays responsive. A second thread refreshes the cache line.
- **Engine work the spike found.** The polygon node preview (`find_polygon_nodes`) and the choice of which nodes a
  selection will download (`planned_nodes`) are interface code in the spike and belong in the library (ADR-004 rule 3).
  Slice 4 or 5 moves them into `mapping` or `project`.
- **Session file.** The notebook saves `last_session.json` at each run. Whether that is documented as a feature, and
  whether the engine gains a project writer, is a slice 4 question.
- **Documentation.** The owner asked for minor text-cell updates in the notebook and an update to `docs/how-to-use.md`.
  Slice 4 does the first; slice 6 (user docs) does the second.
- **Testing.** The spike tests call the app's functions after `runpy.run_path`, with the fake NCSS server and no display.
  Slice 4 keeps this and adds a test that executes the shipped notebook with `nbclient`.
- **Console output.** Prints appear under the cell that started the app. The dual log-and-print convention is unchanged;
  the owner revisits it at slice 4.
- **Maintenance risk.** ipywidgets and JupyterLab were released in the last three months. ipyleaflet's last release,
  0.20.0, is dated 2025-06-13, over 12 months before this decision; the owner judged it maintained. The draw control the
  spike uses is part of it. If it is abandoned, the fallback is NiceGUI.
- **Audience.** A notebook asks the analyst to start JupyterLab and run cells, and Voila was dropped. If analysts find the
  cells off-putting, NiceGUI is the next candidate, and ADR-004's layering means the engine does not change.
- **Freezing.** A desktop executable is out of scope for v1 (RFC decision 4).
- **Not established.** Narrow-width layout, the notebook's install size and telemetry, and the unbuilt candidates.
