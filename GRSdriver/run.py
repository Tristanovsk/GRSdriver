'''
Executable to convert Sentinel-2 or Landsat 8/9 L1C images to png format

Usage:
  grs_driver <input_file> [--rgb_bands RGB] [-o <ofile>] [--odir <odir>] [--resolution res] [--no_clobber]
  grs_driver -h | --help
  grs_driver -v | --version

Options:
  -h --help        Show this screen.
  -v --version     Show version.

  <input_file>     Input file to be processed

  -o ofile         Full (absolute or relative) path to output L2 image.
  --odir odir      Ouput directory [default: ./]
  --rgb_bands RGB  Comma separated list of the band indices of the red, green and blue
                   channels (default: 3,2,1 for Sentinel-2, i.e. B04,B03,B02;
                   4,2,1 for Landsat, i.e. RED,GREEN,BLUE)
  --resolution res  spatial resolution of the scene pixels [default: 60]
  --no_clobber     Do not process <input_file> if <output_file> already exists.

'''

import os, sys
from docopt import docopt
import numpy as np
import logging

from GRSdriver import __package__, __version__
import GRSdriver

import matplotlib.pyplot as plt
import cartopy.crs as ccrs
from eoreader.env_vars import USE_DASK
# Ensure EOReader uses dask
os.environ[USE_DASK] = "1"

def main():

    args = docopt(__doc__, version=__package__ + '_' + __version__)
    print(args)

    file = args['<input_file>']

    resolution = int(args['--resolution'])
    noclobber = args['--no_clobber']

    # Sentinel-2 L1C (.SAFE) or Landsat 8/9 Collection-2 L1
    basename = os.path.basename(file.rstrip('/'))
    is_s2 = basename.startswith('S2') or basename.endswith('.SAFE')
    rgb_bands = args['--rgb_bands'] or ('3,2,1' if is_s2 else '4,2,1')
    RGB = [int(x) for x in rgb_bands.split(',')]
    ##################################
    # File naming convention
    ##################################

    outfile = args['-o']
    if outfile == None:
        outfile = basename.replace('.SAFE', '')
    if not os.path.splitext(outfile)[1]:
        outfile += '.png'

    odir = args['--odir']
    if odir == './':
        odir = os.getcwd()

    if not os.path.exists(odir):
        os.makedirs(odir)

    outfile = os.path.join(odir, outfile)

    if os.path.exists(outfile) & noclobber:
        print('File ' + outfile + ' already processed; skip!')
        sys.exit()

    logging.info('making RGB image for:' +
                 file + ', output file:' + outfile +
                 ', resolution:' + str(resolution))

    # load product into l1c object
    driver = GRSdriver.Sentinel2Driver if is_s2 else GRSdriver.LandsatDriver
    l1c = driver(file,
                 band_idx=RGB,
                 resolution=resolution)
    l1c.load_bands()

    # get geographic information
    epsg = l1c.extent.crs.to_epsg()
    str_epsg = str(epsg)
    zone = str_epsg[-2:]
    is_south = str_epsg[2] == '7'
    proj = ccrs.UTM(zone, southern_hemisphere=is_south)

    # plot RGB image

    plt.figure(figsize=(15, 15))
    # bands are in the order of RGB: red, green, blue
    p = l1c.prod.bands.squeeze().plot.imshow(rgb='wl', robust=True, subplot_kws=dict(projection=proj))
    p.figure.savefig(outfile)

    return


if __name__ == "__main__":
    main()
