Tutorials
=========

Jupyter notebooks showing how to load and use Sentinel-2 and Landsat 8/9 Level-1 products with
GRSdriver. Each tutorial starts with what you will learn and the data it needs; the paths of the
images are those of the author's machine, set them to your own products.

The notebooks are in the ``docs/source/tutorials`` directory of the
`repository <https://github.com/Tristanovsk/GRSdriver>`_: download them to run them on your data.

.. list-table::
   :header-rows: 1
   :widths: 30 45 25

   * - Tutorial
     - Content
     - Data
   * - :doc:`GRSdriver_basics`
     - Load a Sentinel-2 L1C product: bands, per-band viewing geometry, metadata, spectral
       responses; example of water mask
     - one Sentinel-2 L1C product
   * - :doc:`GRSdriver_subsetting`
     - Load a region of interest, save it into netCDF, build a time series and a datacube
     - a year of Sentinel-2 L1C products of one tile
   * - :doc:`GRSdriver_landsat9_TIR`
     - Load the reflective (OLI) and thermal (TIRS) bands of Landsat 8/9 on a common grid
     - one Landsat 8/9 Collection 2 L1 product
   * - :doc:`GRSdriver_landsat9_L1_CAMS`
     - Decode the Landsat quality flags; colocate the CAMS atmospheric data with an image
     - one Landsat 8/9 product and a CAMS forecast file
   * - :doc:`sentinel2_download`
     - Search the Copernicus Data Space catalogue and download Sentinel-2 L1C products
     - a Copernicus Data Space account (download only)

.. toctree::
   :maxdepth: 1
   :caption: Sentinel-2

   GRSdriver_basics
   GRSdriver_subsetting

.. toctree::
   :maxdepth: 1
   :caption: Landsat 8/9

   GRSdriver_landsat9_TIR
   GRSdriver_landsat9_L1_CAMS

.. toctree::
   :maxdepth: 1
   :caption: Data access

   sentinel2_download
