#  kitbash/test/connection_manager.py
#
#  Copyright 2024 liyang <liyang@veronica>
#
import logging, sys
from PyQt5.QtCore import pyqtSlot
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import QApplication, QMainWindow, QTextEdit, QShortcut
from kitbash.connection_manager import JackConnectionManager, JackPort


class MainWindow(QMainWindow):

	def __init__(self):
		super().__init__()
		self.setMinimumWidth(500)
		shortcut = QShortcut(QKeySequence('Ctrl+Q'), self)
		shortcut.activated.connect(self.close)
		shortcut = QShortcut(QKeySequence('Esc'), self)
		shortcut.activated.connect(self.close)
		self.text_box = QTextEdit(self)
		self.text_box.setReadOnly(True)
		self.setCentralWidget(self.text_box)
		self.conn_man = JackConnectionManager()
		self.conn_man.sig_error.connect(self.slot_error)
		self.conn_man.sig_port_registration.connect(self.slot_port_registration)
		self.conn_man.sig_port_connect.connect(self.slot_port_connect)
		self.conn_man.sig_port_rename.connect(self.slot_port_rename)
		self.conn_man.sig_shutdown.connect(self.slot_shutdown)

	@pyqtSlot()
	def slot_error(self, error):
		self.text_box.insertPlainText(error)

	@pyqtSlot(JackPort, int)
	def slot_port_registration(self, port, action):
		self.text_box.insertPlainText('%s %s\n' % (port, 'register' if action else 'gone'))

	@pyqtSlot(JackPort, JackPort, bool)
	def slot_port_connect(self, port_a, port_b, connect):
		self.text_box.insertPlainText('%s port connection: %s -> %s\n' % (
			('New' if connect else 'Closed'), port_a, port_b))

	@pyqtSlot(JackPort, str, str)
	def slot_port_rename(self, port, old_name, new_name):
		self.text_box.insertPlainText('Port %s name changed from "%s" to "%s"\n' % (port, old_name, new_name))

	@pyqtSlot()
	def slot_shutdown(self):
		self.text_box.insertPlainText('JACK server signalled shutdown\n')

	def closeEvent(self, event):
		self.conn_man.close()
		event.accept()


if __name__ == "__main__":
	logging.basicConfig(
		level=logging.DEBUG,
		format="[%(filename)24s:%(lineno)3d] %(levelname)-8s %(message)s"
	)
	app = QApplication([])
	window = MainWindow()
	window.show()
	sys.exit(app.exec())

#  end kitbash/test/connection_manager.py
