

import math
import os

import numpy as np
import pandas as pd
import xarray as xr
import rioxarray  # noqa: F401 (rio accessor)

import pyproj
import rasterio
from rasterio import features
from rasterio.enums import Resampling
import rasterio.warp
import rasterio.windows
from rasterio.vrt import WarpedVRT
from affine import Affine
import geopandas as gpd

# environment variable switching the drivers to lazy (dask-backed) loading
USE_DASK = 'GRSDRIVER_USE_DASK'
# former name (EOReader), still accepted
USE_DASK_LEGACY = 'EOREADER_USE_DASK'
# dask chunks of the lazy products (sizes chosen by dask)
DASK_CHUNKS = {'x': 'auto', 'y': 'auto'}


def use_dask():
    '''
    True when lazy (dask-backed) loading is requested, i.e. when the environment
    variable ``GRSDRIVER_USE_DASK`` (or its former name ``EOREADER_USE_DASK``)
    is set to ``1`` or ``true`` (default: ``0``).
    '''
    value = os.getenv(USE_DASK, os.getenv(USE_DASK_LEGACY, '0'))
    return value.lower() in ('1', 'true')


def read_on_grid(path, transform, width, height,
                 resampling=Resampling.nearest,
                 nodata=None,
                 dtype=None,
                 chunks=None):
    '''
    Read the first band of a raster on a target grid (same CRS): only the pixels
    needed for the target grid are read, and the resampling (if any) is done by GDAL.

    In memory (``chunks=None``), the source window is decoded at once and
    resampled with ``rasterio.warp.reproject`` (a warped VRT decodes compressed
    tiles, e.g. JPEG2000, several times); lazily, through a GDAL warped VRT.

    :param path: path of the raster file
    :param transform: affine transform of the target grid
    :param width: number of columns of the target grid
    :param height: number of rows of the target grid
    :param resampling: ``rasterio.enums.Resampling`` method
    :param nodata: no-data value of the source (pixels ignored when resampling,
        and fill value outside the source); by default the one of the file
    :param dtype: data type in which the resampling is computed (e.g. ``float32``
        to avoid rounding averaged integers); by default the one of the file
    :param chunks: dask chunks (lazy reading), ``None`` to load into memory
    :return: DataArray (y, x), with the ``rio`` georeferencing
    '''
    with rasterio.open(path) as src:
        if chunks is None:
            # source window covering the target grid, with a margin for the resampling kernel
            minx, maxy = transform * (0, 0)
            maxx, miny = transform * (width, height)
            inv = ~src.transform
            col0, row0 = inv * (minx, maxy)
            col1, row1 = inv * (maxx, miny)
            col0, row0 = max(0, math.floor(col0) - 2), max(0, math.floor(row0) - 2)
            col1, row1 = min(src.width, math.ceil(col1) + 2), min(src.height, math.ceil(row1) + 2)
            window = rasterio.windows.Window(col0, row0, col1 - col0, row1 - row0)
            src_nodata = src.nodata if nodata is None else nodata
            data = np.full((height, width), 0 if src_nodata is None else src_nodata,
                           dtype=dtype or src.dtypes[0])
            if window.width > 0 and window.height > 0:
                rasterio.warp.reproject(src.read(1, window=window), data,
                                        src_transform=src.window_transform(window), src_crs=src.crs,
                                        dst_transform=transform, dst_crs=src.crs,
                                        src_nodata=src_nodata, dst_nodata=src_nodata,
                                        resampling=resampling)
            x, _ = transform * (np.arange(width) + 0.5, np.full(width, 0.5))
            _, y = transform * (np.full(height, 0.5), np.arange(height) + 0.5)
            xda = xr.DataArray(data, dims=('y', 'x'), coords=dict(x=x, y=y))
            return xda.rio.write_crs(src.crs).rio.write_transform(transform)
        vrt_kwargs = dict(crs=src.crs, transform=transform, width=width, height=height,
                          resampling=resampling)
        if nodata is not None:
            vrt_kwargs.update(src_nodata=nodata, nodata=nodata)
        if dtype is not None:
            vrt_kwargs.update(dtype=dtype)
        with WarpedVRT(src, **vrt_kwargs) as vrt:
            xda = rioxarray.open_rasterio(vrt, chunks=chunks)
            if chunks is None:
                xda = xda.load()
    return xda.squeeze('band', drop=True)


