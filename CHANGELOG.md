# Version history

We follow [Semantic Versions](https://semver.org/).

## Version 0.5.0

- Updated project metadata for independent release (author, repository, package name)
- Added copyright attribution to LICENSE distinguishing upstream and original code
- Updated CONTRIBUTING.md for fork project workflow

## Version 0.4.0

- Added multi-threaded download (5 threads) with integrity verification (temp file + atomic rename)
- Added progress bar showing download progress (based on total file count)
- Fixed ta50m temperature unit conversion (K → °C)
- Removed duplicate temperature columns (ta50m K) in merged output
- Reordered output columns: environment variables (including rsds) before wind variables
- Added mouse wheel scroll support for Variables and Grid Points panels

## Version 0.3.0

- Added `rsds` (surface shortwave radiation) to environment variables
- Removed `tasmax` and `tasmin` (averaged temperature, :30 timestamps)
- Fixed merge timestamp duplication: `pr` and `rsds` timestamps shifted -30min before merge to align :30 to :00
- Removed old post-merge timestamp shift logic (was applied after merge, too late to prevent duplicate rows)
- Removed cache folder selection from GUI; cache auto-created as `{output}/source/` subfolder
- Added output folder validation (prompts user if not selected)
- GUI variable checkboxes now dynamically generated from `BARRA2_ENV_VARIABLES` dict
- Increased default window height to 750px

## Version 0.2.0

- Added tkinter GUI with coordinate input, grid point selection, and map visualization
- Added folium map with pywebview embedded window (falls back to browser if pywebview unavailable)
- Grid point selection: 4 nearest grid points per coordinate with independent checkboxes
- Variable list restructured: 6 environment variables + 34 wind variables (17 heights x 2 components)
- Removed cache directory from GUI (output only)

## Version 0.1.0

- Initial fork from akarich73/barra2-dl v0.2.0
