#!/usr/bin/env python
from setuptools import setup

setup(name = "xspress3-streamer",
      version = "0.1.10",
      packages = ['xspress3'],
      scripts = ['scripts/xspress3_dummy_receiver.py',
                 'scripts/xspress3_writing_receiver.py',
                 'scripts/xspress3_liveview_receiver.py',
                 'scripts/Xspress3DS',],
      package_dir = {'':'.'},
     )