def stack_bands(read_band, keys, lazy=False):
    '''
    Stack the bands returned by ``read_band(key)`` for each key of ``keys``
    along a new ``bands`` dimension. Eager mode: the bands are loaded one by one
    into a preallocated float32 array (peak memory: the stack plus one band).

    :param read_band: function returning a DataArray (y, x) for a key
    :param keys: band keys (e.g. band numbers)
    :param lazy: concatenate the (dask-backed) bands without computing them
    :return: DataArray (bands, y, x)
    '''
    if lazy:
        return xr.concat([read_band(key) for key in keys], dim='bands')
    stack = None
    for iband, key in enumerate(keys):
        band = read_band(key)
        if stack is None:
            stack = xr.DataArray(np.empty((len(keys),) + band.shape, dtype=np.float32),
                                 dims=('bands',) + band.dims, coords=band.coords)
        stack.values[iband] = band.values
        del band
    return stack


def get_bounds(subset, crs):
    '''
    Bounding box ``(minx, miny, maxx, maxy)`` in ``crs`` of a spatial subset of
    the drivers: a ``geopandas.GeoSeries`` or ``GeoDataFrame`` (any CRS), or a
    sequence whose first element is the bounding box in ``crs``.

    :param subset: spatial subset, or None
    :param crs: CRS of the product
    :return: bounds, or None if ``subset`` is None
    '''
    if subset is None:
        return None
    if hasattr(subset, 'to_crs'):
        return tuple(subset.to_crs(crs).total_bounds)
    return tuple(subset[0])


def subset_grid(transform, width, height, bounds=None):
    '''
    Crop a grid to the pixels intersecting ``bounds``.

    :param transform: affine transform of the full grid (north up)
    :param width: number of columns of the full grid
    :param height: number of rows of the full grid
    :param bounds: ``(minx, miny, maxx, maxy)`` in the grid CRS, or None (full grid)
    :return: (transform, width, height) of the cropped grid
    '''
    if bounds is None:
        return transform, width, height
    res_x, res_y = transform.a, -transform.e
    x0, y0 = transform.c, transform.f
    minx, miny, maxx, maxy = bounds
    col0 = max(0, math.floor((minx - x0) / res_x))
    col1 = min(width, math.ceil((maxx - x0) / res_x))
    row0 = max(0, math.floor((y0 - maxy) / res_y))
    row1 = min(height, math.ceil((y0 - miny) / res_y))
    if col1 <= col0 or row1 <= row0:
        raise ValueError('subset does not intersect the image')
    return (Affine(res_x, 0., x0 + col0 * res_x, 0., -res_y, y0 - row0 * res_y),
            col1 - col0, row1 - row0)


