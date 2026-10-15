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
   * - ``docs/source/tutorials/``
     - The published tutorials, edited and executed in place, listed in
       ``docs/source/tutorials/index.rst``.
   * - ``docs/build/.jupyter_cache/``
     - Execution cache of `myst-nb <https://myst-nb.readthedocs.io>`_, committed to git. Read the
       Docs takes the outputs of the notebooks from it (``nb_execution_mode = 'cache'`` in
       ``conf.py``).
   * - ``notebook/``
     - Working notebooks (development, tests), not published.

The cache is keyed on the code of the notebook: a notebook whose code cells changed is not found
in the cache. On Read the Docs it is then executed with a 60 s timeout, fails for lack of data and
is displayed with errors. **Any change to the code of a tutorial must therefore be followed by a
local execution and a commit of the cache.** Changes to the markdown cells only do not need it.

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
     - the Sentinel-2 L1C ``.SAFE`` of tile T31TFJ for 2022 (one per month is used); the subsets
       are written in a temporary directory
   * - ``GRSdriver_landsat9_TIR``
     - one Landsat 9 Collection-2 L1 product (path/row 196/030, 2022-11-20)
   * - ``GRSdriver_landsat9_L1_CAMS``
     - the same Landsat 9 product and a CAMS global forecast file (``cams_forecast_2022-11.nc``)
   * - ``sentinel2_download``
     - an internet connection (catalogue search); the download itself is disabled
       (``download = False``) and needs a Copernicus Data Space account

Rerunning a tutorial
--------------------

In the environment of GRSdriver, with ``jupyter``, ``cartopy`` and the documentation requirements
(``pip install -r docs/requirements.txt``):

1. Edit and run the notebook in JupyterLab, or execute it from the command line:

   .. code-block:: bash

      jupyter nbconvert --to notebook --execute --inplace docs/source/tutorials/GRSdriver_basics.ipynb

2. Store its outputs in the cache, without executing it again (``--no-validate``: the empty cells
   have no execution count):

   .. code-block:: bash

      cd docs/build
      jcache cache add --no-validate ../source/tutorials/GRSdriver_basics.ipynb

3. Remove the record of the previous version, to keep the cache small (``jcache cache list``
   shows the records, the most recent first):

   .. code-block:: bash

      jcache cache list
      jcache cache remove <ID of the previous record>

   Alternatively, ``make html`` in ``docs/`` executes the notebooks missing from the cache and
   adds them (slower: the notebooks run again).

4. Build the documentation and check the page of the tutorial (``READTHEDOCS=True`` reproduces
   the Read the Docs settings; the log must show ``Using cached notebook`` for every tutorial):

   .. code-block:: bash

      cd docs
      READTHEDOCS=True make html

5. Commit the notebook and the cache:

   .. code-block:: bash

      git add docs/source/tutorials/GRSdriver_basics.ipynb docs/build/.jupyter_cache
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

Write the notebook in ``docs/source/tutorials/``: a title (``# ...``), a short introduction (what
the reader will learn, the data needed and where to get them), and markdown cells explaining each
step. Add it to the ``toctree`` and to the table of ``docs/source/tutorials/index.rst``, then follow
the steps above.

Interactive widgets (holoviews, panel) need a running Python kernel: they are not displayed in the
static documentation, keep them out of the tutorials.
