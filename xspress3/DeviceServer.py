from tango import DevState, Attr, SpectrumAttr
import PyTango
import numpy as np
import time
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
        self._stopped = False

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
        valid = ['SOFTWARE', 'EXTERNAL_MULTI', 'EXTERNAL_MULTI_GATE']
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
    EventWidths = device_property(dtype=(int,), default_value=[], doc='Per channel event width to override calibration.')

    def __init__(self, cl, name):
        Device.__init__(self, cl, name)
        StandardDetector.__init__(self)
        #self._latencytime = self.ReadoutTime  #### how the hell do you get self-attributes?!
        self._write_hdf5 = True
               
    def init_device(self):
        self.set_state(DevState.INIT)
        self.get_device_properties() # now available as attributes on self

        #check if event width set via property (ie overridden calibration)
        self.custom_event_widths = {}
        self.debug_stream("Event widths read from properties")
        for i, v in enumerate(self.EventWidths):
            self.custom_event_widths[i]=v
        else:
            self.debug_stream("Event widths read from hw (calibration")

        if hasattr(self, 'streamer'):
            self.streamer.q.put('kill')
            del self.streamer
        try:
            instr = Xspress3(baseip=self.BaseIP, basemac=self.BaseMAC,
                             baseport=self.BasePort,
                             name=self.Name, header_path=self.HeaderPath,
                             config_path=self.ConfigPath,
                             return_window_counts=self.ReturnCounters,
                             event_widths_override = self.custom_event_widths)
        except Exception as e:
            self.debug_stream(str(e))
            self.set_state(DevState.FAULT)
            self.set_status(str(e))
            return     

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
            self.add_attribute(attr=win1, r_meth=self.read_window_config, w_meth=self.write_window_config)
            name = "Window2_Ch"+str(ch)
            win2 = SpectrumAttr(name, PyTango.DevLong, PyTango.AttrWriteType.READ_WRITE,2) #attr value is [lo,hi]
            self.add_attribute(attr=win2, r_meth=self.read_window_config, w_meth=self.write_window_config)
            #event width
            name = "EventWidth_Ch"+str(ch)
            ew = Attr(name, PyTango.DevShort, PyTango.AttrWriteType.READ)
            self.add_attribute(attr=ew, r_meth=self.read_event_widths)

        # If required, counts in windows can be read directly from Tango e.g. by Sardana (they are always written to file)
        if self.ReturnCounters:
            cmd = command(f=self.ReadRawCounts_Window1, dtype_in=(int,), dtype_out=(int,), doc_in="channel, first frame, last frame", doc_out="window0 raw counts for requested channel for requested frames")
            self.add_command(cmd, True)
            cmd = command(f=self.ReadRawCounts_Window2, dtype_in=(int,), dtype_out=(int,), doc_in="channel, first frame, last frame", doc_out="window1 raw counts for requested channel for requested frames")
            self.add_command(cmd, True)
            cmd = command(f=self.ReadDtcCounts_Window1, dtype_in=(int,), dtype_out=(float,), doc_in="channel, first frame, last frame", doc_out="window0 dead time corrected counts for requested channel for requested frames")
            self.add_command(cmd, True)
            cmd = command(f=self.ReadDtcCounts_Window2, dtype_in=(int,), dtype_out=(float,), doc_in="channel, first frame, last frame", doc_out="window1 dead time corrected counts for requested channel for requested frames")
            self.add_command(cmd, True)

    def read_window_config(self, attr):
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

    def write_window_config(self, attr):
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

    def ReadRawCounts_Window1(self, arg):
        channel, first_frame, last_frame = int(arg[0]),int(arg[1]),int(arg[2])
        return self.read_counts(1,channel,first_frame,last_frame,dtc=False)

    def ReadRawCounts_Window2(self, arg):
        channel, first_frame, last_frame = int(arg[0]),int(arg[1]),int(arg[2])
        return self.read_counts(2,channel,first_frame,last_frame,dtc=False)

    def ReadDtcCounts_Window1(self, arg):
        channel, first_frame, last_frame = int(arg[0]),int(arg[1]),int(arg[2])
        return self.read_counts(1,channel,first_frame,last_frame,dtc=True)

    def ReadDtcCounts_Window2(self, arg):
        channel, first_frame, last_frame = int(arg[0]),int(arg[1]),int(arg[2])
        return self.read_counts(2,channel,first_frame,last_frame,dtc=True)

    def read_counts(self, window, chan, first, last, dtc=False):

        self.debug_stream("ReadCounts in Window: %d" % window)

        if first<1:  #lowest frame number is frame 1
            first=1

        range = last - first + 1
        if dtc:
            chan_counts = [-1.0]*range  # return array of data of appropriate size even if some frames not ready...
        else:
            chan_counts = [-1]*range  # ...floats if dead time corrected otherwise ints

        if self.streamer.instrument.nframes_processed == 0:
            self.debug_stream("read_counts in Window %d for frames %d-%d but 0 frames acquired" % (window, first, last))
            return chan_counts

        elif first > self.streamer.instrument.nframes_processed:
            self.debug_stream("read_counts in Window %d for frames %d-%d but only %d frames acquired " % (window, first,last,self.streamer.instrument.nframes_processed))
            return chan_counts

        elif first <= self.streamer.instrument.nframes_processed and last > self.streamer.instrument.nframes_processed:
            self.debug_stream("read_counts in Window %d for frames %d-%d but last frame available is %d " % (window, first,last,self.streamer.instrument.nframes_processed))
            last = self.streamer.instrument.nframes_processed

        read=False
        requested_data = []
        while read==False:  # array is filled in separate thread, and we may ask too soon...
            time.sleep(self._exposuretime/10.0)
            if(window==1):
                if dtc:
                    requested_data = self.streamer.instrument.window1_data_dtc[first-1:last]  # e.g frame i means pass [lo=i,hi=i] which is i-1:i since count from 0
                else:
                    requested_data = self.streamer.instrument.window1_data_raw[first-1:last]  # e.g frame i means pass [lo=i,hi=i] which is i-1:i since count from 0
            else:
                if dtc:
                    requested_data = self.streamer.instrument.window2_data_dtc[first-1:last]  
                else:
                    requested_data = self.streamer.instrument.window2_data_raw[first-1:last]  
            if len(requested_data)==last-first+1 or self._stopped: # if we have the data we expect
                read=True

        #print("Leave WHILE", len(requested_data), self.streamer.instrument.nframes_processed, first, last, last-first+1)

        # Ugly extraction from list of arrays but seems fast, few ms for 1000 triggers (cf 80ms to readScalars in Lima for one frame)
        for trigger, frame_data in enumerate(requested_data):
            frame_data_for_channel = frame_data[chan]
            chan_counts[trigger]=frame_data_for_channel

        return np.nan_to_num(chan_counts) # in case dtc was 0 giving a nan which Tango does not like


    def read_event_widths(self, attr):
        attrname = attr.get_name()
        ch = int(attrname.split("Ch")[1])
        self.debug_stream("Reading event width setting for %s " % attrname)
        if self.custom_event_widths == {} or len(self.custom_event_widths)!=self.streamer.instrument.num_chan:
            self.debug_stream("Channel %d has calibrated event width " % ch)
            attr.set_value(self.streamer.instrument.event_widths[ch])
        else:
            self.debug_stream("Channel %d has custom event width property " % ch)
            attr.set_value(self.custom_event_widths[ch])

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
        self._stopped = False
        if self._write_hdf5 and self._destinationfilename:
            self.hdf_writer = WritingReceiver(host='localhost', port=self.StreamerPort, disposable=True)
            self.hdf_thread = Thread(target=self.hdf_writer.run)
            self.hdf_thread.start()
        self._swtrigs = 0
        nframes = self._nframespertrigger * self._ntriggers # either ntrigs or nframespertrigger must be one
        self.streamer.instrument.acquire_frames(
            frame_time=self._exposuretime-self._latencytime,
            n_frames=nframes,
            n_trig=self._ntriggers,
            trig_mode=self._triggermode,
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
        self._stopped = True

    def always_executed_hook(self):
        if self.get_state() == DevState.FAULT:
            return
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
