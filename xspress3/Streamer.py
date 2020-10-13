from threading import Thread
from queue import Queue, Empty
import zmq
import time
if __name__ == '__main__':
    from xspress3.Instrument import Xspress3
else:
    from .Instrument import Xspress3
import numpy as np

class Streamer(Thread):
    def __init__(self, instrument, data_port=9999, monitor_port=9998, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.instrument = instrument
        self.q = Queue()
        context = zmq.Context()
        self.data_sock = context.socket(zmq.PUB)
        self.data_sock.bind('tcp://*:%u' % data_port)
        self.monitor_sock = context.socket(zmq.REP)
        self.monitor_sock.bind('tcp://*:%u' % monitor_port)

    def run(self):
        killed = False
        sent_frames = 0
        stopped = True
        data = np.zeros((2,2))
        while not killed:
            # handle incoming commands - no block or timeout
            try:
                cmd = self.q.get(block=False)
                if cmd.startswith('start'):
                    stopped = False
                    filename = cmd.split()[1]
                    nframes = int(cmd.split()[2])
                    self.data_sock.send_json({'htype': 'header',
                                         'filename': filename})
                    sent_frames = 0
                elif cmd.startswith('stop'):
                    print('got the stop command!')
                    stopped = True
                    self.data_sock.send_json({'htype': 'series_end'})
                elif cmd == 'kill':
                    print('Streamer got the kill message. Going down!')
                    killed = True
            except Empty:
                pass

            # check for requests on the monitor port
            try:
                msg = self.monitor_sock.recv(flags=zmq.NOBLOCK)
                print('#########################Message received: "%s". Sending an image.' % msg)
                self.monitor_sock.send_json({'htype': 'image',
                                             'frame': sent_frames,
                                             'shape': (data.shape[1], data.shape[0])})
                self.monitor_sock.send(data, copy=False)
            except zmq.ZMQError:
                pass

            # handle incoming data - only sleep if there's none
            available_frames = self.instrument.nframes_processed
            if (available_frames > sent_frames) and not stopped:
                # gather data
                data = self.instrument.read_hist_data(starting_frame=sent_frames, n_frames=1)
                dtc, i0 = self.instrument.calculate_dtc(starting_frame=sent_frames, n_frames=1)
                scalars = self.instrument.read_scalar_data(starting_frame=sent_frames, n_frames=1)
                print('sending data (%s) because available=%u and sent=%u'%((data.shape[1], data.shape[0]), available_frames, sent_frames))
                # first send a header
                self.data_sock.send_json({'htype': 'image',
                                     'frame': sent_frames,
                                     'shape': (data.shape[1], data.shape[0]),
                                     'type': 'uint32',
                                     'compression': 'none'}, flags=zmq.SNDMORE)
                # then send the histogram image - super fast with buffers
                self.data_sock.send(data, copy=False)
                # then send the additional scalar info - a bit stupid to
                # pickle like this, but takes ~100 us so it's ok.
                self.data_sock.send_pyobj({'deadtime_correction_factors': dtc[0],
                                      'estimated_total_counts': i0[0],
                                      'scalars': scalars[0]})
                sent_frames += 1
                print('**** %u / %u' % (sent_frames, nframes))
                if sent_frames == nframes:
                    self.data_sock.send_json({'htype': 'series_end'})
            else:
                time.sleep(.01)

if __name__ == '__main__':
    """
    Test starting and stopping a burst.
    """

    # init
    instr = Xspress3()
    s = Streamer(instrument=instr)
    s.start()

    # take some frames and stream
    instr.acquire_frames(frame_time=.1, n_frames=100, n_trig=1)
    instr.soft_trigger()
    s.q.put('start /data/staff/nanomax/alex_tmp/testfile.h5 100')
    time.sleep(5)
    s.q.put('stop')
    s.q.put('kill')
