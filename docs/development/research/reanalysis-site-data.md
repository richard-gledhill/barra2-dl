# Reanalysis site data: research note for slices 2 to 5 of RFC-005

Status: Reviewed by the owner on 2026-10-31; four decisions recorded under "Owner decisions". Researched 2026-10-31 for
[slice 1b](../plan/SPEC.md); the recommendations are mine and nothing here changes a requirements doc.

**Method.** Web searches (standard mode) and reads of the pages named under Sources, plus live tests of the NCSS server
for question 4. The searches were short: they found little on the exact questions, and where a claim comes from a search
summary, or from my own knowledge of a standard, the text says so. Nothing here is quoted at length.

## Owner decisions

Made on 2026-10-31 after reviewing this note. They settle the questions the SPEC's design table marks for slice 2b:

- **Boundary smaller than one cell:** the node whose cell holds the centroid. `average4` at the centroid stays an option.
- **Site mean for a boundary:** an opt-in extra series, weighted by each cell's overlap with the polygon, using the hybrid
  method. The node series are always written.
- **Node inclusion rule:** a node is kept if its cell overlaps the polygon, as NCSS returns it. A node-inside filter can
  be added later.
- **Shapefiles:** not in v1. Boundary files are GeoJSON and KML, read with the standard library; `pyshp` is not added.

The other recommendations stand as advice for the slices that use them; each slice's SPEC addendum records what it adopts.

## Summary

| # | Question | Recommendation | Confidence |
|---|---|---|---|
| 1 | Mast correlation: which node(s)? | Keep `nearest` as the default. Offer every candidate (the four around the point, any node in the box) and let the analyst correlate each and the weighted mean; don't choose by distance alone. | Medium: no study settles it |
| 2 | Greenfield site | All nodes whose cell overlaps the boundary is the data. A site mean is an optional extra, not the default. A boundary smaller than one cell gets the node whose cell holds its centroid. | Low: no direct evidence found |
| 3 | Averaging method | Keep the hybrid (scalar-mean speed, vector-mean direction). Use cell-overlap weights for an area mean and keep inverse-distance weights for a point. Don't use any mean for extremes. | Medium |
| 4 | NCSS node behaviour | A box returns every node whose cell overlaps it. Tested live and pinned in `tests/test_ncss_nodes.py`. Slice 2 can use one padded box per site, and one request for a polygon's bounding box serves any smaller box. | High: tested |
| 5 | File formats | GeoJSON and KML with the standard library in v1. A shapefile only with `pyshp` (MIT, pure Python) and only if its CRS is geographic. No GeoPackage. | Medium |
| 6 | Choosing nodes for a point | Show the candidate nodes with distance, `orog` and `sftlf`; allow any node in the box, not only the four around the point; one output per chosen node, as `average4` already writes its node files. | Medium |
| 7 | Mast data conventions | Document, don't build a helper: say what barra2-dl's timestamps mean and give an alignment checklist. | Medium |

