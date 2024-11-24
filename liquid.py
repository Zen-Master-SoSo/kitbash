#  kitbash/liquid.py
#
#  Copyright 2024 liyang <liyang@veronica>
#
import logging
from PyQt5.QtCore import pyqtSignal
from simple_carla.qt import CarlaQt, QtPlugin
from kitbash.sfz import SFZ

class LiquidSFZ(QtPlugin):

	sig_MIDIActiveChanged = pyqtSignal(bool)

	plugin_def = {
		'build': 2,
		'type': 4,		# PLUGIN_LV2
		'filename': 'liquidsfz.lv2',
		'name': 'liquidsfz',
		'label': 'http://spectmorph.org/plugins/liquidsfz',
		'uniqueId': None
	}

	def __init__(self, filename):
		self._filename = filename
		super().__init__()

	def finalize_init(self):
		CarlaQt.instance.autoload(self, self._filename, self.auto_load_complete)

	def auto_load_complete(self):
		self.initialized = True
		self.check_ports_ready()

	def midi_active(self, state):
		logging.debug(f"{self} midi_active")
		self.sig_MIDIActiveChanged.emit(state)


#  end kitbash/liquid.py
