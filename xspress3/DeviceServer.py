from tango import DevState
from tango.server import Device, attribute, command, device_property
from threading import Thread

if __name__ == '__main__':
    from xspress3.Streamer import Streamer
    from xspress3.Instrument import Xspress3
    from xspress3.Receivers import WritingReceiver
else:
    from .Streamer import Streamer
    from .Instrument import Xspress3
    from .Receivers import WritingReceiver

class StandardDetector(object):
    """
    A standard detector Tango Device as proposed by Paul Bell.

    Contains the trivial attributes that just expose internal variables.
    """
    def __init__(self):
        self._exposuretime = .1
        self._ntriggers = 1
        self._nframespertrigger = 1
        self._latencytime = 0.
        self._triggermode = 'SOFTWARE'
        self._destinationfilename = '/tmp/temp.h5'

    @attribute(dtype=float, format='%e')
    def ExposureTime(self):
        return self._exposuretime

    @ExposureTime.setter
    def ExposureTime(self, val):
        self._exposuretime = val

    @attribute(dtype=int)
    def nTriggers(self):
        return self._ntriggers

    @nTriggers.setter
    def nTriggers(self, val):
        self._ntriggers = val

    @attribute(dtype=int)
    def nFramesPerTrigger(self):
        return self._nframespertrigger

    @nFramesPerTrigger.setter
    def nFramesPerTrigger(self, val):
        self._nframespertrigger = val    

    @attribute(dtype=float, format='%.2e')
    def LatencyTime(self):
        return self._latencytime

    @LatencyTime.setter
    def LatencyTime(self, val):
        self._latencytime = val

    @attribute(dtype=str)
    def TriggerMode(self):
        return self._triggermode

    @TriggerMode.setter
    def TriggerMode(self, val):
        valid = ['SOFTWARE', 'EXTERNAL']
        assert (val in valid), 'TriggerMode can be %s'%(' or '.join(valid))
        self._triggermode = val

    @attribute(dtype=str)
    def DestinationFileName(self):
        return self._destinationfilename

    @DestinationFileName.setter
    def DestinationFileName(self, val):
        self._destinationfilename = val


class Xspress3DS(Device, StandardDetector):
    """
    Xspress3 streaming device server.
    """

    HeaderPath = device_property(dtype=str, default_value='/opt/xspress3-sdk/include', doc='Path to the SDK header files, for extracting #define:s.')
    Name = device_property(dtype=str, default_value='', doc='Xspress3 name, empty for default.')
    ConfigPath = device_property(dtype=str, default_value='/home/xspress3/settings', doc='Path to the xspress3 calibration files.')
    StreamerPort = device_property(dtype=int, default_value=9999, doc='Port which the Streamer should use for data.')
    MonitorPort = device_property(dtype=int, default_value=9998, doc='Port which the Streamer should use for monitoring.')
    BaseIP = device_property(dtype=str, default_value='', doc='IP from which to start counting.')
    BasePort = device_property(dtype=int, default_value=-1, doc='Port number from which to start counting.')
    BaseMAC = device_property(dtype=str, default_value='', doc='MAC from which to start counting.')

    def __init__(self, cl, name):
        Device.__init__(self, cl, name)
        StandardDetector.__init__(self)
        #self._latencytime = self.ReadoutTime  #### how the hell do you get self-attributes?!
        self._write_hdf5 = True
               
    def init_device(self):
        self.set_state(DevState.INIT)
        self.get_device_properties() # now available as attributes on self
        if hasattr(self, 'streamer'):
            self.streamer.q.put('kill')
            del self.streamer
        instr = Xspress3(baseip=self.BaseIP, basemac=self.BaseMAC,
                         baseport=self.BasePort,
                         name=self.Name, header_path=self.HeaderPath,
                         config_path=self.ConfigPath)
        self.streamer = Streamer(instrument=instr, data_port=self.StreamerPort, monitor_port=self.MonitorPort)
        self.streamer.start()
        self.set_state(DevState.STANDBY)

    def __del__(self):
        print('Killing and joining the streamer...')
        self.streamer.q.put('kill')
        self.streamer.join()

    @attribute(dtype=bool, doc="The device can optionally receive its own stream and write it to hdf5.")
    def WriteHdf5(self):
        return self._write_hdf5

    @WriteHdf5.setter
    def WriteHdf5(self, val):
        self._write_hdf5 = val

    @attribute(dtype=float, format='%.2e')
    def ReadoutTime(self):
        return self.streamer.instrument._gap_time

    @attribute(dtype=int)
    def nFramesAcquired(self):
        return self.streamer.instrument.nframes_processed

    @attribute(dtype=bool)
    def ReadyForSwTrigger(self):
        if not self.get_state() == DevState.RUNNING:
            return False
        if not self._triggermode == 'SOFTWARE':
            return False
        done = self.streamer.instrument.nframes_processed
        due = self._swtrigs
        if done == due:
            return True

    @command
    def Arm(self):
        self.set_state(DevState.RUNNING)
        if self._write_hdf5:
            self.hdf_writer = WritingReceiver(host='localhost', port=self.StreamerPort, disposable=True)
            self.hdf_thread = Thread(target=self.hdf_writer.run)
            self.hdf_thread.start()
        self._swtrigs = 0
        nframes = self._nframespertrigger * self._ntriggers
        self.streamer.instrument.acquire_frames(
            frame_time=self._exposuretime-self._latencytime,
            n_frames=nframes,
            n_trig=self._ntriggers,
            hw_trig=(self._triggermode=='EXTERNAL'),
            card=0,)
        if self._destinationfilename:
            self.streamer.q.put('start %s %u' % (self._destinationfilename, nframes))

    @command
    def SoftwareTrigger(self):
        self.streamer.instrument.soft_trigger()
        self._swtrigs += 1

    @command
    def Stop(self):
        self.streamer.instrument.stop()
        self.streamer.q.put('stop')
        self.set_state(DevState.STANDBY)

    def always_executed_hook(self):
        # set the state back to standby when done
        if self.get_state() == DevState.RUNNING:
            done = self.streamer.instrument.nframes_processed
            due = self._ntriggers * self._nframespertrigger
            if done == due:
                self.set_state(DevState.STANDBY)

def main():
    Xspress3DS.run_server()
        
if __name__ == '__main__':
    main()
