# The notebook GUI

The GUI is a Jupyter notebook. A form on the left and a map on the right let you place masts,
draw an area, see the
BARRA2 grid nodes, run the downloads and read a summary of each run, without writing code. It runs the same engine as
a [project file](project-file.md).

## Install and start

barra2-dl is not published on PyPI yet, so install the `gui` extra from GitHub (Python 3.12 or later; the extra adds
JupyterLab, about 140 MB):

```bash
pip install "barra2-dl[gui] @ git+https://github.com/richard-gledhill/barra2-dl.git"
```
We recommend installing into a virtual environment.

```bash
# 1. Create the virtual environment (named .venv)
python -m venv .venv

# 2. Activate it
# On Windows (Command Prompt):
.venv\Scripts\activate
# On Windows (PowerShell):
.venv\Scripts\Activate.ps1
# On macOS / Linux:
source .venv/bin/activate

# 3. Now run your install inside the virtual environment
pip install "barra2-dl[gui] @ git+https://github.com/richard-gledhill/barra2-dl.git"
```

...and to run:

```bash
barra2-dl-gui
```

`barra2-dl-gui [folder]` copies the notebook `barra2_dl_gui.ipynb` into the folder (default `./barra2-dl-gui`) and opens
JupyterLab on it. It never overwrites a copy that is already there, so your edits survive; `barra2-dl-gui --reset`
replaces the notebook with the shipped one, and `--no-launch` copies it and stops. If the extra is not installed, the
command says so and prints the install line.

In the notebook, choose Run > Run All Cells. The three code cells import the app, build it and show it; the form and
the map appear under the last cell. Run the cells again, or choose Kernel > Restart Kernel and Run All Cells, to start
the app again.

## Where the files go

Next to the notebook:

| What | Where |
|---|---|
| Downloaded files | `cache/` (the Cache folder box) |
| Results | `out/` (the Output folder box), with a `<name>_run_summary.json` for each site |
| Your settings and sites | `last_session.json` |

Relative folders in the boxes are relative to the notebook's folder. A run skips files already in the cache, so running
again carries on instead of starting over.

## The form

The form has two parts: the site, and the settings shared by every site.

**The site.** The **Site** list holds your masts and, if you have drawn one, the area. **Add mast** adds a mast just north
of the current site; **Remove site** removes the current one (removing the area clears it from the map). Each site has a
**Name**, which becomes the filename prefix (letters, digits, dot, underscore and hyphen, and different for every site),
and for a mast a **Latitude** and **Longitude**. An area has no place boxes: its place is its outline.

**Shared settings.** These apply to every site in the run.

