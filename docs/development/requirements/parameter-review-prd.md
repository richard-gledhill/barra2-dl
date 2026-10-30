Status: Done

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
`1hr`, AUST-04 `1hr` and AUST-04 `20min`. It left open whether to add `day`/`mon`; this RFC decides not to, and to
keep `1hr` and `20min` only (section 5.6). The owner's decisions on the open questions are in section 7.

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

At 20 minutes there is no `ps` or `hurs`, so density inputs aren't available at that frequency. barra2-dl raises an
error rather than filling the gap: it does not substitute `psl` and `huss`, download the hourly `ps`/`hurs`, or
interpolate them to 20 minutes (decision 4). Density work uses `1hr`.

### 4.3 Stability and boundary layer

| Variable | Meaning | Domains | 20min | Status |
|---|---|---|---|---|
| `zmla` | Boundary-layer height, m | Both | no | Propose |
| `hfss` | Surface sensible heat flux, W m-2 | Both | no | Propose (stability sign and strength) |
| `hfls` | Surface latent heat flux | Both | no | Optional |
| `ts` | Surface (skin) temperature | Both | yes | Optional (surface-air temperature difference) |
| `tauu`, `tauv` | Surface wind stress (friction velocity) | `3hr` only | no | No: `3hr` is not supported (decision 3) |
| `z0` | Roughness length | `day`/`mon` only | no | No: `day`/`mon` are not supported (decision 3) |

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
| `orog` | Model surface altitude, m | `fx` (fixed) | Automatic with every point download: report node altitude vs site altitude (decision 2) |
| `sftlf` | Land fraction, % | `fx` | On request only, through the `site` preset: flag coastal nodes that are partly sea (decision 2) |

`fx` files have no time axis and aren't split by month, so they don't fit `BARRA2_URL` or the per-month loop in
`point_data_urlfilenames`. They need their own small template and are fetched once per node. `BARRA2_FREQS` stays
for time series only. Section 5.7 covers how `orog` is fetched and stored.

### 4.6 Out of scope

Convective indices (`CAPE`, `CIN`, `BWD*`, `SRH*` …), soil and land-surface fields, top-of-atmosphere radiation,
radar and lightning fields. They can still be requested by name once the inventory exists (section 5.3).

## 5. Proposed design

### 5.1 Default frequency: 1 hour

`1hr` is the default setting throughout this design, as it already is for `point_data_urlfilenames` (`freq='1hr'`).
It's the only frequency every proposed parameter has on both domains, and it's what MCP and energy-yield work use.

- Presets, the inventory checks and the tests are defined against `1hr` first. A preset is valid only if all its
  variables exist at `1hr` on both domains.
- AUST-04 `20min` is the only other frequency, and it's opt-in: a user gets it only by passing `freq='20min'`.
  Nothing switches frequency automatically. `3hr`, `day` and `mon` aren't supported (5.6).
- The CLI and GUI start on `1hr` and show other frequencies only where `BARRA2_FREQS` lists them for the chosen
  domain.

### 5.2 Presets

All presets are defined at the `1hr` default. The last column shows what happens if a user opts in to AUST-04
`20min`.

| Preset | Variables | Use | At `1hr` (default) | At AUST-04 `20min` (opt-in) |
|---|---|---|---|---|
| `wind` | `uas`, `vas`, `ua/va` 50-250 m | Long-term reference | Yes, both domains | Yes |
| `wind+density` (**default preset**) | `wind` + `ps`, `tas`, `ta50m`…`ta250m`, `hurs` | Energy yield with density correction | Yes, both domains | No: `ps`, `hurs` missing, so it raises an error (decision 4) |
| `wind+stability` | `wind+density` + `zmla`, `hfss` | Shear/veer analysis | Yes, both domains | No |
| `extremes` | `sfcWindmax`, `wsgsmax` | Site suitability screening | Yes, both domains | Partly: `wsgsmax` only |
| `environment` | `pr`, `rsds`, `hurs`, `tas` | Icing, erosion, hybrid | Yes, both domains | Partly: `tas` only |
| `site` | `sftlf` | Coastal-node check (fixed field, on request) | n/a (`fx`) | n/a (`fx`) |

`orog` isn't in any preset because it's fetched automatically with every point download (5.7).

Presets are plain lists in `globals.py`, like `BARRA2_VAR_WIND_DEFAULT`. The CLI and GUI expose them by name.

- **Default preset.** `wind+density` is the default (decision 1). It replaces `BARRA2_VAR_WIND_DEFAULT` as the list
  the CLI, GUI and examples use when the user picks nothing. `BARRA2_VAR_WIND_DEFAULT` stays as it is for scripts
  that import it. Default downloads get larger: 20 variables instead of 9.
- **Missing variables raise an error.** Requesting a preset at an opt-in frequency where some of its variables don't
  exist raises an error. The error names the missing variables and says they are available at `1hr`. barra2-dl
  never quietly downloads part of the preset, substitutes other variables, takes them from `1hr` or interpolates
  (decision 4).
