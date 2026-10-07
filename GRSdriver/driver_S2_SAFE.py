'''
Driver for Sentinel-2 MSI Level-1C products (SAFE format).

Loads the top-of-atmosphere reflectance bands with EOReader and computes the
per-band sun and viewing geometry from the granule metadata
(see :class:`Sentinel2Driver`).
'''

import gc
import glob
import os
import xml.etree.ElementTree as ET

import numpy as np
import dask.array as da
from numba import jit

import pandas as pd
import geopandas as gpd
import xarray as xr
import xmltodict

from rasterio.features import rasterize
import scipy.odr as odr
from affine import Affine
from osgeo import gdal, ogr
#import cartopy.crs as ccrs
from pyproj import CRS
import eoreader as eo

from eoreader.reader import Reader
from eoreader.env_vars import USE_DASK

from . import __package__
from .utils import stack_bands

# EOReader uses dask if == 1. Default to "0": with dask, EOReader computes and writes
# each cleaned band to its disk cache through a much slower path (~3x for a full S2 tile).
# Set EOREADER_USE_DASK=1 beforehand to get lazy (dask-backed) products.
os.environ.setdefault(USE_DASK, "0")

opj = os.path.join
BAND_NAMES = np.array(['B01', 'B02', 'B03', 'B04', 'B05', 'B06', 'B07', 'B08', 'B8A', 'B09', 'B10', 'B11', 'B12'])
BAND_NAMES_EOREADER = np.array(['CA', 'BLUE', 'GREEN', 'RED', 'VRE_1',
                                'VRE_2', 'VRE_3', 'NIR', 'NARROW_NIR',
                                'WV', 'SWIR_CIRRUS', 'SWIR_1', 'SWIR_2'])

BAND_ID = [b.replace('B', '') for b in BAND_NAMES]
NATIVE_RESOLUTION = [60, 10, 10, 10, 20, 20, 20, 10, 20, 60, 60, 20, 20]
WAVELENGTH = np.array([443, 490, 560, 665, 705, 740, 783, 842, 865, 945, 1375, 1610, 2190])
BAND_WIDTH = [20, 65, 35, 30, 15, 15, 20, 115, 20, 20, 30, 90, 180]

INFO = pd.DataFrame({'bandId': range(13),
                     'ESA': BAND_NAMES,
                     'EOREADER': BAND_NAMES_EOREADER,
                     'Wavelength (nm)': WAVELENGTH,
                     'Band width (nm)': BAND_WIDTH,
                     'Resolution (m)': NATIVE_RESOLUTION}).set_index('bandId').T


def _take_yx(iy, ix, src):
    '''
    Block of a lazy nearest-neighbour lookup: ``src[..., iy, :][..., ix]``.
    '''
    return src.take(iy, axis=-2).take(ix, axis=-1)


