# Changelog

All notable changes to GRSdriver are listed here, most recent first.

## Unreleased

- Landsat: the driver no longer uses EOReader. The bands are read with rasterio/GDAL (warped VRT
  on the output grid, only the needed pixels are read) and converted with the coefficients of the
  `*_MTL.xml` file. Results are identical to the EOReader version at 30 m, except:
  - PAN: the 15 m grid (shifted by 7.5 m) is now correctly averaged onto the 30 m grid;
  - other resolutions: the output pixel size is exact (e.g. 100 m instead of 100.013 m), the bands
    are averaged without the fill pixels, and `flags_l1` is resampled with nearest neighbour
    (it was averaged by EOReader for integer factors).
- Landsat: `prod.attrs['tile']` (WRS path/row, e.g. `196030`) added, as required by GRS to find
  the CAMS files; `orbit_direction` and `product_filename` attributes removed.
- Landsat: `LandsatDriver` no longer accepts `**kwargs` (they were passed to EOReader), `subset`
  given as a sequence takes a bounding box in the product CRS, the `reader` attribute is removed.
- `utils.read_on_grid`: read a raster on a target grid through a GDAL warped VRT.

## v1.1.1 (2026-10-14)

- `grs_driver` command line: Sentinel-2 products are now supported (driver chosen from the product
  name), default RGB bands per sensor (Sentinel-2: B04, B03, B02; Landsat: RED, GREEN, BLUE), red and
  blue channels no longer swapped, `.png` added to the output name so that `--no_clobber` works,
  trailing `/` of the input path handled, southern UTM zones detected.

## v1.1.0 (2026-10-14)

- Sentinel-2: the bands of a full tile are now loaded one by one, as intended. The grid check of
  `stack_bands` compares only the x/y values, because the `spatial_ref` coordinate differs between
  resampled and coarsened bands. EOReader `stack` is no longer used as a fallback, and B01 and B02
  are no longer loaded twice. Peak memory of `load_bands` drops from 8.6 GB to 3.75 GB for a full
  tile at 20 m (13 bands).

## v1.0.10 (2026-10-08)

- Lower memory use for large rasters (Sentinel-2): bands loaded one by one into a preallocated array,
  EOReader temporaries freed band by band, nearest resampling of the angles without full-size temporaries.
- Sentinel-2: `lazy_geom` option to keep `vza` and `raa` as dask arrays computed block by block
  from the `resolution_angle` grid (peak memory 7.0 GB -> 3.7 GB for a full tile at 20 m).
- Documentation: new Methods page with the equations of the reflectance, central wavelengths,
  geometry and memory footprint.

## v1.0.9 (2026-10-07)

- Faster loading: Sentinel-2 detector masks read once per band, nearest resampling of the angles
  by index lookup; Landsat angles and flags interpolated only when their grid differs from the bands,
  flags loaded once and on the subset window, vectorized reflectance conversion.
- Dask-backed products with `EOREADER_USE_DASK=1` (eager loading stays the default, as it is faster with EOReader).
- Landsat: valid angle pixels at the swath edges are no longer set to NaN.
- Angles stored as float32, Landsat `flags_l1` as uint32.
- Improved docstrings.

## v1.0.8 (2025-02-10)

- Fix xarray merge policy: `compat='override'`.

## v1.0.7

- Fix for new versions of xarray (>= 2024).

## v1.0.6 (2024-08-28)

- Fix for TIR bands (brightness temperature provided alongside reflectance for the VIS-NIR-SWIR bands).

## v1.0.5

- Add subset tool.

## v1.0.4

- Add thermal bands for Landsat 8 and 9.

## v1.0.3

- Working version for Landsat 8 and 9.

## v1.0.2

- Add documentation.

## v1.0.1

- Package for PyPI.

## v1.0.0

- First commit, from the S2driver package v1.0.6.
