#  kitbash/kitbash/gui/kit_save_dialog.py
#
#  Copyright 2025-2026 Leon Dionne <ldionne@dridesign.sh.cn>
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
Provides KitSaveDialog.
"""
import logging
from os.path import realpath, splitext
from functools import partial
from PyQt5.QtCore import Qt, pyqtSlot, QCoreApplication
from PyQt5.QtWidgets import QVBoxLayout, QLabel, QFileDialog, QGroupBox, QRadioButton
from sfzen import (
	SAMPLES_ABSPATH, SAMPLES_RELPATH, SAMPLES_COPY, SAMPLES_SYMLINK, SAMPLES_HARDLINK)
from kitbash import set_setting, GeometrySaver, KEY_SAMPLES_MODE


class KitSaveDialog(QFileDialog, GeometrySaver):
	"""
	Custom file dialog with added option for choosing samples_mode.
	"""

	def __init__(self, parent, samples_mode):
		QCoreApplication.setAttribute(Qt.AA_DontUseNativeDialogs)
		super().__init__(parent)
		self.samples_mode = samples_mode
		self.restore_geometry()
		self.setWindowTitle("Save bashed kit as .sfz")
		self.setFileMode(QFileDialog.AnyFile)
		self.setViewMode(QFileDialog.List)
		lbl = QLabel()
		self.layout().addWidget(lbl)
		gb = QGroupBox('Sample location')
		self.r_abspath = QRadioButton('Point to the original samples - absolute path')
		self.r_resolve = QRadioButton('Point to the original samples - relative path')
		self.r_copy = QRadioButton('Copy samples to the "./samples" folder')
		self.r_symlink = QRadioButton('Create symlinks in the "./samples" folder')
		self.r_hardlink = QRadioButton('Hardlink the originals in the "./samples" folder')
		self.r_abspath.clicked.connect(partial(self.slot_set_mode, SAMPLES_ABSPATH))
		self.r_resolve.clicked.connect(partial(self.slot_set_mode, SAMPLES_RELPATH))
		self.r_copy.clicked.connect(partial(self.slot_set_mode, SAMPLES_COPY))
		self.r_symlink.clicked.connect(partial(self.slot_set_mode, SAMPLES_SYMLINK))
		self.r_hardlink.clicked.connect(partial(self.slot_set_mode, SAMPLES_HARDLINK))
		lo = QVBoxLayout()
		lo.setContentsMargins(2,2,2,2)
		lo.setSpacing(2)
		lo.addWidget(self.r_abspath)
		lo.addWidget(self.r_resolve)
		lo.addWidget(self.r_copy)
		lo.addWidget(self.r_symlink)
		lo.addWidget(self.r_hardlink)
		gb.setLayout(lo)
		if self.samples_mode == SAMPLES_ABSPATH:
			self.r_abspath.setChecked(True)
		elif self.samples_mode == SAMPLES_RELPATH:
			self.r_resolve.setChecked(True)
		elif self.samples_mode == SAMPLES_COPY:
			self.r_copy.setChecked(True)
		elif self.samples_mode == SAMPLES_SYMLINK:
			self.r_symlink.setChecked(True)
		else:
			self.r_hardlink.setChecked(True)
		self.layout().addWidget(gb)
		self.selected_file = None

	@pyqtSlot(int, bool)
	def slot_set_mode(self, mode, _):
		"""
		Tiggered by any sample mode selection radio button.
		"""
		self.samples_mode = mode

	@pyqtSlot()
	def accept(self):
		"""
		Overloaded function saves preferred mode, sets "selected_file".
		"""
		set_setting(KEY_SAMPLES_MODE, self.samples_mode)
		selected_files = self.selectedFiles()
		if selected_files:
			self.selected_file = realpath(
				selected_files[0] \
				if splitext(selected_files[0])[-1].lower() == '.sfz' \
				else selected_files[0] + '.sfz')
		else:
			self.selected_file = None
		super().accept()

	def done(self, result):
		"""
		Overloaded function saves geometry.
		"""
		self.save_geometry()
		super().done(result)



#  end kitbash/kitbash/gui/kit_save_dialog.py
