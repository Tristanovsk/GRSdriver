import glob
import os
import xml.etree.ElementTree as ET

import numpy as np
from numba import jit

import pandas as pd
import geopandas as gpd
import xarray as xr
import rioxarray as xrio
import xmltodict

from rasterio.features import rasterize
import scipy.odr as odr
from affine import Affine
from osgeo import gdal, ogr
# import cartopy.crs as ccrs
from pyproj import CRS

from importlib_resources import files

import eoreader as eo
from eoreader.reader import Reader
from eoreader.bands import RAW_CLOUDS
from eoreader.keywords import TO_REFLECTANCE

opj = os.path.join

BAND_NAMES = np.array(['B01', 'B02', 'B03', 'B08', 'B04', 'B05', 'B09', 'B06', 'B07'])
BAND_NAMES_EOREADER = np.array(['CA', 'BLUE', 'GREEN', 'PAN', 'RED', 'NIR',
                                'SWIR_CIRRUS', 'SWIR_1', 'SWIR_2'])

BAND_ID = [b.replace('B', '') for b in BAND_NAMES]
NATIVE_RESOLUTION = [30, 30, 30, 15, 30, 30, 30, 30, 30]
WAVELENGTH = np.array([443, 490, 560, 590, 665, 865, 1370, 1610, 2190])
BAND_WIDTH = [25, 60, 60, 173, 33, 28, 21, 95, 287]

INFO = pd.DataFrame({'bandId': range(len(BAND_NAMES)),
                     'ESA': BAND_NAMES,
                     'EOREADER': BAND_NAMES_EOREADER,
                     'Wavelength (nm)': WAVELENGTH,
                     'Band width (nm)': BAND_WIDTH,
                     'Resolution (m)': NATIVE_RESOLUTION}).set_index('bandId').T


