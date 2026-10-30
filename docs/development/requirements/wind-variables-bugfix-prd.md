Status: Done

# RFC-001: Fix the BARRA2 wind variable table and support all wind frequencies

| | |
|---|---|
| Backlog | Known bugs: "`ua300m` unit typo" and "`uas`/`vas` output name" in [backlog.md](../backlog.md) |
| Next | [RFC-002 parameter review](parameter-review-prd.md) |
| Drafted | 2026-10-28 |

## 1. Summary

`BARRA2_WIND_VARS` in `globals.py` lists 18 `(ua, va, height)` pairs. Only 7 exist on the server. The other 11 are
placeholders that return HTTP 404 when downloaded, and one of them carries a wrong height. `convert.py` matches
column names by substring and derives the output name by slicing the variable name, which causes the
`vs[unit="m s-1"]` bug and will break as soon as pressure-level winds are added. This RFC trims the table to real
variables, gives each pair an explicit numeric height, and makes the column matching exact. `ua10m`/`va10m` are
kept as user-facing aliases for `uas`/`vas`: they download `uas`/`vas`, and the conversion step renames the 10 m
columns to `ua10m`/`va10m` so every height follows one `ua<N>m` pattern in the output that third-party software
imports.

The download side also assumes 1-hourly data: the URL constants hard-code `1hr`, the month end is computed as
"last day, 23:00", and cache filenames carry neither domain nor frequency. AUST-04 (BARRA-C2) also publishes the same
height winds every 20 minutes. This RFC makes domain and frequency parameters, with 1-hourly as the default rather
than a built-in limit.

It's first in the [roadmap](wind-engineering-roadmap-prd.md) because every later RFC builds on a correct variable list.

## 2. Evidence

### 2.1 What the server has

