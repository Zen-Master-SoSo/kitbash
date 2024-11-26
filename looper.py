#  kitbash/looper.py
#
#  Copyright 2024 liyang <liyang@veronica>
#
import os, logging
from math import ceil
import numpy as np
from jack import Client, CallbackExit
from jack_midi_looper import (
	Looper,
	JackShutdownError,
	DEFAULT_BEATS_PER_MINUTE
)
from kitbash import APPLICATION_NAME


class MultiPortLooper(Looper):
	"""
	Extends jack_midi_looper.Looper. This class creates multiple MIDI ports, and
	parcels out midi "Note On" events to each of them based on a "pitch" value.
	"""
	port_number = 0

	def __init__(self):
		self.client_name = APPLICATION_NAME
		self._bpm = DEFAULT_BEATS_PER_MINUTE
		self.beats_per_measure = None
		self.beat = 0.0
		self.beats_length = 0.0
		self.loops = {} 		# dict containing Loop objects, indexed on loop_id
		self.out_ports = {}		# dict of DrumkitPort, indexed on port_number
		self.pitch_maps	= {		# dict of int (port_number), indexed on pitch
			pitch:None for pitch in range(128)
		}
		self.state = Looper.INACTIVE
		self._real_process_callback = self._null_process_callback
		self.client = Client(self.client_name, no_start_server=True)
		self.client.set_blocksize_callback(self._blocksize_callback)
		self.client.set_samplerate_callback(self._samplerate_callback)
		self.client.set_process_callback(self._process_callback)
		self.client.set_shutdown_callback(self._shutdown_callback)
		self.client.set_xrun_callback(self._xrun_callback)
		self.client.activate()
		self.client.get_ports()

	def add_port(self):
		"""
		Called when adding drumkit. Each drumkit gets its own synth, and this
		MultiPortLooper is connected to each synth via its own port.
		Returns:
			port_number of the newly created port.
		"""
		self.port_number += 1
		self.out_ports[self.port_number] = self.client.midi_outports.register('looper_%d' % self.port_number)
		return self.port_number

	def delete_port(self, port_number):
		"""
		Called when removing drumkit.
		"""
		self.out_ports[port_number].unregister()
		del	self.out_ports[port_number]

	def map_key(self, pitch, port_number):
		"""
		Send "Note On" events with the given pitch to the given port number.
		"""
		self.pitch_maps[pitch] = port_number

	def unmap_key(self, pitch):
		"""
		Prevent sending "Note On" events with the given pitch to any port.
		"""
		self.pitch_maps[pitch] = None

	def _play_process_callback(self, frames):
		if self.any_loop_active():
			for port in self.out_ports.values():
				port.clear_buffer()
			last_beat = self.beat + self.beats_per_process
			while True:
				events_this_block = np.hstack([loop.events_between(self.beat, last_beat) \
					for loop in self.loops.values() if loop.active])
				if len(events_this_block):
					for evt in np.sort(events_this_block, kind="heapsort", order="beat"):
						offset = int((evt['beat'] - self.beat) * self.samples_per_beat)
						port_number = self.pitch_maps[evt['msg'][1]]
						if not port_number is None:
							self.out_ports[port_number].write_midi_event(offset, evt['msg'])
				if last_beat < self.beats_length:
					self.beat = last_beat
					break
				last_beat -= self.beats_length
				self.beat -= self.beats_length


#  end kitbash/looper.py
