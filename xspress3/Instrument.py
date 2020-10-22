"""
Implements a Python3 interface to the Xspress3, via the proprietary SDK.

Limitations:
* The device is not operated in circular buffer mode, so there's a memory
  limit to the number of frames which can be recorded in one go, typically
  16384 frames if the full energy axis is used.
* Currently no auxiliary dimensions are taken care of.
* Productively using multi-card setups would require additional timing setup.
"""

import os, sys, time
import numpy as np
import ctypes
from ctypes.util import find_library

librt = ctypes.CDLL(find_library('rt'), mode=ctypes.RTLD_GLOBAL)
libm = ctypes.CDLL(find_library('m'), mode=ctypes.RTLD_GLOBAL)
libimg_mod = ctypes.CDLL(find_library('img_mod'), mode=ctypes.RTLD_GLOBAL)
libxspress3 = ctypes.CDLL(find_library('xspress3'))

# configure return values for anything that doesn't return an int
libxspress3.xsp3_get_error_message.restype = ctypes.c_char_p

ERROR_LOOKUP = {
0:   'XSP3_OK',
-1:  'XSP3_ERROR',
-2:  'XSP3_INVALID_PATH',
-3:  'XSP3_ILLEGAL_CARD',
-4:  'XSP3_ILLEGAL_SUBPATH',
-5:  'XSP3_INVALID_DMA_STREAM',
-6:  'XSP3_RANGE_CHECK',
-7:  'XSP3_INVALID_SCOPE_MOD',
-8:  'XSP3_OUT_OF_MEMORY',
-9:  'XSP3_ERR_DEV_NOT_FOUND',
-10: 'XSP3_CANNOT_OPEN_FILE',
-11: 'XSP3_FILE_READ_FAILED',
-12: 'XSP3_FILE_WRITE_FAILED',
-13: 'XSP3_FILE_RENAME_FAILED',
-14: 'XSP3_LOG_FILE_MISSING',
-20: 'XSP3_WOULD_BLOCK',}

