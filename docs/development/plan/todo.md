# Todo: GUI for wind resource assessment (RFC-005)

Resumed 2026-10-31 after RFC-007 shipped. Owner answers to RFC section 9 (SPEC, "Decisions for approval") come before slice 1 code.

## Slice 1: `feat/project-engine`
- [ ] `FileResult`; `_download_file` retries (atomic write and empty response done by RFC-007); tests
- [ ] `download_serial` / `download_multithread`: results, `workers`, `progress`, `cancel`; tests
- [ ] `globals`: `BARRA2_OUTPUT_FORMATS`, `Literal` aliases; `__all__` for `globals` and `mapping`; tests
- [ ] `project.py`: data classes, `Problem`, `ProjectError`, `project_from_dict`/`site_from_dict`, `load_project`, `validate`; tests
- [ ] `plan_site`; tests
- [ ] `run_site`: output (`write_csv`), run summary, `site_result_to_dict`, failed/partial/cancelled/cache-mismatch paths; tests
- [ ] Export in `__init__.py`; `test_package.py` boundary tests
- [ ] `scripts/example_project.toml`; example cell in the netCDF example (`.py` and `.ipynb`)
- [ ] Docs: how-to-use, `CONTEXT.md`, README, modules page; ADR-004
- [ ] Live tests; `make check`, `make test`, `make docs-test`; end-to-end run in a scratch folder
- [ ] PR

## Slice 1b: research (`docs/reanalysis-site-data-research`)
- [ ] Seven research tasks (SPEC); note in `docs/development/research/`; owner review; PR

## Slice 2: `feat/nearest-nodes`
- [ ] SPEC addendum; `mapping.nearest_nodes`; tests; PR

## Slice 2b: `feat/polygon-boundary` (beyond RFC-005; owner request)
- [ ] SPEC addendum; `mapping.Polygon`, file readers, node mask, `Site.polygon`, project-file key; tests; PR

## Slice 3: toolkit spikes and ADR
- [ ] SPEC addendum; five spikes (Streamlit, NiceGUI, Panel, Dash, Flet), tkinter on paper; ADR; PR

## Slice 4: `feat/gui-skeleton`
- [ ] SPEC addendum; `gui` extra, entry point, form, background run, smoke test; PR

## Slice 5: `feat/gui-map-import`
- [ ] SPEC addendum; map preview, optional node layer (site or area plus margin), mast-list, project and boundary-file import, polygon drawing, summary view; PR

## Slice 6: `docs/gui-user-guide`
- [ ] User docs, CSIRO link check, atl3b credit; PR

## Finish
- [ ] Archive plan; RFC-005 Done; roadmap; README
