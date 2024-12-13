#  kitbash/looper.py
#
#  Copyright 2024 liyang <liyang@veronica>
#
import logging
import numpy as np
from jack import Client
from PyQt5.QtCore import QObject
from PyQt5.QtCore import pyqtSignal
from jack_midi_looper import Looper
from kitbash import (
	LOOPER_CLIENT_NAME,
	LOOPER_PORT_FORMAT,
	LOOPER_BASHED_PORT
)

class KitbashLooper(Looper):
	"""
	Extends jack_midi_looper.Looper. This class creates multiple MIDI ports, and
	parcels out midi "Note On" events to each of them based on a "pitch" value.
	"""
	port_number = 0

	def __init__(self):
		super().__init__(LOOPER_CLIENT_NAME)
		self.signals = LooperSignals()

	def create_client(self):
		self.client = Client(self.client_name, no_start_server=True)
		self.client.set_blocksize_callback(self._blocksize_callback)
		self.client.set_samplerate_callback(self._samplerate_callback)
		self.client.set_process_callback(self._process_callback)
		self.client.set_shutdown_callback(self._shutdown_callback)
		self.client.activate()
		logging.debug('Looper client "%s" created', self.client.name)
		self.client.get_ports()
		self.bashed_port = self.client.midi_outports.register(LOOPER_BASHED_PORT)
		self.bashed_exclusive = False
		self.out_ports = {}		# dict of DrumkitPort, indexed on port_number
		self.pitch_maps	= {		# dict of int (port_number), indexed on pitch
			pitch:None for pitch in range(128)
		}

	def add_port(self):
		"""
		Called when adding drumkit. Each drumkit gets its own synth, and this
		KitbashLooper is connected to each synth via its own port.

		Returns:
			port_number:	(int) id number of the newly created port,
			port_name:		(str) Jack port name, including client (<client>:<port>)
		"""
		self.port_number += 1
		port_name = LOOPER_PORT_FORMAT % self.port_number
		with self.loop_manipulation_lock:
			self.out_ports[self.port_number] = self.client.midi_outports.register(port_name)
		return self.port_number, '%s:%s' % (self.client.name, port_name)

	def delete_port(self, port_number):
		"""
		Called when removing drumkit.

		"port_number" is the number assigned to the port when added.
		"""
		with self.loop_manipulation_lock:
			self.out_ports[port_number].unregister()
			for k,v in self.pitch_maps.items():
				if v == port_number:
					self.pitch_maps[k] = None
			del	self.out_ports[port_number]

	def set_mapping(self, pitch, port_number):
		"""
		Map the given port_number to the given pitch, so that MIDI "Note On" events
		with the given pitch are sent to the port identified by the the given
		port_number. If port_number is None, MIDI "Note On" events with the given pitch
		are not sent anywhere.
		"""
		self.pitch_maps[pitch] = port_number

	def _play_process_callback(self, frames):
		self._clear_buffers()
		if self.any_loop_active() and not self.loop_manipulation_lock.locked():
			last_beat = self.beat + self.beats_per_process
			while True:
				events_this_block = np.hstack([loop.events_between(self.beat, last_beat) \
					for loop in self.loops.values() if loop.active])
				if len(events_this_block):
					for evt in np.sort(events_this_block, kind="heapsort", order="beat"):
						offset = int((evt['beat'] - self.beat) * self.samples_per_beat)
						if self.bashed_exclusive:
							self.bashed_port.write_midi_event(offset, evt['msg'])
						else:
							port_number = self.pitch_maps[evt['msg'][1]]
							if not port_number is None:
								self.out_ports[port_number].write_midi_event(offset, evt['msg'])
				if last_beat < self.beats_length:
					self.beat = last_beat
					break
				last_beat -= self.beats_length
				self.beat -= self.beats_length

	def _stop_process_callback(self, frames):
		"""
		Sends MIDI message "All Notes Off" (0x7B) to all channels from 0 - 15,
		and then transitions to "_null_process_callback".
		Overrides Looper._stop_process_callback to send note off to every port.
		"""
		self._clear_buffers()
		msg = bytearray.fromhex('B07B')
		for channel in range(16):
			self.bashed_port.write_midi_event(0, msg)
			for port in self.out_ports.values():
				port.write_midi_event(0, msg)
			msg[0] += 1
		self.beat = 0.0
		self._real_process_callback = self._null_process_callback
		self.stop_event.set()

	def _clear_buffers(self):
		self.bashed_port.clear_buffer()
		for port in self.out_ports.values():
			port.clear_buffer()

	def stop(self):
		super().stop()
		self.signals.sig_state_changed.emit(False)

	def play(self):
		super().play()
		self.signals.sig_state_changed.emit(True)


class LooperSignals(QObject):

	sig_state_changed = pyqtSignal(bool)


#  end kitbash/looper.py
