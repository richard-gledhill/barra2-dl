# Findings: spike 1 (Streamlit) and spike 2 (NiceGUI)

Measured 2026-10-31 on Windows 11, Python 3.12.10, against the fake NCSS server (`tests/data` fixtures), a 6-month run of
the fixture point (19 files; 4 workers). Versions are in `freeze-<toolkit>-3.12.txt`. These are the evidence column of the
checklist; the yes/no is the owner's. Screenshots are in `screens/`.

| Item | Streamlit 1.66.1 (+ streamlit-folium 0.27.4, folium 0.20.0) | NiceGUI 3.18.0 (built-in Leaflet) |
|---|---|---|
| 1 Public API | Yes: `import` check by reading; only `__all__` names and `globals`; `spike_common` also patches `project.preset_variables`/`resolve_variable_versions` (the fake) | Same |
| 2 Nodes drawn | Offered (blue), chosen (green) and used (orange ring) all drawn: `streamlit-offered-nodes`, `streamlit-chosen-and-used` | Same three: `nicegui-offered-nodes`, `nicegui-chosen-and-used` |
| 3 Cancel | Worked: result `cancelled`, 8 files cached (`streamlit-cancelled`) | Worked: result `cancelled` (`nicegui-cancelled`) |
| 4 Pins | `uv pip compile` against the library's numpy 2.5.4, pandas 3.1.0, xarray 2026.9.0, h5py 3.16.0, requests 2.34.2 resolved with no change on 3.12, 3.13 and 3.14 (`compile-streamlit-*.txt`); installed and run on 3.12 only | Same for `compile-nicegui-*.txt`; installed and run on 3.12 only |
| 5 Licence | streamlit Apache-2.0, folium MIT, branca MIT; **streamlit-folium declares no licence in its installed metadata** (no licence file); not verified elsewhere | nicegui MIT, fastapi MIT, uvicorn BSD-3-Clause |
| 6/7 Looks | Screenshots at 1400 px wide only; no narrow-width screenshot taken | Same |
| 9 One command | `python spikes/streamlit/app.py` (calls `streamlit.web.cli.main` with `run <file>`) | `python spikes/nicegui/app.py` (`ui.run`) |
| 10 Validation | Shown as a list in the sidebar (`end: ...`), not beside the field | Shown beside the field (Quasar `error` prop) |
| 12 Click a node | Works through `last_object_clicked`, with about a 1 to 2 s lag per click (whole script reruns) | Works; no layer click events exist, so the app hit-tests the map click against the offered nodes (0.015 degrees) |
| 13 Node details | Tooltip: distance, orog, land fraction | Same (`bindTooltip` on the circle) |
| 14/16 Polygon | Folium `Draw` plugin, GeoJSON back through `all_drawings`, accepted by `polygon_from_geojson`; a polygon site plans and runs (checked headless: 9 nodes in the summary with overlap and weight) | `Leaflet.draw` built in; `draw:created` gives the latlngs, converted to GeoJSON, accepted the same way |
| 15 Edit/delete | Not verified. The app re-renders the polygon as its own layer and added a "Clear polygon" button; toolbar edit/delete was not tested | Delete verified: toolbar "Clear all" reaches Python (`draw:deleted`) and the plan reverts to the point site. Edit (`draw:edited`) not wired |
| 17 Progress | Worked (`st.fragment(run_every=0.5)` polling a shared object) | Worked (`ui.timer(0.3)` polling a shared object) |
| 18 Responsive | Worker is a plain thread and the poll is a fragment, so the page is not blocked; panning the map during a run was not separately tested | `run.io_bound` thread; page not blocked; panning during a run not separately tested |
| 19 Reload | New session on reload: progress and Cancel are lost, but the worker thread **kept running and wrote all 19 files and the output**. Second tab not tested | Same observed result |
| 20 Failed run | Not run in the UI (`SPIKE_FAIL` not tried in a browser); `cancelled` and `ok` shown | Same |
| 21 Threading code | About 15 lines (a `Run` dataclass, a thread, a fragment poll) | About 10 lines (`run.io_bound`, a `State`, a timer) |
| 22 Install | +173 MB and +2,745 files over the library alone (276 vs 103 MB; 6,495 vs 3,750 files); 44 packages in the freeze; 16 s install with a warm cache | +55 MB, +2,431 files (158 MB; 6,181 files); 62 packages; 9 s |
| 23 Telemetry | Streamlit collects usage statistics by default (documented, not measured here); `main()` passes `--browser.gatherUsageStats=false` | Not measured; no analytics option was looked for |
| 24 Entry point | `main()` fits a `[project.scripts]` entry; it must set the usage-stats flag and runs a Streamlit CLI in process | `main()` is `ui.run(...)`; opens the browser itself |
| 25 Smoke test | `streamlit.testing.v1.AppTest`: form validation and a full run, no display, 1 test, 3.6 s (`smoke_test.py`); the map component is not rendered by it | NiceGUI `User` harness: opens the page, edits an input, finds nodes (`test_app.py`, 1.7 s). A full run under `run.io_bound` did not complete in the harness (not diagnosed); the run was checked in a browser |
| 26 Maintenance | streamlit 2026-10-21, streamlit-folium 2026-08-03, folium 2026-07-26 (latest PyPI uploads) | nicegui 2026-10-07, fastapi 2026-10-23, uvicorn 2026-09-25 |
| 27 Freeze | Not assessed (paper later) | Not assessed (paper later) |
| Code size | 225 lines (+28 test) | 295 lines (+17 test) |

## Console output

Both servers show the library's progress prints: one line per file (`<name> downloaded to <folder>`) plus a
`Download time` line, so about 21 lines for the 6-month run and 3 lines for each node lookup (`nearest_nodes` also
prints). A 36-year run would be about 1,300 lines. Neither server captured or hid them (they went to the server's
stdout). Not tried: a `logging` handler feeding a log pane; redirecting stdout in the worker (process-wide, so unsafe in a
threaded server). The progress callback alone gave a working progress bar in both.

## Notes for the engine and slice 4

- `site_result_to_dict` serialises with plain `json.dumps` (checked), so an interface needs no helper.
- The `Problem.key` of a validation problem maps to a form field for every form field the spikes had; `polygon` and
  `nodes` keys map to the map rather than a widget.
- A reload leaves an orphan worker running with no Cancel: slice 4 needs a place for the run state that outlives a page
  (a module-level registry keyed by site name) or a rule that a run stops when its page closes.
- No pre-run node preview exists for a polygon site; the nodes show only after a run (summary `nodes`).
- Spike bug, not a toolkit finding: the NiceGUI progress label keeps its last text after a run ends.
