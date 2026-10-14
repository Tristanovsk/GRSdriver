# Configuration file for the Sphinx documentation builder.
#
# For the full list of options see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html
#
# The API is generated with sphinx-autoapi, which parses the source code
# statically: GRSdriver (and its heavy dependencies: GDAL, EOReader...) is never
# imported to build the docs.

import os
import re

DOCS_SOURCE = os.path.dirname(os.path.abspath(__file__))
PACKAGE_DIR = os.path.abspath(os.path.join(DOCS_SOURCE, '..', '..', 'GRSdriver'))
ON_RTD = os.environ.get('READTHEDOCS') == 'True'

# -- Project information -----------------------------------------------------

project = 'GRSdriver'
copyright = '2026, T. Harmel'
author = 'Tristan Harmel'

# version read from the package without importing it
with open(os.path.join(PACKAGE_DIR, '__init__.py')) as f:
    version = re.search(r"^__version__\s*=\s*['\"]([^'\"]+)['\"]", f.read(), re.M).group(1)
release = version

today_fmt = "%Y-%m-%d"

# -- General configuration ---------------------------------------------------

extensions = [
    'autoapi.extension',
    'sphinx.ext.intersphinx',
    'sphinx.ext.mathjax',
    'sphinx.ext.todo',
    'sphinx.ext.viewcode',
    'sphinx.ext.duration',
    'sphinx_copybutton',
    'sphinxcontrib.mermaid',
    'myst_nb',
    'IPython.sphinxext.ipython_console_highlighting',
]

exclude_patterns = []

intersphinx_mapping = {
    'python': ('https://docs.python.org/3', None),
    'numpy': ('https://numpy.org/doc/stable', None),
    'pandas': ('https://pandas.pydata.org/docs', None),
    'xarray': ('https://docs.xarray.dev/en/stable', None),
    'geopandas': ('https://geopandas.org/en/stable', None),
}

# -- API (sphinx-autoapi) ----------------------------------------------------

autoapi_type = 'python'
autoapi_dirs = [PACKAGE_DIR]
# command line script and spectral response formatting scripts are not part of the API
autoapi_ignore = ['*/run.py', '*/rsr/*']
autoapi_root = 'api'
# the API entry is placed in the index.rst toctree
autoapi_add_toctree_entry = False
autoapi_member_order = 'bysource'
# constructor parameters are documented in the class docstrings
autoapi_python_class_content = 'class'
autoapi_options = [
    'members',
    'undoc-members',
    'show-inheritance',
    'show-module-summary',
]
suppress_warnings = [
    'autoapi.python_import_resolution',
    # heading levels inside the tutorial notebooks
    'myst.header',
    # holoviews/bokeh loader outputs of the notebooks cannot be rendered statically
    'mystnb.unknown_mime_type',
]


def skip_member(app, what, name, obj, skip, options):
    # logging setup of the package, not part of the API
    if name in ('GRSdriver.logger', 'GRSdriver.level'):
        return True
    return skip


def setup(app):
    app.connect('autoapi-skip-member', skip_member)

# -- Options for HTML output -------------------------------------------------

pygments_style = 'sphinx'
html_theme = 'sphinx_book_theme'

html_theme_options = {
    'repository_url': 'https://github.com/Tristanovsk/GRSdriver',
    'repository_branch': 'master',
    'use_repository_button': True,
    'use_issues_button': True,
    'use_edit_page_button': True,
    'navigation_with_keys': True,
    'path_to_docs': 'docs/source',
}

html_logo = '_static/GRS_driver.svg'
html_title = ''
html_favicon = '_static/GRS_driver_light.png'

html_static_path = ['_static']
html_css_files = ['custom.css']

html_show_sourcelink = False
html_last_updated_fmt = today_fmt

# canonical URL provided by Read the Docs
html_baseurl = os.environ.get('READTHEDOCS_CANONICAL_URL', '')

htmlhelp_basename = 'grs_driver_doc'

# -- Jupyter notebooks (myst-nb) ---------------------------------------------

myst_enable_extensions = [
    'amsmath',
    'colon_fence',
    'deflist',
    'dollarmath',
    'html_admonition',
    'html_image',
    'linkify',
    'replacements',
    'smartquotes',
    'substitution',
]

# The notebooks need satellite images that are not available on Read the Docs:
# they are executed locally and their outputs are taken from the execution cache
# committed in docs/build/.jupyter_cache (same location for local and RTD builds).
nb_execution_mode = 'cache'
nb_execution_cache_path = os.path.join(DOCS_SOURCE, '..', 'build', '.jupyter_cache')
# a notebook missing from the cache cannot run on RTD: fail fast instead of hanging
nb_execution_timeout = 60 if ON_RTD else 1800
nb_execution_allow_errors = True
nb_execution_raise_on_error = False

# merge stderr and stdout
nb_merge_streams = True
