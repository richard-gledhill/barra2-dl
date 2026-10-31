#%% md
# # barra2-dl point data demo: netCDF output
# This script uses barra2-dl to download BARRA2 AUS11 and AUST04 files for a list of variables as netCDF4. Individual
# data files are saved in a cache folder, then merged straight into a CF-style xarray Dataset, with wind speed and
# direction derived from the ua and va components, before saving to a netCDF file in an output folder.
#
# To download and write csv files instead, see example_barra2_dl_csv.py.
#
# The first step is to import the necessary python packages and modules from barra2_dl. Also from barra2_dl.globals we
# import some pre-configured default variables to download.
#%%
from datetime import datetime
from pathlib import Path

import barra2_dl
from barra2_dl.globals import (
    BARRA2_INDEX,
    BARRA2_PRESET_DEFAULT,
    BARRA2_PRESETS,
    BARRA2_URL,
)
from barra2_dl.mapping import LatLonPoint

#%%
print('BARRA2_INDEX: ' + BARRA2_INDEX.__str__())
print('Presets: ' + ', '.join(BARRA2_PRESETS))
print('Default preset: ' + BARRA2_PRESET_DEFAULT)
#%% md
# ## Set variables
# Set the cache and output folders.
#%%
cache_dir = 'cache'
output_dir = 'output'
# the folders are git-ignored, so create them on a fresh clone
for folder in (cache_dir, output_dir):
    Path(folder).mkdir(parents=True, exist_ok=True)
#%% md
# Set the location point for downloading. This can either be set explicitly as a Dictionary, or using the
# pre-configured LatLonPoint class in barra2_dl.mapping module. Point data is downloaded to the nearest node.
#%%
# centre of Australia used for demo
# lat_lon_point = {'lat': -23.5527472, 'lon': 133.3961111}  # dict alternative shown for reference only

# or use custom class from mapping
lat_lon_point = LatLonPoint(-23.5527472, 133.3961111)
print(lat_lon_point)
#%% md
# Set start and end time for download.
#%%
start_datetime = datetime.strptime("2023-01-01T00:00:00Z", "%Y-%m-%dT%H:%M:%SZ")
end_datetime = datetime.strptime("2023-03-31T23:00:00Z", "%Y-%m-%dT%H:%M:%SZ")
#%% md
# Set output file custom name prefix to indicate a device or project location for the downloaded data. I.e.
# use project or location name.
#
#%%
fileout_prefix = "demo"

#%% md
# Choose the BARRA2 domain and frequency: AUS-11 (BARRA-R2) at 1hr, or AUST-04 (BARRA-C2) at 1hr or 20min.
# Cache files are named with both, so different runs can share the cache folder.
#%%
domain = "AUS-11"  # or "AUST-04"
freq = "1hr"  # or "20min" on AUST-04

#%% md
# Choose how the nodes are selected. "nearest" downloads the grid node nearest the point. "average4" downloads the
# small grid around the point and averages the four nodes that surround it with inverse-distance weights, keeping
# the four node series too. (For every node in an area, see area_data_urlfilenames and the how-to guide.)
#%%
node_selection = "nearest"  # or "average4"

#%% md
# Choose the variables with a preset. The default, wind+density, adds pressure, temperature and humidity to the wind
# heights for air density work. preset_variables checks the preset is available for the domain and frequency: at
# AUST-04 20min, choose the "wind" preset, as pressure and humidity aren't published every 20 minutes.
#%%
barra2_vars = barra2_dl.download.preset_variables(BARRA2_PRESET_DEFAULT, domain, freq)
print(barra2_vars)
#%% md
# ## Download point data
# Use point_data_urlfilenames and download_multithread to download the desired variables into the target cache folder,
# as netCDF4 files (fileout_type='netcdf4'). The node altitude (orog) is downloaded too, once per node.
#%%
urlfilenames = barra2_dl.download.point_data_urlfilenames(
    barra2_url = BARRA2_URL,
    barra2_vars = barra2_vars,
    latitude = lat_lon_point.lat,
    longitude = lat_lon_point.lon,
    start_datetime= start_datetime,
    end_datetime = end_datetime,
    fileout_prefix = fileout_prefix,
    fileout_type = "netcdf4",
    domain = domain,
    freq = freq,
    node_selection = node_selection,
)
# Use download_multithread (4 parallel downloads by default, set with workers=) or download_serial
barra2_dl.download.download_multithread(urlfilenames, cache_dir)
#%% md
# THREDDS serves only the latest data, so record which dataset version each variable came from. This makes one small
# request per variable, and falls back to "latest" for any it can't read.
#%%
versions = barra2_dl.download.resolve_variable_versions(barra2_vars, domain, freq)
print(versions)
#%% md
# ## Combine data
# Merge the downloaded files into one Dataset. Timestamps are kept as served: variables averaged over the time step
# (such as pr and rsds, stamped at :30) go on their own time_mean coordinate with time_bnds. Wind speed and direction
# are derived from the ua and va components and, with them, sit on a height dimension.
#
# For "nearest" the node altitude is read separately and passed in. For "average4" the downloaded altitude grid is
# read at the four nodes, and the Dataset gets a node dimension holding the four node series beside the average. Its
# wind speed is the weighted mean of the nodes' own speeds, and its direction comes from the weighted-mean components.
#%%
fixed_tag = "" if node_selection == "nearest" else f"{node_selection}_"
fixed_name = f"{fileout_prefix}_{domain}_fx_{fixed_tag}orog.nc"
node_altitude = None
if node_selection == "nearest":
    node_altitude = barra2_dl.merge.read_fixed_fields(cache_dir, fixed_name)['orog[unit="m"]']
