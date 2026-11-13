'''
STAC catalogues of Level-1 products: build a catalogue of the products of a bucket, search a catalogue,
and open the products found with the drivers, in place (see :mod:`GRSdriver.remote`).

- :func:`build_catalog` writes a static STAC catalogue of Sentinel-2 L1C (SAFE) and Landsat
  Collection-2 L1 products, collections ``sentinel-2-l1c`` and ``landsat-c2-l1``, with the URLs of the
  products in the bucket. The layout is that of the catalogues of grstbx (``grstbx.stac``), which can
  read it as well::

      <out_dir>/catalog.json
      <out_dir>/sentinel-2-l1c/collection.json
      <out_dir>/sentinel-2-l1c/items.json      all the Items of the collection, read at once by a search
      <out_dir>/sentinel-2-l1c/<id>/<id>.json
      <out_dir>/landsat-c2-l1/...

- :func:`search` selects the products of a static catalogue (``catalog.json`` or ``collection.json``,
  local, in a bucket or over https) or of a STAC API (Item Search, ``POST /search``) by area, period,
  cloud cover, tile and collection;
- :func:`open_item` returns the driver (:class:`~GRSdriver.Sentinel2Driver` or
  :class:`~GRSdriver.LandsatDriver`) of an Item: its product folder is found from the assets of the
  Item (asset ``product`` of the Items of :func:`build_catalog`, folder ``.SAFE`` of the assets, or
  folder of the metadata file ``MTD_MSIL1C.xml`` / ``*_MTL.xml``).

Example with the local bucket of grstbx (``grstbx-s3-bucket``, products read in place)::

    import os
    os.environ['AWS_PROFILE'] = 'grstbx-local'
    from GRSdriver import stac

    # once, and when products are added (local folder scanned, URLs of the bucket in the Items)
    stac.build_catalog({'/data/satellite/Sentinel-2/L1C': 's3://grstbx-s3/sentinel-2/l1c'},
                       's3://grstbx-s3/stac-l1')

    found = stac.search('s3://grstbx-s3/stac-l1/catalog.json', bbox=(5.03, 43.40, 5.24, 43.56),
                        start='2023-06-01', end='2023-06-30', max_cloud_cover=20)
    l1c = stac.open_item(found.item[0], resolution=20)
    l1c.load_product()
'''

import json
import os
import posixpath
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import xmltodict

from .remote import ProductFiles, get_fs, is_url

STAC_VERSION = '1.0.0'
STAC_EXTENSIONS = [
    'https://stac-extensions.github.io/eo/v1.1.0/schema.json',
    'https://stac-extensions.github.io/projection/v2.0.0/schema.json',
    'https://stac-extensions.github.io/grid/v1.1.0/schema.json',
    'https://stac-extensions.github.io/processing/v1.2.0/schema.json',
    'https://stac-extensions.github.io/sat/v1.0.0/schema.json',
]
COLLECTIONS = {
    'S2': {'id': 'sentinel-2-l1c', 'title': 'Sentinel-2 L1C',
           'description': 'Sentinel-2 MSI Level-1C products (SAFE format): top-of-atmosphere reflectance'},
    'L': {'id': 'landsat-c2-l1', 'title': 'Landsat Collection 2 Level-1',
          'description': 'Landsat 8/9 OLI/TIRS Collection 2 Level-1 products'},
}
MEDIA_JSON = 'application/json'
MEDIA_GEOJSON = 'application/geo+json'
MEDIA_XML = 'application/xml'

S2_NAME = re.compile(r'^S2[A-D]_MSIL1C_\d{8}T\d{6}_N\d{4}_R\d{3}_T\w{5}_\d{8}T\d{6}(\.SAFE)?$')
'''Name of a Sentinel-2 L1C product folder.'''
LANDSAT_NAME = re.compile(r'^L[COTEM]0\d_L1(TP|GT|GS)_\d{6}_\d{8}_\d{8}_\d{2}_(T1|T2|RT)$')
'''Name of a Landsat Collection 2 Level-1 product folder.'''
SEARCH_COLUMNS = ['id', 'collection', 'datetime', 'platform', 'tile', 'cloud_cover', 'href', 'item']


