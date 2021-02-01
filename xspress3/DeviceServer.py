from tango import DevState, Attr, SpectrumAttr
import PyTango
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
    ReturnCounters = device_property(dtype=bool, default_value=False, doc='Counters available as Tango attributes.')

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
        
        # create per channel attributes
        self.initialize_per_channel_attributes()

        self.set_state(DevState.STANDBY)
        self.set_status('')

    def delete_device(self):
        self.debug_stream("In delete device")
        self.__del__()

    def __del__(self):
        print('Killing and joining the streamer...')
        self.streamer.q.put('kill')
        self.streamer.join()

    def initialize_per_channel_attributes(self):
        nchans = self.streamer.instrument.num_chan
        for ch in range(0,nchans):
            name = "Window1_Ch"+str(ch)
            win1 = SpectrumAttr(name, PyTango.DevLong, PyTango.AttrWriteType.READ_WRITE,2) #attr value is [lo,hi]
            self.add_attribute(attr=win1, r_meth=self.read_windows, w_meth=self.write_windows)
            name = "Window2_Ch"+str(ch)
            win2 = SpectrumAttr(name, PyTango.DevLong, PyTango.AttrWriteType.READ_WRITE,2) #attr value is [lo,hi]
            self.add_attribute(attr=win2, r_meth=self.read_windows, w_meth=self.write_windows)
            #event width
            name = "EventWidth_Ch"+str(ch)
            ew = Attr(name, PyTango.DevShort, PyTango.AttrWriteType.READ)
            self.add_attribute(attr=ew, r_meth=self.read_event_widths)

        # If required, counts in windows can be read directly from Tango e.g. by Sardana (they are always written to file)
        if self.ReturnCounters:
            cmd = command(f=self.ReadCounts_Window1, dtype_in=(int,), dtype_out=(int,), doc_in="channel, first frame, last frame", doc_out="window0 counts for requested channel for requested frames")
            self.add_command(cmd, True)
            cmd = command(f=self.ReadCounts_Window2, dtype_in=(int,), dtype_out=(int,), doc_in="channel, first frame, last frame", doc_out="window1 counts for requested channel for requested frames")
            self.add_command(cmd, True)

    def read_windows(self, attr):
        attrname = attr.get_name()
        ch = int(attrname.split("Ch")[1])
        self.debug_stream("Reading window settings for %s " % attrname)
        if "Window1" in attrname:
            lo, hi = self.streamer.instrument.get_window(ch,0) #window 1 = 0th window
            self.debug_stream("Return Window1 information for channel %d: (%d, %d) " % (ch, lo, hi))
            attr.set_value([lo,hi])
        else:
            lo, hi = self.streamer.instrument.get_window(ch,1) #window 2 = 1st window
            self.debug_stream("Return Window2 information for channel %d: (%d, %d) " % (ch, lo, hi))
            attr.set_value([lo,hi])

    def write_windows(self, attr):
        attrname = attr.get_name()
        ch = int(attrname.split("Ch")[1])
        attrval = attr.get_write_value()
        lo = attrval[0]
        hi = attrval[1]
        if hi>4095:
            hi=4095
        if lo<0:
            lo=0
        self.debug_stream("Writing window settings for %s (%d, %d)" % (attrname, lo, hi))
        if "Window1" in attrname:
            self.streamer.instrument.set_window(ch,lo,hi,0)
        else:
            self.streamer.instrument.set_window(ch,lo,hi,1)

    def ReadCounts_Window1(self, arg):
        channel = int(arg[0])
        first_frame = int(arg[1])
        last_frame = int(arg[2])
        return self.ReadCounts(1,channel,first_frame,last_frame)

    def ReadCounts_Window2(self, arg):
        channel = int(arg[0])
        first_frame = int(arg[1])
        last_frame = int(arg[2])
        return self.ReadCounts(2,channel,first_frame,last_frame)

    def ReadCounts(self, window, chan, first, last):

        self.debug_stream("ReadCounts in Window: %d" % window)

        range = last - first + 1
        chan_counts = [-1]*range  # return array of data of appropriate size even if some frames not ready

        if self.streamer.instrument.nframes_processed == 0:
            self.debug_stream("Request ReadCounts in Window %d for frames %d-%d but 0 frames acquired" % (window, first, last))

        elif first > self.streamer.instrument.nframes_processed:
            self.debug_stream("Request ReadCounts in Window %d for frames %d-%d but only %d frames acquired " % (window, first,last,self.streamer.instrument.nframes_processed))
            
        elif first <= self.streamer.instrument.nframes_processed and last > self.streamer.instrument.nframes_processed:
            self.debug_stream("Request ReadCounts in Window %d for frames %d-%d but last frame available is %d " % (window, first,last,self.streamer.instrument.nframes_processed))

        if(window==1):
            requested_data = self.streamer.instrument.window1_data[first-1:last]  # e.g to frame i means pass [lo=i,hi=i] which is i-1:i since count from 0
        else:
            requested_data = self.streamer.instrument.window2_data[first-1:last]  

        # Ugly extraction from list of arrays but seems fast, few ms for 1000 triggers (cf 80ms to readScalars in Lima for one frame)
        for trigger, frame_data in enumerate(requested_data):
            frame_data_for_channel = frame_data[chan]
            chan_counts[trigger]=frame_data_for_channel

        print("chan counts", chan_counts)
        return chan_counts


    def read_event_widths(self, attr):
        attrname = attr.get_name()
        ch = int(attrname.split("Ch")[1])
        self.debug_stream("Reading event width setting for %s " % attrname)
        width = self.streamer.instrument.event_widths[ch]
        attr.set_value(width)

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
        if self._write_hdf5 and self._destinationfilename:
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
        dest = self._destinationfilename if self._destinationfilename else 'None'
        self.streamer.q.put('start %s %u' % (dest, nframes))

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
        if self.get_state() == DevState.RUNNING:
            # set the state back to standby when done
            done = self.streamer.instrument.nframes_processed
            due = self._ntriggers * self._nframespertrigger
            if done == due:
                self.set_state(DevState.STANDBY)
            # check if the Streamer is OK
            if not self.streamer.is_alive():
                exc = self.streamer.errq.get()
                self.set_state(DevState.FAULT)
                self.set_status('My Streamer thread is dead with this error: %s' % exc)

def main():
    Xspress3DS.run_server()
        
if __name__ == '__main__':
    main()
