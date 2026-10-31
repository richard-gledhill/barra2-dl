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
- [ ] PR

## Slice 1b: research (`docs/reanalysis-site-data-research`)
- [x] Seven research tasks (SPEC); note in `docs/development/research/`
- [x] Task 4 pinned: `save_node_boxes` fixtures and `tests/test_ncss_nodes.py`
- [x] Owner review of the note (decisions recorded in the SPEC); PR

## Slice 2: `feat/nearest-nodes`
- [x] SPEC addendum written (PR `docs: slice 2 SPEC addendum (nearest_nodes)`); approved with four answers 2026-10-31
- [x] Owner answers recorded under "Decisions" in the addendum; implementation is a separate PR, started when the owner says
- [ ] Fixtures: `save_node_lookups` in `scripts/build_test_fixtures.py` (live, once)
- [ ] `mapping`: `GridNode`, `NodeLookupError`, `nearest_nodes` (cache, shrunk box); delete the three draft helpers and their tests (approved); tests
- [ ] `globals`: `nodes` in `BARRA2_NODE_SELECTIONS` and `NodeSelection`; `download.nodes_data_urlfilenames`; tests
- [ ] `merge`: `node_selection='nodes'`, `node_mean`, frames and header without a mean; tests
- [ ] `project`: `Site.nodes`/`node_mean`, validation rows, `run_site` nodes route, summary; tests
- [ ] Example project and netCDF example cells (`.py` and `.ipynb`); docs (how-to-use, CONTEXT, README, AGENTS); live tests
- [ ] `make check`, `make test`, `make docs-test`, end-to-end run; PR

## Slice 2b: `feat/polygon-boundary` (beyond RFC-005; owner request)
- [ ] SPEC addendum; `mapping.Polygon`, file readers, node mask, `Site.polygon`, project-file key; tests; PR

## Slice 3: toolkit spikes and ADR
- [ ] SPEC addendum; five spikes (Streamlit, NiceGUI, Panel, Dash, Flet), tkinter on paper; ADR; PR

## Slice 4: `feat/gui-skeleton`
- [ ] SPEC addendum; `gui` extra, entry point, form, background run, carry selected/used nodes through, smoke test; PR

## Slice 5: `feat/gui-map-import`
- [ ] SPEC addendum; map preview, nodes selected or used drawn on the map (owner requirement), optional node layer (site or area plus margin), mast-list, project and boundary-file import, polygon drawing, summary view; PR

## Slice 6: `docs/gui-user-guide`
- [ ] User docs, CSIRO link check, atl3b credit; PR

## Finish
- [ ] Archive plan; RFC-005 Done; roadmap; README
