# Todo: netCDF output

## Slice 1: `feat/netcdf-dataset` (phases 1 and 2)
- [x] Add `xarray`, `h5netcdf`, `h5py` to dependencies; `uv lock`; deptry DEP002 ignore (owner-approved)
- [x] `merge.to_dataset` and tests
- [x] `fileout_type='netcdf4'`, `resolve_variable_versions`
- [x] `merge_netcdf_to_dataset`, `read_fixed_fields` for `.nc`, `tests/data/` fixtures, equality test
- [x] Separate csv and netCDF examples, `docs/how-to-use.md`, README, `CONTEXT.md`
- [x] `make check`, `make test`, live tests, scratch end-to-end runs
- [ ] PR

## Slice 2: `feat/node-averaging-area` (phase 3)
- [ ] `BARRA2_GRID_SPACING`, `average4` and `area` downloads
- [ ] `node` dimension, hybrid averaging, `dataset_to_frames`
- [ ] Docs, netCDF example, live tests, `make check`, `make test`, PR

## Finish
- [ ] Archive plan, RFC-003 Done, roadmap status (docs PR)
