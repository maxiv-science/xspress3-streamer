from threading import Thread
from queue import Queue, Empty
import zmq
import time
from Instrument import Xspress3
import numpy as np

class Streamer(Thread):
    def __init__(self, instrument, port=9999, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.instrument = instrument
        self.q = Queue()
        context = zmq.Context()
        self.sock = context.socket(zmq.PUB)
        self.sock.bind('tcp://*:%u' % port)

    def run(self):
        killed = False
        sent_frames = 0
        stopped = True
        while not killed:
            # handle incoming commands - no block or timeout
            try:
                cmd = self.q.get(block=False)
                if cmd.startswith('start'):
                    stopped = False
                    filename = cmd.split()[1]
                    self.sock.send_json({'htype': 'header',
                                         'filename': filename})
                    sent_frames = 0
                elif cmd.startswith('stop'):
                    print('got the stop command!')
                    stopped = True
                    self.sock.send_json({'htype': 'series_end'})
                elif cmd == 'kill':
                    killed = True
            except Empty:
                pass

            # handle incoming data - only sleep if there's none
            available_frames = self.instrument.nframes_processed
            if (available_frames > sent_frames) and not stopped:
                data = self.instrument.read_hist_data(starting_frame=sent_frames, n_frames=1)
                print('sending data (%s) because available=%u and sent=%u'%(data.shape, available_frames, sent_frames))
                self.sock.send_json({'htype': 'image',
                                     'frame': sent_frames,
                                     'shape': list(data.shape),
                                     'type': 'uint32',
                                     'compression': 'none'}, flags=zmq.SNDMORE)
                self.sock.send(data, copy=False)
                sent_frames += 1
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
    s.q.put('start fakefile.h5')
    time.sleep(5)
    s.q.put('stop')
    s.q.put('kill')

