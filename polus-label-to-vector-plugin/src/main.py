import argparse
import logging

from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, wait
from multiprocessing import cpu_count
from pathlib import Path
import filepattern
import numpy as np
import zarr
from bfio.bfio import BioReader, BioWriter
import torch

from cellpose import dynamics

logging.getLogger('cellpose').setLevel(logging.CRITICAL)

TILE_SIZE = 2048
TILE_OVERLAP = 512

def flow_thread(input_path: Path,
                zfile: Path,
                use_gpu: bool,
                dev: torch.device,
                x: int,
                y: int,
                z: int) -> bool:
    """ Converts labels to flows

    This function converts labels in each tile to vector field.

    Args:
        input_path(path): Path of input image collection
        zfile(path): Path where output zarr file will be saved
        x(int): Start index of the tile in x dimension of image
        y(int): Start index of the tile in y dimension of image
        z(int): Z slice of the  image

    """
    
    logging.basicConfig(format='%(asctime)s - %(name)-8s - %(levelname)-8s - %(message)s',
                        datefmt='%d-%b-%y %H:%M:%S')
    logger = logging.getLogger("flow")
    logger.setLevel(logging.INFO)

    root = zarr.open(str(zfile))[0]
    
    with BioReader(input_path) as br:
        x_min = max([0, x - TILE_OVERLAP])
        x_max = min([br.X, x + TILE_SIZE + TILE_OVERLAP])
        y_min = max([0, y - TILE_OVERLAP])
        y_max = min([br.Y, y + TILE_SIZE + TILE_OVERLAP])
        
        # Normalize
        I = br[y_min:y_max, x_min:x_max, z:z+1, 0, 0].squeeze()
        _, image = np.unique(I, return_inverse=True)
        image = image.reshape(y_max-y_min,x_max-x_min)

        flow = dynamics.masks_to_flows(image,
                                       use_gpu,
                                       dev)[0]
        
        logger.debug('Computed flows on slice %d tile(y,x) %d:%d %d:%d ', z, y,
                     y_max, x, x_max)
        flow_final = flow[:, :, :, np.newaxis, np.newaxis].transpose(1, 2, 3, 0, 4)
        x_overlap = x - x_min
        x_min = x
        x_max = min([br.X, x + TILE_SIZE])
        y_overlap = y - y_min
        y_min = y
        y_max = min([br.Y, y + TILE_SIZE])
        
        root[0:1,0:1,z:z + 1,y_min:y_max, x_min:x_max,] = (I[y_overlap:y_max - y_min + y_overlap,
                                                             x_overlap:x_max - x_min + x_overlap,
                                                             np.newaxis,np.newaxis,np.newaxis]>0).transpose(4,3,2,0,1)
        root[0:1,1:3,z:z + 1,y_min:y_max,x_min:x_max] = flow_final[y_overlap:y_max - y_min + y_overlap,
                                                                   x_overlap:x_max - x_min + x_overlap,
                                                                   ...].transpose(4,3,2,0,1)
        root[0:1,3:4,z:z + 1,y_min:y_max, x_min:x_max,] = I[y_overlap:y_max - y_min + y_overlap,
                                                            x_overlap:x_max - x_min + x_overlap,
                                                            np.newaxis,np.newaxis,np.newaxis].astype(np.float32).transpose(4,3,2,0,1)

    return True

def main(inpDir: Path,
         outDir: Path,
         filePattern: str = None
         ) -> None:
    """ Turn labels into flow fields.

    Args:
        inpDir: Path to the input directory
        outDir: Path to the output directory
    """

    # Use a gpu if it's available
    use_gpu = torch.cuda.is_available()
    if use_gpu:
        dev = torch.device("cuda")
    else:
        dev = torch.device("cpu")
    logger.info(f'Running on: {dev}')
    
    # Determine the number of threads to run on
    num_threads = max([cpu_count() // 2, 1])
    logger.info(f'Number of threads: {num_threads}')
    
    # Get all file names in inpDir image collection based on input pattern
    if filePattern:
        fp = filepattern.FilePattern(inpDir, filePattern)
        inpDir_files = [file[0]['file'].name for file in fp()]
        logger.info('Processing %d labels based on filepattern  ' % (len(inpDir_files)))
    else:
        inpDir_files = [f.name for f in Path(inpDir).iterdir() if f.is_file()]
    
    # Loop through files in inpDir image collection and process
    processes = []
    
    if use_gpu:
        executor = ThreadPoolExecutor(num_threads)
    else:
        executor = ProcessPoolExecutor(num_threads)
    
    for f in inpDir_files:
        br = BioReader(Path(inpDir).joinpath(f).absolute())
        out_file = Path(outDir).joinpath(f.replace('.ome','_flow.ome').replace('.tif','.zarr')).absolute()
        bw = BioWriter(out_file,metadata=br.metadata)
        bw.C = 4
        bw.dtype = np.float32
        bw.channel_names = ['cell_probability','x','y','labels']
        
        bw._backend._init_writer()

        for z in range(br.Z):
            for x in range(0, br.X, TILE_SIZE):
                for y in range(0, br.Y, TILE_SIZE):
                    processes.append(executor.submit(flow_thread,
                                                     Path(inpDir).joinpath(f).absolute(),
                                                     out_file,
                                                     use_gpu,dev,
                                                     x, y, z))
        bw.close()
        br.close()

    done, not_done = wait(processes, 0)

    logger.info(f'Percent complete: {100 * len(done) / len(processes):6.3f}%')

    while len(not_done) > 0:
        for r in done:
            r.result()
        done, not_done = wait(processes, 5)
        logger.info(f'Percent complete: {100 * len(done) / len(processes):6.3f}%')
        
    executor.shutdown()

if __name__ == "__main__":
    # Initialize the logger
    logging.basicConfig(format='%(asctime)s - %(name)-8s - %(levelname)-8s - %(message)s',
                        datefmt='%d-%b-%y %H:%M:%S')
    logger = logging.getLogger("main")
    logger.setLevel(logging.INFO)

    ''' Argument parsing '''
    logger.info("Parsing arguments...")
    parser = argparse.ArgumentParser(prog='main', description='Cellpose parameters')

    # Input arguments
    parser.add_argument('--inpDir', dest='inpDir', type=str,
                        help='Input image collection to be processed by this plugin', required=True)
    parser.add_argument('--filePattern', dest='filePattern', type=str,
                        help='Input file name pattern.', required=False)
    # Output arguments
    parser.add_argument('--outDir', dest='outDir', type=str,
                        help='Output collection', required=True)

    # Parse the arguments
    args = parser.parse_args()
    inpDir = args.inpDir
    if (Path.is_dir(Path(args.inpDir).joinpath('images'))):
        # Switch to images folder if present
        inpDir = str(Path(args.inpDir).joinpath('images').absolute())
    logger.info('inpDir = {}'.format(inpDir))
    filePattern = args.filePattern
    logger.info('File pattern = {}'.format(filePattern))
    outDir = args.outDir
    logger.info('outDir = {}'.format(outDir))
    
    main(inpDir,
         outDir,
         filePattern)
