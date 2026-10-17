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


@pytest.mark.parametrize('offset', [(0, 0), (3, 5), (-4, -2), (95, 90)])
def test_read_on_grid_direct(tmp_path, offset):
    '''Target grid aligned on the source grid: direct copy identical to the GDAL resampling,
    with the fill value outside the source.'''
    import rasterio
    from affine import Affine
    from rasterio.enums import Resampling
    from GRSdriver import utils
    src_transform = Affine(30, 0, 600000, 0, -30, 4800000)
    data = np.arange(100 * 100, dtype=np.uint16).reshape(100, 100) + 1
    data[10:20, 30:40] = 0
    path = tmp_path / 'src.tif'
    with rasterio.open(path, 'w', driver='GTiff', width=100, height=100, count=1, dtype='uint16',
                       crs='EPSG:32631', transform=src_transform, nodata=0) as dst:
        dst.write(data, 1)
    row, col = offset
    transform = src_transform * Affine.translation(col, row)
    args = (str(path), transform, 20, 30, Resampling.nearest, 0, 'float32')
    direct = utils._read_window(*args)
    try:
        utils._pixel_offset, pixel_offset = (lambda *a: None), utils._pixel_offset
        resampled = utils._read_window(*args)
    finally:
        utils._pixel_offset = pixel_offset
    assert pixel_offset(src_transform, transform) == (row, col)
    assert direct.dtype == resampled.dtype == np.float32
    np.testing.assert_array_equal(direct, resampled)
