'''
v1.0.2:
    - fix for EOreader version >= 0.23
v1.0.3:
    - add landsat driver for L8 and L9
v1.0.4:
    - add subset option for S2
v1.0.5:
    - add time coordinate by default
v1.0.6:
    - convert Landsat bands into TOA reflectance
'''

__version__='1.0.6'

from .driver_landsat_col2 import landsat_driver
from .driver_S2_SAFE import sentinel2_driver