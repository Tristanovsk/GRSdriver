'''
Driver for Landsat 8 and 9 (OLI/TIRS) Collection 2 Level-1 products.

Loads the bands with EOReader, the sun/viewing angles from the angle
GeoTIFFs and the L1 quality bitmask (see :class:`LandsatDriver`).
'''

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
from eoreader.utils import use_dask

from . import __package__
from .utils import stack_bands

opj = os.path.join

BAND_NAMES = np.array(['B01', 'B02', 'B03', 'B08', 'B04', 'B05', 'B09', 'B06', 'B07','B08','B09'])
BAND_NAMES_EOREADER = np.array(['CA', 'BLUE', 'GREEN', 'PAN', 'RED', 'NIR',
                                'SWIR_CIRRUS', 'SWIR_1', 'SWIR_2','TIR_1','TIR_2'])

BAND_ID = [b.replace('B', '') for b in BAND_NAMES]
NATIVE_RESOLUTION = [30, 30, 30, 15, 30, 30, 30, 30, 30,100,100]
WAVELENGTH = np.array([443, 490, 560, 590, 665, 865, 1370, 1610, 2190,11000,12000])
BAND_WIDTH = [25, 60, 60, 173, 33, 28, 21, 95, 287,590,1010]

INFO = pd.DataFrame({'bandId': range(len(BAND_NAMES)),
                     'ESA': BAND_NAMES,
                     'EOREADER': BAND_NAMES_EOREADER,
                     'Wavelength (nm)': WAVELENGTH,
                     'Band width (nm)': BAND_WIDTH,
                     'Resolution (m)': NATIVE_RESOLUTION}).set_index('bandId').T