Height-above-ground winds, from the NCI parameter descriptions
([BARRA2 Parameter Descriptions](https://opus.nci.org.au/spaces/NDP/pages/338002591/BARRA2+Parameter+Descriptions),
[BARRA2 FAQ](https://opus.nci.org.au/pages/viewpage.action?pageId=264241306)) and a listing of the AWS mirror
`s3://bom-opendata-climate/BARRA2/` on 2026-10-28:

| Height | Variables | AUS-11 (BARRA-R2) | AUST-04 (BARRA-C2) |
|---|---|---|---|
| 10 m | `uas`, `vas` | yes | yes |
| 50 m | `ua50m`, `va50m` | yes | yes |
| 100 m | `ua100m`, `va100m` | yes | yes |
| 150 m | `ua150m`, `va150m` | yes | yes |
| 200 m | `ua200m`, `va200m` | yes | yes |
| 250 m | `ua250m`, `va250m` | yes | yes |
| 1500 m | `ua1500m`, `va1500m` | yes | yes |

NCI describes `uas`/`vas` as "the wind at 10 metre above the surface". There is **no `ua10m`/`va10m`**: it isn't in
either NCI page or any S3 listing, and a live request returns 404. On the server the 10 m pair is `uas`/`vas`
only, so barra2-dl treats `ua10m`/`va10m` as its own aliases (section 4.3), never as server names.

Separately, `ua200`, `ua850`, `ua1000` etc. (no `m`) are **pressure-level** winds in hPa, not heights. They exist,
but they are a different kind of variable (RFC-002, section 5.3).

### 2.2 Domains and frequencies

From the THREDDS catalogue
([AUST-04 BARRA-C2 v1](https://thredds.nci.org.au/thredds/catalog/ob53/output/reanalysis/AUST-04/BOM/ERA5/historical/hres/BARRA-C2/v1/catalog.html))
and the S3 listing:

| Domain (model) | Frequencies published | With height winds | Notes |
|---|---|---|---|
| AUS-11 (BARRA-R2) | `1hr`, `3hr`, `day`, `mon`, `fx` | `1hr`, `day`, `mon` | 129 variables at `1hr`. |
| AUST-04 (BARRA-C2) | `1hr`, `20min`, `3hr`, `day`, `mon`, `fx` | `1hr`, `20min`, `day`, `mon` | 209 variables at `1hr`, 34 at `20min`. |
| AUST-11 (BARRA-R2 convective subset) | `1hr`, `day`, `mon`, `fx` | none | Convective parameters only; not relevant here. |

Wherever height winds exist, the **names are the same**: the 14 variables in 2.1. So the wind table doesn't need a
copy per frequency. What varies by domain and frequency is the URL path, the time step and which other variables
are present.

The AUST-04 `20min` folder holds the winds above plus `tas`, `ta50m`…`ta1500m`, `huss`, `psl`, `wsgsmax`, `ts`,
`clt`, precipitation and radiation fields, but not `ps` or `hurs`. Files are one per variable-month, named
`ua50m_AUST-04_ERA5_historical_hres_BOM_BARRA-C2_v1_20min_202001-202001.nc`. A live NCSS point request for that file
returned HTTP 200 with steps at 00:00, 00:20, 00:40, 01:00 …

### 2.3 What the table lists

| Entry in `BARRA2_WIND_VARS` | Status |
|---|---|
| `uas`, `ua50m`, `ua100m`, `ua150m`, `ua200m`, `ua250m` | Real |
| `ua10m` | Not a server variable (404). Becomes an alias for `uas` (section 4.3). |
| `ua20m`, `ua30m`, `ua70m`, `ua300m`, `ua400m`, `ua500m`, `ua600m`, `ua700m`, `ua850m`, `ua925m`, `ua1000m` | Placeholders, 404. The 400-1000 entries look like pressure levels mistaken for heights. |
| `ua300m` | Also has the height string `30m[...]` (pinned by a strict xfail). |
| `ua1500m` | Missing. |

### 2.4 Code defects

1. **Output name sliced from the variable name.** `convert_wind_components` builds the column from `tup[0][2:]`, so
   `uas` becomes `vs[unit="m s-1"]` rather than `v10m[...]` (pinned by
   `test_convert_wind_components_surface_wind_column_name`). The third tuple field, meant to carry the height, isn't
   used.
2. **Substring column matching.** `df.columns.str.contains(tup[0])` matches any column containing the text, and the
   code then takes the first match (`iloc[:, 0]`). Today this mis-pairs `uas` with `uasmax[...]` or `uasmean[...]`
   if a user downloads those. Once pressure levels are allowed, `ua200` matches `ua200m[...]` as well.
3. **No check that a variable exists.** A misspelt or placeholder variable creates one 404 per month, logged but not
   summarised.
4. **Frequency is hard-coded.** The only URL constants are `BARRA2_URL_AUS11_1HR` and `BARRA2_URL_AUST04_1HR`.
   There is no way to request AUST-04 20-minute data without writing a URL template by hand.
5. **Month end assumes an hourly step.** `point_data_urlfilenames` sets `time_end` to the month end minus one hour.
   With a hand-written 20-minute template, every month would lose its 23:20 and 23:40 values.
6. **Cache filenames collide.** Filenames are `{prefix}_{var}_{start}_{end}.csv`, with no domain or frequency. If
   AUS-11 and AUST-04 runs, or 1-hourly and 20-minute runs, share a cache folder and prefix, the second run finds
   the first run's file and skips it as "already downloaded", silently returning the wrong data.

## 3. Goals and non-goals

**Goals**
- G1. `BARRA2_WIND_VARS` lists only height-wind pairs that BARRA2 publishes. Because the names are the same on every
  domain and frequency that has height winds, one table serves all of them. Which domain/frequency combinations are
  supported is a separate table (section 4.2). 1-hourly is the default, not a constraint: AUST-04 20-minute data
  works through the same functions, and further frequencies are a table entry rather than new code.
- G2. Each entry has a numeric height in metres; output names come from it (`v10m`, `v50m` …, `v1500m`).
- G2a. `ua10m`/`va10m` are accepted as aliases for `uas`/`vas` when downloading, and the converted output names the
  10 m components `ua10m`/`va10m`, so all heights share the `ua<N>m`/`va<N>m` pattern.
- G3. Columns are matched exactly on the variable name before `[unit=...]`.
- G4. A live test fails if any listed variable stops being served on any supported domain/frequency.
- G5. Remove the two backlog rows and their strict xfails.
- G6. The time range of each monthly request ends at the last time step of that frequency, and cache filenames
  include domain and frequency so different runs can't overwrite or masquerade as each other.

**Non-goals**
- Adding new variable families (temperature, pressure, humidity, pressure-level wind). That is RFC-002.
- Validating arbitrary user-supplied variable names against the full inventory (RFC-002).
- `day` and `mon` frequencies. Their wind components are time means, and speed computed from mean components
  understates the mean speed, so whether and how to offer them is an RFC-002 decision. The design below takes them
  as table entries if accepted.
- Resampling 20-minute data to hourly or the reverse.

## 4. Proposed change

### 4.1 Wind table

```python
# (ua, va, height in metres above ground), by server name. The same names on every domain and frequency with
# height winds. uas/vas are the 10 m winds; ua10m/va10m are barra2-dl aliases for them (BARRA2_VAR_ALIASES).
BARRA2_WIND_VARS = [
    ('uas', 'vas', 10),
    ('ua50m', 'va50m', 50),
    ('ua100m', 'va100m', 100),
    ('ua150m', 'va150m', 150),
    ('ua200m', 'va200m', 200),
    ('ua250m', 'va250m', 250),
    ('ua1500m', 'va1500m', 1500),
]
```

A plain tuple keeps the change small. A `NamedTuple` (`WindPair(ua, va, height_m)`) reads better at call sites and
is the alternative (open question 1).

`BARRA2_VAR_WIND_DEFAULT` already uses only real variables and doesn't change.

### 4.2 Domains, frequencies and one URL template

Replace the two hard-coded URL constants with one template plus two small tables:

```python
# BARRA2 domain -> model that produced it.
BARRA2_DOMAINS = {'AUS-11': 'BARRA-R2', 'AUST-04': 'BARRA-C2'}

# Frequencies barra2-dl downloads for each domain, with their time step. 1hr is the default.
BARRA2_FREQS = {
    'AUS-11': {'1hr': timedelta(hours=1)},
    'AUST-04': {'1hr': timedelta(hours=1), '20min': timedelta(minutes=20)},
}

BARRA2_URL = (
    'https://thredds.nci.org.au/thredds/ncss/grid/ob53/output/reanalysis/{domain}/BOM/ERA5'
    '/historical/hres/{model}/v1/{freq}/{var}/latest/'
    '{var}_{domain}_ERA5_historical_hres_BOM_{model}_v1_{freq}_{year}{month:02d}-{year}{month:02d}.nc'
    '?var={var}&latitude={latitude}&longitude={longitude}'
    '&time_start={time_start_str}&time_end={time_end_str}'
    '&timeStride=&vertCoord=&accept={fileout_type}'
)
```

`point_data_urlfilenames` takes `domain='AUS-11'` and `freq='1hr'` as keyword arguments:

- An unsupported combination (e.g. `AUS-11`, `20min`) raises `ValueError` listing what is supported, before any
  request.
- `time_end` is the month end minus that frequency's step: 23:00 for `1hr`, 23:40 for `20min`.
- Filenames become `{prefix}_{domain}_{freq}_{var}_{start}_{end}.csv`, e.g.
  `site_AUST-04_20min_ua50m_20200101_20200131.csv`.

`BARRA2_URL_AUS11_1HR` and `BARRA2_URL_AUST04_1HR` are used by the README, the example script and tests. They stay
for one release, built from `BARRA2_URL` with the domain and frequency filled in, and passing `barra2_url` logs a
deprecation warning (open question 3).

Adding a frequency or domain later (`day`, `mon`, or a new BARRA2 domain) means adding a `BARRA2_FREQS` entry and a
live-test case, not new code.

### 4.3 `ua10m`/`va10m` aliases

Third-party wind software (Windographer, WindPRO, openWind) maps columns by a height in the name. `uas` carries
no height, so a 10 m column would need mapping by hand. barra2-dl keeps the server's names in the cache and uses
the height-named form in its converted output.

```python
# barra2-dl alias -> BARRA2 server variable. The server has no ua10m/va10m.
BARRA2_VAR_ALIASES = {'ua10m': 'uas', 'va10m': 'vas'}
```

| Stage | Behaviour |
|---|---|
| Request | `point_data_urlfilenames` accepts `ua10m`/`va10m` and resolves them to `uas`/`vas` for the URL and the cache filename. Asking for both `uas` and `ua10m` downloads one file, not two. |
| Cache | Holds `uas`/`vas` files exactly as served (raw data is never renamed; ADR-002 resume still works). |
| Merge | `merge_csvs_to_df` returns server names (`uas[unit="m s-1"]`), unchanged. |
| Convert | `convert_wind_components` renames `uas[...]`/`vas[...]` to `ua10m[...]`/`va10m[...]` and adds `v10m[...]` and `v10m_phi_met[...]`. |

The rename belongs to the conversion step because that's the step whose output is meant for import into other
tools; anyone who wants raw server names reads the merge output. The table entry stays `('uas', 'vas', 10)`, since
that's what the server and merged frame contain.

### 4.4 `convert_wind_components`

- Build a map from each column's base name (text before `[`) to the column.
- For each pair, use `cols.get(ua)` and `cols.get(va)`. Convert only when both are present.
- Name outputs `f'v{height}m[unit="m s-1"]'` and `f'v{height}m_phi_met[unit="degrees"]'`.
- Rename the 10 m components through `BARRA2_VAR_ALIASES` (section 4.3), keeping the `[unit=...]` suffix.
- Behaviour for the existing heights 50-250 m is unchanged; `uas`/`vas` now give `ua10m`, `va10m`, `v10m` and
  `v10m_phi_met` columns.
- Nothing here depends on the time step, so 20-minute frames convert the same way.

### 4.5 Tests

| Test | Change |
|---|---|
| `test_wind_vars_pairs_are_consistent` | Assert the height is an `int` and, for `ua*m`, equals the number in the name; drop the `ua300m` xfail param (the entry is gone). |
| `test_convert_wind_components_surface_wind_column_name` | Remove the strict xfail; it now passes. |
| URL constant tests in `test_globals.py` and `test_download.py` | Parametrise over every `(domain, freq)` in `BARRA2_FREQS`; keep the old constants' tests until they're removed. |
| New: exact matching | A frame with `uas`, `uasmax` and `vas` converts `uas`/`vas` only; a frame with `ua200` and `ua200m` doesn't cross-match. |
| New: 1500 m | `ua1500m`/`va1500m` produce `v1500m` columns. |
| New: alias request | `point_data_urlfilenames(['ua10m', 'va10m'])` builds `uas`/`vas` URLs and filenames; `['uas', 'ua10m']` yields one URL per month. |
| New: alias output | Converting a frame with `uas[...]`/`vas[...]` yields `ua10m[...]`, `va10m[...]`, `v10m[...]`, `v10m_phi_met[...]` and no `uas`/`vas` columns. |
| New: 20-minute URL | `domain='AUST-04', freq='20min'` builds the URL verified in 2.2, with `time_end` on the month's last day at 23:40. |
| New: unsupported combination | `domain='AUS-11', freq='20min'` raises `ValueError`. |
| New: filenames | The same variable and period give different filenames for AUS-11/1hr, AUST-04/1hr and AUST-04/20min. |
| New: deprecated constants | Passing `BARRA2_URL_AUS11_1HR` still works, gives the same URLs as `domain='AUS-11'`, and logs a deprecation warning. |
| New live test (`BARRA2_LIVE=1`) | Every variable in `BARRA2_WIND_VARS` and the default lists returns HTTP 200 for one month on every `(domain, freq)` in `BARRA2_FREQS`; the 20-minute response has three steps per hour. |

### 4.6 Docs

- Remove both backlog rows.
- `CONTEXT.md`: add that `uas`/`vas` are the 10 m wind on the server, that `ua10m`/`va10m` are barra2-dl's aliases
  for them in converted output, and that `ua<N>` without `m` is a pressure level. Add a **Frequency** term (`1hr`,
  `20min` …, the BARRA2 folder name) and note that AUST-04 has 20-minute data.
- README and `scripts/example_barra2_dl.py`: switch to `domain=`/`freq=` and show a 20-minute AUST-04 example.
- MkDocs user docs: a table of available heights per domain and frequency.
- `CHANGELOG.md`: note the breaking changes below.

## 5. Compatibility and risks

1. **Output column rename (breaking).** Anyone who downloaded `uas`/`vas` and read `vs[unit="m s-1"]` will now get
   `v10m[unit="m s-1"]`, and the converted output's `uas[...]`/`vas[...]` columns become `ua10m[...]`/`va10m[...]`.
   This is the fix the backlog asks for. Release as 0.4.0 with a changelog note. The merge output keeps server names.
2. **Table shape (breaking for direct users).** The third field changes from a string fragment to an `int`. It's
   exported from `globals.py` and nothing in the package used it.
3. **Removed names.** Scripts that listed `ua20m` etc. got only 404s, so removing them changes no data. Scripts
   that listed `ua10m`/`va10m` start getting 10 m data through the alias.
4. **Cache filenames change.** Existing caches use the old names, so the first run after upgrading downloads again
   rather than resuming. It's one-off, and it is what fixes the collision in 2.4 item 6. Merge patterns such as
   `f'{prefix}*.csv'` still match; a user mixing frequencies in one folder should narrow the pattern to
   `f'{prefix}_AUST-04_20min_*.csv'`.
5. **URL constants.** Kept, with a deprecation warning, for one release (open question 3).
6. **Data volume.** A 20-minute series is three times the rows and requests per variable-month of an hourly one.
   The time per request is similar; the docs should say so.
7. **Pressure levels.** Kept out of `BARRA2_WIND_VARS` on purpose; mixing heights in metres with pressures in hPa
   in one table would repeat the original mistake.

## 6. Open questions

1. Plain tuple or a `WindPair` `NamedTuple`?
2. Include `ua1500m` in the table (recommended: it's real and cheap) but leave it out of the default list, as it's
   above any rotor?
3. Keep `BARRA2_URL_AUS11_1HR` / `BARRA2_URL_AUST04_1HR` and the `barra2_url` argument for one release with a
   deprecation warning (recommended, since the README and example use them), or remove them now while the package
   is still alpha?
4. Should `day` and `mon` be added to `BARRA2_FREQS` here, or wait for RFC-002 to decide how mean wind components
   are handled?
