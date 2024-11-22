#  kitbash/looper.py
#
#  Copyright 2024 liyang <liyang@veronica>
#
import logging
import numpy as np
from math import ceil
from jack import Client, Port, Status, JackError, CallbackExit, STOPPED, ROLLING, STARTING, NETSTARTING
from PyQt5.QtCore import pyqtSlot
from PyQt5.QtWidgets import QMainWindow
from kitbash.loops import Loop, EVENT_STRUCT

DEFAULT_BEATS_PER_MINUTE = 120


class Looper:

	# state constants:
	INACTIVE	= 0
	PLAYING		= 1

	def __init__(self, client_name='looper', test=False):
		self._bpm = DEFAULT_BEATS_PER_MINUTE
		self.beats_per_measure = None
		self.beat = 0.0
		self.loops = []
		self.state = Looper.INACTIVE
		self.__real_process_callback = self.null_process_callback
		self.client_name = client_name
		if test:
			self.client = FakeClient()
			self.out_port = FakePort()
			self.rescale()
		else:
			self.client = Client(self.client_name, no_start_server=True)
			self.client.set_blocksize_callback(self.blocksize_callback)
			self.client.set_samplerate_callback(self.samplerate_callback)
			self.client.set_process_callback(self.process_callback)
			self.client.set_shutdown_callback(self.shutdown_callback)
			self.client.set_xrun_callback(self.xrun_callback)
			self.client.activate()
			self.client.get_ports()
			self.out_port = self.client.midi_outports.register('out')

	@property
	def bpm(self):
		"""
		Play position offset, i.e.
			If offset is 4, all notes are played 4 beats late
		"""
		return self._bpm

	@bpm.setter
	def bpm(self, val):
		self._bpm = val
		self.rescale()

	def add_loop(self, loop, starting_beat=0):
		with Pause(self):
			if self.beats_per_measure is None:
				self.beats_per_measure = loop.beats_per_measure
			elif loop.beats_per_measure != self.beats_per_measure:
				raise Exception("beats_per_measure mismatch")
			self.loops.append(loop)
			last_beat = max([loop.last_beat for loop in self.loops])
			self.end_beat = float(ceil(last_beat / self.beats_per_measure) * self.beats_per_measure)

	def clear_loops(self):
		with Pause(self):
			self.loops = []

	def rescale(self):
		beats_per_second = self._bpm / 60
		self.samples_per_beat = self.client.samplerate / beats_per_second
		seconds_per_process = self.client.blocksize / self.client.samplerate
		self.beats_per_process = beats_per_second * seconds_per_process

	def stop(self):
		logging.debug('STOP')
		self.__real_process_callback = self.null_process_callback
		self.state = Looper.INACTIVE

	def play(self):
		logging.debug('PLAY')
		self.__real_process_callback = self.play_process_callback
		self.state = Looper.PLAYING

	def rewind(self):
		logging.debug('REWIND')
		for loop in self.loops:
			loop.reset_iteration()
		self.beat = 0.0

	def null_process_callback(self, frames):
		pass

	def play_process_callback(self, frames):
		self.out_port.clear_buffer()
		end_beat = self.beat + self.beats_per_process
		while True:
			if len(self.loops):
				events_this_block = np.hstack([
					loop.events_between(self.beat, end_beat) for loop in self.loops
				])
				if len(events_this_block):
					np.sort(events_this_block, kind="heapsort", order="beat")
					for evt in events_this_block:
						offset = int((evt['beat'] - self.beat) * self.samples_per_beat)
						if offset < 0:
							logging.warn('negative offset')
						elif offset < self.client.blocksize:
							self.out_port.write_midi_event(offset, evt['msg'])
			if end_beat < self.end_beat:
				self.beat = end_beat
				return
			end_beat -= self.end_beat
			self.beat = 0.0

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
		if self.state != Looper.INACTIVE:
			self.stop_everything()
			raise JackShutdownError

	def xrun_callback(self, delayed_usecs):
		"""
		The callback argument is the delay in microseconds due to the most recent XRUN
		occurrence. The callback is supposed to raise CallbackExit on error.
		"""
		logging.debug('xrun: delayed %.2f microseconds' % delayed_usecs)
		pass


class JackShutdownError(Exception):

	pass


class FakeClient:

	samplerate = 48000
	blocksize = 1024


class FakePort:

	rc = 0

	def clear_buffer(self):
		pass

	def write_midi_event(self, offset, tup):
		print('MIDI EVENT: {:7d}  0x{:x}  {:d}  {:d}'.format(offset, tup[0], tup[1], tup[2]))
		self.rc += 1