class LandsatDriver():
    '''
    Load a Landsat 8 or 9 Collection 2 Level-1 image as an xarray Dataset with
    TOA reflectance, spectral response functions, geometry and L1 flags.

    Usage::

        l1 = LandsatDriver('LC09_L1TP_..._T1', resolution=30)
        l1.load_product()
        prod = l1.prod

    Content of ``prod`` after :meth:`load_product`:

    - ``bands`` (wl, y, x): TOA reflectance for vis-NIR-SWIR bands
      (wavelength <= 3000 nm, divided by cos(sza)); TIR bands as provided
      by EOReader (brightness temperature)
    - ``sza``, ``vza`` (y, x): solar and viewing zenith angles (deg)
    - ``raa`` (y, x): relative azimuth, solar - viewing azimuth (deg)
    - ``flags_l1`` (y, x): L1 quality bitmask (``QA_PIXEL``), uint32
    - ``SRF`` (wl, wl_hr): spectral response function of each band
    - ``wl_true`` (wl): central wavelength computed from the SRF (nm)
    - coordinates ``wl`` (nominal wavelength, nm), ``x``, ``y`` (product CRS)
      and ``time``.

    The angles are those of the scene angle files (``*SZA.TIF``, ``*VZA.TIF``...),
    i.e. not band specific. They are interpolated only if their grid differs from
    the bands (other ``resolution`` or ``subset``).

    With ``EOREADER_USE_DASK=1`` set before importing GRSdriver, the product is
    lazy (dask-backed) and all variables share the chunks of the bands.

    :param image_path: path to the directory of the L1 product
    :param band_idx: indices of the bands to load, in
        ``CA, BLUE, GREEN, PAN, RED, NIR, SWIR_CIRRUS, SWIR_1, SWIR_2, TIR_1, TIR_2``
        (0 to 10); TIR bands excluded by default
    :param band_tbp_idx: indices of the bands to be processed downstream
        (stored as ``prod.attrs['wl_to_process']``); by default all but cirrus
    :param subset: optional spatial subset: a ``geopandas.GeoSeries`` (any CRS,
        its bounding box is used), or a sequence whose first element is passed as
        ``window`` to EOReader
    :param resolution: pixel size (m) of the output bands
    :param verbose: verbosity flag
    :param kwargs: passed to ``eoreader.reader.Reader.open``
    '''

    def __init__(self, image_path,
                 band_idx=[0, 1, 2, 3, 4, 5, 6, 7, 8],
                 band_tbp_idx=[0, 1, 2, 3, 4, 5, 7, 8],
                 subset=None,
                 resolution=30,
                 verbose=False,
                 **kwargs):

        self.abspath = os.path.abspath(image_path)
        dirroot, basename = os.path.split(self.abspath)
        self.verbose = verbose
        self.band_idx = band_idx
        self.band_tbp_idx = band_tbp_idx
        self.subset = subset
        self.resolution = resolution
        self.INFO = INFO[band_idx]

        # -----------------------------------------------------
        # define prod and geom where data will be loaded
        # -----------------------------------------------------
        self.prod = xr.Dataset()
        self.geom = xr.Dataset()
        self.mask = None

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
            srf_file = files(__package__+'.rsr.data').joinpath('rsr_landsat_8_oli_tirs.nc')
        elif '9' in self.satellite:
            srf_file = files(__package__+'.rsr.data').joinpath('rsr_landsat_9_oli_tirs.nc')
        else:
            print('Problem to fetch spectral response functions for ', self.satellite)

        self.SRFs = xr.open_dataset(srf_file)

    def load_product(self,
                     add_time=True,
                     **kwargs):
        '''
        Load bands, geometry and L1 flags into ``self.prod`` and convert the
        vis-NIR-SWIR bands into TOA reflectance. The flags already loaded
        with :meth:`load_mask` are reused.

        :param add_time: add the acquisition date as ``time`` coordinate
        :param kwargs: passed to ``eoreader`` ``stack`` (see :meth:`load_bands`)
        '''

        self.load_bands(subset=self.subset,add_time=add_time, **kwargs)
        self.load_geom()
        if self.mask is None:
            self.load_mask()
        # bitmask: nearest neighbour only, kept as integer
        mask = self._match_grid(self.mask, method='nearest')
        mask['flags_l1'] = mask.flags_l1.fillna(0).astype(np.uint32)
        self.prod = xr.merge([self.prod,
                              self._match_grid(self.geom, method='linear'),
                              mask],compat='override')
        self.geom, self.mask = None, None

        # -----------------------------------------------------------
        # convert band from normalized radiance into reflectance
        # vis-NIR-SWIR bands only (upper limit 3000nm)
        # -----------------------------------------------------------
        mus = np.cos(np.radians(self.prod['sza'])).astype(self.prod.bands.dtype)
        self.prod['bands'] = xr.where(self.prod.wl <= 3000, self.prod.bands / mus, self.prod.bands,
                                      keep_attrs=True).transpose(*self.prod.bands.dims)


        self.prod.attrs = self.prod.attrs
        self.prod.attrs['satellite'] = self.satellite
        self.prod.attrs['solar_irradiance'] = 'NA'  # self.solar_irradiance #[:, 1]
        self.prod.attrs['solar_irradiance_unit'] = 'W/m²/µm'
        self.prod.attrs['acquisition_date'] = str(self.acquisition_date)



    def _get_window(self, subset):
        '''
        Convert ``subset`` (see :class:`LandsatDriver`) into an EOReader window.
        '''
        if subset is None:
            return None
        if subset.dtype == 'geometry':
            return subset.to_crs(self.crs).bounds.values[0]
        return subset[0]

    def _match_grid(self, ds, method='linear'):
        '''
        Put ``ds`` on the (x, y) grid of ``self.prod``: no-op when the grids already coincide,
        otherwise ``ds`` is clipped to the product extent before being interpolated.
        ``ds`` is chunked as the bands when they are dask-backed.

        :param ds: xarray Dataset with ``x`` and ``y`` coordinates
        :param method: interpolation method (``nearest`` for bitmasks)
        :return: ``ds`` on the grid of ``self.prod``
        '''
        x, y = self.prod.x.values, self.prod.y.values
        if ds.x.size == x.size and ds.y.size == y.size and \
                np.allclose(ds.x.values, x) and np.allclose(ds.y.values, y):
            ds = ds.assign_coords(x=self.prod.x, y=self.prod.y)
        else:
            margin = 2 * max(abs(float(ds.x[1] - ds.x[0])), abs(float(ds.y[1] - ds.y[0])))
            ds = ds.sel(x=slice(x.min() - margin, x.max() + margin),
                        y=slice(y.max() + margin, y.min() - margin))
            ds = ds.interp(x=self.prod.x, y=self.prod.y, method=method)
        if self.prod.bands.chunks is not None:
            ds = ds.chunk({dim: self.prod.bands.chunksizes[dim] for dim in ('y', 'x')})
        return ds

    def load_mask(self):
        '''
        Load the L1 quality bitmask (``QA_PIXEL``) in ``self.mask``
        (variable ``flags_l1``) at the product resolution and subset.
        '''
        self.mask = self.reader.load([RAW_CLOUDS], pixel_size=self.resolution,
                                     window=self._get_window(self.subset)
                                     ).squeeze().rename(
                                        {RAW_CLOUDS: "flags_l1"}).astype(np.uint32).drop_vars('band')

    def load_bands(self,
                   subset=None,
                   add_time=True,
                   **kwargs):
        '''
        Load the bands into ``self.prod`` (variable ``bands``) along with the
        spectral response functions (``SRF``) and the central wavelengths
        (``wl_true``). Vis-NIR-SWIR bands are not yet divided by cos(sza),
        see :meth:`load_product`.

        :param subset: spatial subset (see :class:`LandsatDriver`)
        :param add_time: add the acquisition date as ``time`` coordinate
        :param kwargs: passed to ``eoreader`` ``stack``
        '''

        # ----------------------------------
        # getting bands
        # ----------------------------------
        window = self._get_window(subset)
        bands = stack_bands(self.reader, list(BAND_NAMES_EOREADER[self.band_idx]),
                                  pixel_size=self.resolution,
                                  window=window,
                                  **kwargs)
        # fix for naming in differnt EOreader versions
        if 'z' in bands.coords:
            bands = bands.rename({'z': 'bands'})

        # ----------------------------------
        # setting up coordinates and dimensions
        # ----------------------------------
        self.prod = bands.assign_coords(wl=('bands', self.INFO.loc['Wavelength (nm)'])). \
            swap_dims({'bands': 'wl'}).drop_vars(['band', 'bands', 'variable'], errors='ignore')
        self.prod['wl'] = self.prod.wl.astype(float)
        self.prod = self.prod.assign_coords(bandID=('wl', self.INFO.loc['ESA'].values))
        self.prod = self.prod.to_dataset(name='bands', promote_attrs=True)
        self.prod.attrs['wl_to_process'] = WAVELENGTH[self.band_tbp_idx]

        # add spectral response function
        self.prod = xr.merge([self.prod, self.SRFs.sel(wl=self.prod.wl.values,method="nearest")],
                             compat='override').drop_vars('bandID')

        # compute central wavelengths
        wl_true = []
        for wl_, srf in self.prod.SRF.groupby('wl'):
            srf = srf.dropna('wl_hr')
            wl_true.append((srf.wl_hr * srf).integrate('wl_hr') / srf.integrate('wl_hr'))
        wl_true = xr.concat(wl_true, dim='wl')
        wl_true.name = 'wl_true'
        self.prod = xr.merge([self.prod, wl_true],compat='override')

        # add time
        if add_time:
            self.prod = self.prod.assign_coords(time=self.datetime) #.expand_dims('time')
        # self.prod.clear()

    def load_geom(self, scale_factor=0.01,
                  nodata=0,
                  geoms=(['sza', 'SZA'], ['vza', 'VZA'], ['vaa', 'VAA'], ['saa', 'SAA'])):
        '''
        Load the angles from the angle GeoTIFFs of the product into ``self.geom``
        (``sza``, ``vza`` and ``raa`` = saa - vaa, in deg, float32), on their native grid.

        :param scale_factor: scale factor of the stored integer values
        :param nodata: no-data value of the stored integer values
        :param geoms: pairs (output name, file suffix) of the angle files
        '''

        # basic angle loading from geotiff (mean value of bands, needs to be improved for each band separately)

        # lazy reading when EOReader works with dask
        chunks = True if use_dask() else None
        geom = []
        for geom_ in geoms:
            ang_file = glob.glob(opj(self.abspath, '*' + geom_[1] + '.TIF'))[0]
            raster = xrio.open_rasterio(ang_file, chunks=chunks).squeeze()
            raster.rio.write_nodata(nodata, inplace=True)
            raster = raster.where(raster != raster.rio.nodata).astype(np.float32) * np.float32(scale_factor)

            raster.name = geom_[0]
            geom.append(raster)
        geom = xr.merge(geom,compat='override')
        geom['raa'] = (geom['saa'] - geom['vaa'])  # %360
        self.geom = geom.drop_vars(['vaa', 'saa','band'])

    @staticmethod
    def scat_angle(sza, vza, azi):
        '''
        Scattering angle from the sun and viewing angles.

        :param sza: solar zenith angle (deg)
        :param vza: viewing zenith angle (deg)
        :param azi: relative azimuth (deg), convention azi=180 when sun and sensor are in opposition
        :return: scattering angle (deg)
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
