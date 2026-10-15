'''
Driver for Landsat 8 and 9 (OLI/TIRS) Collection 2 Level-1 products.

Reads the bands (GeoTIFF) and converts them to TOA reflectance or brightness
temperature with the coefficients of the ``*_MTL.xml`` metadata file, and loads
the sun/viewing angles from the angle GeoTIFFs and the L1 quality bitmask
(see :class:`LandsatDriver`).
'''

import datetime
import glob
import math
import os

import numpy as np
import pandas as pd
import geopandas as gpd
import xarray as xr
import rioxarray as xrio
import rasterio
import xmltodict

from rasterio.enums import Resampling
from affine import Affine
from shapely.geometry import box

from importlib_resources import files

from . import __package__
from .utils import use_dask, read_on_grid

opj = os.path.join

BAND_NAMES = np.array(['B01', 'B02', 'B03', 'B08', 'B04', 'B05', 'B09', 'B06', 'B07','B08','B09'])
BAND_LONG_NAMES = np.array(['CA', 'BLUE', 'GREEN', 'PAN', 'RED', 'NIR',
                            'SWIR_CIRRUS', 'SWIR_1', 'SWIR_2','TIR_1','TIR_2'])
# band number in the Landsat file names (``*_B<n>.TIF``) and metadata
BAND_NUMBER = np.array([1, 2, 3, 8, 4, 5, 9, 6, 7, 10, 11])

BAND_ID = [b.replace('B', '') for b in BAND_NAMES]
NATIVE_RESOLUTION = [30, 30, 30, 15, 30, 30, 30, 30, 30,100,100]
WAVELENGTH = np.array([443, 490, 560, 590, 665, 865, 1370, 1610, 2190,11000,12000])
BAND_WIDTH = [25, 60, 60, 173, 33, 28, 21, 95, 287,590,1010]

INFO = pd.DataFrame({'bandId': range(len(BAND_NAMES)),
                     'ESA': BAND_NAMES,
                     'name': BAND_LONG_NAMES,
                     'Landsat band': BAND_NUMBER,
                     'Wavelength (nm)': WAVELENGTH,
                     'Band width (nm)': BAND_WIDTH,
                     'Resolution (m)': NATIVE_RESOLUTION}).set_index('bandId').T

