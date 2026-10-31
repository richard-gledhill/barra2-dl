# Checklist (one copy per toolkit)

Toolkit: ______  Date: ______  Assessed by: the owner. The evidence column is the spike author's; the yes/no is the owner's.
A "no" on a **gate** removes the toolkit unless waived in the comment box.

| # | Does it... | Yes / No | Evidence |
|---|---|---|---|
| 1 | **gate** Use only `__all__` names and `globals` constants, with all thin-slice items except polygon drawing working? | | |
| 2 | **gate** Draw the offered, chosen and used nodes on the map, distinguishable from each other? | | |
| 3 | **gate** Stop a run on Cancel, with the result reading `cancelled`? | | |
| 4 | **gate** Install against the library's pins with no loosening, on Python 3.12, 3.13 and 3.14 on Windows? | | |
| 5 | **gate** Have an MIT, BSD or Apache-2.0 (or similar) licence for the toolkit and every component used? | | |
| 6 | Look good enough for wind analysts at desktop width? | | |
| 7 | Still work and look fine at a narrow laptop width? | | |
| 8 | Let an analyst find the next step without help? | | |
| 9 | Start with one command? | | |
| 10 | Show validation messages beside the field they concern, and invalid combinations clearly? | | |
| 11 | Pan, zoom and tiles feel smooth? | | |
| 12 | Let you select a node by clicking it? | | |
| 13 | Show distance, altitude and land fraction for a node? | | |
| 14 | Let you draw a polygon on the map? | | |
| 15 | Let you edit and delete it? | | |
| 16 | Give a valid `Polygon` through `polygon_from_geojson`? | | |
| 17 | Show live progress while `run_site` runs? | | |
| 18 | Stay responsive during a run (pan the map, read the form)? | | |
| 19 | Behave acceptably on page reload and on a second tab during a run? | | |
| 20 | Show a failed and a cancelled run properly in the summary? | | |
| 21 | Need only modest threading code? | | |
| 22 | Have an acceptable install size and number of new packages? | | |
| 23 | Make no unwanted outbound calls or telemetry at start-up? | | |
| 24 | Fit the `gui` extra and a `barra2-dl-gui` entry point cleanly? | | |
| 25 | Allow a display-free smoke test of one fake download? | | |
| 26 | Look actively maintained (a release in the last 12 months), including the map component? | | |
| 27 | Look feasible to freeze to a desktop executable later? | | |

Information shown beside the checklist, not scored: code size; console-output findings.

**Final comment box** (anything the questions missed, gate waivers, overall standing, e.g. "first choice", "acceptable", "reject"):

&nbsp;

&nbsp;
