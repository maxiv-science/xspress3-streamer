#/env/bin/python3
import sys
from xspress3.Receivers import WritingReceiver
host, port = 'b303a-a100380-cab01-dia-detxfcu-01', 9999
r = WritingReceiver(host=host, port=port)
r.run()
