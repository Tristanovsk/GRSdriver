# import ez_setup
# ez_setup.use_setuptools()

from setuptools import setup, find_packages

__package__ = 'GRSdriver'
__version__ = '1.0.6'

setup(
    name=__package__,
    version=__version__,
    packages=find_packages(exclude=['build']),
    package_data={
        '': ['*.nc', '*.txt', '*.csv', '*.dat'],

    },
    include_package_data=True,

    url='',
    license='MIT',
    author='T. Harmel',
    author_email='tristan.harmel@gmail.com',
    description='driver dedicated to the Level 1C of the ESA Sentinel-2 imagery including accurate computations of the viewing angle for each spectral band',

    # Dependent packages (distributions)
    # install_requires=['numpy', 'scipy', 'pandas', 'xarray',
    #                   'matplotlib', 'rasterio', 'cartopy',
    #                   'numba','eoreader',
    #                   'geopandas','affine','shapely','memory_profiler','xmltodict' ,'importlib_resources']
    # entry_points={
    #     'console_scripts': [
    #         'GRSdriver = TODO'
    #     ]}
)
