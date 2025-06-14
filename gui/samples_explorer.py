#  kitbash/gui/samples_explorer.py
#
#  Copyright 2025 liyang <liyang@veronica>
#
import os, sys, logging
#import filecmp

from PyQt5 import 			uic
from PyQt5.QtCore import	Qt, pyqtSlot, QDir, QModelIndex
from PyQt5.QtGui import		QColor, QIcon
from PyQt5.QtWidgets import	QDialog, QListWidgetItem, QFileSystemModel

import soundfile as sf
from jack_audio_player import JackAudioPlayer
from qt_extras import ShutUpQT

from kitbash import	settings, set_application_style, \
					KEY_SAMPLE_XPLORE_ROOT, KEY_SAMPLE_XPLORE_CURR
from kitbash.drumkit import Drumkit
from kitbash.gui import GeometrySaver


class SamplesExplorer(QDialog, GeometrySaver):

	def __init__(self, parent):
		super().__init__(parent)
		with ShutUpQT():
			uic.loadUi(os.path.join(os.path.dirname(__file__), 'samples_explorer.ui'), self)
		self.restore_geometry()
		self.finished.connect(self.save_geometry)
		self.player = JackAudioPlayer()
		self.current_drumkit = None
		root_path = settings().value(KEY_SAMPLE_XPLORE_ROOT, QDir.homePath())
		current_path = settings().value(KEY_SAMPLE_XPLORE_CURR, QDir.homePath())
		self.lbl_selection.setText(current_path)
		self.directory_model = QFileSystemModel()
		self.directory_model.setRootPath(root_path)
		self.directory_model.setNameFilters(['*.sfz'])
		self.tree_files.setModel(self.directory_model)
		self.tree_files.hideColumn(1)
		self.tree_files.hideColumn(2)
		self.tree_files.hideColumn(3)
		self.tree_files.setRootIndex(self.directory_model.index(root_path))
		index = self.directory_model.index(current_path)
		self.tree_files.setCurrentIndex(index)
		self.tree_files.scrollTo(index, 1)
		self.tree_files.selectionModel().currentChanged.connect(self.slot_tree_current_changed)
		self.lst_instruments.currentItemChanged.connect(self.slot_inst_current_changed)
		self.lst_samples.itemPressed.connect(self.slot_sample_pressed)

	@pyqtSlot(QModelIndex)
	def slot_tree_current_changed(self, index):
		path = self.directory_model.filePath(index)
		self.lbl_selection.setText(path)
		if self.directory_model.isDir(index):
			settings().setValue(KEY_SAMPLE_XPLORE_CURR, path)
		else:
			self.current_drumkit = Drumkit(path)
			self.lst_instruments.clear()
			self.lst_samples.clear()
			for inst in self.current_drumkit.instruments():
				list_item = QListWidgetItem(self.lst_instruments)
				list_item.setText(inst.name)
				list_item.setData(Qt.UserRole, inst)

	@pyqtSlot(QListWidgetItem, QListWidgetItem)
	def slot_inst_current_changed(self, list_item, previous):
		if list_item:
			inst = list_item.data(Qt.UserRole)
			self.lst_samples.clear()
			for sample in inst.samples():
				list_item = QListWidgetItem(self.lst_samples)
				list_item.setText(sample.basename)
				soundfile = sf.SoundFile(sample.abspath)
				list_item.setData(Qt.UserRole, soundfile)
				if soundfile.samplerate != self.player.client.samplerate:
					list_item.setIcon(QIcon.fromTheme('dialog-warning'))

	@pyqtSlot(QListWidgetItem)
	def slot_sample_pressed(self, list_item):
		soundfile = list_item.data(Qt.UserRole)
		self.player.play_python_soundfile(soundfile)

if __name__ == "__main__":
	from PyQt5.QtWidgets import QApplication
	logging.basicConfig(
		stream = sys.stdout,
		level = logging.DEBUG,
		format = "[%(filename)24s:%(lineno)-4d] %(levelname)-8s %(message)s"
	)
	app = QApplication([])
	set_application_style()
	dialog = SamplesExplorer(None)
	dialog.exec_()


#  end kitbash/gui/samples_explorer.py
