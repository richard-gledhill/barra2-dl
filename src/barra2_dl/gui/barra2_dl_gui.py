# %% [markdown]
# # barra2-dl: BARRA2 data for a wind site
#
# This notebook downloads BARRA2 reanalysis data (wind, temperature, pressure and more) from the Bureau of
# Meteorology's NCI THREDDS server for one or more places, and writes a CSV or netCDF file for each.
# A place is a **mast** (a point you can drag on the map) or an **area** (a polygon you draw or import).
#
# ## How to use it
#
# 1. Run the three code cells below, from the top (Run > Run All Cells). The form and the map appear under the last
#    cell.
# 2. Drag the mast to your site, or type its latitude and longitude. Draw a polygon on the map to add an area.
# 3. Set the dates, the domain, the preset (which variables) and the output format.
# 4. **Find nodes** shows the BARRA2 grid nodes near a mast or under an area. Click a blue node to choose it. The
#    violet rings mark the nodes a run will download.
# 5. **Run all sites** (or **Run selected site**) downloads the files, merges them and writes the output. **Cancel**
#    stops after the file it is on.
#
# ## Where the files go
#
# Next to this notebook: downloads in `cache/`, results in `out/` (each run also writes a `_run_summary.json`), and
# your settings in `last_session.json`. The Cache folder and Output folder boxes change the first two. A run skips
# files already in the cache, so running again carries on instead of starting over.
#
# ## Restarting
#
# **Load last session** (under Import) restores your sites and settings from the last run. To start the app again,
# run the cells again, or choose Kernel > Restart Kernel and Run All Cells. To get a fresh copy of this notebook, run
# `barra2-dl-gui --reset`.

# %%
from barra2_dl.gui.app import build_app

# %% [markdown]
# The app keeps its files in this notebook's folder.

# %%
app = build_app()

# %% [markdown]
# The form and the map:

# %%
app.show()