class landsat_driver():
    def __init__(self, image_path,
                 band_idx=[0, 1, 2, 3, 4, 5, 6, 7, 8],
                 band_tbp_idx=[0, 1, 2, 3, 4, 5, 7, 8],
                 resolution=30,
                 verbose=False,
                 **kwargs):

        self.abspath = os.path.abspath(image_path)
        dirroot, basename = os.path.split(self.abspath)
        self.verbose = verbose
        self.band_idx = band_idx
        self.band_tbp_idx = band_tbp_idx
        self.resolution = resolution
        self.INFO = INFO[band_idx]

        # -----------------------------------------------------
        # define prod and geom where data will be loaded
        # -----------------------------------------------------
        self.prod = xr.Dataset()
        self.geom = xr.Dataset()

        self.solar_irradiance = None

        # Open instance of eoreader
        reader = Reader()

        # Open the product
        reader = reader.open(image_path, remove_tmp=True, **kwargs)
        self.reader = reader
        self.satellite = reader.constellation.value
        self.datetime = reader.datetime
        self.acquisition_date = reader.datetime
        self.tile = reader.tile_name

        # save geographic data
        self.extent = reader.extent()
        self.bounds = self.extent.bounds
        minx, miny, maxx, maxy = self.bounds.values[0]
        self.crs = self.reader.crs()
        self.epsg = self.extent.crs.to_epsg()

        self.transform = Affine(resolution, 0., minx, 0., -resolution, maxy)

        # --------------------------------
        # Spectral Response Functions
        # --------------------------------

        if '8' in self.satellite:
            srf_file = files('rsr.data').joinpath('rsr_landsat_8_oli.nc')
        elif '9' in self.satellite:
            srf_file = files('rsr.data').joinpath('rsr_landsat_9_oli.nc')
        else:
            print('Problem to fetch spectral response functions for ', self.satellite)

        self.SRFs = xr.open_dataset(srf_file)

    def load_product(self, add_time=True, **kwargs):

        self.load_bands(add_time=add_time, **kwargs)
        self.load_geom()
        self.load_mask()
        self.prod = xr.merge([self.prod, self.geom,self.mask])
        del self.geom,self.mask

        # -----------------------------------------------------------
        # convert band from normalized radiance into reflectance
        # -----------------------------------------------------------
        self.prod['bands']=self.prod['bands'] / np.cos(np.radians(self.prod['sza']))


        self.prod.attrs = self.prod.attrs
        self.prod.attrs['satellite'] = self.satellite
        self.prod.attrs['solar_irradiance'] = 'NA'  # self.solar_irradiance #[:, 1]
        self.prod.attrs['solar_irradiance_unit'] = 'W/m²/µm'
        self.prod.attrs['acquisition_date'] = str(self.acquisition_date)



    def load_mask(self):
        self.mask = self.reader.load([RAW_CLOUDS], pixel_size=self.resolution
                                   ).squeeze().rename(
                                    {RAW_CLOUDS: "l1c_flag"}).astype(np.uint32)

    def load_bands(self, add_time=True, **kwargs):

        # ----------------------------------
        # getting bands
        # ----------------------------------
        bands = self.reader.stack(list(BAND_NAMES_EOREADER[self.band_idx]), resolution=self.resolution, **kwargs)
        # fix for naming in differnt EOreader versions
        if 'z' in bands.coords:
            bands = bands.rename({'z': 'bands'})

        # ----------------------------------
        # setting up coordinates and dimensions
        # ----------------------------------
        self.prod = bands.assign_coords(wl=('bands', self.INFO.loc['Wavelength (nm)'])). \
            swap_dims({'bands': 'wl'}).drop({'band', 'bands', 'variable'})
        self.prod = self.prod.assign_coords(bandID=('wl', self.INFO.loc['ESA'].values))
        self.prod = self.prod.to_dataset(name='bands', promote_attrs=True)
        self.prod.attrs['wl_to_process'] = WAVELENGTH[self.band_tbp_idx]

        # add spectral response function
        self.prod = xr.merge([self.prod, self.SRFs.sel(wl=self.prod.wl.values)]).drop_vars('bandID')

        # compute central wavelengths
        wl_true = []
        for wl_, srf in self.prod.SRF.groupby('wl'):
            srf = srf.dropna('wl_hr')
            wl_true.append((srf.wl_hr * srf).integrate('wl_hr') / srf.integrate('wl_hr'))
        wl_true = xr.concat(wl_true, dim='wl')
        wl_true.name = 'wl_true'
        self.prod = xr.merge([self.prod, wl_true])

        # add time
        if add_time:
            self.prod = self.prod.assign_coords(time=self.datetime) #.expand_dims('time')
        # self.prod.clear()

    def load_geom(self, scale_factor=0.01,
                  nodata=0,
                  geoms=(['sza', 'SZA'], ['vza', 'VZA'], ['vaa', 'VAA'], ['saa', 'SAA'])):

        # basic angle loading from geotiff (mean value of bands, needs to be improved for each band separately)

        geom = []
        for geom_ in geoms:
            ang_file = glob.glob(opj(self.abspath, '*' + geom_[1] + '.TIF'))[0]
            raster = xrio.open_rasterio(ang_file).squeeze()
            raster.rio.write_nodata(nodata, inplace=True)
            raster = raster.where(raster != raster.rio.nodata) * scale_factor

            raster.name = geom_[0]
            geom.append(raster)
        geom = xr.merge(geom)
        geom['raa'] = (geom['saa'] - geom['vaa'])  # %360
        self.geom = geom.drop_vars(['vaa', 'saa'])

    @staticmethod
    def scat_angle(sza, vza, azi):
        '''
        self.azi: azimuth in rad for convention azi=180 when sun-sensor in opposition
        :return: scattering angle in deg
        '''

        sza = np.radians(sza)
        vza = np.radians(vza)
        azi = np.radians(azi)
        ang = -np.cos(sza) * np.cos(vza) - np.sin(sza) * np.sin(vza) * np.cos(azi)
        ang = np.arccos(ang)
        return np.degrees(ang)

# ------------------------------------------------------------------------------------------
# ------------------------------------------------------------------------------------------
# ------------------------------------------------------------------------------------------
