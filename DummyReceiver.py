import zmq
import numpy as np
import matplotlib.pyplot as plt
plt.ion()

class Receiver(object):
    def __init__(self, port=9999, host='localhost'):
        context = zmq.Context()
        self.sock = context.socket(zmq.SUB)
        self.sock.connect ("tcp://%s:%u" % (host, port))
        self.sock.setsockopt(zmq.SUBSCRIBE, b"")

    def run(self):
        plt.figure()
        while True:
            meta = self.sock.recv_json()
            print(meta)
            if meta['htype'] == 'image':
                buff = self.sock.recv()
                m, n = meta['shape'][:2]
                frame = np.frombuffer(buff, dtype=meta['type']).reshape((m, n), order='F')
                plt.gca().clear()
                plt.plot(frame)
                plt.axvline(640, linestyle='--', color='k')
                plt.pause(.01)
                print(frame.shape, frame.dtype)

if __name__ == '__main__':
    r = Receiver(host='b303a-a100380-cab01-dia-detxfcu-01')
    r.run()