class Xspress3(object):
    def __init__(self, ncards=1, maxframes=-1, baseip=None,
                 baseport=-1, basemac=None, nchan=-1, create_mod=-1,
                 name=None, debug=-1, cardindex=-1, debounce=80,
                 header_path='/opt/xspress3-sdk/include',
                 config_path='/home/xspress3/settings',):
        """
        The C constructor takes -1 and NULL for defaults everywhere
        for ints/*chars, respectively.

        debounce: (int) minimum number of 80 MHz clock cycles for a gate
                        to be considered changed, for excluding artefacts
                        in ringing cables.
        """
        baseip = baseip.encode() if baseip else None # converts 0 and "" to None
        basemac = basemac.encode() if basemac else None
        name = name.encode() if name else None
        if ncards > 1:
            raise Exception('More than one card isn''t supported')
        handle = libxspress3.xsp3_config(ncards, maxframes, baseip, baseport,
                                         basemac, nchan, int(create_mod), name,
                                         int(debug), cardindex)
        if handle < 0:
            raise Exception('Failed to configure the Xspress3 (code %s):\n*** %s ***' %
                                (ERROR_LOOKUP[handle], self.error()))
        self.handle = handle
        self._parse_headers(header_path)
        self.debounce = debounce
        self._gap_mode = self.XSP3_ITFG_GAP_MODE_25NS
        self._gap_time = {
            self.XSP3_ITFG_GAP_MODE_25NS: 25e-9,
            self.XSP3_ITFG_GAP_MODE_200NS: 200-9,
            self.XSP3_ITFG_GAP_MODE_500NS: 500e-9,
            self.XSP3_ITFG_GAP_MODE_1US: 1e-6,}[self._gap_mode]
        self.check(libxspress3.xsp3_set_run_flags(self.handle,
                    self.XSP3_RUN_FLAGS_HIST | self.XSP3_RUN_FLAGS_SCALERS))
        self.check(libxspress3.xsp3_clocks_setup(self.handle, 0, 
                        self.XSP3_CLK_SRC_XTAL,
                        self.XSP3_CLK_FLAGS_MASTER|self.XSP3_CLK_FLAGS_NO_DITHER, 0))
        self.check(libxspress3.xsp3_restore_settings(self.handle, config_path.encode('ascii'), 0))

    def check(self, result):
        if result == self.XSP3_OK:
            return result
        else:
            raise Exception('SDK Error: %d (%s),\n   the last error is: "%s"' %
                            (result, ERROR_LOOKUP[result], self.error()))

    def _parse_headers(self, path):
        with open(os.path.join(path, 'xspress3.h'), 'r') as fp:
            for line in fp:
                if line.strip().startswith('#define'):
                    data = line.strip().split()[1:3]
                    if len(data) == 2:
                        var, val = data
                        try:
                            val = eval(val)
                        except:
                            # some things are too advanced, sizeof() for example.
                            # there are also typos in the header, with too many closing
                            # parentheses. take what we get.
                            continue
                        exec('self.%s = %s' % (var, val)) # for future use
                        exec('%s = %s' % (var, val)) # for composite macros

    @property
    def _debounce_flag(self):
        return (((self.debounce)&0xFF)<<16)

    def error(self):
        """
        Get the latest error message.
        """
        return libxspress3.xsp3_get_error_message().decode()

    def close(self):
        """
        Shut down.
        """
        self.check(libxspress3.xsp3_close(self.handle))

    @property
    def revision(self):
        """
        Firmware revision.
        """
        return libxspress3.xsp3_get_revision(self.handle)

    @property
    def num_chan(self):
        """
        The number of channels currently configured in the system.
        """
        return libxspress3.xsp3_get_num_chan(self.handle)

    @property
    def bins_per_mca(self):
        """
        The number of bins per MCA configures in the xspress3 system.
        """
        return libxspress3.xsp3_get_bins_per_mca(self.handle)
    
    def acquire_frames(self, frame_time=1., n_frames=1, n_trig=1, trig_mode='software', card=0,):
        """
        Starts the acquisition of internally timed frames.

        frame_time: (float) exposure time plus gap time (which is short)
        n_frames:   (int) how many frames to gather
        n_trig:     (int) how many triggers to expect (equal to 1 or n_frames)
        trig_mode:  (str) 'software', 'rising', or 'gate'
        card:       (int) which card to use
        """

        fit_frames = libxspress3.xsp3_format_run(self.handle, -1, 0, 0, 0, 0, 0, 12)
        print('Can fit %u frames' % fit_frames)
        trig_mode = trig_mode.lower()
        assert trig_mode in ('software', 'rising', 'gate'), 'Invalid trigger mode!'
        self.check(libxspress3.xsp3_histogram_clear(self.handle, 0, self.num_chan, 0, n_frames))
        cycles = ctypes.c_uint32(int((frame_time - self._gap_time) * 80e6)) # time in 80 MHz clock cycles
        if (n_trig != n_frames) and (n_trig != 1):
            raise AttributeError('n_trig must equal 1 or n_frames')
        if trig_mode == 'software':
            if n_trig == 1:
                trg_mode = self.XSP3_ITFG_TRIG_MODE_SOFTWARE_ONLY_FIRST
            elif n_trig == n_frames:
                trg_mode = self.XSP3_ITFG_TRIG_MODE_SOFTWARE
            self.check(libxspress3.xsp3_set_glob_timeA(self.handle, card, self.XSP3_GTIMA_SRC_INTERNAL))
            self.check(libxspress3.xsp3_itfg_setup(self.handle, card, n_frames, cycles, trg_mode, self._gap_mode))
            self.check(libxspress3.xsp3_histogram_arm(self.handle, card)) # the manual says to call arm() here...
        elif trig_mode == 'rising':
            if n_trig == 1:
                trg_mode = self.XSP3_ITFG_TRIG_MODE_HARDWARE_ONLY_FIRST
            elif n_trig == n_frames:
                trg_mode = self.XSP3_ITFG_TRIG_MODE_HARDWARE
            self.check(libxspress3.xsp3_set_glob_timeA(self.handle, card, self.XSP3_GTIMA_SRC_INTERNAL))
            self.check(libxspress3.xsp3_itfg_setup(self.handle, card, n_frames, cycles, trg_mode, self._gap_mode))
            self.check(libxspress3.xsp3_histogram_start(self.handle, card)) # ...and start() here
        elif trig_mode == 'gate':
            # Note: the SDK prescribes putting XSP3_GTIMA_SRC_ flags
            # through the operation ((x)&7), which makes no difference
            # of course so skipping as advance preprocessor macros have
            # to be done manually.
            self.check(libxspress3.xsp3_set_glob_timeA(self.handle, card,
                            self.XSP3_GTIMA_SRC_TTL_VETO_ONLY |
                            self._debounce_flag))
            self.check(libxspress3.xsp3_set_glob_timeFixed(self.handle, card, 0))

    def soft_trigger(self, card=0):
        self.check(libxspress3.xsp3_histogram_continue(self.handle, card))
        self.check(libxspress3.xsp3_histogram_pause(self.handle, card))

    def read_hist_data(self, starting_frame=0, n_frames=None,
                     starting_energy=0, n_energies=None,
                     starting_channel=None, n_channels=None):
        """
        Reads histogram data for some cuboid in the
        (frames, energy bins, channels) space. The default is to
        read everything.
        """
        # we're ignoring aux dimensions per the limitations above
        aux, n_aux = 0, 1
        if n_energies is None:
            n_energies = self.bins_per_mca
        if n_frames is None:
            n_frames = self.nframes_processed
        if n_channels is None:
            n_channels = self.num_chan
        shape = (n_energies, n_channels, n_frames)
        Buff = ctypes.c_uint32 * (np.prod(shape))
        buff = Buff()
        self.check(libxspress3.xsp3_histogram_read3d(self.handle, buff,
                                starting_energy, starting_channel,
                                starting_frame, n_energies,
                                n_channels, n_frames))
        # no memory copied -these calls take 40-50 us for a single
        # frame and 60-70 us for 1000 frames.
        arr = np.frombuffer(buff, dtype=ctypes.c_uint32)
        arr = arr.reshape(shape)
        return arr

    def read_scalars_raw(self, starting_frame, n_frames):
        """
        Reads the scalars and returns the raw flat buffer.
        """
        first_scalar, n_scalars = 0, self.XSP3_SW_NUM_SCALERS
        first_channel, n_channels = 0, self.num_chan
        Buff = ctypes.c_uint32 * (n_scalars * n_channels * n_frames)
        buff = Buff()
        self.check(libxspress3.xsp3_scaler_read(self.handle, buff,
                                first_scalar, first_channel, starting_frame,
                                n_scalars, n_channels, n_frames))
        return buff

    def read_scalar_data(self, starting_frame=0, n_frames=None):
        """
        Reads recorded scalars and returns a reasonably shaped array.
        Indexing goes as (frame, channel, scalar).
        """
        if n_frames is None:
            n_frames = self.nframes_processed
        buff = self.read_scalars_raw(starting_frame, n_frames)
        shape = (n_frames, self.num_chan, self.XSP3_SW_NUM_SCALERS)
        return np.frombuffer(buff, dtype=ctypes.c_uint32).reshape(shape)

    def read_window_data(self, *args, **kwargs):
        """
        Picks out the in-window counter data from the scalars. Gets and
        converts the scalar buffer again, so use read_scalar_data if you
        want to get all the numbers in one go.
        """
        scalars = self.read_scalar_data(*args, **kwargs)
        return scalars[:, :, 5:7]

    def calculate_dtc(self, starting_frame=0, n_frames=None):
        """
        Calculate dead time correction factor and estimated total input counts
        from the acquired scalar values. Indexing goes as (frame, channel). This
        is done on the raw buffer with an SDK call.
        """
        if n_frames is None:
            n_frames = self.nframes_processed
        buff = self.read_scalars_raw(starting_frame, n_frames)
        Array = ctypes.c_double * n_frames * self.num_chan
        dtc_params = Array()
        total_input_counts = Array()
        libxspress3.xsp3_calculateDeadtimeCorrectionFactors(self.handle, buff,
                        dtc_params, total_input_counts, n_frames, 0, self.num_chan)
        dtc = np.frombuffer(dtc_params, dtype=ctypes.c_double).reshape((n_frames, self.num_chan))
        i0 = np.frombuffer(total_input_counts, dtype=ctypes.c_double).reshape((n_frames, self.num_chan))
        return dtc, i0

    def set_window(self, channel=-1, low=0, high=None, window=0):
        """
        Set the hardware in-window counter to integrate over a specific
        energy range. `window` is the counter number (0 or 1). The limits
        are specified in raw energy bins and don't depend on any roi
        settings. If no channel number is given, the setting is applied
        to all channels.
        """
        if high is None:
            high = self.bins_per_mca-1
        self.check(libxspress3.xsp3_set_window(self.handle, channel,
                                    window, low, high))

    def get_window(self, channel, window=0):
        low = ctypes.pointer(ctypes.c_uint32())
        high = ctypes.pointer(ctypes.c_uint32())
        self.check(libxspress3.xsp3_get_window(self.handle, channel,
                                    window, low, high))
        return low.contents.value, high.contents.value

    def stop(self, card=0):
        self.check(libxspress3.xsp3_histogram_stop(self.handle, card))

    def busy(self):
        # something fishy here, xsp3_histogram_is_any_busy never returns 1.
        ret = self.check(libxspress3.xsp3_histogram_is_any_busy(self.handle))
        return bool(ret)

    @property
    def nframes_processed(self):
        return libxspress3.xsp3_scaler_check_progress(0)


if __name__ == '__main__':
    xsp = Xspress3()
    N = 5
    print('taking %u images...'%N)
    xsp.acquire_frames(.1, n_frames=N, n_trig=1)
    xsp.soft_trigger()
    while xsp.nframes_processed < N:
        print('have %u frames...'%xsp.nframes_processed)
        time.sleep(.05)
    print('done! here the data from channel 0...')
    data = xsp.read_hist_data()
    print(data)
    print('shape %s'%(data.shape,))
