#  kitbash/liquid.py
#
#  Copyright 2024 liyang <liyang@veronica>
#
"""
Provides LiquidSFZ class
"""
from simple_carla.qt import CarlaQt, QtPlugin

class LiquidSFZ(QtPlugin):
	"""
	Encapsulates Liquid SFZ plugin for carla, via the simple_carla object-oriented
	interface.
	"""

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
		"""
		Called by Carla after plugin added to its engine.
		"""
		CarlaQt.instance.autoload(self, self._filename, self.auto_load_complete)

	def auto_load_complete(self):
		"""
		Called by Carla after filename passed to plugin.
		"""
		self.initialized = True
		self.check_ports_ready()


#  end kitbash/liquid.py
