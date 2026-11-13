'''
Tests of the access to the products in a bucket (GRSdriver.remote) and of the STAC catalogues
(GRSdriver.stac).

The tests of the products in a bucket need an S3 bucket holding a Sentinel-2 L1C product also
available locally: GRSDRIVER_TEST_S3 (URL of the product in the bucket) and GRSDRIVER_TEST_S3_LOCAL
(local copy), read with the AWS profile GRSDRIVER_TEST_S3_PROFILE (defaults below: the local bucket of
grstbx, ``grstbx-s3-bucket``); they are skipped if they are not available. The Landsat product of
test_landsat_driver.py is used to test the catalogues of local products.
'''

import json
import os

import numpy as np
import pytest

from GRSdriver import remote, stac

S3_PRODUCT = os.getenv('GRSDRIVER_TEST_S3', 's3://grstbx-s3/sentinel-2/l1c/31TFJ/2023/06/11/'
                                             'S2A_MSIL1C_20230611T103631_N0509_R008_T31TFJ_20230611T155912.SAFE')
S3_LOCAL = os.getenv('GRSDRIVER_TEST_S3_LOCAL', '/data/satellite/Sentinel-2/L1C/31TFJ/2023/06/11/'
                                                'S2A_MSIL1C_20230611T103631_N0509_R008_T31TFJ_20230611T155912.SAFE')
S3_PROFILE = os.getenv('GRSDRIVER_TEST_S3_PROFILE', 'grstbx-local')
LANDSAT = os.getenv('GRSDRIVER_TEST_LANDSAT',
                    '/data/satellite/landsat/LC09_L1TP_196030_20221120_20230321_02_T1')


# ---------------------------------------------------------------------------------------------------
# remote
# ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('path, expected', [
    ('/data/a.jp2', '/data/a.jp2'),
    ('s3://bucket/key/a.jp2', '/vsis3/bucket/key/a.jp2'),
    ('gs://bucket/a.tif', '/vsigs/bucket/a.tif'),
    ('https://host/a.tif', '/vsicurl/https://host/a.tif'),
])
def test_gdal_path(path, expected):
    assert remote.gdal_path(path) == expected


def test_gdal_options(tmp_path, monkeypatch):
    for name in ('AWS_PROFILE', 'AWS_DEFAULT_PROFILE', 'AWS_ENDPOINT_URL', 'AWS_ENDPOINT_URL_S3', 'AWS_REGION',
                 'AWS_DEFAULT_REGION'):
        monkeypatch.delenv(name, raising=False)
    config = tmp_path / 'config'
    config.write_text('[profile local]\nregion = us-east-1\nendpoint_url = http://127.0.0.1:9000\n')
    monkeypatch.setenv('AWS_CONFIG_FILE', str(config))
    assert remote.gdal_options('/data/product') == {}

    # endpoint of the AWS profile
    monkeypatch.setenv('AWS_PROFILE', 'local')
    options = remote.gdal_options('s3://bucket/product')
    assert options['AWS_S3_ENDPOINT'] == '127.0.0.1:9000'
    assert options['AWS_HTTPS'] == 'NO' and options['AWS_VIRTUAL_HOSTING'] == 'FALSE'
    assert options['AWS_REGION'] == 'us-east-1'

    # explicit options of fsspec/s3fs
    options = remote.gdal_options('s3://eodata/product', {'key': 'k', 'secret': 's', 'requester_pays': True,
                                                         'endpoint_url': 'https://eodata.example.eu'})
    assert options['AWS_S3_ENDPOINT'] == 'eodata.example.eu' and options['AWS_HTTPS'] == 'YES'
    assert options['AWS_ACCESS_KEY_ID'] == 'k' and options['AWS_SECRET_ACCESS_KEY'] == 's'
    assert options['AWS_REQUEST_PAYER'] == 'requester'
    monkeypatch.delenv('AWS_PROFILE')
    assert remote.gdal_options('s3://bucket/p', {'anon': True})['AWS_NO_SIGN_REQUEST'] == 'YES'
    assert 'AWS_S3_ENDPOINT' not in remote.gdal_options('s3://bucket/p')


def test_product_files(tmp_path):
    root = tmp_path / 'S2A_MSIL1C_20230611T103631_N0509_R008_T31TFJ_20230611T155912.SAFE'
    for rel in ('MTD_MSIL1C.xml', 'GRANULE/L1C_T31TFJ/MTD_TL.xml', 'GRANULE/L1C_T31TFJ/IMG_DATA/T31TFJ_B02.jp2',
                'GRANULE/L1C_T31TFJ/IMG_DATA/T31TFJ_B8A.jp2'):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(rel)
    files = remote.ProductFiles(root)
    assert files.name == root.name and len(files.files) == 4
    # '*' does not match '/', as glob
    assert files.find('*.xml') == [str(root / 'MTD_MSIL1C.xml')]
    assert files.find('GRANULE/*/IMG_DATA/*_B8A.jp2') == [str(root / 'GRANULE/L1C_T31TFJ/IMG_DATA/T31TFJ_B8A.jp2')]
    assert files.read_text(files.get('GRANULE/*/MTD_TL.xml')) == 'GRANULE/L1C_T31TFJ/MTD_TL.xml'
    with pytest.raises(FileNotFoundError):
        files.get('*_MTL.xml')
    # product described by its files (e.g. assets of a STAC Item)
    url = 'https://host/data/LC09_L1TP_196030_20221120_20230321_02_T1'
    files = remote.ProductFiles(url, hrefs=[url + '/LC09_B1.TIF', url + '/LC09_MTL.xml'])
    assert files.find('*_MTL.xml') == [url + '/LC09_MTL.xml'] and files.name == url.rsplit('/', 1)[1]


