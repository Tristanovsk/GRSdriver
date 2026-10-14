Updating the tutorials
======================

The tutorials of this documentation are Jupyter notebooks. They need satellite images that are
not available on Read the Docs, so they are **executed locally** and Read the Docs only displays
the stored outputs.

Where the notebooks live
------------------------

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Location
     - Role
   * - ``notebook/``
     - Working copies, edited and run in JupyterLab.
   * - ``docs/source/examples/``
     - Copies published in the documentation (listed in ``examples/*.rst``).
   * - ``docs/build/.jupyter_cache/``
     - Execution cache of `myst-nb <https://myst-nb.readthedocs.io>`_, committed to git. Read the
       Docs takes the outputs of the notebooks from it (``nb_execution_mode = 'cache'`` in
       ``conf.py``).

The cache is keyed on the code of the notebook: a notebook whose code cells changed is not found
in the cache. On Read the Docs it is then executed with a 60 s timeout, fails for lack of data and
is displayed with errors. **Any change to the code of a published notebook must therefore be
followed by a local execution and a commit of the cache.**

Data used by the tutorials
--------------------------

The paths are those of the author's machine; set them to your own copy of the products.

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Notebook
     - Input data
   * - ``GRSdriver_basics``
     - one Sentinel-2 L1C ``.SAFE`` (T49QDB, 2023-07-11)
   * - ``GRSdriver_subsetting``
     - Sentinel-2 L1C ``.SAFE`` time series of tile T30PYT (2021) and the subsets written by
       the notebook
   * - ``GRSdriver_landsat9_TIR``
     - one Landsat 9 Collection-2 L1 product (path/row 196/030, 2022-11-20)
   * - ``GRSdriver_landsat9_L1_CAMS``
     - the same Landsat 9 product and a CAMS global forecast file (``cams_forecast_2022-11.nc``)
   * - ``sentinel2_download``
     - a Copernicus Data Space account (downloads the images)

Rerunning a tutorial
--------------------

In the environment of GRSdriver (with ``jupyter``, ``cartopy``, ``holoviews``, ``memory_profiler``
and the documentation requirements ``pip install -r docs/requirements.txt``):

1. Edit and run the notebook in ``notebook/``, or execute it from the command line:

   .. code-block:: bash

      jupyter nbconvert --to notebook --execute --inplace notebook/GRSdriver_basics.ipynb

2. Copy it to the documentation:

   .. code-block:: bash

      cp notebook/GRSdriver_basics.ipynb docs/source/examples/

3. Store its outputs in the cache, without executing it again:

   .. code-block:: bash

      cd docs/build
      jcache cache add ../source/examples/GRSdriver_basics.ipynb

   Alternatively, ``make html`` in ``docs/`` executes the notebooks missing from the cache and
   adds them (slower: the notebooks run again).

4. Build the documentation and check the page of the tutorial:

   .. code-block:: bash

      cd docs
      make html

5. Commit the notebook and the cache:

   .. code-block:: bash

      git add notebook/GRSdriver_basics.ipynb docs/source/examples/GRSdriver_basics.ipynb docs/build/.jupyter_cache
      git commit -m "docs: rerun GRSdriver_basics"

Figures of the Methods page
---------------------------

The figures of the Sentinel-2 geometry (``docs/source/_static/s2_*.png``) are made by a script,
from one L1C product and a zoom box on the sea (lon/lat):

.. code-block:: bash

   python docs/figures/make_geometry_figures.py \
       S2B_MSIL1C_20230711T030529_N0509_R075_T49QDB_20230711T054244.SAFE \
       docs/source/_static 110.62,19.15,110.92,19.45

Adding a tutorial
-----------------

Copy the executed notebook to ``docs/source/examples/``, add its name to the ``toctree`` of the
matching ``docs/source/examples/*.rst`` page (or create a page and list it in ``index.rst``), then
follow steps 3 to 5 above.

Interactive widgets (holoviews, panel) need a running Python kernel: they are not displayed in the
static documentation.
