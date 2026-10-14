'''
v1.0.0:
first commit from S2driver package v1.0.6

v1.0.1:
package for Pypi

v1.0.2:
add documentation

v1.0.3:
working version for Landsat 8 and 9

v1.0.4:
add thermal bands for Landsat 8 and 9

v1.0.5:
add subset tool

v1.0.6:
fix for TIR bands (get Brightness temperature alongside reflectance for vis-NIR-SWIR bands)

v1.0.7:
fix for new version xarray >=2024

v1.0.8 (2025-02-10):
fix xarray merge policy: compat='override'

v1.0.9 (2026-10-07):
speed up loading and enable dask-backed products (EOREADER_USE_DASK=1),
Landsat: keep valid angle pixels at swath edges, flags_l1 as uint32,
angles in float32, improved docstrings

v1.0.10 (2026-10-08):
lower memory use for large Sentinel-2 rasters (bands loaded one by one,
lean nearest resampling of the angles), lazy_geom option (vza/raa as dask
arrays computed block by block), Methods page in the documentation

v1.1.0 (2026-10-14):
Sentinel-2: bands now really loaded one by one on full tiles (the grid check
always failed because of spatial_ref), peak memory of load_bands 8.6 GB -> 3.75 GB

v1.1.1 (2026-10-14):
grs_driver command line: Sentinel-2 supported, default RGB bands per sensor,
red/blue channels no longer swapped, --no_clobber fixed
'''

__version__='1.1.1'
__package__ ='GRSdriver'

from .driver_landsat_col2 import LandsatDriver
from .driver_S2_SAFE import Sentinel2Driver
from .utils import SpatioTemp
#from .visual import *

import logging
#init logger
logger = logging.getLogger()

level = logging.getLevelName("INFO")
logger.setLevel(level)