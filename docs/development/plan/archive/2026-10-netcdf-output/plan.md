# Plan: netCDF output, four-node averaging and area download

Builds [SPEC.md](SPEC.md). Two branches, two PRs, in order.

1. **`feat/netcdf-dataset`** (phases 1 and 2). Add `xarray`, `h5netcdf` and `h5py`; `merge.to_dataset` (csv bridge);
   `fileout_type='netcdf4'`; `merge_netcdf_to_dataset`; `resolve_variable_versions`; `tests/data/` fixtures and the
   script that rebuilds them; csv-vs-netCDF equality test; separate csv and netCDF examples; `docs/how-to-use.md`.
2. **`feat/node-averaging-area`** (phase 3). `BARRA2_GRID_SPACING`; `average4` and `area` URLs; bounding-box fixture;
   `node` dimension and hybrid averaging; `dataset_to_frames`; netCDF example update; live tests.

Each slice ends with `make check`, `make test`, live tests, an end-to-end run in a scratch folder, then the PR.
After slice 2, a docs PR archives this folder, sets RFC-003 to Done and updates the roadmap.
