Status: Draft

# RFC-002: Review supported BARRA2 parameters against wind energy assessment needs

| | |
|---|---|
| Depends on | [RFC-001 wind variable fix](wind-variables-bugfix-prd.md) (Done, shipped in #128) |
| Next | RFC-003 netCDF output |
| Drafted | 2026-10-28, updated 2026-10-30 after RFC-001 shipped |

## 1. Summary

barra2-dl supports height winds plus `ta50m`, and treats everything else as "pass a variable name and hope". A wind
energy assessment needs more: air density inputs (pressure, temperature, humidity), stability and shear indicators,
gusts, and some site context. This RFC maps what a wind energy assessment uses against what BARRA2 publishes for each
domain and frequency, proposes which parameters to support, groups them into presets, and adds a checked variable
inventory so a bad name fails before any download.

RFC-001 made domain and frequency parameters (`BARRA2_DOMAINS`, `BARRA2_FREQS`, `BARRA2_URL`) and supports AUS-11
`1hr`, AUST-04 `1hr` and AUST-04 `20min`. It left two questions here: whether to add `day`/`mon`, and how to treat
their time-averaged wind components (section 5.5).

## 2. Sources

- NCI [BARRA2 Parameter Descriptions](https://opus.nci.org.au/spaces/NDP/pages/338002591/BARRA2+Parameter+Descriptions)
  and [BARRA2 FAQ](https://opus.nci.org.au/pages/viewpage.action?pageId=264241306): names, units, frequencies,
  definitions.
- Listing of `s3://bom-opendata-climate/BARRA2/` on 2026-10-28: 129 variables at AUS-11 `1hr`, 209 at AUST-04 `1hr`
  and 34 at AUST-04 `20min`.

## 3. What a wind energy assessment needs

| Need | Used for | Typical source |
|---|---|---|
| Wind speed and direction at several heights | Long-term reference for MCP; shear; wind rose | Mast/lidar + reanalysis |
| Air density at hub height | Power-curve density adjustment (IEC 61400-12-1); energy yield | Pressure, temperature, humidity |
| Temperature at height | Density; stability (lapse rate); low/high temperature shutdowns | Mast thermometers, reanalysis |
| Stability indicators | Explain shear and veer; diurnal behaviour; power-curve performance | Lapse rate, heat flux, boundary-layer height |
| Gusts and maximum winds | Extreme wind (site suitability, IEC class), high-wind hysteresis losses | Reanalysis gust diagnostics (with known underestimation) |
| Icing indicators | Icing loss and downtime | Temperature, humidity, cloud, precipitation |
| Precipitation | Blade leading-edge erosion, access/construction | Reanalysis |
| Solar radiation | Wind-solar hybrid projects (common in Australia) | Reanalysis GHI/DNI |
| Terrain and land cover at the node | Judging how representative a node is for the site | Static fields |

Turbulence intensity and 10-minute statistics are central to wind assessment but **not available**. BARRA2 is
hourly, plus 20-minute output for 34 AUST-04 fields, and has no TI. Document this limit.

## 4. Inventory review

Status key:
- **Now**: listed in `globals.py` today.
- **Propose**: add to a preset.
- **Optional**: allowed and documented, but not in any preset.
- **No**: out of scope.

"Both" means AUS-11 and AUST-04 at `1hr`. The **20min** column says whether AUST-04 `20min` has the variable.

### 4.1 Wind

| Variable | Meaning | Domains | 20min | Status |
|---|---|---|---|---|
| `uas`, `vas` | 10 m wind components; requested as `ua10m`/`va10m` too, and named so in converted output (RFC-001) | Both | yes | Now |
| `ua50m`…`ua250m`, `va50m`…`va250m` | Wind components at 50, 100, 150, 200, 250 m | Both | yes | Now |
| `ua1500m`, `va1500m` | 1500 m wind components | Both | yes | Now in the table, not in the default list (RFC-001) |
| `sfcWind` | 10 m wind speed (timestep mean) | Both | no | Optional (duplicates `uas`/`vas`) |
| `sfcWindmax` | Hourly max 10 m wind speed | Both | no | Propose (extremes) |
| `wsgsmax` | Hourly max 3 s gust | Both | yes | Propose (extremes) |
| `wsgs` | Gust | AUST-04 only | no | Optional |
| `uasmax`, `vasmax`, `uasmean`, `vasmean` | Max/mean 10 m components | `max` AUS-11 only; `mean` both | no | Optional |
| `ua850`, `ua925`, `ua1000` … | Pressure-level winds (hPa) | Both | no | Optional; separate family. The lower levels can be below ground at elevated sites. |

### 4.2 Temperature and air density

| Variable | Meaning | Domains | 20min | Status |
|---|---|---|---|---|
| `tas` | Near-surface (1.5 m) air temperature, K | Both | yes | Propose |
| `ta50m`, `ta100m`, `ta150m`, `ta200m`, `ta250m` | Air temperature at height, K | Both | yes | `ta50m` now; propose all (hub-height density, lapse rate) |
| `ta1500m` | 1500 m temperature | Both | yes | Optional |
| `ps` | Surface air pressure, Pa | Both | **no** | Propose (density) |
| `psl` | Sea-level pressure, Pa | Both | yes | Optional (not for density at site without `orog`) |
| `hurs` | 1.5 m relative humidity, % | Both | **no** | Propose (density humidity correction, icing) |
| `huss` | 1.5 m specific humidity | Both | yes | Optional (alternative to `hurs`) |
| `tasmax`, `tasmin`, `tasmean` | Hourly max/min/mean of `tas` | Both | no | Optional (temperature shutdown analysis) |

Pressure at height isn't published. Derive it from `ps`, `orog` and the temperature profile (hypsometric equation)
when density is calculated (roadmap, derived variables).

At 20 minutes there is no `ps` or `hurs`. Density needs either `psl` reduced to the node altitude with `orog`, plus
`huss`, or the hourly `ps`/`hurs` interpolated to 20 minutes. Open question 4.

### 4.3 Stability and boundary layer

| Variable | Meaning | Domains | 20min | Status |
|---|---|---|---|---|
| `zmla` | Boundary-layer height, m | Both | no | Propose |
| `hfss` | Surface sensible heat flux, W m-2 | Both | no | Propose (stability sign and strength) |
| `hfls` | Surface latent heat flux | Both | no | Optional |
| `ts` | Surface (skin) temperature | Both | yes | Optional (surface-air temperature difference) |
| `tauu`, `tauv` | Surface wind stress (friction velocity) | `3hr` only | no | Optional; needs a `3hr` entry in `BARRA2_FREQS` |
| `z0` | Roughness length | `day`/`mon` only | no | Optional; needs a `day`/`mon` entry in `BARRA2_FREQS` |

Lapse rates between `ta50m`…`ta250m` give a simple stability class at the download's own frequency without new
downloads.

### 4.4 Icing, precipitation and solar

| Variable | Meaning | Domains | 20min | Status |
|---|---|---|---|---|
| `pr` | Precipitation, kg m-2 s-1 (hourly mean) | Both | no (`prra`, `prsn` only) | Propose (erosion, icing) |
| `prsn` | Snowfall | Both | yes | Optional |
| `clt`, `cll` | Total and low cloud cover | Both | `clt` only | Optional (icing screening) |
| `twiso` | Wet-bulb temperature | Both | no | Optional |
| `visibility`, `fogfraction` | Visibility, fog | AUST-04 only | no | Optional |
| `rsds` | Surface downwelling shortwave (GHI estimate) | Both | no (`rsdsdir`, `rsdsdif`, `rss`) | Propose (hybrid projects) |
| `rsdsdir` | Direct shortwave (DNI = `rsdsdir` / cos zenith) | Both | yes | Optional |

### 4.5 Static site fields

| Variable | Meaning | Frequency | Status |
|---|---|---|---|
| `orog` | Model surface altitude, m | `fx` (fixed) | Propose: report node altitude vs site altitude |
| `sftlf` | Land fraction, % | `fx` | Propose: flag coastal nodes that are partly sea |

`fx` files have no time axis and aren't split by month, so they don't fit `BARRA2_URL` or the per-month loop in
`point_data_urlfilenames`. They need their own small template and are fetched once per node. `BARRA2_FREQS` stays
for time series only.

### 4.6 Out of scope

Convective indices (`CAPE`, `CIN`, `BWD*`, `SRH*` …), soil and land-surface fields, top-of-atmosphere radiation,
radar and lightning fields. They can still be requested by name once the inventory exists (section 5.2).

## 5. Proposed design

### 5.1 Presets

| Preset | Variables | Use | AUST-04 `20min` |
|---|---|---|---|
| `wind` (default) | `uas`, `vas`, `ua/va` 50-250 m | Long-term reference | Yes |
| `wind+density` | `wind` + `ps`, `tas`, `ta50m`…`ta250m`, `hurs` | Energy yield with density correction | No: `ps`, `hurs` missing (open question 4) |
| `wind+stability` | `wind+density` + `zmla`, `hfss` | Shear/veer analysis | No |
| `extremes` | `sfcWindmax`, `wsgsmax` | Site suitability screening | Partly: `wsgsmax` only |
| `environment` | `pr`, `rsds`, `hurs`, `tas` | Icing, erosion, hybrid | Partly: `tas` only |
| `site` | `orog`, `sftlf` | Node representativeness (fixed fields) | n/a (`fx`) |

Presets are plain lists in `globals.py`, like `BARRA2_VAR_WIND_DEFAULT`. The CLI and GUI expose them by name.
Requesting a preset at a frequency where some of its variables don't exist raises an error that names the missing
variables. It never quietly downloads part of the preset.

### 5.2 Variable inventory

Add `BARRA2_VARS: dict[tuple[str, str], frozenset[str]]`, keyed by `(domain, freq)` to match `BARRA2_FREQS`. Generate
it from the S3 listing with a small script in `scripts/` and check it in. Uses:

- `point_data_urlfilenames` resolves aliases (`BARRA2_VAR_ALIASES`) first, then checks every name against
  `BARRA2_VARS[(domain, freq)]`. Unknown names raise a `ValueError` naming the domain and frequency, before any
  request. Today an unknown name only produces one logged 404 per month.
- A live test (`BARRA2_LIVE=1`) re-lists S3 and fails if the checked-in inventory drifts.
- A test that every `(domain, freq)` in `BARRA2_FREQS` has an inventory entry, so adding a frequency forces the
  inventory to follow.

Also record per-variable metadata needed downstream: units, and the cell method, i.e. whether the value is
instantaneous (`time: point`), a mean or a maximum. RFC-003 needs this for time alignment (`pr`, `rsds` are hourly
means stamped at :30) and section 5.5 needs it for wind.

### 5.3 Pressure levels

Accept `ua<hPa>`/`va<hPa>` through the inventory, but keep them out of `BARRA2_WIND_VARS` and presets. RFC-001's
exact column matching already stops `ua200` pairing with `ua200m`. If they are ever converted, name the outputs
`v<hPa>hPa[...]` so they can't collide with heights.

### 5.4 Unit conversion

Adopt the useful conversions from the atl3b fork as an explicit, opt-in step: K → °C, Pa → hPa,
kg m-2 s-1 → mm h-1. Keep SI by default in netCDF; CSV for wind software may prefer °C and hPa.

### 5.5 Daily and monthly frequencies (deferred from RFC-001)

The `day` and `mon` folders have the same height wind names as `1hr`, but each value is a time mean of the
component. Wind speed computed from mean components is the speed of the mean wind vector. It is always at most the
mean of the hourly speeds, and much lower when the direction varies. A daily or monthly `v<h>m` would therefore
understate the wind resource.

Recommendation:
- Add `day` and `mon` to `BARRA2_FREQS` for both domains, so non-wind parameters (`tas`, `ps`, `pr`, `z0` …) can be
  fetched for climate summaries.
- `convert_wind_components` refuses mean components: it checks the cell method recorded in 5.2 and raises an error
  that says to use `1hr` data and average the speeds instead.
- For a daily or monthly mean wind speed, document `sfcWind` (10 m, a true mean speed) and recommend averaging
  hourly `v<h>m` for other heights.

## 6. Testing

- Unit tests that every preset is a subset of the inventory for each `(domain, freq)` it claims to support.
- A preset requested at an unsupported frequency raises an error naming the missing variables.
- `point_data_urlfilenames` raises on an unknown variable, offline.
- Every `(domain, freq)` in `BARRA2_FREQS` has an inventory entry.
- `convert_wind_components` refuses `day`/`mon` mean components.
- Live inventory drift test.

## 7. Open questions

1. Which presets do your users need on day one? `wind+density` is the strongest candidate for the default.
2. Fetch `orog`/`sftlf` automatically with every point download, or only on request?
3. Add `3hr`, `day` and `mon` to `BARRA2_FREQS` now (recommended for `day`/`mon`, with the wind guard in 5.5), or
   keep to `1hr` and `20min`?
4. For 20-minute density, which approach: `psl` reduced with `orog` plus `huss` (all 20-minute), or the hourly `ps`
   and `hurs` interpolated to 20 minutes?
