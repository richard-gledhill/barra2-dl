# Manual checks

Checks that need a person or software outside the test suite. Run them before a release that touches the area, and
record the result in the table at the end of each check.

## Windographer import of a csv with a metadata header

**Why:** `merge.write_csv` opens each csv with a `key,value` [metadata header](../../how-to-use.md#csv-metadata-header).
Windographer's pages say it finds the header block, the column-name row and the first data row itself, and reads
latitude, longitude and elevation "from the file header", but give no syntax for those lines
([RFC-007's SPEC](../plan/archive/2026-10-cache-validation/SPEC.md), "Findings from the Windographer pages"). Only an import
settles it. Run it again if the header layout (`merge._csv_header`) or the column names change.

**Files:** write both from the example fixtures or a real run (`scripts/example_barra2_dl_netcdf.py`):

1. A nearest-node file: `node_selection = "nearest"` (22 header lines).
2. An `average4` average file: `node_selection = "average4"`, the `..._average4_...csv` file (26 header lines, with
   `Node 1` to `Node 4` lines).

**Steps:** for each file, in Windographer use File > Import Raw Data File, then open Configure Dataset.

**Record:**

- Is the header block stripped, so the first data row is the first `time` row and the column row is the
  `time,station,latitude...` row?
- Are latitude, longitude and elevation filled in from the header? Are they the values in the file (`Latitude`,
  `Longitude`, `Elevation`)?
- Are the time step (1 hr) and time zone (UTC) picked up, or do they need setting by hand?
- Is the text `station` column ignored, as the pages say?
- Any warning or column Windographer misreads (for example the `[unit="..."]` suffix in the column names).

**If it doesn't read the location, time step or time zone:** the header stays as the provenance record. Setting them
from the file is RFC-006 work: a Windographer `.wis` sidecar (time zone, time stamp meaning, column properties) and
Windographer-native column names. Add what you found to that RFC.

| Date | barra2-dl version | Windographer version | Nearest file | `average4` file | Notes |
|---|---|---|---|---|---|
| _not yet run_ | | | | | RFC-007 acceptance: owner to record here |

## Example scripts and notebooks

**Why:** `scripts/example_barra2_dl_*.py` and the notebooks download real data, so they are not in the test suite
(see [README.md](README.md)).

**Steps:** run each `.py` and its `.ipynb` top to bottom in a scratch folder, twice (the second run should make no
requests). Then move the point and run again: it should stop with `CacheMismatchError` before any request. Keep each
`.py` and `.ipynb` pair in step.

| Date | Scripts run | Result |
|---|---|---|
| 2026-10-31 | csv example, `.py` and `.ipynb` (owner) | Work, before the filename and header change |
| 2026-10-31 | csv example `.py` after the change (Claude, scratch folder; second run made no requests) | Work |
| 2026-10-31 | csv example `.ipynb` after the change (owner) | Work |
| 2026-10-31 | netCDF example project cell (`run_site` over `example_project.toml`), `.py` and `.ipynb` (owner) | Work; outputs spot-checked |
| 2026-10-31 | netCDF example, `.py` and `.ipynb`, after the change (owner) | Work |
