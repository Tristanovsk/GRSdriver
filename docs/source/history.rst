
Version history
==================

v1.0.0:
    - first commit from S2driver package v1.0.6

v1.0.1:
    - package for Pypi

v1.0.2:
    - add documentation

v1.0.3:
    - working version for Landsat 8 and 9

v1.0.4:
    - add thermal bands for Landsat 8 and 9

v1.0.5:
    - add subset tool

v1.0.6:
    - fix for TIR bands (get brightness temperature alongside reflectance for vis-NIR-SWIR bands)

v1.0.7:
    - fix for new version xarray >=2024

v1.0.8:
    - fix xarray merge policy: compat='override'

v1.0.9:
    - faster loading: Sentinel-2 detector masks read once per band, nearest resampling of the angles
      by index lookup; Landsat angles and flags interpolated only when their grid differs from the bands,
      flags loaded once and on the subset window, vectorized reflectance conversion
    - dask-backed products with ``EOREADER_USE_DASK=1`` (eager loading stays the default, as it is faster with EOReader)
    - Landsat: valid angle pixels at the swath edges are no longer set to NaN
    - angles stored as float32, Landsat ``flags_l1`` as uint32
    - improved docstrings

Unreleased (develop):
    - lower memory use for large rasters (Sentinel-2): bands loaded one by one into a preallocated array,
      EOReader temporaries freed band by band, nearest resampling of the angles without full-size temporaries
    - Sentinel-2: ``lazy_geom`` option to keep ``vza`` and ``raa`` as dask arrays computed block by block
      from the ``resolution_angle`` grid (peak memory 7.0 GB -> 3.7 GB for a full tile at 20 m)
    - documentation: new Methods page with the equations of the reflectance, central wavelengths,
      geometry and memory footprint