class Sentinel2Driver():
    '''
    Load a Sentinel-2 L1C image (SAFE format) as an xarray Dataset with
    TOA reflectance, spectral response functions and per-band viewing geometry.

    The viewing angles are provided in the metadata on a coarse 5 km grid for
    each band and each detector. For each band and detector, a plane is fitted
    to these values (orthogonal distance regression); the plane of the detector
    seen by each pixel (detector footprint mask ``DETFOO``) is then evaluated on
    the ``resolution_angle`` grid. The result is resampled (nearest neighbour)
    on the grid of the bands.

    Usage::

        l1c = Sentinel2Driver('S2A_MSIL1C_..._.SAFE', resolution=20)
        l1c.load_product()
        prod = l1c.prod

    Content of ``prod`` after :meth:`load_product`:

    - ``bands`` (wl, y, x): TOA reflectance
    - ``vza`` (wl, y, x): viewing zenith angle (deg)
    - ``raa`` (wl, y, x): relative azimuth, (viewing - solar azimuth) % 360 (deg)
    - ``sza`` (y, x): solar zenith angle (deg)
    - ``SRF`` (wl, wl_hr): spectral response function of each band
    - ``wl_true`` (wl): central wavelength computed from the SRF (nm)
    - coordinates ``wl`` (nominal wavelength, nm), ``x``, ``y`` (product CRS)
      and ``time``; native metadata and solar irradiance in ``attrs``.

    EOReader returns numpy arrays by default: with dask enabled, EOReader
    computes and writes each band in its cache through a much slower path.
    Set the environment variable ``EOREADER_USE_DASK=1`` before importing
    GRSdriver to get a lazy (dask-backed) product; the geometry is then chunked
    as the bands.

    :param imageSAFE: path to the ``.SAFE`` directory of the L1C product
    :param band_idx: indices of the bands to load, in
        ``B01, B02, B03, B04, B05, B06, B07, B08, B8A, B09, B10, B11, B12``
        (0 to 12)
    :param band_tbp_idx: indices of the bands to be processed downstream
        (stored as ``prod.attrs['wl_to_process']``); by default all but
        B09 (water vapour) and B10 (cirrus)
    :param subset: optional spatial subset: a ``geopandas.GeoSeries`` (any CRS,
        its bounding box is used), or a sequence whose first element is passed as
        ``window`` to EOReader
    :param resolution: pixel size (m) of the output bands
    :param resolution_angle: pixel size (m) of the grid on which the viewing
        angles are computed: 10, 20 or 60 (coarser is faster and lighter)
    :param lazy_geom: keep ``vza`` and ``raa`` as dask arrays, computed block by
        block from the ``resolution_angle`` grid when they are used, instead of
        storing them at the band resolution (saves ``2 x 4 x Nwl x Ny x Nx`` bytes,
        e.g. 3.1 GB for 13 bands at 20 m, 12.5 GB at 10 m); always the case when
        the bands are dask-backed
    :param geom_chunks: size (pixels) of the ``y`` and ``x`` chunks of the lazy
        geometry when the bands are not dask-backed
    :param verbose: print progress and fitting reports
    :param kwargs: passed to ``eoreader.reader.Reader.open``
    '''

    def __init__(self, imageSAFE,
                 band_idx=[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
                 band_tbp_idx=[0, 1, 2, 3, 4, 5, 6, 7, 8, 11, 12],
                 subset=None,
                 resolution=20,
                 resolution_angle=60,
                 lazy_geom=False,
                 geom_chunks=1024,
                 verbose=False,
                 **kwargs):

        abspath = os.path.abspath(imageSAFE)
        dirroot, basename = os.path.split(abspath)
        self.verbose = verbose
        self.band_idx = band_idx
        self.band_tbp_idx = band_tbp_idx
        self.subset = subset
        self.resolution_angle = resolution_angle
        self.resolution = resolution
        self.lazy_geom = lazy_geom
        self.geom_chunks = geom_chunks
        self.INFO = INFO[band_idx]

        # -----------------------------------------------------
        # define prod and geom where data will be loaded
        # -----------------------------------------------------
        self.prod = xr.Dataset()
        self.geom = xr.Dataset()

        # --------------------------------
        # define interpolation parameters
        # --------------------------------
        # tile for 10m resolution: width,height = 10980,10980
        # tile for 20m resolution: width,height = 5490,5490
        # tile for 60m resolution: width,height = 1830,1830
        if resolution_angle == 10:
            self.width, self.height = 10980, 10980
        elif resolution_angle == 20:
            self.width, self.height = 5490, 5490
        elif resolution_angle == 60:
            self.width, self.height = 1830, 1830
        try:
            self.xml_granule = glob.glob(opj(imageSAFE, 'GRANULE', '*', 'MTD_TL.xml'))[0]
            self.xml_file = glob.glob(opj(imageSAFE, 'MTD*.xml'))[0]
        except:
            print('old or deprecated SAFE format detected')
            self.xml_granule = glob.glob(opj(imageSAFE, 'GRANULE', '*', '*MTD*.xml'))[0]
            self.xml_file = glob.glob(opj(imageSAFE, '*MTD*.xml'))[0]

        # get metadata and angle file
        ds = gdal.Open(self.xml_file)
        self.metadata = ds.GetMetadata()
        self.metadata2 = xmltodict.parse(ds.GetMetadata('xml:SENTINEL2')[0])
        __ = []
        for _ in self.metadata2['n1:Level-1C_User_Product']['n1:General_Info']['Product_Image_Characteristics'][
            'Reflectance_Conversion']['Solar_Irradiance_List']['SOLAR_IRRADIANCE']:
            __.append([int(_['@bandId']), float(_['#text'])])
        self.solar_irradiance = np.array(__)

        # Spectral Response Functions
        SRFs = []
        wl_hr = np.arange(400, 2350)
        for _ in self.metadata2['n1:Level-1C_User_Product'][
            'n1:General_Info']['Product_Image_Characteristics']['Spectral_Information_List']['Spectral_Information']:

            bandID = int(_['@bandId'])
            if not self.band_idx.__contains__(bandID):
                continue

            wl_min, wl_max = float(_['Wavelength']['MIN']['#text']), float(_['Wavelength']['MAX']['#text'])
            step = float(_['Spectral_Response']['STEP']['#text'])
            wl = np.arange(wl_min, wl_max + step, step)
            SRF = np.asarray(_['Spectral_Response']['VALUES'].split(), dtype=np.float32)
            SRFs.append(
                xr.DataArray(SRF, coords=dict(wl_hr=wl[:len(SRF)]), name='SRF').interp(wl_hr=wl_hr).assign_coords(
                    dict(wl=WAVELENGTH[bandID])))
        self.SRFs = xr.concat(SRFs, dim='wl')
        self.SRFs.attrs['description'] = 'Spectral response function of each band'

        # Open instance of eoreader
        reader = Reader()

        # Open the product
        reader = reader.open(imageSAFE, remove_tmp=True, **kwargs)
        self.reader = reader
        self.processing_baseline = reader._processing_baseline
        self.datetime = reader.datetime

        # save geographic data
        self.extent = reader.extent()
        self.bounds = self.extent.bounds
        minx, miny, maxx, maxy = self.bounds.values[0]
        self.crs = self.reader.crs()
        self.epsg = self.extent.crs.to_epsg()
        # str_epsg = str(self.epsg)
        # zone = str_epsg[-2:]
        # is_south = str_epsg[2] == 7
        # self.proj = ccrs.UTM(zone, is_south)
        # self.proj = CRS.from_dict({'proj': 'utm', 'zone': zone, 'south': is_south})
        self.transform = Affine(resolution, 0., minx, 0., -resolution, maxy)

        # -------------------------
        # interpolation
        # -------------------------
        # set the indexing of numpy and xarray
        self.indexing = 'xy'
        self.new_x = np.linspace(minx, maxx, self.width)
        self.new_y = np.linspace(miny, maxy, self.height)[::-1]

        # ---------------------------------
        # getting appropriate version of mask driver
        # ---------------------------------
        # TODO generalize to load all available masks
        if self.processing_baseline < 4:
            self._open_mask = reader._open_mask_lt_4_0
        else:
            self._open_mask = reader._open_mask_gt_4_0

    def load_product(self,
                     add_time=True,
                     **kwargs):
        '''
        Load bands and geometry into ``self.prod`` and add the native metadata
        as attributes (``satellite``, ``tile``, ``solar_irradiance``,
        ``mean_solar_zenith_angle``, ``acquisition_date``...).

        :param add_time: add the acquisition date as ``time`` coordinate
        :param kwargs: passed to ``eoreader`` ``stack`` (see :meth:`load_bands`)
        '''

        self.load_bands(subset=self.subset, add_time=add_time, **kwargs)

        self.load_geom()
        self.geom = self._nearest_to_band_grid(self.geom)
        self.prod = xr.merge([self.prod, self.geom],compat='override')
        del self.geom

        # add native metadata
        for item in self.metadata:
            self.prod.attrs[item] = self.metadata[item]

        self.prod.attrs['satellite'] = self.prod.attrs['PRODUCT_URI'].split('_')[0]
        self.prod.attrs['tile'] = self.prod.attrs['PRODUCT_URI'].split('_')[5][1:]
        self.prod.attrs['solar_irradiance'] = self.solar_irradiance[:, 1]
        self.prod.attrs['solar_irradiance_unit'] = 'W/m²/µm'
        self.prod.attrs['mean_solar_azimuth'] = self.mean_sun_azi
        self.prod.attrs['mean_solar_zenith_angle'] = self.mean_sza
        self.prod.attrs['acquisition_date'] = self.prod.attrs['DATATAKE_1_DATATAKE_SENSING_START']

    def _nearest_to_band_grid(self, geom):
        '''
        Nearest-neighbour resampling of ``geom`` onto the (x, y) grid of ``self.prod``
        as a plain index lookup (much faster than interp).

        Eager mode: each 2D slice is filled in a preallocated array (no full-size
        temporaries). Lazy mode (``lazy_geom`` or dask-backed bands): dask arrays
        whose blocks are looked up in the ``resolution_angle`` grid when computed,
        chunked as the bands (or by ``geom_chunks``), all ``wl`` in one chunk.

        :param geom: Dataset on the ``resolution_angle`` grid
        :return: ``geom`` on the grid of ``self.prod``
        '''
        x, y = self.prod.x, self.prod.y
        ix = geom.indexes['x'].get_indexer(x.values, method='nearest')
        iy = geom.indexes['y'].get_indexer(y.values, method='nearest')
        lazy = self.lazy_geom or self.prod.bands.chunks is not None
        if lazy:
            if self.prod.bands.chunks is not None:
                chunks = {dim: self.prod.bands.chunksizes[dim] for dim in ('y', 'x')}
            else:
                chunks = {'y': self.geom_chunks, 'x': self.geom_chunks}
            iy_ = da.from_array(iy, chunks=chunks['y'])
            ix_ = da.from_array(ix, chunks=chunks['x'])

        out = xr.Dataset(coords=geom.drop_dims(['x', 'y']).coords, attrs=geom.attrs)
        for name, arr in geom.data_vars.items():
            arr = arr.transpose(..., 'y', 'x')
            src = arr.values
            if lazy:
                lead = 'abcdefgh'[:src.ndim - 2]
                new = da.blockwise(_take_yx, lead + 'yx', iy_, 'y', ix_, 'x', src=src,
                                   new_axes=dict(zip(lead, src.shape[:-2])), dtype=src.dtype)
            else:
                new = np.empty(src.shape[:-2] + (len(iy), len(ix)), dtype=src.dtype)
                for idx in np.ndindex(src.shape[:-2]):
                    np.take(src[idx].take(iy, axis=0), ix, axis=1, out=new[idx])
            out[name] = xr.DataArray(new, dims=arr.dims, attrs=arr.attrs)
            del src, new
        return out.assign_coords(x=x, y=y)

    def load_bands(self,
                   subset=None,
                   add_time=True,
                   **kwargs):
        '''
        Load the TOA reflectance bands into ``self.prod`` (variable ``bands``)
        along with the spectral response functions (``SRF``) and the central
        wavelengths (``wl_true``).

        :param subset: spatial subset (see :class:`Sentinel2Driver`); with a subset,
            the 2 edge pixels are removed to work around an EOReader issue
        :param add_time: add the acquisition date as ``time`` coordinate
        :param kwargs: passed to ``eoreader`` ``stack``
        '''

        # ----------------------------------
        # getting bands
        # ----------------------------------
        window=None
        if subset is not None:

            if subset.dtype == 'geometry':
                window = subset.to_crs(self.crs).bounds.values[0]
            else:
                window = subset[0]

            bands = stack_bands(self.reader, list(BAND_NAMES_EOREADER[self.band_idx]),
                                  pixel_size=self.resolution,
                                  window=window,
                                  **kwargs)
            # Warning!!! fix for issue in eoreader when subsetting multibands
            # needs to remove edge pixels
            Nwl, Ny, Nx = bands.shape
            bands=bands.isel(x=slice(2, Nx - 2), y=slice(2, Ny - 2))
        else:
            bands = stack_bands(self.reader, list(BAND_NAMES_EOREADER[self.band_idx]),
                                      pixel_size=self.resolution,
                                      **kwargs)


        # fix for naming in differnt EOreader versions
        if 'z' in bands.coords:
            bands = bands.rename({'z': 'bands'})

        # ----------------------------------
        # setting up coordinates and dimensions
        # ----------------------------------
        self.prod = bands.assign_coords(wl=('bands', self.INFO.loc['Wavelength (nm)'])). \
            swap_dims({'bands': 'wl'}).drop_vars(['band', 'bands', 'variable'], errors='ignore')
        self.prod = self.prod.assign_coords(bandID=('wl', self.INFO.loc['ESA'].values))
        self.prod = self.prod.to_dataset(name='bands', promote_attrs=True)
        self.prod.attrs['wl_to_process'] = WAVELENGTH[self.band_tbp_idx]

        # add spectral response function
        self.prod = xr.merge([self.prod, self.SRFs.sel(wl=self.prod.wl.values)],compat='override').drop_vars('bandID')

        # compute central wavelengths
        wl_true = []
        for wl_, srf in self.prod.SRF.groupby('wl', squeeze=False):
            srf = srf.dropna('wl_hr')
            wl_true.append((srf.wl_hr * srf).integrate('wl_hr') / srf.integrate('wl_hr'))
        wl_true = xr.concat(wl_true, dim='wl')
        wl_true.name = 'wl_true'
        self.prod = xr.merge([self.prod, wl_true],compat='override')

        # add time
        if add_time:
            self.prod = self.prod.assign_coords(time=self.datetime) #.expand_dims('time')
        # self.prod.clear()

    @staticmethod
    def parse_angular_grid_node(node):
        '''
        Parse an angular grid of the granule metadata (``MTD_TL.xml``).

        :param node: XML element containing a ``Values_List``
        :return: 2D numpy array of the angles (deg)
        '''
        values = []
        for c in node.find('Values_List'):
            values.append(np.array([float(t) for t in c.text.split()]))
            values_array = np.stack(values)
        return values_array

    @staticmethod
    def set_crs(arr, crs):
        '''
        Write ``crs`` in ``arr`` (in place) with rioxarray.

        :param arr: xarray DataArray or Dataset
        :param crs: coordinate reference system
        '''
        #arr.rio.set_crs(crs, inplace=True)
        arr.rio.write_crs(crs, inplace=True)

    def get_raw_angles(self):
        '''
        Read the sun and viewing angle grids of the granule metadata.

        Sets ``raw_sun_ang`` (``sza``, ``sazi``), ``raw_view_ang``
        (``vza``, ``vazi`` per ``bandId`` and ``detectorId``), ``detector_num``
        and the mean solar angles ``mean_sza`` and ``mean_sun_azi``.
        '''

        minx, miny, maxx, maxy = self.bounds.values[0]
        with open(self.xml_granule) as xml_file:
            tree = ET.parse(xml_file)
            root = tree.getroot()

        raw_sza = self.parse_angular_grid_node(root.find('.//Tile_Angles/Sun_Angles_Grid/Zenith'))
        raw_sazi = self.parse_angular_grid_node(root.find('.//Tile_Angles/Sun_Angles_Grid/Azimuth'))
        self.mean_sza= np.nanmean(raw_sza)
        self.mean_sun_azi = np.nanmean(raw_sazi)

        # compute x and y for angle grids
        # check dimension
        Nx, Ny = raw_sza.shape

        xang = np.linspace(minx, maxx, Nx)
        yang = np.linspace(miny, maxy, Ny)[::-1]

        raw_sun_ang = xr.Dataset(data_vars=dict(sza=(['y', 'x'], raw_sza),
                                                sazi=(['y', 'x'], raw_sazi)),
                                 coords=dict(x=xang, y=yang))
        self.set_crs(raw_sun_ang, self.crs)
        self.raw_sun_ang = raw_sun_ang

        # ---------------------------------
        # getting viewing geometry datacube
        # ---------------------------------
        bandIds, detectorIds = [], []
        for angleID in root.findall('.//Tile_Angles/Viewing_Incidence_Angles_Grids'):
            bandIds.append(int(angleID.attrib['bandId']))
            detectorIds.append(int(angleID.attrib['detectorId']))
        Nband, Ndetector = np.max(bandIds) + 1, np.max(detectorIds) + 1

        # allocate/fill rasters
        vza = np.full((Nband, Ndetector, Nx, Ny), np.nan, dtype=float)
        vazi = np.full((Nband, Ndetector, Nx, Ny), np.nan, dtype=float)

        for angleID in root.findall('.//Tile_Angles/Viewing_Incidence_Angles_Grids'):
            iband = int(angleID.attrib['bandId'])
            idetector = int(angleID.attrib['detectorId'])
            vza[iband, idetector] = self.parse_angular_grid_node(angleID.find('Zenith'))
            vazi[iband, idetector] = self.parse_angular_grid_node(angleID.find('Azimuth'))

        raw_view_ang = xr.Dataset(data_vars=dict(vza=(['bandId', 'detectorId', 'y', 'x'], vza),
                                                 vazi=(['bandId', 'detectorId', 'y', 'x'], vazi)),
                                  coords=dict(bandId=range(Nband),
                                              detectorId=range(Ndetector),
                                              x=xang, y=yang))
        self.set_crs(raw_view_ang, self.crs)

        # clean up Dataset (remove empty slices)
        raw_view_ang = raw_view_ang.dropna('detectorId', how='all')
        self.raw_view_ang = raw_view_ang

        # set number of different detectors
        self.detector_num = len(raw_view_ang.detectorId)

        return

    def load_geom(self,
                  method='linear'):
        '''
        Compute sun and viewing angles on the ``resolution_angle`` grid
        into ``self.geom`` (see :meth:`get_all_band_angles`).

        :param method: interpolation method of the sun angles
        '''

        self.get_raw_angles()
        self.get_all_band_angles( method=method)

    @staticmethod
    def linfit(beta, x):
        '''
        Plane model ``beta[0] * x + beta[1] * y + beta[2]``.

        :param beta: plane coefficients
        :param x: coordinates stacked as ``(x, y)``
        '''
        return beta[0] * x[0] + beta[1] * x[1] + beta[2]

    @staticmethod
    @jit(nopython=True, cache=True)  # "uint16[:,:](float64[:],float64[:],float64[:,:],float64[:,:],intp,intp)",
    def lin2D(arr, x, y, mask, betas, detector_offset=0, scale_factor=100):
        '''
        Fill ``arr`` (in place, numba compiled) with the plane of the detector
        seen by each pixel; pixels with no detector are left untouched.

        :param arr: 2D output array (y, x)
        :param x: x coordinates of the columns
        :param y: y coordinates of the rows
        :param mask: detector number of each pixel (y, x)
        :param betas: plane coefficients of each detector (detector, 3)
        :param detector_offset: number of the first detector in ``betas``
        :param scale_factor: factor applied to the values (for integer compression)
        '''

        Nx, Ny = mask.shape

        for ii in range(Nx):
            for jj in range(Ny):
                detect = mask[ii, jj]
                if detect >=  detector_offset:
                    #continue
                    beta = betas[detect - detector_offset]
                    val = beta[0] * x[jj] + beta[1] * y[ii] + beta[2]
                    # compression using simple int8 and scale factor
                    arr[ii, jj] = (val * scale_factor)

    def data_fitting(self, x0, y0, arr):
        '''
        Fit a plane to the angle grid ``arr`` with orthogonal distance regression,
        NaN values being ignored.

        :param x0: x coordinates of ``arr``
        :param y0: y coordinates of ``arr``
        :param arr: 2D DataArray of the angles
        :return: plane coefficients (see :meth:`linfit`)
        '''
        # ---------------------------------
        # ODR multilinear regression
        # ---------------------------------
        xgrid, ygrid = np.meshgrid(x0, y0, indexing=self.indexing)

        # vectorize
        values = arr.values.flatten()
        x_ = xgrid.flatten()
        y_ = ygrid.flatten()

        # remove NaN
        idx = ~np.isnan(values)
        values = values[idx]
        points = np.empty((2, len(values)))
        points[0] = x_[idx]
        points[1] = y_[idx]

        # set ODR fitting
        mean = np.nanmean(values)
        linear = odr.Model(self.linfit)
        data = odr.Data(points, values)
        beta0 = [0, 0, mean]

        # proceed with ODR fitting
        fit = odr.ODR(data, linear, beta0=beta0)
        resfit = fit.run()

        if self.verbose:
            resfit.pprint()

        return resfit.beta

    def get_detector_mask(self, bandId=0,
                          resolution=20,
                          detector_mask_name='DETFOO'):
        '''
        Rasterize the detector footprint of a band: each pixel gets the number
        of the detector it is seen by.

        :param bandId: band index (0 to 12)
        :param resolution: pixel size (m) of the mask
        :param detector_mask_name: name of the mask in the L1C product
        :return: 2D numpy array of the detector numbers
        '''

        if self.processing_baseline < 4:
            mask_df = self._open_mask(detector_mask_name, BAND_ID[bandId])
            detector_num = mask_df.gml_id.str.split('-', expand=True).values[:, 2]
            poly_shp = [[geom, int(value)] for geom, value in zip(mask_df.geometry, detector_num)]

            mask = rasterize(shapes=poly_shp,
                             out_shape=(self.height, self.width),
                             transform=self.transform)
        else:
            # TODO deprecate 'resolution' argument, 'pixel_size' is used instead since EOReader 0.20
            mask = self._open_mask(detector_mask_name, BAND_ID[bandId], resolution=resolution,
                                   pixel_size=resolution).astype(np.int8)

            mask = mask.squeeze()
        return np.array(mask)

    def get_band_angle_as_numpy(self, xarr,
                                bandId=0,
                                resolution=20,
                                detector_mask_name='DETFOO',
                                compress=False,
                                mask=None,
                                ):
        '''
        Compute a viewing angle of one band on the ``resolution_angle`` grid:
        a plane is fitted for each detector, then evaluated on the pixels
        of that detector.

        :param xarr: raw angle grids (bandId, detectorId, y, x), e.g. ``raw_view_ang.vza``
        :param bandId: band index (0 to 12)
        :param resolution: pixel size (m) of the detector mask
        :param detector_mask_name: name of the detector mask in the L1C product
        :param compress: experimental, store the angles as int16 scaled by 100
        :param mask: detector mask already loaded with :meth:`get_detector_mask`
            (loaded here if None)
        :return: 2D numpy array of the angles (deg)
        '''

        detector_offset = int(xarr.detectorId.min())
        if mask is None:
            mask = self.get_detector_mask(bandId=bandId, resolution=resolution,
                                          detector_mask_name=detector_mask_name)

        # TODO check how to avoid taking the nodata value "0" when coarsening the raster
        # TODO for the moment this induces bad detector number at the edge of the image swath
        # mask = _open_mask(detector_mask_name, BAND_ID[bandId], resolution=NATIVE_RESOLUTION[bandId])
        # # mask nodata value
        # mask = mask.where(mask!=0)
        # # resample mask at the desired resolution
        # if resolution != NATIVE_RESOLUTION[iband]:
        #     mask = mask.interp(x=new_x, y=new_y, method='nearest')
        # # compress mask into int8
        # mask = mask.astype(np.int8)

        x, y = self.new_x, self.new_y
        # self.prod.clear()
        betas = np.full((self.detector_num, 3), np.nan)
        xarr_ = xarr.sel(bandId=bandId)
        for id in range(self.detector_num):
            # --------------------------------------------------------------
            # Linear 2D-fitting to get the function of the regression plane
            # --------------------------------------------------------------
            arr = xarr_.isel(detectorId=id).dropna('y', how='all').dropna('x', how='all')
            x0, y0 = arr.x.values, arr.y.values
            betas[id, :] = self.data_fitting(x0, y0, arr)

        if compress:
            # TODO experimental, needs to be tested
            # compression in uint16 (NB: range 0-65535)
            new_arr = np.full((self.width, self.height), np.nan, dtype=np.int16)
            # compute angles from betas values for each detector and band
            self.lin2D(new_arr, x, y, mask, betas, detector_offset=detector_offset, scale_factor=100)
        else:
            #
            new_arr = np.full((self.width, self.height), np.nan, dtype=np.float32)
            # compute angles from betas values for each detector and band
            self.lin2D(new_arr, x, y, mask, betas, detector_offset=detector_offset, scale_factor=1)

        return new_arr

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

    def get_all_band_angles(self, method='linear'):
        '''
        Fill ``self.geom`` with ``vza`` and ``raa`` (wl, y, x) for each band of
        ``band_idx`` and ``sza`` (y, x), on the ``resolution_angle`` grid (float32).
        :meth:`get_raw_angles` must have been called before.

        :param method: interpolation method of the sun angles
        '''

        new_x, new_y = self.new_x, self.new_y
        band_idx = self.band_idx
        # -----------------------------------------------------------------
        # Sun angles (easy!) based on standard bidimensional interpolation
        # -----------------------------------------------------------------
        new_sun_ang = self.raw_sun_ang.interp(x=new_x, y=new_y, method=method)

        # ------------------------------------------------------
        # Viewing angles (not easy!) based on 2D-plane fitting
        # ------------------------------------------------------
        raw_vza = self.raw_view_ang.vza
        raw_vazi = self.raw_view_ang.vazi

        # ---------------------------------------------------------
        # convert vza, azi angles into cartesian vector components
        # (NOT NEEDED FOR THE MOMENT!!)
        # ---------------------------------------------------------
        # np.tan(np.deg2rad(view_ang.vza)) * np.sin(np.deg2rad(view_ang.vazi))
        # np.tan(np.deg2rad(view_ang.vza)) * np.cos(np.deg2rad(view_ang.vazi))
        # dx.name = 'dx'
        # dy.name = 'dy'

        new_vza = np.empty((len(band_idx), self.width, self.height), dtype=np.float32)
        raa = np.empty((len(band_idx), self.width, self.height), dtype=np.float32)
        for ibandId, bandId in enumerate(band_idx):
            if self.verbose:
                print('Band number ' + str(bandId) + ' is being loaded')
            # the detector mask is read once and shared by zenith and azimuth
            mask = self.get_detector_mask(bandId=bandId, resolution=self.resolution_angle)
            new_vza[ibandId] = self.get_band_angle_as_numpy(raw_vza, bandId=bandId,
                                                            resolution=self.resolution_angle, mask=mask)
            raa[ibandId] = self.get_band_angle_as_numpy(raw_vazi, bandId=bandId,
                                                        resolution=self.resolution_angle, mask=mask)
            # EOReader temporaries are kept in reference cycles: free them band by band
            del mask
            gc.collect()
        # relative azimuth computed in place: raa = (vazi - sazi) % 360
        raa -= new_sun_ang.sazi.values.astype(np.float32)
        raa %= 360

        self.geom['vza'] = xr.DataArray(new_vza, dims=['wl', 'y', 'x'])
        self.geom['raa'] = xr.DataArray(raa, dims=['wl', 'y', 'x'])
        self.geom['sza'] = xr.DataArray(new_sun_ang.sza.values.astype(np.float32), dims=['y', 'x'])
        #
        # xr.Dataset(data_vars=dict(vza=(['wl', 'y', 'x'], )),
        #                      coords=dict(wl=self.INFO.loc['Wavelength (nm)'],
        #
        # vazi = xr.Dataset(data_vars=dict(vazi=(['wl', 'y', 'x'], np.array(new_vazi))),
        #                   coords=dict(wl=self.INFO.loc['Wavelength (nm)'], x=new_x, y=new_y))
        # new_ang = xr.Dataset(data_vars=dict(vza=(['wl', 'y', 'x'], np.array(new_vza))),
        #                      coords=dict(wl=self.INFO.loc['Wavelength (nm)'], x=new_x, y=new_y))
        #
        # new_ang['sza'] = new_sun_ang.sza
        # new_ang['razi'] = vazi.vazi - new_sun_ang.sazi) % 360
        # # new_ang['scat_ang'] = scat_angle(new_ang.sza, new_ang.vza, new_ang.razi)
        self.geom['x']=self.new_x
        self.geom['y']=self.new_y
        self.set_crs(self.geom, self.crs)

        del new_vza, raa, new_sun_ang

        return

# ------------------------------------------------------------------------------------------
# ------------------------------------------------------------------------------------------
# ------------------------------------------------------------------------------------------
