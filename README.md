# s2driver package
## Tool for easy loading of Sentinel-2 L1C SAFE format with accurate computation of the viewing angles

### Installation on TREX (CNES)
1. First clone the repository:
```commandline
git clone https://gitlab.cnes.fr/waterquality/io/s2driver
```

2. Create the conda environment 'grs_cnes'
```commandline
module load conda
conda env create -f environment.yml
```

3. Install s2driver
```commandline
conda activate grs_cnes
pip install .
```
You are done.

### Usual installation, please use conda environment
conda create -n "YOUR_ENV" python=3.11

conda activate "YOUR_ENV"

conda install gdal numba rasterio

pip install .

## Example

![example gif](illustration/s2driver_visual_tool_optimized.gif)


## 2D-fiiting method for angle computation

![example files](fig/example_3D_fitting_one_detector_v2.png)
![example files](fig/example_2D_fitting_one_band_v3.png)
![example files](fig/example_scattering_angle_all_bands.png)
![example files](fig/example_reflectance_all_bands.png)
![example files](fig/example_ndwi_mask.png)
