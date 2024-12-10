#  kitbash/synth.py
#
#  Copyright 2024 liyang <liyang@veronica>
#
"""
Provides Synth class
"""
from collections import deque
from liquiphy import LiquidSFZ
from PyQt5.QtCore import (
	pyqtSignal,
	pyqtSlot,
	QObject
)

class Synth(QObject):
	"""
	The purpose of this class is to allow for loading and registration of LiquidSFZ
	instances to happen in such a way that the Jack client / port registration
	callbacks are always associated with the correct synth.
	"""

	sig_ready = pyqtSignal()
	queue = deque()
	midi_in_port = None
	audio_outs = []
	_liquid = None

	def __init__(self):
		Synth.queue.append(self)
		super().__init__()

	def load(self, filename):
		if self._liquid is None:
			self._liquid = LiquidSFZ(filename)
		else:
			self._liquid.load(filename)

	@classmethod
	def port_registered(cls, port):
		synth = cls.queue[0]
		if port.is_input and port.is_midi:
			synth.midi_in_port = port
		elif port.is_output and port.is_audio:
			synth.audio_outs.append(port)
		else:
			logging.warning('Incorrect port type: %s', port)
		if len(synth.audio_outs) == 2 and not synth.midi_in_port is None:
			cls.queue.popleft()
			synth.sig_ready.emit()

	def quit(self):
		if self._liquid:
			self._liquid.quit()


#  end kitbash/synth.py
