Processing Chain Description
=============================

This page documents GRSdriver following the
`Processing Chain Documentation Template <https://processing-chain-guidelines.readthedocs.io/en/latest/Data_processing_chain_template/>`_.

Process description
--------------------

Description
~~~~~~~~~~~

GRSdriver is the input stage of the GRS processor (Glint Removal for Sentinel-2-like sensors).
It reads one Level-1 (top-of-atmosphere) product and returns it as a single ``xarray.Dataset``
ready for the atmospheric and sunglint correction:

- top-of-atmosphere reflectance of the selected bands, resampled to one common grid;
- sun and viewing geometry. For Sentinel-2, the viewing angles are computed per band and
  per detector from the granule metadata (see :doc:`methods`);
- spectral response function and central wavelength of each band;
- product metadata (acquisition date, tile, solar irradiance...) and, for Landsat, the L1 quality
  bitmask.

GRSdriver is mainly a Python library. It has two entry points:

- :py:class:`GRSdriver.Sentinel2Driver` and :py:class:`GRSdriver.LandsatDriver`
  (``load_product()`` fills the ``prod`` attribute), called by the GRS processor or by the user;
- the ``grs_driver`` command-line executable (entry point ``GRSdriver.run:main``, see
  :py:mod:`GRSdriver.run`), which writes an RGB quicklook (PNG) of a product.

The bands are read with `EOReader <https://eoreader.readthedocs.io>`_.

Application Domain (Granule)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

One run (one granule) corresponds to **one Level-1 product for one acquisition date and one
tile/footprint**:

- one Sentinel-2 A/B/C ``MSIL1C`` ``.SAFE`` product, or
- one Landsat-8/9 Collection-2 Level-1 (``L1TP``/``L1GT``) product.

The output covers the footprint of the input tile, or the bounding box of the optional
``subset``, at the requested ``resolution``.

Scheduling and Triggers
~~~~~~~~~~~~~~~~~~~~~~~~

GRSdriver has no scheduler and no periodicity of its own. It is triggered granule by granule:

- **By the GRS processor**: each GRS run calls GRSdriver to load its input product, so GRSdriver
  is scheduled with GRS (see the
  `GRS documentation <https://github.com/CNES/GRSprocessor>`_).
- **Interactively**: from Python or a notebook (see the tutorials and :doc:`usage`).
- **Command line**: ``grs_driver <input_file> ...``, one call per product.

Dataflow
--------

.. mermaid:: _diagrams/dataflow.mmd

Inputs
------

.. list-table::
   :header-rows: 1
   :widths: 20 15 65

   * - Data Type Name
     - Cardinality
     - Selection Criteria
   * - Level-1 product (``imageSAFE`` / ``image_path`` / ``<input_file>``)
     - 1..1 (mandatory)
     - One Sentinel-2 ``MSIL1C`` ``.SAFE`` directory (processing baselines below and above 4.0
       are supported), or one Landsat-8/9 Collection-2 L1 product directory.
   * - Spatial subset (``subset``)
     - 0..1 (optional)
     - ``geopandas.GeoSeries`` in any CRS (its bounding box is used), or a sequence whose first
       element is passed as ``window`` to EOReader. Python API only.

Outputs
-------

.. list-table::
   :header-rows: 1
   :widths: 30 15 55

   * - Data Type Name
     - Cardinality
     - Description
   * - L1 product (``prod``)
     - 1..1
     - In-memory ``xarray.Dataset`` with the variables ``bands`` (wl, y, x), ``sza``, ``vza``,
       ``raa``, ``SRF``, ``wl_true`` (and ``flags_l1`` for Landsat), coordinates ``wl``, ``x``,
       ``y``, ``time`` and the product metadata in ``attrs`` (see `Output product format`_).
       It is not written to disk by GRSdriver.
   * - RGB quicklook (PNG)
     - 0..1
     - Written by the ``grs_driver`` command line only, at ``<odir>/<ofile>``.
   * - EOReader temporary files
     - 1..1
     - Cleaned bands cached as GeoTIFF by EOReader in a temporary directory. The directory is
       removed when the program exits (``remove_tmp=True``).

Output product format
~~~~~~~~~~~~~~~~~~~~~

``prod`` is an ``xarray.Dataset`` in the CRS of the product (UTM), georeferenced with
``rioxarray``:

