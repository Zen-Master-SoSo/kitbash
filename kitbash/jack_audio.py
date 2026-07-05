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
Provides MainWindow of the kitbash application.
"""
import logging	# pylint: disable = unused-import
from tempfile import mkstemp
from os import unlink
from qt_liquid_pool import LiquidPool
from kitbash import get_setting, set_setting, KEY_MIDI_SOURCE, KEY_AUDIO_SINK


class Audio(LiquidPool):
	"""
	Handles audio, including hosting LiquidSFZ instances.
	"""

	def __init__(self):
		super().__init__()
		_, self.tempfile = mkstemp(suffix='.sfz')
		self.kit_synth = None
		self.sig_jack_ready.connect(self.slot_jack_ready)

	def quit(self):
		super().quit()
		unlink(self.tempfile)

	def slot_jack_ready(self, state):
		if state:
			with open(self.tempfile, 'w', encoding = 'utf-8') as fob:
				fob.write('// Empty\n')
			self.kit_synth = self.create_synth(self.tempfile)

	def get_preferred_midi_source(self):
		return get_setting(KEY_MIDI_SOURCE)

	def set_preferred_midi_source(self, value):
		set_setting(KEY_MIDI_SOURCE, value)
		super().set_preferred_midi_source(value)

	def get_preferred_audio_sink(self):
		return get_setting(KEY_AUDIO_SINK)

	def set_preferred_audio_sink(self, value):
		set_setting(KEY_AUDIO_SINK, value)
		super().set_preferred_audio_sink(value)

	def connect_midi_source(self, port):
		"""
		Override in order to prevent all but the main window bashed drumkit synth from
		connecting to the midi source.
		"""
		self.conn_man.connect(port, self.kit_synth.input_port)

	def load_kit(self, drumkit):
		with open(self.tempfile, 'w', encoding = 'utf-8') as fob:
			drumkit.write(fob)
		self.kit_synth.load(self.tempfile)	# pylint: disable = no-member


#  end kitbash/kitbash/jack_audio.py
