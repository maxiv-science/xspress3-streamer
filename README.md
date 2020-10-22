This package provides

- A convenient Python wrapper around the official Xspress3 SDK.
- A threaded streaming utility which continuously streams out the data over zmq
- A Tango device to optionally contain these things, and
- Basic stream receivers for live plotting and fast file writing.

## To-do list
- Direct readback of histogram and scalar data over Tango.
- Expose window counters (aka ROI:s).
- Enable recording only part of the spectrum (what the SDK calls ROI:s).

## Pipeline overview

The core of the pipeline is a process running on the rack server. This process runs the C-library, listens to commands, streams out data, optionally writes files, and provides live data on the monitoring port upon request. This is done in a dedicated thread, so that the Tango device remains responsive.

Not that the file writing, the downstream receivers, and the live viewer are optional. Sardana controllers are not provided, as NanoMAX runs [contrast](https://github.com/maxiv-science/contrast) instead.

<img src="doc/overview.png" alt="Pipeline overview" width="800px"/>

## Data and monitor streams

Two zmq interfaces are presented. An efficient data socket which transfers raw data with minimal latency, and a monitoring socket which gives the latest frame upon request by for example a live viewer.

## Data written

The built-in data writer writes frames together with deadtime correction information and all scalar quantities (event information, exact frame time in clock cycles, etc) to file. Any custom file writer can be hooked up to the zmq data port.

<img src="doc/hsd5_structure.png" alt="HDF5 format" width="800px"/>

## Limitations
- The device is not operated in circular buffer mode, so there's a memory limit to the number of frames which can be recorded in one go, typically 16384 frames if the full energy axis is used.
- Currently no auxiliary dimensions are taken care of. Not even sure what these would be.
- Productively using multi-card setups would require additional timing setup.
 