#  kitbash/synth.py
#
#  Copyright 2024 liyang <liyang@veronica>
#
"""
Provides Synth class
"""
import logging
from collections import deque
from liquiphy import LiquidSFZ
from PyQt5.QtCore import (
	pyqtSignal,
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

	def __init__(self, moniker):
		"""
		Appends this Synth to the queue BEFORE the LiquidSFZ process is started.
		"""
		Synth.queue.append(self)
		self.moniker = moniker
		self.midi_in_port = None
		self.audio_outs = []
		self._liquid = None
		super().__init__()

	def load(self, filename):
		if self._liquid is None:
			self._liquid = LiquidSFZ(filename)
		else:
			self._liquid.load(filename)

	@classmethod
	def port_registered(cls, port):
		"""
		Function called from MainWindow, in response to ConnectionManager port
		registration callbacks. Populates the ports of the synth at the front of the
		queue. When all ports are accounted for, pops the queue so that the next synth
		can be instantiated.
		"""
		synth = cls.queue[0]
		logging.debug('Synth %s port_registered: %s', synth.moniker, port)
		if port.is_input and port.is_midi:
			synth.midi_in_port = port
		elif port.is_output and port.is_audio:
			synth.audio_outs.append(port)
		else:
			logging.warning('Incorrect port type: %s', port)
		if len(synth.audio_outs) == 2 and not synth.midi_in_port is None:
			logging.debug('Synth %s ports complete - popping Synth.queue', synth.moniker)
			cls.queue.popleft()
			synth.sig_ready.emit()

	def quit(self):
		"""
		Gracefully quits the contained LiquidSFZ instance.
		"""
		if self._liquid:
			self._liquid.quit()


#  end kitbash/synth.py