def sensor_of(name):
    '''``'S2'`` (Sentinel-2 L1C), ``'L'`` (Landsat C2 L1) or None, from the name of a product folder.'''
    name = posixpath.basename(str(name).rstrip('/').replace(os.sep, '/'))
    if S2_NAME.match(name):
        return 'S2'
    if LANDSAT_NAME.match(name):
        return 'L'
    return None


# ---------------------------------------------------------------------------------------------------
# Items of the products
# ---------------------------------------------------------------------------------------------------

def _isotime(value):
    '''ISO date in UTC (``...Z``) of a date string.'''
    time = pd.Timestamp(value)
    time = time.tz_localize('UTC') if time.tzinfo is None else time.tz_convert('UTC')
    return time.strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def _polygon(lonlat):
    '''GeoJSON polygon of a ring of (lon, lat) points, and its bounding box.'''
    ring = [[round(float(lon), 7), round(float(lat), 7)] for lon, lat in lonlat]
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    lons, lats = [p[0] for p in ring], [p[1] for p in ring]
    return {'type': 'Polygon', 'coordinates': [ring]}, [min(lons), min(lats), max(lons), max(lats)]


def _s2_item(files):
    '''Properties, geometry and assets of a Sentinel-2 L1C product (``MTD_MSIL1C.xml`` and ``MTD_TL.xml``).'''
    from .driver_S2_SAFE import flat_metadata

    xml_file = files.get('MTD*.xml') if files.find('MTD*.xml') else files.get('*MTD*.xml')
    product = xmltodict.parse(files.read_bytes(xml_file))
    product = product[next(iter(product))]
    md = flat_metadata(product)
    name = md.get('PRODUCT_URI', files.name).replace('.SAFE', '')
    pos = [float(v) for v in md['FOOTPRINT'][len('POLYGON(('):-2].replace(',', ' ').split()]
    geometry, bbox = _polygon(zip(pos[0::2], pos[1::2]))
    tile = name.split('_')[5][1:]
    properties = {
        'datetime': _isotime(md['DATATAKE_1_DATATAKE_SENSING_START']),
        'constellation': 'sentinel-2',
        'platform': md['DATATAKE_1_SPACECRAFT_NAME'].lower(),
        'instruments': ['msi'],
        'eo:cloud_cover': float(md['CLOUD_COVERAGE_ASSESSMENT']),
        'grid:code': f'MGRS-{tile}',
        'processing:level': 'L1C',
        'sat:relative_orbit': int(md['DATATAKE_1_SENSING_ORBIT_NUMBER']),
        'sat:orbit_state': md['DATATAKE_1_SENSING_ORBIT_DIRECTION'].lower(),
        's2:processing_baseline': md['PROCESSING_BASELINE'],
    }
    assets = {'product': {'href': files.root, 'title': 'SAFE product folder', 'roles': ['data']},
              'metadata': {'href': xml_file, 'type': MEDIA_XML, 'title': 'Product metadata',
                           'roles': ['metadata']}}
    granule = files.find('GRANULE/*/MTD_TL.xml') or files.find('GRANULE/*/*MTD*.xml')
    if granule:
        import xml.etree.ElementTree as ET

        assets['granule_metadata'] = {'href': granule[0], 'type': MEDIA_XML, 'title': 'Granule metadata',
                                      'roles': ['metadata']}
        geocoding = ET.fromstring(files.read_bytes(granule[0])).find('.//Tile_Geocoding')
        ulx = float(geocoding.findtext("Geoposition[@resolution='10']/ULX"))
        uly = float(geocoding.findtext("Geoposition[@resolution='10']/ULY"))
        ncols = int(geocoding.findtext("Size[@resolution='10']/NCOLS"))
        nrows = int(geocoding.findtext("Size[@resolution='10']/NROWS"))
        properties.update({'proj:code': geocoding.findtext('HORIZONTAL_CS_CODE'),
                           'proj:shape': [nrows, ncols],
                           'proj:transform': [10.0, 0.0, ulx, 0.0, -10.0, uly],
                           'proj:bbox': [ulx, uly - 10 * nrows, ulx + 10 * ncols, uly]})
    return name, properties, geometry, bbox, assets


