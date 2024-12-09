#  kitbash/test/connection_manager.py
#
#  Copyright 2024 liyang <liyang@veronica>
#
import logging, sys
from PyQt5.QtCore import pyqtSlot
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import QApplication, QMainWindow, QShortcut
from kitbash.connection_manager import JackConnectionManager, JackPort


class MainWindow(QMainWindow):

	def __init__(self):
		super().__init__()
		self.quit_shortcut = QShortcut(QKeySequence('Ctrl+Q'), self)
		self.quit_shortcut.activated.connect(self.close)
		self.conn_man = JackConnectionManager()
		self.conn_man.sig_error.connect(self.slot_error)
		self.conn_man.sig_port_reg.connect(self.slot_port_reg)
		self.conn_man.sig_port_connect.connect(self.slot_port_connect)
		self.conn_man.sig_port_rename.connect(self.slot_port_rename)
		self.conn_man.sig_xrun.connect(self.slot_xrun)
		self.conn_man.sig_shutdown.connect(self.slot_shutdown)
		print(self.conn_man.playback_clients())

	@pyqtSlot()
	def slot_error(self, error):
		logging.error(error)

	@pyqtSlot(JackPort, int)
	def slot_port_reg(self, port, action):
		logging.debug('%s %s', port, 'register' if action else 'gone')

	@pyqtSlot(JackPort, JackPort, bool)
	def slot_port_connect(self, port_a, port_b, connect):
		logging.debug('%s port connection: %s -> %s',
			('New' if connect else 'Closed'),
			port_a, port_b)

	@pyqtSlot(JackPort, str, str)
	def slot_port_rename(self, port, old_name, new_name):
		logging.debug('Port %s name changed from "%s" to "%s"', port, old_name, new_name)

	@pyqtSlot()
	def slot_shutdown(self):
		logging.warning('JACK server signalled shutdown')

	@pyqtSlot()
	def slot_xrun(self):
		logging.warning('Xrun')

	def closeEvent(self, event):
		logging.debug('MainWindow close()')
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
