

import os
import matplotlib
matplotlib.use('TkAgg')
import numpy as np
import pandas as pd
import xarray as xr

import datetime as dt

opj = os.path.join

idir='GRSdriver/rsr/data/'



#---------------------
# landsat-8 OLI-TIRS common
#---------------------
files={"OLI":'L8_Ball_BA_RSR.v1.2.xlsx',
      "TIRS":'L8_TIRS_Relative_Spectral_Responses.BA_.v1.xlsx'}

sheets = {"OLI":['CoastalAerosol','Blue','Green','Pan','Red','NIR','Cirrus','SWIR1','SWIR2'],
          "TIRS":["TIRS Band 10 BA RSR","TIRS Band 11 BA RSR"]}


#---------------------
# landsat-8 OLI
#---------------------
wl_hr=np.linspace(400,2349,1950)
BAND_NAMES = np.array(['B01', 'B02', 'B03', 'B08', 'B04', 'B05','B09', 'B06', 'B07'])
BAND_NAMES_EOREADER = np.array(['CA', 'BLUE', 'GREEN','PAN',  'RED', 'NIR',
                                'SWIR_CIRRUS','SWIR_1', 'SWIR_2'])

WAVELENGTH = np.array([443, 490, 560,590, 665, 865, 1370, 1610, 2190 ])

file = files["OLI"]
sheet = sheets["OLI"]

ofile='rsr_landsat_8_oli.nc'
SRFs=[]
for iband, band_name in enumerate(BAND_NAMES):

    df = pd.read_excel(opj(idir,file),sheet_name=sheet[iband])
    df.columns=['wl_hr','SRF','rsr_std']
    ds = df.set_index('wl_hr').to_xarray()
    ds['SRF'].interp(wl_hr=wl_hr,kwargs={"fill_value":0.})
    SRFs.append(ds['SRF'].interp(wl_hr=wl_hr).assign_coords(
                    dict(wl=WAVELENGTH[iband])))
SRFs = xr.concat(SRFs, dim='wl')
SRFs.attrs['OLI_long_name']='SRF_Landat_8_OLI'
SRFs.attrs['OLI_file_creation']=str(dt.datetime.now())
SRFs.attrs['OLI_from_file']=file
SRFs.attrs['OLI_description']='relative spectral response functions for Landat-8 OLI bands'
SRFs.to_netcdf(opj(idir,ofile))
SRFs.plot(x='wl_hr',hue='wl',color='orange',lw=1)
SRF_output=[SRFs]

#---------------------
# landsat-8 TIRS
#---------------------
wl_hr=np.linspace(9500,13500,1001)
BAND_NAMES = np.array(['B08','B09'])
BAND_NAMES_EOREADER = np.array(['TIR_1','TIR_2'])

WAVELENGTH = np.array([ 11000,12000 ])

file = files["TIRS"]
sheet = sheets["TIRS"]
ofile='rsr_landsat_8_tirs.nc'
SRFs=[]
for iband, band_name in enumerate(BAND_NAMES):

    df = pd.read_excel(opj(idir,file),sheet_name=sheet[iband],index_col=0)
    df.index.name='wl_hr'
    # convert into nm
    df.index = df.index * 1e3
    # get RSR only to compute mean(RSR) (i.e., remove stadard deviation columns)
    df=df.loc[:, df.columns.str.contains('RSR')].mean(axis=1)

    ds = df.to_xarray()
    ds.name='SRF'
    ds.interp(wl_hr=wl_hr,kwargs={"fill_value":0.})
    SRFs.append(ds.interp(wl_hr=wl_hr).assign_coords(
                    dict(wl=WAVELENGTH[iband])))
SRFs = xr.concat(SRFs, dim='wl')
SRFs.attrs['TIRS_long_name']='SRF_Landat_8_TIRS'
SRFs.attrs['TIRS_file_creation']=str(dt.datetime.now())
SRFs.attrs['TIRS_from_file']=file
SRFs.attrs['TIRS_description']='relative spectral response functions for Landat-8 TIRS bands'
SRFs.to_netcdf(opj(idir,ofile))
SRFs.plot(x='wl_hr',hue='wl',color='orange',lw=1)
SRF_output.append(SRFs)

# merge files:
ofile='rsr_landsat_8_oli_tirs.nc'
allSRFs=xr.merge(SRF_output,combine_attrs="no_conflicts")
allSRFs.to_netcdf(opj(idir,ofile))




