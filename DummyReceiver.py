import zmq
import time
import numpy as np
import matplotlib.pyplot as plt
plt.ion()

class Receiver(object):
    def __init__(self, port=9999, host='localhost', plot=True):
        context = zmq.Context()
        self.sock = context.socket(zmq.SUB)
        self.sock.connect ("tcp://%s:%u" % (host, port))
        self.sock.setsockopt(zmq.SUBSCRIBE, b"")
        self.plot = plot

    def run(self):
        if self.plot:
            plt.figure()
            plt.axvline(640, linestyle='--', color='k')
            lines = []
        while True:
            meta = self.sock.recv_json()
            print(meta)
            if meta['htype'] == 'image':
                buff = self.sock.recv()
                m, n = meta['shape'][:2]
                frame = np.frombuffer(buff, dtype=meta['type']).reshape((m, n), order='F')
                if self.plot:
                    while lines:
                        lines.pop(0).remove()
                    lines = plt.plot(frame[::10])
                    plt.pause(1e-10)
                print(frame.shape, frame.dtype)

if __name__ == '__main__':
    r = Receiver(host='b303a-a100380-cab01-dia-detxfcu-01', plot=False)
    r.run()
