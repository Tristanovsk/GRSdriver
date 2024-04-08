import glob
import os
import numpy as np
import pandas as pd
import geopandas as gpd

import matplotlib.pyplot as plt
import matplotlib as mpl
# mpl.use('TkAgg')
import hvplot.xarray

import holoviews as hv
import holoviews.operation.datashader as hd
from holoviews.operation.datashader import rasterize, shade, spread
from holoviews.element.tiles import EsriImagery
from holoviews.element import tiles as hvts
from holoviews import opts

hv.extension('bokeh')

import datashader as ds
import datashader.transfer_functions as tf
import bokeh
import colorcet as cc
import panel as pn
import panel.widgets as pnw
import param as pm
from shapely.geometry import Polygon
from collections import OrderedDict as odict



class utils():

    @staticmethod
    def get_geom(aoi_stream, crs=4326):
        geom = aoi_stream.data
        ys, xs = geom['ys'][-1], geom['xs'][-1]
        polygon_geom = Polygon(zip(xs, ys))
        polygon = gpd.GeoDataFrame(index=[0], crs=3857, geometry=[polygon_geom])
        return polygon.to_crs(crs)

    @staticmethod
    def custom_hover():
        formatter_code = """
          var digits = 4;
          var projections = Bokeh.require("core/util/projections");
          var x = special_vars.x; var y = special_vars.y;
          var coords = projections.wgs84_mercator.invert(x, y);
          return "" + (Math.round(coords[%d] * 10**digits) / 10**digits).toFixed(digits)+ "";
        """
        formatter_code_x, formatter_code_y = formatter_code % 0, formatter_code % 1
        custom_tooltips = [('Lon', '@x{custom}'), ('Lat', '@y{custom}'), ('Value', '@image{0.0000}')]
        custom_formatters = {
            '@x': bokeh.models.CustomJSHover(code=formatter_code_x),
            '@y': bokeh.models.CustomJSHover(code=formatter_code_y)
        }
        return bokeh.models.HoverTool(tooltips=custom_tooltips, formatters=custom_formatters)