class SpatioTemp():
    '''
    Spatial helpers: build a box around a point (e.g. to define a ``subset``
    of the drivers), rasterize shapes and clip rasters.
    '''

    def wktbox(self,
               center_lon,
               center_lat,
               width=100,
               height=100,
               ellps='WGS84'):

        '''

        :param center_lon: decimal longitude
        :param center_lat: decimal latitude
        :param width: width of the box in m
        :param height: height of the box in m
        :return: wkt of the box centered on provided coordinates
        '''

        #width,height = width/2 , height/2
        geod = pyproj.Geod(ellps=ellps)

        rect_diag = np.sqrt(width ** 2 + height ** 2)

        azimuth1 = np.arctan(width / height)
        azimuth2 = np.arctan(-width / height)
        azimuth3 = np.arctan(width / height) + np.pi  # first point + 180 degrees
        azimuth4 = np.arctan(-width / height) + np.pi  # second point + 180 degrees

        pt1_lon, pt1_lat, _ = geod.fwd(center_lon, center_lat, azimuth1 * 180 / np.pi, rect_diag)
        pt2_lon, pt2_lat, _ = geod.fwd(center_lon, center_lat, azimuth2 * 180 / np.pi, rect_diag)
        pt3_lon, pt3_lat, _ = geod.fwd(center_lon, center_lat, azimuth3 * 180 / np.pi, rect_diag)
        pt4_lon, pt4_lat, _ = geod.fwd(center_lon, center_lat, azimuth4 * 180 / np.pi, rect_diag)

        wkt_point = 'POINT (%.6f %.6f)' % (center_lon, center_lat)
        wkt_poly = 'POLYGON (( %.6f %.6f, %.6f %.6f, %.6f %.6f, %.6f %.6f, %.6f %.6f ))' % (
            pt1_lon, pt1_lat, pt2_lon, pt2_lat, pt3_lon, pt3_lat, pt4_lon, pt4_lat, pt1_lon, pt1_lat)
        return wkt_poly

    def transform_from_latlon(self, lat, lon):
        '''
        Affine transform of a regular grid from its 1D coordinates.

        :param lat: 1D latitude (or y) coordinates
        :param lon: 1D longitude (or x) coordinates
        :return: ``affine.Affine`` transform
        '''
        lat = np.asarray(lat)
        lon = np.asarray(lon)
        trans = Affine.translation(lon[0], lat[0])
        scale = Affine.scale(lon[1] - lon[0], lat[1] - lat[0])
        return trans * scale

    def rasterize(self, shapes, coords, latitude='lat', longitude='lon',
                  fill=np.nan, **kwargs):
        '''
        Rasterize a list of (geometry, fill_value) tuples onto the given xarray
        coordinates. This only works for 1D latitude and longitude arrays.

        Usage::

            states = gpd.read_file(shp_dir)
            shapes = zip(states.geometry, range(len(states)))
            ds['states'] = rasterize(shapes, ds.coords, longitude='X', latitude='Y')

        :param shapes: iterable of (geometry, value) pairs
        :param coords: coordinates of the target grid (e.g. ``ds.coords``)
        :param latitude: name of the latitude (or y) coordinate
        :param longitude: name of the longitude (or x) coordinate
        :param fill: value of the pixels outside the shapes
        :param kwargs: passed to ``rasterio.features.rasterize``
        :return: DataArray (latitude, longitude) with the value of the shape
            covering each pixel, ``fill`` elsewhere
        '''
        # transform = transform_from_latlon(coords[latitude], coords[longitude])
        out_shape = (len(coords[latitude]), len(coords[longitude]))
        raster = features.rasterize(shapes, out_shape=out_shape,
                                    fill=fill,  # transform=transform,
                                    dtype=float, **kwargs)
        spatial_coords = {latitude: coords[latitude], longitude: coords[longitude]}
        return xr.DataArray(raster, coords=spatial_coords, dims=(latitude, longitude))

    @staticmethod
    def clip_raster(raster, lat, lon, extent_m):
        '''
        :param raster as rioxarray object with documented coordinate system
        :param lat: latitude (float) of central point of buffer
        :param lon: longitude (float) of central point of buffer
        :param extent_m: extent of square centered on lat/lon
        :param crs: crs for reprojection, use lat/lon epsg4326 otherwise.
        :return: clipped raster
        '''
        # distance is d/2 of the square buffer around the point,
        # from center to corner;
        # find buffer width in meters
        buffer_width_m = extent_m / np.sqrt(2)

        # EPSG:4326 sets Coordinate Reference System to WGS84 to match input
        wgs84_pt_gdf = gpd.GeoDataFrame(geometry=gpd.points_from_xy([lon], [lat], crs='4326'))

        # find suitable projected coordinate system for distance
        utm_crs = wgs84_pt_gdf.estimate_utm_crs()
        # reproject to UTM -> create square buffer (cap_style = 3) around point -> reproject back to WGS84
        buffer = wgs84_pt_gdf.to_crs(utm_crs).buffer(buffer_width_m, cap_style=3)
        # get buffer in the raster coordinate system
        buffer = buffer.to_crs(raster.rio.crs)

        # clipping
        return raster.rio.clip(buffer)
