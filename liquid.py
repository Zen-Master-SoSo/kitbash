#  kitbash/liquid.py
#
#  Copyright 2024 liyang <liyang@veronica>
#
from PyQt5.QtCore import pyqtSignal
from simple_carla.qt import CarlaQt, QtPlugin
from kitbash.sfz import SFZ

class LiquidSFZ(QtPlugin):

	sig_SFZLoaded = pyqtSignal(SFZ)
	sig_MIDIActiveChanged = pyqtSignal(bool)

	def __init__(self, port, slot, sfz, saved_state=None):
		self.port = port
		self.slot = slot
		self.sfz = sfz
		super().__init__({
			'build': 2,
			'type': 4,		# PLUGIN_LV2
			'filename': 'liquidsfz.lv2',
			'name': 'liquidsfz',
			'label': 'http://spectmorph.org/plugins/liquidsfz',
			'uniqueId': None
		}, saved_state)

	def finalize_init(self):
		self.load_sfz()

	def change_sfz(self, sfz):
		self.sfz = sfz
		self.load_sfz()

	def load_sfz(self):
		CarlaQt.instance.autoload(self, self.sfz.filename, self.auto_load_complete)

	def auto_load_complete(self):
		self.sig_SFZLoaded.emit(self.sfz)
		self.initialized = True
		self.check_ports_ready()

	def midi_active(self, state):
		self.sig_MIDIActiveChanged.emit(state)


#  end kitbash/liquid.py
