'''
Access to the files of a Level-1 product, in a local folder or in a bucket (``s3://``, ``gs://``,
``https://``...).

A product is opened in place, nothing is downloaded: the metadata files are read through
`fsspec <https://filesystem-spec.readthedocs.io>`_ and the rasters by GDAL through its virtual file
systems (``/vsis3/``, ``/vsigs/``, ``/vsicurl/``), only the parts of the files needed being read.
The access to a bucket needs the optional dependencies of the ``remote`` extra
(``pip install "GRSdriver[remote]"``).

The credentials and the endpoint of an S3 bucket are those of fsspec/s3fs (``storage_options``, or
else the environment: ``AWS_PROFILE``, ``~/.aws/config``, ``~/.aws/credentials``), passed to GDAL
as configuration options (see :func:`gdal_options`), so that both read the same bucket. Example
with the local bucket of grstbx (``grstbx-s3-bucket``)::

    import os
    os.environ['AWS_PROFILE'] = 'grstbx-local'

    from GRSdriver import Sentinel2Driver
    l1c = Sentinel2Driver('s3://grstbx-s3/sentinel-2/l1c/31TFJ/2023/06/14/S2A_MSIL1C_..._.SAFE')

or with explicit options (any bucket, e.g. the ``eodata`` bucket of the Copernicus Data Space)::

    so = {'key': '...', 'secret': '...', 'endpoint_url': 'https://eodata.dataspace.copernicus.eu'}
    l1c = Sentinel2Driver('s3://eodata/Sentinel-2/MSI/L1C/2023/06/14/S2A_MSIL1C_..._.SAFE',
                          storage_options=so)
'''

import configparser
import contextlib
import fnmatch
import os
import posixpath
import threading
import urllib.parse

import rasterio
from rasterio.env import set_gdal_config

INSTALL_HINT = 'pip install "GRSdriver[remote]"'

# GDAL virtual file systems of the URL schemes
VSI_PREFIX = {'s3': '/vsis3/', 'gs': '/vsigs/', 'gcs': '/vsigs/',
              'http': '/vsicurl/http://', 'https': '/vsicurl/https://'}

# GDAL options for all the remote files: retries of the failed requests. Not
# GDAL_DISABLE_READDIR_ON_OPEN: with it, the JPEG2000 tiles of Sentinel-2 read from /vsis3/ decode
# as zeros (GDAL 3.8, OpenJPEG)
GDAL_REMOTE_OPTIONS = {'GDAL_HTTP_MAX_RETRY': '4',
                       'GDAL_HTTP_RETRY_DELAY': '1'}


def is_url(path):
    '''True if ``path`` is a URL (``s3://``, ``https://``...), read through fsspec and GDAL.'''
    return '://' in str(path)


def get_fs(url, storage_options=None):
    '''
    fsspec file system of a URL, and the path of the URL in it.

    :param url: URL (``s3://bucket/key``...)
    :param storage_options: options of the file system (e.g. ``key``, ``secret``, ``endpoint_url``,
        ``profile``, ``anon`` for s3fs)
    :return: (file system, path)
    '''
    try:
        import fsspec
    except ImportError as exc:
        raise ImportError(f'fsspec is needed to read {url}: {INSTALL_HINT}') from exc
    return fsspec.core.url_to_fs(str(url), **(storage_options or {}))


def _aws_profile_config(profile):
    '''Options of an AWS profile in the AWS config file (``AWS_CONFIG_FILE`` or ``~/.aws/config``).'''
    path = os.path.expanduser(os.getenv('AWS_CONFIG_FILE', '~/.aws/config'))
    parser = configparser.ConfigParser()
    try:
        parser.read(path)
    except configparser.Error:
        return {}
    section = 'default' if profile == 'default' else f'profile {profile}'
    return dict(parser[section]) if parser.has_section(section) else {}


