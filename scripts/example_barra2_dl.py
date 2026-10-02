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
    BARRA2_URL_AUS11_1HR,
    BARRA2_URL_AUST04_1HR,
    BARRA2_VAR_WIND_50,
    BARRA2_VAR_WIND_DEFAULT,
)
from barra2_dl.mapping import LatLonPoint

#%%
print('BARRA2_INDEX: ' + BARRA2_INDEX.__str__())
print('BARRA2_VAR_WIND_50: ' + BARRA2_VAR_WIND_50.__str__())
print('BARRA2_VAR_WIND_DEFAULT: ' + BARRA2_VAR_WIND_DEFAULT.__str__())
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
fileout_prefix = "barra2_aust04_1hr"
fileout_prefix = "barra2_aus11_1hr"

#%% md
# ## Download point data
# Use point_data_urlfilenames and download_multithread to download the closest node for the desired variables
# into the target cache folder.
#%%
urlfilenames = barra2_dl.download.point_data_urlfilenames(
    barra2_url = BARRA2_URL_AUS11_1HR, # or barra2_url_aust04_1hr
    barra2_vars = BARRA2_VAR_WIND_DEFAULT,
    latitude = lat_lon_point.lat,
    longitude = lat_lon_point.lon,
    start_datetime= start_datetime,
    end_datetime = end_datetime,
    fileout_prefix = fileout_prefix,
)
# Use download_multithread with n-1 threads or download_serial with 1 thread
barra2_dl.download.download_multithread(urlfilenames, cache_dir)
#%% md
# ## Combine data
# Merge downloaded csvs into a new dataframe. Optionally export merged data to a new csv.
#%%
df_merged = barra2_dl.merge.merge_csvs_to_df(
    filein_folder= cache_dir,
    filename_pattern=f'{fileout_prefix}*.csv',
    index_for_join=BARRA2_INDEX,
)
print(df_merged.head())
#%%
df_merged.to_csv(Path(output_dir) / f"{fileout_prefix}_merged_{start_datetime.strftime("%Y%m%d")}"
                                    f"_{end_datetime.strftime("%Y%m%d")}.csv", index=False)
#%% md
# ## Convert wind speed components
# Using the merged dataframe, convert ua and va to v and phi_met, and export to new csv file
#%%
df_converted = barra2_dl.convert.convert_wind_components(df_merged)
print(df_converted.head())
#%%
df_converted.to_csv(Path(output_dir) / f"{fileout_prefix}_converted_{start_datetime.strftime("%Y%m%d")}"
                                       f"_{end_datetime.strftime("%Y%m%d")}.csv", index=False)
#%% md
# The merged and converted data is now ready to import into your favourite wind analysis program...