# ---------------------------------------------------------------------------------------------------
# STAC
# ---------------------------------------------------------------------------------------------------

def _item(id, datetime, bbox, cloud, collection='sentinel-2-l1c', assets=None, **props):
    lon0, lat0, lon1, lat1 = bbox
    return {'type': 'Feature', 'stac_version': '1.0.0', 'id': id, 'collection': collection, 'bbox': list(bbox),
            'geometry': {'type': 'Polygon', 'coordinates': [[[lon0, lat0], [lon1, lat0], [lon1, lat1],
                                                             [lon0, lat1], [lon0, lat0]]]},
            'properties': {'datetime': datetime, 'eo:cloud_cover': cloud, **props}, 'links': [],
            'assets': assets or {}}


def test_sensor_and_tile():
    assert stac.sensor_of('s3://b/S2A_MSIL1C_20230611T103631_N0509_R008_T31TFJ_20230611T155912.SAFE/') == 'S2'
    assert stac.sensor_of('/d/LC09_L1TP_196030_20221120_20230321_02_T1') == 'L'
    assert stac.sensor_of('/d/S2A_MSIL2A_20230611T103631_N0509_R008_T31TFJ_20230611T155912.SAFE') is None
    assert stac.item_tile({'properties': {'grid:code': 'MGRS-31TFJ'}}) == '31TFJ'
    assert stac.item_tile({'properties': {'landsat:wrs_path': '196', 'landsat:wrs_row': '30'}}) == '196030'
    assert stac.item_tile({'id': 'S2A_MSIL1C_20230611T103631_N0509_R008_T31TFJ_20230611T155912',
                           'properties': {}}) == '31TFJ'


def test_product_href():
    safe = 's3://eodata/Sentinel-2/MSI/L1C/2023/06/11/S2A_MSIL1C_20230611T103631_N0509_R008_T31TFJ_20230611T155912.SAFE'
    # Items of build_catalog
    assert stac.product_href(_item('a', '2023-06-11', (0, 0, 1, 1), 0, assets={'product': {'href': safe + '/'}})) == safe
    # assets in the SAFE folder (e.g. Copernicus Data Space)
    item = _item('a', '2023-06-11', (0, 0, 1, 1), 0,
                 assets={'B02': {'href': safe + '/GRANULE/L1C_T31TFJ/IMG_DATA/T31TFJ_B02.jp2'}})
    assert stac.product_href(item) == safe
    # folder of the metadata file, alternate hrefs (e.g. USGS)
    folder = 'collection02/level-1/standard/oli-tirs/2022/196/030/LC09_L1TP_196030_20221120_20230321_02_T1'
    item = _item('LC09', '2022-11-20', (0, 0, 1, 1), 0, collection='landsat-c2-l1', assets={'mtl.xml': {
        'href': f'https://landsatlook.usgs.gov/data/{folder}/LC09_L1TP_196030_20221120_20230321_02_T1_MTL.xml',
        'alternate': {'s3': {'href': f's3://usgs-landsat/{folder}/LC09_L1TP_196030_20221120_20230321_02_T1_MTL.xml'}}}})
    assert stac.product_href(item) == f'https://landsatlook.usgs.gov/data/{folder}'
    assert stac.product_href(item, alternate='s3') == f's3://usgs-landsat/{folder}'
    with pytest.raises(ValueError):
        stac.product_href(_item('a', '2023-06-11', (0, 0, 1, 1), 0, assets={'thumbnail': {'href': 'q.png'}}))


