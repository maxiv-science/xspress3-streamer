#/env/bin/python3
import sys
from xspress3.Receivers import WritingReceiver
host, port = '172.16.126.70', 9999
r = WritingReceiver(host=host, port=port)
r.run()
