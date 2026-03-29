# BARRA2 Data Downloader (Fork)

Fork of [akarich73/barra2-dl](https://github.com/akarich73/barra2-dl) with a Windows GUI and custom modifications.

## Features

- Windows desktop GUI (tkinter) for coordinate input, grid point selection, and variable download
- Interactive map (folium + pywebview) for visualizing coordinates and grid points
- Automatic grid point finding with 4-point selection per coordinate
- Batch download with merge and unit conversion
- Timestamp alignment for mixed instantaneous/averaged variables

## Installation

```bash
pip install pandas requests pywebview folium
```

## Usage

```bash
python scripts/barra2_gui.py
```

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

## Data Source

- **Provider**: Bureau of Meteorology, Australia
- **Data**: BARRA-R2 (AUS-11, ~12km resolution) and BARRA-C2 (AUST-04, ~50km resolution)
- **Period**: 1979-present
- **THREDDS Server**: https://thredds.nci.org.au/thredds/fileServer/ob53/BARRA2/README.txt
- **License**: [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/)

## Acknowledgements

Original project: [akarich73/barra2-dl](https://github.com/akarich73/barra2-dl)