def _landsat_item(files):
    '''Properties, geometry and assets of a Landsat Collection 2 L1 product (``*_MTL.xml``).'''
    xml_file = files.get('*_MTL.xml')
    md = xmltodict.parse(files.read_bytes(xml_file))['LANDSAT_METADATA_FILE']
    image, proj = md['IMAGE_ATTRIBUTES'], md['PROJECTION_ATTRIBUTES']
    name = md['PRODUCT_CONTENTS']['LANDSAT_PRODUCT_ID']
    corners = ('UL', 'UR', 'LR', 'LL')
    geometry, bbox = _polygon((proj[f'CORNER_{c}_LON_PRODUCT'], proj[f'CORNER_{c}_LAT_PRODUCT']) for c in corners)
    path, row = int(image['WRS_PATH']), int(image['WRS_ROW'])
    properties = {
        'datetime': _isotime(image['DATE_ACQUIRED'] + 'T' + image['SCENE_CENTER_TIME'].rstrip('Z')[:15]),
        'constellation': 'landsat',
        'platform': image['SPACECRAFT_ID'].lower().replace('_', '-'),
        'instruments': [s.lower() for s in image['SENSOR_ID'].split('_')],
        'eo:cloud_cover': float(image['CLOUD_COVER']),
        'grid:code': f'WRS2-{path:03d}{row:03d}',
        'processing:level': md['PRODUCT_CONTENTS'].get('PROCESSING_LEVEL', 'L1'),
        'landsat:wrs_path': f'{path:03d}',
        'landsat:wrs_row': f'{row:03d}',
        'landsat:collection_category': md['PRODUCT_CONTENTS'].get('COLLECTION_CATEGORY'),
    }
    if proj.get('MAP_PROJECTION') == 'UTM':
        res = float(proj['GRID_CELL_SIZE_REFLECTIVE'])
        ulx, uly = float(proj['CORNER_UL_PROJECTION_X_PRODUCT']), float(proj['CORNER_UL_PROJECTION_Y_PRODUCT'])
        lrx, lry = float(proj['CORNER_LR_PROJECTION_X_PRODUCT']), float(proj['CORNER_LR_PROJECTION_Y_PRODUCT'])
        # corners: centers of the corner pixels
        properties.update({'proj:code': f"EPSG:326{int(proj['UTM_ZONE']):02d}",
                           'proj:shape': [int(proj['REFLECTIVE_LINES']), int(proj['REFLECTIVE_SAMPLES'])],
                           'proj:transform': [res, 0.0, ulx - res / 2, 0.0, -res, uly + res / 2],
                           'proj:bbox': [ulx - res / 2, lry - res / 2, lrx + res / 2, uly + res / 2]})
    assets = {'product': {'href': files.root, 'title': 'Product folder', 'roles': ['data']},
              'metadata': {'href': xml_file, 'type': MEDIA_XML, 'title': 'Product metadata (MTL)',
                           'roles': ['metadata']}}
    return name, {k: v for k, v in properties.items() if v is not None}, geometry, bbox, assets


def product_item(path, storage_options=None):
    '''
    STAC Item of a Level-1 product, from its metadata files only (no raster read).

    The assets are the product folder (``product``, role ``data``, opened by :func:`open_item`) and its
    metadata files, with the locations of the files (local paths or URLs).

    :param path: product folder: local path, URL or :class:`~GRSdriver.remote.ProductFiles`
    :param storage_options: options of the fsspec file system of a URL
    :return: Item (dict)
    '''
    files = path if isinstance(path, ProductFiles) else ProductFiles(path, storage_options)
    sensor = sensor_of(files.name)
    if sensor is None:
        raise ValueError(f'{files.root} is neither a Sentinel-2 L1C nor a Landsat C2 L1 product')
    name, properties, geometry, bbox, assets = (_s2_item if sensor == 'S2' else _landsat_item)(files)
    return {'type': 'Feature', 'stac_version': STAC_VERSION, 'stac_extensions': list(STAC_EXTENSIONS),
            'id': name, 'collection': COLLECTIONS[sensor]['id'], 'properties': properties,
            'geometry': geometry, 'bbox': bbox, 'links': [], 'assets': assets}


# ---------------------------------------------------------------------------------------------------
# catalogue
# ---------------------------------------------------------------------------------------------------

