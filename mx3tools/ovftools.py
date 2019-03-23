# This code is based on oommfdecode.py by Duncan Parkes:
# https://github.com/deparkes/OOMMFTools/blob/master/oommftools/core/oommfdecode.py
# The _binary_decode function is taken almost directly from there, except the order in which the OVF data is stored
# has been changed to conform with numpy's array indexing conventions.
#
# The _fast_binary_decode function uses numpy's ndarray constructor to eliminate the need for loops, dramatically
# reducing the time needed to move the data read from the file object into an array (~100x speedup).

import numpy as np
import struct
import pathlib
import tqdm
from . import ioutil


def unpack_slow(path):
    path = ioutil.pathize(path)

    with path.open('rb') as f:
        headers = _read_header(f)

        if headers['data_type'][3] == 'Text':
            return _text_decode(f, headers)

        elif headers['data_type'][3] == 'Binary':
            chunk_size = int(headers['data_type'][4])
            endianness = _endianness(f, nbytes)
            decoder = _byte_decoder(endianness)
            return _binary_decode(f, chunk_size, decoder, headers, endianness)


def unpack(path):
    path = ioutil.pathize(path)

    with path.open('rb') as f:
        headers = _read_header(f)

        if headers['data_type'][3] == 'Text':
            return _text_decode(f, headers)

        elif headers['data_type'][3] == 'Binary':
            chunk_size = int(headers['data_type'][4])
            return _fast_binary_decode(f, chunk_size, headers, _endianness(f, chunk_size))


def _read_header(fobj):
    """Read headers from OVF file object. fobj must be opened in 'rb' mode (read as bytes).

    Parameters
    ----------
    fobj : file
        OVF file to read, must be opened in bytes mode (mode='rb')

    Returns
    -------
    dict
        Dictionary containing the [important] header keys and values
    """

    headers = {'SimTime': -1, 'Iteration': -1, 'Stage': -1, 'MIFSource': ''}

    line = ''
    while 'Begin: Data' not in line:

        line = fobj.readline().strip().decode()

        for key in ["xbase",
                    "ybase",
                    "zbase",
                    "xstepsize",
                    "ystepsize",
                    "zstepsize",
                    "xnodes",
                    "ynodes",
                    "znodes",
                    "valuemultiplier"]:
            if key in line:
                headers[key] = float(line.split(': ')[1])

        if 'Total simulation time' in line:
            headers['SimTime'] = float(line.split(':')[-1].strip().split()[0].strip())
        elif 'Iteration' in line:
            headers['Iteration'] = float(line.split(':')[2].split(',')[0].strip())
        elif 'Stage' in line:
            headers['Stage'] = float(line.split(':')[2].split(',')[0].strip())
        elif 'MIF source file' in line:
            headers['MIFSource'] = line.split(':', 2)[2].strip()
        else:
            continue

    headers['data_type'] = line.split()

    return headers


def _byte_decoder(endianness):
    return struct.Struct(endianness)


def _endianness(f, nbytes):
    buffer = f.read(nbytes)

    big_endian = {4: '>f', 8: '>d'}
    little_endian = {4: '<f', 8: '<d'}
    value = {4: 1234567.0, 8: 123456789012345.0}

    if struct.unpack(big_endian[nbytes], buffer)[0] == value[nbytes]:       # Big endian?
        return big_endian[nbytes]
    elif struct.unpack(little_endian[nbytes], buffer)[0] == value[nbytes]:  # Little endian?
        return little_endian[nbytes]
    else:
        raise IOError(f'Cannot decode {nbytes}-byte order mark: ' + hex(buffer))


def _binary_decode(f, chunk_size, decoder, headers, dtype):

    data = np.empty((int(headers['znodes']),
                     int(headers['ynodes']),
                     int(headers['xnodes']), 3), dtype=dtype)

    for k in range(data.shape[0]):
        for j in range(data.shape[1]):
            for i in range(data.shape[2]):
                for coord in range(3):
                    data[k, j, i, coord] = decoder.unpack(f.read(chunk_size))[0]

    return data*headers.get('valuemultiplier', 1)


def _text_decode(f, headers):

    data = np.empty((int(headers['znodes']),
                     int(headers['ynodes']),
                     int(headers['xnodes']), 3), dtype=float)

    for k in range(data.shape[0]):
        for j in range(data.shape[1]):
            for i in range(data.shape[2]):
                text = f.readline().strip().split()
                data[k, j, i] = (float(text[0]), float(text[1]), float(text[2]))

    return data*headers.get('valuemultiplier', 1)


def _fast_binary_decode(f, chunk_size, headers, dtype):

    xs, ys, zs = (int(headers['xnodes']), int(headers['ynodes']), int(headers['znodes']))
    ret = np.ndarray(shape=(xs*ys*zs, 3),
                     dtype=dtype,
                     buffer=f.read(xs*ys*zs*3*chunk_size),
                     offset=0,
                     strides=(3*chunk_size, chunk_size))

    return ret.reshape((zs, ys, xs, 3))


def _fast_binary_decode_scalars(f, chunk_size, headers, dtype):

    xs, ys, zs = (int(headers['xnodes']), int(headers['ynodes']), int(headers['znodes']))
    ret = np.ndarray(shape=(xs*ys*zs, 1),
                     dtype=dtype,
                     buffer=f.read(xs*ys*zs*chunk_size),
                     offset=0,
                     strides=(chunk_size, chunk_size))

    return ret.reshape((zs, ys, xs))


def group_unpack(path):

    path = ioutil.pathize(path)

    if path.suffix == '.out':
        files = sorted(path.glob('m*.ovf'))
    elif path.suffix == '.ovf':
        files = sorted(path.parent.glob('m*.ovf'))

    return np.array([unpack(f) for f in tqdm.tqdm(files)])


def unpack_scalars(path):
    path = ioutil.pathize(path)

    with path.open('rb') as f:
        headers = _read_header(f)

        if headers['data_type'][3] == 'Binary':
            chunk_size = int(headers['data_type'][4])
            return _fast_binary_decode_scalars(f, chunk_size, headers, _endianness(f, chunk_size))

        else:
            raise NotImplementedError
