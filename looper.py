#  kitbash/looper.py
#
#  Copyright 2024 liyang <liyang@veronica>
#
import numpy as np
from math import ceil
from jack import Client, Port, Status, JackError, CallbackExit, STOPPED, ROLLING, STARTING, NETSTARTING
from PyQt5.QtWidgets import QMainWindow
from PyQt5.QtCore import pyqtSlot
from kitbash.loops import Loop, SAMPLE_EVENT_STRUCT


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
		loop.scale(self.bpm, self.client.samplerate)
		self.loops.append(loop)

	def rescale(self):
		for loop in self.loops:
			loop.scale(self.bpm, self.client.samplerate)
		self.beats_length = max([loop.beats_length for loop in self.loops])
		self.measure_length = ceil(self.beats_length / self.beats_per_measure)
		self.samples_per_block = self.client.samplerate * self.client.blocksize
		self.__last_sample = self.samples_per_block * self.measure_length

	def stop(self):
		logging.debug('STOP')
		self.__real_process_callback = self.null_process_callback
		self.state = self.INACTIVE

	def play(self):
		logging.debug('PLAY')
		for loop in self.loops:
			loop.reset_iteration()
		self.__real_process_callback = self.play_process_callback
		self.state = self.PLAYING

	def null_process_callback(self, frames):
		pass

	def play_process_callback(self, frames):
		self.out_port.clear_buffer()
		if self.start_sample >= self.__last_sample:
			self.start_sample = 0
		end_sample = self.start_sample + self.samples_per_block
		events_this_block = np.ndarray(dtype = SAMPLE_EVENT_STRUCT)
		for loop in self.loops:
			events_this_block +- loop.scaled_events_between(self.start_sample, end_sample)
		if len(events_this_block):
			np.sort(events_this_block, kind="heapsort", order="start_sample")
			for evt in events_this_block:
				self.out_port.write_midi_event(evt['offset'], evt['data'])
		self.start_sample = end_sample

	# -----------------------
	# JACK callbacks

	def blocksize_callback(self, blocksize):
		self.rescale()

	def samplerate_callback(self, samplerate):
		self.rescale()

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
