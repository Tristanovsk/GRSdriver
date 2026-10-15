'''
Tests of the Sentinel-2 driver on L1C products of processing baseline >= 4.0
(JPEG2000 masks) and < 4.0 (GML masks).

The product directories are given by the environment variables GRSDRIVER_TEST_S2
and GRSDRIVER_TEST_S2_OLD (defaults below); the tests are skipped if they are not
available.
'''

import glob
import os

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from shapely.geometry import box

from GRSdriver import Sentinel2Driver

PRODUCTS = {
    'pb4': (os.getenv('GRSDRIVER_TEST_S2', '/data/satellite/Sentinel-2/ZOE/'
                      'S2B_MSIL1C_20240602T132239_N0510_R038_T22JEM_20240602T134842.SAFE'),
            box(-50.6, -30.3, -50.45, -30.15)),
    'pb2': (os.getenv('GRSDRIVER_TEST_S2_OLD', '/home/harmel/Dropbox/Dropbox/work/OBS2CO/vrac/L2h/'
                      'S2A_MSIL1C_20180324T133221_N0206_R081_T22KDC_20180324T151310.SAFE'),
            box(-51.6, -20.4, -51.45, -20.25)),
}


def _product(key):
    image, subset = PRODUCTS[key]
    if not os.path.isdir(image):
        pytest.skip('Sentinel-2 test product not available: ' + image)
    return image, gpd.GeoSeries([subset], crs=4326)


def _raw(image, band):
    with rasterio.open(glob.glob(os.path.join(image, 'GRANULE', '*', 'IMG_DATA', '*_' + band + '.jp2'))[0]) as src:
        return src.read(1), src.transform


@pytest.fixture(scope='module', params=['pb4', 'pb2'])
def l1c(request):
    image, subset = _product(request.param)
    l1c = Sentinel2Driver(image, band_idx=[0, 1, 4], band_tbp_idx=[0, 1, 4], subset=subset,
                          resolution=20, resolution_angle=60)
    l1c.load_product()
    return l1c


def test_structure(l1c):
    prod = l1c.prod
    assert list(prod.wl.values) == [443, 490, 705]
    assert prod.bands.dtype == np.float32
    assert prod.attrs['constellation_id'] == 'S2'
    assert prod.attrs['tile'] == os.path.basename(l1c.abspath).split('_')[5][1:]
    assert np.allclose(np.diff(prod.x.values), 20)
    # geometry defined wherever the bands are
    valid = np.isfinite(prod.bands.values)
    assert valid.any()
    assert np.isfinite(prod.vza.values[valid]).all()
    assert np.isfinite(prod.raa.values[valid]).all()


def test_values_from_dn(l1c):
    '''20 m band (native) and 10 m band (2 x 2 average) recomputed from the raw DN.'''
    prod = l1c.prod
    offset = -1000. if l1c.processing_baseline >= 4 else 0.
    dn, transform = _raw(l1c.abspath, 'B05')
    cols = ((prod.x.values - transform.c) // 20).astype(int)
    rows = ((transform.f - prod.y.values) // 20).astype(int)
    rho = ((dn[np.ix_(rows, cols)] + offset) / 10000).clip(min=0)
    new = prod.bands.sel(wl=705).values
    valid = np.isfinite(new)
    np.testing.assert_allclose(new[valid], rho[valid], rtol=1e-6)

    dn, _ = _raw(l1c.abspath, 'B02')
    sel = np.ix_(np.repeat(2 * rows, 2) + np.tile([0, 1], len(rows)),
                 np.repeat(2 * cols, 2) + np.tile([0, 1], len(cols)))
    mean = dn[sel].astype(np.float64).reshape(len(rows), 2, len(cols), 2).mean(axis=(1, 3))
    rho = ((mean + offset) / 10000).clip(min=0)
    new = prod.bands.sel(wl=490).values
    valid = np.isfinite(new)
    np.testing.assert_allclose(new[valid], rho[valid], rtol=1e-5)


def test_list_subset_and_dask(monkeypatch):
    '''Subset given as bounds in the product CRS; lazy product identical to the eager one.'''
    image, subset = _product('pb4')
    l1c = Sentinel2Driver(image, band_idx=[1, 8], resolution=60)
    bounds = tuple(subset.to_crs(l1c.crs).total_bounds)
    l1c = Sentinel2Driver(image, band_idx=[1, 8], subset=[bounds], resolution=60)
    l1c.load_bands(subset=l1c.subset)
    eager = l1c.prod.bands

    monkeypatch.setenv('GRSDRIVER_USE_DASK', '1')
    l1c.load_bands(subset=l1c.subset)
    assert l1c.prod.bands.chunks is not None
    np.testing.assert_allclose(l1c.prod.bands.values, eager.values, rtol=1e-6)


@pytest.mark.parametrize('key', ['pb4', 'pb2'])
def test_flat_metadata(key):
    '''Main metadata identical to the GDAL SENTINEL2 driver (compared only if GDAL is installed).'''
    import xmltodict
    from GRSdriver.driver_S2_SAFE import flat_metadata
    image, _ = _product(key)
    xml_file = os.path.join(image, 'MTD_MSIL1C.xml')
    with open(xml_file) as f:
        md = flat_metadata(xmltodict.parse(f.read())['n1:Level-1C_User_Product'])
    # items used by the driver and by GRS
    assert md['PRODUCT_URI'] == os.path.basename(image)
    assert md['DATATAKE_1_DATATAKE_SENSING_START'].startswith(md['PRODUCT_START_TIME'][:10])
    assert 0.9 < float(md['REFLECTANCE_CONVERSION_U']) < 1.1
    assert md['FOOTPRINT'].startswith('POLYGON((')
    gdal = pytest.importorskip('osgeo.gdal')
    gdal.UseExceptions()
    assert md == gdal.Open(xml_file).GetMetadata()


def test_n_workers_identical():
    '''Bands and angles read in parallel threads identical to the sequential reading.'''
    image, subset = _product('pb4')
    prods = []
    for n_workers in (1, 4):
        l1c = Sentinel2Driver(image, band_idx=[0, 1, 8, 11], subset=subset, resolution=60, n_workers=n_workers)
        l1c.load_product()
        prods.append(l1c.prod)
    for var in ('bands', 'vza', 'raa', 'sza'):
        np.testing.assert_array_equal(prods[0][var].values, prods[1][var].values)
