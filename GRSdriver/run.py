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
  --rgb_bands=RGB  band number to be used in RGB [default: '4,3,1']

  --resolution=res  spatial resolution of the scene pixels
  --no_clobber     Do not process <input_file> if <output_file> already exists.

'''

import os, sys
from docopt import docopt
import numpy as np
import logging
from GRSdriver import __package__, __version__


def main():

    args = docopt(__doc__, version=__package__ + '_' + __version__)
    print(args)

    file = args['<input_file>']

    resolution = int(args['--resolution'])
    RGB = np.array(args['--rgb_bands'])
    noclobber = args['--no_clobber']

    ##################################
    # File naming convention
    ##################################

    outfile = args['-o']
    if outfile == None:
        basename = os.path.basename(file)
        outfile = basename.replace('.SAFE', '').rstrip('/')

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

   # TODO implement the RGB converter


    return


if __name__ == "__main__":
    main()
