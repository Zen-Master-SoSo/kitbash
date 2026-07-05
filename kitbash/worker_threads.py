#  kitbash/kitbash/worker_threads.py
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
Provides worker threads that load and bash drumkits.
"""
from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot, QRunnable
from sfzen.drumkits import Drumkit


class KitWorkerSignals(QObject):
	"""
	Signals common to KitLoader and KitBasher.
	(PyQt QRunnable does not support its own signals)
	"""
	sig_loaded = pyqtSignal(QObject, Drumkit)
	sig_bashed = pyqtSignal(Drumkit)


class KitLoader(QRunnable):
	"""
	Loads a Drumkit in a background thread.
	"""

	def __init__(self, drumkit_widget):
		super().__init__()
		self.drumkit_widget = drumkit_widget
		self.signals = KitWorkerSignals()

	@pyqtSlot()
	def run(self):
		drumkit = Drumkit(self.drumkit_widget.sfz_filename)
		drumkit.midi_channel = 10 if 'lochan' in drumkit.opcodes_used() else 0
		self.signals.sig_loaded.emit(self.drumkit_widget, drumkit)


class KitBasher(QRunnable):
	"""
	Compiles a bashed kit and signals that its ready to be saved.
	"""

	def __init__(self, drumkit_widgets):
		super().__init__()
		self.drumkit_widgets = drumkit_widgets
		self.signals = KitWorkerSignals()

	@pyqtSlot()
	def run(self):
		bashed_kit = Drumkit()
		for drumkit_widget in self.drumkit_widgets:
			for instrument in drumkit_widget.selected_instruments():
				bashed_kit.import_instrument(instrument)
		self.signals.sig_bashed.emit(bashed_kit)


#  end kitbash/kitbash/worker_threads.py