# QA_PIXEL value of the fill (no data) pixels
QA_FILL = 1


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
      (wavelength <= 3000 nm, divided by cos(sza)); brightness temperature (K)
      for the TIR bands
    - ``sza``, ``vza`` (y, x): solar and viewing zenith angles (deg)
    - ``raa`` (y, x): relative azimuth, solar - viewing azimuth (deg)
    - ``flags_l1`` (y, x): L1 quality bitmask (``QA_PIXEL``), uint32
    - ``SRF`` (wl, wl_hr): spectral response function of each band
    - ``wl_true`` (wl): central wavelength computed from the SRF (nm)
    - coordinates ``wl`` (nominal wavelength, nm), ``x``, ``y`` (product CRS)
      and ``time``.

    The output grid has the pixel size ``resolution`` and is aligned on the
    upper-left corner of the scene. The bands are averaged when degraded
    (e.g. PAN or 30 m bands at 60 m), bilinearly interpolated when refined,
    and the bitmask is resampled with nearest neighbour. Fill pixels
    (``QA_PIXEL`` = 1 or DN = 0) are set to NaN and negative values to 0.

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
    :param subset: optional spatial subset: a ``geopandas.GeoSeries`` or
        ``GeoDataFrame`` (any CRS, its bounding box is used), or a sequence whose
        first element is the bounding box ``(minx, miny, maxx, maxy)`` in the
        product CRS
    :param resolution: pixel size (m) of the output bands
    :param verbose: verbosity flag
    '''

    def __init__(self, image_path,
                 band_idx=[0, 1, 2, 3, 4, 5, 6, 7, 8],
                 band_tbp_idx=[0, 1, 2, 3, 4, 5, 7, 8],
                 subset=None,
                 resolution=30,
                 verbose=False):

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

        # --------------------------------
        # metadata
        # --------------------------------
        mtd_files = glob.glob(opj(self.abspath, '*_MTL.xml'))
        if not mtd_files:
            raise FileNotFoundError('No *_MTL.xml metadata file in ' + self.abspath)
        self.mtd_file = mtd_files[0]
        with open(self.mtd_file) as f:
            self.metadata = xmltodict.parse(f.read())['LANDSAT_METADATA_FILE']
        content = self.metadata['PRODUCT_CONTENTS']
        image = self.metadata['IMAGE_ATTRIBUTES']

        self.product_name = content['LANDSAT_PRODUCT_ID']
        # LANDSAT_9 -> Landsat-9, L9
        spacecraft = image['SPACECRAFT_ID']
        self.satellite = spacecraft.replace('LANDSAT_', 'Landsat-')
        self.constellation_id = spacecraft.replace('LANDSAT_', 'L')
        self.instrument = image['SENSOR_ID'].replace('_', '-')
        self.tile = '{:03d}{:03d}'.format(int(image['WRS_PATH']), int(image['WRS_ROW']))
        self.cloud_cover = float(image['CLOUD_COVER'])
        self.datetime = datetime.datetime.strptime(
            image['DATE_ACQUIRED'] + 'T' + image['SCENE_CENTER_TIME'][:8], '%Y-%m-%dT%H:%M:%S')
        self.acquisition_date = self.datetime

        # save geographic data (from the QA_PIXEL band, on the 30 m grid of the scene)
        with rasterio.open(self._get_file('QA_PIXEL')) as src:
            self.crs = src.crs
            minx, miny, maxx, maxy = src.bounds
        self.epsg = self.crs.to_epsg()
        self.extent = gpd.GeoDataFrame(geometry=[box(minx, miny, maxx, maxy)], crs=self.crs)
        self.bounds = self.extent.bounds

        self.transform = Affine(resolution, 0., minx, 0., -resolution, maxy)
        self.width = int(round((maxx - minx) / resolution))
        self.height = int(round((maxy - miny) / resolution))

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
                     add_time=True):
        '''
        Load bands, geometry and L1 flags into ``self.prod`` and convert the
        vis-NIR-SWIR bands into TOA reflectance. The flags already loaded
        with :meth:`load_mask` are reused.

        :param add_time: add the acquisition date as ``time`` coordinate
        '''

        self.load_bands(subset=self.subset,add_time=add_time)
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

    def _get_file(self, suffix):
        '''
        Path of the product file ``*_<suffix>.TIF`` (e.g. ``B4``, ``QA_PIXEL``).
        '''
        file = glob.glob(opj(self.abspath, '*_' + suffix + '.TIF'))
        if not file:
            raise FileNotFoundError('No *_' + suffix + '.TIF file in ' + self.abspath)
        return file[0]

    def _get_window(self, subset):
        '''
        Convert ``subset`` (see :class:`LandsatDriver`) into bounds
        ``(minx, miny, maxx, maxy)`` in the product CRS.
        '''
        if subset is None:
            return None
        if hasattr(subset, 'to_crs'):
            return tuple(subset.to_crs(self.crs).total_bounds)
        return tuple(subset[0])

    def _get_grid(self, subset=None):
        '''
        Output grid: the scene grid at the product resolution, cropped to the
        pixels intersecting ``subset`` (see :class:`LandsatDriver`).

        :return: (transform, width, height)
        '''
        res = self.resolution
        x0, y0 = self.transform.c, self.transform.f
        col0, col1, row0, row1 = 0, self.width, 0, self.height
        window = self._get_window(subset)
        if window is not None:
            minx, miny, maxx, maxy = window
            col0 = max(col0, math.floor((minx - x0) / res))
            col1 = min(col1, math.ceil((maxx - x0) / res))
            row0 = max(row0, math.floor((y0 - maxy) / res))
            row1 = min(row1, math.ceil((y0 - miny) / res))
            if col1 <= col0 or row1 <= row0:
                raise ValueError('subset does not intersect the image ' + self.abspath)
        transform = Affine(res, 0., x0 + col0 * res, 0., -res, y0 - row0 * res)
        return transform, col1 - col0, row1 - row0

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

    def _read_qa(self, grid, chunks=None):
        '''
        Read ``QA_PIXEL`` on ``grid`` (see :meth:`_get_grid`) with nearest neighbour,
        pixels outside the scene set to fill.
        '''
        return read_on_grid(self._get_file('QA_PIXEL'), *grid,
                            resampling=Resampling.nearest, nodata=QA_FILL, chunks=chunks)

    def _read_band(self, band_number, grid, qa=None, chunks=None):
        '''
        Read band ``band_number`` on ``grid`` (see :meth:`_get_grid`) and convert
        the DN into TOA reflectance (not divided by cos(sza)) or, for the thermal
        bands, into brightness temperature (K). Fill pixels are set to NaN
        and negative values to 0.

        :param band_number: Landsat band number (1 to 11)
        :param grid: output grid (transform, width, height)
        :param qa: ``QA_PIXEL`` on ``grid``, read if not provided
        :param chunks: dask chunks (lazy reading), ``None`` to load into memory
        :return: DataArray (y, x), float32
        '''
        path = self._get_file('B' + str(band_number))
        with rasterio.open(path) as src:
            native_res = src.res[0]
        if self.resolution > native_res:
            resampling = Resampling.average
        elif self.resolution < native_res:
            resampling = Resampling.bilinear
        else:
            resampling = Resampling.nearest
        # resampling computed in float32 (no rounding of averaged DN)
        dn = read_on_grid(path, *grid, resampling=resampling, nodata=0, dtype='float32', chunks=chunks)
        if qa is None:
            qa = self._read_qa(grid, chunks=chunks)
        valid = (dn != 0) & (qa != QA_FILL)

        rescaling = self.metadata['LEVEL1_RADIOMETRIC_RESCALING']
        if band_number in (10, 11):
            # DN -> radiance -> brightness temperature
            thermal = self.metadata['LEVEL1_THERMAL_CONSTANTS']
            gain = np.float32(rescaling['RADIANCE_MULT_BAND_' + str(band_number)])
            offset = np.float32(rescaling['RADIANCE_ADD_BAND_' + str(band_number)])
            k1 = np.float32(thermal['K1_CONSTANT_BAND_' + str(band_number)])
            k2 = np.float32(thermal['K2_CONSTANT_BAND_' + str(band_number)])
            band = k2 / np.log(k1 / (gain * dn + offset) + np.float32(1))
        else:
            gain = np.float32(rescaling['REFLECTANCE_MULT_BAND_' + str(band_number)])
            offset = np.float32(rescaling['REFLECTANCE_ADD_BAND_' + str(band_number)])
            band = gain * dn + offset
        return band.clip(min=0).where(valid).astype(np.float32)

    def load_mask(self):
        '''
        Load the L1 quality bitmask (``QA_PIXEL``) in ``self.mask``
        (variable ``flags_l1``) at the product resolution and subset.
        '''
        chunks = True if use_dask() else None
        qa = self._read_qa(self._get_grid(self.subset), chunks=chunks).astype(np.uint32)
        # fill pixels are valid flag values: no _FillValue (would be decoded as NaN)
        qa.attrs, qa.encoding = {}, {}
        self.mask = qa.to_dataset(name='flags_l1')

    def load_bands(self,
                   subset=None,
                   add_time=True):
        '''
        Load the bands into ``self.prod`` (variable ``bands``) along with the
        spectral response functions (``SRF``) and the central wavelengths
        (``wl_true``). Vis-NIR-SWIR bands are not yet divided by cos(sza),
        see :meth:`load_product`.

        :param subset: spatial subset (see :class:`LandsatDriver`)
        :param add_time: add the acquisition date as ``time`` coordinate
        '''

        # ----------------------------------
        # getting bands
        # ----------------------------------
        grid = self._get_grid(subset)
        chunks = True if use_dask() else None
        qa = self._read_qa(grid, chunks=chunks)
        band_numbers = self.INFO.loc['Landsat band'].values
        if chunks:
            bands = xr.concat([self._read_band(n, grid, qa=qa, chunks=chunks) for n in band_numbers],
                              dim='bands')
        else:
            # bands loaded one by one into a preallocated array (low memory)
            bands = None
            for iband, band_number in enumerate(band_numbers):
                band = self._read_band(band_number, grid, qa=qa)
                if bands is None:
                    bands = xr.DataArray(np.empty((len(band_numbers),) + band.shape, dtype=np.float32),
                                         dims=('bands',) + band.dims, coords=band.coords)
                bands.values[iband] = band.values
                del band
        del qa
        bands.rio.write_nodata(np.nan, encoded=True, inplace=True)

        # ----------------------------------
        # setting up coordinates and dimensions
        # ----------------------------------
        self.prod = bands.assign_coords(wl=('bands', self.INFO.loc['Wavelength (nm)'])). \
            swap_dims({'bands': 'wl'}).drop_vars(['band', 'bands', 'variable'], errors='ignore')
        self.prod['wl'] = self.prod.wl.astype(float)
        self.prod = self.prod.assign_coords(bandID=('wl', self.INFO.loc['ESA'].values))
        self.prod = self.prod.to_dataset(name='bands')
        self.prod.attrs = self._product_attrs()
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

    def _product_attrs(self):
        '''
        Product metadata stored as attributes of ``prod``.
        '''
        names = self.INFO.loc['name'].values
        is_tir = np.isin(names, ['TIR_1', 'TIR_2'])
        if is_tir.all():
            radiometry = 'brightness temperature'
        elif is_tir.any():
            radiometry = 'reflectance and brightness temperature'
        else:
            radiometry = 'reflectance'
        return {'long_name': ' '.join(names),
                'constellation': self.satellite,
                'constellation_id': self.constellation_id,
                'product_path': self.abspath,
                'product_name': self.product_name,
                'instrument': self.instrument,
                'product_type': 'L1',
                'tile': self.tile,
                'acquisition_date': str(self.datetime),
                'condensed_name': '{:%Y%m%dT%H%M%S}_{}_{}_{}'.format(
                    self.datetime, self.constellation_id, self.tile, self.instrument.replace('-', '_')),
                'radiometry': radiometry,
                'cloud_cover': self.cloud_cover}

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

        # lazy reading in dask mode
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
