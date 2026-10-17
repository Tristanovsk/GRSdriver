'''
Tests of the Landsat driver on a Collection 2 L1 product.

The product directory is given by the environment variable GRSDRIVER_TEST_LANDSAT
(default below); the tests are skipped if it is not available.
'''

import glob
import os

import geopandas as gpd
import numpy as np
import pytest
import rasterio
import xmltodict
from shapely.geometry import box

from GRSdriver import LandsatDriver

IMAGE = os.getenv('GRSDRIVER_TEST_LANDSAT',
                  '/data/satellite/landsat/LC09_L1TP_196030_20221120_20230321_02_T1')
SUBSET = gpd.GeoSeries([box(3.6, 43.3, 3.9, 43.5)], crs=4326)

pytestmark = pytest.mark.skipif(not os.path.isdir(IMAGE), reason='Landsat test product not available')


def _raw(suffix):
    with rasterio.open(glob.glob(os.path.join(IMAGE, '*_' + suffix + '.TIF'))[0]) as src:
        return src.read(1), src.transform


@pytest.fixture(scope='module')
def prod():
    l1 = LandsatDriver(IMAGE, band_idx=[1, 4, 9], subset=SUBSET, resolution=30)
    l1.load_product()
    return l1.prod


def test_structure(prod):
    assert list(prod.wl.values) == [490., 665., 11000.]
    assert prod.bands.dtype == np.float32
    assert prod.flags_l1.dtype == np.uint32
    assert '_FillValue' not in prod.flags_l1.encoding
    assert prod.attrs['constellation_id'] in ('L8', 'L9')
    assert len(prod.attrs['tile']) == 6
    assert prod.attrs['radiometry'] == 'reflectance and brightness temperature'
    # 30 m grid aligned on the scene, pixel centers
    _, transform = _raw('QA_PIXEL')
    assert np.allclose((prod.x.values - transform.c) % 30, 15)
    assert np.allclose((transform.f - prod.y.values) % 30, 15)


def test_values_from_dn(prod):
    '''Values recomputed from the raw DN and the MTL coefficients.'''
    with open(glob.glob(os.path.join(IMAGE, '*_MTL.xml'))[0]) as f:
        mtd = xmltodict.parse(f.read())['LANDSAT_METADATA_FILE']
    resc = mtd['LEVEL1_RADIOMETRIC_RESCALING']
    therm = mtd['LEVEL1_THERMAL_CONSTANTS']
    qa, transform = _raw('QA_PIXEL')
    cols = ((prod.x.values - transform.c) // 30).astype(int)
    rows = ((transform.f - prod.y.values) // 30).astype(int)
    sel = np.ix_(rows, cols)
    np.testing.assert_array_equal(prod.flags_l1.values, qa[sel])

    mus = np.cos(np.radians(prod.sza.values))
    dn = _raw('B4')[0][sel].astype(np.float32)
    rho = (np.float32(resc['REFLECTANCE_MULT_BAND_4']) * dn
           + np.float32(resc['REFLECTANCE_ADD_BAND_4'])).clip(min=0) / mus
    rho[(dn == 0) | (qa[sel] == 1)] = np.nan
    np.testing.assert_allclose(prod.bands.sel(wl=665).values, rho, rtol=1e-6)

    dn = _raw('B10')[0][sel].astype(np.float32)
    rad = np.float32(resc['RADIANCE_MULT_BAND_10']) * dn + np.float32(resc['RADIANCE_ADD_BAND_10'])
    bt = np.float32(therm['K2_CONSTANT_BAND_10']) / np.log(np.float32(therm['K1_CONSTANT_BAND_10']) / rad + 1)
    bt[(dn == 0) | (qa[sel] == 1)] = np.nan
    np.testing.assert_allclose(prod.bands.sel(wl=11000).values, bt, rtol=1e-6)


def test_coarser_resolution():
    l1 = LandsatDriver(IMAGE, band_idx=[3, 4], subset=SUBSET, resolution=90)
    l1.load_product()
    assert np.allclose(np.diff(l1.prod.x.values), 90)
    # flags resampled with nearest neighbour: only existing QA_PIXEL values
    qa, _ = _raw('QA_PIXEL')
    assert np.isin(np.unique(l1.prod.flags_l1.values), np.unique(qa)).all()
    assert np.isfinite(l1.prod.bands).any()


def test_n_workers_identical():
    '''Bands read in parallel threads identical to the sequential reading.'''
    prods = []
    for n_workers in (1, 4):
        l1 = LandsatDriver(IMAGE, band_idx=[1, 4, 9], subset=SUBSET, resolution=30, n_workers=n_workers)
        l1.load_product()
        prods.append(l1.prod)
    np.testing.assert_array_equal(prods[0].bands.values, prods[1].bands.values)


@pytest.mark.parametrize('resolution', [30, 60])
def test_dask_identical(monkeypatch, resolution):
    '''Lazy (dask) product identical to the eager one, float32 angles in both modes.'''
    prods = []
    for lazy in ('0', '1'):
        monkeypatch.setenv('GRSDRIVER_USE_DASK', lazy)
        l1 = LandsatDriver(IMAGE, band_idx=[1, 4, 9], subset=SUBSET, resolution=resolution)
        l1.load_product()
        prods.append(l1.prod.compute())
    eager, lazy = prods
    for var in ('bands', 'sza', 'vza', 'raa'):
        assert eager[var].dtype == lazy[var].dtype == np.float32
        np.testing.assert_array_equal(eager[var].values, lazy[var].values)
    np.testing.assert_array_equal(eager.flags_l1.values, lazy.flags_l1.values)
