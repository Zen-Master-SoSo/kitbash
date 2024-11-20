#  kitbash/looper.py
#
#  Copyright 2024 liyang <liyang@veronica>
#
import numpy as np
from jack import Client, Port, Status, JackError, CallbackExit, STOPPED, ROLLING, STARTING, NETSTARTING
from PyQt5.QtWidgets import QMainWindow
from PyQt5.QtCore import pyqtSlot
from kitbash.loops import Loop


class Looper:

	# state constants:
	INACTIVE	= 0
	PLAYING		= 1

	def __init__(self, bpm=120, client_name='looper'):
		self.bpm = bpm
		self.loops = []
		self.beats_per_measure = None
		self.beats_length = None
		self.__real_process_callback = self.null_process_callback
		self.client_name = client_name
		self.client = Client(self.client_name, no_start_server=True)
		self.client.set_blocksize_callback(self.blocksize_callback)
		self.client.set_samplerate_callback(self.samplerate_callback)
		self.client.set_process_callback(self.process_callback)
		self.client.set_shutdown_callback(self.shutdown_callback)
		self.client.set_xrun_callback(self.xrun_callback)
		self.client.activate()
		self.client.get_ports()
		self.out_port = self.client.midi_outports.register('out')

	def add_loop(self, loop, starting_beat=0):
		assert(isinstance(loop, Loop))
		if self.beats_per_measure is None:
			self.beats_per_measure = loop.beats_per_measure
		elif loop.beats_per_measure != self.beats_per_measure:
			raise Exception("beats_per_measure mismatch")
		self.loops.append(loop)
		self.scale_loops()
		self.beats_length = max([loop.beats_length for loop in self.loops])

	def scale_loops(self):
		for loop in self.loops:
			loop.scale(self.bpm, self.client.samplerate)

	def stop(self):
		logging.debug('STOP')
		self.__real_process_callback = self.null_process_callback
		self.state = self.INACTIVE

	def play(self):
		logging.debug('PLAY')
		for loop in self.loops:
			loop.reset_iteration()
		self.__frame = 0
		self.__real_process_callback = self.play_process_callback
		self.state = self.PLAYING

	def null_process_callback(self, frames):
		pass

	def play_process_callback(self, frames):
		self.out_port.clear_buffer()
		for loop in self.loops:
			while self.__frame == self.buffers[loop][self.buf_idx[loop]]['frame']:
				self.out_port.write_midi_event(self.buffers[loop][self.buf_idx[loop]]['offset'], self.buffers[loop][self.buf_idx[loop]]['data'])
				self.buf_idx[loop] += 1
		self.__frame += 1

	# -----------------------
	# JACK callbacks

	def blocksize_callback(self, blocksize):
		self.scale_loops()

	def samplerate_callback(self, samplerate):
		self.scale_loops()

	def process_callback(self, frames):
		try:
			self.__real_process_callback(frames)
		except Exception as e:
			logging.error(e)
			raise CallbackExit

	def shutdown_callback(self, status, reason):
		"""
		The argument status is of type jack.Status.
		"""
		if self.state != self.INACTIVE:
			self.stop_everything()
			raise JackShutdownError

	def xrun_callback(self, delayed_usecs):
		"""
		The callback argument is the delay in microseconds due to the most recent XRUN
		occurrence. The callback is supposed to raise CallbackExit on error.
		"""
		#logging.debug('xrun: delayed %.2f microseconds' % delayed_usecs)
		pass


class JackShutdownError(Exception):

	pass



class LooperTestWindow(QMainWindow):

	def __init__(self, options):
		super().__init__()
		self._options = options
		self.loop_button = QPushButton(self)
		self.loop_button.setText('PLAY')
		self.loop_button.setCheckable(True)
		self.loop_button.toggled.connect(self.play_toggle)
		self.setCentralWidget(self.loop_button)
		self.quit_shortcut = QShortcut(QKeySequence('Ctrl+Q'), self)
		self.quit_shortcut.activated.connect(self.close)
		self.looper = Looper()
		QTimer.singleShot(0, self.layout_complete)

	# -----------------------------------------------------------------
	# Setup functions:

	@pyqtSlot()
	def layout_complete(self):
		self.looper.add_loop(Loop(1))

	@pyqtSlot(bool)
	def play_toggle(self, state):
		if state:
			self.looper.play()
		else:
			self.looper.stop()

	def closeEvent(self, event):
		logging.debug('MainWindow close()')
		self.looper.stop()
		event.accept()

	def system_signal(self, sig, frame):
		logging.debug("Caught signal - shutting down")
		self.close()



# -----------------------------------------------------------------
# main()

if __name__ == "__main__":
	import sys, os, logging, json, glob, argparse
	from functools import partial
	from PyQt5.QtCore import Qt
	from PyQt5.QtCore import QTimer
	from PyQt5.QtWidgets import QFileDialog
	from PyQt5.QtGui import QKeySequence
	from PyQt5.QtWidgets import QLabel
	from PyQt5.QtWidgets import QPushButton
	from PyQt5.QtWidgets import QMainWindow
	from PyQt5.QtWidgets import QWidget
	from PyQt5.QtWidgets import QFrame
	from PyQt5.QtWidgets import QVBoxLayout
	from PyQt5.QtWidgets import QHBoxLayout
	from PyQt5.QtWidgets import QApplication
	from PyQt5.QtWidgets import QShortcut
	from PyQt5.QtWidgets import QGroupBox
	from PyQt5.QtWidgets import QRadioButton

	p = argparse.ArgumentParser()
	p.epilog = """
	Write your help text!
	"""
	p.add_argument('Filename', type=str, nargs='*', help='SFZ file[s] to include at startup')
	p.add_argument("--verbose", "-v", action="store_true", help="Show more detailed debug information")
	options = p.parse_args()

	#log_level = logging.DEBUG if options.verbose else logging.ERROR
	log_level = logging.DEBUG
	log_format = "[%(filename)24s:%(lineno)4d] %(levelname)-8s %(message)s"
	logging.basicConfig(
		level= log_level,
		format=log_format
	)

	try:
		del os.environ['SESSION_MANAGER']
	except KeyError:
		pass
	app = QApplication([])
	main_window = LooperTestWindow(options)
	main_window.show()
	sys.exit(app.exec())


#  end kitbash/gui.py