def gdal_options(url, storage_options=None):
    '''
    GDAL configuration options to read the rasters of a URL as fsspec does with ``storage_options``.

    For ``s3://``: the endpoint (``endpoint_url`` of the options or of their ``client_kwargs``, else
    ``AWS_ENDPOINT_URL_S3`` / ``AWS_ENDPOINT_URL``, else ``endpoint_url`` of the AWS profile), the
    profile, the keys (``key``, ``secret``, ``token``), the anonymous access (``anon``), the region and
    the requester-pays buckets (``requester_pays``). A custom endpoint (MinIO, rclone, Copernicus Data
    Space...) is addressed in path style.

    :param url: URL of a file or folder
    :param storage_options: options of the fsspec file system
    :return: dict of GDAL configuration options (empty for a local path)
    '''
    if not is_url(url):
        return {}
    scheme = urllib.parse.urlsplit(str(url)).scheme.lower()
    options = dict(GDAL_REMOTE_OPTIONS)
    if scheme not in ('s3', 's3a'):
        return options
    so = dict(storage_options or {})
    client_kwargs = so.get('client_kwargs') or {}
    profile = so.get('profile') or os.getenv('AWS_PROFILE') or os.getenv('AWS_DEFAULT_PROFILE') or 'default'
    config = _aws_profile_config(profile)

    if so.get('profile'):
        options['AWS_PROFILE'] = so['profile']
    if so.get('anon'):
        options['AWS_NO_SIGN_REQUEST'] = 'YES'
    for key, option in (('key', 'AWS_ACCESS_KEY_ID'), ('secret', 'AWS_SECRET_ACCESS_KEY'),
                        ('token', 'AWS_SESSION_TOKEN')):
        if so.get(key):
            options[option] = so[key]
    if so.get('requester_pays'):
        options['AWS_REQUEST_PAYER'] = 'requester'
    region = client_kwargs.get('region_name') or os.getenv('AWS_REGION') or os.getenv('AWS_DEFAULT_REGION') \
        or config.get('region')
    if region:
        options['AWS_REGION'] = region

    endpoint = (so.get('endpoint_url') or client_kwargs.get('endpoint_url') or os.getenv('AWS_ENDPOINT_URL_S3')
                or os.getenv('AWS_ENDPOINT_URL') or config.get('endpoint_url'))
    if endpoint:
        parts = urllib.parse.urlsplit(endpoint if '://' in endpoint else 'https://' + endpoint)
        options['AWS_S3_ENDPOINT'] = parts.netloc + parts.path.rstrip('/')
        options['AWS_HTTPS'] = 'NO' if parts.scheme == 'http' else 'YES'
        options['AWS_VIRTUAL_HOSTING'] = 'FALSE'
    return options


def gdal_path(path):
    '''
    Path of a file for GDAL: local paths unchanged, URLs as GDAL virtual file system paths
    (``s3://bucket/key`` -> ``/vsis3/bucket/key``).
    '''
    path = str(path)
    if not is_url(path):
        return path
    scheme, rest = path.split('://', 1)
    scheme = scheme.lower()
    if scheme == 's3a':
        scheme = 's3'
    if scheme not in VSI_PREFIX:
        raise ValueError(f'URL scheme {scheme}:// not readable by GDAL: {path}')
    return VSI_PREFIX[scheme] + rest


_GDAL_LOCK = threading.Lock()
_GDAL_APPLIED = {}


def apply_gdal_options(env):
    '''
    Set GDAL configuration options for the whole process (see :func:`gdal_options`).

    The options are global rather than set in a ``rasterio.Env``: the options of a ``rasterio.Env`` are
    local to its thread, and are not seen by the threads of GDAL itself (e.g. the multi-threaded
    decoding of the JPEG2000 tiles, which then reads the files from the wrong endpoint), nor by
    the dask workers of the lazy products. As a consequence, the products of a single endpoint and
    set of credentials are read at a time (the last options set are used).

    :param env: GDAL configuration options (dict)
    '''
    with _GDAL_LOCK:
        for key, value in (env or {}).items():
            if _GDAL_APPLIED.get(key) != value:
                set_gdal_config(key, value)
                _GDAL_APPLIED[key] = value


@contextlib.contextmanager
def open_raster(path, env=None):
    '''
    Open a raster with rasterio, local or remote (see :func:`gdal_path`), with the GDAL
    configuration ``env`` (see :func:`gdal_options` and :func:`apply_gdal_options`).

    :param path: local path or URL
    :param env: GDAL configuration options (dict)
    '''
    if env:
        apply_gdal_options(env)
    with rasterio.open(gdal_path(path)) as src:
        yield src


def _match(relpath, pattern):
    '''Glob matching path segment by path segment (``*`` does not match ``/``), as ``glob.glob``.'''
    parts, pats = relpath.split('/'), pattern.split('/')
    return len(parts) == len(pats) and all(fnmatch.fnmatchcase(p, q) for p, q in zip(parts, pats))


