#  kitbash/tests/file_save_dialog.py
#
#  Copyright 2025 liyang <liyang@veronica>
#
"""
Test the KitSaveDialog.
"""
import sys
from PyQt5.QtWidgets import QLabel, QPushButton, QMainWindow, QWidget, QVBoxLayout, \
							QApplication, QShortcut
from PyQt5.QtGui import QKeySequence
from sfzen import	SAMPLES_ABSPATH, SAMPLES_RESOLVE, SAMPLES_COPY, \
					SAMPLES_SYMLINK, SAMPLES_HARDLINK
from kitbash.gui.main_window import KitSaveDialog


class TestWindow(QMainWindow):
	"""
	Window used for testing KitSaveDialog.
	"""

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
		dlg = KitSaveDialog(self, SAMPLES_SYMLINK)
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