class LooperTestWindow(QMainWindow):

	def __init__(self, options):
		super().__init__()
		self._options = options
		self.setWindowTitle('Looper')

		window_frame = QFrame()
		main_layout = QVBoxLayout()
		beat_layout = QHBoxLayout()

		self.group_label = QLabel('group')
		main_layout.addWidget(self.group_label)

		self.loop_label = QLabel('loop')
		main_layout.addWidget(self.loop_label)

		spinner_label = QLabel('BPM:')
		beat_layout.addWidget(spinner_label)

		self.beat_spinner = QSpinBox(self)
		self.beat_spinner.setMinimum(30)
		self.beat_spinner.setMaximum(280)
		self.beat_spinner.setValue(DEFAULT_BEATS_PER_MINUTE)
		self.beat_spinner.valueChanged.connect(self.set_bpm)
		beat_layout.addWidget(self.beat_spinner)

		self.beat_label = QLabel('beat')
		font = self.beat_label.font()
		font.setPixelSize(32)
		self.beat_label.setFont(font)
		beat_layout.addWidget(self.beat_label)

		main_layout.addItem(beat_layout)

		self.play_button = QPushButton(self)
		self.play_button.setText('PLAY')
		self.play_button.setCheckable(True)
		self.play_button.setEnabled(False)
		self.play_button.toggled.connect(self.play_toggle)
		font = self.play_button.font()
		font.setPixelSize(22)
		self.play_button.setFont(font)
		main_layout.addWidget(self.play_button)

		self.shuffle_button = QPushButton(self)
		self.shuffle_button.setText('Shuffle')
		self.shuffle_button.clicked.connect(self.shuffle)
		main_layout.addWidget(self.shuffle_button)

		window_frame.setLayout(main_layout)
		for label in window_frame.findChildren(QLabel):
			label.setAlignment(Qt.AlignCenter)
		self.setCentralWidget(window_frame)

		self.quit_shortcut = QShortcut(QKeySequence('Ctrl+Q'), self)
		self.quit_shortcut.activated.connect(self.close)

		self.looper = Looper()
		self.update_timer = QTimer()
		self.update_timer.setInterval(int(1 / 8 * 1000))
		self.update_timer.timeout.connect(self.slot_timer_timeout)
		QTimer.singleShot(0, self.layout_complete)

	@pyqtSlot()
	def slot_timer_timeout(self):
		self.beat_label.setText("%.1f" % (self.looper.beat + 1.0))

	@pyqtSlot()
	def layout_complete(self):
		self.shuffle()
		self.update_timer.start()

	@pyqtSlot(bool)
	def play_toggle(self, state):
		if state:
			self.looper.play()
		else:
			self.looper.stop()

	@pyqtSlot()
	def shuffle(self):
		with Pause(self.looper):
			self.looper.clear_loops()
			try:
				loop = Loop.random()
			except IndexError:
				DevilBox('Failed choosing a random loop')
			else:
				self.looper.add_loop(loop)
				self.group_label.setText(loop.loop_group)
				self.loop_label.setText(loop.name)
				self.play_button.setEnabled(True)

	@pyqtSlot(int)
	def set_bpm(self, bpm):
		self.looper.bpm = bpm

	def closeEvent(self, event):
		self.looper.stop()
		event.accept()

	def system_signal(self, sig, frame):
		logging.debug("Caught signal - shutting down")
		self.close()


class Pause:
	"""
	A context manager that remembers what state a Looper is in,
	stops it, lets you do work, and then restarts it if it had
	been running.
	"""

	def __init__(self, looper):
		self.looper = looper
		self.previous_state = looper.state

	def __enter__(self):
		self.looper.stop()

	def __exit__(self, *_):
		if self.previous_state == Looper.PLAYING:
			self.looper.play()



if __name__ == "__main__":
	import sys, os, json, glob, argparse
	from functools import partial
	from PyQt5.QtCore import Qt
	from PyQt5.QtCore import QTimer
	from PyQt5.QtWidgets import QFileDialog
	from PyQt5.QtGui import QKeySequence
	from PyQt5.QtWidgets import QLabel
	from PyQt5.QtWidgets import QPushButton
	from PyQt5.QtWidgets import QWidget
	from PyQt5.QtWidgets import QFrame
	from PyQt5.QtWidgets import QSpinBox
	from PyQt5.QtWidgets import QVBoxLayout
	from PyQt5.QtWidgets import QHBoxLayout
	from PyQt5.QtWidgets import QApplication
	from PyQt5.QtWidgets import QShortcut
	from PyQt5.QtWidgets import QGroupBox
	from PyQt5.QtWidgets import QRadioButton
	from qt_extras import DevilBox

	p = argparse.ArgumentParser()
	p.epilog = """
	Write your help text!
	"""
	p.add_argument('Filename', type=str, nargs='*', help='SFZ file[s] to include at startup')
	p.add_argument("--verbose", "-v", action="store_true", help="Show more detailed debug information")
	options = p.parse_args()

	log_level = logging.DEBUG if options.verbose else logging.ERROR
	log_format = "[%(filename)24s:%(lineno)4d] %(levelname)-8s %(message)s"
	logging.basicConfig(level = log_level, format = log_format)

	try:
		del os.environ['SESSION_MANAGER']
	except KeyError:
		pass
	app = QApplication([])
	try:
		main_window = LooperTestWindow(options)
	except JackError:
		DevilBox('Could not connect to JACK server. Is it running?')
		sys.exit(1)
	main_window.show()
	sys.exit(app.exec())


#  end kitbash/gui.py
