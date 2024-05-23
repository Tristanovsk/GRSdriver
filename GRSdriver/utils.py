

import numpy as np
import pandas as pd
import xarray as xr

import pyproj
from rasterio import features
from affine import Affine
import geopandas as gpd

class SpatioTemp():

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
        lat = np.asarray(lat)
        lon = np.asarray(lon)
        trans = Affine.translation(lon[0], lat[0])
        scale = Affine.scale(lon[1] - lon[0], lat[1] - lat[0])
        return trans * scale

    def rasterize(self, shapes, coords, latitude='lat', longitude='lon',
                  fill=np.nan, **kwargs):
        """Rasterize a list of (geometry, fill_value) tuples onto the given
        xray coordinates. This only works for 1d latitude and longitude
        arrays.

        usage:
        -----
        1. read shapefile to geopandas.GeoDataFrame
              `states = gpd.read_file(shp_dir)`
        2. encode the different shapefiles that capture those lat-lons as different
            numbers i.e. 0.0, 1.0 ... and otherwise np.nan
              `shapes = (zip(states.geometry, range(len(states))))`
        3. Assign this to a new coord in your original xarray.DataArray
              `ds['states'] = rasterize(shapes, ds.coords, longitude='X', latitude='Y')`

        arguments:
        ---------
        : **kwargs (dict): passed to `rasterio.rasterize` function

        attrs:
        -----
        :transform (affine.Affine): how to translate from latlon to ...?
        :raster (numpy.ndarray): use rasterio.features.rasterize fill the values
          outside the .shp file with np.nan
        :spatial_coords (dict): dictionary of {"X":xr.DataArray, "Y":xr.DataArray()}
          with "X", "Y" as keys, and xr.DataArray as values

        returns:
        -------
        :(xr.DataArray): DataArray with `values` of nan for points outside shapefile
          and coords `Y` = latitude, 'X' = longitude.


        """
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