| Field | Meaning |
|---|---|
| Start, End | The first and last day to download, inclusive |
| Domain | `AUS-11` (the default; see [why](#why-aus-11-is-the-default)) or `AUST-04` |
| Frequency | `1hr`, or `20min` on `AUST-04` only. Changing the domain resets the frequency if it no longer applies |
| Preset | Which variables to download. A note under the box lists them. `wind+density` is the default |
| Mast nodes | `nearest`: the one node nearest the mast. `average4`: the four nodes around it, averaged with inverse-distance weights. Greyed out for an area, and for a mast whose nodes you have chosen |
| Output | `netcdf` (the form's default) or `csv`. An area can only be written as `netcdf` |
| Cache folder, Output folder | See [Where the files go](#where-the-files-go) |

A box with a problem gets a red border, and every problem is listed in red under the map with the site it belongs to.
A run does not start while a problem remains. Problems are found before any request, for example `20min` on `AUS-11`,
a preset the frequency does not have, an area as `csv`, or two sites with the same name.

The form does not set the number of parallel downloads (4) or the download format (netCDF4). A project file can.

## The map

The map starts on a mast near Alice Springs. The map's tiles are OpenStreetMap, fetched by your browser; heavy or
commercial use needs a tile provider that allows it.

**Masts.** Drag a mast to move it, or type its latitude and longitude. Click a marker to make that site the current one.
The current mast is black and the others light grey. Moving a mast forgets the nodes you found for it, because they were
for the old place.

**The area.** Use the polygon tool on the map's toolbar to draw an outline. There is at most one area; the tool goes
away while there is one, and drawing a second keeps the first. Reshape, move or delete the area with the toolbar's edit,
drag and remove tools. The current area is purple and an idle one grey, labelled with its name.

**Nodes.** Press **Find nodes** to show the BARRA2 grid nodes for the current site. For a mast, it shows the nine nodes
around it; for an area, every node whose cell the outline overlaps. All nodes come from the server's own grid, never
from arithmetic on a grid origin. The colours are:

| Mark | Meaning |
|---|---|
| Blue circle | A node offered for a mast |
| Green circle | A node you chose; every node of an area |
| Violet ring | A node the run will download, from the current choice |
| Orange ring | A node the last run used |

Click a node to see its distance, altitude (`orog`) and land fraction. For a mast, clicking also chooses the node, and
clicking it again drops it. For an area, it also shows how much of the node's cell lies inside the outline (its cell
overlap). Choosing nodes replaces the **Mast nodes** setting for that mast: the run downloads the nodes you chose, in
the order you clicked them. Changing the domain forgets all the nodes.

**The weighted mean.** For a mast with chosen nodes, or for an area, tick **Also write the weighted mean of the nodes**
to add the mean to the output. A mast's mean uses inverse-distance weights; an area's mean uses cell overlap. The mean
is not for extremes or gusts.

## Run

The line under the map reads "N files, M cached" for each valid site, and updates when the cache folder changes.

- **Run all sites** runs every site, one after another. **Run selected site** runs only the current one.
- A progress bar and a line below it show the site, the file and its status. Progress is also written under the cell
  that started the app.
- **Cancel** stops after the file it is on. Files already downloaded stay in the cache.
- Every run first saves your settings and sites to `last_session.json`.

A failing site does not stop the others; its summary says what went wrong.

## The run summary

When a site finishes, its summary appears under the buttons:

- **The status**: `ok`; `partial` (output written, some files missing); `failed`; or `cancelled`.
- **The error**, in red, when it failed, and **missing**, in amber, listing the variable-months that could not be
  downloaded, such as `ua50m 2023-02`.
- **Outputs**: the files written in the output folder.
- **A table of files**: each file's status, HTTP status code and number of attempts.
- **A table of nodes used**: latitude, longitude, distance in km, `orog`, and the weight or cell overlap where there is
  one. The same nodes are ringed in orange on the map.

The summary is also written to `<name>_run_summary.json` beside the output. The output files are named as they are for a
[project file](project-file.md) run. For a mast, `csv` gives one file per series with a metadata header, and `netcdf` gives
one file; an area gives one netCDF file.

## Import

Open **Import a project, polygon file or the last session** under the form.

- **Load last session** restores the settings and sites saved by the last run, ready to Run again: cached files are skipped
  and the outputs are rewritten.
- **A path or an upload** of a `project.toml` replaces the settings and all sites (see the
  [project-file reference](project-file.md)). The notebook shows what it can: a box site is skipped, a site's own
  overrides are ignored because settings are shared, and only one area is kept. Each skip is reported under the button.
- **A `.geojson`, `.json` or `.kml` polygon** becomes the area, replacing the area there is, and the map zooms to it.
- A polygon file named inside a project is read relative to the project when you give a path. When you upload instead,
  select the polygon file together with the `project.toml` (Ctrl-click).

## Why AUS-11 is the default

`AUS-11` is the BARRA-R2 domain, a regional reanalysis on a grid of about 11 km. It covers a wider area than `AUST-04` (BARRA-C2), and it
ranked first, ahead of MERRA-2 and ERA5, in a CSIRO-published validation of simulated wind power against observed output at
54 Australian wind farms:

> Palmer, G. et al. "Validation of BARRA2 and comparison with MERRA-2 and ERA5 using historical wind power generation".
> *Journal of Southern Hemisphere Earth Systems Science* (CSIRO Publishing), manuscript ES24028.

Choose `AUST-04` when you want its finer grid (about 4 km against 11 km) or its `20min` data. A point outside the domain gives
an error when the nodes are looked up. The validation found that modelled power can differ noticeably from observed
power at times, so check the data against measurements where you have them.

## Run the GUI from a clone

To run the GUI from a clone of the repository, install the `gui` extra with the development dependencies, then start
it through `uv`:

```bash
uv sync --all-extras
```

```bash
uv run barra2-dl-gui
```

This runs the code in your clone, not an installed copy. It puts the notebook in `./barra2-dl-gui`, with the cache,
the output and `last_session.json` beside it, and opens JupyterLab. Use `uv run barra2-dl-gui --no-launch <folder>` to
copy the notebook without starting JupyterLab.

The command never overwrites a notebook already in the folder. After you change the shipped notebook, add `--reset` to
replace the folder's copy:

```bash
uv run barra2-dl-gui --reset
```

The shipped notebook, `src/barra2_dl/gui/barra2_dl_gui.ipynb`, is generated from the jupytext source beside it,
`barra2_dl_gui.py`. Edit the `.py` file, then regenerate the notebook; a test fails if the two differ:

```bash
uv run jupytext --to ipynb src/barra2_dl/gui/barra2_dl_gui.py
```

The code behind the form and the map is `src/barra2_dl/gui/app.py`. Its tests use a fake NCSS server and need the extra,
so without `uv sync --all-extras` they are skipped.
