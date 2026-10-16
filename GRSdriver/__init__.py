'''
Load Sentinel-2 and Landsat 8/9 Level-1 products as xarray datasets, ready for the GRS
atmospheric correction.

The drivers read a Level-1 product and return an ``xarray.Dataset`` with the top-of-atmosphere
reflectance of the selected bands on a common grid, the sun and viewing geometry, the spectral
response functions and the main metadata:

- :class:`~GRSdriver.driver_S2_SAFE.Sentinel2Driver`: Sentinel-2 MSI Level-1C (SAFE format),
  with the viewing angles of each band and detector;
- :class:`~GRSdriver.driver_landsat_col2.LandsatDriver`: Landsat 8/9 OLI/TIRS Collection 2
  Level-1, with the brightness temperature of the thermal bands and the quality flags;
- :class:`~GRSdriver.utils.SpatioTemp`: helpers to define a region of interest.

They are available at the package level::

    from GRSdriver import Sentinel2Driver

    l1c = Sentinel2Driver('S2B_MSIL1C_..._.SAFE', resolution=20)
    l1c.load_product()
    prod = l1c.prod

Set the environment variable ``GRSDRIVER_USE_DASK=1`` before importing GRSdriver to get lazy
(dask-backed) products (see :func:`~GRSdriver.utils.use_dask`). The :doc:`tutorials
</tutorials/index>` show the drivers at work; the :doc:`Methods </methods>` page gives the
equations.
'''

# Release history (details in CHANGELOG.md)
#
# v1.0.0:
# first commit from S2driver package v1.0.6
#
# v1.0.1:
# package for Pypi
#
# v1.0.2:
# add documentation
#
# v1.0.3:
# working version for Landsat 8 and 9
#
# v1.0.4:
# add thermal bands for Landsat 8 and 9
#
# v1.0.5:
# add subset tool
#
# v1.0.6:
# fix for TIR bands (get Brightness temperature alongside reflectance for vis-NIR-SWIR bands)
#
# v1.0.7:
# fix for new version xarray >=2024
#
# v1.0.8 (2025-02-10):
# fix xarray merge policy: compat='override'
#
# v1.0.9 (2026-10-07):
# speed up loading and enable dask-backed products (EOREADER_USE_DASK=1),
# Landsat: keep valid angle pixels at swath edges, flags_l1 as uint32,
# angles in float32, improved docstrings
#
# v1.0.10 (2026-10-08):
# lower memory use for large Sentinel-2 rasters (bands loaded one by one,
# lean nearest resampling of the angles), lazy_geom option (vza/raa as dask
# arrays computed block by block), Methods page in the documentation
#
# v1.1.0 (2026-10-14):
# Sentinel-2: bands now really loaded one by one on full tiles (the grid check
# always failed because of spatial_ref), peak memory of load_bands 8.6 GB -> 3.75 GB
#
# v1.1.1 (2026-10-14):
# grs_driver command line: Sentinel-2 supported, default RGB bands per sensor,
# red/blue channels no longer swapped, --no_clobber fixed
#
# v2.0.0 (2026-10-15):
# EOReader, sertit, the GDAL Python bindings, fiona and pystac no longer needed
# (pip-only install): bands read with rasterio/GDAL on the output grid and calibrated
# from the product metadata, ~2x faster for Sentinel-2; Sentinel-2 baseline < 4.0
# angles fixed; least-squares plane fit of the viewing angles (scipy.odr deprecated);
# API: no ``**kwargs``, no ``.reader``, ``GRSDRIVER_USE_DASK``
#
# v2.0.1 (2026-10-16):
# parallel band reading (``n_workers``) and Sentinel-2 angles, ~2x faster; really lazy
# and ~7x faster dask mode; SpatioTemp.wktbox and clip_raster boxes of the documented size;
# API documentation
#
# v2.0.2 (2026-10-16):
# continuous integration (tests with Python 3.9 to 3.13, PyPI publishing on tags);
# grs_driver --help without matplotlib/cartopy
__version__='2.0.2'
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