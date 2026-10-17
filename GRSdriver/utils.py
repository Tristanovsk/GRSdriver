'''
Tools shared by the drivers, and spatial helpers for the users.

- Reading: :func:`read_on_grid` reads a raster directly on a target grid, :func:`stack_bands`
  stacks the bands of a product, :func:`get_bounds` and :func:`subset_grid` turn a ``subset``
  into an output grid.
- Lazy loading: the drivers return dask-backed products when :func:`use_dask` is True, i.e. when
  the environment variable ``GRSDRIVER_USE_DASK=1`` is set before importing GRSdriver.
- :class:`SpatioTemp`: build a region of interest around a point, rasterize shapes, clip rasters.
'''

import math
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import dask
import dask.array as da
import pandas as pd
import xarray as xr
import rioxarray  # noqa: F401 (rio accessor)

import pyproj
import rasterio
from rasterio import features
from rasterio.enums import Resampling
import rasterio.warp
import rasterio.windows
from affine import Affine
import geopandas as gpd

USE_DASK = 'GRSDRIVER_USE_DASK'
'''Name of the environment variable switching the drivers to lazy (dask-backed) loading.'''

USE_DASK_LEGACY = 'EOREADER_USE_DASK'
'''Former name of :data:`USE_DASK` (GRSdriver < 2.0), still accepted.'''

DASK_CHUNKS = {'x': 'auto', 'y': 'auto'}
'''Dask chunks of the lazy products (sizes chosen by dask).'''


def use_dask():
    '''
    True when lazy (dask-backed) loading is requested, i.e. when the environment
    variable ``GRSDRIVER_USE_DASK`` (or its former name ``EOREADER_USE_DASK``)
    is set to ``1`` or ``true`` (default: ``0``).
    '''
    value = os.getenv(USE_DASK, os.getenv(USE_DASK_LEGACY, '0'))
    return value.lower() in ('1', 'true')


def _pixel_offset(src_transform, transform):
    '''
    (row, col) offset of the target grid in the source grid when both grids coincide (same
    pixel size, north up, target origin on a source pixel corner), else None.
    '''
    if not (np.isclose(transform.a, src_transform.a) and np.isclose(transform.e, src_transform.e)
            and transform.b == transform.d == src_transform.b == src_transform.d == 0):
        return None
    col = (transform.c - src_transform.c) / src_transform.a
    row = (transform.f - src_transform.f) / src_transform.e
    if abs(col - round(col)) > 1e-6 or abs(row - round(row)) > 1e-6:
        return None
    return round(row), round(col)


def _read_window(path, transform, width, height, resampling, nodata, dtype):
    '''
    Read the first band of ``path`` on a target grid, as a numpy array (see :func:`read_on_grid`).
    '''
    with rasterio.open(path) as src:
        offset = _pixel_offset(src.transform, transform)
        if offset is not None:
            # target grid = part of the source grid: direct copy, no resampling needed
            row, col = offset
            src_nodata = src.nodata if nodata is None else nodata
            data = np.full((height, width), 0 if src_nodata is None else src_nodata,
                           dtype=dtype or src.dtypes[0])
            r0, c0 = max(row, 0), max(col, 0)
            r1, c1 = min(row + height, src.height), min(col + width, src.width)
            if r1 > r0 and c1 > c0:
                window = rasterio.windows.Window(c0, r0, c1 - c0, r1 - r0)
                data[r0 - row:r1 - row, c0 - col:c1 - col] = src.read(1, window=window)
            return data
        # source window covering the target grid (north up), with a margin for the
        # resampling kernel
        minx, maxx = transform.c, transform.c + transform.a * width
        maxy, miny = transform.f, transform.f + transform.e * height
        col0, col1 = [(x - src.transform.c) / src.transform.a for x in (minx, maxx)]
        row0, row1 = [(y - src.transform.f) / src.transform.e for y in (maxy, miny)]
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
    return data


