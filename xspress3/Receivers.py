"""
Stream receivers for the Xspress3, both for the data and monitoring ports.
"""

import zmq
import json
import numpy as np
import os, h5py
import time
import matplotlib.pyplot as plt

class DummyReceiver(object):
    """
    Receiver which monitors the data PUB socket and just prints what
    comes out. Good for testing and as a minimal example.
    """
    def __init__(self, port=9999, host='localhost', disposable=False):
        context = zmq.Context()
        self.sock = context.socket(zmq.SUB)
        self.sock.connect ("tcp://%s:%u" % (host, port))
        self.sock.setsockopt(zmq.SUBSCRIBE, b"")
        self.disposable = disposable

    def run(self):
        while True:
            meta = self.sock.recv_json()
            print(meta)
            if meta['htype'] == 'image':
                buff = self.sock.recv()
                m, n = meta['shape'][:2]
                frame = np.frombuffer(buff, dtype=meta['type']).reshape((m, n))
                extra = self.sock.recv_pyobj()
                print(frame.shape, frame.dtype, extra['deadtime_correction_factors'].shape)

class WritingReceiver(DummyReceiver):
    """
    Receiver which reads from the data PUB socket and writes to hdf5.
    """
    def run(self):
        print('disposable writer running')
        while True:
            meta = self.sock.recv_json()
            print(meta)
            if meta['htype'] == 'header':
                fn = meta['filename']
                while os.path.exists(fn):
                    fn = fn.split('.')[0] + '_.' + fn.split('.', maxsplit=1)[-1]
                fp = h5py.File(fn, 'w')

            elif meta['htype'] == 'image':
                buff = self.sock.recv()
                m, n = meta['shape'][:2]
                frame = np.frombuffer(buff, dtype=meta['type']).reshape((m, n))
                extra = self.sock.recv_pyobj()
                extra['frames'] = frame
                if meta['frame'] == 0:
                    #create datasets
                    for name, arr in extra.items():
                        d = fp.create_dataset(name, shape=(1,)+arr.shape, maxshape=(None,)+arr.shape, dtype=arr.dtype)
                        d[:] = arr
                else:
                    #expand datasets
                    for name, arr in extra.items():
                        d = fp[name]
                        old = d.shape[0]
                        d.resize((old+1,) + d.shape[1:])
                        d[old:] = arr
                print(frame.shape, frame.dtype)

            elif meta['htype'] == 'series_end':
                fp.flush()
                fp.close()
                if self.disposable:
                    print('disposable writer done')
                    return 0

class LiveViewReceiver(object):
    """
    Receiver which asks for images on the monitoring socket at regular
    intervals, and plots spectra.
    """
    def __init__(self, port=9998, host='localhost', delay=.5):
        context = zmq.Context()
        self.sock = context.socket(zmq.REQ)
        res = self.sock.connect("tcp://%s:%u" % (host, port))
        self.delay = delay

    def run(self):
        plt.ion()
        fig = plt.figure()
        while True:
            plt.pause(self.delay)
            self.sock.send_string('give us a frame please!')
            print('asked for a frame...')
            parts = self.sock.recv_multipart() # blocks
            meta = json.loads(parts[0])
            frameno = meta['frame']
            m, n = meta['shape'][:2]
            print('***', meta, len(parts[1]))
            frame = np.frombuffer(parts[1], dtype=meta['type']).reshape((m, n))
            plt.gca().clear()
            print(frame.shape)
            for i, curve in enumerate(frame):
                plt.plot(curve, label='%u'%i)
            plt.legend()