def find_products(root, storage_options=None, maxdepth=6):
    '''
    Folders of Level-1 products below ``root`` (local folder or URL), recognized by their names (see
    :data:`S2_NAME` and :data:`LANDSAT_NAME`), up to ``maxdepth`` levels, e.g.
    ``<root>/<tile>/YYYY/MM/DD/<product>``.

    :return: sorted list of local paths or URLs
    '''
    if not is_url(root):
        found = []
        for folder, dirs, _ in os.walk(os.path.abspath(root), followlinks=True):
            depth = os.path.relpath(folder, root).count(os.sep) + 1
            found += [os.path.join(folder, d) for d in dirs if sensor_of(d)]
            dirs[:] = [d for d in dirs if not sensor_of(d)] if depth < maxdepth else []
        return sorted(found)
    fs, path = get_fs(root, storage_options)
    found, level = [], [path.rstrip('/')]

    def subfolders(folder):
        try:
            entries = fs.ls(folder, detail=True)
        except FileNotFoundError:       # empty folder (no object below it)
            return []
        return [entry['name'].rstrip('/') for entry in entries if entry['type'] == 'directory']

    with ThreadPoolExecutor(16) as pool:
        for _ in range(maxdepth):
            folders = [f for sub in pool.map(subfolders, level) for f in sub]
            found += [f for f in folders if sensor_of(f)]
            level = [f for f in folders if not sensor_of(f)]
            if not level:
                break
    return sorted(fs.unstrip_protocol(f) for f in found)


def _write_json(path, content, storage_options=None):
    text = json.dumps(content, indent=1)
    if is_url(path):
        fs, fpath = get_fs(path, storage_options)
        fs.pipe_file(fpath, text.encode())
        return
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = f'{path}.part{os.getpid()}'
    with open(tmp, 'w') as f:
        f.write(text)
    os.replace(tmp, path)


def _join(base, *parts):
    '''Path or URL ``base/parts``.'''
    return posixpath.join(base, *parts) if is_url(base) else os.path.join(base, *parts)


def _to_url(href, roots):
    '''URL in the bucket of a local path below one of the ``roots`` (dict {folder: URL}); else unchanged.'''
    if is_url(href):
        return href
    path = os.path.abspath(href)
    for root, url in roots.items():
        root = os.path.abspath(root)
        if path == root or path.startswith(root + os.sep):
            return url.rstrip('/') + path[len(root):].replace(os.sep, '/')
    return href


def _extent(items):
    boxes = [item['bbox'] for item in items]
    times = sorted(item['properties']['datetime'] for item in items)
    return {'spatial': {'bbox': [[min(b[0] for b in boxes), min(b[1] for b in boxes),
                                  max(b[2] for b in boxes), max(b[3] for b in boxes)]]},
            'temporal': {'interval': [[times[0], times[-1]]]}}


