#  kitbash/looper.py
#
#  Copyright 2024 liyang <liyang@veronica>
#
import logging
import numpy as np
from math import ceil
from jack import Client, JackError, CallbackExit
from PyQt5.QtCore import pyqtSlot
from PyQt5.QtWidgets import QMainWindow
from kitbash.loops import Loop, Loops, EVENT_STRUCT

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

	def add_loop(self, loop):
		if self.loaded_loop(loop.loop_id):
			return
		with Pause(self):
			if self.beats_per_measure is None:
				self.beats_per_measure = loop.beats_per_measure
			elif loop.beats_per_measure != self.beats_per_measure:
				raise Exception("beats_per_measure mismatch")
			self.loops.append(loop)
			last_beat = max([loop.last_beat for loop in self.loops])
			self.end_beat = float(ceil(last_beat / self.beats_per_measure) * self.beats_per_measure)

	def loaded_loop(self, loop_id):
		for loop in self.loops:
			if loop.loop_id == loop_id:
				return loop

	def clear(self):
		self.stop()
		self.loops = []

	def rescale(self):
		beats_per_second = self._bpm / 60
		self.samples_per_beat = self.client.samplerate / beats_per_second
		seconds_per_process = self.client.blocksize / self.client.samplerate
		self.beats_per_process = beats_per_second * seconds_per_process

	def stop(self):
		if self.state == Looper.INACTIVE:
			return
		logging.debug('STOP')
		self.__real_process_callback = self.null_process_callback
		self.state = Looper.INACTIVE

	def play(self):
		if self.state == Looper.PLAYING:
			return
		logging.debug('PLAY')
		self.__real_process_callback = self.play_process_callback
		self.state = Looper.PLAYING

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

	COLUMNS = 4

	def __init__(self, options):
		super().__init__()
		self._options = options
		self.setWindowTitle('Looper')

		window_frame = QFrame()
		main_layout = QVBoxLayout()

		group_layout = QHBoxLayout()
		group_layout.setSpacing(6)
		lbl = QLabel('Group:')
		lbl.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
		group_layout.addWidget(lbl)
		self.cmb_group = QComboBox(self)
		self.cmb_group.addItem('')
		self.cmb_group.addItems(Loops.groups())
		self.cmb_group.currentTextChanged.connect(self.group_changed)
		group_layout.addWidget(self.cmb_group)
		main_layout.addItem(group_layout)

		self.frm_loops = QFrame()
		loops_layout = QGridLayout()
		loops_layout.setContentsMargins(2,2,2,2)
		loops_layout.setSpacing(2)
		self.frm_loops.setLayout(loops_layout)
		main_layout.addWidget(self.frm_loops)

		beat_layout = QHBoxLayout()
		beat_layout.addSpacing(10)

		lbl = QLabel('BPM:')
		lbl.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
		beat_layout.addWidget(lbl)

		self.beat_spinner = QSpinBox(self)
		self.beat_spinner.setMinimum(30)
		self.beat_spinner.setMaximum(280)
		self.beat_spinner.setValue(DEFAULT_BEATS_PER_MINUTE)
		self.beat_spinner.valueChanged.connect(self.set_bpm)
		self.beat_spinner.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
		beat_layout.addWidget(self.beat_spinner)

		self.beat_label = QLabel('0')
		font = self.beat_label.font()
		font.setPixelSize(32)
		self.beat_label.setFont(font)
		self.beat_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
		beat_layout.addWidget(self.beat_label)

		beat_layout.addSpacing(10)
		main_layout.addItem(beat_layout)

		self.play_button = QPushButton(self)
		self.play_button.setText('PLAY')
		self.play_button.setCheckable(True)
		#self.play_button.setEnabled(False)
		self.play_button.toggled.connect(self.play_toggle)
		font = self.play_button.font()
		font.setPixelSize(22)
		self.play_button.setFont(font)
		main_layout.addWidget(self.play_button)

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

	@pyqtSlot()
	def slot_timer_timeout(self):
		self.beat_label.setText("%.1f" % (self.looper.beat + 1.0))

	@pyqtSlot(str)
	def group_changed(self, text):
		self.looper.stop()
		self.looper.clear()
		for button in self.frm_loops.findChildren(QPushButton):
			self.frm_loops.removeChild(button)
			button.deleteLater()
		if text == '':
			return
		ord_ = 0
		for tup in Loops.group_loops(text):
			button = QPushButton(tup[1], self.frm_loops)
			button.setCheckable(True)
			button.loop_id = tup[0]
			button.toggled.connect(partial(self.loop_select, tup[0]))
			self.frm_loops.layout().addWidget(button, int(ord_ / self.COLUMNS), ord_ % self.COLUMNS)
			ord_ += 1

	@pyqtSlot(int, bool)
	def loop_select(self, loop_id, state):
		if state:
			for button in self.frm_loops.findChildren(QPushButton):
				if button.loop_id != loop_id:
					button.setChecked(False)
			loop = self.looper.loaded_loop(loop_id)
			if loop is None:
				loop = Loop(loop_id)
				self.looper.add_loop(loop)
			loop.active = True
		else:
			self.looper.loaded_loop(loop_id).active = False

	@pyqtSlot(bool)
	def play_toggle(self, state):
		if state:
			self.update_timer.start()
			self.looper.play()
		else:
			self.update_timer.stop()
			self.looper.stop()

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
	from PyQt5.QtGui import QKeySequence
	from PyQt5.QtWidgets import QApplication
	from PyQt5.QtWidgets import QShortcut
	from PyQt5.QtWidgets import QLabel
	from PyQt5.QtWidgets import QPushButton
	from PyQt5.QtWidgets import QFrame
	from PyQt5.QtWidgets import QComboBox
	from PyQt5.QtWidgets import QSpinBox
	from PyQt5.QtWidgets import QVBoxLayout
	from PyQt5.QtWidgets import QHBoxLayout
	from PyQt5.QtWidgets import QGridLayout
	from PyQt5.QtWidgets import QSizePolicy
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