class view_geo(utils):
    def __init__(self, raster, dates=None,
                 bands=None,
                 reproject=False,
                 minmaxvalues=(0, 0.5),
                 minmax=(0, 1)):
        # layout settings
        self.width, self.height = 1200, 700

        self.key_dimensions = ['x', 'y']
        self.minmaxvalues = minmaxvalues
        self.minmax = minmax
        self.colormaps = ['CET_D13', 'bky', 'CET_D1A', 'CET_CBL2', 'CET_L10', 'CET_C6s',
                          'kbc', 'blues_r', 'kb', 'rainbow', 'fire', 'kgy', 'bjy', 'gray']
        # variables settings
        self.dates = dates
        if dates == None:
            self.dates = raster.time.dt.date.values
        self.bands = bands
        if bands == None:
            self.bands = raster.wl.values

        # load raster
        self.raster = raster
        self.dataarrays = {}

        if isinstance(raster.time.values, (list, np.ndarray)):
            times = raster.time.values
        else:
            times = [raster.time.values]

        for itime, time in enumerate(times):
            raster_ = raster.sel(time=time)
            for iband, band in enumerate(self.bands):
                if reproject:
                    self.dataarrays[itime, iband] = raster_.sel(wl=band).rio.reproject(3857, nodata=np.nan)
                else:
                    self.dataarrays[itime, iband] = raster_.sel(wl=band)

        # declare streaming object to get Area of Interest (AOI), crs=crs.epsg(3857)
        self.aoi_polygons = hv.Polygons([]).opts(opts.Polygons(
            fill_alpha=0.3, fill_color='white',
            line_width=1.2))  ##, active_tools=['poly_draw']))#.opts(crs.GOOGLE_MERCATOR)
        self.aoi_stream = hv.streams.PolyDraw(
            source=self.aoi_polygons, drag=True)  # , num_objects=1)#5,styles={'fill_color': aoi_colours})
        self.edit_stream = hv.streams.PolyEdit(source=self.aoi_polygons, vertex_style={'color': 'red'})

    @staticmethod
    def custom_hover():
        formatter_code = """
          var digits = 4;
          var projections = Bokeh.require("core/util/projections");
          var x = special_vars.x; var y = special_vars.y;
          var coords = projections.wgs84_mercator.invert(x, y);
          return "" + (Math.round(coords[%d] * 10**digits) / 10**digits).toFixed(digits)+ "";
        """
        formatter_code_x, formatter_code_y = formatter_code % 0, formatter_code % 1
        custom_tooltips = [('Lon', '@x{custom}'), ('Lat', '@y{custom}'), ('Value', '@image{0.0000}')]
        custom_formatters = {
            '@x': bokeh.models.CustomJSHover(code=formatter_code_x),
            '@y': bokeh.models.CustomJSHover(code=formatter_code_y)
        }
        return bokeh.models.HoverTool(tooltips=custom_tooltips, formatters=custom_formatters)

    def visu(self):
        dates = self.dates
        bands = self.bands
        hv.opts.defaults(
            hv.opts.Image(height=self.height, width=self.width,
                          colorbar=True, tools=[self.custom_hover()], active_tools=['wheel_zoom'],
                          clipping_colors={'NaN': '#00000000'}),
            hv.opts.Tiles(active_tools=['wheel_zoom'])
        )
        gopts = hv.opts.Tiles(xaxis=None, yaxis=None, bgcolor='black', show_grid=False)

        titles, images = {}, {}
        for idate, date in enumerate(dates):
            for iband, band in enumerate(bands):
                titles[date, iband] = str(date) + ', wl = {:.2f} nm '.format(band)
                datasets = hv.Dataset(self.dataarrays[idate, iband].squeeze(), kdims=self.key_dimensions)
                images[date, iband] = hv.Image(datasets).opts(gopts)

        bases = [name for name, ts in hv.element.tiles.tile_sources.items()]
        pn_band = pn.widgets.RadioButtonGroup(value=0, options=list(range(len(bands))))
        pn_colormap = pn.widgets.Select(value='CET_D13',
                                        options=self.colormaps)
        pn_opacity = pn.widgets.FloatSlider(name='Opacity', value=0.95, start=0, end=1, step=0.05)
        range_slider = pn.widgets.RangeSlider(name='Range Slider', start=self.minmax[0], end=self.minmax[1],
                                              value=self.minmaxvalues, step=0.0001)
        pn_basemaps = pn.widgets.Select(value='StamenTerrainRetina', options=bases)
        pn_date = pn.widgets.DatePicker(value=dates[0], start=dates[0],
                                        enabled_dates=dates.tolist())  # .date, end=dates[-1],value=dates[0])

        @pn.depends(
            pn_date_value=pn_date.param.value,
            pn_band_value=pn_band.param.value,
            pn_colormap_value=pn_colormap.param.value,
            pn_opacity_value=pn_opacity.param.value,
            range_slider_value=range_slider.param.value

        )
        def load_map(pn_date_value, pn_band_value,
                     pn_colormap_value, pn_opacity_value, range_slider_value):
            image = images[pn_date_value, pn_band_value]
            used_colormap = cc.cm[pn_colormap_value]
            image.opts(cmap=used_colormap, alpha=pn_opacity_value, clim=range_slider_value,
                       title=titles[pn_date_value, pn_band_value])
            return image

        @pn.depends(
            basemap_value=pn_basemaps.param.value)
        def load_tiles(basemap_value):
            tiles = hv.element.tiles.tile_sources[basemap_value]()
            return tiles.options(height=self.height, width=self.width).opts(gopts)

        dynmap = hd.regrid(hv.DynamicMap(load_map))
        combined = (hv.DynamicMap(
            load_tiles) * dynmap * self.aoi_polygons)

        return pn.Column(
            pn.WidgetBox(
                '## S2 L1C',
                pn.Column(
                    pn.Row(
                        pn.Row('### Band', pn_band),
                        pn.Row('### Date', pn_date),
                        pn.Row('#### Basemap', pn_basemaps)
                    ),
                    pn.Row(
                        pn.Row('', range_slider),
                        pn.Row('#### Opacity', pn_opacity),
                        pn.Row('#### Colormap', pn_colormap))
                ),
            combined)
        )