- **Default preset at 20 minutes.** Because the default preset needs `ps` and `hurs`, a 20-minute request that keeps
  the default preset fails with that error. The message should tell the user to choose `wind` for 20-minute data.

### 5.3 Variable inventory

Add `BARRA2_VARS: dict[tuple[str, str], frozenset[str]]`, keyed by `(domain, freq)` to match `BARRA2_FREQS`. Generate
it from the S3 listing with a small script in `scripts/` and check it in. Uses:

- `point_data_urlfilenames` resolves aliases (`BARRA2_VAR_ALIASES`) first, then checks every name against
  `BARRA2_VARS[(domain, freq)]`. Unknown names raise a `ValueError` naming the domain and frequency, before any
  request. Today an unknown name only produces one logged 404 per month. With `freq` left at its default, the check
  uses the `1hr` inventory.
- A live test (`BARRA2_LIVE=1`) re-lists S3 and fails if the checked-in inventory drifts.
- A test that every `(domain, freq)` in `BARRA2_FREQS` has an inventory entry, so adding a frequency forces the
  inventory to follow.

Also record per-variable metadata needed downstream: units, and the cell method, i.e. whether the value is
instantaneous (`time: point`), a mean or a maximum. RFC-003 needs this for time alignment (`pr`, `rsds` are hourly
means stamped at :30).

### 5.4 Pressure levels

Accept `ua<hPa>`/`va<hPa>` through the inventory, but keep them out of `BARRA2_WIND_VARS` and presets. RFC-001's
exact column matching already stops `ua200` pairing with `ua200m`. If they are ever converted, name the outputs
`v<hPa>hPa[...]` so they can't collide with heights.

### 5.5 Unit conversion

Adopt the useful conversions from the atl3b fork as an explicit, opt-in step: K → °C, Pa → hPa,
kg m-2 s-1 → mm h-1. Keep SI by default in netCDF; CSV for wind software may prefer °C and hPa.

### 5.6 Frequencies: `1hr` and `20min` only (deferred from RFC-001)

`BARRA2_FREQS` stays as RFC-001 shipped it: AUS-11 `1hr`, AUST-04 `1hr` and `20min`. `3hr`, `day` and `mon` aren't
added (decision 3), because they aren't useful in wind analysis:

- `3hr` has no height winds.
- `day` and `mon` wind components are time means. Wind speed computed from mean components is the speed of the mean
  wind vector, which understates the mean wind speed and so the resource.

The only parameters lost are `tauu`/`tauv` (`3hr`) and `z0` (`day`/`mon`), which are marked out of scope in 4.3.
A daily or monthly summary should be computed from `1hr` data instead. Since `day`/`mon` aren't supported,
`convert_wind_components` needs no guard against mean components.

### 5.7 Automatic node altitude (`orog`)

Every point download also fetches `orog` for the node, once per node and domain (decision 2):

- `point_data_urlfilenames` adds one `fx` request for `orog` alongside the monthly requests. Its cache file is
  `{prefix}_{domain}_fx_orog.csv`. Like other downloads it is skipped when the file already exists, and an HTTP
  failure is logged, not raised.
- `orog` is a single value, not a time series, so it isn't merged into the per-time frame. It's reported with the
  node coordinates: in the run summary now, and as a netCDF attribute in RFC-003.
- `sftlf` is fetched only when the user asks for the `site` preset.
- Before building, check that NCSS serves `fx` point requests in the same CSV form as time series. That hasn't been
  verified yet.

## 6. Testing

- `1hr` is the default frequency, and every preset except `site` is a subset of the `1hr` inventory on both domains.
- Unit tests that every preset is a subset of the inventory for each opt-in `(domain, freq)` it claims to support.
- A preset requested at an opt-in frequency that lacks some of its variables raises an error naming them and
  pointing to `1hr`.
- The default preset is `wind+density`.
- `wind+density` at AUST-04 `20min` raises an error naming `ps` and `hurs`, and downloads nothing.
- `point_data_urlfilenames` raises on an unknown variable, offline.
- Every `(domain, freq)` in `BARRA2_FREQS` has an inventory entry, and `BARRA2_FREQS` holds only `1hr` and `20min`.
- Every point download includes one `orog` request per node; `sftlf` appears only with the `site` preset.
- Live inventory drift test, and a live check that an `fx` point request returns `orog`.

## 7. Decisions

The owner settled the open questions on 2026-10-30:

1. **Default preset:** `wind+density` (5.2).
2. **Site fields:** `orog` is fetched automatically with every point download; `sftlf` only on request (4.5, 5.7).
3. **Frequencies:** keep `1hr` and `20min` only; `3hr`, `day` and `mon` aren't useful in wind analysis (5.6).
4. **20-minute density:** raise an error. Don't fill the gap from other variables, download from `1hr` or
   interpolate (4.2, 5.2).
