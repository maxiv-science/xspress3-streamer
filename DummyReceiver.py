import zmq
import numpy as np

class Receiver(object):
    def __init__(self, port=9999):
        context = zmq.Context()
        self.sock = context.socket(zmq.SUB)
        self.sock.connect ("tcp://localhost:%u" % port)
        self.sock.setsockopt(zmq.SUBSCRIBE, b"")

    def run(self):
        while True:
            meta = self.sock.recv_json()
            print(meta)
            if meta['htype'] == 'image':
                buff = self.sock.recv()
                m, n = meta['shape'][:2]
                frame = np.frombuffer(buff, dtype=meta['type']).reshape((m, n))
                print(frame.shape, frame.dtype)

if __name__ == '__main__':
    r = Receiver()
    r.run()
