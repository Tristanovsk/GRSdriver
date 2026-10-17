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

Releasing a new version
=======================

GRSdriver is published on `PyPI <https://pypi.org/project/GRSdriver/>`_ as a source archive and a
pure-Python wheel; the version is read from ``__version__`` in ``GRSdriver/__init__.py``.

Prepare the release
-------------------

1. On ``develop``, set ``__version__`` (``X.Y.Z``) and add a line to the history comments of
   ``GRSdriver/__init__.py``; rename the ``Unreleased`` section of ``CHANGELOG.md`` to
   ``vX.Y.Z (YYYY-MM-DD)``.
2. Run the tests (``pytest tests``; they need the Sentinel-2 and Landsat test products, see the
   header of each test file) and, if the code of a tutorial changed, rerun it (see above).
3. Commit, bring ``master`` up to ``develop`` and tag:

   .. code-block:: shell

      git commit -am "vX.Y.Z"
      git fetch . develop:master        # fast-forward master without leaving develop
      git tag -a X.Y.Z -m "vX.Y.Z"

Build and check
---------------

With ``build`` and ``twine`` (``pip install build twine``), in an empty output directory:

.. code-block:: shell

   rm -rf dist build
   python -m build                      # dist/grsdriver-X.Y.Z.tar.gz and -py3-none-any.whl
   twine check dist/*                   # metadata and README rendering on PyPI

Check the wheel in a fresh environment (no GDAL installation needed):

.. code-block:: shell

   python -m venv /tmp/venv_grsdriver
   /tmp/venv_grsdriver/bin/pip install dist/grsdriver-X.Y.Z-py3-none-any.whl pytest
   cd tests && /tmp/venv_grsdriver/bin/python -I -m pytest -q   # -I: test the installed package

Publish
-------

1. Push the branches and the tag:

   .. code-block:: shell

      git push origin master develop
      git push origin X.Y.Z

2. Upload to PyPI. Once the trusted publisher is set up (see below), pushing the tag is enough:
   the ``publish`` GitHub workflow checks that the tag equals ``__version__``, builds and uploads the
   distributions. Otherwise, upload them yourself with an
   `API token <https://pypi.org/manage/account/token/>`_ (user name ``__token__``, the token as
   password, or stored in ``~/.pypirc``):

   .. code-block:: shell

      twine upload dist/*

   A version cannot be uploaded twice: use one of the two ways, not both. To try the upload first,
   use `TestPyPI <https://test.pypi.org>`_ (``twine upload --repository testpypi dist/*``, separate
   account and token).
3. Check ``pip install --upgrade GRSdriver`` and the project page; Read the Docs builds the
   documentation of ``master`` automatically. With the ``publish`` workflow, the GitHub release of
   the tag is also created, with the CHANGELOG section of the version as notes and the
   distributions attached; otherwise, create it by hand from the tag.

Continuous integration
----------------------

Two GitHub Actions workflows are in ``.github/workflows``:

- ``tests.yml``, on each push to ``master`` or ``develop`` and on pull requests: installs the package
  with Python 3.9 (oldest supported), 3.12 and 3.13 and runs the tests (those that need satellite
  products are skipped), then builds the distributions and runs ``twine check``;
- ``publish.yml``, on a version tag (e.g. ``2.0.2``): builds and uploads to PyPI, then creates the
  GitHub release (notes from the CHANGELOG). Push the tag alone (``git push origin 2.0.2``): GitHub
  starts no workflow for the tags of a push that contains more than three tags.

The upload uses `trusted publishing <https://docs.pypi.org/trusted-publishers/>`_, without any token
stored on GitHub. One-time setup:

1. on PyPI, *Your projects* > GRSdriver > *Publishing* > *Add a new publisher* > GitHub: owner
   ``Tristanovsk``, repository ``GRSdriver``, workflow ``publish.yml``, environment ``pypi``;
2. on GitHub, *Settings* > *Environments* > *New environment* ``pypi`` (optionally with yourself as
   required reviewer, to approve each upload).

Pushing workflow files over HTTPS needs a token with the ``workflow`` scope.