def test_search_static_catalog(tmp_path):
    # small static catalogue: Items read at once (items.json) or one by one (item links)
    items = [_item('S2A_MSIL1C_20230601T104021_N0509_R008_T31TFJ_20230601T191959', '2023-06-01T10:40:21Z',
                   (4.2, 43.2, 5.6, 44.2), 31.4, **{'grid:code': 'MGRS-31TFJ'}),
             _item('S2B_MSIL1C_20230616T103629_N0509_R008_T31TFJ_20230616T111910', '2023-06-16T10:36:29Z',
                   (4.2, 43.2, 5.6, 44.2), 0.3, **{'grid:code': 'MGRS-31TFJ'},
                   assets={'product': {'href': '/data/S2B_MSIL1C_20230616T103629_N0509_R008_T31TFJ_20230616T111910.SAFE'}}),
             _item('S2B_MSIL1C_20230616T103629_N0509_R008_T31TGJ_20230616T111910', '2023-06-16T10:36:29Z',
                   (5.5, 43.2, 6.9, 44.2), 2.0, **{'grid:code': 'MGRS-31TGJ'})]
    col = tmp_path / 'sentinel-2-l1c'
    for item in items:
        (col / item['id']).mkdir(parents=True)
        (col / item['id'] / (item['id'] + '.json')).write_text(json.dumps(item))
    (col / 'items.json').write_text(json.dumps({'type': 'FeatureCollection', 'features': items}))
    item_links = [{'rel': 'item', 'href': f"./{item['id']}/{item['id']}.json"} for item in items]
    for with_items in (True, False):
        links = item_links + ([{'rel': 'items', 'href': './items.json'}] if with_items else [])
        (col / 'collection.json').write_text(json.dumps({'type': 'Collection', 'id': 'sentinel-2-l1c', 'links': links}))
        (tmp_path / 'catalog.json').write_text(json.dumps(
            {'type': 'Catalog', 'id': 'c', 'links': [{'rel': 'child', 'href': './sentinel-2-l1c/collection.json'}]}))
        catalog = str(tmp_path / 'catalog.json')

        assert len(stac.search(catalog)) == 3
        found = stac.search(catalog, bbox=(4.5, 43.5, 4.6, 43.6), max_cloud_cover=10)
        assert list(found.id) == [items[1]['id']] and found.href[0].endswith('.SAFE')
        assert found.tile[0] == '31TFJ' and found.cloud_cover[0] == pytest.approx(0.3)
        assert list(stac.search(catalog, start='2023-06-02', tile='31TGJ').id) == [items[2]['id']]
        assert list(stac.search(catalog, end='2023-06-01').id) == [items[0]['id']]
        assert len(stac.search(catalog, collections='landsat-c2-l1')) == 0
        # self links: relative hrefs of the Items resolved from their location
        self_href = next(link['href'] for link in found.item[0]['links'] if link['rel'] == 'self')
        assert os.path.isfile(self_href)


@pytest.mark.skipif(not os.path.isdir(LANDSAT), reason='Landsat test product not available')
def test_catalog_of_local_products(tmp_path):
    folder = os.path.dirname(LANDSAT)
    assert LANDSAT in stac.find_products(folder, maxdepth=1)
    item = stac.product_item(LANDSAT)
    assert item['collection'] == 'landsat-c2-l1' and item['properties']['proj:code'].startswith('EPSG:326')
    assert item['assets']['product']['href'] == LANDSAT

    # catalogue of a local folder, the products described with their (would-be) bucket URLs
    counts, _ = stac.build_catalog({folder: 's3://bucket/landsat'}, str(tmp_path / 'stac'), maxdepth=1)
    assert counts['landsat-c2-l1'] >= 1
    found = stac.search(str(tmp_path / 'stac' / 'catalog.json'), tile=item['properties']['grid:code'][5:])
    assert found.href[0] == 's3://bucket/landsat/' + os.path.basename(LANDSAT)

    # local catalogue: products opened from the Items
    stac.build_catalog([folder], str(tmp_path / 'local'), maxdepth=1)
    found = stac.search(str(tmp_path / 'local' / 'catalog.json'), tile=item['properties']['grid:code'][5:])
    l1 = stac.open_item(found.iloc[0], band_idx=[1])
    assert type(l1).__name__ == 'LandsatDriver' and l1.abspath == LANDSAT


# ---------------------------------------------------------------------------------------------------
# products in a bucket
# ---------------------------------------------------------------------------------------------------

@pytest.fixture(scope='module')
def s3_product():
    pytest.importorskip('s3fs')
    if not os.path.isdir(S3_LOCAL):
        pytest.skip('local copy of the S3 test product not available: ' + S3_LOCAL)
    so = {'profile': S3_PROFILE}
    try:
        files = remote.ProductFiles(S3_PRODUCT, so)
    except Exception as exc:  # noqa: BLE001 (no bucket, no credentials...)
        pytest.skip(f'S3 test product not available: {S3_PRODUCT} ({exc})')
    return files, so


def test_s3_same_as_local(s3_product):
    import geopandas as gpd
    from GRSdriver import Sentinel2Driver

    files, so = s3_product
    prods = []
    for path, options in ((S3_LOCAL, None), (S3_PRODUCT, so)):
        l1c = Sentinel2Driver(path, band_idx=[1, 8], band_tbp_idx=[1, 8], resolution=60, storage_options=options)
        l1c.subset = gpd.GeoSeries([l1c.extent.geometry[0].centroid.buffer(3000)], crs=l1c.crs)
        l1c.load_product()
        prods.append(l1c.prod)
    assert prods[1].attrs['product_path'] == S3_PRODUCT.rstrip('/')
    for name in ('bands', 'vza', 'raa', 'sza'):
        assert np.array_equal(prods[0][name].values, prods[1][name].values, equal_nan=True), name
    assert np.isfinite(prods[1].vza.values).any()
