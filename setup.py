
from setuptools import setup, find_packages

# read the contents of README file
from pathlib import Path
this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text()

__package__ = 'GRSdriver'
__version__ = '1.0.0'

setup(
    name=__package__,
    version=__version__,
    # other arguments omitted
    long_description=long_description,
    long_description_content_type='text/markdown',
    packages=find_packages(exclude=['build']),
    package_data={
        '': ['*.nc', '*.txt', '*.csv', '*.dat'],

    },
    include_package_data=True,

    url='',
    license='Apache Software License',
    author='T. Harmel',
    author_email='tristan.harmel@gmail.com',
    description='Driver dedicated to the Level 1C of the ESA Sentinel-2 imagery including accurate computations of the viewing angle for each spectral band',

    # Dependent packages (distributions)
    install_requires=['GDAL', 'numpy', 'scipy', 'pandas', 'xarray','rioxarray',
                      'matplotlib', 'rasterio', 'cartopy',
                      'numba','eoreader','docopt',
                      'geopandas','affine','shapely','s2cloudless',
                      'xmltodict' ,'importlib_resources'],

    entry_points={
         'console_scripts': [
             'GRSdriver = GRSdriver.run:main'
         ]}
)
