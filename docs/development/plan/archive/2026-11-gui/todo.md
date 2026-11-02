# Todo: GUI for wind resource assessment (RFC-005)

Resumed 2026-10-31 after RFC-007 shipped. The owner answered RFC section 9 on 2026-10-31 (SPEC, "Decisions"); RFC-005 is Accepted.

## Slice 1: `feat/project-engine`
- [x] `FileResult`; `_download_file` retries (atomic write and empty response done by RFC-007); tests
- [x] `download_serial` / `download_multithread`: results, `workers`, `progress`, `cancel`; tests
- [x] `globals`: `BARRA2_OUTPUT_FORMATS`, `Literal` aliases; `__all__` for `globals` and `mapping`; tests
- [x] `project.py`: data classes, `Problem`, `ProjectError`, `project_from_dict`/`site_from_dict`, `load_project`, `validate`; tests
- [x] `plan_site`; tests
- [x] `run_site`: csv download option for point sites (`write_df_csv`); output (`write_csv`), run summary, `site_result_to_dict`, failed/partial/cancelled/cache-mismatch paths; tests
- [x] Export in `__init__.py`; `test_package.py` boundary tests
- [x] `scripts/example_project.toml`; example cell in the netCDF example (`.py` and `.ipynb`)
- [x] Docs: how-to-use, `CONTEXT.md`, README, modules page; ADR-004
- [x] Live tests; `make check`, `make test`, `make docs-test`; end-to-end run in a scratch folder
- [x] PR (#163)

## Slice 1b: research (`docs/reanalysis-site-data-research`)
- [x] Seven research tasks (SPEC); note in `docs/development/research/`
- [x] Task 4 pinned: `save_node_boxes` fixtures and `tests/test_ncss_nodes.py`
- [x] Owner review of the note (decisions recorded in the SPEC); PR

## Slice 2: `feat/nearest-nodes`
- [x] SPEC addendum written (PR `docs: slice 2 SPEC addendum (nearest_nodes)`); approved with four answers 2026-10-31
- [x] Owner answers recorded under "Decisions" in the addendum; implementation is a separate PR, started when the owner says
- [x] Fixtures: `save_node_lookups` in `scripts/build_test_fixtures.py` (live, once)
- [x] `mapping`: `GridNode`, `NodeLookupError`, `nearest_nodes` (cache, shrunk box); delete the three draft helpers and their tests (approved); tests
- [x] `globals`: `nodes` in `BARRA2_NODE_SELECTIONS` and `NodeSelection`; `download.nodes_data_urlfilenames`; tests
- [x] `merge`: `node_selection='nodes'`, `node_mean`, frames and header without a mean; tests
- [x] `project`: `Site.nodes`/`node_mean`, validation rows, `run_site` nodes route, summary; tests
- [x] Example project and netCDF example cells (`.py` and `.ipynb`); docs (how-to-use, CONTEXT, README, AGENTS); live tests
- [x] `make check`, `make test`, `make docs-test`, live tests, end-to-end run of the example project; PR

## Slice 2b: `feat/polygon-boundary` (beyond RFC-005; owner request)
- [x] SPEC addendum written (PR `docs: slice 2b SPEC addendum (polygon boundary)`); approved with five answers 2026-10-31
- [x] Owner answers recorded under "Decisions" in the addendum
- [x] `mapping.Polygon`, readers, `cell_overlap`; tests
- [x] `merge` polygon mask and `_site_mean`; `project` `Site.polygon`, validation, summary; tests
- [x] Example boundary, docs, live tests; `make check`, `make test`, `make docs-test`; PR

## Slice 3: toolkit spikes and ADR
- [x] SPEC addendum written (PR `docs: slice 3 SPEC addendum (toolkit spikes)`) and approved 2026-10-31
- [x] Set up: spike branch `chore/gui-toolkit-spikes`, `spikes/common` (fake NCSS server), pin dry run for all six
- [x] Spikes built: Streamlit, NiceGUI, notebook (ipywidgets and ipyleaflet, no Voila). Not built: Panel, Dash, Flet
- [x] Notebook chosen by the owner 2026-11-02; checklist completed in the research note
- [x] Research note `docs/development/research/gui-toolkit-spikes.md`, with the register of spikes run and not run
- [x] ADR-005 and `adr/README.md` row; spike branch tagged `rfc005-spikes` (`1a62287`)
- [x] `make check`, `make docs-test`; PR `docs: ADR-005 GUI toolkit (slice 3)` merged as #157 (no spike code on `main`)
- [x] tkinter on paper: dropped, not written up

## Slice 4: `feat/gui-skeleton`
- [x] SPEC addendum written (PR `docs: slice 4 SPEC addendum (notebook GUI)`); approved 2026-11-02 with answers A to N
- [x] Owner answers recorded under "Decisions" in the addendum
- [x] Owner reviews the notebook's markdown cells before the commit that adds the notebook
- [x] Library: `mapping.polygon_nodes`, `mapping.planned_nodes`, `project.project_to_dict`; tests
- [x] `gui` extra, entry point, `gui/app.py` (`build_app`), notebook and its jupytext source, port of the spike's behaviours; tests
- [x] Reduced fake server in `tests/`; `test_gui.py`, `test_gui_notebook.py`, `test_package.py` updates
- [x] CI installs the extra; `make check`, `make test`, `make docs-test`; install size into the research note; PR

## Slice 5: `feat/gui-map-import` (retired 2026-11-02)
- [x] Retired by the owner: slice 4 covers the map, the nodes drawn, imports and the summary. Mast-list CSV import and the optional node layer are in the backlog; the plain box `area` node table is dropped (the GUI has no plain box)

## Slice 6: `docs/gui-user-guide`
- [x] SPEC addendum (#162, approved)
- [x] User docs: GUI guide, project-file reference with `tests/test_docs.py`, `how-to-use.md`, AUS-11 note (CSIRO cited without a link, owner decision), atl3b credit in README, docs and release notes text
- [x] PR (#163)

## Finish
- [x] Archived. RFC-005 set to Done and the roadmap updated, with the owner's OK
- [x] README roadmap row