ds = barra2_dl.merge.merge_netcdf_to_dataset(
    filein_folder = cache_dir,
    filename_pattern = f'{fileout_prefix}_{domain}_{freq}_*.nc',
    domain = domain,
    freq = freq,
    requested = lat_lon_point,
    orog = node_altitude,
    node_selection = node_selection,
    versions = versions,
    fixed_pattern = None if node_selection == "nearest" else fixed_name,
)
print(ds)
#%% md
# ## Write netCDF
# Name the file for the site, as <prefix>_<domain>_<freq>_<selection>_<start>_<end>.nc.
#%%
ds.to_netcdf(Path(output_dir) / f"{fileout_prefix}_{domain}_{freq}_{node_selection}_{start_datetime.strftime("%Y%m%d")}"
                                f"_{end_datetime.strftime("%Y%m%d")}.nc")
#%% md
# ## Write csv (optional)
# The same data can be written as csv. write_csv writes a file for the series, and for "average4" one for the average and
# one for each of the four nodes. Each file opens with a metadata header (source, node, elevation, requested point, time
# zone, dataset versions ...); header=False writes the bare frame. merge.read_csv reads a file back with its header.
#%%
csv_paths = barra2_dl.merge.write_csv(ds, output_dir, fileout_prefix)
#%% md
# The netCDF file is now ready to open with xarray, e.g. xarray.open_dataset(path), or any netCDF tool.
# For example ds.wind_speed.sel(height=[50, 100]) selects two heights.
#%% md
# ## Choose specific nodes (optional)
# nearest_nodes asks the server for the grid nodes around a point and returns them nearest first, with their distance,
# altitude (orog) and land fraction in percent (sftlf). Pick the nodes you want and give their exact latitude and longitude
# to a site as nodes = [[lat, lon], ...] (see example_project.toml); never type a node you worked out yourself.
# The two small fixed-field files are kept in cache/nodes, so a repeat lookup makes no request.
#%%
for node in barra2_dl.mapping.nearest_nodes(lat_lon_point, domain, 4, cache=cache_dir):
    print(f'{node.lat!r:>22} {node.lon!r:>8}  {node.distance_km:6.2f} km  orog {node.orog:6.1f} m  sftlf {node.sftlf:5.1f} %')
#%% md
# ## Use a site boundary (optional)
# read_polygon reads a GeoJSON or KML outline (WGS 84, one polygon). A boundary site uses every BARRA2 node whose grid cell
# overlaps it (or, for an outline smaller than one cell, the one node whose cell holds its centroid). cell_overlap says how
# much of each cell the outline covers, which is also each node's weight in the optional site mean (node_mean). See the
# farm-boundary site in example_project.toml, which writes the masked grid and the mean as netCDF.
#%%
boundary = barra2_dl.mapping.read_polygon('example_boundary.geojson')
print(boundary.bbox(), f'{boundary.area_km2():.0f} km2, centroid {boundary.centroid()}')
spacing = barra2_dl.globals.BARRA2_GRID_SPACING[domain]
nodes = barra2_dl.mapping.nearest_nodes(boundary.centroid(), domain, 9, cache=cache_dir)
lats, lons = sorted({n.lat for n in nodes}), sorted({n.lon for n in nodes})
print(boundary.cell_overlap(lats, lons, spacing).round(2), lats, lons)
#%% md
# ## Run a whole project from a file (optional)
# Everything above is what project.run_site does for you. A project file lists shared settings and one site per mast,
# point or area; load_project checks all of it at once, and run_site downloads, merges and writes each site's output
# and a run summary (<name>_run_summary.json). A site that fails is reported, not raised, so the loop carries on.
# See example_project.toml. This downloads data, so run it only when you want those sites.
#%%
project = barra2_dl.project.load_project("example_project.toml")
for site in project.sites:
    result = barra2_dl.project.run_site(site, project.settings)
    print(result.site, result.status, [path.name for path in result.outputs], result.missing)
