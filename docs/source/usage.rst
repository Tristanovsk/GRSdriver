Usage
=====

Installation
------------

These instructions will get you a copy of the project up and running on
your local machine for development and testing purposes. See deployment
for notes on how to deploy the project on a live system.

.. code-block:: bash

    pip install GRSdriver


No separate GDAL installation is needed: rasterio and geopandas ship with their own GDAL
(including the JPEG2000 driver for Sentinel-2). The ``grs_driver`` command line (RGB quicklooks)
needs matplotlib and cartopy:

.. code-block:: bash

    pip install "GRSdriver[cli]"


Installation from GRSdriver repository (enables use of the notebook and visualization tools)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
1. First clone the repository:

.. code-block:: bash

    git clone https://github.com/Tristanovsk/GRSdriver.git


2. You may duplicate the conda environment (optional)

.. code-block:: bash

    conda env create -f environment.yml


3. Install GRSdriver

.. code-block:: bash

    conda activate grssuite

    conda install -c pyviz holoviews panel

    pip install .


4. Install and configure JupyterLab and Holoviews

.. code-block:: bash

    pip install holoviews datashader cartopy

    conda install -c conda-forge jupyterlab




You are done.


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
