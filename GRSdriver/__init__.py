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

'''

__version__='1.0.6'
__package__ ='GRSdriver'

from .driver_landsat_col2 import LandsatDriver
from .driver_S2_SAFE import Sentinel2Driver
from .utils import SpatioTemp
from .visual import *

import logging
#init logger
logger = logging.getLogger()

level = logging.getLevelName("INFO")
logger.setLevel(level)