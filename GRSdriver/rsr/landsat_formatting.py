

import os

import numpy as np
import pandas as pd
import xarray as xr

import datetime as dt

opj = os.path.join

idir='./rsr/data/'

#---------------------
# landsat-8 OLI
#---------------------
wl_hr=np.linspace(400,2349,1950)
BAND_NAMES = np.array(['B01', 'B02', 'B03', 'B08', 'B04', 'B05','B09', 'B06', 'B07'])
BAND_NAMES_EOREADER = np.array(['CA', 'BLUE', 'GREEN','PAN',  'RED', 'NIR',
                                'SWIR_CIRRUS','SWIR_1', 'SWIR_2'])
sheets = ['CoastalAerosol','Blue','Green','Pan','Red','NIR','Cirrus','SWIR1','SWIR2']
WAVELENGTH = np.array([443, 490, 560,590, 665, 865, 1370, 1610, 2190 ])

file='Ball_BA_RSR.v1.2.xlsx'
ofile='rsr_landsat_8_oli.nc'
SRFs=[]
for iband, band_name in enumerate(BAND_NAMES):

    df = pd.read_excel(opj(idir,file),sheet_name=sheets[iband])
    df.columns=['wl_hr','SRF','rsr_std']
    ds = df.set_index('wl_hr').to_xarray()
    ds['SRF'].interp(wl_hr=wl_hr,kwargs={"fill_value":0.})
    SRFs.append(ds['SRF'].interp(wl_hr=wl_hr).assign_coords(
                    dict(wl=WAVELENGTH[iband])))
SRFs = xr.concat(SRFs, dim='wl')
SRFs.attrs['long_name']='SRF_Landat_8_OLI'
SRFs.attrs['file_creation']=str(dt.datetime.now())
SRFs.attrs['from_file']=file
SRFs.attrs['description']='relative spectral response functions for Landat-8 OLI bands'
SRFs.to_netcdf(opj(idir,ofile))
SRFs.plot(x='wl_hr',hue='wl',color='orange',lw=1)



#---------------------
# landsat-9 OLI
#---------------------
wl_hr=np.linspace(400,2349,1950)
BAND_NAMES = np.array(['B01', 'B02', 'B03', 'B08', 'B04', 'B05','B09', 'B06', 'B07'])
BAND_NAMES_EOREADER = np.array(['CA', 'BLUE', 'GREEN','PAN',  'RED', 'NIR',
                                'SWIR_CIRRUS','SWIR_1', 'SWIR_2'])
sheets = ['CoastalAerosol','Blue','Green','Pan','Red','NIR','Cirrus','SWIR1','SWIR2']
WAVELENGTH = np.array([443, 490, 560,590, 665, 865, 1370, 1610, 2190 ])

file='L9_OLI2_Ball_FPM_RSR.v1.0.xlsx'
ofile='rsr_landsat_9_oli.nc'
SRFs=[]
for iband, band_name in enumerate(BAND_NAMES):

    df = pd.read_excel(opj(idir,file),sheet_name=sheets[iband],index_col=0)
    df.index.name='wl_hr'
    # get RSR only to compute mean(RSR) (i.e., remove stadard deviation columns)
    df=df.loc[:, df.columns.str.contains('RSR')].mean(axis=1)

    ds = df.to_xarray()
    ds.name='SRF'
    ds.interp(wl_hr=wl_hr,kwargs={"fill_value":0.})
    SRFs.append(ds.interp(wl_hr=wl_hr).assign_coords(
                    dict(wl=WAVELENGTH[iband])))
SRFs = xr.concat(SRFs, dim='wl')
SRFs.attrs['long_name']='SRF_Landat_9_OLI'
SRFs.attrs['file_creation']=str(dt.datetime.now())
SRFs.attrs['from_file']=file
SRFs.attrs['description']='relative spectral response functions for Landat-9 OLI bands'
SRFs.to_netcdf(opj(idir,ofile))
SRFs.plot(x='wl_hr',hue='wl',color='orange',lw=1)
