from threading import Thread
from queue import Queue, Empty
import zmq
import time
if __name__ == '__main__':
    from xspress3.Instrument import Xspress3
else:
    from .Instrument import Xspress3
import numpy as np

class CircularBufferError(Exception):
    pass

class Streamer(Thread):
    def __init__(self, instrument, data_port=9999, monitor_port=9998, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.instrument = instrument
        self.q = Queue()
        self.errq = Queue()
        context = zmq.Context()
        self.data_sock = context.socket(zmq.PUB)
        # a reasonable high-water mark (50000 messages, ~1 Gb):
        self.data_sock.set_hwm(50000)
        self.data_sock.bind('tcp://*:%u' % data_port)
        self.monitor_sock = context.socket(zmq.REP)
        self.monitor_sock.bind('tcp://*:%u' % monitor_port)

    def run(self):
        killed = False
        sent_frames = 0
        stopped = True
        ever_started = False
        sent_last_to_monitor = False
        data = np.zeros((2,2), dtype='uint32')
        last_print = 0.
        frames_since_last_print = 0
        nframes = 0
        while not killed:

            try:
                # handle incoming commands - no block or timeout
                try:
                    cmd = self.q.get(block=False)
                    if cmd.startswith('start'):
                        ever_started = True
                        stopped = False
                        filename = cmd.split()[1]
                        filename = '' if filename.lower()=='none' else filename
                        nframes = int(cmd.split()[2])
                        overwritable = cmd.split()[3]
                        overwritable = True if overwritable.lower() == 'true' else False
                        self.data_sock.send_json({'htype': 'header',
                                             'filename': filename,
                                             'overwritable': overwritable})
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
                if not sent_last_to_monitor:
                    try:
                        msg = self.monitor_sock.recv_string(flags=zmq.NOBLOCK)
                        sent_last_to_monitor = True
                        print('Message on the monitoring port: "%s". Sending an image.' % msg)
                        dct = {'htype': 'image',
                               'exptime': self.instrument._latest_exptime,
                               'frame': sent_frames,
                               'type': 'uint32',
                               'shape': (data.shape[1], data.shape[0])}
                        self.monitor_sock.send_json(dct, flags=zmq.SNDMORE)
                        self.monitor_sock.send(data)
                    except zmq.ZMQError:
                        pass

                # handle incoming data - only sleep if there's none
                # For x3 mini, get error if you ask for the progress before arming!
                if ever_started:
                    available_frames = self.instrument.nframes_processed
                else:
                    available_frames = 0                    

                if (available_frames > sent_frames) and not stopped:
                    # gather data
                    frame_info = {'starting_frame':sent_frames, 'n_frames':1}

                    data = self.instrument.read_hist_data(**frame_info)
                    # scalar data explicitly, plus event width
                    (win0, win1, AllEvents, AllGood, ClockTicks,
                        TotalTicks, ResetTicks, dtc, ocr, event_widths
                        ) = self.instrument.read_scalar_data(**frame_info)

                    if self.instrument.sum_window_counts==True:
                        self.instrument.window1_data_raw.append(win0[0]) # 0th element since read one frame at a time
                        self.instrument.window2_data_raw.append(win1[0])  
                        self.instrument.window1_data_dtc.append(win0[0]*dtc[0])
                        self.instrument.window2_data_dtc.append(win1[0]*dtc[0])  

                    # first send a header
                    self.data_sock.send_json({'htype': 'image',
                                         'exptime': self.instrument._latest_exptime,
                                         'frame': sent_frames,
                                         'shape': (data.shape[1], data.shape[0]),
                                         'type': 'uint32',
                                         'compression': 'none'})
                    # then send the histogram image - copy the data to release
                    # the SDK's circular buffer and let zmq deal with it.
                    self.data_sock.send(data, copy=True)
                    self.instrument.clear_circular_buffer(**frame_info)
                    frames_since_last_print += 1

                    # Now send extra data. We used to send as dict, which is easy for the receiver
                    # to interpret. Unfortunately pickling a dict took too much time, so now sending
                    # as a list, which is faster but where the receiver has to know the order. Forming
                    # and sending the below list takes around 150 us.
                    self.data_sock.send_pyobj([ocr[0], AllEvents[0], AllGood[0], ClockTicks[0],
                                               TotalTicks[0], ResetTicks[0], event_widths, dtc[0]])

                    sent_frames += 1
                    sent_last_to_monitor = False
                    if sent_frames == nframes:
                        self.data_sock.send_json({'htype': 'series_end'})
                else:
                    time.sleep(.001)

                # maybe time to print some info
                if (time.time() - last_print) >= 1.:
                    beginc, endc = ('\033[92m', '\033[0m')
                    print(beginc, end='')
                    print('Streamer: sent %u new frames (total %u / %u)' %
                               (frames_since_last_print, sent_frames, nframes))
                    print(endc, end='')
                    last_print = time.time()
                    frames_since_last_print = 0

                # check for circular buffer overrun
                if self.instrument.overrun_detected:
                    raise CircularBufferError("Circular buffer overrun detected!")

            except Exception as e:
                self.errq.put(e)
                raise e

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
    s.q.put('start /data/staff/nanomax/alex_tmp/testfile.h5 100 False')
    time.sleep(5)
    s.q.put('stop')
    s.q.put('kill')