def build_catalog(roots, out_dir, title='Level-1 products', description='Sentinel-2 L1C and Landsat C2 L1 products',
                  license='proprietary', workers=8, storage_options=None, maxdepth=6):
    '''
    Write the static STAC catalogue of the Level-1 products of folders (see :mod:`GRSdriver.stac`).
    Run it again when products are added: the catalogue is rewritten.

    :param roots: folders of products: dict {local folder: URL of this folder in the bucket}, e.g.
        ``{'/data/satellite/Sentinel-2/L1C': 's3://grstbx-s3/sentinel-2/l1c'}`` (the products are read on
        disk, much faster than in the bucket, and described with their URLs in the bucket); or list of
        folders (URLs in the bucket, or local folders for a local catalogue)
    :param out_dir: folder of the catalogue, local or URL (e.g. ``s3://grstbx-s3/stac-l1``)
    :param title: title of the catalogue
    :param description: description of the catalogue
    :param license: license of the collections
    :param workers: number of products described in parallel
    :param storage_options: options of the fsspec file system of the URLs
    :param maxdepth: depth of the search of the products below each folder
    :return: (number of Items per collection, list of (product, error) of the products skipped)
    '''
    if not isinstance(roots, dict):
        roots = {root: None for root in ([roots] if isinstance(roots, (str, os.PathLike)) else roots)}
    mapping = {str(root): url for root, url in roots.items() if url}
    products = [p for root in roots for p in find_products(str(root), storage_options, maxdepth)]

    def describe(path):
        try:
            item = product_item(path, storage_options)
        except Exception as exc:  # noqa: BLE001 (incomplete or corrupted product: skipped, reported)
            return path, None, f'{type(exc).__name__}: {exc}'
        for asset in item['assets'].values():
            asset['href'] = _to_url(asset['href'], mapping)
        return path, item, None

    with ThreadPoolExecutor(max(1, workers)) as pool:
        results = list(pool.map(describe, products))
    skipped = [(path, error) for path, item, error in results if item is None]
    items = {}
    for _, item, _ in results:
        if item is not None:
            items.setdefault(item['collection'], {})[item['id']] = item     # one Item per product id

    children = []
    for sensor, spec in COLLECTIONS.items():
        level_items = sorted(items.get(spec['id'], {}).values(), key=lambda item: item['properties']['datetime'])
        if not level_items:
            continue
        folder = _join(out_dir, spec['id'])
        for item in level_items:
            item['links'] = [{'rel': 'root', 'href': '../../catalog.json', 'type': MEDIA_JSON},
                             {'rel': 'parent', 'href': '../collection.json', 'type': MEDIA_JSON},
                             {'rel': 'collection', 'href': '../collection.json', 'type': MEDIA_JSON}]
        with ThreadPoolExecutor(max(1, workers)) as pool:
            list(pool.map(lambda item: _write_json(_join(folder, item['id'], item['id'] + '.json'), item,
                                                   storage_options), level_items))
        # in items.json too, the links are relative to the folder of each Item: <id>/
        _write_json(_join(folder, 'items.json'), {'type': 'FeatureCollection', 'features': level_items},
                    storage_options)
        _write_json(_join(folder, 'collection.json'), storage_options=storage_options, content={
            'type': 'Collection', 'stac_version': STAC_VERSION, 'id': spec['id'], 'title': spec['title'],
            'description': spec['description'], 'license': license, 'extent': _extent(level_items),
            'summaries': {
                'platform': sorted({item['properties']['platform'] for item in level_items}),
                'grid:code': sorted({item['properties']['grid:code'] for item in level_items})},
            'links': [{'rel': 'root', 'href': '../catalog.json', 'type': MEDIA_JSON},
                      {'rel': 'parent', 'href': '../catalog.json', 'type': MEDIA_JSON},
                      {'rel': 'items', 'href': './items.json', 'type': MEDIA_GEOJSON}]
            + [{'rel': 'item', 'href': f"./{item['id']}/{item['id']}.json", 'type': MEDIA_GEOJSON}
               for item in level_items]})
        children.append({'rel': 'child', 'href': f"./{spec['id']}/collection.json", 'type': MEDIA_JSON,
                         'title': spec['title']})
    _write_json(_join(out_dir, 'catalog.json'), storage_options=storage_options, content={
        'type': 'Catalog', 'stac_version': STAC_VERSION, 'id': 'grsdriver-l1', 'title': title,
        'description': description,
        'links': [{'rel': 'root', 'href': './catalog.json', 'type': MEDIA_JSON}] + children})
    return {spec['id']: len(items.get(spec['id'], {})) for spec in COLLECTIONS.values()}, skipped


# ---------------------------------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------------------------------

def _read_json(location, storage_options=None, timeout=60, headers=None):
    '''JSON document of a URL (``http(s)://`` with urllib, other schemes through fsspec) or local file.'''
    if re.match(r'https?://', location):
        req = urllib.request.Request(location, headers={'Accept': 'application/geo+json, application/json',
                                                        **(headers or {})})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.load(response)
    if is_url(location):
        fs, path = get_fs(location, storage_options)
        return json.loads(fs.cat_file(path))
    with open(location) as f:
        return json.load(f)


def _resolve(base, href):
    '''Location of ``href`` relative to the document ``base`` (URL of any scheme, or local path).'''
    if is_url(href) or os.path.isabs(href):
        return href
    if not is_url(base):
        return os.path.normpath(os.path.join(os.path.dirname(base), href))
    scheme, rest = base.split('://', 1)
    return f'{scheme}://' + posixpath.normpath(posixpath.join(posixpath.dirname(rest), href))


def _self_href(item):
    return next((link['href'] for link in item.get('links', []) if link.get('rel') == 'self'), None)


