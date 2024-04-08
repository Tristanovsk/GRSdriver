<img src="docs/_static/GRS_driver.png" alt="GRSdriver_icon" width="100"/>

# GRSdriver package
## Driver dedicated to load and prepare data for the GRS processor
- Tool for easy loading of Sentinel-2 L1C SAFE format with accurate computation of the viewing angles
- Applicable to Landsat 8 and 9
- Visualization tools

### Installation
1. First clone the repository:
```commandline
git clone https://github.com/Tristanovsk/GRSdriver.git
```

2. You may duplicate the conda environment (optional)
```commandline
conda env create -f environment.yml
```

3. Install GRSdriver
```commandline
conda activate grssuite
pip install .
```
You are done.

### Usual installation
```commandline
pip install .
```

## Example

![example gif](docs/_static/s2driver_visual_tool_optimized.gif)


## 2D-fiiting method for angle computation


![example files](docs/_static/example_2D_fitting_one_band_v3.png)
![example files](docs/_static/example_scattering_angle_all_bands.png)
![example files](docs/_static/example_reflectance_all_bands.png)
![example files](docs/_static/example_ndwi_mask.png)
