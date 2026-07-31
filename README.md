# BARRA2 Data Downloader (Fork)

Fork of [akarich73/barra2-dl](https://github.com/akarich73/barra2-dl) with a Windows GUI and custom modifications.

## Features

- Windows desktop GUI (tkinter) for coordinate input, grid point selection, and variable download
- Interactive map (folium) for visualizing coordinates and grid points in browser
- Automatic grid point finding with 4-point selection per coordinate
- Multi-threaded batch download (5 threads) with integrity verification
- Batch download with merge and unit conversion
- Timestamp alignment for mixed instantaneous/averaged variables
- Progress bar showing download progress

## Installation

```bash
pip install pandas requests pywebview folium
```

## Usage

```bash
python scripts/barra2_gui.py
```

### GUI Operations

1. **Add Coordinates**: Enter a label, latitude, and longitude, then click "Add Coordinate"
2. **Select Grid Points**: After coordinates are added, select the desired grid points from the list
3. **Select Variables**: Choose which variables to download (environment variables, wind variables, or specific heights)
4. **Set Date Range**: Choose start and end dates for the download period
5. **Set Output Folder**: Choose where to save the downloaded and merged data
6. **Download**: Click "Download" for raw data, or "Download & Convert" for processed data with unit conversions

### Download Options

- **Download**: Downloads raw CSV files from BARRA2 server (no unit conversion)
- **Download & Convert**: Downloads and merges files with the following unit conversions:
  - Temperature: K → °C (tas, tasmax, tasmin, ta50m)
  - Pressure: Pa → hPa (psl, ps)
  - Precipitation: kg m⁻² s⁻¹ → mm hr⁻¹ (pr, prc, prsn)
  - Specific humidity: kg kg⁻¹ → g kg⁻¹ (huss)
  - Wind components (ua/va) → wind speed (v) and direction (phi_met)

## Available Variables

### Environment Variables

| Variable | Description | Unit | cell_methods | Time Stamp | Merge Handling |
|----------|-------------|------|-------------|------------|----------------|
| `tas` | 2m air temperature (instantaneous) | K | `time: point` | :00 | No shift needed |
| `hurs` | 2m relative humidity | % | `time: point` | :00 | No shift needed |
| `ps` | Surface pressure | Pa | `time: point` | :00 | No shift needed |
| `ta50m` | 50m air temperature (instantaneous) | K | `time: point` | :00 | No shift needed |
| `pr` | Precipitation flux (hourly mean) | kg m-2 s-1 | `time: mean (1hr)` | :30 | Shifted -30min to :00 before merge |
| `rsds` | Surface downwelling shortwave radiation (hourly mean) | W m-2 | `time: mean (1hr)` | :30 | Shifted -30min to :00 before merge |

### Wind Variables

17 heights available: 10m, 20m, 30m, 50m, 70m, 100m, 150m, 200m, 250m, 300m, 400m, 500m, 600m, 700m, 850m, 925m, 1000m. Each height has two components:

| Component | Description | Unit | cell_methods | Time Stamp | Merge Handling |
|-----------|-------------|------|-------------|------------|----------------|
| `ua{H}m` | Eastward wind at {H}m | m s-1 | `time: point` | :00 | No shift needed |
| `va{H}m` | Northward wind at {H}m | m s-1 | `time: point` | :00 | No shift needed |

> NOTE: Only 5 heights (50m, 100m, 150m, 200m, 250m) are currently accessible on the AUS-11 THREDDS server. Others return HTTP 404.

## Timestamp Alignment

BARRA2 variables use two different timestamp conventions:

- **Instantaneous variables** (`time: point`): timestamp at :00, representing a snapshot at that exact time
- **Mean/accumulated variables** (`time: mean`): timestamp at :30, representing the average over the preceding hour (e.g., 01:30 = average of 00:30-01:30)

When merging multiple variables into a single CSV, this causes `pd.merge(outer)` to produce duplicate time rows (one set at :00, another at :30). To produce a single unified time axis:

1. Before merge, CSV files for `pr` and `rsds` have their timestamps shifted **-30 minutes** (e.g., 01:30 becomes 01:00), aligning them to the same :00 axis as instantaneous variables
2. After merge, all variables share a single :00 time axis with no duplicate rows

This timestamp shift is applied in `barra2_gui.py` and does not modify the upstream `barra2_dl/` source code.

## Merged Output Data

When using "Download & Convert", the output CSV contains the following columns:

### Index Columns

| Column | Description | Unit |
|--------|-------------|------|
| `time` | Timestamp | ISO 8601 (UTC) |
| `station` | Station identifier | - |
| `latitude[unit="degrees_north"]` | Latitude | degrees_north |
| `longitude[unit="degrees_east"]` | Longitude | degrees_east |

### Environment Variables (Converted)

| Column | Original Variable | Converted Unit |
|--------|------------------|----------------|
| `tas_celsius[unit="degrees_C"]` | tas | °C |
| `ta50m_celsius[unit="degrees_C"]` | ta50m | °C |
| `ps_hPa[unit="hPa"]` | ps | hPa |
| `pr_mmhr[unit="mm hr-1"]` | pr | mm hr⁻¹ |
| `hurs[unit="%"]` | hurs | % |
| `rsds[unit="W m-2"]` | rsds | W m⁻² |

### Wind Variables (Converted)

| Column | Description | Unit |
|--------|-------------|------|
| `v50m[unit="m s-1"]` | Wind speed at 50m | m s⁻¹ |
| `v100m[unit="m s-1"]` | Wind speed at 100m | m s⁻¹ |
| `v150m[unit="m s-1"]` | Wind speed at 150m | m s⁻¹ |
| `v200m[unit="m s-1"]` | Wind speed at 200m | m s⁻¹ |
| `v250m[unit="m s-1"]` | Wind speed at 250m | m s⁻¹ |
| `v50m_phi_met[unit="degrees"]` | Wind direction at 50m | degrees |
| `v100m_phi_met[unit="degrees"]` | Wind direction at 100m | degrees |
| `v150m_phi_met[unit="degrees"]` | Wind direction at 150m | degrees |
| `v200m_phi_met[unit="degrees"]` | Wind direction at 200m | degrees |
| `v250m_phi_met[unit="degrees"]` | Wind direction at 250m | degrees |

> Note: Wind direction is meteorological convention (direction wind is coming from, 0° = North)

## Data Source

- **Provider**: Bureau of Meteorology, Australia
- **Data**: BARRA-R2 (AUS-11, ~12km resolution) and BARRA-C2 (AUST-04, ~50km resolution)
- **Period**: 1979-present
- **THREDDS Server**: https://thredds.nci.org.au/thredds/fileServer/ob53/BARRA2/README.txt
- **License**: [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/)

## Changelog

### v0.5 (2026-03-30)
- Updated project metadata for independent release (package name, author, repository)
- Added copyright attribution to LICENSE distinguishing upstream and original code
- Updated CONTRIBUTING.md for independent fork project workflow
- Added `.codebuddy/` to `.gitignore`

### v0.4 (2026-03-29)
- Added multi-threaded download (5 threads) with integrity verification
- Added progress bar showing download progress
- Fixed ta50m temperature unit conversion (K → °C)
- Removed duplicate temperature columns in merged output
- Reordered output columns: environment variables (including rsds) before wind variables
- Added mouse wheel scroll support for Variables and Grid Points panels

### v0.3 (2026-03-??)
- Added interactive map in browser for coordinate visualization
- Added grid point selection with 4 nearest points per coordinate
- Added batch download with merge functionality
- Added timestamp alignment for mixed instantaneous/averaged variables

### v0.2 (2026-03-??)
- Added Windows GUI (tkinter)
- Added variable selection

### v0.1 (2026-03-??)
- Initial fork from akarich73/barra2-dl
- Basic CLI functionality

## Acknowledgements

Original project: [akarich73/barra2-dl](https://github.com/akarich73/barra2-dl)