def _static_items(source, collections=None, storage_options=None, headers=None):
    '''
    Items of a static catalogue, following its ``child`` links: the ``items`` link of a collection
    (read at once, see :func:`build_catalog`), or else its ``item`` links, read in parallel. A ``self``
    link to its location is added to each Item, to resolve its relative hrefs.
    '''
    collections = [collections] if isinstance(collections, str) else collections
    read = lambda location: _read_json(location, storage_options, headers=headers)  # noqa: E731
    node = read(source)
    pending, items, item_hrefs = [(node, source)], [], []
    while pending:
        node, base = pending.pop(0)
        wanted = node.get('type') != 'Collection' or not collections or node.get('id') in collections
        links = node.get('links', [])
        items_link = next((link for link in links if link.get('rel') == 'items'), None)
        if wanted and items_link and node.get('type') == 'Collection':
            href = _resolve(base, items_link['href'])
            try:
                features = read(href).get('features', [])
            except (OSError, ValueError):
                features = None         # e.g. a STAC API collection: its item links are read instead
            if features is not None:
                for item in features:
                    if _self_href(item) is None:
                        item.setdefault('links', []).append(
                            {'rel': 'self', 'href': _resolve(href, f"{item['id']}/{item['id']}.json")})
                items += features
                links = [link for link in links if link.get('rel') != 'item']
        for link in links:
            if link.get('rel') == 'child':
                href = _resolve(base, link['href'])
                pending.append((read(href), href))
            elif link.get('rel') == 'item' and wanted:
                item_hrefs.append(_resolve(base, link['href']))
    if item_hrefs:
        def fetch(href):
            item = read(href)
            if _self_href(item) is None:
                item.setdefault('links', []).append({'rel': 'self', 'href': href})
            return item

        with ThreadPoolExecutor(16) as pool:
            items += list(pool.map(fetch, item_hrefs))
    return items


def _api_items(url, body, limit, timeout=60, headers=None):
    '''Items of a STAC API Item Search (``POST <url>/search``), following the ``next`` links.'''
    url = url.rstrip('/')
    request = {'url': url if url.endswith('/search') else url + '/search', 'method': 'POST', 'body': body}
    items = []
    while request and len(items) < limit:
        data = json.dumps(request['body']).encode() if request.get('body') is not None else None
        method = request.get('method', 'POST' if data else 'GET')
        req = urllib.request.Request(request['url'], data=data if method == 'POST' else None, method=method,
                                     headers={'Content-Type': 'application/json',
                                              'Accept': 'application/geo+json, application/json',
                                              **(headers or {})})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            page = json.load(response)
        items += page.get('features', [])
        link = next((link for link in page.get('links', []) if link.get('rel') == 'next'), None)
        if not link or not page.get('features'):
            break
        next_body = link.get('body')
        if next_body is not None and link.get('merge'):
            next_body = {**request['body'], **next_body}
        request = {'url': link['href'], 'method': link.get('method', 'GET'), 'body': next_body}
    return items[:limit]


def item_tile(item):
    '''Tile of an Item: MGRS tile (e.g. ``31TFJ``) or WRS-2 path/row (e.g. ``196030``), None if unknown.'''
    props = item.get('properties', {})
    if props.get('grid:code'):
        return props['grid:code'].split('-', 1)[-1]
    if props.get('s2:mgrs_tile'):
        return props['s2:mgrs_tile']
    if 'mgrs:utm_zone' in props:
        return f"{int(props['mgrs:utm_zone']):02d}{props.get('mgrs:latitude_band', '')}{props.get('mgrs:grid_square', '')}"
    if 'landsat:wrs_path' in props:
        return f"{int(props['landsat:wrs_path']):03d}{int(props['landsat:wrs_row']):03d}"
    match = re.search(r'_T(\d{2}[A-Z]{3})_', item.get('id', '')) or \
        re.match(r'L[COTEM]0\d_\w{4}_(\d{6})_', item.get('id', ''))
    return match.group(1) if match else None


