'''
Tests of the spatial helpers (no satellite data needed).
'''

import numpy as np
import pyproj
import pytest
from shapely import wkt

from GRSdriver import SpatioTemp


@pytest.mark.parametrize('lon, lat, width, height', [(5.10, 43.47, 22000, 18000),
                                                     (110.5, 19.4, 10000, 30000),
                                                     (-51.5, -60.2, 5000, 5000)])
def test_wktbox_size(lon, lat, width, height):
    '''Sides of the box (geodesic lengths) equal to the requested width and height.'''
    box = wkt.loads(SpatioTemp().wktbox(lon, lat, width=width, height=height))
    corners = list(box.exterior.coords)[:4]
    geod = pyproj.Geod(ellps='WGS84')
    sides = [geod.inv(*corners[i], *corners[(i + 1) % 4])[2] for i in range(4)]
    # corners in order: north-east, north-west, south-west, south-east
    np.testing.assert_allclose(sides, [width, height, width, height], rtol=1e-3)
    np.testing.assert_allclose(box.centroid.coords[0], (lon, lat), atol=1e-3)


def test_clip_raster_size():
    '''Clipped square of side extent_m (to the pixel size).'''
    import xarray as xr
    import rioxarray  # noqa: F401
    x = np.arange(600000, 700000, 100.) + 50
    y = np.arange(4900000, 4800000, -100.) - 50
    raster = xr.DataArray(np.ones((y.size, x.size)), coords=dict(y=y, x=x), dims=('y', 'x')).rio.write_crs(32631)
    clipped = SpatioTemp.clip_raster(raster, 43.47, 5.10, 10000)
    for coord in (clipped.x, clipped.y):
        assert abs(float(coord.max() - coord.min()) + 100 - 10000) <= 200