def read_on_grid(path, transform, width, height,
                 resampling=Resampling.nearest,
                 nodata=None,
                 dtype=None,
                 chunks=None):
    '''
    Read the first band of a raster on a target grid (same CRS): only the pixels
    needed for the target grid are read and decoded once, then resampled (if needed)
    by GDAL (``rasterio.warp.reproject``).

    With ``chunks``, the raster is read lazily: a dask array computed by a single task
    (the whole raster is decoded at once, much faster than block by block for
    compressed formats such as JPEG2000), then rechunked to ``chunks``.

    :param path: path of the raster file
    :param transform: affine transform of the target grid
    :param width: number of columns of the target grid
    :param height: number of rows of the target grid
    :param resampling: ``rasterio.enums.Resampling`` method
    :param nodata: no-data value of the source (pixels ignored when resampling,
        and fill value outside the source); by default the one of the file
    :param dtype: data type in which the resampling is computed (e.g. ``float32``
        to avoid rounding averaged integers); by default the one of the file
    :param chunks: dask chunks (lazy reading, e.g. :data:`DASK_CHUNKS`), ``None`` to load
        into memory
    :return: DataArray (y, x), with the ``rio`` georeferencing
    '''
    with rasterio.open(path) as src:
        crs, out_dtype = src.crs, np.dtype(dtype or src.dtypes[0])
    args = (path, transform, width, height, resampling, nodata, dtype)
    if chunks is None:
        data = _read_window(*args)
    else:
        data = da.from_delayed(dask.delayed(_read_window)(*args), shape=(height, width), dtype=out_dtype)
    # pixel centers
    x = transform.c + transform.a * (np.arange(width) + 0.5)
    y = transform.f + transform.e * (np.arange(height) + 0.5)
    xda = xr.DataArray(data, dims=('y', 'x'), coords=dict(x=x, y=y))
    if chunks is not None:
        xda = xda.chunk(chunks)
    return xda.rio.write_crs(crs).rio.write_transform(transform)


def stack_bands(read_band, keys, lazy=False, n_workers=1):
    '''
    Stack the bands returned by ``read_band(key)`` for each key of ``keys``
    along a new ``bands`` dimension.

    Eager mode: the bands are read by ``n_workers`` threads (decoding and resampling
    release the GIL) and copied into a preallocated float32 array as soon as they are
    read; the peak memory is the stack plus about ``n_workers`` bands being read.

    :param read_band: function returning a DataArray (y, x) for a key
    :param keys: band keys (e.g. band numbers)
    :param lazy: concatenate the (dask-backed) bands without computing them
    :param n_workers: number of bands read in parallel (eager mode)
    :return: DataArray (bands, y, x)
    '''
    keys = list(keys)
    if lazy:
        return xr.concat([read_band(key) for key in keys], dim='bands')
    # the first band gives the grid of the stack
    band = read_band(keys[0])
    stack = xr.DataArray(np.empty((len(keys),) + band.shape, dtype=np.float32),
                         dims=('bands',) + band.dims, coords=band.coords)
    stack.values[0] = band.values
    del band
    with ThreadPoolExecutor(max_workers=max(1, n_workers)) as executor:
        futures = {executor.submit(read_band, key): iband for iband, key in enumerate(keys[1:], start=1)}
        for future in as_completed(futures):
            stack.values[futures.pop(future)] = future.result().values
            del future
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
    Spatial helpers: build a box around a point (:meth:`~GRSdriver.utils.SpatioTemp.wktbox`, e.g. to define the
    ``subset`` of the drivers), rasterize shapes (:meth:`~GRSdriver.utils.SpatioTemp.rasterize`) and clip a raster
    around a point (:meth:`~GRSdriver.utils.SpatioTemp.clip_raster`).
    '''

    def wktbox(self,
               center_lon,
               center_lat,
               width=100,
               height=100,
               ellps='WGS84'):

        '''
        Rectangle of ``width`` x ``height`` meters centered on a point, e.g. to define
        the ``subset`` of the drivers::

            box = SpatioTemp().wktbox(5.10, 43.47, width=20000, height=15000)
            subset = geopandas.GeoSeries.from_wkt([box], crs=4326)

        The corners are computed on the ellipsoid (geodesic distance and azimuth from the
        center): the box is aligned with the meridians at its center.

        :param center_lon: longitude of the center (deg)
        :param center_lat: latitude of the center (deg)
        :param width: width of the box (m, west-east)
        :param height: height of the box (m, south-north)
        :param ellps: ellipsoid (``pyproj.Geod``)
        :return: WKT polygon of the box (lon/lat, EPSG:4326)
        '''

        geod = pyproj.Geod(ellps=ellps)

        # distance from the center to the corners: half the diagonal
        rect_diag = np.sqrt(width ** 2 + height ** 2) / 2

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
        Clip a raster to a square centered on a point.

        The square is built in the local UTM projection of the point, then reprojected
        into the CRS of the raster.

        :param raster: DataArray or Dataset with its CRS (``rio`` accessor)
        :param lat: latitude of the center (deg)
        :param lon: longitude of the center (deg)
        :param extent_m: size of the side of the square (m)
        :return: clipped raster
        '''
        # a square buffer (cap_style=3) of distance d has sides of 2 d
        buffer_width_m = extent_m / 2

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
