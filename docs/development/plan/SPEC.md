# SPEC: parameter presets, variable inventory and fixed fields

Requirement: [RFC-002](../requirements/parameter-review-prd.md). Style and gates: [conventions.md](../conventions.md),
[constraints.md](../constraints.md).

## Scope

RFC-002 section 5, with its decisions (section 7): `wind+density` is the default preset; `orog` comes with every
point download and `sftlf` only on request; `BARRA2_FREQS` stays at `1hr` and `20min`; missing 20-minute density
inputs raise an error.

Out of scope:
- Derived variables (density, shear, veer). The roadmap lists them as following from RFC-002, but RFC-002 doesn't
  design them.
- The run summary, where `orog` is reported. It's built in RFC-005. Until then `merge.read_fixed_fields` returns
  `orog` for scripts to use.
- netCDF attributes (RFC-003).

## Changes

### Inventory: `src/barra2_dl/data/barra2_variables.csv`

- One row per `(domain, freq, var)` that barra2-dl can download, covering every `(domain, freq)` in `BARRA2_FREQS`
  plus `fx`. Columns: `units`, `cell_methods`, `long_name`.
- Generated from the THREDDS catalogue and OPeNDAP attributes by `scripts/build_barra2_inventory.py`.
- `globals.py` loads it at import into:
  - `BARRA2_VARS: dict[tuple[str, str], frozenset[str]]`;
  - `BARRA2_VAR_INFO: dict[tuple[str, str, str], dict[str, str]]`.

### `globals.py`

- `BARRA2_PRESETS`: `wind`, `wind+density`, `wind+stability`, `extremes`, `environment`, `site`, as in RFC-002 5.2.
- `BARRA2_PRESET_DEFAULT = 'wind+density'`.
- `BARRA2_FIXED_VARS_AUTO = ['orog']`: fixed fields added to every point download.
- `BARRA2_URL_FX`: a template for `fx` files, which have no time range and no month in the name.
- `BARRA2_VAR_WIND_DEFAULT` is unchanged, for scripts that import it.

### `download.py`

- `preset_variables(preset, domain='AUS-11', freq='1hr') -> list[str]`, public. It returns the preset's variables,
  or raises `ValueError` naming any that are missing at that domain and frequency. The message says they're
  available at `1hr`, and suggests `wind` when the preset is a density preset at `20min`.
- `point_data_urlfilenames`:
  - **Validation.** After resolving aliases, every variable is checked against `BARRA2_VARS[(domain, freq)]` and the
    `fx` set. Unknown names raise `ValueError` before any URL is built, naming the domain and frequency, and noting
    when the name exists at `1hr`.
  - **Fixed fields.** `fx` variables (`orog`, `sftlf`) get one request each instead of one per month, using
    `BARRA2_URL_FX`, cached as `{prefix}_{domain}_fx_{var}.csv`.
  - **Automatic `orog`.** It's added once whenever at least one variable is requested.

### `merge.py`

- `merge_csvs_to_df` skips fixed-field files (`_fx_` in the name), so a loose pattern such as `prefix*.csv` doesn't
  add a 1970 row, and logs that it skipped them.
- `read_fixed_fields(filein_folder, filename_pattern='*_fx_*.csv') -> dict[str, float]`, public. It returns
  `{'orog[unit="m"]': 33.05, ...}` from the fixed-field files.

### `convert.py`

- `convert_units(df) -> DataFrame`, public and opt-in. It converts K → °C, Pa → hPa and kg m-2 s-1 → mm h-1 on
  columns whose unit suffix matches, renaming the suffix, e.g. `tas[unit="K"]` → `tas[unit="degC"]`. Other columns
  are left as they are, and the input isn't modified.

## Acceptance

- Every test in RFC-002 section 6 exists. The live ones (inventory drift, `fx` `orog` request) are opt-in with
  `BARRA2_LIVE=1`.
- README, `CONTEXT.md`, the example script and the notebook use the default preset and show `orog`.
- `make check` and `make test` pass; the live tests pass with `BARRA2_LIVE=1`.