#---------------------
# landsat-9 OLI-TIRS common
#---------------------
files={"OLI":'L9_OLI2_Ball_FPM_RSR.v1.0.xlsx',
      "TIRS":'L9_TIRS2_Relative_Spectral_Responses.BA.v1.0.xlsx'}

sheets = {"OLI":['CoastalAerosol','Blue','Green','Pan','Red','NIR','Cirrus','SWIR1','SWIR2'],
          "TIRS":["TIRS Band 10 BA RSR","TIRS Band 11 BA RSR"]}

#---------------------
# landsat-9 OLI
#---------------------
wl_hr=np.linspace(400,2349,1950)
BAND_NAMES = np.array(['B01', 'B02', 'B03', 'B08', 'B04', 'B05','B09', 'B06', 'B07','B08','B09'])
BAND_NAMES_EOREADER = np.array(['CA', 'BLUE', 'GREEN','PAN',  'RED', 'NIR',
                                'SWIR_CIRRUS','SWIR_1', 'SWIR_2','TIR_1','TIR_2'])

WAVELENGTH = np.array([443, 490, 560,590, 665, 865, 1370, 1610, 2190, 11000,12000 ])


file = files["OLI"]
sheet = sheets["OLI"]
ofile='rsr_landsat_9_oli.nc'
SRFs=[]
for iband, band_name in enumerate(BAND_NAMES[:-2]):

    df = pd.read_excel(opj(idir,file),sheet_name=sheet[iband],index_col=0)
    df.index.name='wl_hr'
    # get RSR only to compute mean(RSR) (i.e., remove stadard deviation columns)
    df=df.loc[:, df.columns.str.contains('RSR')].mean(axis=1)

    ds = df.to_xarray()
    ds.name='SRF'
    ds.interp(wl_hr=wl_hr,kwargs={"fill_value":0.})
    SRFs.append(ds.interp(wl_hr=wl_hr).assign_coords(
                    dict(wl=WAVELENGTH[iband])))
SRFs = xr.concat(SRFs, dim='wl')
SRFs.attrs['OLI_long_name']='SRF_Landat_9_OLI'
SRFs.attrs['OLI_file_creation']=str(dt.datetime.now())
SRFs.attrs['OLI_from_file']=file
SRFs.attrs['OLI_description']='relative spectral response functions for Landat-9 OLI bands'
SRFs.to_netcdf(opj(idir,ofile))
SRFs.plot(x='wl_hr',hue='wl',color='orange',lw=1)
SRF_output=[SRFs]
#---------------------
# landsat-9 TIRS
#---------------------
wl_hr=np.linspace(9500,13500,1001)
BAND_NAMES = np.array(['B08','B09'])
BAND_NAMES_EOREADER = np.array(['TIR_1','TIR_2'])

WAVELENGTH = np.array([ 11000,12000 ])

file = files["TIRS"]
sheet = sheets["TIRS"]
ofile='rsr_landsat_9_tirs.nc'
SRFs=[]
for iband, band_name in enumerate(BAND_NAMES):

    df = pd.read_excel(opj(idir,file),sheet_name=sheet[iband],index_col=0)
    df.index.name='wl_hr'
    # convert into nm
    df.index = df.index * 1e3
    # get RSR only to compute mean(RSR) (i.e., remove stadard deviation columns)
    df=df.loc[:, df.columns.str.contains('RSR')].mean(axis=1)

    ds = df.to_xarray()
    ds.name='SRF'
    ds.interp(wl_hr=wl_hr,kwargs={"fill_value":0.})
    SRFs.append(ds.interp(wl_hr=wl_hr).assign_coords(
                    dict(wl=WAVELENGTH[iband])))
SRFs = xr.concat(SRFs, dim='wl')
SRFs.attrs['TIRS_long_name']='SRF_Landat_9_TIRS'
SRFs.attrs['TIRS_file_creation']=str(dt.datetime.now())
SRFs.attrs['TIRS_from_file']=file
SRFs.attrs['TIRS_description']='relative spectral response functions for Landat-9 TIRS bands'
SRFs.to_netcdf(opj(idir,ofile))
SRFs.plot(x='wl_hr',hue='wl',color='orange',lw=1)
SRF_output.append(SRFs)

# merge files:
ofile='rsr_landsat_9_oli_tirs.nc'
allSRFs=xr.merge(SRF_output,combine_attrs="no_conflicts")
allSRFs.to_netcdf(opj(idir,ofile))