# Plan: GUI for wind resource assessment (RFC-005)

Spec: [SPEC.md](SPEC.md). One PR per slice, each branched from an up-to-date `main`, each passing `make check`,
`make test` and `make docs-test`. Check a PR's state before pushing to its branch.

## Slice 1: engine (`feat/project-engine`)

Order, each step test-first:

1. `FileResult` and `_download_file` retries (atomic write and empty-response failure came with RFC-007). Tests with
   `requests.get` and `time.sleep` faked.
2. `download_serial` / `download_multithread`: results in input order, `workers`, `progress`, `cancel`. Replace the
   `cpu_count` test.
3. `project.py` data classes, `Problem`, `ProjectError`, `project_from_dict`/`site_from_dict`, `load_project`, public
   `validate` (all problems in one error); `BARRA2_OUTPUT_FORMATS`, `Literal` aliases, `__all__` for `globals` and
   `mapping`.
4. `plan_site`; `run_site`: URLs, download (netCDF4 default, csv for a point site with `download = "csv"`), versions,
   merge, output (`write_csv` or `write_df_csv`, with header), run summary,
   `site_result_to_dict`; failure, partial, cache-mismatch and cancel paths.
5. `__init__.py` export, `test_package.py` boundary tests, `scripts/example_project.toml`, example cell (`.py` and
   `.ipynb`).
6. Docs: how-to-use, `CONTEXT.md`, README, modules page, ADR-004.
7. Live tests, then full verification: `make check`, `make test`, `make docs-test`, live tests, end-to-end run in a
   scratch folder.

Risks: the fake server must return a valid NCSS netCDF for any variable (build from `tests/data/`); the cache of
other runs must not be mistaken for this site's files (filenames carry the site name as prefix, and `merge` filters
by pattern); the jupytext sync of the notebook must not reformat unrelated cells.

## Later slices (SPEC addendum before each)

1b. **Research** (`docs/reanalysis-site-data-research`): after slice 1 merges, a time-boxed note resolving the open
   design questions (SPEC, "Research to resolve them"): practice for masts and greenfield sites, averaging method,
   live NCSS node behaviour, point and node selection, file formats, mast conventions. Owner reviews it before the slice 2b addendum is written.
2. **Node lookup** (`feat/nearest-nodes`): `mapping.nearest_nodes(point, domain, n=4) -> list[GridNode]` from a
   bounding-box request of real nodes, never from arithmetic on an origin; a test pins that every returned node is a node
   of the grid. Choosing specific nodes for a point (a `nodes` selection) is reviewed here (SPEC, "Open design
   questions"). Decide then whether this finishes or deletes the unwired draft helpers (backlog).
2b. **Polygon boundary** (`feat/polygon-boundary`, added at the owner's request on 2026-10-30; goes beyond RFC-005,
   whose area is a rectangle): a `Polygon` type in `mapping` (bounding box, point-in-polygon, node mask); readers for
   standard files (GeoJSON and KML with the standard library; shapefile only if the owner approves a dependency such
   as `pyshp`); WGS84 only. An area download fetches the polygon's bounding box and keeps the nodes inside it.
   `Site` gains an optional `polygon` and the project file a `polygon = "farm.geojson"` key. Open, and reviewed
   with the owner before coding (SPEC, "Open design questions"): the default output for a boundary, an optional
   weighted site mean, the node inclusion rule, and polygons smaller than one grid cell.
3. **Toolkit spikes** (`docs/gui-toolkit-adr`): time-boxed Streamlit, NiceGUI, Panel, Dash (Plotly) and Flet builds of
   the same thin slice (RFC 5.2); an ADR records the choice. Spike code is throwaway and not merged. Drawing a polygon on the map is a spike criterion. The owner added
   Dash and Flet to the RFC's list on 2026-10-30; Flet also shows what freezing a desktop-native build would cost.
   tkinter stays the baseline and is judged on paper, not built. The RFC text is unchanged until the owner approves
   an edit.
4. **GUI skeleton** (`feat/gui-skeleton`): `gui` extra, `barra2-dl-gui` entry point, form to `Settings`/`Site`, background
   `run_site` with progress and cancel, display-free smoke test.
5. **Map, import, summary view** (`feat/gui-map-import`): node preview with distances, an optional node layer limited
   to the site or area plus a margin (nodes from the server, never a stored file), mast-list CSV and project-file
   import, boundary file import, polygon drawing on the map, run-summary view.
6. **User docs and credit** (`docs/gui-user-guide`): GUI guide, project-file reference, why AUS-11 is the default (confirm
   the CSIRO URL first), "raised by atl3b" in README, docs and release notes.

## Finish

Archive `SPEC.md`, `plan.md` and `todo.md` into `archive/2026-NN-gui/`, set RFC-005 to Done, update the roadmap and
README.
