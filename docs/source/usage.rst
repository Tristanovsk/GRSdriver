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

Tutorials
---------

The tutorials are Jupyter notebooks of the ``notebook/`` folder of the repository; the paths to the
images are those of the author's machine: set them to your own data. To rerun them for this
documentation, see :doc:`contributing`.
