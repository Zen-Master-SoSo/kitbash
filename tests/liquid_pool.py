#  kitbash/tests/liquid_pool.py
#
#  Copyright 2025 liyang <liyang@veronica>
#
"""
Test used for confirming that instances of LiquidSFZ have their ports
identified correctly.
"""
import logging
from collections import deque
from conn_jack import JackConnectionManager, JackConnectError
from kitbash.gui.main_window import JackLiquidSFZ


class LiquidPool():
	"""
	The purpose of this class is to allow for loading and registration of LiquidSFZ
	instances to happen in such a way that the instance is always associated with
	the correct object (MainWindow or DrumkitWidget)

	The main window and each drumkit_widget each get their own instance of a
	LiquidSFZ. These are constructed in the following sequence:

	1.	The object (MainWindow, DrumkitWidget) is pushed onto the queue
	2.	Their LiquizSFZ synth is instantiated.
	3.	When the connection manager registers a JACK client named "liquidsfz(-NN)",
		the client name is associated with the first object in the queue.
	4.	If the LiquidSFZ client has all of its ports registered, its'
		associated object is popped off of the queue.
	5.	If the queue is not empty, another LiquidSFZ instance is constructed,
		and steps 3 & 4 above are repeated.

	"""

	def __init__(self):
		self.conn_man = JackConnectionManager('liquid-pool')
		self.conn_man.on_client_registration(self.on_client_registration)
		self.conn_man.on_port_registration(self.on_port_registration)
		self.queue = deque()
		self.new_synth = None

	def instantiate_synth(self, associated_object):
		self.queue.append(associated_object)
		if self.new_synth is None:
			self.start_new_synth()

	def start_new_synth(self):
		self.new_synth = JackLiquidSFZ(self.queue[0].filename)
		self.new_synth.start()

	def on_client_registration(self, client_name, action):
		if action and self.new_synth and 'liquidsfz' in client_name:
			self.new_synth.client_name = client_name

	def on_port_registration(self, port, action):
		if action and self.new_synth and self.new_synth.client_name in port.name:
			if port.is_input and port.is_midi:
				self.new_synth.input_port = port
			elif port.is_output and port.is_audio:
				self.new_synth.output_ports.append(port)
			else:
				logging.warning('Incorrect port type: %s', port)
			if self.new_synth.input_port and len(self.new_synth.output_ports) == 2:
				logging.debug('%s ports complete', self.new_synth.client_name)
				associated_object = self.queue.popleft()
				associated_object.synth = self.new_synth
				if len(self.queue):
					self.start_new_synth()
				else:
					self.new_synth = None


class FakeTarget():
	"""
	Emulates a DrumkitWidget
	"""

	ordinal = 0

	def __init__(self):
		self.filename = None
		self.moniker = f'fake-target-{FakeTarget.ordinal:02d}'
		FakeTarget.ordinal += 1
		self.synth = None

	def __str__(self):
		return self.moniker


if __name__ == "__main__":
	import sys

	logging.basicConfig(
		level = logging.DEBUG,
		format = "[%(filename)24s:%(lineno)4d] %(levelname)-8s %(message)s"
	)

	try:
		pool = LiquidPool()
	except JackConnectError:
		print('\nCould not connect to JACK server. Is it running?')
		sys.exit(1)

	targets = [ FakeTarget() for i in range(16) ]
	for target in targets:
		pool.instantiate_synth(target)

	while any(target.synth is None for target in targets):
		print('Waiting for synth instantiation ...')

	sys.exit(0)


#  end kitbash/tests/liquid_pool.py
