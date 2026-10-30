#%% md
# # barra2-dl point data demo
# This script uses barra2-dl to download BARRA2 AUS11 and AUST04 files for a list of variables. Individual data files
# will be
# saved as csv files in a cache folder, then merged into a single pandas dataframe. As a final step the wind ua and va
# components are converted to v and phi_met, before saving to a new csv file in an output folder.
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
cache_dir = 'scripts/cache'
output_dir = 'scripts/output'
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
# Choose the variables with a preset. The default, wind+density, adds pressure, temperature and humidity to the wind
# heights for air density work. preset_variables checks the preset is available for the domain and frequency: at
# AUST-04 20min, choose the "wind" preset, as pressure and humidity aren't published every 20 minutes.
#%%
barra2_vars = barra2_dl.download.preset_variables(BARRA2_PRESET_DEFAULT, domain, freq)
print(barra2_vars)
#%% md
# ## Download point data
# Use point_data_urlfilenames and download_multithread to download the closest node for the desired variables
# into the target cache folder. The node altitude (orog) is downloaded too, once per node.
#%%
urlfilenames = barra2_dl.download.point_data_urlfilenames(
    barra2_url = BARRA2_URL,
    barra2_vars = barra2_vars,
    latitude = lat_lon_point.lat,
    longitude = lat_lon_point.lon,
    start_datetime= start_datetime,
    end_datetime = end_datetime,
    fileout_prefix = fileout_prefix,
    domain = domain,
    freq = freq,
)
# Use download_multithread with n-1 threads or download_serial with 1 thread
barra2_dl.download.download_multithread(urlfilenames, cache_dir)
#%% md
# ## Combine data
# Merge downloaded csvs into a new dataframe. Optionally export merged data to a new csv.
#%%
df_merged = barra2_dl.merge.merge_csvs_to_df(
    filein_folder= cache_dir,
    filename_pattern=f'{fileout_prefix}_{domain}_{freq}_*.csv',
    index_for_join=BARRA2_INDEX,
)
print(df_merged.head())
#%% md
# The node altitude is a single value rather than a time series, so it isn't merged; read it separately.
#%%
print(barra2_dl.merge.read_fixed_fields(cache_dir, f'{fileout_prefix}_{domain}_fx_*.csv'))
#%%
df_merged.to_csv(Path(output_dir) / f"{fileout_prefix}_merged_{start_datetime.strftime("%Y%m%d")}"
                                    f"_{end_datetime.strftime("%Y%m%d")}.csv", index=False)
#%% md
# ## Convert wind speed components
# Using the merged dataframe, convert ua and va to v and phi_met, and export to new csv file
#%%
df_converted = barra2_dl.convert.convert_wind_components(df_merged)
# optional: convert K to degC, Pa to hPa and precipitation flux to mm h-1
df_converted = barra2_dl.convert.convert_units(df_converted)
print(df_converted.head())
#%%
df_converted.to_csv(Path(output_dir) / f"{fileout_prefix}_converted_{start_datetime.strftime("%Y%m%d")}"
                                       f"_{end_datetime.strftime("%Y%m%d")}.csv", index=False)
#%% md
# The merged and converted data is now ready to import into your favourite wind analysis program...
