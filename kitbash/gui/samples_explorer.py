#  kitbash/gui/samples_explorer.py
#
#  Copyright 2025 liyang <liyang@veronica>
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
import os, sys, logging
from functools import lru_cache

from PyQt5 import 			uic
from PyQt5.QtCore import	Qt, pyqtSlot, QPoint, QDir, QItemSelection
from PyQt5.QtGui import		QIcon
from PyQt5.QtWidgets import	QDialog, QListWidget, QListWidgetItem, QFileSystemModel, \
							QMenu, QApplication

import soundfile as sf
from midi_notes import MIDI_DRUM_NAMES, MIDI_DRUM_IDS
from jack import JackError
from jack_audio_player import JackAudioPlayer
from qt_extras import ShutUpQT
from sfzen.drumkits import Drumkit

from kitbash import	settings, set_application_style, \
					KEY_SAMPLE_XPLORE_ROOT, KEY_SAMPLE_XPLORE_CURR
from kitbash.gui import GeometrySaver


class SamplesExplorer(QDialog, GeometrySaver):

	def __init__(self, parent):
		super().__init__(parent)
		with ShutUpQT():
			uic.loadUi(os.path.join(os.path.dirname(__file__), 'samples_explorer.ui'), self)
		self.restore_geometry()
		self.finished.connect(self.save_geometry)
		self.audio_player = JackAudioPlayer()
		root_path = settings().value(KEY_SAMPLE_XPLORE_ROOT, QDir.homePath())
		current_path = settings().value(KEY_SAMPLE_XPLORE_CURR, QDir.homePath())
		self.files_model = QFileSystemModel()
		self.files_model.setRootPath(root_path)
		self.files_model.setNameFilters(['*.sfz'])
		self.tree_files.setModel(self.files_model)
		self.tree_files.hideColumn(1)
		self.tree_files.hideColumn(2)
		self.tree_files.hideColumn(3)
		self.tree_files.setRootIndex(self.files_model.index(root_path))
		index = self.files_model.index(current_path)
		self.tree_files.setCurrentIndex(index)
		self.tree_files.scrollTo(index, 1)
		for pitch, inst_id in MIDI_DRUM_IDS.items():
			list_item = QListWidgetItem(self.lst_instruments)
			list_item.setData(Qt.UserRole, inst_id)
			list_item.setText(MIDI_DRUM_NAMES[pitch])
		self.instrument_list_ids = [
			list_item.data(Qt.UserRole) \
			for list_item in self.iterate_instrument_list()
		]
		self.instrument_list_drumkit_paths = [
			[] for row in range(self.lst_instruments.count())
		]
		self.reset_instrument_selections()
		# Connect signals
		self.tree_files.selectionModel().selectionChanged.connect(self.slot_tree_selection_changed)
		self.tree_files.setContextMenuPolicy(Qt.CustomContextMenu)
		self.tree_files.customContextMenuRequested.connect(self.slot_files_context_menu)
		self.lst_instruments.currentItemChanged.connect(self.slot_inst_current_changed)
		self.lst_samples.itemPressed.connect(self.slot_sample_pressed)
		self.lst_samples.mouseReleaseEvent = self.samples_mouse_release
		self.lst_samples.setContextMenuPolicy(Qt.CustomContextMenu)
		self.lst_samples.customContextMenuRequested.connect(self.slot_samples_context_menu)
		# Populate samples, if applicable
		#self.slot_tree_selection_changed(index)

	def iterate_instrument_list(self):
		for row in range(self.lst_instruments.count()):
			yield self.lst_instruments.item(row)

	@lru_cache
	def drumkit(self, path):
		return Drumkit(path)

	@pyqtSlot(QPoint)
	def slot_files_context_menu(self, position):
		indexes = self.tree_files.selectedIndexes()
		if len(indexes):
			menu = QMenu(self)
			menu.addAction('Copy path' if len(indexes) == 1 else 'Copy paths')
			if menu.exec(self.tree_files.mapToGlobal(position)):
				QApplication.instance().clipboard().setText("\n".join(
					self.files_model.filePath(index) for index in indexes
				))

	def reset_instrument_selections(self):
		for row in range(self.lst_instruments.count()):
			self.lst_instruments.item(row).setFlags(Qt.NoItemFlags)
			self.instrument_list_drumkit_paths[row] = []

	@pyqtSlot(QItemSelection, QItemSelection)
	def slot_tree_selection_changed(self, *_):
		QApplication.setOverrideCursor(Qt.WaitCursor)
		self.lst_samples.clear()
		self.reset_instrument_selections()
		indexes = self.tree_files.selectedIndexes()
		for index in indexes:
			path = self.files_model.filePath(index)
			if self.files_model.isDir(index):
				settings().setValue(KEY_SAMPLE_XPLORE_CURR, path)
			else:
				settings().setValue(KEY_SAMPLE_XPLORE_CURR, os.path.dirname(path))
				for inst in self.drumkit(path).instruments():
					row = self.instrument_list_ids.index(inst.inst_id)
					self.instrument_list_drumkit_paths[row].append(path)
					self.lst_instruments.item(row).setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
		selected_items = self.lst_instruments.selectedItems()
		if len(selected_items):
			self.populate_samples(selected_items.pop())
		QApplication.restoreOverrideCursor()

	@pyqtSlot(QListWidgetItem, QListWidgetItem)
	def slot_inst_current_changed(self, list_item, _):
		if list_item:
			self.populate_samples(list_item)

	def populate_samples(self, list_item):
		self.lst_samples.clear()
		inst_id = list_item.data(Qt.UserRole)
		row = self.lst_instruments.row(list_item)
		for path in self.instrument_list_drumkit_paths[row]:
			for sample in self.drumkit(path).instrument(inst_id).samples():
				existing_items = self.lst_samples.findItems(sample.basename, Qt.MatchExactly)
				if len(existing_items):
					for existing_item in existing_items:
						if existing_item.data(Qt.UserRole).name == sample.abspath:
							return
				list_item = QListWidgetItem(self.lst_samples)
				list_item.setText(sample.basename)
				soundfile = sf.SoundFile(sample.abspath)
				list_item.setData(Qt.UserRole, soundfile)
				s_samp = soundfile.name + \
					f'\nThis file has a sample rate of {soundfile.samplerate} Hz,\n'
				if soundfile.samplerate != self.audio_player.client.samplerate:
					list_item.setIcon(QIcon.fromTheme('face-sad'))
					list_item.setToolTip(s_samp + \
						f'while the JACK server is running at {self.audio_player.client.samplerate} Hz')
				else:
					list_item.setIcon(QIcon.fromTheme('face-cool'))
					list_item.setToolTip(s_samp + 'the same as the JACK server')

	@pyqtSlot(QPoint)
	def slot_samples_context_menu(self, position):
		list_item = self.lst_samples.currentItem()
		if list_item is not None:
			menu = QMenu(self)
			menu.addAction('Copy path')
			if menu.exec(self.lst_samples.mapToGlobal(position)):
				QApplication.instance().clipboard().setText(list_item.data(Qt.UserRole).name)

	@pyqtSlot(QListWidgetItem)
	def slot_sample_pressed(self, list_item):
		if QApplication.mouseButtons() == Qt.LeftButton:
			soundfile = list_item.data(Qt.UserRole)
			soundfile.seek(0)
			self.audio_player.play_python_soundfile(soundfile)

	def samples_mouse_release(self, event):
		self.audio_player.stop()
		super(QListWidget, self.lst_samples).mouseReleaseEvent(event)


if __name__ == "__main__":
	logging.basicConfig(
		level = logging.DEBUG,
		format = "[%(filename)24s:%(lineno)-4d] %(levelname)-8s %(message)s"
	)
	app = QApplication([])
	set_application_style()
	try:
		dialog = SamplesExplorer(None)
	except JackError as err:
		print('Could not connect to JACK server. Is it running?')
		sys.exit(1)
	else:
		dialog.exec_()
		sys.exit(0)


#  end kitbash/gui/samples_explorer.py
