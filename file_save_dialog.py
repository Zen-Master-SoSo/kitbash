#  kitbash/file_save_dialog.py
#
#  Copyright 2024 liyang <liyang@veronica>
import sys
from functools import partial
from PyQt5.QtCore import Qt, QCoreApplication, pyqtSlot
from PyQt5.QtWidgets import QFileDialog, QLabel, QPushButton, QMainWindow, QWidget, QVBoxLayout, \
							QApplication, QShortcut, QGroupBox, QRadioButton
from PyQt5.QtGui import QKeySequence
from kitbash import 		settings, \
							SAMPLES_ABSPATH, SAMPLES_RESOLVE, SAMPLES_COPY, \
							SAMPLES_SYMLINK, SAMPLES_HARDLINK


class FileSaveDialog(QFileDialog):

	def __init__(self, parent):
		QCoreApplication.setAttribute(Qt.AA_DontUseNativeDialogs)
		super().__init__(parent)
		self.setWindowTitle("Save as .sfz")
		self.setFileMode(QFileDialog.AnyFile)
		self.setViewMode(QFileDialog.List)
		lbl = QLabel()
		self.layout().addWidget(lbl)
		gb = QGroupBox('Sample location')
		self.r_abspath = QRadioButton('Point to the original samples - absolute path')
		self.r_resolve = QRadioButton('Point to the original samples - relative')
		self.r_copy = QRadioButton('Copy to a new "./samples" folder')
		self.r_symlink = QRadioButton('Create symlinks in a new "./samples" folder')
		self.r_hardlink = QRadioButton('Hardlink the originals in a new "./samples" folder')
		self.r_abspath.clicked.connect(partial(self.slot_set_mode, SAMPLES_ABSPATH))
		self.r_resolve.clicked.connect(partial(self.slot_set_mode, SAMPLES_RESOLVE))
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
		self.samples_mode = int(settings().value("save_as_samples_mode", SAMPLES_HARDLINK))
		if self.samples_mode == SAMPLES_ABSPATH:
			self.r_abspath.setChecked(True)
		elif self.samples_mode == SAMPLES_RESOLVE:
			self.r_resolve.setChecked(True)
		elif self.samples_mode == SAMPLES_COPY:
			self.r_copy.setChecked(True)
		elif self.samples_mode == SAMPLES_SYMLINK:
			self.r_symlink.setChecked(True)
		else:
			self.r_hardlink.setChecked(True)
		self.layout().addWidget(gb)

	@pyqtSlot(int, bool)
	def slot_set_mode(self, mode, state):
		self.samples_mode = mode

	def accept(self):
		settings().setValue("save_as_samples_mode", self.samples_mode)
		selected_files = self.selectedFiles()
		self.selected_file = selected_files[0] if selected_files else None
		super().accept()


class TestWindow(QMainWindow):

	def __init__(self):
		super().__init__()
		self.quit_shortcut = QShortcut(QKeySequence('Esc'), self)
		self.quit_shortcut.activated.connect(self.close)
		central_widget = QWidget()
		self.setCentralWidget(central_widget)
		layout = QVBoxLayout()
		self.label = QLabel("Selected path will be displayed here")
		layout.addWidget(self.label)
		self.mode_label = QLabel("Selected sample mode will be displayed here")
		layout.addWidget(self.mode_label)
		self.open_file_button = QPushButton("Open File Dialog")
		self.open_file_button.clicked.connect(self.open_file_dialog)
		layout.addWidget(self.open_file_button)
		central_widget.setLayout(layout)
		self.setWindowTitle("File Dialog Example")

	def open_file_dialog(self):
		dlg = FileSaveDialog(self)
		if dlg.exec_():
			if dlg.selected_file:
				self.label.setText(f"Selected file: {dlg.selected_file}")
				if dlg.samples_mode == SAMPLES_ABSPATH:
					self.mode_label.setText('Point to the originals (absolute)')
				elif dlg.samples_mode == SAMPLES_RESOLVE:
					self.mode_label.setText('Point to the originals (relative)')
				elif dlg.samples_mode == SAMPLES_COPY:
					self.mode_label.setText('Copy the originals')
				elif dlg.samples_mode == SAMPLES_SYMLINK:
					self.mode_label.setText('Create symlinks to the originals')
				elif dlg.samples_mode == SAMPLES_HARDLINK:
					self.mode_label.setText('Hardlink the originals')
			else:
				self.label.setText("No files selected")


if __name__ == '__main__':
	app = QApplication(sys.argv)
	ex = TestWindow()
	ex.show()
	sys.exit(app.exec_())


#  end kitbash/file_save_dialog.py