def search(source, bbox=None, intersects=None, start=None, end=None, max_cloud_cover=None, tile=None,
           collections=None, limit=1000, storage_options=None, headers=None):
    '''
    Level-1 products of a STAC catalogue matching an area, a period, a tile and a maximum cloud cover.

    The catalogue is a static catalogue (its ``catalog.json`` or ``collection.json``, local, in a bucket
    or over http(s), e.g. written by :func:`build_catalog`) or a STAC API (URL ``http(s)://`` of the API,
    Item Search ``POST /search``: area, period, collections and cloud cover sent to the server). The
    criteria are applied again to the results, so a server ignoring some of them gives the same
    selection.

    :param source: ``catalog.json`` / ``collection.json`` of a static catalogue, or STAC API URL
    :param bbox: area (lon_min, lat_min, lon_max, lat_max), deg
    :param intersects: area as a shapely geometry or GeoJSON dict (lon/lat), instead of ``bbox``
    :param start: first acquisition date (included)
    :param end: last acquisition date (included)
    :param max_cloud_cover: maximum cloud cover (%); the Items without ``eo:cloud_cover`` are kept
    :param tile: MGRS tile (e.g. ``'31TFJ'``) or WRS-2 path/row (e.g. ``'196030'``), see :func:`item_tile`
    :param collections: collection id or list of ids (e.g. ``'sentinel-2-l1c'``)
    :param limit: maximum number of Items read from a STAC API
    :param storage_options: options of the fsspec file system of a catalogue in a bucket
    :param headers: HTTP headers of the requests to a STAC API or an http(s) catalogue (e.g. token)
    :return: pandas.DataFrame, one row per Item sorted by acquisition time: ``id``, ``collection``,
        ``datetime`` (UTC, without time zone), ``platform``, ``tile``, ``cloud_cover``, ``href`` (product
        folder, see :func:`product_href`, None if not found), ``item`` (the Item, dict, for
        :func:`open_item`)
    '''
    from shapely.geometry import box, mapping, shape

    if isinstance(intersects, dict):
        intersects = shape(intersects)
    area = intersects if intersects is not None else (box(*bbox) if bbox is not None else None)
    start = pd.Timestamp(start) if start is not None else None
    end = pd.Timestamp(end) + pd.Timedelta('1D') - pd.Timedelta('1ms') if end is not None else None
    if start is not None and start.tzinfo is not None:
        start = start.tz_convert(None)
    if end is not None and end.tzinfo is not None:
        end = end.tz_convert(None)
    collections = [collections] if isinstance(collections, str) else collections
    source = str(source).strip()

    if source.endswith('.json') or not re.match(r'https?://', source):
        items = _static_items(source, collections, storage_options, headers)
    else:
        body = {'limit': min(limit, 100)}
        if intersects is not None:
            body['intersects'] = mapping(intersects)
        elif bbox is not None:
            body['bbox'] = list(bbox)
        if start is not None or end is not None:
            body['datetime'] = (f'{start.isoformat() + "Z" if start is not None else ".."}/'
                                f'{end.isoformat() + "Z" if end is not None else ".."}')
        if collections:
            body['collections'] = list(collections)
        if max_cloud_cover is not None:
            body['query'] = {'eo:cloud_cover': {'lte': max_cloud_cover}}
        items = _api_items(source, body, limit, headers=headers)

    rows = []
    for item in items:
        props = item.get('properties', {})
        time = pd.Timestamp(props.get('datetime') or props.get('start_datetime'))
        time = time.tz_convert(None) if time.tzinfo is not None else time
        cloud = props.get('eo:cloud_cover')
        if collections and item.get('collection') and item['collection'] not in collections:
            continue
        if area is not None and not (item.get('bbox') and box(*item['bbox'][:2], *item['bbox'][-2:]).intersects(area)
                                     and (item.get('geometry') is None or shape(item['geometry']).intersects(area))):
            continue
        if (start is not None and time < start) or (end is not None and time > end):
            continue
        if max_cloud_cover is not None and cloud is not None and float(cloud) > max_cloud_cover:
            continue
        if tile and item_tile(item) != str(tile).lstrip('T'):
            continue
        try:
            href = product_href(item)
        except ValueError:
            href = None
        rows.append(dict(id=item['id'], collection=item.get('collection'), datetime=time,
                         platform=props.get('platform'), tile=item_tile(item),
                         cloud_cover=float(cloud) if cloud is not None else None, href=href, item=item))
    found = pd.DataFrame(rows, columns=SEARCH_COLUMNS)
    return found.sort_values('datetime', kind='stable').reset_index(drop=True)


# ---------------------------------------------------------------------------------------------------
# opening the products of the Items
# ---------------------------------------------------------------------------------------------------

