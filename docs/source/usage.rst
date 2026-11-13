Usage
=====

Installation
------------

GRSdriver needs Python 3.9 to 3.13:

.. code-block:: bash

    pip install GRSdriver

No separate GDAL installation is needed: rasterio and geopandas ship with their own GDAL
(including the JPEG2000 driver for Sentinel-2). Optional extras:

- ``cli``: the ``grs_driver`` command line (RGB quicklooks): ``pip install "GRSdriver[cli]"``
- ``viz``: the interactive visualization tools (``GRSdriver.visual``): ``pip install "GRSdriver[viz]"``
- ``tutorials``: to run the tutorial notebooks: ``pip install "GRSdriver[tutorials]"``
- ``remote``: products in S3 buckets and STAC catalogues (:mod:`GRSdriver.remote`,
  :mod:`GRSdriver.stac`): ``pip install "GRSdriver[remote]"``

Installation from the repository
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To run the tutorials or work on the code:

.. code-block:: bash

    git clone https://github.com/Tristanovsk/GRSdriver.git
    cd GRSdriver
    pip install -e ".[cli,viz,tutorials,dev]"

or with conda:

.. code-block:: bash

    conda env create -f environment.yml
    conda activate grsdriver


Quick start
-----------

.. code-block:: python

    from GRSdriver import Sentinel2Driver, LandsatDriver

    # Sentinel-2: 20 m bands, viewing angles computed on a 60 m grid
    l1c = Sentinel2Driver('S2B_MSIL1C_..._.SAFE', resolution=20)
    l1c.load_product()
    prod = l1c.prod          # bands, vza, raa, sza, SRF, wl_true + metadata

    # Landsat 8/9
    l1 = LandsatDriver('LC09_L1TP_..._02_T1', resolution=30)
    l1.load_product()

The bands are read by 4 threads in parallel: set ``n_workers`` (e.g. ``n_workers=1``) to trade
speed for memory. For a full Sentinel-2 tile at 10 m, ``Sentinel2Driver(..., lazy_geom=True)``
keeps the per-band viewing angles lazy and saves several GB of memory (see :doc:`methods`). Set
``GRSDRIVER_USE_DASK=1`` before importing GRSdriver to get a fully lazy (dask-backed) product.

Command line
~~~~~~~~~~~~

``grs_driver`` writes an RGB quicklook (PNG) of a Sentinel-2 or Landsat product:

.. code-block:: bash

    grs_driver S2B_MSIL1C_..._.SAFE --odir ./quicklooks --resolution 60

Run ``grs_driver --help`` for all the options.

Products in an S3 bucket
~~~~~~~~~~~~~~~~~~~~~~~~

The drivers take the URL of a product in a bucket as well as a local path (``remote`` extra). The
product is read in place, nothing is downloaded: its folder is listed once, the metadata files are read
through `fsspec <https://filesystem-spec.readthedocs.io>`_, and only the parts of the rasters needed
for the output grid are read by GDAL (``/vsis3/``), so a subset reads a small part of the files. The
credentials and the endpoint are those of fsspec/s3fs: the environment (``AWS_PROFILE``,
``~/.aws/config`` with its ``endpoint_url``, ``~/.aws/credentials``) or ``storage_options``:

.. code-block:: python

    import os
    os.environ['AWS_PROFILE'] = 'grstbx-local'       # local bucket of grstbx (grstbx-s3-bucket)

    l1c = Sentinel2Driver('s3://grstbx-s3/sentinel-2/l1c/31TFJ/2023/06/11/'
                          'S2A_MSIL1C_20230611T103631_N0509_R008_T31TFJ_20230611T155912.SAFE',
                          resolution=20, subset=roi)   # roi: GeoSeries of the region of interest
    l1c.load_product()

    # any S3 service, with explicit options
    so = {'key': '...', 'secret': '...', 'endpoint_url': 'https://eodata.dataspace.copernicus.eu'}
    l1c = Sentinel2Driver('s3://eodata/Sentinel-2/MSI/L1C/.../S2A_MSIL1C_..._.SAFE', storage_options=so)

The options are passed to GDAL as configuration options of the whole process (see
:func:`GRSdriver.remote.apply_gdal_options`): read the products of one endpoint and set of credentials
at a time. The lazy mode (``GRSDRIVER_USE_DASK=1``) works the same way.

STAC catalogues
~~~~~~~~~~~~~~~

:mod:`GRSdriver.stac` writes a static STAC catalogue of the Level-1 products of folders
(:func:`~GRSdriver.stac.build_catalog`, collections ``sentinel-2-l1c`` and ``landsat-c2-l1``, from
the metadata files only), searches a static catalogue or a STAC API by area, period, cloud cover and
tile (:func:`~GRSdriver.stac.search`), and opens the product of an Item with the right driver
(:func:`~GRSdriver.stac.open_item`). The catalogue has the layout of those of
`grstbx <https://github.com/Tristanovsk/grstbx>`__ (``catalog.json``, one folder per collection with
``collection.json``, ``items.json`` and one folder per Item), next to its L2A and L2B catalogues:

.. code-block:: python

    from GRSdriver import stac

    # local folders scanned (fast), products described with their URLs in the bucket;
    # a list of bucket URLs scans the bucket instead
    counts, skipped = stac.build_catalog(
        {'/data/satellite/Sentinel-2/L1C': 's3://grstbx-s3/sentinel-2/l1c'}, 's3://grstbx-s3/stac-l1')

    found = stac.search('s3://grstbx-s3/stac-l1/catalog.json', bbox=(5.03, 43.40, 5.24, 43.56),
                        start='2023-06-01', end='2023-06-30', max_cloud_cover=20)
    found[['id', 'datetime', 'cloud_cover', 'href']]

    l1c = stac.open_item(found.iloc[0], resolution=20, subset=roi)
    l1c.load_product()

The Items of other catalogues are opened when their assets give the product folder: a ``.SAFE``
folder (e.g. Copernicus Data Space) or the folder of the metadata file ``*_MTL.xml`` (e.g. USGS, with
``alternate='s3'`` and ``storage_options={'requester_pays': True}`` for its requester-pays bucket).

Tutorials
---------

The tutorials are Jupyter notebooks of the ``notebook/`` folder of the repository; the paths to the
images are those of the author's machine: set them to your own data. To rerun them for this
documentation, see :doc:`contributing`.
