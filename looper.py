#  kitbash/looper.py
#
#  Copyright 2024 liyang <liyang@veronica>
#
import logging
import numpy as np
from math import ceil
from jack import Client, JackError, CallbackExit
from PyQt5.QtWidgets import QMainWindow
from kitbash.loops import Loop

DEFAULT_BEATS_PER_MINUTE = 120


class Looper:

	# state constants:
	INACTIVE	= 0
	PLAYING		= 1

	def __init__(self, client_name='looper', test=False):
		self._bpm = DEFAULT_BEATS_PER_MINUTE
		self.beats_per_measure = None
		self.beat = 0.0
		self.last_beat = 0.0
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

	def load_loop(self, loop_id):
		"""
		Loads a single loop, if not already loaded.
		Returns the loaded loop.
		Throws up if the loop's beats per measure does not
		match all the loaded loop's beats per measure.
		"""
		loop = self._loaded_loop(loop_id)
		if loop is None:
			loop = Loop(loop_id)
			if self.beats_per_measure is not None and \
				loop.beats_per_measure != self.beats_per_measure:
				raise Exception("beats_per_measure mismatch")
			with Pause(self):
				self.beats_per_measure = loop.beats_per_measure
				self.loops.append(loop)
				self.remeasure()
		return loop

	def load_loops(self, loop_ids):
		"""
		Loads multiple loops, if not already loaded.
		Returns a list of the loops loaded.
		Ignores any loop if its beats per measure does not
		match previous loaded loop's beats per measure,
		(including the first loop loaded by this function if
		no other loops are loaded)
		"""
		loops_to_load = set(loop_ids) ^ set(self.loaded_loop_ids())
		if loops_to_load:
			new_loops = [Loop(loop_id) for loop_id in loops_to_load]
			if self.beats_per_measure is None:
				self.beats_per_measure = new_loops[0].beats_per_measure
			valid_new_loops = [ loop for loop in new_loops \
								if loop.beats_per_measure == self.beats_per_measure ]
			if valid_new_loops:
				with Pause(self):
					self.loops.extend(valid_new_loops)
					self.remeasure()
				return valid_new_loops
		return []

	def remeasure(self):
		if self.loops:
			last_beat = max([loop.last_beat for loop in self.loops])
			self.last_beat = float(ceil(last_beat / self.beats_per_measure) * self.beats_per_measure)
			if self.beat > self.last_beat:
				self.beat = 0.0
		else:
			self.beat = 0.0
			self.last_beat = 0.0

	def _loaded_loop(self, loop_id):
		for loop in self.loops:
			if loop.loop_id == loop_id:
				return loop
		return None

	def loaded_loop_ids(self):
		return [loop.loop_id for loop in self.loops]

	def clear(self):
		self.stop()
		self.loops = []
		self.beats_per_measure = None

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
		if len(self.loops):
			self.out_port.clear_buffer()
			end_beat = self.beat + self.beats_per_process
			while True:
				events_this_block = np.hstack([loop.events_between(self.beat, end_beat) \
					for loop in self.loops if loop.play])
				if len(events_this_block):
					for evt in np.sort(events_this_block, kind="heapsort", order="beat"):
						offset = int((evt['beat'] - self.beat) * self.samples_per_beat)
						self.out_port.write_midi_event(offset, evt['msg'])
				if end_beat < self.end_beat:
					self.beat = end_beat
					break
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
			logging.error('{} "{}"'.format(type(e).__name__, e))
			raise CallbackExit

	def shutdown_callback(self, status, reason):
		"""
		The argument status is of type jack.Status.
		"""
		logging.debug('JACK Shutdown')
		if self.state != Looper.INACTIVE:
			raise JackShutdownError

	def xrun_callback(self, delayed_usecs):
		"""
		The callback argument is the delay in microseconds due to the most recent XRUN
		occurrence. The callback is supposed to raise CallbackExit on error.
		"""
		logging.debug(f'xrun: delayed {delayed_usecs:.2f} microseconds')
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

	def __init__(self):
		super().__init__()
		from kitbash.looper_widget import LooperWidget
		from PyQt5.QtWidgets import QShortcut
		from PyQt5.QtGui import QKeySequence
		self.setWindowTitle('Looper')
		self.looper_widget = LooperWidget(self)
		self.setCentralWidget(self.looper_widget)
		self.quit_shortcut = QShortcut(QKeySequence('Ctrl+Q'), self)
		self.quit_shortcut.activated.connect(self.close)

	def closeEvent(self, event):
		self.looper_widget.looper.stop()
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
	import sys, os, argparse
	from PyQt5.QtWidgets import QApplication
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
		main_window = LooperTestWindow()
	except JackError:
		DevilBox('Could not connect to JACK server. Is it running?')
		sys.exit(1)
	main_window.show()
	sys.exit(app.exec())


#  end kitbash/gui.py
