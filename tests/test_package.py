'''
Tests of the installed package (no satellite data needed): version, data files, command line.
'''

from importlib.metadata import version

import pytest
import xarray as xr
from importlib_resources import files

import GRSdriver


def test_version():
    assert GRSdriver.__version__ == version('GRSdriver')


@pytest.mark.parametrize('name', ['rsr_landsat_8_oli_tirs.nc', 'rsr_landsat_9_oli_tirs.nc'])
def test_spectral_responses(name):
    '''Spectral response functions of Landsat installed with the package.'''
    with xr.open_dataset(files('GRSdriver.rsr.data').joinpath(name)) as srf:
        assert srf.sizes and all(size > 0 for size in srf.sizes.values())
        assert len(srf.data_vars) > 0


def test_command_line_imports():
    '''The command line module loads without its optional dependencies (matplotlib, cartopy).'''
    from GRSdriver import run
    assert callable(run.main)