class ProductFiles:
    '''
    Files of a Level-1 product (folder), local or in a bucket, listed once.

    The folder is listed recursively when it is opened (one request for a bucket). A folder that cannot
    be listed (``https://``) can be described by the list of its files ``hrefs``, e.g. the assets of a
    STAC Item (see :func:`GRSdriver.stac.open_item`).

    :param root: product folder: local path or URL (``s3://bucket/.../S2A_MSIL1C_..._.SAFE``)
    :param storage_options: options of the fsspec file system of a URL
    :param hrefs: files of the product (paths or URLs) instead of the listing of ``root``

    :ivar root: absolute local path or URL of the folder, without trailing ``/``
    :ivar files: dict {path relative to ``root`` (``/`` separated): local path or URL}
    :ivar env: GDAL configuration options to read the rasters (:func:`gdal_options`)
    '''

    def __init__(self, root, storage_options=None, hrefs=None):
        root = str(root)
        self.remote = is_url(root)
        self.root = root.rstrip('/') if self.remote else os.path.abspath(root)
        self.storage_options = storage_options
        self.env = gdal_options(self.root, storage_options)
        self.files = self._index(hrefs) if hrefs is not None else self._list()
        if not self.files:
            raise FileNotFoundError(f'No product files in {self.root}')

    @property
    def name(self):
        '''Name of the product folder (e.g. ``S2A_MSIL1C_..._.SAFE``).'''
        return posixpath.basename(self.root) if self.remote else os.path.basename(self.root)

    def _relative(self, href):
        href = str(href)
        sep = '/' if self.remote else os.sep
        if href.startswith(self.root + sep):
            return href[len(self.root) + 1:].replace(os.sep, '/')
        return posixpath.basename(href.replace(os.sep, '/'))

    def _index(self, hrefs):
        return {self._relative(href): str(href) for href in hrefs}

    def _list(self):
        if not self.remote:
            if not os.path.isdir(self.root):
                raise FileNotFoundError(f'No product folder {self.root}')
            files = {}
            for folder, _, names in os.walk(self.root, followlinks=True):
                for name in names:
                    path = os.path.join(folder, name)
                    files[os.path.relpath(path, self.root).replace(os.sep, '/')] = path
            return files
        fs, path = get_fs(self.root, self.storage_options)
        path = path.rstrip('/')
        try:
            found = fs.find(path)
        except (NotImplementedError, OSError) as exc:
            raise FileNotFoundError(f'Cannot list {self.root} ({exc}); describe the product by its files '
                                    '(hrefs), e.g. with GRSdriver.stac.open_item') from exc
        return {p[len(path) + 1:]: fs.unstrip_protocol(p) for p in found if p.startswith(path + '/')}

    def find(self, pattern):
        '''
        Files matching a glob pattern relative to the product folder (e.g. ``GRANULE/*/MTD_TL.xml``).

        :return: sorted list of local paths or URLs
        '''
        return sorted(href for rel, href in self.files.items() if _match(rel, pattern))

    def get(self, pattern):
        '''First file matching ``pattern`` (see :meth:`find`); ``FileNotFoundError`` if there is none.'''
        found = self.find(pattern)
        if not found:
            raise FileNotFoundError(f'No {pattern} file in {self.root}')
        return found[0]

    def read_bytes(self, path):
        '''Content of a file of the product (local path or URL).'''
        if not is_url(path):
            with open(path, 'rb') as f:
                return f.read()
        fs, fpath = get_fs(path, self.storage_options)
        return fs.cat_file(fpath)

    def read_text(self, path):
        '''Text content of a file of the product.'''
        return self.read_bytes(path).decode('utf-8')

    def open_raster(self, path):
        '''Open a raster of the product with rasterio (context manager, see :func:`open_raster`).'''
        return open_raster(path, self.env)

    def __repr__(self):
        return f'ProductFiles({self.root!r}, {len(self.files)} files)'


def product_files(path, storage_options=None):
    '''
    :class:`ProductFiles` of ``path``: a :class:`ProductFiles` (returned as is), a local folder or a URL.
    '''
    if isinstance(path, ProductFiles):
        return path
    return ProductFiles(os.fspath(path) if not is_url(path) else str(path), storage_options)
