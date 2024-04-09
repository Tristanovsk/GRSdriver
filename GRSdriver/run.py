''' Executable to convert Sentinel-2 or Landsat 8/9 L1C images to png format

Usage:
  GRSdriver <input_file>  [-o <ofile>] [--odir <odir>] [--rgb_bands ][--resolution res]
  grs -h | --help
  grs -v | --version

Options:
  -h --help        Show this screen.
  -v --version     Show version.

  <input_file>     Input file to be processed

  -o ofile         Full (absolute or relative) path to output L2 image.
  --odir odir      Ouput directory [default: ./]
  --no_clobber     Do not process <input_file> if <output_file> already exists.
  --resolution=res  spatial resolution of the scene pixels
  --rgb_bands R,G,B  band number to be used in RGB [default: 4,3,1]

'''

import os, sys
from docopt import docopt
import numpy as np
import logging
from . import __package__, __version__


def main():
    args = docopt(__doc__, version=__package__ + '_' + __version__)
    print(args)

    file = args['<input_file>']

    resolution = int(args['--resolution'])
    R,G,B = np.array(args['--rgb_bands'])
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