def _as_item(item, storage_options=None):
    '''Item as a dict: dict, row of :func:`search`, pystac Item, or location of an Item JSON file.'''
    if isinstance(item, pd.Series):
        item = item['item']
    if hasattr(item, 'to_dict') and not isinstance(item, dict):
        item = item.to_dict()
    if isinstance(item, (str, os.PathLike)):
        location = str(item)
        item = _read_json(location, storage_options)
        if _self_href(item) is None:
            item.setdefault('links', []).append({'rel': 'self', 'href': location})
    if not (isinstance(item, dict) and item.get('type') == 'Feature'):
        raise ValueError('not a STAC Item')
    return item


def _asset_hrefs(item, alternate=None):
    '''Hrefs of the assets of an Item, resolved from its ``self`` link, or their ``alternate`` hrefs.'''
    base = _self_href(item)
    hrefs = {}
    for key, asset in item.get('assets', {}).items():
        href = asset.get('href')
        if alternate and alternate in asset.get('alternate', {}):
            href = asset['alternate'][alternate].get('href', href)
        if href:
            hrefs[key] = _resolve(base, href) if base and not is_url(href) and not os.path.isabs(href) else href
    return hrefs


def product_href(item, alternate=None):
    '''
    Location of the product folder of an Item: its asset ``product`` (Items of :func:`build_catalog`),
    else the ``.SAFE`` folder of its assets (e.g. Copernicus Data Space), else the folder of its metadata
    file (``MTD_MSIL1C.xml``, ``*_MTL.xml``, e.g. USGS).

    :param item: Item (see :func:`open_item`)
    :param alternate: name of the alternate hrefs of the assets to use (e.g. ``'s3'`` for the USGS Items)
    :return: local path or URL
    '''
    item = _as_item(item)
    hrefs = _asset_hrefs(item, alternate)
    if 'product' in hrefs:
        return hrefs['product'].rstrip('/')
    for href in hrefs.values():
        match = re.match(r'(.*?\.SAFE)(/|$)', href)
        if match:
            return match.group(1)
    for href in hrefs.values():
        name = posixpath.basename(href.split('?')[0])
        if name.startswith('MTD_MSIL1C') or re.match(r'L\w+_MTL\.(xml|txt)$', name):
            return posixpath.dirname(href.split('?')[0]) if is_url(href) else os.path.dirname(href)
    raise ValueError(f"no product folder found in the assets of {item.get('id')}")


def open_item(item, storage_options=None, alternate=None, **driver_kwargs):
    '''
    Driver of the product of a STAC Item, opened in place (see :mod:`GRSdriver.remote`).

    The product folder (:func:`product_href`) is listed when it is local or in a bucket; over http(s),
    where a folder cannot be listed, the files of the product are the assets of the Item (all the files
    used by the driver must then be assets).

    :param item: Item: dict, row of :func:`search`, ``pystac.Item``, or location of an Item JSON file
    :param storage_options: options of the fsspec file system of the product (e.g. S3 keys and endpoint)
    :param alternate: name of the alternate hrefs of the assets to use (e.g. ``'s3'``)
    :param driver_kwargs: arguments of the driver (``resolution``, ``band_idx``, ``subset``...)
    :return: :class:`~GRSdriver.Sentinel2Driver` or :class:`~GRSdriver.LandsatDriver` (call its
        ``load_product``)
    '''
    from .driver_S2_SAFE import Sentinel2Driver
    from .driver_landsat_col2 import LandsatDriver

    item = _as_item(item, storage_options)
    root = product_href(item, alternate)
    if re.match(r'https?://', root):
        files = ProductFiles(root, storage_options, hrefs=list(_asset_hrefs(item, alternate).values()))
    else:
        files = ProductFiles(root, storage_options)
    sensor = sensor_of(files.name)
    if sensor is None:
        constellation = str(item.get('properties', {}).get('constellation', '')).lower()
        sensor = 'S2' if 'sentinel-2' in constellation else 'L' if 'landsat' in constellation else None
    if sensor is None:
        raise ValueError(f"unknown sensor of {item.get('id')} ({root})")
    driver = Sentinel2Driver if sensor == 'S2' else LandsatDriver
    return driver(files, **driver_kwargs)
