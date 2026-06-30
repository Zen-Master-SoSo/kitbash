#  kitbash/kitbash/jack_audio.py
#
#  Copyright 2026 Leon Dionne <ldionne@dridesign.sh.cn>
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#  MA 02110-1301, USA.
#
"""
Provides MainWindow of the kitstarter application.
"""
import logging, tempfile
from os import unlink
from PyQt5.QtCore import Qt, QObject, pyqtSignal, pyqtSlot, QTimer
from liquiphy import LiquidSFZ
from conn_jack import JackConnectionManager, JackConnectError
from kitstarter import get_setting, set_setting, KEY_MIDI_SOURCE, KEY_AUDIO_SINK


SYNTH_NAME = 'liquidsfz'
AUDIO_PLAYER_CLIENT = 'kitstarter_jack_player'
CONNECT_RETRY_INTERVAL = 1776


class Audio(QObject):
	"""
	Handles audio, including hosting an instance of liquidsfz, and playing samples.
	"""

	sig_ports_complete = pyqtSignal()	# \
	sig_sources_changed = pyqtSignal()	#  Used to decouple JackConnectionManager callbacks
	sig_sinks_changed = pyqtSignal()	# /
	sig_jack_down = pyqtSignal()		#
	sig_jack_ready = pyqtSignal(int)
	sig_midi_connected = pyqtSignal(str)

	def __init__(self):
		super().__init__()
		self.conn_man = None
		self.synth = None
		_, self.tempfile = tempfile.mkstemp(suffix='.sfz')
		self.sig_ports_complete.connect(self.slot_ports_complete, type = Qt.QueuedConnection)
		self.sig_sources_changed.connect(self.slot_sources_changed, type = Qt.QueuedConnection)
		self.sig_sinks_changed.connect(self.slot_sinks_changed, type = Qt.QueuedConnection)
		self.sig_jack_down.connect(self.slot_jack_down, type = Qt.QueuedConnection)
		self.connect_retry_timer = QTimer()
		self.connect_retry_timer.setInterval(CONNECT_RETRY_INTERVAL)
		self.connect_retry_timer.setSingleShot(True)
		self.connect_retry_timer.timeout.connect(self.connect)

	def connect(self):
		try:
			self.conn_man = JackConnectionManager()
		except JackConnectError:
			self.connect_retry_timer.start()
		else:
			self.conn_man.on_error(self.jack_error)
			self.conn_man.on_shutdown(self.jack_shutdown)
			self.conn_man.on_client_registration(self.jack_client_registration)
			self.conn_man.on_port_registration(self.jack_port_registration)
			self.synth = JackLiquidSFZ(self.tempfile)
			self.sig_jack_ready.emit(self.conn_man.samplerate)
			self.synth.start()

	def quit(self):
		if self.synth and hasattr(self.synth, 'quit'):
			self.synth.ports_ready = False
			self.synth.quit()	# pylint: disable = no-member
		unlink(self.tempfile)

	# -----------------------------------------------------------------
	# JACK callbacks

	def jack_client_registration(self, client_name, action):
		if action and not self.synth.client_name and client_name.startswith(SYNTH_NAME):
			self.synth.client_name = client_name

	def jack_port_registration(self, port, action):
		if action and self.synth.client_name and port.name.startswith(self.synth.client_name + ':'):
			if port.is_input and port.is_midi:
				self.synth.input_port = port
			elif port.is_output and port.is_audio:
				self.synth.output_ports.append(port)
			if self.synth.input_port and len(self.synth.output_ports) == 2:
				self.synth.ports_ready = True
				self.sig_ports_complete.emit()
		if port.is_input:
			self.sig_sinks_changed.emit()
		else:
			self.sig_sources_changed.emit()

	def jack_error(self, error_message):
		logging.error('JACK ERROR: "%s"', error_message)

	def jack_shutdown(self):
		logging.warning('JACK is shutting down')
		self.sig_jack_down.emit()

	@pyqtSlot()
	def slot_jack_down(self):
		"""
		Triggered by sig_jack_down emitted from another thread in "jack_shutdown"
		"""
		self.conn_man.close()
		self.conn_man = None
		self.connect_retry_timer.start()

	# -----------------------------------------------------------------
	# Source / sink management

	@pyqtSlot()
	def slot_ports_complete(self):
		"""
		Triggered by sig_ports_complete, emitted in "jack_port_registration".
		"""
		self.connect_midi_source()
		self.connect_audio_sinks()

	@pyqtSlot(str)
	def slot_midi_src_selected(self, value):
		"""
		Triggered from combo box selection
		"""
		self.midi_src = value

	@pyqtSlot(str)
	def slot_audio_sink_selected(self, value):
		"""
		Triggered from combo box selection
		"""
		self.audio_sink = value

	@pyqtSlot()
	def slot_sources_changed(self):
		"""
		Triggered by sig_sources_changed, emitted in "jack_port_registration".
		"""
		if self.synth.ports_ready:
			self.connect_midi_source()

	@pyqtSlot()
	def slot_sinks_changed(self):
		"""
		Triggered by sig_sinks_changed, emitted in "jack_port_registration".
		"""
		if self.synth.ports_ready:
			self.connect_audio_sinks()

	@property
	def midi_src(self):
		return get_setting(KEY_MIDI_SOURCE)

	@midi_src.setter
	def midi_src(self, value):
		set_setting(KEY_MIDI_SOURCE, value)
		self.connect_midi_source()

	@property
	def audio_sink(self):
		return get_setting(KEY_AUDIO_SINK)

	@audio_sink.setter
	def audio_sink(self, value):
		set_setting(KEY_AUDIO_SINK, value)
		self.connect_audio_sinks()

	def connect_midi_source(self):
		if self.synth and self.synth.ports_ready:
			# Look for source port if midi_src has a str value:
			if self.midi_src:
				src_port = self.conn_man.get_port_by_name(self.midi_src)
				# No need to disconnect / reconnect if they are equal:
				if src_port == self.synth.connected_midi_src_port:
					return
			else:
				src_port = None
			# Disconnect existing:
			if self.synth.connected_midi_src_port:
				self.conn_man.disconnect(self.synth.connected_midi_src_port, self.synth.input_port)
			# Connect if midi_src has a str value:
			if src_port:
				self.conn_man.connect(src_port, self.synth.input_port)
				self.sig_midi_connected.emit(src_port.name)
			# Update connected port (may be none):
			self.synth.connected_midi_src_port = src_port

	def connect_audio_sinks(self):
		if self.synth and self.synth.ports_ready:
			# Look for target ports if audio_sink has a str value:
			if self.audio_sink:
				tgt_ports = [ port for port in self.conn_man.get_client_ports(self.audio_sink)
					if port.is_audio and port.is_input ]
				# No need to disconnect / reconnect if they are equal:
				if tgt_ports == self.synth.connected_audio_sink_ports:
					return
			else:
				tgt_ports = []
			# Disconnect existing:
			if self.synth.connected_audio_sink_ports:
				for src, tgt in zip(
					self.synth.output_ports, self.synth.connected_audio_sink_ports):
					self.conn_man.disconnect(src, tgt)
			# Connect if audio_sink has a str value:
			if tgt_ports:
				for src, tgt in zip(self.synth.output_ports, tgt_ports):
					self.conn_man.connect(src, tgt)
			# Update connected ports (may be none):
			self.synth.connected_audio_sink_ports = tgt_ports

	def load_kit(self, kit):
		with open(self.tempfile, 'w', encoding = 'utf-8') as fob:
			kit.write(fob)
		self.synth.load(self.tempfile)	# pylint: disable = no-member


class JackLiquidSFZ(LiquidSFZ):
	"""
	Wraps a LiquidSFZ instance in order to hold references to jacklib ports created
	by JackConnectionManager.
	"""

	def __init__(self, filename):
		self.client_name = None
		self.ports_ready = False
		self.input_port = None
		self.output_ports = []
		self.connected_midi_src_port = None
		self.connected_audio_sink_ports = []
		super().__init__(filename, defer_start = True)


#  end kitbash/kitbash/jack_audio.py
