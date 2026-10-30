# SPEC: wind variable table and wind frequencies

Requirement: [RFC-001](../../../requirements/wind-variables-bugfix-prd.md). Style and gates: [conventions.md](../../../conventions.md),
[constraints.md](../../../constraints.md).

## Decisions on RFC-001's open questions

The RFC's recommended options, taken as defaults while it is being built:

1. `BARRA2_WIND_VARS` stays a list of plain tuples `(ua, va, height_m)`.
2. `ua1500m`/`va1500m` are in the table but not in `BARRA2_VAR_WIND_DEFAULT`.
3. `BARRA2_URL_AUS11_1HR` and `BARRA2_URL_AUST04_1HR` stay for one release; passing one to
   `point_data_urlfilenames` raises a `DeprecationWarning`. The new generic template `BARRA2_URL` is passed in the same
   `barra2_url` argument with `domain=` and `freq=`, so the argument stays positional and only the pre-filled
   templates are deprecated.
4. `day` and `mon` are not added; that waits for RFC-002.

## Changes

### `globals.py`

- `BARRA2_WIND_VARS`: the 7 real pairs, heights as `int` metres.
- `BARRA2_VAR_ALIASES = {'ua10m': 'uas', 'va10m': 'vas'}`.
- `BARRA2_DOMAINS = {'AUS-11': 'BARRA-R2', 'AUST-04': 'BARRA-C2'}`.
- `BARRA2_FREQS`: `AUS-11` → `1hr`; `AUST-04` → `1hr`, `20min`; values are `timedelta` steps.
- `BARRA2_URL`: one template with `{domain}`, `{model}`, `{freq}` placeholders. The two old constants are derived
  from it.

### `download.py` — `point_data_urlfilenames`

- New keyword-only `domain='AUS-11'`, `freq='1hr'`. Unsupported combinations raise `ValueError` before any URL is
  built.
- A pre-filled template (no `{freq}` placeholder) raises a `DeprecationWarning`; the two known constants set
  `domain`/`freq` from themselves.
- Aliases resolve to server names; duplicates after resolving are dropped, order kept.
- `time_end` = month end − step.
- Filenames: `{prefix}_{domain}_{freq}_{var}_{start}_{end}.csv`.

### `convert.py` — `convert_wind_components`

- Exact match on the column base name (text before `[`).
- Output names from the height: `v{h}m[unit="m s-1"]`, `v{h}m_phi_met[unit="degrees"]`.
- `uas[...]`/`vas[...]` renamed to `ua10m[...]`/`va10m[...]` in the result.

## Acceptance

- Every test row in RFC-001 section 4.5 exists and passes offline, except the live test, which is opt-in
  (`BARRA2_LIVE=1`).
- The `ua300m` and `uas`/`vas` strict xfails are gone and their backlog rows removed.
- `make check` and `make test` pass.