One correction for the RFC (not changed here): decision 8 says the CSIRO link returned 404. It still does. The paper is
now at <https://connectsci.au/es/article/75/1/ES24028/200355/Validation-of-BARRA2-and-comparison-with-MERRA-2>, DOI
[10.1071/ES24028](https://doi.org/10.1071/ES24028), open access. The old `publish.csiro.au` addresses redirect to a 404.

## 1. Practice for mast correlation

**What I found.**
- The one study that checked BARRA2 against generation, Palmer et al. (2025, J. Southern Hemisphere Earth Systems
  Science), used 54 wind farms (221 site-years, 2014 to 2021) and ranked BARRA-R2 first, then MERRA-2, then ERA5. This
  confirms the claim behind RFC decision 8. Per the summary of its tables (not read verbatim, so check them before quoting):
  median hourly correlation 0.81 for BARRA-R2, 0.75 MERRA-2 and 0.77 ERA5, and a capacity-factor bias of about -7% for
  BARRA-R2 and MERRA-2 against -30% for ERA5. BARRA-R2 here is about 12 km (0.11°) and was a pre-release dataset.
- The paper does not say how it picked the node for each farm. It calls reanalysis wind speed a grid-cell average and says
  linear scaling fixes the annual bias but not the error spread.
- Practice in wind resource software: choose the reference series by the correlation it gives, not by distance (a 2024
  ICREPQ study did this; EMD's windPRO notes recommend letting the tool find the best time offset). A search summary
  quotes the AWS Truepower claim that a combination of the four surrounding nodes correlates better "in select cases"
  than an interpolated value; that is a vendor statement.
- Bechmann et al. (2020, Wind Energy Science) compare closest, inverse-distance-weighted (d^-2) and "most similar"
  predictors, but for **met masts as predictors**, not reanalysis nodes. Inverse-distance weighting cut power-density
  error by 13% against the closest mast, and the most similar by 34%. The paper warns the benefit of averaging depends on
  the individual predictions being independent, which neighbouring reanalysis nodes are not.

**Not found.** A published comparison of nearest node against a few surrounding nodes against a weighted mean, for
reanalysis, on Australian masts.

**Recommendation.** The evidence supports testing candidates, not fixing one. Keep `nearest` as the default (it is the
simplest, and the closest cell is the one that contains the site). Make every candidate easy to get, which RFC-003's
`average4` (the mean plus the four node series) and slice 2's node lookup do. The docs should say: correlate each node and
the mean against the mast, and pick by out-of-sample correlation and error.

## 2. Practice for greenfield sites

**What I found.** Nothing that compares a representative point with an area mean for a site with no mast. Related points:
- A reanalysis value is already an average over the grid cell (Palmer et al.). At 12 km (AUS-11) a wind farm can be
  smaller than one cell; at 4 km (AUST-04) the cell is a third of that width.
- Mast-less estimates are benchmarked in a 2025 WindEurope workshop (calibrated mesoscale maps against measurement-based
  assessment); I found only the programme entry. A vendor presentation reports a mean absolute error of about 5.7% in
  mean wind speed for reanalysis-driven "virtual masts" against 115 masts (WRF downscaling, not raw reanalysis).
- Resolution smooths extremes: DTU work (GASP report, a South Africa extreme-wind paper) describes mesoscale and reanalysis
  winds underestimating extremes because of smoothing. Palmer et al. report all three reanalyses reproduce long lulls, and
  that simulated power reaches rated power more often than observed power does.

**Recommendation.**
- For a boundary, **the data is the set of nodes**, one series each. That matches the RFC-003 area download and is what an
  analyst can later average, weight or pick from.
- A **site mean** is useful but has no established method for a polygon, so make it opt-in and say how it is weighted
  (question 3). It is a judgement for the owner whether to build it in slice 2b or leave it to the analyst.
- A polygon smaller than one cell: use the node whose cell holds the centroid. NCSS already gives this (question 4, a box
  inside one cell returns that node). The SPEC's proposal of `average4` at the centroid would blend in cells the site does
  not touch, so I'd keep it as an option rather than the default. No source settles this.

## 3. Averaging method

**What I found.**
- Scalar mean (average the speeds) is never lower than vector mean (average u and v, then take the speed); the gap comes
  from directional spread, is small at moderate and high wind speeds, and is large when winds oppose. Directions from the
  two usually agree within a few degrees. This is standard and matches the RFC-003 hybrid method (Copernicus Marine's
  "how to average winds", WindGuard, a flux-parameterisation abstract that prefers the scalar mean in weak winds).
- Inverse-distance weighting with d^-2 is the usual choice for combining mast predictions (Bechmann et al.). I found
  no source on weights for combining reanalysis nodes. `average4` uses weights proportional to 1/distance.
- Averaging nodes of a product that is already a grid-cell average smooths it further (variance falls), consistent with the
  extremes point above.

**Recommendation.**
- Keep the hybrid method for any node mean.
- For a **point**, keep inverse-distance weights. Moving to d^-2 would be a documented change, not a fix; no evidence
  favours it for reanalysis.
- For an **area mean**, weight by the area of each cell inside the polygon. It is the physical areal mean, needs no
  tuning, and degrades to the single node for a small polygon. Distance weights have no meaning for an area.
- Say in the docs that a mean is not for extremes or gusts; use the node series.

## 4. NCSS behaviour (tested live, 2026-10-31)

Boxes were requested for the `orog` fixed field on AUS-11 (spacing 0.11°; nodes near the fixtures at latitude -23.65,
-23.54, -23.43 and longitude 133.25, 133.36, 133.47) and on AUST-04 (0.04°).

| Case | Box (N, S, E, W) | Nodes returned |
|---|---|---|
| Overlaps four cells, contains one node | -23.45, -23.60, 133.40, 133.30 | 3 lat x 2 lon: -23.65, -23.54, -23.43 by 133.25, 133.36 |
| Smaller than a cell, no node inside | -23.50, -23.52, 133.40, 133.38 | 1: (-23.54, 133.36), which lies outside the box |
| A single point | -23.54, -23.54, 133.36, 133.36 | 1: (-23.54, 133.36) |
| Exactly one cell | -23.485, -23.595, 133.415, 133.305 | 2 x 2: -23.54, -23.43 by 133.36, 133.47 |
| Superset of the first | -23.30, -23.75, 133.60, 133.15 | 5 x 5, and the shared nodes have identical values |
| AUST-04, 0.01° box across a cell edge | -23.505, -23.515, 133.405, 133.395 | 2 x 2 |

**Findings.**
1. A box returns **every node whose grid cell overlaps it**, where the cell is the node plus or minus half the spacing.
   It does not filter to nodes inside the box, and a box smaller than a cell returns the node whose cell holds it.
2. Edges on a cell edge are inconsistent: the cell touched on the north or east side was returned, the one touched on the
   south or west side was not (half-open cells, or float rounding). Don't rely on it; pad boxes off cell edges.
3. One request for a larger box serves any smaller box inside it: shared nodes had identical values. A polygon's bounding
   box can be fetched once and cached for several sites inside it.
4. AUST-04 behaves the same way.
5. The returned grid has margin nodes beyond the polygon. A polygon boundary needs a client-side mask.

**Consequences.**
- `nearest_nodes(point, n)` can use the box RFC-003 already uses for `average4` (one spacing either side of the point),
  which always returns a 3 x 3 or smaller block around the cell holding the point. No node arithmetic is needed.
- The node inclusion rule for a polygon should be **cell overlaps the polygon**, because that is what the server returns and
  what makes the area-weighted mean (question 3) consistent. "Node point inside the polygon" is a stricter filter that can be
  offered later.
- Pinned by `tests/test_ncss_nodes.py`, using fixtures built by `scripts/build_test_fixtures.py` (`save_node_boxes`).

## 5. File formats

From the standards, not sourced in this pass, except where noted:
- **GeoJSON** (RFC 7946): JSON, WGS84, coordinates in longitude then latitude order. The standard library reads it.
- **KML**: XML, WGS84, `<coordinates>` as longitude,latitude,altitude triples. `xml.etree` reads it. The standard library's
  XML parser is not hardened against entity-expansion files, so reject a DOCTYPE; a local file the user chose is low risk.
- **Shapefile**: a set of files (`.shp`, `.shx`, `.dbf`, and `.prj` for the CRS). Not in the standard library.
  `pyshp` reads it: version 3.1.6 on PyPI (checked today), MIT, pure Python, Python 3.9 or later, no dependencies. Many
  Australian shapefiles are in a **projected** CRS (for example an MGA zone), which needs reprojection, and that would mean
  `pyproj`. Geographic GDA94 or GDA2020 is within about 2 m of WGS84, which is fine here.
- **GeoPackage**: SQLite with a binary geometry column. `sqlite3` can open it but the geometry blob needs its own parser.

**Recommendation.** v1 reads GeoJSON and KML with the standard library. Add shapefile only if the owner approves `pyshp` as
an optional dependency, and then only for a geographic CRS: read the `.prj`, and stop with a clear message for a projected
one rather than reproject. Leave GeoPackage out. This is consistent with decision 4 of the SPEC: nothing outside the
standard library in the core install.

## 6. Point and node selection

**What I found.**
- Users of reanalysis in wind software pick a node on a map and download it (brightwind), or compare several by
  correlation (question 1). I found no documented rule for choosing a node by `orog` or surface type.
- `sftlf` is the CMIP land-area fraction in percent, and `orog` is surface altitude, both published as BARRA2 fixed
  fields. A coastal node with a low land fraction represents mostly sea, which matters for a land mast. I found no BARRA2
  guidance on a threshold (the one reference grid I saw uses 99.9% to call a cell land).

**Recommendation.**
- The node preview shows, for each candidate: distance from the point, `orog` and its difference from the site elevation
  if the user gives one, and `sftlf`.
- Any node the box returns can be chosen, not only the four around the point (question 4 shows 3 x 3 for a point box).
- A chosen set of nodes is a `nodes` selection with the same output layout as `average4`'s node series (a `node`
  dimension, one csv per node), plus the mean only if asked. Node lookup returns grid values, so a chosen node is
  identified by its exact latitude and longitude, never by arithmetic.
- `sftlf` is already in the `site` preset, so the preview can request it as a fixed field the same way as `orog`.

## 7. Mast data conventions

**What I found.**
- There is no single convention. Whether a timestamp labels the start or the end of an averaging interval differs by
  logger and software, and the choice shifts the match by up to an hour for 10-minute data against hourly reanalysis (EMD's
  MCP documentation shows an example and recommends the tool's automatic offset search). One university mast labels the
  start of the interval. A solar-data paper notes the meaning is often missing from metadata.
- I did not find a source on UTC against local time for mast files, or on typical measurement heights.

**What barra2-dl does** (from the project docs): timestamps are UTC and kept as served; instantaneous variables are stamped
at the instant; variables averaged over the step (such as `pr` and `rsds`) are stamped mid-step (:30 at 1hr).

**Recommendation.** No helper in v1. The user guide gets a short alignment checklist: confirm your logger's time zone and
whether a stamp is the start or end of its interval; convert to UTC; compare mast and reanalysis at a few lags and take the
lag that correlates best; remember BARRA2 wind is an instantaneous value, not an hour mean. Mast heights are left to the
analyst, since the series carries the heights it has (10 to 250 m).

## What I could not establish

- Which node Palmer et al. used per farm, and the exact table values (read from summaries; check Tables 3 to 5).
- Any study of nearest node against surrounding nodes for BARRA2 or any reanalysis on masts.
- Weights for combining reanalysis nodes, and whether d^-1 or d^-2 is better.
- Typical mast heights, and mast time-zone practice in Australia.
- Whether the half-open edge behaviour in question 4 is stable; the tests pin today's behaviour.

## Does anything contradict an RFC-005 decision?

No. Decision 8's claim (BARRA-R2 ranked first) is supported by the paper; only its link is out of date. Decision 2 (nearest,
four-node average and area for netCDF) fits the findings. The SPEC's proposed default of `average4` at the centroid for a
polygon smaller than a cell is the one place I'd change course (question 2).

## Sources

- Palmer et al., Validation of BARRA2 and comparison with MERRA-2 and ERA5 using historical wind power generation,
  J. Southern Hemisphere Earth Systems Science 75, ES24028 (2025): <https://connectsci.au/es/article/75/1/ES24028/200355/Validation-of-BARRA2-and-comparison-with-MERRA-2>
- Bechmann, Leon, Olsen, Hristov, The most similar predictor, Wind Energy Science 5, 1679 (2020): <https://wes.copernicus.org/articles/5/1679/2020/>
- EMD, MCP changes in time offset when using averaging: <https://help.emd.dk/mediawiki/index.php/MCP_Changes_in_time_offset_when_using_Averaging>
- EMD, ERA5 in windPRO release note (108-mast correlation): <https://help.emd.dk/mediawiki/images/archive/8/81/20170830174805%2120170829_ERA5_WindPRO_ReleaseNote.pdf>
- Copernicus Marine, how to average winds: <https://help.marine.copernicus.eu/en/articles/5487266-how-to-average-winds>
- WindGuard, vector averaging: <https://www.windguard.de/WindGuardInsight/2018/09/18/different-approach-lidar-data-evaluation/>
- DTU GASP report on smoothing of extreme winds: <https://energiforskning.dk/files/media/document/D2.1_GASP.pdf>
- WindEurope Technology Workshop 2025, mast-less assessment: <https://windeurope.org/tech2025/programme/presentations/152>
- brightwind, download reanalysis data: <https://brightwind.gitbook.io/brighthub-user-docs/quick-start-guide/download-reanalysis-data>
- pyshp on PyPI: <https://pypi.org/project/pyshp/>
- Live NCSS tests: `scripts/build_test_fixtures.py` (`save_node_boxes`) and `tests/test_ncss_nodes.py`.
