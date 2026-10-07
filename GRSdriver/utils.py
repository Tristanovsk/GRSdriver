

import gc

import numpy as np
import pandas as pd
import xarray as xr
import rioxarray  # noqa: F401 (rio accessor)

import pyproj
from rasterio import features
from affine import Affine
import geopandas as gpd
from eoreader.utils import use_dask


def stack_bands(reader, bands, **kwargs):
    '''
    Memory-efficient equivalent of EOReader ``stack``: the bands are loaded one
    by one into a preallocated float32 array (bands, y, x), instead of loading
    them all before copying them into the stack (about twice less memory).

    EOReader ``stack`` is used as is when EOReader works with dask (lazy
    product), with a ``window`` (the windowed bands are not on the same grid, EOReader
    aligns them), when a stack-only argument (``stack_path``, ``save_as_int``) is given
    or when the bands are not on the same grid.

    :param reader: EOReader product
    :param bands: names of the bands to load
    :param kwargs: passed to ``reader.load`` (``pixel_size``, ``window``...)
    :return: DataArray (bands, y, x) with the attributes of the product
    '''
    if use_dask() or kwargs.get('window') is not None or \
            kwargs.get('stack_path') or kwargs.get('save_as_int'):
        return reader.stack(bands, **kwargs)
    kwargs.pop('stack_path', None)
    kwargs.pop('save_as_int', None)

    stack = None
    for iband, band in enumerate(bands):
        band_xds = reader.load([band], **kwargs)
        band_xda = next(iter(band_xds.data_vars.values())).squeeze('band', drop=True)
        if stack is None:
            stack = xr.DataArray(np.empty((len(bands),) + band_xda.shape, dtype=np.float32),
                                 dims=('bands',) + band_xda.dims,
                                 coords=band_xda.coords,
                                 attrs=band_xds.attrs)
        elif not (band_xda.x.equals(stack.x) and band_xda.y.equals(stack.y)):
            # bands on different grids (e.g. with a window): let EOReader align them
            del stack, band_xds, band_xda
            gc.collect()
            return reader.stack(bands, **kwargs)
        stack.values[iband] = band_xda.values
        # EOReader temporaries are kept in reference cycles: free them before the next band
        del band_xds, band_xda
        gc.collect()
    stack.attrs['long_name'] = ' '.join(bands)
    stack.rio.write_nodata(kwargs.get('nodata', reader.nodata), encoded=True, inplace=True)
    return stack


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
