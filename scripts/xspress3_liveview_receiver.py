#/env/bin/python3
import sys
from xspress3.Receivers import LiveViewReceiver
host, port = 'b303a-a100380-cab01-dia-detxfcu-01', 9998
r = LiveViewReceiver(host=host, port=port)
r.run()