.. list-table::
   :header-rows: 1
   :widths: 20 20 60

   * - Variable
     - Dimensions
     - Description
   * - ``bands``
     - wl, y, x
     - TOA reflectance (float32). Landsat TIR bands: brightness temperature.
   * - ``vza``
     - wl, y, x (Sentinel-2); y, x (Landsat)
     - Viewing zenith angle (deg, float32).
   * - ``raa``
     - wl, y, x (Sentinel-2); y, x (Landsat)
     - Relative azimuth (deg, float32).
   * - ``sza``
     - y, x
     - Solar zenith angle (deg, float32).
   * - ``flags_l1``
     - y, x
     - Landsat only: L1 quality bitmask (``QA_PIXEL``, uint32).
   * - ``SRF``
     - wl, wl_hr
     - Spectral response function of each band.
   * - ``wl_true``
     - wl
     - Central wavelength computed from the SRF (nm).

The arrays are numpy arrays by default. They are dask arrays (lazy) when
``EOREADER_USE_DASK=1`` is set before importing GRSdriver. With ``lazy_geom=True``
(Sentinel-2), only ``vza`` and ``raa`` are lazy. The product can be saved by the user with the
xarray writers (``prod.to_netcdf``, ``prod.to_zarr``).

Return Codes
------------

The Python API reports errors by raising exceptions (missing metadata file, product not
recognized by EOReader...). The ``grs_driver`` command line (``docopt``-based, see
:py:func:`GRSdriver.run.main`) behaves as follows:

- ``0``: normal exit. This includes the case where the output file already exists and
  ``--no_clobber`` is set: the product is skipped with a message on the standard output.
- ``1``: an uncaught exception was raised (Python traceback on the standard error).
- Invalid command-line arguments are rejected by ``docopt``, which prints the usage and exits
  with a non-zero code.

Log Format
----------

GRSdriver writes no log file. At import, the level of the root ``logging`` logger is set to
``INFO``. Messages are emitted with the standard ``logging`` module (command line) and
``print`` (progress with ``verbose=True``, ODR fitting reports of the viewing angles). EOReader
logs through its own ``eoreader`` logger. The calling application (e.g. GRS) configures the
handlers and the format of the records.

Required Resources
-------------------

Measured for one full Sentinel-2 tile (T28PFV, 13 bands, ``resolution=20``,
``resolution_angle=60``, numpy mode, EOReader 0.23, GRSdriver 1.1.0) on a shared 40-core node.
The resources scale with the number of pixels: about 4 x more at 10 m, about 9 x less at 60 m.

.. list-table::
   :header-rows: 1
   :widths: 30 30 40

   * - Resource Type
     - Quantity
     - Source / notes
   * - CPU
     - multi-threaded: ~8 min of CPU time for ~2.5 min of wall time
     - JP2 decoding by GDAL uses several threads. ``load_bands`` takes ~75 % of the time
       (EOReader reading, nodata masking, 10 m -> 20 m resampling).
   * - RAM
     - peak ~7.5 GB; ~4.5 GB with ``lazy_geom=True``
     - final ``prod``: 4.8 GB (``bands``, ``vza``, ``raa``: 1.57 GB each). At 10 m,
       ``vza`` + ``raa`` take 12.5 GB: use ``lazy_geom=True`` (see :doc:`methods`).
   * - Execution time
     - ~2.5 min per full tile at 20 m
     - ``__init__`` 10 s, ``load_bands`` 1.8 min, geometry 20 s.
   * - Disk — input
     - one L1 product: ~0.4–0.8 GB (Sentinel-2 SAFE), ~1 GB (Landsat L1)
     - read only
   * - Disk — temporary
     - EOReader cache of the cleaned bands, about the size of ``bands``
     - removed at exit
   * - Disk — output
     - none (Python API); one PNG (command line)
     - the user saves ``prod`` if needed

Data Types
----------

.. list-table::
   :header-rows: 1
   :widths: 18 32 15 35

   * - Data Name
     - Description
     - Granule
     - Nomenclature
   * - Sentinel-2 L1C product
     - Sentinel-2 MSI top-of-atmosphere reflectance
     - one tile, one date
     - ``S2{A,B,C}_MSIL1C_<datetime>_N<baseline>_R<orbit>_T<tile>_<datetime>.SAFE``
   * - Landsat L1 product
     - Landsat-8/9 OLI/TIRS Collection-2 Level-1 product
     - one path/row, one date
     - ``LC0{8,9}_L1{TP,GT}_<path><row>_<acq. date>_<proc. date>_02_T{1,2}``
   * - L1 product (``prod``)
     - ``xarray.Dataset`` passed to GRS
     - one tile, one date (or subset)
     - in memory, no file name
   * - RGB quicklook
     - PNG image from the ``grs_driver`` command line
     - one tile, one date
     - ``<odir>/<ofile>``; by default ``<ofile>`` is the input basename without ``.SAFE``,
       ``.png`` is added when ``<ofile>`` has no extension
