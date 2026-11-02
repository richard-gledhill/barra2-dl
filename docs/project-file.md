# Project-file reference

A project file is TOML with one `[settings]` table and one `[[site]]` table for each site. `load_project` reads it,
checks everything at once, and raises one `ProjectError` that lists every problem with its site and key, before any
request. The [how-to-use page](how-to-use.md#project-file) shows how to run one; this page lists every key.

**Unknown keys are errors.** An unknown table, setting or site key is reported with the keys that are known, so a typo
is never silently ignored:

```text
Invalid project:
  settings, workes: Unknown setting. Known: domain, freq, preset, node_selection, format, download, start, end, cache, out, workers.
```

The notebook GUI saves each run as `last_session.json`, the same tables written as JSON with one extra key, `active`
(the name of the site being worked on). The [GUI guide](gui.md) covers what the notebook does with a project file.

## Settings keys

The `[settings]` table holds what a run does. `start` and `end` are required; every other key has a default.

| Key | Type | Default | Values and rules |
|---|---|---|---|
| `start` | date | required | First day, inclusive: `"2023-01-01"` or a TOML date. Must not be after `end` |
| `end` | date | required | Last day, inclusive |
| `domain` | text | `"AUS-11"` | `"AUS-11"` (BARRA-R2) or `"AUST-04"` (BARRA-C2) |
| `freq` | text | `"1hr"` | `"1hr"`; `"20min"` on `AUST-04` only |
| `preset` | text | `"wind+density"` | `wind`, `wind+density`, `wind+stability`, `extremes`, `environment` or `site`. The frequency must have every variable of the preset |
| `node_selection` | text | `"nearest"` | `"nearest"` or `"average4"`, for a point site. A site with `nodes`, a box or a `polygon` sets its own, and `"area"` or `"nodes"` are rejected here |
| `format` | text | `"csv"` | The output: `"csv"` (with a metadata header) or `"netcdf"`. A box or `polygon` site needs `"netcdf"` |
| `download` | text | `"netcdf4"` | The download format: `"netcdf4"`, or `"csv"` for a nearest-node point site with csv output |
| `cache` | text | `"cache"` | Folder for downloaded files, relative to the project file |
| `out` | text | `"output"` | Folder for outputs and run summaries, relative to the project file |
| `workers` | whole number | `4` | Parallel downloads, at least 1 |

The GUI form defaults `format` to `"netcdf"` and `out` to `out`, and has no `download` or `workers` box.

## Site keys

Each `[[site]]` table is one place. Give it a `name` and exactly one place: `lat` with `lon`, a box, or a `polygon`.
A point site may also give `nodes`.

| Key | Type | Rules |
|---|---|---|
| `name` | text | Required. Becomes the filename prefix: letters, digits, dot, underscore and hyphen only. Unique in the project |
| `lat` | number | Latitude in degrees, -90 to 90. Give it with `lon` |
| `lon` | number | Longitude in degrees, -180 to 180 |
| `north` | number | A box site gives all four of `north`, `south`, `east` and `west`; `north` must be greater than `south` and `east` greater than `west`. A box is an area download of every node in it: netCDF only |
| `south` | number | See `north` |
| `east` | number | See `north` |
| `west` | number | See `north` |
| `nodes` | list of `[lat, lon]` | Chosen nodes for a point site. See [below](#nodes) |
| `node_mean` | true or false | Also write the weighted mean. Needs `nodes` or a `polygon`. Default `false` |
| `polygon` | path or table | A boundary. See [below](#polygon) |
| `domain` | text | Overrides the setting for this site only |
| `freq` | text | Overrides the setting for this site only |
| `preset` | text | Overrides the setting for this site only |
| `node_selection` | text | Overrides the setting for this site only. Not allowed with `nodes`, a box or a `polygon` |
| `format` | text | Overrides the setting for this site only |
| `download` | text | Overrides the setting for this site only |
| `start` | date | Overrides the setting for this site only |
| `end` | date | Overrides the setting for this site only |

`cache`, `out` and `workers` belong to the whole project: a site cannot override them.

### Nodes

`nodes` is a list of 1 to 9 `[lat, lon]` pairs, copied exactly from `mapping.nearest_nodes` (or chosen on the GUI map). The
site is then a `nodes` download of those nodes, in that order, each written as its own series (`node1`, `node2`, ...). The
site also needs `lat` and `lon`, the place the distances are measured from. Each node must be within 1.5 grid spacings
of the site, none may repeat, and netCDF4 download is used. A site with `nodes` cannot also have a `polygon` or box, or
override `node_selection`.

```toml
[[site]]
name = "mast-chosen"
lat = -23.55
lon = 133.40
nodes = [[-23.54, 133.36], [-23.54, 133.47]]
node_mean = true   # also write the inverse-distance weighted mean of the two
```

### Polygon

`polygon` is either:

- the path of a GeoJSON or KML file, relative to the project file, in quotes; or
- a GeoJSON feature written inline as a TOML table (this is how `last_session.json` stores it, so it does not depend on
  a boundary file still existing).

A polygon site is an area download of every node whose cell the outline overlaps; its output is netCDF, so `format`
must be `"netcdf"`. A boundary whose bounding box covers more than 2,500 grid nodes is refused. A polygon site cannot
have a point, box or `nodes`, and cannot override `node_selection`. The outline has one ring with optional holes, in WGS 84.
`node_mean = true` adds the mean of the nodes it uses, weighted by cell overlap.

```toml
[[site]]
name = "farm-boundary"
polygon = "farm.geojson"
node_mean = true
```

## Example

```toml
[settings]
domain = "AUS-11"
freq = "1hr"
preset = "wind+density"
format = "netcdf"
start = "2023-01-01"
end = "2023-01-31"
cache = "cache"
out = "output"

[[site]]
name = "mast-north"
lat = -23.55
lon = 133.40
node_selection = "average4"

[[site]]
name = "farm-boundary"
polygon = "farm.geojson"
node_mean = true
```

## What the GUI does with a project file

The notebook has one set of shared settings and at most one area, so on import it skips a box site, ignores a site's own
overrides, and keeps only the first `polygon` site. It reports each skip. See the [GUI guide](gui.md#import).
