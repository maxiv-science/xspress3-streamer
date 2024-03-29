"""
Stream receivers for the Xspress3, both for the data and monitoring ports.
"""

import zmq
import json
import numpy as np
import os, h5py
import time

# Extra data from the xspress3 comes as a list, with the following interpretation.
EXTRA = ['output_count_rate',
         'all_events',
         'all_good',
         'clock_ticks',
         'total_ticks',
         'reset_ticks',
         'event_width',
         'dead_time_correction',
         'data']

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
        self._color = '\033[94m'

    def print(self, msg):
        print(self._color + str(msg) + '\033[0m')

    def run(self):
        last_print = 0.
        frames_since_last_print = 0
        frames_total = 0
        while True:
            meta = self.sock.recv_json()
            if meta['htype'] == 'image':
                buff = self.sock.recv()
                m, n = meta['shape'][:2]
                frame = np.frombuffer(buff, dtype=meta['type']).reshape((m, n))
                extra = self.sock.recv_pyobj()
                frames_since_last_print += 1
                frames_total += 1
                # print some output sometimes
                if (time.time() - last_print) > 1.:
                    self.print('WritingReceiver: got %u new frames (%u total), shape %s, dtype %s'
                            %(frames_since_last_print, frames_total, frame.shape, frame.dtype))
                    last_print = time.time()
                    frames_since_last_print = 0
            elif meta['htype'] == 'series_end':
                self.print('WritingReceiver: got %u new frames (%u total), shape %s, dtype %s'
                            %(frames_since_last_print, frames_total, frame.shape, frame.dtype))
                self.print(meta)
            else:
                self.print(meta)

class WritingReceiver(DummyReceiver):
    """
    Receiver which reads from the data PUB socket and writes to hdf5.
    """
    def run(self):
        dsp = 'disposable' if self.disposable else 'persistent'
        self.print('%s writer running'%dsp)
        last_print = 0.
        frames_since_last_print = 0
        total_frames = 0
        while True:
            meta = self.sock.recv_json()
            if meta['htype'] == 'header':
                self.print(meta)
                fn = meta['filename']
                ow = meta['overwritable']
                if fn.lower() == 'none':
                    fn = ''
                if fn:
                    if ow==False:  #if not overwritable then append a _
                        while os.path.exists(fn):
                            fn = fn.split('.')[0] + '_.' + fn.split('.', maxsplit=1)[-1]
                    fp = h5py.File(fn, 'w')
                else:
                    self.print('Filename empty, not saving!')

            elif meta['htype'] == 'image':
                frames_since_last_print += 1
                total_frames += 1
                buff = self.sock.recv()
                m, n = meta['shape'][:2]
                frame = np.frombuffer(buff, dtype=meta['type']).reshape((m, n))
                extra = self.sock.recv_pyobj()
                extra.append(frame) # the actual data
                if fn:
                    if meta['frame'] == 0:
                        #first frame, create datasets within a group.  ie one arm creates one file.
                        group = fp.create_group('entry/instrument/xspress3')
                        group.attrs["NX_class"]="NXdetector"
                        for i, item in enumerate(extra):
                            print(i,item,type(item))
                            d = group.create_dataset(EXTRA[i], shape=(1,)+item.shape, maxshape=(None,)+item.shape, dtype=item.dtype, chunks=(1,)+item.shape)
                            d[:] = item
                    else:
                        #expand datasets
                        for i, item in enumerate(extra):
                            d = fp["entry/instrument/xspress3"][EXTRA[i]]
                            old = d.shape[0]
                            d.resize((old+1,) + d.shape[1:])
                            d[old] = item
                # print some output
                if (time.time() - last_print) > 1.:
                    self.print('WritingReceiver: got %u new frames (total %u)'
                                  %(frames_since_last_print, total_frames))
                    last_print = time.time()
                    frames_since_last_print = 0

            elif meta['htype'] == 'series_end':
                self.print('WritingReceiver: got %u new frames (total %u)'
                                  %(frames_since_last_print, total_frames))
                self.print(meta)
                if fn:
                    fp.flush()
                    fp.close()
                if self.disposable:
                    self.print('disposable writer done')
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
        import matplotlib.pyplot as plt
        plt.ion()
        fig = plt.figure()
        first = True
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
            #plt.gca().clear()
            print(frame.shape)
            rates = []
            if first:
                lines = []
                for i, curve in enumerate(frame):
                    lines.append(plt.plot([], label='%u'%i)[0])
                x = np.arange(len(curve))
                plt.xlim(0, x.max())
                plt.ylim(0, np.log10(curve[:-1].max())+1)
                first = False
            for i, curve in enumerate(frame):
                lines[i].set_data(x[:-1], np.log10(curve[:-1]))
                rates.append('ch%u: %.1e'%(i, curve.sum()/meta['exptime']))
            plt.draw()
            plt.suptitle('; '.join(rates) + ' ph/s')
            plt.legend()

